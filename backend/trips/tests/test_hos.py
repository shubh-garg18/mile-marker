"""The priority suite: proof that the simulator obeys 49 CFR Part 395.

These tests construct activity lists directly. No network, no Django, no fixtures
from the routing layer, which is the point of keeping `trips.domain` pure, and the
architectural guard at the bottom of this file enforces it.

Scenarios are numbered for reference from the section headings below.
"""

from __future__ import annotations

import ast
import os
import random
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from trips.domain.constants import (
    BREAK_MINUTES,
    CYCLE_LIMIT_MINUTES,
    DRIVING_MINUTES_BEFORE_BREAK,
    DROPOFF_MINUTES,
    FUEL_INTERVAL_MILES,
    FUEL_STOP_MINUTES,
    MAX_DRIVING_MINUTES_PER_SHIFT,
    MAX_WINDOW_MINUTES,
    PICKUP_MINUTES,
    QUANTUM_MINUTES,
    RESET_MINUTES,
    RESTART_MINUTES,
)
from trips.domain.hos import cycle_minutes_at_end, simulate
from trips.domain.models import Activity, DutyEvent, DutyStatus

START = datetime(2026, 7, 27, 8, 0)

#: A 10-hour reset or a 34-hour restart both end a shift and start a fresh one.
SHIFT_BOUNDARY_KINDS = {"reset", "restart"}


# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #


def drive(minutes: int, miles: float, label: str = "Leg") -> Activity:
    return Activity(kind="drive", label=label, minutes=minutes, miles=miles)


def leg_at(mph: float, minutes: int, label: str = "Leg") -> Activity:
    """A drive leg of `minutes` at a given implied speed."""
    return drive(minutes=minutes, miles=minutes / 60 * mph, label=label)


def pickup(minutes: int = 60, label: str = "Loading") -> Activity:
    return Activity(kind="task", label=label, minutes=minutes, task_kind="pickup")


def dropoff(minutes: int = 60, label: str = "Unloading") -> Activity:
    return Activity(kind="task", label=label, minutes=minutes, task_kind="dropoff")


def kinds(events: list[DutyEvent]) -> list[str]:
    return [event.kind for event in events]


def shifts(events: list[DutyEvent]) -> list[list[DutyEvent]]:
    """Split a timeline at every 10-hour reset and 34-hour restart.

    The boundary event belongs to neither shift: it is the off-duty period between
    them, and it is what makes the next 11- and 14-hour allowances legal.
    """
    grouped: list[list[DutyEvent]] = [[]]
    for event in events:
        if event.kind in SHIFT_BOUNDARY_KINDS:
            grouped.append([])
        else:
            grouped[-1].append(event)
    return [shift for shift in grouped if shift]


# --------------------------------------------------------------------------- #
# 1. A short trip needs no intervention
# --------------------------------------------------------------------------- #


def test_short_trip_inserts_no_rest_and_keeps_driving_under_the_limit():
    events = simulate(
        [leg_at(60, 120), pickup(), leg_at(60, 180), dropoff()],
        cycle_used_minutes=0,
        start_dt=START,
    )

    assert "reset" not in kinds(events)
    assert "restart" not in kinds(events)
    assert "break" not in kinds(events)
    assert "fuel" not in kinds(events)

    driving = sum(e.minutes for e in events if e.status is DutyStatus.DRIVING)
    assert driving == 300
    assert driving <= 660  # literal: 11 h, §395.3(a)(3)

    assert kinds(events).count("pickup") == 1
    assert kinds(events).count("dropoff") == 1


# --------------------------------------------------------------------------- #
# 2. The 11-hour driving limit
# --------------------------------------------------------------------------- #


