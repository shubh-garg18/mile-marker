"""Timeline in, log sheets out.

A flat list of `DutyEvent`s becomes one Record of Duty Status per calendar day:
padded to midnight at both ends, split wherever it crosses midnight, grouped by
date, and totalled.

Pure functions, no I/O. A sheet whose four status totals do not sum to exactly
24:00 raises `RodsIntegrityError` here rather than reaching the renderer. Those
totals are the first arithmetic a reviewer or a roadside inspector checks.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date as Date
from datetime import datetime, time, timedelta

from trips.domain.models import (
    DUTY_STATUS_ORDER,
    DutyEvent,
    DutyStatus,
    Remark,
    RodsDay,
    RodsSegment,
)

MINUTES_PER_DAY = 24 * 60

#: Remark text for events the engine left unlabelled.
FALLBACK_NOTES: dict[str, str] = {
    "pad": "Off duty",
    "drive": "Began driving",
    "fuel": "Fuel stop",
    "break": "30-minute rest break",
    "reset": "Began 10-hour rest",
    "restart": "Began 34-hour restart",
    "pickup": "Pickup",
    "dropoff": "Dropoff",
}


class RodsIntegrityError(ValueError):
    """A timeline that cannot produce a valid log sheet.

    A sheet that does not add up is worse than no sheet, since it looks
    authoritative and is wrong. Fail rather than render one.
    """


def build_days(events: Sequence[DutyEvent]) -> list[RodsDay]:
    """One RODS sheet per calendar day the trip spans.

    Days that fall entirely inside a 34-hour restart get a sheet too. The driver
    still files one, showing 24 hours off duty.
    """
    _require_contiguous(events)

    padded = _pad_to_midnights(events)
    remarks_by_date = _remarks_by_date(padded)
    segments_by_date = _segments_by_date(padded)

    dates = sorted(segments_by_date)
    _require_consecutive(dates)

    exact_miles = [_driving_miles(segments_by_date[day]) for day in dates]
    whole_miles = _allocate_miles(exact_miles)

    return [
        _build_day(day_number, day, segments_by_date[day], remarks_by_date.get(day, []), miles)
        for day_number, (day, miles) in enumerate(zip(dates, whole_miles, strict=True), start=1)
    ]


def _build_day(
    day_number: int,
    day: Date,
    segments: list[RodsSegment],
    remarks: list[Remark],
    driving_miles: int,
) -> RodsDay:
    return RodsDay(
        date=day.isoformat(),
        day_number=day_number,
        driving_miles=driving_miles,
        segments=segments,
        totals=_totals(day, segments),
        remarks=remarks,
    )


def _driving_miles(segments: Sequence[RodsSegment]) -> float:
    return sum(s.miles for s in segments if s.status is DutyStatus.DRIVING)


def _allocate_miles(exact: Sequence[float]) -> list[int]:
    """Whole miles per sheet that still add up to the whole trip.

    §395.8 asks for total miles driven on each sheet, and a reviewer who adds the
    column expects the trip total. Rounding each day on its own does not give
    that: five days of 605.4 miles each round down and the column falls one mile
    short. Largest-remainder allocation hands the shortfall to the days with the
    biggest fractional part, which moves each day the least.
    """
    floors = [int(miles) for miles in exact]
    shortfall = round(sum(exact)) - sum(floors)
    if shortfall <= 0:
        return floors

    by_remainder = sorted(range(len(exact)), key=lambda i: exact[i] - floors[i], reverse=True)
    for index in by_remainder[:shortfall]:
        floors[index] += 1
    return floors


# --------------------------------------------------------------------------- #
# 1. Padding
# --------------------------------------------------------------------------- #


def _pad_to_midnights(events: Sequence[DutyEvent]) -> list[DutyEvent]:
    """Extend the timeline to cover whole days at both ends.

    A driver is off duty before departing and after arriving, and the sheet must
    account for all 24 hours either way.
    """
    first, last = events[0], events[-1]
    padded = list(events)

    day_opens = _midnight(first.start)
    if day_opens < first.start:
        padded.insert(
            0,
            DutyEvent(
                status=DutyStatus.OFF_DUTY,
                start=day_opens,
                end=first.start,
                kind="pad",
                at_mile=0.0,
                note="Off duty",
                location=first.location,
            ),
        )

    day_closes = _midnight(last.end)
    if day_closes < last.end:
        day_closes += timedelta(days=1)
    if day_closes > last.end:
        padded.append(
            DutyEvent(
                status=DutyStatus.OFF_DUTY,
                start=last.end,
                end=day_closes,
                kind="pad",
                at_mile=last.at_mile,
                note="Off duty",
                location=last.location,
            )
        )

    return padded


# --------------------------------------------------------------------------- #
# 2 & 3. Split at midnight, group by date
# --------------------------------------------------------------------------- #


def _segments_by_date(events: Sequence[DutyEvent]) -> dict[Date, list[RodsSegment]]:
    grouped: dict[Date, list[RodsSegment]] = defaultdict(list)

    for event in events:
        cursor = event.start
        while cursor < event.end:
            piece_end = min(_midnight(cursor) + timedelta(days=1), event.end)
            minutes = int((piece_end - cursor).total_seconds()) // 60
            start_minute = _minute_of_day(cursor)

            grouped[cursor.date()].append(
                RodsSegment(
                    status=event.status,
                    start_minute=start_minute,
                    end_minute=start_minute + minutes,
                    kind=event.kind,
                    # Implied speed is constant within a leg, so mileage divides
                    # in proportion to minutes.
                    miles=event.miles * minutes / event.minutes,
                )
            )
            cursor = piece_end

    return {day: _merge_adjacent(segments) for day, segments in grouped.items()}


def _merge_adjacent(segments: list[RodsSegment]) -> list[RodsSegment]:
    """Collapse consecutive runs of the same status into one segment.

    The duty-status line on a paper log is continuous and only moves between rows
    at an actual change of status. A fuel stop running straight into a pickup is
    one unbroken run of on-duty time; drawing it as two abutting segments is what
    produces hairline overlaps on the grid.
    """
    merged: list[RodsSegment] = []
    for segment in segments:
        previous = merged[-1] if merged else None
        if previous is None or previous.status is not segment.status:
            merged.append(segment)
            continue

        # Name the run after its longest constituent, so a merged run reads as the
        # 34-hour restart and not the few minutes of padding before it.
        kind = previous.kind if previous.minutes >= segment.minutes else segment.kind
        merged[-1] = RodsSegment(
            status=previous.status,
            start_minute=previous.start_minute,
            end_minute=segment.end_minute,
            kind=kind,
            miles=previous.miles + segment.miles,
        )
    return merged


# --------------------------------------------------------------------------- #
# 4. Totals
# --------------------------------------------------------------------------- #


def _totals(day: Date, segments: Sequence[RodsSegment]) -> dict[str, float]:
    minutes = dict.fromkeys(DUTY_STATUS_ORDER, 0)
    for segment in segments:
        minutes[segment.status.value] += segment.minutes

    counted = sum(minutes.values())
    if counted != MINUTES_PER_DAY:
        raise RodsIntegrityError(
            f"Log sheet for {day.isoformat()} accounts for {counted} minutes, not "
            f"{MINUTES_PER_DAY}. A sheet that does not total 24:00 is not a valid RODS."
        )

    # Every duration is a whole number of quarter hours, so these divisions are
    # exact in binary floating point and the four rows sum to 24.0 exactly.
    totals = {status: minutes[status] / 60 for status in DUTY_STATUS_ORDER}
    totals["total"] = sum(totals.values())
    return totals


# --------------------------------------------------------------------------- #
# 5. Remarks
# --------------------------------------------------------------------------- #


def _remarks_by_date(events: Sequence[DutyEvent]) -> dict[Date, list[Remark]]:
    """One entry per change of duty status, per §395.8(a).

    Computed on the whole padded timeline before it is split, so a segment that
    merely continues across midnight is not reported as a change.
    """
    grouped: dict[Date, list[Remark]] = defaultdict(list)

    # The first real event announces itself. Nothing precedes it to change from,
    # but the driver went on duty (or began a restart) somewhere and the sheet has
    # to say so. Two cases need this: a departure at exactly midnight has no
    # leading pad to change away from, and a trip that opens with a 34-hour
    # restart is off duty just like the pad before it, so a status-change-only
    # rule would leave a blank 24-hour sheet unexplained. The pad itself is
    # exempt, since midnight-to-departure is not a change of anything.
    first_reportable = next((index for index, e in enumerate(events) if e.kind != "pad"), None)

    for index, event in enumerate(events):
        changed = index > 0 and events[index - 1].status is not event.status
        if index != first_reportable and not changed:
            continue

        grouped[event.start.date()].append(
            Remark(
                minute=_minute_of_day(event.start),
                location=_location_of(event),
                note=event.note or FALLBACK_NOTES.get(event.kind, "Change of duty status"),
            )
        )

    return grouped


def mile_marker_label(at_mile: float | None) -> str:
    """The label a stop wears when reverse geocoding could not name the place.

    Shared with the planner so the itinerary and the remarks strip agree on what
    to call the same point on the route.
    """
    if at_mile is None:
        return "On route"
    return f"Near mile {round(at_mile):,} on route"


def _location_of(event: DutyEvent) -> str:
    """A remark is never blank, even when reverse geocoding was unavailable."""
    return event.location or mile_marker_label(event.at_mile)


# --------------------------------------------------------------------------- #
# Guards and small helpers
# --------------------------------------------------------------------------- #


def _require_contiguous(events: Sequence[DutyEvent]) -> None:
    if not events:
        raise RodsIntegrityError("Cannot build log sheets from an empty timeline.")

    for earlier, later in zip(events, events[1:], strict=False):
        if earlier.end != later.start:
            raise RodsIntegrityError(
                f"Timeline is not contiguous: {earlier.kind} ends "
                f"{earlier.end.isoformat()} but {later.kind} starts {later.start.isoformat()}."
            )


def _require_consecutive(dates: Sequence[Date]) -> None:
    for earlier, later in zip(dates, dates[1:], strict=False):
        if later - earlier != timedelta(days=1):
            raise RodsIntegrityError(
                f"Calendar gap between log sheets: {earlier.isoformat()} then {later.isoformat()}."
            )


def _midnight(moment: datetime) -> datetime:
    return datetime.combine(moment.date(), time.min)


def _minute_of_day(moment: datetime) -> int:
    return moment.hour * 60 + moment.minute
