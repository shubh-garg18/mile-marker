"""End-to-end tests for the HTTP surface, with OpenRouteService stubbed.

The stub sits at `requests.request` rather than at the client module, so these
exercise the real parsing, the real error translation and the real planner,
everything except the network.
"""

from __future__ import annotations

import pytest
import requests
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework.throttling import AnonRateThrottle

from trips.services import ors_client

PLAN_URL = "/api/v1/trips/plan"
HEALTH_URL = "/api/v1/health"

PLACES = {
    "dallas, tx": (32.7767, -96.7970, "Dallas", "TX"),
    "oklahoma city, ok": (35.4676, -97.5164, "Oklahoma City", "OK"),
    "denver, co": (39.7392, -104.9903, "Denver", "CO"),
    "seattle, wa": (47.6062, -122.3321, "Seattle", "WA"),
}

VALID_REQUEST = {
    "current_location": "Dallas, TX",
    "pickup_location": "Oklahoma City, OK",
    "dropoff_location": "Denver, CO",
    "current_cycle_used_hours": 12.5,
    "start_datetime": "2026-07-27T08:00:00",
}


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: object = None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeOrs:
    """A believable OpenRouteService, driven entirely from memory."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.unknown_places: set[str] = set()
        self.reverse_label: str | None = "Amarillo, TX"
        # Dallas -> Oklahoma City -> Denver: 206 mi then 917 mi.
        self.leg_miles = [206.0, 917.0]
        self.leg_hours = [3.5, 14.5]
        self.directions_override: FakeResponse | None = None

    # -- wiring ---------------------------------------------------------- #

    def __call__(self, method: str, url: str, **kwargs):
        self.calls.append(url)
        if url == ors_client.GEOCODE_URL:
            return self._geocode(kwargs["params"]["text"])
        if url == ors_client.REVERSE_URL:
            return self._reverse()
        if url == ors_client.DIRECTIONS_URL:
            return self.directions_override or self._directions()
        raise AssertionError(f"unexpected ORS call to {url}")

    # -- endpoints ------------------------------------------------------- #

    def _geocode(self, text: str):
        key = " ".join(text.lower().split())
        if key in self.unknown_places or key not in PLACES:
            return FakeResponse(200, {"features": []})

        lat, lon, locality, region = PLACES[key]
        return FakeResponse(200, {"features": [_feature(lat, lon, locality, region)]})

    def _reverse(self):
        if self.reverse_label is None:
            return FakeResponse(200, {"features": []})
        locality, region = self.reverse_label.split(", ")
        return FakeResponse(200, {"features": [_feature(35.22, -101.83, locality, region)]})

    def _directions(self):
        total_meters = sum(self.leg_miles) * 1609.344
        total_seconds = sum(self.leg_hours) * 3600
        return FakeResponse(
            200,
            {
                "features": [
                    {
                        "geometry": {
                            "coordinates": [
                                [PLACES["dallas, tx"][1], PLACES["dallas, tx"][0]],
                                [PLACES["oklahoma city, ok"][1], PLACES["oklahoma city, ok"][0]],
                                [PLACES["denver, co"][1], PLACES["denver, co"][0]],
                            ]
                        },
                        "properties": {
                            "summary": {"distance": total_meters, "duration": total_seconds},
                            "segments": [
                                {"distance": miles * 1609.344, "duration": hours * 3600}
                                for miles, hours in zip(self.leg_miles, self.leg_hours, strict=True)
                            ],
                        },
                    }
                ]
            },
        )


def _feature(lat: float, lon: float, locality: str, region: str) -> dict:
    return {
        "geometry": {"coordinates": [lon, lat]},
        "properties": {
            "locality": locality,
            "region_a": region,
            "label": f"{locality}, {region}, United States",
        },
    }


@pytest.fixture(autouse=True)
def _isolated(settings, monkeypatch):
    settings.ORS_API_KEY = "test-key"
    cache.clear()
    monkeypatch.setattr(ors_client.time, "sleep", lambda _seconds: None)
    yield
    cache.clear()


@pytest.fixture
def ors(monkeypatch):
    fake = FakeOrs()
    monkeypatch.setattr(requests, "request", fake)
    return fake


@pytest.fixture
def client():
    return APIClient()


def plan(client, **overrides):
    return client.post(PLAN_URL, {**VALID_REQUEST, **overrides}, format="json")


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #


def test_health_returns_ok_without_touching_the_routing_service(client, ors):
    response = client.get(HEALTH_URL)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert ors.calls == []


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #


def test_a_valid_trip_returns_the_documented_payload(client, ors):
    response = plan(client)
    assert response.status_code == 200
    body = response.json()

    assert set(body) == {"trip", "waypoints", "route", "stops", "days", "log_header", "warnings"}

    trip = body["trip"]
    assert set(trip) == {
        "start_datetime",
        "end_datetime",
        "timezone",
        "total_distance_miles",
        "total_driving_hours",
        "total_on_duty_hours",
        "days_count",
        "cycle_used_start_hours",
        "cycle_used_end_hours",
        "cycle_remaining_hours",
    }
    assert trip["start_datetime"] == "2026-07-27T08:00:00"
    assert trip["total_distance_miles"] == 1123
    assert trip["cycle_used_start_hours"] == 12.5
    assert trip["days_count"] == len(body["days"])

    assert [point["role"] for point in body["waypoints"]] == ["current", "pickup", "dropoff"]
    assert body["waypoints"][0]["coord"] == [32.7767, -96.797]
    assert body["waypoints"][0]["label"] == "Dallas, TX"


def test_the_route_carries_geometry_bbox_and_two_legs(client, ors):
    route = plan(client).json()["route"]

    assert len(route["geometry"]) >= 2
    assert route["geometry"][0] == [32.7767, -96.797]
    assert len(route["bbox"]) == 4

    assert [(leg["from"], leg["to"]) for leg in route["legs"]] == [
        ("current", "pickup"),
        ("pickup", "dropoff"),
    ]
    assert route["legs"][0]["distance_miles"] == 206


def test_stops_are_ordered_and_typed(client, ors):
    stops = plan(client).json()["stops"]

    assert [stop["seq"] for stop in stops] == list(range(1, len(stops) + 1))
    assert {stop["type"] for stop in stops} <= {
        "pickup",
        "dropoff",
        "fuel",
        "break",
        "rest",
        "restart",
    }
    assert [stop["type"] for stop in stops].count("pickup") == 1
    assert [stop["type"] for stop in stops].count("dropoff") == 1

    for stop in stops:
        assert stop["label"]
        assert stop["reason"]
        assert len(stop["coord"]) == 2
        assert stop["arrive"] < stop["depart"]

    pickup = next(stop for stop in stops if stop["type"] == "pickup")
    assert pickup["coord"] == [35.4676, -97.5164], "a known waypoint is not interpolated"
    assert pickup["duration_hours"] == 1.0


def test_every_returned_day_totals_twenty_four_hours(client, ors):
    days = plan(client).json()["days"]

    assert days
    for index, day in enumerate(days, start=1):
        assert day["day_number"] == index
        assert day["totals"]["total"] == 24.0
        assert day["segments"][0]["start_minute"] == 0
        assert day["segments"][-1]["end_minute"] == 1440
        assert all(remark["location"] for remark in day["remarks"])


def test_the_trip_summary_arithmetic_is_exact(client, ors):
    """Value assertions, not just key presence.

    The stub route is 206 mi in 3.5 h then 917 mi in 14.5 h, departing 08:00 with
    12.5 cycle hours spent. Every figure below is derivable by hand, which is the
    point. A key-presence check would pass just as happily with driving and
    on-duty hours swapped, or the end time read off the wrong event.
    """
    body = plan(client).json()
    trip = body["trip"]

    driving = sum(
        segment["end_minute"] - segment["start_minute"]
        for day in body["days"]
        for segment in day["segments"]
        if segment["status"] == "driving"
    )
    on_duty = driving + sum(
        segment["end_minute"] - segment["start_minute"]
        for day in body["days"]
        for segment in day["segments"]
        if segment["status"] == "on_duty_not_driving"
    )

    assert trip["total_driving_hours"] == driving / 60 == 18.0
    assert trip["total_on_duty_hours"] == on_duty / 60 == 20.5
    assert trip["cycle_used_end_hours"] == 12.5 + 20.5
    assert trip["cycle_remaining_hours"] == 70 - trip["cycle_used_end_hours"]
    assert trip["end_datetime"] > trip["start_datetime"]
    assert trip["end_datetime"] == "2026-07-28T14:30:00"
    assert body["warnings"] == []


def test_cycle_remaining_never_goes_negative(client, ors):
    ors.leg_miles, ors.leg_hours = [900.0, 1400.0], [15.0, 23.0]

    trip = plan(client, current_cycle_used_hours=69).json()["trip"]

    assert trip["cycle_remaining_hours"] >= 0


def test_leg_durations_round_up_to_the_quarter_hour(client, ors):
    """Cycle hours round up, which is the safe direction. The
    default fixture's legs are already lattice-aligned, so nothing defended it."""
    ors.leg_hours = [3.6, 14.2]  # 216 and 852 minutes -> 225 and 855

    body = plan(client, current_cycle_used_hours=0).json()
    driving = sum(
        segment["end_minute"] - segment["start_minute"]
        for day in body["days"]
        for segment in day["segments"]
        if segment["status"] == "driving"
    )

    assert driving == 225 + 855