def test_reset_is_inserted_once_driving_reaches_exactly_eleven_hours():
    events = simulate([leg_at(60, 15 * 60)], cycle_used_minutes=0, start_dt=START)

    resets = [e for e in events if e.kind == "reset"]
    assert resets, "a 15-hour drive must force a 10-hour reset"

    first_reset = events.index(resets[0])
    driving_before = sum(e.minutes for e in events[:first_reset] if e.status is DutyStatus.DRIVING)
    assert driving_before == 660  # literal: 11 h, §395.3(a)(3)

    assert resets[0].minutes == RESET_MINUTES == 600
    assert resets[0].status is DutyStatus.SLEEPER_BERTH

    after = events[first_reset + 1 :]
    assert any(e.status is DutyStatus.DRIVING for e in after), "driving resumes after the reset"


# --------------------------------------------------------------------------- #
# 3. The 30-minute break
# --------------------------------------------------------------------------- #


def test_break_appears_after_eight_cumulative_driving_hours():
    events = simulate([leg_at(60, 10 * 60)], cycle_used_minutes=0, start_dt=START)

    breaks = [e for e in events if e.kind == "break"]
    assert len(breaks) == 1

    first_break = events.index(breaks[0])
    driving_before = sum(e.minutes for e in events[:first_break] if e.status is DutyStatus.DRIVING)
    assert driving_before == 480  # literal: 8 h, §395.3(a)(3)(ii)
    assert breaks[0].minutes == 30
    assert breaks[0].status is DutyStatus.OFF_DUTY


def test_break_does_not_extend_the_fourteen_hour_window():
    """The break consumes window time; it never buys any back. §395.3(a)(2).

    Note what is *not* asserted here: that the shift itself fits inside 14 hours.
    It need not. The FMCSA guide's worked example (p.18) says plainly, "There is
    no problem with being on duty longer than 14 hours as long as there is no CMV
    driving time after the 14th hour." The rule bounds driving, not the shift.
    """
    events = simulate([leg_at(60, 10 * 60)], cycle_used_minutes=0, start_dt=START)

    first_shift = shifts(events)[0]
    shift_start = first_shift[0].start
    assert any(event.kind == "break" for event in first_shift)

    for event in first_shift:
        if event.status is DutyStatus.DRIVING:
            driving_ended_at = (event.end - shift_start).total_seconds() / 60
            assert driving_ended_at <= 840  # literal: 14 h, §395.3(a)(2)


def test_a_shift_may_run_past_fourteen_hours_as_long_as_no_driving_follows():
    """The counterpart to the test above, on a timeline that really does exceed it."""
    events = simulate(
        [leg_at(60, 600), pickup(minutes=240, label="Detention at dock"), dropoff()],
        cycle_used_minutes=0,
        start_dt=START,
    )

    first_shift = shifts(events)[0]
    shift_start = first_shift[0].start
    elapsed = (first_shift[-1].end - shift_start).total_seconds() / 60
    assert elapsed > 840, "this fixture is only interesting if the shift overruns"

    for event in first_shift:
        if event.status is DutyStatus.DRIVING:
            assert (event.end - shift_start).total_seconds() / 60 <= 840


# --------------------------------------------------------------------------- #
# 4. A fuel stop satisfies the break
# --------------------------------------------------------------------------- #


def test_fuel_stop_before_the_break_trigger_removes_the_need_for_a_break():
    """A 30-minute non-driving interruption qualifies, whatever its purpose.

    The implied speed here is deliberately unrealistic: it places the 1,000-mile
    fuel boundary at 7 driving hours, just before the 8-hour break trigger, which
    is the interaction under test.
    """
    events = simulate(
        [drive(minutes=630, miles=1500, label="High-speed leg")],
        cycle_used_minutes=0,
        start_dt=START,
    )

    assert kinds(events).count("fuel") == 1
    assert "break" not in kinds(events), "the fuel stop already interrupted the driving"

    fuel = next(e for e in events if e.kind == "fuel")
    assert fuel.minutes == 30
    assert fuel.status is DutyStatus.ON_DUTY_NOT_DRIVING

    driving_after_fuel = sum(
        e.minutes for e in events[events.index(fuel) + 1 :] if e.status is DutyStatus.DRIVING
    )
    assert driving_after_fuel < DRIVING_MINUTES_BEFORE_BREAK


