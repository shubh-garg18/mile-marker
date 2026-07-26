"""HTTP layer. Views parse, delegate and serialize, nothing else."""

from __future__ import annotations

import logging
import time

from rest_framework.decorators import api_view, throttle_classes
from rest_framework.request import Request
from rest_framework.response import Response

from trips.api.serializers import TripPlanRequestSerializer
from trips.services import planner

logger = logging.getLogger(__name__)


@api_view(["GET"])
@throttle_classes([])
def health(_request: Request) -> Response:
    """Cheap, dependency-free liveness probe. The frontend calls it on mount to
    wake the free-tier instance before the user submits anything.

    Exempt from the throttle. It costs nothing upstream, and sharing the anonymous
    budget with `plan_trip` would let a repeatedly reloaded page or an uptime
    pinger spend the allowance the actual trip needs.
    """
    return Response({"status": "ok"})


@api_view(["POST"])
def plan_trip(request: Request) -> Response:
    serializer = TripPlanRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    started = time.monotonic()
    plan = planner.plan_trip(**serializer.validated_data)
    elapsed_ms = round((time.monotonic() - started) * 1000)

    logger.info(
        "trip_planned route=%s distance_miles=%s days=%s warnings=%s elapsed_ms=%s",
        " -> ".join(point["resolved_name"] for point in plan["waypoints"]),
        plan["trip"]["total_distance_miles"],
        plan["trip"]["days_count"],
        len(plan["warnings"]),
        elapsed_ms,
    )
    return Response(plan)
