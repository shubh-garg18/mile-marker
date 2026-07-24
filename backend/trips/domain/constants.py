"""Every number the simulation depends on, with its source.

No duration is hard-coded anywhere else in the project. Each value below is a
regulatory limit from 49 CFR Part 395, a figure fixed by the brief, or an
assumption recorded in docs/design-decisions.md.

Every regulatory constant here divides evenly by QUANTUM_MINUTES. That is what
lets the simulation run on integer minutes and land exactly on the limits.
"""

from datetime import time

# --- Regulatory limits: 49 CFR Part 395, property-carrying CMV ---

MAX_DRIVING_MINUTES_PER_SHIFT = 11 * 60
"""§395.3(a)(3). At most 11 hours driving after 10 consecutive hours off duty."""

MAX_WINDOW_MINUTES = 14 * 60
"""§395.3(a)(2). No driving beyond the 14th consecutive hour after coming on duty.
Elapsed wall time; it never pauses."""

DRIVING_MINUTES_BEFORE_BREAK = 8 * 60
"""§395.3(a)(3)(ii). 8 cumulative driving hours without a qualifying interruption."""

BREAK_MINUTES = 30
"""The interruption must be 30 consecutive minutes. Short periods cannot be summed."""

RESET_MINUTES = 10 * 60
"""§395.3(a)(1). Ten consecutive hours off duty or in the sleeper berth before
driving may begin again."""

CYCLE_LIMIT_MINUTES = 70 * 60
"""§395.3(b)(2). 70 on-duty hours in 8 consecutive days."""

RESTART_MINUTES = 34 * 60
"""§395.3(c). 34 consecutive hours off duty returns the cycle to zero."""

# --- From the brief ---

FUEL_INTERVAL_MILES = 1000
"""Fueling at least once every 1,000 miles."""

PICKUP_MINUTES = 60
DROPOFF_MINUTES = 60
"""One hour each for pickup and dropoff."""

# --- Assumptions (see docs/design-decisions.md) ---

FUEL_STOP_MINUTES = 30
"""On duty, not driving. Thirty consecutive non-driving minutes also satisfies the
break requirement, so fuel stops and breaks often coincide."""

DEFAULT_START_TIME = time(8, 0)
"""08:00 home-terminal time. No separate pre-trip inspection is modeled."""

QUANTUM_MINUTES = 15
"""All timeline arithmetic runs on this lattice, the same one the log grid uses."""

REST_STATUS = "sleeper_berth"
"""10-hour resets are logged as sleeper berth; a 34-hour restart is logged as off duty."""

MAX_ROUTE_KM = 6000
"""OpenRouteService caps driving profiles at 6,000 km per route."""

MAX_IMPLIED_MPH = FUEL_INTERVAL_MILES * 60 / QUANTUM_MINUTES
"""The speed above which the drive loop could not terminate: 4,000 mph.

Above this, a full fuel interval takes less than one quantum of driving, so the
loop would resolve a fuel stop every iteration without the leg advancing. The
value is derived from the two constants that create the hazard so it stays
correct if either changes. Real legs run two orders of magnitude below it."""