# --------------------------------------------------------------------------- #
# 5. The window can bind before the driving limit does
# --------------------------------------------------------------------------- #


def test_window_expires_before_eleven_driving_hours_when_dwell_time_is_long():
    """The 14-hour clock is elapsed wall time and never pauses.

    Five hours of detention leave only three of window, so the driver is parked
    with unused driving hours in hand. This is the single most mis-modeled rule in
    the domain, which is why it gets an explicit test.
    """
    events = simulate(
        [leg_at(60, 240), pickup(minutes=300, label="Detention at dock"), leg_at(60, 600)],
        cycle_used_minutes=0,
        start_dt=START,
    )

    resets = [e for e in events if e.kind == "reset"]
    assert resets, "the window must run out and force a reset"

    first_reset = events.index(resets[0])
    driving_before = sum(e.minutes for e in events[:first_reset] if e.status is DutyStatus.DRIVING)
    assert driving_before < MAX_DRIVING_MINUTES_PER_SHIFT, (
        "the window bound first, not the 11-hour limit"
    )

    window_elapsed = (resets[0].start - events[0].start).total_seconds() / 60
    assert window_elapsed == MAX_WINDOW_MINUTES


# --------------------------------------------------------------------------- #
# 6. Fuel every 1,000 miles
# --------------------------------------------------------------------------- #


def test_long_trip_fuels_at_every_thousand_mile_boundary():
    mph = 60
    events = simulate([leg_at(mph, 2100)], cycle_used_minutes=0, start_dt=START)

    fuel_stops = [e for e in events if e.kind == "fuel"]
    assert len(fuel_stops) == 2

    # Each stop lands within one quantum of driving *below* its 1,000-mile mark,
    # and that shortfall carries into the next one, so the allowance accumulates.
    tolerance_miles = QUANTUM_MINUTES / 60 * mph
    for index, stop in enumerate(fuel_stops, start=1):
        assert stop.at_mile is not None
        assert index * FUEL_INTERVAL_MILES - index * tolerance_miles <= stop.at_mile
        assert stop.at_mile <= index * FUEL_INTERVAL_MILES


@pytest.mark.parametrize("mph,minutes", [(60, 2100), (62, 3000), (55, 3990), (68, 1200)])
def test_the_truck_never_travels_more_than_the_fuel_interval_without_fuelling(mph, minutes):
    """The brief's rule is "at least once every 1,000 miles", so it is the *gap*
    between consecutive stops that is bounded, not merely that each 1,000-mile
    block contains one.

    Because a stop lands up to a quantum early, the next interval is measured from
    where it actually happened. Anchoring to the round mark instead would let a gap
    reach 1,000 miles plus that shortfall.
    """
    events = simulate([leg_at(mph, minutes)], cycle_used_minutes=0, start_dt=START)

    milestones = [0.0] + [e.at_mile for e in events if e.kind == "fuel" and e.at_mile is not None]
    total_miles = minutes / 60 * mph

    for before, after in zip(milestones, milestones[1:], strict=False):
        assert after - before <= FUEL_INTERVAL_MILES

    # And the trip does not simply end early to dodge the rule.
    assert total_miles - milestones[-1] <= FUEL_INTERVAL_MILES


# --------------------------------------------------------------------------- #
# 7 & 8. The 70-hour cycle and the 34-hour restart
# --------------------------------------------------------------------------- #


