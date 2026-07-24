"""The hours-of-service simulator.

Pure Python: no Django imports, no network calls, no clock reads. The same
activities always produce the same timeline, which is what makes it testable.

Four limits from 49 CFR Part 395 run concurrently and any one of them can stop
driving. They are four independent counters in `Clocks`, advanced together and
consulted in a fixed precedence order (see `_resolve_blocking_constraint`).

Two properties hold by construction:

1. Only driving is gated. On-duty non-driving work such as a pickup, a dropoff or
   a dock wait is always permitted, including past the 14-hour window and past
   the 70-hour cycle. The FMCSA guide's worked example shows the same.
2. The 14-hour window never pauses, not for the break, fuel, or a short off-duty
   period. A driver can run out of window while still holding unused driving
   hours, and this simulator produces that outcome.

All arithmetic is integer minutes on a 15-minute lattice. No float touches a
duration, so limits are hit exactly.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from trips.domain.constants import (
    BREAK_MINUTES,
    CYCLE_LIMIT_MINUTES,
    DRIVING_MINUTES_BEFORE_BREAK,
    FUEL_INTERVAL_MILES,
    FUEL_STOP_MINUTES,
    MAX_DRIVING_MINUTES_PER_SHIFT,
    MAX_IMPLIED_MPH,
    MAX_WINDOW_MINUTES,
    QUANTUM_MINUTES,
    RESET_MINUTES,
    REST_STATUS,
    RESTART_MINUTES,
)
from trips.domain.models import Activity, Clocks, DutyEvent, DutyStatus

REST_DUTY_STATUS = DutyStatus(REST_STATUS)


def floor_to_quantum(minutes: float) -> int:
    """Round down to the 15-minute lattice the log grid itself uses."""
    return int(minutes // QUANTUM_MINUTES) * QUANTUM_MINUTES


def ceil_to_quantum(minutes: float) -> int:
    """Round up. Leg durations use this direction so driving time is never
    under-reported."""
    return int(math.ceil(minutes / QUANTUM_MINUTES)) * QUANTUM_MINUTES


def simulate(
    activities: Sequence[Activity],
    cycle_used_minutes: int,
    start_dt: datetime,
) -> list[DutyEvent]:
    """Turn a list of planned work into a compliant duty-status timeline.

    `cycle_used_minutes` is the driver's 70-hour/8-day figure at departure.
    `start_dt` is home-terminal local time, naive by design (§395.8(a) requires one
    time standard for the whole trip, even across time zones).

    Returns events that tile the trip end to end, with no gaps and no overlaps.
    """
    _validate(activities, cycle_used_minutes, start_dt)

    timeline = _Timeline(now=start_dt, clocks=Clocks(cycle_minutes=cycle_used_minutes))
    for activity in activities:
        if activity.kind == "task":
            timeline.work(activity)
        else:
            timeline.drive(activity)
    return timeline.events


def cycle_minutes_at_end(events: Iterable[DutyEvent], cycle_used_minutes: int) -> int:
    """The 70-hour figure the driver finishes the trip holding.

    Driving and on-duty-not-driving both spend cycle time; off duty and sleeper
    berth do not. Only a 34-hour restart gives any back.
    """
    used = cycle_used_minutes
    for event in events:
        if event.kind == "restart":
            used = 0
        elif event.counts_against_cycle:
            used += event.minutes
    return used


def _validate(activities: Sequence[Activity], cycle_used_minutes: int, start_dt: datetime) -> None:
    """Enforce the lattice invariant at the domain boundary.

    The exact 11-hour stop and the four daily totals summing to 1,440 both rest on
    every duration being a whole multiple of the quantum. Quantizing is the
    caller's job; catching a violation before it spreads is this function's.
    """
    if cycle_used_minutes % QUANTUM_MINUTES:
        raise ValueError(
            f"cycle_used_minutes must sit on the {QUANTUM_MINUTES}-minute lattice, "
            f"got {cycle_used_minutes}"
        )
    if not 0 <= cycle_used_minutes <= CYCLE_LIMIT_MINUTES:
        raise ValueError(
            f"cycle_used_minutes must be between 0 and {CYCLE_LIMIT_MINUTES}, "
            f"got {cycle_used_minutes}"
        )
    if start_dt.second or start_dt.microsecond or start_dt.minute % QUANTUM_MINUTES:
        raise ValueError(
            f"start_dt must sit on the {QUANTUM_MINUTES}-minute lattice, got {start_dt.isoformat()}"
        )
    for activity in activities:
        if activity.minutes % QUANTUM_MINUTES:
            raise ValueError(
                f"Activity {activity.label!r} is {activity.minutes} minutes, which is off the "
                f"{QUANTUM_MINUTES}-minute lattice"
            )
        _validate_speed(activity)


def _validate_speed(activity: Activity) -> None:
    """Reject a leg fast enough to break the drive loop's termination guarantee.

    The loop places fuel stops by mileage. Above `MAX_IMPLIED_MPH` a whole fuel
    interval takes less than one quantum of driving, so every iteration resolves a
    fuel stop while `miles_done` stands still, emitting events forever. Bounding
    the input here closes that off at the boundary where the lattice invariant is
    already checked, instead of defending the loop from inside.
    """
    if activity.kind != "drive" or activity.minutes <= 0 or activity.miles <= 0:
        return

    implied_mph = activity.miles / (activity.minutes / 60)
    if implied_mph > MAX_IMPLIED_MPH:
        raise ValueError(
            f"Activity {activity.label!r} implies {implied_mph:,.0f} mph "
            f"({activity.miles:,.1f} miles in {activity.minutes} minutes), above the "
            f"{MAX_IMPLIED_MPH:,.0f} mph bound the fuel-stop loop needs to terminate"
        )


@dataclass
class _Timeline:
    """Mutable simulation state: the clock, the counters, and the events so far."""

    now: datetime
    clocks: Clocks
    events: list[DutyEvent] = field(default_factory=list)
    miles_done: float = 0.0
    next_fuel_mile: float = float(FUEL_INTERVAL_MILES)
    consecutive_non_driving_minutes: int = 0
    """Unbroken non-driving time. Reaching 30 satisfies the break, whatever it was
    spent on and however many events it spans."""

    # -- emitting ----------------------------------------------------------- #

    def emit(
        self,
        status: DutyStatus,
        minutes: int,
        *,
        kind: str,
        miles: float = 0.0,
        note: str = "",
    ) -> None:
        end = self.now + timedelta(minutes=minutes)
        self.events.append(
            DutyEvent(
                status=status,
                start=self.now,
                end=end,
                kind=kind,
                miles=miles,
                at_mile=self.miles_done,
                note=note,
            )
        )
        self.now = end
        self._track_interruption(status, minutes)

    def _track_interruption(self, status: DutyStatus, minutes: int) -> None:
        """Maintain the 30-consecutive-minute break credit in one place.

        §395.3(a)(3)(ii) requires 30 consecutive minutes without driving. The FMCSA
        guide is explicit that they need not be one activity: "a driver could take
        15 minutes of on-duty not driving time plus 15 minutes of off-duty time to
        satisfy his or her 30-minute requirement, as long as those two periods are
        consecutive." Non-consecutive periods cannot be summed, which is what
        driving in between resets.
        """
        if status is DutyStatus.DRIVING:
            self.consecutive_non_driving_minutes = 0
            return

        self.consecutive_non_driving_minutes += minutes
        if self.consecutive_non_driving_minutes >= BREAK_MINUTES:
            self.clocks.since_break_minutes = 0

    # -- work --------------------------------------------------------------- #

    def work(self, activity: Activity) -> None:
        """On-duty, not driving. Never blocked, whatever the clocks say."""
        if activity.minutes <= 0:
            return

        assert activity.task_kind is not None  # guaranteed by Activity.__post_init__
        self.emit(
            DutyStatus.ON_DUTY_NOT_DRIVING,
            activity.minutes,
            kind=activity.task_kind,
            note=activity.label,
        )
        # `emit` handles the break credit via `_track_interruption`, since a
        # qualifying interruption may span several events.
        self.clocks.window_minutes += activity.minutes
        self.clocks.cycle_minutes += activity.minutes

    def drive(self, activity: Activity) -> None:
        """Drive one leg, pausing for whatever the regulations require along the way."""
        if activity.minutes <= 0:
            return

        # A constant implied speed within the leg maps mileage to time, which is
        # what lets a fuel stop be placed at a mileage rather than at a duration.
        speed = activity.miles / (activity.minutes / 60) if activity.miles > 0 else 0.0
        remaining = activity.minutes

        while remaining > 0:
            if self._resolve_blocking_constraint():
                continue

            if self._minutes_to_fuel(speed) < QUANTUM_MINUTES:
                # Fuel just before the boundary rather than just after it, so the
                # distance between two stops never exceeds the interval. The cost
                # is fueling up to one quantum early.
                self.insert_fuel()
                continue

            chunk = self._next_chunk(remaining, speed)
            chunk_miles = chunk / 60 * speed

            self.emit(
                DutyStatus.DRIVING, chunk, kind="drive", miles=chunk_miles, note=activity.label
            )
            self.clocks.driving_minutes += chunk
            self.clocks.window_minutes += chunk
            self.clocks.since_break_minutes += chunk
            self.clocks.cycle_minutes += chunk
            self.miles_done += chunk_miles
            remaining -= chunk

    # -- constraint resolution ---------------------------------------------- #

    def _resolve_blocking_constraint(self) -> bool:
        """Insert whatever the binding constraint requires. True if anything was.

        Precedence matters: a remedy that does not address the binding constraint
        resolves nothing and the loop spins. Only a restart restores cycle hours,
        so it is checked first. Only a reset restores driving hours and window, so
        it comes before the break.
        """
        if self.clocks.cycle_minutes >= CYCLE_LIMIT_MINUTES:
            self.insert_restart34()
            return True
        if (
            self.clocks.driving_minutes >= MAX_DRIVING_MINUTES_PER_SHIFT
            or self.clocks.window_minutes >= MAX_WINDOW_MINUTES
        ):
            self.insert_reset10()
            return True
        if self.clocks.since_break_minutes >= DRIVING_MINUTES_BEFORE_BREAK:
            self.insert_break30()
            return True
        return False

    def _minutes_to_fuel(self, speed: float) -> float:
        """Driving minutes left before the next 1,000-mile boundary."""
        if speed <= 0:
            return math.inf
        return floor_to_quantum((self.next_fuel_mile - self.miles_done) / speed * 60)

    def _next_chunk(self, remaining: int, speed: float) -> int:
        """How far to drive before something has to happen.

        Whichever of the four limits, the fuel boundary, or the leg itself comes
        first. Callers must have cleared `_resolve_blocking_constraint` and the
        fuel check; that is what guarantees a result of at least one quantum.
        """
        clocks = self.clocks
        chunk = floor_to_quantum(
            min(
                MAX_DRIVING_MINUTES_PER_SHIFT - clocks.driving_minutes,
                MAX_WINDOW_MINUTES - clocks.window_minutes,
                DRIVING_MINUTES_BEFORE_BREAK - clocks.since_break_minutes,
                CYCLE_LIMIT_MINUTES - clocks.cycle_minutes,
                self._minutes_to_fuel(speed),
                remaining,
            )
        )
        # Every iteration advances time by at least one quantum, which is the
        # loop's termination guarantee. It holds because each counter, limit and
        # leg duration is a whole multiple of the quantum (see `_validate`).
        assert chunk >= QUANTUM_MINUTES, f"driving chunk collapsed to {chunk} minutes"
        return chunk

    # -- insertions --------------------------------------------------------- #

    def insert_break30(self) -> None:
        """§395.3(a)(3)(ii). Off duty, and it spends window time rather than buying any."""
        self.emit(DutyStatus.OFF_DUTY, BREAK_MINUTES, kind="break", note="30-minute rest break")
        self.clocks.window_minutes += BREAK_MINUTES

    def insert_fuel(self) -> None:
        """On duty, not driving, so it costs cycle time as well as window time."""
        self.emit(DutyStatus.ON_DUTY_NOT_DRIVING, FUEL_STOP_MINUTES, kind="fuel", note="Fuel stop")
        self.clocks.window_minutes += FUEL_STOP_MINUTES
        self.clocks.cycle_minutes += FUEL_STOP_MINUTES

        # Measured from where this stop happened, not from the round 1,000-mile
        # mark it aimed at. A stop lands up to one quantum early, so anchoring the
        # next one absolutely would let the gap between two stops reach 1,000
        # miles plus that shortfall. The brief asks for fuel at least once every
        # 1,000 miles, not once per 1,000-mile block.
        self.next_fuel_mile = self.miles_done + FUEL_INTERVAL_MILES

    def insert_reset10(self) -> None:
        """Ten consecutive hours off. Resets driving, window and break, but not the cycle."""
        self.emit(REST_DUTY_STATUS, RESET_MINUTES, kind="reset", note="10-hour off-duty reset")
        self.clocks.driving_minutes = 0
        self.clocks.window_minutes = 0

    def insert_restart34(self) -> None:
        """§395.3(c). Thirty-four consecutive hours off duty: all four counters to zero."""
        self.emit(DutyStatus.OFF_DUTY, RESTART_MINUTES, kind="restart", note="34-hour restart")
        self.clocks = Clocks()
