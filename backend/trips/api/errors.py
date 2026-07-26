"""The single error shape this API speaks, and the DRF hook that enforces it.

Every failure, whether validated, expected or unforeseen, leaves the service as:

    {"error": {"code": ..., "message": ..., "field": ...}}

The failure vocabulary lives one layer down in `trips/services/errors.py` so the
planner and the ORS client can raise without importing HTTP. This module owns the
translation: which code, which status, what the dispatcher reads.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.exceptions import ParseError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from trips.services.errors import (
    GeocodeNotFound,
    PlannerError,
    RouteNotFound,
    RouteTooLong,
    UpstreamError,
    UpstreamRateLimited,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ERROR_STATUS",
    "GeocodeNotFound",
    "PlannerError",
    "RouteNotFound",
    "RouteTooLong",
    "UpstreamError",
    "UpstreamRateLimited",
    "error_envelope",
    "error_response",
    "exception_handler",
    "http_status_for",
]

# code -> HTTP status.
ERROR_STATUS: dict[str, int] = {
    "VALIDATION_ERROR": status.HTTP_400_BAD_REQUEST,
    "GEOCODE_NOT_FOUND": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "ROUTE_NOT_FOUND": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "ROUTE_TOO_LONG": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "UPSTREAM_RATE_LIMITED": status.HTTP_503_SERVICE_UNAVAILABLE,
    "UPSTREAM_ERROR": status.HTTP_502_BAD_GATEWAY,
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "METHOD_NOT_ALLOWED": status.HTTP_405_METHOD_NOT_ALLOWED,
    "NOT_ACCEPTABLE": status.HTTP_406_NOT_ACCEPTABLE,
    "UNSUPPORTED_MEDIA_TYPE": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    "RATE_LIMITED": status.HTTP_429_TOO_MANY_REQUESTS,
    "INTERNAL_ERROR": status.HTTP_500_INTERNAL_SERVER_ERROR,
}

#: The inverse, for translating a status DRF chose back into our vocabulary. A
#: client keys on `code`, so a 405 reported as INTERNAL_ERROR would be wrong.
CODE_FOR_STATUS: dict[int, str] = {
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
    status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
    status.HTTP_406_NOT_ACCEPTABLE: "NOT_ACCEPTABLE",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "UNSUPPORTED_MEDIA_TYPE",
    status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMITED",
}

MESSAGE_FOR_STATUS: dict[int, str] = {
    status.HTTP_404_NOT_FOUND: "That address isn't part of this API.",
    status.HTTP_405_METHOD_NOT_ALLOWED: "That request method isn't allowed on this address.",
    status.HTTP_406_NOT_ACCEPTABLE: "This API only returns JSON.",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "Send the trip details as JSON.",
    status.HTTP_429_TOO_MANY_REQUESTS: "Too many trips planned just now. Please wait a moment.",
}

GENERIC_MESSAGE = "Something went wrong on our side while planning that trip. Please try again."


def http_status_for(code: str) -> int:
    return ERROR_STATUS.get(code, status.HTTP_500_INTERNAL_SERVER_ERROR)


def error_envelope(code: str, message: str, field: str | None = None) -> dict:
    return {"error": {"code": code, "message": message, "field": field}}


def error_response(code: str, message: str, field: str | None = None) -> Response:
    return Response(error_envelope(code, message, field), status=http_status_for(code))


def _first_field_error(detail: object, path: str = "") -> tuple[str | None, str | None]:
    """Pull one (field, message) pair out of DRF's nested validation detail.

    Nested paths are joined, so the frontend gets `stops.origin.city` rather than
    just `city` and can attach the message to the input that caused it.
    """
    if isinstance(detail, dict):
        for key, value in detail.items():
            # `detail` and `non_field_errors` are DRF's own envelope keys rather
            # than anything the caller sent, so they are not reported as fields.
            if key in {"detail", "non_field_errors"}:
                child_path = path
            else:
                child_path = f"{path}.{key}" if path else str(key)

            found_field, found_message = _first_field_error(value, child_path)
            if found_message:
                return found_field, found_message
        return None, None

    if isinstance(detail, list):
        for item in detail:
            found_field, found_message = _first_field_error(item, path)
            if found_message:
                return found_field, found_message
        return None, None

    return (path or None), str(detail)


def exception_handler(exc: Exception, context: dict) -> Response:
    """DRF exception hook. Nothing escapes this function in another shape."""
    if isinstance(exc, PlannerError):
        logger.info("planner_error code=%s field=%s message=%s", exc.code, exc.field, exc.message)
        return error_response(exc.code, exc.message, exc.field)

    if isinstance(exc, ParseError):
        # DRF's own text names a JSON column number, which a dispatcher cannot
        # act on.
        return error_response(
            "VALIDATION_ERROR", "We couldn't read that request. Please try again."
        )

    response = drf_exception_handler(exc, context)

    if response is None:
        logger.exception("unhandled_exception")
        return error_response("INTERNAL_ERROR", GENERIC_MESSAGE)

    if response.status_code == status.HTTP_400_BAD_REQUEST:
        field, message = _first_field_error(response.data)
        return error_response("VALIDATION_ERROR", message or "That request wasn't valid.", field)

    code = CODE_FOR_STATUS.get(response.status_code, "INTERNAL_ERROR")
    message = MESSAGE_FOR_STATUS.get(response.status_code, GENERIC_MESSAGE)
    return Response(error_envelope(code, message), status=response.status_code)