def test_restart_is_inserted_before_the_cycle_would_exceed_seventy_hours():
    events = simulate([leg_at(60, 300)], cycle_used_minutes=68 * 60, start_dt=START)

    restarts = [e for e in events if e.kind == "restart"]
    assert len(restarts) == 1
    assert restarts[0].minutes == RESTART_MINUTES == 2040
    assert restarts[0].status is DutyStatus.OFF_DUTY

    driving_before = sum(
        e.minutes for e in events[: events.index(restarts[0])] if e.status is DutyStatus.DRIVING
    )
    assert 68 * 60 + driving_before == CYCLE_LIMIT_MINUTES


def test_exhausted_cycle_forces_a_restart_before_any_driving_at_all():
    events = simulate([leg_at(60, 120), dropoff()], cycle_used_minutes=70 * 60, start_dt=START)

    first_driving = next(i for i, e in enumerate(events) if e.status is DutyStatus.DRIVING)
    assert "restart" in kinds(events[:first_driving])
    assert events[0].kind == "restart"


def test_restart_returns_the_cycle_to_zero():
    events = simulate([leg_at(60, 300)], cycle_used_minutes=68 * 60, start_dt=START)

    ended_with = cycle_minutes_at_end(events, cycle_used_minutes=68 * 60)
    driving_after_restart = sum(
        e.minutes
        for e in events[events.index(next(e for e in events if e.kind == "restart")) + 1 :]
        if e.counts_against_cycle
    )
    assert ended_with == driving_after_restart


# --------------------------------------------------------------------------- #
# 9. Non-driving work is never blocked
# --------------------------------------------------------------------------- #


def test_dropoff_still_happens_past_hour_fourteen_but_driving_does_not():
    """Only driving is gated. A driver past the window may still work on duty."""
    events = simulate(
        [
            leg_at(60, 600),
            pickup(minutes=240, label="Detention at dock"),
            dropoff(),
            leg_at(60, 60, label="Deadhead home"),
        ],
        cycle_used_minutes=0,
        start_dt=START,
    )

    unload = next(e for e in events if e.kind == "dropoff")
    window_elapsed = (unload.start - events[0].start).total_seconds() / 60
    assert window_elapsed > MAX_WINDOW_MINUTES, "the dropoff happens past the 14-hour window"
    assert unload.status is DutyStatus.ON_DUTY_NOT_DRIVING

    after_unload = events[events.index(unload) + 1 :]
    driving_index = next(i for i, e in enumerate(after_unload) if e.status is DutyStatus.DRIVING)
    assert "reset" in kinds(after_unload[:driving_index]), "driving may only resume after a reset"


# --------------------------------------------------------------------------- #
# 10. The timeline is a tiling
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "activities,cycle_used",
    [
        ([leg_at(60, 120), pickup(), leg_at(60, 180), dropoff()], 0),
        ([leg_at(58, 2400), pickup(), leg_at(58, 1200), dropoff()], 30 * 60),
        ([leg_at(65, 90), pickup(), leg_at(65, 45), dropoff()], 69 * 60),
    ],
)
def test_events_are_contiguous_and_non_overlapping(activities, cycle_used):
    events = simulate(activities, cycle_used_minutes=cycle_used, start_dt=START)

    assert events[0].start == START
    for earlier, later in zip(events, events[1:], strict=False):
        assert earlier.end == later.start
    assert all(e.minutes > 0 for e in events)
    assert all(e.minutes % QUANTUM_MINUTES == 0 for e in events)


# --------------------------------------------------------------------------- #
# 11. Property test: the limits hold over randomized trips
# --------------------------------------------------------------------------- #


def _random_trip(rng: random.Random) -> tuple[list[Activity], int]:
    def random_leg(label: str) -> Activity:
        minutes = QUANTUM_MINUTES * rng.randint(4, 140)  # 1 h – 35 h
        return drive(minutes=minutes, miles=minutes / 60 * rng.uniform(45, 68), label=label)

    activities = [
        random_leg("Current to pickup"),
        pickup(minutes=QUANTUM_MINUTES * rng.randint(2, 20)),
        random_leg("Pickup to dropoff"),
        dropoff(minutes=QUANTUM_MINUTES * rng.randint(2, 20)),
    ]
    return activities, QUANTUM_MINUTES * rng.randint(0, 280)  # 0 h – 70 h


