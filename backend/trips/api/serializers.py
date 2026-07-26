"""Input validation. Messages here are read by a dispatcher, not a developer."""

from __future__ import annotations

import re
from decimal import Decimal

from rest_framework import serializers

from trips.domain.constants import CYCLE_LIMIT_MINUTES, QUANTUM_MINUTES

MAX_CYCLE_HOURS = CYCLE_LIMIT_MINUTES / 60
QUARTER_HOUR = Decimal(QUANTUM_MINUTES) / Decimal(60)


#: A trailing `Z` or `+05:30` on an ISO-8601 string.
UTC_OFFSET = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")


class HomeTerminalDateTimeField(serializers.DateTimeField):
    """A departure time in home-terminal wall time, with no UTC offset.

    §395.8(a) requires one time standard for the whole trip, so every time in this
    system is home-terminal local. An offset would have to be either honoured
    (shifting the departure) or discarded (ignoring what was sent), and both
    surprise the caller. Sending `08:00-05:00` for a terminal already on -05:00
    used to depart at 13:00 and carry every log sheet with it.

    The check belongs here rather than in `validate_start_datetime`. With
    `USE_TZ = False` DRF has already converted the value to naive UTC by the time
    a field validator sees it, so the offset is gone and the damage is done.
    """

    default_error_messages = {
        "has_offset": (
            "Enter the departure as home-terminal local time, without a UTC "
            "offset. For example 2026-07-27T08:00:00."
        )
    }

    def to_internal_value(self, value):
        if isinstance(value, str) and UTC_OFFSET.search(value.strip()):
            self.fail("has_offset")
        return super().to_internal_value(value)


def _location_field(label: str) -> serializers.CharField:
    return serializers.CharField(
        max_length=200,
        trim_whitespace=True,
        error_messages={
            "blank": f"Enter the {label}.",
            "required": f"Enter the {label}.",
            "max_length": f"That {label} is too long. Try a city and state.",
        },
    )


class TripPlanRequestSerializer(serializers.Serializer):
    current_location = _location_field("driver's current location")
    pickup_location = _location_field("pickup location")
    dropoff_location = _location_field("dropoff location")

    current_cycle_used_hours = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal(0),
        max_value=Decimal(MAX_CYCLE_HOURS),
        error_messages={
            "required": "Enter how many hours of the 70-hour cycle are already used.",
            "invalid": "Enter cycle hours as a number, for example 12.5.",
            "min_value": "Cycle hours used can't be negative.",
            "max_value": (
                f"Cycle hours used can't exceed {MAX_CYCLE_HOURS:.0f}, the whole "
                f"70-hour/8-day limit."
            ),
        },
    )

    start_datetime = HomeTerminalDateTimeField(
        required=False,
        allow_null=True,
        default=None,
        error_messages={"invalid": "Enter the departure time as a date and time."},
    )

    def validate_current_cycle_used_hours(self, value: Decimal) -> Decimal:
        """Snap up to the next quarter hour.

        The log grid is drawn in 15-minute cells and every duration in the
        simulation sits on that lattice. Rounding up never credits the driver with
        hours they have already spent, which is the safe direction.
        """
        quarters = (value / QUARTER_HOUR).to_integral_value(rounding="ROUND_CEILING")
        snapped = quarters * QUARTER_HOUR

        if snapped > Decimal(MAX_CYCLE_HOURS):
            return Decimal(MAX_CYCLE_HOURS)
        return snapped
