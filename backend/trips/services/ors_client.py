"""The only module that talks to OpenRouteService.

Three things happen here and nowhere else:

1. The API key is used. It lives in the server environment and never leaves this
   process. The browser calls Django, Django calls ORS.
2. Coordinates change order. ORS speaks [longitude, latitude]; Leaflet and every
   other module here speaks (latitude, longitude). The swap happens once, on the
   way out.
3. Upstream failures become our error codes. No ORS payload, status line or
   numeric code reaches the client, only the documented error envelope.

Free-tier limits worth designing against: about 2,000 directions requests a day
and 40 a minute, answered with 403 and 429 respectively, and driving profiles
capped at 6,000 km per route. Geocoding results are cached by normalized query,
which keeps a demo clear of the quota.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from hashlib import blake2s

import requests
from django.conf import settings
from django.core.cache import cache

from trips.domain.constants import MAX_ROUTE_KM
from trips.services.errors import (
    GeocodeNotFound,
    PlannerError,
    RouteNotFound,
    RouteTooLong,
    UpstreamError,
    UpstreamRateLimited,
)
from trips.services.geo import Coordinate, meters_to_miles

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://api.openrouteservice.org/geocode/search"
REVERSE_URL = "https://api.openrouteservice.org/geocode/reverse"
DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/driving-hgv/geojson"

MAX_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 0.75

#: ORS's own numeric error codes, mapped onto ours.
ROUTE_LENGTH_EXCEEDED = 2004
ROUTE_NOT_FOUND_CODES = frozenset({2009, 2010})

#: About 110 m of precision. Finer than a remark label needs, and it collapses
#: near-identical lookups onto one cache entry.
REVERSE_CACHE_PRECISION = 3

#: How long to remember that a lookup found nothing. Kept short, because a
#: degraded upstream also answers with nothing.
NEGATIVE_CACHE_SECONDS = 300

#: How far ORS may look from a requested point to find a road a truck can use.
#: Its default is 350 m, which is not enough: the geocoder answers a city query
#: with the city's centroid, and a centroid often lands in a pedestrian core or a
#: park. "Oklahoma City, OK" geocodes to a point with no routable HGV road inside
#: 350 m and the whole trip fails with ORS code 2010. Measured against the live
#: API, 1 km is enough for that case and 5 km returns an identical route, so the
#: wider radius costs nothing where a nearer road exists and only helps a rural
#: pickup. A genuinely unreachable point still fails, which is correct.
SNAP_RADIUS_METERS = 5000


@dataclass(frozen=True, slots=True)
class GeocodedPlace:
    query: str
    label: str
    resolved_name: str
    lat: float
    lon: float

    @property
    def coord(self) -> Coordinate:
        return (self.lat, self.lon)


@dataclass(frozen=True, slots=True)
class RouteLeg:
    distance_miles: float
    duration_minutes: float


@dataclass(frozen=True, slots=True)
class RouteGeometry:
    coords: list[Coordinate]
    distance_miles: float
    duration_minutes: float
    legs: list[RouteLeg]


# --------------------------------------------------------------------------- #
# Public surface
# --------------------------------------------------------------------------- #


def geocode(text: str, *, field: str) -> GeocodedPlace:
    """Resolve a free-text place to a coordinate. `field` names the form input to
    blame if it cannot be resolved."""
    # Hashed rather than interpolated. Place names contain spaces and punctuation
    # that are illegal in a memcached or Redis key, and the local-memory backend
    # would let that pass until the cache backend changed.
    normalized = " ".join(text.lower().split())
    digest = blake2s(normalized.encode("utf-8"), digest_size=8).hexdigest()
    cache_key = f"ors:geocode:v1:{digest}"

    cached = cache.get(cache_key)
    if isinstance(cached, GeocodedPlace):
        return cached

    body = _request(
        "GET",
        GEOCODE_URL,
        params={"text": text, "size": 1, "boundary.country": "US"},
    )

    features = _feature_list(body)
    if not features:
        raise GeocodeNotFound(
            f'We couldn\'t find "{text}". Try adding a state or ZIP code. '
            f"This planner searches US locations only.",
            field=field,
        )

    place = _place_from_feature(features[0], query=text)
    cache.set(cache_key, place)
    return place


def directions(points: list[Coordinate]) -> RouteGeometry:
    """A truck route through the given `(lat, lon)` points, in order."""
    payload = {
        # ORS wants [longitude, latitude]. This is the conversion boundary.
        "coordinates": [[lon, lat] for lat, lon in points],
        # Must stay true. It reads like turn-by-turn text we do not use, but ORS
        # drops `properties.segments` from the response entirely when it is false,
        # and the per-leg distance and duration in there are what the engine plans
        # against. Setting it false costs about 40 KB and the whole trip.
        "instructions": True,
        # One radius per coordinate, which is the shape ORS requires.
        "radiuses": [SNAP_RADIUS_METERS] * len(points),
        # Required for driving-hgv: without it, vehicle restrictions silently do
        # not apply and the route is no longer truck-aware.
        "options": {"vehicle_type": "hgv"},
    }

    body = _request("POST", DIRECTIONS_URL, payload=payload)

    features = _feature_list(body)
    if not features:
        raise RouteNotFound(
            "We couldn't find a truck route connecting those locations. "
            "Check the pickup and dropoff, then try again."
        )

    feature = features[0]
    coords = [
        (float(point[1]), float(point[0]))
        for point in _coordinates(feature)
        if isinstance(point, list | tuple) and len(point) >= 2
    ]
    if len(coords) < 2:
        raise RouteNotFound(
            "The routing service returned a route with no path. Try slightly different locations."
        )

    properties = _properties(feature)
    summary = properties.get("summary")
    if not isinstance(summary, dict):
        raise UpstreamError(UNREADABLE)

    try:
        distance_meters = float(summary.get("distance") or 0.0)
        duration_seconds = float(summary.get("duration") or 0.0)
    except (TypeError, ValueError) as exc:
        raise UpstreamError(UNREADABLE) from exc

    if distance_meters > MAX_ROUTE_KM * 1000:
        raise RouteTooLong(
            f"That trip is about {round(meters_to_miles(distance_meters)):,} miles, which is "
            f"beyond the {round(meters_to_miles(MAX_ROUTE_KM * 1000)):,}-mile limit of the "
            f"routing service. Try a shorter trip."
        )

    segments = properties.get("segments")
    if not isinstance(segments, list):
        raise UpstreamError(UNREADABLE)

    try:
        legs = [
            RouteLeg(
                distance_miles=meters_to_miles(float(segment.get("distance") or 0.0)),
                duration_minutes=float(segment.get("duration") or 0.0) / 60,
            )
            for segment in segments
            if isinstance(segment, dict)
        ]
    except (TypeError, ValueError) as exc:
        raise UpstreamError(UNREADABLE) from exc

    return RouteGeometry(
        coords=coords,
        distance_miles=meters_to_miles(distance_meters),
        duration_minutes=duration_seconds / 60,
        legs=legs,
    )


def reverse_geocode(lat: float, lon: float) -> str | None:
    """A place label for a point on the route, or `None` if one is unavailable.

    This never raises. A remark must never be blank and must never block a
    response, so the caller falls back to a mile marker and carries on. A missing
    label is a cosmetic loss, not a failed trip.
    """
    point = f"{round(lat, REVERSE_CACHE_PRECISION)}:{round(lon, REVERSE_CACHE_PRECISION)}"
    cache_key = f"ors:reverse:v1:{point}"
    cached = cache.get(cache_key)
    if isinstance(cached, str):
        return cached or None

    try:
        body = _request("GET", REVERSE_URL, params={"point.lat": lat, "point.lon": lon, "size": 1})
    except PlannerError as exc:
        logger.warning("reverse_geocode_unavailable lat=%s lon=%s reason=%s", lat, lon, exc)
        return None

    features = _feature_list(body)
    label = _short_label(features[0].get("properties") or {}) if features else ""

    # A miss is cached only briefly. `features: []` is also what a degraded Pelias
    # returns, and holding that for the default 24 hours would keep showing mile
    # markers on later plans long after ORS recovered.
    cache.set(cache_key, label, None if label else NEGATIVE_CACHE_SECONDS)
    return label or None


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


UNREADABLE = "The routing service sent back a response we couldn't read. Please try again."


def _feature_list(body: dict) -> list[dict]:
    """The `features` array, or an empty one if the payload isn't shaped like GeoJSON.

    A body that is valid JSON but structurally wrong (`features` holding strings,
    coordinates arriving as one-tuples) used to reach the caller and fail there
    with an AttributeError or ValueError, which left as INTERNAL_ERROR/500. An
    unreadable payload is meant to be UPSTREAM_ERROR/502, so the shape is checked
    once, here, where the payload arrives.
    """
    features = body.get("features")
    if not isinstance(features, list):
        return []
    return [feature for feature in features if isinstance(feature, dict)]


def _coordinates(feature: dict) -> list:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        return []
    coordinates = geometry.get("coordinates")
    return coordinates if isinstance(coordinates, list) else []


def _properties(feature: dict) -> dict:
    properties = feature.get("properties")
    return properties if isinstance(properties, dict) else {}


def _place_from_feature(feature: dict, *, query: str) -> GeocodedPlace:
    properties = _properties(feature)
    coordinates = _coordinates(feature)
    if len(coordinates) < 2:
        raise GeocodeNotFound(
            f'We couldn\'t place "{query}" on the map. Try a nearby city, or add a ZIP code.'
        )

    try:
        lon, lat = float(coordinates[0]), float(coordinates[1])
    except (TypeError, ValueError) as exc:
        raise UpstreamError(UNREADABLE) from exc
    label = _short_label(properties)
    return GeocodedPlace(
        query=query,
        label=label,
        resolved_name=properties.get("label") or label,
        lat=lat,
        lon=lon,
    )


def _short_label(properties: dict) -> str:
    """Build the "Dallas, TX" form of label the remarks strip wants.

    §395.8 asks for the name of the city, town or village plus the state
    abbreviation at every change of duty status. In Pelias's vocabulary that is
    `locality` plus `region_a`.
    """
    place = (
        properties.get("locality")
        or properties.get("localadmin")
        or properties.get("county")
        or properties.get("name")
        or ""
    )
    state = properties.get("region_a") or ""

    if place and state:
        return f"{place}, {state}"
    return place or state or properties.get("label") or ""


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #


class _TransientUpstream(UpstreamError):
    """A fault worth exactly one more attempt.

    Rate limits are not in this category. See the 429 branch of `_attempt`, which
    surfaces them immediately.
    """


def _request(
    method: str, url: str, *, params: dict | None = None, payload: dict | None = None
) -> dict:
    """One retry, with backoff, on an unreachable or server-side fault only.

    A 404, a 429, a malformed payload or a bad request will not improve on a
    second try, so those are raised immediately.
    """
    delay = RETRY_BACKOFF_SECONDS

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _attempt(method, url, params=params, payload=payload)
        except _TransientUpstream as exc:
            if attempt == MAX_ATTEMPTS:
                raise
            logger.warning("ors_retry url=%s attempt=%s reason=%s", url, attempt, exc.message)
            time.sleep(delay)
            delay *= 2

    raise AssertionError("unreachable: the loop either returns or raises")


def _attempt(method: str, url: str, *, params: dict | None, payload: dict | None) -> dict:
    if not settings.ORS_API_KEY:
        raise UpstreamError(
            "Trip planning is not configured on the server yet. Please try again later."
        )

    headers = {
        "Authorization": settings.ORS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json, application/geo+json",
    }

    try:
        response = requests.request(
            method,
            url,
            params=params,
            json=payload,
            headers=headers,
            timeout=settings.ORS_TIMEOUT_SECONDS,
        )
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise _TransientUpstream(
            "We couldn't reach the routing service. Please try again in a moment."
        ) from exc
    except requests.RequestException as exc:
        # Only an unreachable host or a 5xx is retried. A malformed URL, a
        # redirect loop or a TLS failure will not improve on a second attempt.
        raise UpstreamError(
            "We couldn't reach the routing service. Please try again in a moment."
        ) from exc

    if response.status_code == 429:
        # ORS enforces the minute limit as a sliding 60-second window. Retrying
        # 0.75 s later cannot clear it and only spends another request from the
        # same exhausted budget, so this is surfaced immediately.
        raise UpstreamRateLimited(
            "The routing service is busy right now. Please try again in a minute."
        )
    if response.status_code == 403:
        raise _forbidden_for(response)
    if response.status_code >= 500:
        raise _TransientUpstream(
            "The routing service is having trouble. Please try again in a moment."
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise UpstreamError(
            "The routing service sent back a response we couldn't read. Please try again."
        ) from exc

    if not isinstance(body, dict):
        raise UpstreamError(
            "The routing service sent back a response we couldn't read. Please try again."
        )

    if response.status_code >= 400:
        raise _error_for(body)

    return body


def _forbidden_for(response: requests.Response) -> PlannerError:
    """Split ORS's two meanings for 403: a key it will not accept, and a daily
    quota that has run out.

    They need different copy. "Try again tomorrow" is useless advice when the
    server's key is wrong, and a wrong key is the most likely fault on a fresh
    deployment. A rejected key answers with a plain-string error; the quota
    answers with ORS's structured error object.
    """
    try:
        body = response.json()
    except ValueError:
        body = None
    reason = body.get("error") if isinstance(body, dict) else None

    if isinstance(reason, str) and "disallow" in reason.lower():
        # ERROR level: only an operator can fix this, and every request fails
        # until they do.
        logger.error("ors_key_rejected reason=%s", reason)
        return UpstreamError(
            "Trip planning isn't set up correctly on the server. "
            "Please let whoever runs this service know."
        )

    logger.warning("ors_forbidden reason=%s", reason)
    return UpstreamRateLimited(
        "The routing service's daily quota has run out. Please try again tomorrow."
    )


def _error_for(body: dict) -> PlannerError:
    """Translate an ORS error body into ours, without quoting any of it back."""
    error = body.get("error")
    code = error.get("code") if isinstance(error, dict) else None

    if code == ROUTE_LENGTH_EXCEEDED:
        return RouteTooLong(
            f"That trip is longer than the {round(meters_to_miles(MAX_ROUTE_KM * 1000)):,}-mile "
            f"limit of the routing service. Try a shorter trip."
        )
    if code in ROUTE_NOT_FOUND_CODES:
        return RouteNotFound(
            "We couldn't find a truck route connecting those locations. One of them may be "
            "somewhere a truck can't reach. Try a nearby town or a major road."
        )

    logger.warning("ors_unmapped_error code=%s", code)
    return UpstreamError(
        "The routing service couldn't handle that request. Please check the locations and "
        "try again."
    )