def test_property_limits_hold_across_randomized_trips():
    rng = random.Random(20260727)

    for _ in range(200):
        activities, cycle_used = _random_trip(rng)
        events = simulate(activities, cycle_used_minutes=cycle_used, start_dt=START)

        for earlier, later in zip(events, events[1:], strict=False):
            assert earlier.end == later.start

        for shift in shifts(events):
            shift_start = shift[0].start

            driving = sum(e.minutes for e in shift if e.status is DutyStatus.DRIVING)
            assert driving <= MAX_DRIVING_MINUTES_PER_SHIFT

            for event in shift:
                if event.status is DutyStatus.DRIVING:
                    elapsed = (event.end - shift_start).total_seconds() / 60
                    assert elapsed <= MAX_WINDOW_MINUTES

            since_break = 0
            for event in shift:
                if event.status is DutyStatus.DRIVING:
                    since_break += event.minutes
                    assert since_break <= DRIVING_MINUTES_BEFORE_BREAK
                elif event.minutes >= 30:
                    since_break = 0

        cycle = cycle_used
        for event in events:
            if event.kind == "restart":
                cycle = 0
                continue
            if event.status is DutyStatus.DRIVING:
                assert cycle < CYCLE_LIMIT_MINUTES, "driving began with the cycle exhausted"
            if event.counts_against_cycle:
                cycle += event.minutes


# --------------------------------------------------------------------------- #
# The regulation itself
# --------------------------------------------------------------------------- #


def test_the_regulatory_limits_are_the_numbers_the_cfr_says_they_are():
    """Pin every limit to a literal, cited to its paragraph.

    Every other test in this file asserts behaviour *relative* to these constants,
    which means changing one moves the assertions with it and the suite stays
    green. This is the only test that would notice the 11-hour driving limit
    quietly becoming twelve.
    """
    assert MAX_DRIVING_MINUTES_PER_SHIFT == 11 * 60  # §395.3(a)(3)
    assert MAX_WINDOW_MINUTES == 14 * 60  # §395.3(a)(2)
    assert DRIVING_MINUTES_BEFORE_BREAK == 8 * 60  # §395.3(a)(3)(ii)
    assert BREAK_MINUTES == 30  # §395.3(a)(3)(ii)
    assert RESET_MINUTES == 10 * 60  # §395.3(a)(1)
    assert CYCLE_LIMIT_MINUTES == 70 * 60  # §395.3(b)(2)
    assert RESTART_MINUTES == 34 * 60  # §395.3(c)
    assert FUEL_INTERVAL_MILES == 1000  # from the brief
    assert PICKUP_MINUTES == 60 and DROPOFF_MINUTES == 60  # from the brief
    assert QUANTUM_MINUTES == 15

    # The lattice argument the whole engine rests on: every regulatory duration is
    # a whole number of quarter hours, so a limit can be reached exactly.
    for minutes in (
        MAX_DRIVING_MINUTES_PER_SHIFT,
        MAX_WINDOW_MINUTES,
        DRIVING_MINUTES_BEFORE_BREAK,
        BREAK_MINUTES,
        RESET_MINUTES,
        CYCLE_LIMIT_MINUTES,
        RESTART_MINUTES,
        FUEL_STOP_MINUTES,
        PICKUP_MINUTES,
        DROPOFF_MINUTES,
    ):
        assert minutes % QUANTUM_MINUTES == 0


# --------------------------------------------------------------------------- #
# The 30-minute break is 30 *consecutive* minutes
# --------------------------------------------------------------------------- #


