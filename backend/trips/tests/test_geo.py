"""Geometry tests: distance on a sphere, and interpolation along a polyline."""

from __future__ import annotations

import pytest

from trips.services.geo import (
    RoutePolyline,
    haversine_miles,
    meters_to_miles,
    point_at_distance,
)

DALLAS = (32.7767, -96.7970)
OKLAHOMA_CITY = (35.4676, -97.5164)
NEW_YORK = (40.7128, -74.0060)
LOS_ANGELES = (34.0522, -118.2437)
LONDON = (51.5074, -0.1278)
PARIS = (48.8566, 2.3522)


# --------------------------------------------------------------------------- #
# Haversine
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "start,end,published_miles",
    [
        (NEW_YORK, LOS_ANGELES, 2451),  # 3,944 km great circle
        (LONDON, PARIS, 214),  # 344 km great circle
    ],
)
def test_haversine_matches_published_great_circle_distances(start, end, published_miles):
    assert haversine_miles(start, end) == pytest.approx(published_miles, rel=0.01)


def test_haversine_is_symmetric_and_zero_for_a_point_against_itself():
    assert haversine_miles(DALLAS, OKLAHOMA_CITY) == pytest.approx(
        haversine_miles(OKLAHOMA_CITY, DALLAS)
    )
    assert haversine_miles(DALLAS, DALLAS) == 0.0


def test_meters_convert_to_miles():
    assert meters_to_miles(1609.344) == pytest.approx(1.0)
    assert meters_to_miles(0) == 0.0


# --------------------------------------------------------------------------- #
# point_at_distance
# --------------------------------------------------------------------------- #

# Three points on the same meridian, evenly spaced: the midpoint of the whole line
# is exactly the middle vertex, which makes every expectation below checkable by
# hand rather than by running the code and writing down what it said.
STRAIGHT_LINE = [(30.0, -100.0), (31.0, -100.0), (32.0, -100.0)]


def test_point_at_zero_is_the_start_of_the_line():
    assert point_at_distance(STRAIGHT_LINE, 0.0) == STRAIGHT_LINE[0]


def test_point_at_the_total_length_is_the_end_of_the_line():
    route = RoutePolyline(coords=STRAIGHT_LINE)
    assert route.point_at(route.length_miles) == pytest.approx(STRAIGHT_LINE[-1])


def test_point_at_the_midpoint_of_a_straight_line_is_the_middle_vertex():
    route = RoutePolyline(coords=STRAIGHT_LINE)
    latitude, longitude = route.point_at(route.length_miles / 2)

    assert latitude == pytest.approx(31.0, abs=1e-6)
    assert longitude == pytest.approx(-100.0, abs=1e-6)


def test_point_at_a_quarter_of_the_way_interpolates_within_the_first_segment():
    route = RoutePolyline(coords=STRAIGHT_LINE)
    latitude, _ = route.point_at(route.length_miles / 4)

    assert latitude == pytest.approx(30.5, abs=1e-6)


def test_a_distance_beyond_the_end_clamps_to_the_last_point():
    assert point_at_distance(STRAIGHT_LINE, 99_999) == pytest.approx(STRAIGHT_LINE[-1])


def test_a_negative_distance_clamps_to_the_first_point():
    assert point_at_distance(STRAIGHT_LINE, -50) == pytest.approx(STRAIGHT_LINE[0])


def test_a_single_point_polyline_is_its_own_answer():
    assert point_at_distance([DALLAS], 100) == DALLAS


def test_an_empty_polyline_is_rejected():
    with pytest.raises(ValueError):
        RoutePolyline(coords=[])


def test_repeated_coordinates_do_not_divide_by_zero():
    route = RoutePolyline(coords=[DALLAS, DALLAS, OKLAHOMA_CITY])
    assert route.point_at(0.0) == DALLAS
    assert route.point_at(route.length_miles) == pytest.approx(OKLAHOMA_CITY)


# --------------------------------------------------------------------------- #
# Rescaling into polyline space
# --------------------------------------------------------------------------- #


def test_route_mileage_is_rescaled_into_polyline_space_before_interpolating():
    """Road distance exceeds the polyline's summed great-circle hops.

    Half of the *reported* distance must land halfway along the *drawn* line, or
    every marker on a long route sits progressively further from where it belongs.
    """
    route = RoutePolyline(coords=STRAIGHT_LINE, reported_miles=1000.0)

    latitude, _ = route.point_at_route_mile(500.0)
    assert latitude == pytest.approx(31.0, abs=1e-6)

    assert route.point_at_route_mile(0.0) == STRAIGHT_LINE[0]
    assert route.point_at_route_mile(1000.0) == pytest.approx(STRAIGHT_LINE[-1])


def test_reported_miles_defaults_to_the_polylines_own_length():
    route = RoutePolyline(coords=STRAIGHT_LINE)
    assert route.reported_miles == pytest.approx(route.length_miles)


def test_bounds_are_returned_in_leaflet_order():
    route = RoutePolyline(coords=[DALLAS, OKLAHOMA_CITY])
    min_lat, min_lon, max_lat, max_lon = route.bounds()

    assert (min_lat, max_lat) == (DALLAS[0], OKLAHOMA_CITY[0])
    assert (min_lon, max_lon) == (OKLAHOMA_CITY[1], DALLAS[1])


def test_cumulative_distances_increase_monotonically_from_zero():
    route = RoutePolyline(coords=[DALLAS, OKLAHOMA_CITY, (39.7392, -104.9903)])

    assert route.cumulative_miles[0] == 0.0
    assert len(route.cumulative_miles) == 3
    assert route.cumulative_miles == sorted(route.cumulative_miles)
    assert route.cumulative_miles[-1] == pytest.approx(
        haversine_miles(DALLAS, OKLAHOMA_CITY)
        + haversine_miles(OKLAHOMA_CITY, (39.7392, -104.9903))
    )
