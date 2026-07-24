"""Value objects and counters used by the simulator.

Pure Python: no Django, no I/O, no clock reads, so the engine can be exercised
from a test file with DJANGO_SETTINGS_MODULE unset.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal

# The four rows of a Record of Duty Status, in the order they appear on the form.
DUTY_STATUS_ORDER: tuple[str, ...] = (
    "off_duty",
    "sleeper_berth",
    "driving",
    "on_duty_not_driving",
)


class DutyStatus(StrEnum):
    OFF_DUTY = "off_duty"
    SLEEPER_BERTH = "sleeper_berth"
    DRIVING = "driving"
    ON_DUTY_NOT_DRIVING = "on_duty_not_driving"


#: Statuses that count against the 70-hour cycle. Off duty and sleeper berth do not.
ON_DUTY_STATUSES: frozenset[DutyStatus] = frozenset(
    {DutyStatus.DRIVING, DutyStatus.ON_DUTY_NOT_DRIVING}
)

TaskKind = Literal["pickup", "dropoff"]

#: Every value `DutyEvent.kind` may take.
EVENT_KINDS: frozenset[str] = frozenset(
    {"drive", "fuel", "break", "reset", "restart", "pickup", "dropoff", "pad"}
)


@dataclass(frozen=True, slots=True)
class Activity:
    """One planned item of work, produced from the route before the engine runs.

    A `drive` activity carries the ORS leg duration and distance. A `task` activity
    is on-duty non-driving work (loading or unloading) and covers no distance.
    """

    kind: Literal["drive", "task"]
    label: str
    minutes: int = 0
    miles: float = 0.0
    task_kind: TaskKind | None = None

    def __post_init__(self) -> None:
        if self.minutes < 0:
            raise ValueError(f"Activity minutes cannot be negative: {self.label!r}")
        if self.kind == "task" and self.task_kind is None:
            raise ValueError(f"Task activity {self.label!r} must name its task_kind")
        if self.kind == "drive" and self.task_kind is not None:
            raise ValueError(f"Drive activity {self.label!r} must not carry a task_kind")


@dataclass(frozen=True, slots=True)
class DutyEvent:
    """One contiguous block of a single duty status on the timeline.

    Events tile the trip end to end: each one's `end` is the next one's `start`,
    with no gaps and no overlaps. `rods._require_contiguous` asserts this rather
    than assuming it, because a gap draws as a broken trace on the sheet.
    """

    status: DutyStatus
    start: datetime
    end: datetime
    kind: str
    miles: float = 0.0
    at_mile: float | None = None
    note: str = ""
    location: str = ""

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"DutyEvent {self.kind} ends before it starts")
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"Unknown DutyEvent kind: {self.kind!r}")

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds()) // 60

    @property
    def counts_against_cycle(self) -> bool:
        return self.status in ON_DUTY_STATUSES


@dataclass
class Clocks:
    """The four limits, running concurrently. Whichever expires first binds."""

    driving_minutes: int = 0
    """Driving since the last 10-hour reset. §395.3(a)(3)."""

    window_minutes: int = 0
    """Elapsed wall time since coming on duty after 10 hours off. Never pauses."""

    since_break_minutes: int = 0
    """Cumulative driving since the last 30-minute non-driving interruption."""

    cycle_minutes: int = 0
    """On-duty minutes used in the 70-hour/8-day cycle."""


@dataclass(frozen=True, slots=True)
class Remark:
    """One line in the remarks strip: when the status changed, and where."""

    minute: int
    location: str
    note: str


@dataclass(frozen=True, slots=True)
class RodsSegment:
    """One horizontal run on a log sheet's duty-status grid.

    Minutes are measured from that day's midnight, 0 to 1440, which is all the
    renderer needs: `x = 110 + minute / 60 * 36`. Keeping it in minutes means the
    frontend never parses a date to draw a line.
    """

    status: DutyStatus
    start_minute: int
    end_minute: int
    kind: str
    miles: float = 0.0

    @property
    def minutes(self) -> int:
        return self.end_minute - self.start_minute


@dataclass(frozen=True, slots=True)
class RodsDay:
    """One log sheet: a calendar date's worth of the timeline."""

    date: str
    day_number: int
    driving_miles: int
    segments: list[RodsSegment] = field(default_factory=list)
    totals: dict[str, float] = field(default_factory=dict)
    remarks: list[Remark] = field(default_factory=list)