def test_two_consecutive_short_stops_together_satisfy_the_break():
    """§395.3(a)(3)(ii), and the guide's own worked example (p.10):

    "a driver could take 15 minutes of on-duty not driving time plus 15 minutes of
    off-duty time to satisfy his or her 30-minute requirement, as long as those
    two periods are consecutive."
    """
    events = simulate(
        [leg_at(60, 480), pickup(minutes=15), dropoff(minutes=15), leg_at(60, 60)],
        cycle_used_minutes=0,
        start_dt=START,
    )

    assert "break" not in kinds(events), "30 consecutive non-driving minutes were served"


def test_short_stops_split_by_driving_do_not_add_up_to_a_break():
    """The other half of the rule: non-consecutive periods cannot be summed."""
    events = simulate(
        [leg_at(60, 480), pickup(minutes=15), leg_at(60, 15), dropoff(minutes=15), leg_at(60, 60)],
        cycle_used_minutes=0,
        start_dt=START,
    )

    assert "break" in kinds(events), "driving in between broke the interruption"


def test_a_single_stop_shorter_than_thirty_minutes_does_not_satisfy_the_break():
    events = simulate(
        [leg_at(60, 480), pickup(minutes=15), leg_at(60, 60)],
        cycle_used_minutes=0,
        start_dt=START,
    )

    assert "break" in kinds(events)


def test_a_stop_of_exactly_thirty_minutes_does_satisfy_the_break():
    events = simulate(
        [leg_at(60, 480), pickup(minutes=30), leg_at(60, 60)],
        cycle_used_minutes=0,
        start_dt=START,
    )

    assert "break" not in kinds(events)


# --------------------------------------------------------------------------- #
# Precedence, and what each remedy actually resets
# --------------------------------------------------------------------------- #


def test_an_exhausted_cycle_is_remedied_by_a_restart_not_a_reset():
    """Precedence matters: only a restart restores cycle hours, so a 10-hour reset
    here would resolve nothing and the loop would come straight back to it."""
    events = simulate([leg_at(60, 15 * 60)], cycle_used_minutes=CYCLE_LIMIT_MINUTES, start_dt=START)

    assert events[0].kind == "restart"
    assert "reset" not in kinds(events[:1])


def test_a_reset_clears_the_break_counter_so_no_break_follows_it():
    """Ten hours off is emphatically an interruption; emitting a 30-minute break
    immediately afterwards would be absurd on the sheet."""
    events = simulate([leg_at(60, 20 * 60)], cycle_used_minutes=0, start_dt=START)

    resets = [i for i, e in enumerate(events) if e.kind == "reset"]
    assert resets
    for index in resets:
        assert events[index + 1].kind != "break"


def test_a_restart_restores_a_full_eleven_hours_of_driving():
    """§395.3(c) resets the cycle and, incidentally, everything else."""
    events = simulate([leg_at(60, 12 * 60)], cycle_used_minutes=CYCLE_LIMIT_MINUTES, start_dt=START)

    restart_at = next(i for i, e in enumerate(events) if e.kind == "restart")
    after = events[restart_at + 1 :]

    driving_before_next_rest = 0
    for event in after:
        if event.kind in SHIFT_BOUNDARY_KINDS:
            break
        if event.status is DutyStatus.DRIVING:
            driving_before_next_rest += event.minutes

    assert driving_before_next_rest == 660, "a full 11 hours was available after the restart"


# --------------------------------------------------------------------------- #
# Contract guards
# --------------------------------------------------------------------------- #


def test_simulate_rejects_input_that_is_off_the_quarter_hour_lattice():
    with pytest.raises(ValueError):
        simulate([leg_at(60, 120)], cycle_used_minutes=37, start_dt=START)

    with pytest.raises(ValueError):
        simulate([drive(minutes=37, miles=40)], cycle_used_minutes=0, start_dt=START)

    with pytest.raises(ValueError):
        simulate([leg_at(60, 120)], cycle_used_minutes=0, start_dt=START + timedelta(minutes=7))


