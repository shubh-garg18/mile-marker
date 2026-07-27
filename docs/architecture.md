# Architecture

How the pieces fit, and why the boundaries sit where they do.

```
React 19 + Vite + TypeScript          Django 5.2 LTS + DRF 3.16
┌────────────────────────┐            ┌──────────────────────────────────┐
│  components/           │  HTTPS     │  trips/api/       thin views     │
│  api/client.ts         │ ────────►  │        ↓                         │
│  types/trip.ts         │            │  trips/services/  side effects   │
└────────────────────────┘            │        ↓                         │
        Vercel                        │  trips/domain/    pure Python    │
                                      └──────────────────────────────────┘
                                          Render          ↓ ORS_API_KEY
                                                   OpenRouteService
```

## Layering

Dependencies point one way: `api -> services -> domain`.

Nothing under `trips/domain/` imports Django, `requests`, or anything from the layers above it.
Nothing under `trips/services/` imports from `trips/api/`, which is why the failure taxonomy
lives in `trips/services/errors.py` rather than next to the HTTP layer that renders it.

Three tests enforce this:

1. A static scan that follows relative imports and recurses into subpackages.
2. A runtime probe that imports each domain module in a clean subprocess and inspects
   `sys.modules` afterwards.
3. A check that the service layer never reaches upward.

The runtime probe is the one that matters. An AST scan alone can be walked around with
`importlib`, a relative import, or a transitive hop through a sibling module.

The constraint earns its keep. The hours-of-service engine is the part of this product worth
trusting, and part of why it is trustworthy is that it runs with no framework, no settings
module, no network and no clock in the room. Given the same activities it returns the same
timeline every time. `pytest trips/tests/test_hos.py` is green with `DJANGO_SETTINGS_MODULE`
unset.

| Module | Holds |
| --- | --- |
| `trips/domain/constants.py` | Every tunable number, each with its regulation or its source. |
| `trips/domain/models.py` | `DutyStatus`, `Activity`, `DutyEvent`, `Clocks`, `RodsDay`, `RodsSegment`, `Remark`. |
| `trips/domain/hos.py` | The simulator. Four concurrent limits, resolved in precedence order. |
| `trips/domain/rods.py` | Timeline to per-day log sheets. Refuses to emit a sheet that is not 24:00. |
| `trips/services/ors_client.py` | The only module holding the API key or seeing an ORS payload. |
| `trips/services/geo.py` | Haversine, cumulative distance, interpolation onto the polyline. |
| `trips/services/errors.py` | The failure taxonomy, raised by the planner and the ORS client. |
| `trips/services/planner.py` | Orchestration. Holds no regulatory logic of its own. |
| `trips/api/` | Serializers, two thin views, and the error envelope. |

## The time lattice

All time arithmetic is integer minutes on a 15-minute lattice, the same lattice the log grid is
drawn in. Every regulatory constant is a whole multiple of 15, so limits are reached exactly
rather than approximately, no float touches a duration, and each day's four totals sum to
precisely 1,440 minutes.

`hos._validate` enforces the invariant at the domain boundary. Quantising is the caller's job;
catching a violation before it spreads is the domain's. The same invariant is what guarantees the
drive loop terminates: every iteration advances the clock by at least one quantum.

## Request flow

A single `POST /api/v1/trips/plan` runs:

1. **Validate.** `TripPlanRequestSerializer` checks the three locations and the cycle figure.
   Cycle hours snap up to the next quarter hour; a supplied departure snaps down. A departure
   carrying a UTC offset is rejected rather than silently shifted.
2. **Geocode.** Three ORS geocoding calls, cached by normalised query, restricted to the US.
3. **Route.** One `driving-hgv` directions call through all three points, with
   `options.vehicle_type = "hgv"` so vehicle restrictions actually apply. Coordinates arrive as
   `[lon, lat]` and are converted to `(lat, lon)` here, once.
4. **Build activities.** The two legs plus a one-hour pickup and a one-hour dropoff. Leg
   durations round up to the lattice.
5. **Simulate.** `hos.simulate` returns a contiguous list of `DutyEvent`s covering the trip end
   to end, with every required stop inserted.
6. **Locate.** Each stop gets a place label from reverse geocoding, resolved once per stop rather
   than once per event, and capped by both a call count and a wall-clock budget.
7. **Build sheets.** `rods.build_days` pads to midnight at both ends, splits at every midnight,
   groups by date, merges adjacent same-status runs, and totals each day.
8. **Assemble.** The planner shapes the response and rounds display geometry.

## The simulator

`trips/domain/hos.py` is a single pass over the planned activities, carrying four counters in a
`Clocks` dataclass:

| Counter | Reset by |
| --- | --- |
| `driving_minutes` | 10-hour reset, 34-hour restart |
| `window_minutes` | 10-hour reset, 34-hour restart |
| `since_break_minutes` | any 30 consecutive non-driving minutes |
| `cycle_minutes` | 34-hour restart only |