def test_the_pickup_leg_is_driven_before_the_dropoff_leg(client, ors):
    """Swapping them still yields a plausible-looking plan with the wrong mileage
    everywhere, so the order needs asserting directly."""
    stops = plan(client, current_cycle_used_hours=0).json()["stops"]

    pickup_stop = next(stop for stop in stops if stop["type"] == "pickup")
    assert pickup_stop["at_mile"] == 206


def test_the_log_header_placeholders_are_returned_once(client, ors):
    header = plan(client).json()["log_header"]

    assert header["driver_name"]
    assert header["carrier_name"]
    assert header["tractor_number"]


# --------------------------------------------------------------------------- #
# Acceptance criteria from the brief
# --------------------------------------------------------------------------- #


def test_a_short_trip_renders_one_sheet(client, ors):
    ors.leg_miles = [60.0, 120.0]
    ors.leg_hours = [1.0, 2.0]

    body = plan(client, current_cycle_used_hours=0).json()

    assert body["trip"]["days_count"] == 1
    assert body["days"][0]["totals"]["total"] == 24.0
    assert not any(stop["type"] in {"rest", "restart"} for stop in body["stops"])


def test_a_long_trip_renders_three_or_more_sheets_with_rests_and_fuel(client, ors):
    ors.leg_miles = [900.0, 1400.0]
    ors.leg_hours = [15.0, 23.0]

    body = plan(client, current_cycle_used_hours=0).json()

    assert body["trip"]["days_count"] >= 3
    assert all(day["totals"]["total"] == 24.0 for day in body["days"])
    assert sum(day["driving_miles"] for day in body["days"]) >= 2200

    types = [stop["type"] for stop in body["stops"]]
    assert types.count("rest") >= 2
    assert types.count("fuel") >= 2, "2,300 miles needs fuel at 1,000 and 2,000"


