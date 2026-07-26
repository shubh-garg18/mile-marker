from django.http import JsonResponse
from django.urls import path

from trips.api import views
from trips.api.errors import error_envelope

urlpatterns = [
    path("api/v1/health", views.health, name="health"),
    path("api/v1/trips/plan", views.plan_trip, name="plan-trip"),
]


def _not_found(_request, exception=None):  # noqa: ARG001 (Django passes it by keyword)
    """Django's own 404 is an HTML page. Every error leaves this service in the
    JSON envelope, including the ones no view handled."""
    return JsonResponse(
        error_envelope("NOT_FOUND", "That address isn't part of this API."), status=404
    )


def _server_error(_request):
    return JsonResponse(
        error_envelope(
            "INTERNAL_ERROR",
            "Something went wrong on our side while planning that trip. Please try again.",
        ),
        status=500,
    )


handler404 = _not_found
handler500 = _server_error