Driving is emitted in chunks. Before each chunk the loop asks whether any limit is already
binding, and if so inserts the remedy that addresses it. Precedence matters: only a restart
restores cycle hours, and only a reset restores driving hours and window, so a remedy chosen out
of order would resolve nothing and the loop would spin.

Chunk length is the minimum of every remaining limit, the distance to the next fuel boundary, and
the rest of the leg, floored to the lattice. Because the caller has already cleared the blocking
constraints, that minimum is always at least one quantum.

The 30-minute break credit has a single owner. `_track_interruption` runs on every emitted event
and counts consecutive non-driving minutes, so an interruption that spans several events (a fuel
stop running into a pickup) still qualifies, which is what §395.3(a)(3)(ii) and the FMCSA guide
require.

Fuel stops are placed by mileage, just before each 1,000-mile boundary rather than after it, and
the next interval is measured from where the stop happened. That bounds the gap between two
stops, which is what "at least once every 1,000 miles" actually asks for.

## From timeline to log sheets

`trips/domain/rods.py` is a pure function with five stages:

1. **Pad.** Extend the timeline with off-duty time back to the first midnight and forward to the
   last, so every sheet accounts for a whole 24 hours.
2. **Remarks.** Computed on the padded timeline *before* it is split, so a segment that merely
   continues past midnight is not reported as a status change. The first reportable event always
   gets a remark, which covers a departure at exactly midnight and a trip opening with a restart.
3. **Split and group.** Cut at each midnight, group by calendar date, converting each piece to a
   `RodsSegment` with minutes measured from that day's midnight. Mileage divides in proportion to
   minutes, which is exact because implied speed is constant within a leg.
4. **Merge.** Collapse adjacent same-status runs, since the line on a paper log only moves
   between rows at a real change of status.
5. **Total.** Sum each status. A day that does not come to exactly 1,440 minutes raises
   `RodsIntegrityError` rather than reaching the renderer.

Per-day mileage uses largest-remainder allocation so the column on the sheets totals the trip
distance in the summary, which independent per-day rounding does not guarantee.

## Errors

The failure vocabulary is a small exception hierarchy in `trips/services/errors.py`, each class
carrying a `code`. `trips/api/errors.py` owns the translation to an HTTP status and the envelope:

```json
{ "error": { "code": "...", "message": "...", "field": "..." } }
```

The DRF exception handler is the only exit. It covers planner errors, DRF's own validation and
method errors, and anything unforeseen, which is logged with a traceback and returned as one
sentence. `config/urls.py` sets `handler404` and `handler500` so even requests no view saw leave
in the same shape.

Messages are written for a dispatcher. No ORS payload, status line or numeric code is ever quoted
back to the client.

Where a failure is cosmetic the app degrades. A reverse-geocode failure returns `None` rather
than raising, the stop falls back to a route mile marker, and a warning on the response explains
why the labels look like that. The two causes (upstream unavailable, budget spent) get different
copy, because telling a dispatcher the geocoder was down when we simply stopped asking sends them
to investigate a healthy service.

## Frontend

`App.tsx` holds the whole of the state: the plan, the in-flight flag, and the last error. There
is no store and no router, because there is one screen and one request.

| Component | Draws |
| --- | --- |
| `TripForm` | The four inputs, with the server's `field` steering the error to the right one. |
| `TripSummary` | Distance, driving and on-duty hours, cycle before and after, warnings. |
| `StopItinerary` | A vertical mile-marker rail of every stop. |
| `RouteMap` | Leaflet polyline and `divIcon` markers, coloured by duty status. |
| `LogSheetStack` / `LogSheet` | One drawn RODS per day. |

`LogSheet` is the largest piece. The header is HTML because text layout, truncation and
screen-reader behaviour are all better there; the grid is SVG because it genuinely needs vector
drawing. Both sit inside one `break-inside: avoid` block so a sheet prints as a unit.

The duty-status trace is one continuous path: a horizontal run on each row's centreline plus a
vertical connector at every transition. A gap or an overlap is the visual tell of an invalid log,
so the backend guarantees contiguity and the renderer draws it without smoothing.

Remark labels are rotated -60 degrees and staggered across three baselines. Placement measures
each label's clearance perpendicular to the baseline against the labels already placed and takes
the first row that clears, because at that angle a naive row rotation moves a label almost
exactly along the text rather than away from it.

`src/types/trip.ts` mirrors the API response field for field. If the contract changes, both
change in the same commit.

## Deployment shape

The API is stateless, so there is nothing to migrate and nothing to back up. `build.sh` installs,
collects static files, and runs `manage.py check --deploy --fail-level ERROR`, which fails the
build on a malformed CORS origin that would otherwise surface only as silently absent headers.

The frontend is a static bundle. Only `VITE_`-prefixed variables reach it, which is exactly why
the ORS key is not one.