def test_simulate_rejects_a_cycle_figure_outside_the_legal_range():
    with pytest.raises(ValueError):
        simulate([leg_at(60, 120)], cycle_used_minutes=-15, start_dt=START)

    with pytest.raises(ValueError):
        simulate([leg_at(60, 120)], cycle_used_minutes=CYCLE_LIMIT_MINUTES + 15, start_dt=START)


def test_zero_distance_leg_does_not_divide_by_zero():
    events = simulate(
        [drive(minutes=60, miles=0.0, label="Yard move")], cycle_used_minutes=0, start_dt=START
    )
    assert sum(e.minutes for e in events if e.status is DutyStatus.DRIVING) == 60
    assert "fuel" not in kinds(events)


BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
FORBIDDEN_IN_DOMAIN = ("django", "requests", "rest_framework")


def _module_names(package: str) -> list[str]:
    """Every module in a `trips` subpackage, recursively."""
    directory = BACKEND_ROOT / "trips" / package
    return sorted(
        f"trips.{package}."
        + path.relative_to(directory).with_suffix("").as_posix().replace("/", ".")
        for path in directory.rglob("*.py")
        if path.name != "__init__.py"
    )


def _imported_roots(module_name: str) -> set[str]:
    """Top-level packages a module imports, following relative imports too."""
    path = BACKEND_ROOT / (module_name.replace(".", "/") + ".py")
    package = module_name.rsplit(".", 1)[0]
    tree = ast.parse(path.read_text(), filename=str(path))

    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # A relative import resolves against this module's own package, so
            # `from ..api import errors` must be caught as `trips.api`.
            resolved = node.module or ""
            if node.level:
                prefix = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
                resolved = f"{prefix}.{resolved}" if resolved else prefix
            if resolved:
                roots.add(resolved)
    return roots


def test_the_domain_layer_imports_neither_django_nor_requests():
    """The architectural guard, part one: the engine runs framework-free.

    A static scan, which is fast and pinpoints the offending file. It is backed by
    the runtime check below. On its own an AST scan can be walked around with
    `importlib`, a relative import, or a transitive hop through another module.
    """
    modules = _module_names("domain")
    assert modules, "expected to find modules under trips/domain/"

    for module_name in modules:
        roots = _imported_roots(module_name)
        offenders = {root for root in roots if root.split(".")[0] in FORBIDDEN_IN_DOMAIN}
        offenders |= {root for root in roots if root.startswith(("trips.services", "trips.api"))}
        assert not offenders, f"{module_name} imports {sorted(offenders)}"


def test_importing_the_domain_layer_does_not_load_django_at_runtime():
    """The architectural guard, part two: proof rather than inspection.

    Each domain module is imported in a clean subprocess and `sys.modules` is
    examined afterwards. This catches what the AST scan cannot: a transitive
    import through a sibling, an `importlib.import_module` call, or anything else
    that pulls the framework in by a route nobody thought to look for.
    """
    for module_name in _module_names("domain"):
        probe = (
            "import sys, importlib;"
            f"importlib.import_module({module_name!r});"
            f"print(sorted(m for m in {FORBIDDEN_IN_DOMAIN!r} if m in sys.modules))"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=BACKEND_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
        )
        assert result.returncode == 0, f"{module_name} failed to import alone:\n{result.stderr}"
        assert result.stdout.strip() == "[]", f"{module_name} pulled in {result.stdout.strip()}"


def test_the_service_layer_does_not_import_the_api_layer():
    """The architectural guard, part three: `services` never reaches upward.

    This is the direction the guard used not to look, and the direction in which
    the rule had already been broken. The error taxonomy now lives in
    `trips/services/errors.py` precisely so that it cannot be.
    """
    for module_name in _module_names("services"):
        offenders = {root for root in _imported_roots(module_name) if root.startswith("trips.api")}
        assert not offenders, f"{module_name} imports {sorted(offenders)}"
