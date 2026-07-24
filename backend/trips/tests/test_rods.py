"""Tests for the timeline-to-log-sheets conversion.

The invariant that matters most is arithmetic: four status totals summing to
exactly 24:00. It is the first thing a reviewer or a roadside inspector
checks, so it is asserted on every fixture here and raised on in the code itself.
"""

from __future__ import annotations

from datetime import datetime, time

import pytest

from trips.domain.constants import QUANTUM_MINUTES
from trips.domain.hos import simulate
from trips.domain.models import Activity, DutyEvent, DutyStatus
from trips.domain.rods import MINUTES_PER_DAY, RodsIntegrityError, _driving_miles, build_days

START = datetime(2026, 7, 27, 8, 0)


def drive(minutes: int, miles: float, label: str = "Leg") -> Activity:
    return Activity(kind="drive", label=label, minutes=minutes, miles=miles)


def leg_at(mph: float, minutes: int, label: str = "Leg") -> Activity:
    return drive(minutes=minutes, miles=minutes / 60 * mph, label=label)


def pickup(minutes: int = 60) -> Activity:
    return Activity(kind="task", label="Loading", minutes=minutes, task_kind="pickup")


def dropoff(minutes: int = 60) -> Activity:
    return Activity(kind="task", label="Unloading", minutes=minutes, task_kind="dropoff")


def located(events: list[DutyEvent]) -> list[DutyEvent]:
    """Stand in for the planner, which resolves a location label per event."""
    from dataclasses import replace

    return [replace(event, location="Amarillo, TX") for event in events]


TIMELINES = {
    "short single day": ([leg_at(60, 120), pickup(), leg_at(60, 180), dropoff()], 0),
    "overnight": ([leg_at(62, 900), pickup(), leg_at(62, 300), dropoff()], 0),
    "long haul": ([leg_at(58, 1800), pickup(), leg_at(58, 900), dropoff()], 20 * 60),
    "restart required": ([leg_at(60, 600), pickup(), leg_at(60, 300), dropoff()], 68 * 60),
    "starts at 20:00": ([leg_at(60, 360)], 0),
}


def timeline(name: str, start: datetime = START) -> list[DutyEvent]:
    activities, cycle_used = TIMELINES[name]
    return located(simulate(activities, cycle_used_minutes=cycle_used, start_dt=start))


# --------------------------------------------------------------------------- #
# The totals invariant
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", list(TIMELINES))
def test_every_sheet_totals_exactly_twenty_four_hours(name):
    for day in build_days(timeline(name)):
        assert day.totals["total"] == 24.0
        four_rows = sum(
            day.totals[status]
            for status in ("off_duty", "sleeper_berth", "driving", "on_duty_not_driving")
        )
        assert four_rows == 24.0


@pytest.mark.parametrize("name", list(TIMELINES))
def test_segments_tile_the_whole_day_without_gaps(name):
    for day in build_days(timeline(name)):
        assert day.segments[0].start_minute == 0
        assert day.segments[-1].end_minute == MINUTES_PER_DAY
        for earlier, later in zip(day.segments, day.segments[1:], strict=False):
            assert earlier.end_minute == later.start_minute
        assert all(segment.minutes > 0 for segment in day.segments)
        assert all(segment.minutes % QUANTUM_MINUTES == 0 for segment in day.segments)


# --------------------------------------------------------------------------- #
# Splitting at midnight
# --------------------------------------------------------------------------- #


def test_a_segment_crossing_midnight_splits_with_mileage_in_proportion_to_minutes():
    events = timeline("starts at 20:00", start=datetime(2026, 7, 27, 20, 0))
    days = build_days(events)

    assert [day.date for day in days] == ["2026-07-27", "2026-07-28"]

    first_night = next(s for s in days[0].segments if s.status is DutyStatus.DRIVING)
    assert (first_night.start_minute, first_night.end_minute) == (1200, MINUTES_PER_DAY)

    next_morning = next(s for s in days[1].segments if s.status is DutyStatus.DRIVING)
    assert (next_morning.start_minute, next_morning.end_minute) == (0, 120)

    # 360 driving minutes at 60 mph, split 240/120 across midnight.
    assert first_night.miles == pytest.approx(240.0)
    assert next_morning.miles == pytest.approx(120.0)
    assert days[0].driving_miles == 240
    assert days[1].driving_miles == 120


def test_a_thirty_four_hour_restart_produces_a_sheet_that_is_entirely_off_duty():
    events = located(simulate([leg_at(60, 300)], cycle_used_minutes=70 * 60, start_dt=START))
    days = build_days(events)

    idle = [day for day in days if day.totals["off_duty"] == 24.0]
    assert idle, "34 hours off duty must fully occupy at least one calendar day"
    assert idle[0].driving_miles == 0
    assert len(idle[0].segments) == 1