def test_a_fuel_stop_appears_at_least_once_per_thousand_miles(client, ors):
    ors.leg_miles = [500.0, 1800.0]
    ors.leg_hours = [8.0, 29.0]

    stops = plan(client, current_cycle_used_hours=0).json()["stops"]
    fuel_miles = [0] + [stop["at_mile"] for stop in stops if stop["type"] == "fuel"]

    assert len(fuel_miles) - 1 == 2
    for before, after in zip(fuel_miles, fuel_miles[1:], strict=False):
        assert after - before <= 1000


def test_an_almost_exhausted_cycle_forces_a_thirty_four_hour_restart(client, ors):
    body = plan(client, current_cycle_used_hours=68).json()

    restarts = [stop for stop in body["stops"] if stop["type"] == "restart"]
    assert len(restarts) == 1
    assert restarts[0]["duration_hours"] == 34.0
    assert body["trip"]["cycle_used_end_hours"] < 68


def test_cycle_hours_are_snapped_up_to_the_quarter_hour(client, ors):
    body = plan(client, current_cycle_used_hours=12.3).json()

    assert body["trip"]["cycle_used_start_hours"] == 12.5


def test_an_omitted_start_datetime_defaults_to_eight_in_the_morning(client, ors):
    body = plan(client, start_datetime=None).json()

    assert body["trip"]["start_datetime"].endswith("T08:00:00")


def test_a_start_time_off_the_lattice_is_snapped_down(client, ors):
    body = plan(client, start_datetime="2026-07-27T08:07:00").json()

    assert body["trip"]["start_datetime"] == "2026-07-27T08:00:00"


# --------------------------------------------------------------------------- #
# Every error code is reachable, in its documented shape
# --------------------------------------------------------------------------- #


def assert_error(response, *, code: str, status: int, field: str | None = None):
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "field"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    assert body["error"]["message"][0].isupper(), "error copy is a sentence, not a code"
    if field is not None:
        assert body["error"]["field"] == field


def test_a_missing_location_is_a_validation_error_naming_the_field(client, ors):
    response = client.post(PLAN_URL, {**VALID_REQUEST, "pickup_location": "  "}, format="json")
    assert_error(response, code="VALIDATION_ERROR", status=400, field="pickup_location")


def test_cycle_hours_above_seventy_are_rejected_naming_the_field(client, ors):
    response = plan(client, current_cycle_used_hours=71)
    assert_error(response, code="VALIDATION_ERROR", status=400, field="current_cycle_used_hours")
    assert "70" in response.json()["error"]["message"]


