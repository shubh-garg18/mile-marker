"""What can go wrong while planning a trip, as typed vocabulary.

These live in the service layer because that is where they are raised. The
planner and the OpenRouteService client both need them, and neither should import
the HTTP layer to describe a failure. `trips/api/errors.py` owns the other half:
mapping a code onto a status and rendering the envelope.

Every message here is user-facing copy written for a dispatcher. No upstream
payload, status line or traceback is ever quoted into one.
"""

from __future__ import annotations


class PlannerError(Exception):
    """A failure we anticipated and can explain to the user (-> 500 unless overridden)."""

    code = "INTERNAL_ERROR"

    def __init__(self, message: str, *, field: str | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field
        if code is not None:
            self.code = code


class GeocodeNotFound(PlannerError):
    """No geocoder match for one of the three locations (-> 422)."""

    code = "GEOCODE_NOT_FOUND"


class RouteNotFound(PlannerError):
    """The router answered, but no truck route connects the waypoints (-> 422)."""

    code = "ROUTE_NOT_FOUND"


class RouteTooLong(PlannerError):
    """The route exceeds the 6,000 km cap on the driving profile (-> 422)."""

    code = "ROUTE_TOO_LONG"


class UpstreamRateLimited(PlannerError):
    """The routing service's daily quota or per-minute limit is spent (-> 503)."""

    code = "UPSTREAM_RATE_LIMITED"


class UpstreamError(PlannerError):
    """The routing service failed, timed out, or sent a payload we cannot read (-> 502)."""

    code = "UPSTREAM_ERROR"