def test_day_numbers_and_dates_cover_the_calendar_span_without_holes():
    events = timeline("long haul")
    days = build_days(events)

    assert [day.day_number for day in days] == list(range(1, len(days) + 1))
    assert days[0].date == events[0].start.date().isoformat()
    assert days[-1].date == events[-1].end.date().isoformat()

    dates = [day.date for day in days]
    assert dates == sorted(dates)
    assert len(dates) == len(set(dates))


def test_a_long_trip_produces_three_or_more_sheets_with_mileage_spread_across_them():
    days = build_days(timeline("long haul"))

    assert len(days) >= 3
    assert sum(day.driving_miles for day in days) > 1800
    assert sum(1 for day in days if day.driving_miles > 0) >= 3


@pytest.mark.parametrize("name", sorted(TIMELINES))
def test_the_mileage_column_adds_up_to_the_miles_actually_driven(name: str):
    """§395.8 asks each sheet for miles driven that day, and the column has to
    total the trip. Rounding each day on its own does not achieve that: five
    days of 605.4 miles round down to a mile short of the trip."""
    activities, _ = TIMELINES[name]
    days = build_days(timeline(name))

    driven = sum(activity.miles for activity in activities)
    assert sum(day.driving_miles for day in days) == round(driven)


def test_the_mileage_remainder_goes_to_the_day_that_came_closest_to_earning_it():
    # 200.24 miles then 300.36: both days round down on their own, losing the
    # 0.6 mile between them, and the column totals 500 for a 501-mile trip.
    events = located(
        simulate([leg_at(50.06, 600)], cycle_used_minutes=0, start_dt=datetime(2026, 7, 27, 20, 0))
    )
    days = build_days(events)

    assert [round(_driving_miles(day.segments), 2) for day in days] == [200.24, 300.36]
    assert sum(round(_driving_miles(day.segments)) for day in days) == 500, "rounded in isolation"
    assert [day.driving_miles for day in days] == [200, 301]


# --------------------------------------------------------------------------- #
# Remarks
# --------------------------------------------------------------------------- #


def expected_status_changes(events: list[DutyEvent]) -> int:
    """Transitions on the padded timeline, with the driver off duty either side."""
    statuses = [event.status for event in events]
    if events[0].start != datetime.combine(events[0].start.date(), time.min):
        statuses.insert(0, DutyStatus.OFF_DUTY)
    if events[-1].end != datetime.combine(events[-1].end.date(), time.min):
        statuses.append(DutyStatus.OFF_DUTY)
    return sum(1 for a, b in zip(statuses, statuses[1:], strict=False) if a is not b)


@pytest.mark.parametrize("name", list(TIMELINES))
def test_every_status_change_gets_one_remark_with_a_location(name):
    events = timeline(name)
    days = build_days(events)

    remarks = [remark for day in days for remark in day.remarks]

    assert len(remarks) == expected_status_changes(events)
    assert all(remark.location for remark in remarks)
    assert all(remark.note for remark in remarks)
    assert all(0 <= remark.minute < MINUTES_PER_DAY for remark in remarks)


def test_a_remark_falls_back_to_a_mile_marker_when_no_location_was_resolved():
    """Remarks must never be blank, and must never block a response."""
    events = simulate([leg_at(60, 120), pickup()], cycle_used_minutes=0, start_dt=START)
    days = build_days(events)  # no locations resolved at all

    remarks = [remark for day in days for remark in day.remarks]
    assert remarks
    assert all(remark.location for remark in remarks)
    assert any("mile" in remark.location for remark in remarks)


def test_a_segment_continuing_across_midnight_is_not_reported_as_a_status_change():
    events = timeline("starts at 20:00", start=datetime(2026, 7, 27, 20, 0))
    days = build_days(events)

    assert all(remark.minute != 0 for remark in days[1].remarks)


# --------------------------------------------------------------------------- #
# The integrity check itself
# --------------------------------------------------------------------------- #


def test_a_timeline_with_a_hole_in_it_raises_rather_than_emitting_a_bad_sheet():
    events = [
        DutyEvent(
            status=DutyStatus.DRIVING,
            start=datetime(2026, 7, 27, 8, 0),
            end=datetime(2026, 7, 27, 12, 0),
            kind="drive",
        ),
        DutyEvent(  # an hour unaccounted for
            status=DutyStatus.OFF_DUTY,
            start=datetime(2026, 7, 27, 13, 0),
            end=datetime(2026, 7, 27, 14, 0),
            kind="break",
        ),
    ]
    with pytest.raises(RodsIntegrityError):
        build_days(events)


def test_an_empty_timeline_raises():
    with pytest.raises(RodsIntegrityError):
        build_days([])
