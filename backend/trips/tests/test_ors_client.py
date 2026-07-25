"""OpenRouteService client: parsing, caching, and failure translation.

Nothing here touches the network. Every test drives a fake `requests.request`, so
the assertions are about the two things that actually go wrong in this layer:
coordinate order, and what the user is told when the upstream fails.
"""

from __future__ import annotations

import pytest
import requests
from django.core.cache import cache

from trips.api.errors import http_status_for
from trips.services import ors_client
from trips.services.errors import (
    GeocodeNotFound,
    RouteNotFound,
    RouteTooLong,
    UpstreamError,
    UpstreamRateLimited,
)


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: object = None, *, unreadable: bool = False):
        self.status_code = status_code
        self._payload = payload
        self._unreadable = unreadable

    def json(self):
        if self._unreadable:
            raise ValueError("not json")
        return self._payload


@pytest.fixture(autouse=True)
def _isolated(settings, monkeypatch):
    """A configured key, an empty cache, and no real sleeping between retries."""
    settings.ORS_API_KEY = "test-key"
    cache.clear()
    monkeypatch.setattr(ors_client.time, "sleep", lambda _seconds: None)
    yield
    cache.clear()


class FakeOrs:
    """Stands in for `requests.request`: records calls, replies from a queue."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.queue: list[FakeResponse | Exception] = []

    def __call__(self, method: str, url: str, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        reply = self.queue.pop(0) if self.queue else FakeResponse(200, {})
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def ors(monkeypatch):
    fake = FakeOrs()
    monkeypatch.setattr(requests, "request", fake)
    return fake


def geocode_payload(*, locality="Dallas", region_a="TX", lon=-96.797, lat=32.7767):
    return {
        "features": [
            {
                "geometry": {"coordinates": [lon, lat]},
                "properties": {
                    "locality": locality,
                    "region_a": region_a,
                    "label": f"{locality}, Texas, United States",
                },
            }
        ]
    }


def directions_payload(*, distance_meters=331_000.0, duration_seconds=12_600.0):
    return {
        "features": [
            {
                "geometry": {
                    "coordinates": [[-96.797, 32.7767], [-97.0, 34.0], [-97.5164, 35.4676]]
                },
                "properties": {
                    "summary": {"distance": distance_meters, "duration": duration_seconds},
                    "segments": [
                        {"distance": distance_meters / 2, "duration": duration_seconds / 2},
                        {"distance": distance_meters / 2, "duration": duration_seconds / 2},
                    ],
                },
            }
        ]
    }


# --------------------------------------------------------------------------- #
# Geocoding
# --------------------------------------------------------------------------- #


def test_geocode_reads_lon_lat_and_returns_lat_lon(ors):
    ors.queue.append(FakeResponse(200, geocode_payload()))

    place = ors_client.geocode("Dallas TX", field="current_location")

    assert (place.lat, place.lon) == (32.7767, -96.797)
    assert place.label == "Dallas, TX"
    assert place.resolved_name == "Dallas, Texas, United States"
    assert place.coord == (32.7767, -96.797)


def test_geocode_searches_us_locations_only(ors):
    ors.queue.append(FakeResponse(200, geocode_payload()))

    ors_client.geocode("Dallas TX", field="current_location")

    assert ors.calls[0]["params"]["boundary.country"] == "US"
    assert ors.calls[0]["params"]["size"] == 1


def test_geocode_result_is_cached_by_normalized_query(ors):
    ors.queue.append(FakeResponse(200, geocode_payload()))

    first = ors_client.geocode("Dallas TX", field="current_location")
    second = ors_client.geocode("  dallas   tx  ", field="pickup_location")

    assert len(ors.calls) == 1, "the second lookup must be served from cache"
    assert second == first


def test_geocode_with_no_match_names_the_offending_field(ors):
    ors.queue.append(FakeResponse(200, {"features": []}))

    with pytest.raises(GeocodeNotFound) as raised:
        ors_client.geocode("Dalas TX", field="current_location")

    assert raised.value.field == "current_location"
    assert "Dalas TX" in raised.value.message
    assert raised.value.code == "GEOCODE_NOT_FOUND"


def test_geocode_label_falls_back_when_locality_is_absent(ors):
    ors.queue.append(
        FakeResponse(
            200,
            {
                "features": [
                    {
                        "geometry": {"coordinates": [-104.99, 39.74]},
                        "properties": {"county": "Denver County", "region_a": "CO"},
                    }
                ]
            },
        )
    )

    assert ors_client.geocode("somewhere", field="pickup_location").label == "Denver County, CO"


# --------------------------------------------------------------------------- #
# Directions
# --------------------------------------------------------------------------- #


def test_directions_sends_lon_lat_and_the_hgv_vehicle_type(ors):
    ors.queue.append(FakeResponse(200, directions_payload()))

    ors_client.directions([(32.7767, -96.797), (35.4676, -97.5164)])

    body = ors.calls[0]["json"]
    assert body["coordinates"] == [[-96.797, 32.7767], [-97.5164, 35.4676]]
    assert body["options"] == {"vehicle_type": "hgv"}
    assert ors.calls[0]["url"].endswith("/driving-hgv/geojson")
    assert ors.calls[0]["headers"]["Authorization"] == "test-key"


def test_directions_returns_geometry_in_leaflet_order(ors):
    ors.queue.append(FakeResponse(200, directions_payload()))

    route = ors_client.directions([(32.7767, -96.797), (35.4676, -97.5164)])

    assert route.coords[0] == (32.7767, -96.797)
    assert route.coords[-1] == (35.4676, -97.5164)


def test_directions_converts_meters_and_seconds_at_the_boundary(ors):
    ors.queue.append(FakeResponse(200, directions_payload()))

    route = ors_client.directions([(32.7767, -96.797), (35.4676, -97.5164)])

    assert route.distance_miles == pytest.approx(205.7, abs=0.5)
    assert route.duration_minutes == pytest.approx(210.0)
    assert len(route.legs) == 2
    assert route.legs[0].distance_miles == pytest.approx(102.8, abs=0.5)
    assert route.legs[0].duration_minutes == pytest.approx(105.0)


def test_a_route_beyond_the_profile_cap_is_rejected_before_planning(ors):
    ors.queue.append(FakeResponse(200, directions_payload(distance_meters=6_500_000.0)))

    with pytest.raises(RouteTooLong) as raised:
        ors_client.directions([(32.7767, -96.797), (35.4676, -97.5164)])

    assert raised.value.code == "ROUTE_TOO_LONG"
    assert http_status_for(raised.value.code) == 422


def test_directions_with_no_feature_is_a_route_not_found(ors):
    ors.queue.append(FakeResponse(200, {"features": []}))

    with pytest.raises(RouteNotFound):
        ors_client.directions([(32.7767, -96.797), (35.4676, -97.5164)])


# --------------------------------------------------------------------------- #
# Upstream failures become our error codes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "ors_code,expected",
    [(2004, RouteTooLong), (2009, RouteNotFound), (2010, RouteNotFound), (9999, UpstreamError)],
)
def test_ors_error_codes_map_onto_ours(ors, ors_code, expected):
    ors.queue.append(FakeResponse(404, {"error": {"code": ors_code, "message": "upstream"}}))

    with pytest.raises(expected) as raised:
        ors_client.directions([(32.7767, -96.797), (35.4676, -97.5164)])

    assert "upstream" not in raised.value.message, "no upstream text is quoted back"


def test_a_minute_rate_limit_is_surfaced_immediately_rather_than_retried(ors):
    """ORS enforces the minute limit over a sliding 60-second window.

    A sub-second retry cannot clear it and spends another request from the very
    budget that is already exhausted, so the retry would make the rate limiting
    worse, not better.
    """
    ors.queue.extend([FakeResponse(429), FakeResponse(200, directions_payload())])

    with pytest.raises(UpstreamRateLimited) as raised:
        ors_client.directions([(32.7767, -96.797), (35.4676, -97.5164)])

    assert len(ors.calls) == 1
    assert http_status_for(raised.value.code) == 503


def test_a_redirect_loop_or_tls_failure_is_not_retried(ors):
    """Only an unreachable host or a 5xx is retried. These will not improve."""
    ors.queue.append(requests.TooManyRedirects("loop"))

    with pytest.raises(UpstreamError):
        ors_client.directions([(32.7767, -96.797), (35.4676, -97.5164)])

    assert len(ors.calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"features": ["not-a-feature"]},
        {"features": [{"geometry": {"coordinates": [[-96.8]]}, "properties": {}}]},
        {"features": [{"geometry": {"coordinates": [[-96.8, 32.7], [-97.5, 35.4]]}}]},
        {
            "features": [
                {"geometry": {"coordinates": [[-96.8, 32.7], [-97.5, 35.4]]}, "properties": []}
            ]
        },
    ],
)
def test_a_structurally_malformed_payload_is_an_upstream_error_not_a_crash(ors, payload):
    """Valid JSON in the wrong shape used to escape as AttributeError/ValueError
    and leave as INTERNAL_ERROR/500. An unreadable payload is meant to be 502, so we
    cannot read."""
    ors.queue.append(FakeResponse(200, payload))

    with pytest.raises((UpstreamError, RouteNotFound)) as raised:
        ors_client.directions([(32.7767, -96.797), (35.4676, -97.5164)])

    assert http_status_for(raised.value.code) in {422, 502}


def test_a_retried_request_that_succeeds_returns_normally(ors):
    ors.queue.extend([FakeResponse(503), FakeResponse(200, directions_payload())])

    route = ors_client.directions([(32.7767, -96.797), (35.4676, -97.5164)])

    assert len(ors.calls) == 2
    assert route.distance_miles > 0


def test_the_daily_quota_is_not_retried(ors):
    ors.queue.append(FakeResponse(403))

    with pytest.raises(UpstreamRateLimited):
        ors_client.directions([(32.7767, -96.797), (35.4676, -97.5164)])

    assert len(ors.calls) == 1, "a 403 is the daily quota; a retry cannot fix it"


def test_a_rejected_key_is_not_reported_as_the_daily_quota(ors):
    """ORS answers 403 to a key it will not accept, with exactly this body. Sending
    a dispatcher away for a day is the wrong response to a server misconfiguration
    and a wrong key is the likeliest fault on a fresh deployment."""
    ors.queue.append(FakeResponse(403, {"error": "Access to this API has been disallowed"}))

    with pytest.raises(UpstreamError) as raised:
        ors_client.directions([(32.7767, -96.797), (35.4676, -97.5164)])

    assert not isinstance(raised.value, UpstreamRateLimited)
    assert "tomorrow" not in raised.value.message
    assert "set up correctly" in raised.value.message
    assert len(ors.calls) == 1


def test_a_server_fault_becomes_an_upstream_error_after_one_retry(ors):
    ors.queue.extend([FakeResponse(500), FakeResponse(500)])

    with pytest.raises(UpstreamError) as raised:
        ors_client.directions([(32.7767, -96.797), (35.4676, -97.5164)])

    assert len(ors.calls) == 2
    assert http_status_for(raised.value.code) == 502


def test_a_timeout_becomes_an_upstream_error(ors):
    ors.queue.extend([requests.Timeout("slow"), requests.Timeout("slow")])

    with pytest.raises(UpstreamError):
        ors_client.directions([(32.7767, -96.797), (35.4676, -97.5164)])


def test_an_unreadable_payload_is_not_retried_and_becomes_an_upstream_error(ors):
    ors.queue.append(FakeResponse(200, unreadable=True))

    with pytest.raises(UpstreamError):
        ors_client.directions([(32.7767, -96.797), (35.4676, -97.5164)])

    assert len(ors.calls) == 1


def test_a_missing_api_key_never_reaches_the_network(ors, settings):
    settings.ORS_API_KEY = ""

    with pytest.raises(UpstreamError):
        ors_client.geocode("Dallas TX", field="current_location")

    assert ors.calls == []


# --------------------------------------------------------------------------- #
# Reverse geocoding degrades rather than failing
# --------------------------------------------------------------------------- #


def test_reverse_geocode_returns_a_short_label(ors):
    ors.queue.append(FakeResponse(200, geocode_payload(locality="Amarillo", region_a="TX")))

    assert ors_client.reverse_geocode(35.22, -101.83) == "Amarillo, TX"


def test_reverse_geocode_returns_none_instead_of_raising_when_the_quota_is_gone(ors):
    ors.queue.append(FakeResponse(403))

    assert ors_client.reverse_geocode(35.22, -101.83) is None


def test_reverse_geocode_returns_none_when_there_is_no_match(ors):
    ors.queue.append(FakeResponse(200, {"features": []}))

    assert ors_client.reverse_geocode(35.22, -101.83) is None


def test_nearby_reverse_lookups_share_a_cache_entry(ors):
    ors.queue.append(FakeResponse(200, geocode_payload(locality="Amarillo", region_a="TX")))

    first = ors_client.reverse_geocode(35.2200, -101.8300)
    second = ors_client.reverse_geocode(35.22004, -101.83002)

    assert (first, second) == ("Amarillo, TX", "Amarillo, TX")
    assert len(ors.calls) == 1
