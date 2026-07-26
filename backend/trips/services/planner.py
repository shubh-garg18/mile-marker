"""Orchestration: route in, plan out.

The only module that knows the shape of the whole job. Geocode the three places,
route between them, turn the route into planned work, hand that to the engine,
then dress the resulting timeline as the API contract. It holds no regulatory
logic; every hours-of-service decision belongs to `trips.domain`.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, time, timedelta
from decimal import Decimal
from time import monotonic
from zoneinfo import ZoneInfo

from django.conf import settings

from trips.domain.constants import (
    CYCLE_LIMIT_MINUTES,
    DEFAULT_START_TIME,
    DROPOFF_MINUTES,
    PICKUP_MINUTES,
)
from trips.domain.hos import ceil_to_quantum, cycle_minutes_at_end, floor_to_quantum, simulate
from trips.domain.models import Activity, DutyEvent, DutyStatus, RodsDay
from trips.domain.rods import build_days, mile_marker_label
from trips.services import ors_client
from trips.services.errors import UpstreamError
from trips.services.geo import RoutePolyline
from trips.services.ors_client import GeocodedPlace, RouteGeometry

logger = logging.getLogger(__name__)

#: `DutyEvent.kind` -> the `stops[].type` vocabulary of the API contract.
STOP_TYPES: dict[str, str] = {
    "pickup": "pickup",
    "dropoff": "dropoff",
    "fuel": "fuel",
    "break": "break",
    "reset": "rest",
    "restart": "restart",
}

#: Reverse geocoding is cosmetic. Past this many lookups a trip falls back to mile
#: markers rather than spending more of the user's time on labels.
MAX_REVERSE_LOOKUPS = 16

#: A wall-clock ceiling on the same work. A request that overruns the web
#: server's timeout is a real failure, and gunicorn's default is 30 seconds, so
#: the sequential lookups stop well before the response is at risk.
REVERSE_LOOKUP_BUDGET_SECONDS = 8.0

#: Roughly 1.5 MB of JSON is the point at which the geometry is worth thinning
#: for display. A coordinate pair at five decimal places costs about 23 bytes, so
#: that is a little over 65,000 points; 40,000 keeps a margin while still sending
#: full road geometry for any real route. Thinning affects display only, since
#: distance was computed against the full-resolution polyline.
MAX_DISPLAY_POINTS = 40_000
COORDINATE_PRECISION = 5


def plan_trip(
    *,
    current_location: str,
    pickup_location: str,
    dropoff_location: str,
    current_cycle_used_hours: Decimal,
    start_datetime: datetime | None = None,
) -> dict:
    """Plan one trip. Returns the response payload documented in the README."""
    current = ors_client.geocode(current_location, field="current_location")
    pickup = ors_client.geocode(pickup_location, field="pickup_location")
    dropoff = ors_client.geocode(dropoff_location, field="dropoff_location")

    route = ors_client.directions([current.coord, pickup.coord, dropoff.coord])
    polyline = RoutePolyline(coords=route.coords, reported_miles=route.distance_miles)

    start = _resolve_start(start_datetime)
    cycle_used_minutes = int(current_cycle_used_hours * 60)

    events = simulate(
        _activities(route, current, pickup, dropoff),
        cycle_used_minutes=cycle_used_minutes,
        start_dt=start,
    )

    warnings: list[str] = []
    events = _with_locations(events, polyline, current, pickup, dropoff, warnings)
    days = build_days(events)

    return {
        "trip": _trip_summary(events, days, route, start, cycle_used_minutes),
        "waypoints": [
            _waypoint("current", current),
            _waypoint("pickup", pickup),
            _waypoint("dropoff", dropoff),
        ],
        "route": _route_payload(route, polyline),
        "stops": _stops(events, polyline, pickup, dropoff),
        "days": [_day_payload(day) for day in days],
        "log_header": settings.LOG_SHEET_HEADER,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# Route -> planned work
# --------------------------------------------------------------------------- #


def _activities(
    route: RouteGeometry,
    current: GeocodedPlace,
    pickup: GeocodedPlace,
    dropoff: GeocodedPlace,
) -> list[Activity]:
    """The four items of work a trip consists of."""
    if len(route.legs) != 2:
        raise UpstreamError(
            "The routing service returned a route we couldn't break into legs. Please try again."
        )

    to_pickup, to_dropoff = route.legs
    return [
        Activity(
            kind="drive",
            label=f"{current.label} → {pickup.label}",
            # Leg durations round up so driving time is never under-reported.
            minutes=ceil_to_quantum(to_pickup.duration_minutes),
            miles=to_pickup.distance_miles,
        ),
        Activity(kind="task", label="Loading", minutes=PICKUP_MINUTES, task_kind="pickup"),
        Activity(
            kind="drive",
            label=f"{pickup.label} → {dropoff.label}",
            minutes=ceil_to_quantum(to_dropoff.duration_minutes),
            miles=to_dropoff.distance_miles,
        ),
        Activity(kind="task", label="Unloading", minutes=DROPOFF_MINUTES, task_kind="dropoff"),
    ]


def _resolve_start(requested: datetime | None) -> datetime:
    """Departure time, snapped onto the 15-minute lattice the engine requires.

    Defaults to 08:00 tomorrow. Exposing the field is what makes a plan
    reproducible and therefore testable.
    """
    if requested is None:
        # The home terminal's calendar, not the server's. Render runs in UTC, and
        # between 18:00 and midnight Chicago time those are different days.
        # "Tomorrow" has to mean tomorrow to the driver.
        today = datetime.now(ZoneInfo(settings.HOME_TERMINAL_TIMEZONE)).date()
        return datetime.combine(today + timedelta(days=1), DEFAULT_START_TIME)

    naive = requested.replace(second=0, microsecond=0)
    minutes = floor_to_quantum(naive.hour * 60 + naive.minute)
    return datetime.combine(naive.date(), time.min) + timedelta(minutes=minutes)


# --------------------------------------------------------------------------- #
# Locating the timeline
# --------------------------------------------------------------------------- #


def _with_locations(
    events: list[DutyEvent],
    polyline: RoutePolyline,
    current: GeocodedPlace,
    pickup: GeocodedPlace,
    dropoff: GeocodedPlace,
    warnings: list[str],
) -> list[DutyEvent]:
    """Attach a place label to every event, for the remarks strip.

    The truck only moves while driving, so everything between two stops happened
    in the same place and a label needs resolving once per stop. That keeps a
    transcontinental trip to a dozen or so reverse-geocode calls instead of one
    per event, which matters for latency and for the free-tier quota.
    """
    located: list[DutyEvent] = []
    label = current.label
    lookups = 0
    started = monotonic()
    lookup_failed = False
    budget_spent = False

    for index, event in enumerate(events):
        if event.kind == "pickup":
            label = pickup.label
        elif event.kind == "dropoff":
            label = dropoff.label
        elif index > 0 and events[index - 1].status is DutyStatus.DRIVING:
            within_budget = (
                lookups < MAX_REVERSE_LOOKUPS
                and monotonic() - started < REVERSE_LOOKUP_BUDGET_SECONDS
            )
            resolved = None
            if within_budget:
                lookups += 1
                latitude, longitude = polyline.point_at_route_mile(event.at_mile or 0.0)
                resolved = ors_client.reverse_geocode(latitude, longitude)
                lookup_failed = lookup_failed or resolved is None
            else:
                budget_spent = True

            label = resolved or mile_marker_label(event.at_mile)

        located.append(replace(event, location=label))

    # The two causes get different copy. Telling a dispatcher the geocoder was
    # unavailable when we simply chose to stop asking sends them to investigate a
    # service that is working fine.
    if lookup_failed:
        warnings.append(
            "Some stop locations are shown as route mile markers because the place-name "
            "lookup was unavailable."
        )
    if budget_spent:
        warnings.append(
            "This trip has more stops than we look up place names for, so the later ones are "
            "shown as route mile markers."
        )
    return located


# --------------------------------------------------------------------------- #
# Payload assembly
# --------------------------------------------------------------------------- #


def _trip_summary(
    events: list[DutyEvent],
    days: list[RodsDay],
    route: RouteGeometry,
    start: datetime,
    cycle_used_minutes: int,
) -> dict:
    driving_minutes = sum(e.minutes for e in events if e.status is DutyStatus.DRIVING)
    on_duty_minutes = sum(e.minutes for e in events if e.counts_against_cycle)
    cycle_end_minutes = cycle_minutes_at_end(events, cycle_used_minutes)

    return {
        "start_datetime": start.isoformat(),
        "end_datetime": events[-1].end.isoformat(),
        "timezone": settings.HOME_TERMINAL_TIMEZONE,
        "total_distance_miles": round(route.distance_miles),
        "total_driving_hours": driving_minutes / 60,
        "total_on_duty_hours": on_duty_minutes / 60,
        "days_count": len(days),
        "cycle_used_start_hours": cycle_used_minutes / 60,
        "cycle_used_end_hours": cycle_end_minutes / 60,
        "cycle_remaining_hours": max(CYCLE_LIMIT_MINUTES - cycle_end_minutes, 0) / 60,
    }


def _waypoint(role: str, place: GeocodedPlace) -> dict:
    return {
        "role": role,
        "label": place.label,
        "resolved_name": place.resolved_name,
        "coord": [place.lat, place.lon],
    }


def _route_payload(route: RouteGeometry, polyline: RoutePolyline) -> dict:
    return {
        "geometry": _display_geometry(polyline),
        "bbox": list(polyline.bounds()),
        "legs": [
            {
                "from": origin,
                "to": destination,
                "distance_miles": round(leg.distance_miles),
                "driving_hours": round(leg.duration_minutes / 60, 2),
            }
            for leg, (origin, destination) in zip(
                route.legs, [("current", "pickup"), ("pickup", "dropoff")], strict=False
            )
        ],
    }


def _display_geometry(polyline: RoutePolyline) -> list[list[float]]:
    """Coordinates for drawing, rounded and thinned if the route is very long."""
    coords = polyline.coords
    if len(coords) > MAX_DISPLAY_POINTS:
        stride = len(coords) // MAX_DISPLAY_POINTS + 1
        thinned = coords[::stride]
        if thinned[-1] != coords[-1]:
            thinned.append(coords[-1])
        coords = thinned

    return [
        [round(lat, COORDINATE_PRECISION), round(lon, COORDINATE_PRECISION)] for lat, lon in coords
    ]


def _stops(
    events: list[DutyEvent],
    polyline: RoutePolyline,
    pickup: GeocodedPlace,
    dropoff: GeocodedPlace,
) -> list[dict]:
    """Every place the truck is stationary, in order, for the map and itinerary."""
    fixed_coords = {"pickup": [pickup.lat, pickup.lon], "dropoff": [dropoff.lat, dropoff.lon]}
    stops: list[dict] = []

    for event in events:
        stop_type = STOP_TYPES.get(event.kind)
        if stop_type is None:
            continue

        at_mile = event.at_mile or 0.0
        coord = fixed_coords.get(event.kind)
        if coord is None:
            latitude, longitude = polyline.point_at_route_mile(at_mile)
            coord = [round(latitude, COORDINATE_PRECISION), round(longitude, COORDINATE_PRECISION)]

        stops.append(
            {
                "seq": len(stops) + 1,
                "type": stop_type,
                "label": event.location,
                "coord": coord,
                "at_mile": round(at_mile),
                "arrive": event.start.isoformat(),
                "depart": event.end.isoformat(),
                "duration_hours": event.minutes / 60,
                "duty_status": event.status.value,
                "reason": event.note,
            }
        )

    return stops


def _day_payload(day: RodsDay) -> dict:
    return {
        "date": day.date,
        "day_number": day.day_number,
        "driving_miles": day.driving_miles,
        "segments": [
            {
                "status": segment.status.value,
                "start_minute": segment.start_minute,
                "end_minute": segment.end_minute,
                "kind": segment.kind,
                "miles": round(segment.miles, 1),
            }
            for segment in day.segments
        ],
        "totals": day.totals,
        "remarks": [
            {"minute": remark.minute, "location": remark.location, "note": remark.note}
            for remark in day.remarks
        ],
    }