def test_cycle_hours_below_zero_are_rejected(client, ors):
    assert_error(
        plan(client, current_cycle_used_hours=-1),
        code="VALIDATION_ERROR",
        status=400,
        field="current_cycle_used_hours",
    )


def test_an_unrecognisable_place_names_the_offending_field(client, ors):
    ors.unknown_places.add("dalas tx")

    response = plan(client, current_location="Dalas TX")
    assert_error(response, code="GEOCODE_NOT_FOUND", status=422, field="current_location")
    assert "Dalas TX" in response.json()["error"]["message"]


def test_an_unroutable_pair_is_a_route_not_found(client, ors):
    ors.directions_override = FakeResponse(404, {"error": {"code": 2009, "message": "no route"}})

    assert_error(plan(client), code="ROUTE_NOT_FOUND", status=422)


def test_a_route_past_the_profile_cap_is_rejected(client, ors):
    ors.leg_miles = [3000.0, 1500.0]  # 4,500 mi > the 6,000 km cap
    ors.leg_hours = [50.0, 25.0]

    assert_error(plan(client), code="ROUTE_TOO_LONG", status=422)


def test_a_rate_limited_upstream_is_a_service_unavailable(client, ors):
    ors.directions_override = FakeResponse(429, {})

    assert_error(plan(client), code="UPSTREAM_RATE_LIMITED", status=503)


def test_an_upstream_fault_is_a_bad_gateway(client, ors):
    ors.directions_override = FakeResponse(500, {})

    assert_error(plan(client), code="UPSTREAM_ERROR", status=502)


def test_an_unexpected_failure_still_leaves_in_the_envelope(client, ors, monkeypatch):
    """The catch-all path: never a stack trace, a blank screen or a bare 500."""

    def explode(*_args, **_kwargs):
        raise RuntimeError("something nobody anticipated")

    monkeypatch.setattr("trips.api.views.planner.plan_trip", explode)

    response = plan(client)
    assert_error(response, code="INTERNAL_ERROR", status=500)
    body = response.json()
    assert "Traceback" not in body["error"]["message"]
    assert "nobody anticipated" not in body["error"]["message"]


def test_an_unknown_path_returns_the_envelope_not_djangos_html(client, ors):
    response = client.get("/api/v1/nope")

    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.fixture
def two_per_minute(monkeypatch):
    """DRF binds `THROTTLE_RATES` to the settings dict when `rest_framework.throttling`
    is imported, so overriding `REST_FRAMEWORK` at run time never reaches it. The
    env var still works in production, since it is read before that import."""
    monkeypatch.setattr(AnonRateThrottle, "THROTTLE_RATES", {"anon": "2/min"})


def test_planning_is_throttled_and_says_so_in_our_own_vocabulary(client, ors, two_per_minute):
    assert plan(client).status_code == 200
    assert plan(client).status_code == 200

    assert_error(plan(client), code="RATE_LIMITED", status=429)


def test_the_health_probe_does_not_spend_the_planning_allowance(client, ors, two_per_minute):
    """A page reload, or an uptime pinger, must never exhaust the budget the
    actual trip needs."""
    for _ in range(6):
        assert client.get(HEALTH_URL).status_code == 200

    assert plan(client).status_code == 200


def test_a_wrong_method_reports_itself_as_such_not_as_an_internal_error(client, ors):
    response = client.get(PLAN_URL)

    assert_error(response, code="METHOD_NOT_ALLOWED", status=405)


def test_a_departure_with_a_utc_offset_is_rejected_rather_than_reinterpreted(client, ors):
    """§395.8(a) wants one time standard. Silently shifting the trip by the offset
    moved every log sheet with it."""
    response = plan(client, start_datetime="2026-07-27T08:00:00-05:00")

    assert_error(response, code="VALIDATION_ERROR", status=400, field="start_datetime")


def test_an_unconfigured_api_key_fails_without_leaking_why(client, ors, settings):
    settings.ORS_API_KEY = ""

    response = plan(client)
    assert_error(response, code="UPSTREAM_ERROR", status=502)
    assert "key" not in response.json()["error"]["message"].lower()


# --------------------------------------------------------------------------- #
# Degradation
# --------------------------------------------------------------------------- #


def test_a_failed_reverse_lookup_warns_but_still_returns_a_plan(client, ors):
    ors.reverse_label = None

    body = plan(client).json()

    assert body["warnings"], "the fallback is worth telling the user about"
    assert all(day["totals"]["total"] == 24.0 for day in body["days"])
    assert all(stop["label"] for stop in body["stops"])
    assert any("mile" in stop["label"] for stop in body["stops"])
