"""Placing stops on the route polyline.

The HOS engine works in the time domain, so each stop arrives carrying a
cumulative mileage rather than a coordinate. Turning that mileage back into a
point on the map is this module's job.

Coordinates here are (latitude, longitude), Leaflet's order. The conversion from
OpenRouteService's [longitude, latitude] happens once, in `ors_client`.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_MILES = 3958.7613
METERS_PER_MILE = 1609.344

Coordinate = tuple[float, float]


def haversine_miles(a: Coordinate, b: Coordinate) -> float:
    """Great-circle distance between two (lat, lon) points, in statute miles."""
    lat1, lon1 = radians(a[0]), radians(a[1])
    lat2, lon2 = radians(b[0]), radians(b[1])

    half_chord = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * asin(sqrt(half_chord))


def meters_to_miles(meters: float) -> float:
    return meters / METERS_PER_MILE


@dataclass
class RoutePolyline:
    """A route geometry with its cumulative-distance array computed once.

    Building the array is O(n) and every stop lookup afterwards is O(log n).
    Rebuilding per stop would be O(n) each time, and a transcontinental
    driving-hgv route runs to tens of thousands of points.

    The polyline's summed length differs from the distance OpenRouteService
    reports by a fraction of a percent, because great-circle hops between vertices
    are not real road geometry. `reported_miles` carries the authoritative figure
    so `point_at_route_mile` can rescale into polyline space before interpolating,
    which keeps markers in place on long routes.
    """

    coords: list[Coordinate]
    reported_miles: float = 0.0
    cumulative_miles: list[float] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        if not self.coords:
            raise ValueError("A route polyline needs at least one coordinate")

        running = 0.0
        cumulative = [0.0]
        for earlier, later in zip(self.coords, self.coords[1:], strict=False):
            running += haversine_miles(earlier, later)
            cumulative.append(running)
        self.cumulative_miles = cumulative

        if self.reported_miles <= 0:
            self.reported_miles = running

    @property
    def length_miles(self) -> float:
        """Length of the drawn polyline, which is not quite the reported distance."""
        return self.cumulative_miles[-1]

    def point_at(self, target_miles: float) -> Coordinate:
        """Walk the polyline to `target_miles` and interpolate. Clamped to the ends."""
        if len(self.coords) == 1:
            return self.coords[0]

        target = min(max(target_miles, 0.0), self.length_miles)
        index = min(bisect_right(self.cumulative_miles, target) - 1, len(self.coords) - 2)
        index = max(index, 0)

        span = self.cumulative_miles[index + 1] - self.cumulative_miles[index]
        if span <= 0:
            return self.coords[index]

        fraction = (target - self.cumulative_miles[index]) / span
        start, end = self.coords[index], self.coords[index + 1]
        return (
            start[0] + (end[0] - start[0]) * fraction,
            start[1] + (end[1] - start[1]) * fraction,
        )

    def point_at_route_mile(self, route_mile: float) -> Coordinate:
        """As `point_at`, but for a mileage measured against the reported distance."""
        if self.reported_miles <= 0:
            return self.point_at(route_mile)
        return self.point_at(route_mile * self.length_miles / self.reported_miles)

    def bounds(self) -> tuple[float, float, float, float]:
        """(min_lat, min_lon, max_lat, max_lon), the order Leaflet's fitBounds wants."""
        lats = [lat for lat, _ in self.coords]
        lons = [lon for _, lon in self.coords]
        return min(lats), min(lons), max(lats), max(lons)


def point_at_distance(coords: list[Coordinate], target_miles: float) -> Coordinate:
    """One-shot wrapper. Prefer `RoutePolyline` when placing many stops."""
    return RoutePolyline(coords=list(coords)).point_at(target_miles)
