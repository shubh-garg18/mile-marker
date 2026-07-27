# Design choices

The decisions that shaped this build, and the trade-offs behind them. Where a choice was
reached by getting it wrong first, that is recorded too.

---

## Project shape

- **No database, no models, no `migrate` step.** The API is a pure compute endpoint: inputs
  in, plan out, nothing stored. `DATABASES = {}` states that outright instead of leaving an
  unused SQLite file lying around, and it removes a whole class of failure from the deploy.

- **`USE_TZ = False`.** §395.8(a) requires a single home-terminal time standard for the whole
  trip even when it crosses time zones. Naive local datetimes model that directly.
  Timezone-aware ones would invite a conversion the regulation does not want.

- **`timezone` is a configured property of the home terminal, not derived from the route.** It
  is reported for display only; no time is ever converted against it. Deriving it from a
  coordinate would model the wrong thing.

- **Test dependencies sit in `requirements.txt` alongside runtime ones.** It costs a few
  seconds on the deploy build and keeps `pip install -r requirements.txt && pytest` true. A
  split `requirements-dev.txt` would make the documented commands lie.

- **Frontend direct dependencies are pinned exactly, not just locked.** `package-lock.json`
  already guarantees reproducibility for `npm ci`, but an accidental `npm install` on a caret
  range is how a deployed build drifts from a tested one.

---

## The engine

- **`Activity` carries an explicit `task_kind`.** `DutyEvent.kind` needs to say which task a
  stop is, pickup or dropoff. Rather than infer it from the label, `Activity` names it and
  validates in `__post_init__` that a task has one and a drive leg does not.

- **Fuel stops go just before the 1,000-mile boundary, not after it.** Stopping early
  guarantees the distance between two stops never exceeds the interval. Crossing first and
  then fuelling would let a gap reach 1,000 miles plus one quantum.

- **Each fuel interval is measured from where the last stop happened, not from the round mark
  it aimed at.** Absolute anchoring was the first implementation and it was wrong: because a
  stop lands up to one quantum early, a stop at mile 991 followed by one at 1,996 is a
  1,005-mile gap. The brief asks for fuel at least once every 1,000 miles, not once per
  1,000-mile block, so the gap is what has to be bounded. The cost is that stops drift below
  the round marks on a long trip, by at most one quantum of driving each. This was caught by
  the end-to-end acceptance pass rather than by the unit tests, which is what that pass is
  for.

- **The 30-minute break accepts consecutive short interruptions.** The FMCSA guide (p.10) is
  explicit: "15 minutes of on-duty not driving time plus 15 minutes of off-duty time … as long
  as those two periods are consecutive". Only non-consecutive periods may not be summed. The
  credit has a single owner reached through `emit`, so it cannot drift between the four
  insertion helpers. An earlier version credited the break only when one activity ran 30
  minutes or longer, which was stricter than the rule.

- **`simulate` raises on input off the 15-minute lattice rather than quietly rounding it.**
  Every downstream guarantee rests on that invariant, so the domain enforces it and the
  service layer adapts to it.

- **A bound on implied speed, derived rather than chosen.** Above `FUEL_INTERVAL_MILES * 60 /
  QUANTUM_MINUTES`, which is 4,000 mph, a whole fuel interval fits inside one quantum of
  driving, so the drive loop resolved a fuel stop every iteration without `miles_done`
  advancing, emitting events until memory ran out. Unreachable through ORS, reachable from a
  corrupt payload, and the module's own docstring promised a termination guarantee it did not
  have. Deriving the bound from the two constants that create the hazard means it cannot drift
  out of date.

- **`cycle_minutes_at_end` is a separate function rather than a second return value.**
  Replaying the cycle over a finished timeline needs no regulatory knowledge: on duty adds, a
  restart zeroes. Keeping it out of `simulate` keeps that signature simple.

---

## Log sheets

- **Remarks are computed on the padded timeline before it is split at midnight.** A driving
  segment that merely continues past midnight is not a change of duty status and must not
  produce a remark on the next day's sheet. Computing remarks after the split would make every
  overnight segment look like a status change.

- **The first reportable event always gets a remark.** Remarks originally came from
  `zip(events, events[1:])`, so the opening event announced nothing. The leading off-duty pad
  hid this except when departure is exactly midnight (no pad) or when a 34-hour restart begins
  the trip (restart and pad are both off duty), which produced a blank 24-hour sheet with no
  explanation. That is precisely the case the guide requires an explanation for.

- **Adjacent same-status segments are merged.** The line on a paper log only moves between
  rows at a real change of status, so a day inside a 34-hour restart is one unbroken off-duty
  run rather than a pad abutting a restart. A merged run is named after its longest
  constituent.

- **`RodsIntegrityError` rather than an assertion.** Assertions vanish under `python -O`. A
  sheet whose four totals do not sum to 24:00 is worse than no sheet, because it looks
  authoritative and is wrong, so this one raises unconditionally.

- **Per-day mileage is allocated, not rounded independently.** Five days of 605.4 miles each
  round down to a mile short of the trip, so the column on the sheets did not total the
  distance in the summary. The remainder now goes to the days with the largest fractional
  part, which moves each day the least.

- **`mile_marker_label` lives in `rods.py` and is shared with the planner**, so the itinerary
  and the remarks strip can never disagree about what to call the same point on the route.

---

## Routing and upstream

- **Geocoding is restricted to `boundary.country=US`.** This app models US federal hours of
  service and the brief's assumptions are US-specific. Unrestricted Pelias search returns a
  same-named town in another country often enough for short queries such as "Springfield" to
  make the restriction worth it. The error copy says so plainly.

- **Geocode cache keys are hashed, not interpolated.** Place names contain spaces and
  punctuation that are illegal in a memcached or Redis key. The local-memory backend tolerates
  them, so the bug would surface only on the day the cache backend changed. Reverse-geocode
  keys are interpolated coordinates, which are key-safe already.

- **Reverse geocoding returns `None` instead of raising.** A missing remark label is cosmetic;
  a failed trip is not. The caller falls back to a mile marker and adds a warning.

- **A reverse-geocode miss is cached for five minutes, not twenty-four hours.** An empty
  feature list is also what a degraded Pelias returns, and holding that for a day would keep
  showing mile markers on later plans long after ORS recovered.

- **Neither a 403 nor a 429 is retried.** On the free tier 403 is the daily quota, which a
  second attempt cannot fix. 429 is a sliding 60-second window; a sub-second backoff cannot
  outlast it and merely spends another request from the exhausted budget, so retrying made
  rate limiting worse rather than better. Only 5xx, timeouts and connection errors are
  retried, once.

- **A 403 is split into two meanings.** ORS answers 403 both to a key it will not accept
  (`{"error": "Access to this API has been disallowed"}`) and to an exhausted quota. Mapping
  everything to "try again tomorrow" prescribes a day-long wait for what is really a server
  misconfiguration, and a wrong key is the likeliest fault on a fresh deployment. The two are
  split on the response body, with the key case logged at ERROR because only an operator can
  fix it.

- **`instructions` stays true on the directions request.** It looks like turn-by-turn text
  we never render and an easy 40 KB to save, but ORS drops `properties.segments` from the
  response entirely when it is false, and the per-leg distance and duration in there are
  what the engine plans against. With it false the API returns a valid 200 carrying only a
  summary, and every trip fails as UPSTREAM_ERROR. Found on the first call against a real
  key; a test now pins the flag.

- **The snap radius is widened to 5 km from the ORS default of 350 m.** The geocoder answers
  a city query with the city's centroid, and a centroid often lands in a pedestrian core or
  a park. "Oklahoma City, OK" resolves to a point with no routable HGV road inside 350 m, so
  ORS returns code 2010 and the whole trip fails. Measured against the live API, 1 km clears
  that case and 5 km returns an identical route, so the wider radius costs nothing where a
  nearer road exists and only helps a rural pickup. A genuinely unreachable point still
  fails, which is correct.

- **Route length is checked both from ORS's error code 2004 and from the returned distance.**
  Either alone leaves a hole, and the check happens before the engine runs so a rejected trip
  costs nothing.

- **Geometry is rounded to five decimal places and thinned above 40,000 points, for display
  only.** Distance was already computed against the full-resolution polyline. An earlier
  threshold of 6,000 points was set from a comment claiming roughly 1.5 MB; measured, that was
  137 KB, and two thirds of a real route's road geometry was being discarded to save 190 KB.

---

## Planner and API

- **Locations are resolved once per stop, not once per event.** The truck only moves while
  driving, so every event between two stops happened in the same place. That turns a
  transcontinental trip from roughly twenty reverse-geocode calls into a dozen, which matters
  for latency and for the free-tier quota.

- **A wall-clock budget on reverse geocoding.** One plan could make twenty sequential ORS
  calls with no whole-request deadline, against gunicorn's 30-second default. A 3,700-mile
  trip with healthy upstream latency reproduced a worker timeout and a bare HTML 500 that
  bypassed the error envelope entirely. Labels are cosmetic; the response is not.

- **Cycle hours snap up to the next quarter hour; a requested departure snaps down.**
  Rejecting `12.3` outright would be pedantic on a dispatcher's form. Rounding cycle hours up
  never credits the driver with time already spent, and flooring the departure keeps the drawn
  grid aligned to the 15-minute cells it is made of.

- **A departure carrying a UTC offset is rejected, not adjusted.** Honouring it would shift
  the trip; discarding it would ignore what was sent. Sending `08:00-05:00` for a terminal
  already on -05:00 used to depart at 13:00 and carry every log sheet with it. The check has
  to sit in the field's `to_internal_value`, because with `USE_TZ = False` DRF has already
  converted the value to naive UTC by the time a field validator runs.

- **The failure taxonomy lives in `trips/services/errors.py`.** It was originally in
  `trips/api/`, which meant `services/` imported the HTTP layer, inverting the dependency rule
  and pulling DRF into the ORS client for nothing but exception classes.

- **JSON-only rendering.** Removing DRF's browsable API also removed its dependency on
  collected static files, and with it a bare 500 that rendered after the exception handler had
  already run and so could never be caught by it.

- **`log_header` is returned once at the top level**, not repeated on every day. The frontend
  needs it once per plan.

- **`/api/v1/health` is exempt from the throttle.** It costs nothing upstream, and sharing the
  anonymous budget meant a repeatedly reloaded page or an uptime pinger could spend the
  allowance the actual plan needs.

- **The gunicorn timeout and the ORS budget are tuned together.** Four sequential upstream
  calls, each allowed one retry at 15 seconds, bound the worst case near 123 seconds. The
  documented timeout is 90 seconds, matching the browser's own ceiling, and the README states
  the arithmetic so the two numbers are not changed independently.

---

## Frontend

- **The console is a warm neutral, not the usual navy.** The sheets are manila, and a warm
  stock on a blue-grey shell reads as a picture of paper pasted onto a screen rather than
  paper lying on a desk. Pulling the shell to warm asphalt puts both in the same light and
  makes the DOT amber the brightest point of one continuous range instead of a lone bright
  accent on a cold field. Every token clears its WCAG floor: text at 4.5:1 or better on both
  surfaces, the hairline at 3.3:1 as a UI boundary.

- **Paper carries its own four duty colours.** The screen values are tuned against the dark
  shell, and on manila amber falls to 1.8:1 and steel to 2.4:1, which is the faintest mark on
  the sheet and close to invisible in greyscale print. Berth and on-duty clear 3:1 on paper
  unaided, but have ink variants anyway: a sheet drawn with two rows at 3.2:1 and two at
  4.5:1 looks unevenly inked, and the darker pair survives a fax.

- **The empty state is a real, blank duty-status grid.** A driver's day begins as an unfilled
  Record of Duty Status, so the app does too. Showing the actual artifact before anything is
  typed states what the product makes faster than a paragraph, and it is drawn from the same
  geometry as the finished sheet, so it is not a mock-up of something that looks different
  once it is real. It replaced a dashed placeholder box.

- **The loading state is that grid being swept.** While a plan runs, one slow amber pass
  crosses the blank sheet from midnight to midnight, so the progress indicator is the subject:
  24 hours being simulated. Reduced motion withdraws the animation rather than inheriting the
  global duration collapse, which would park the sweep at the far edge looking like a stray
  rule on the grid.

- **The cycle meter shows two segments, not one.** It used to be a rounded progress bar
  carrying only the figure on arrival, which hides the number a dispatcher is actually
  deciding on: what this trip costs. Steel is what was already spent, amber is what the trip
  adds, and the gap on the right is what is left to sell.

- **Stop markers are Leaflet `divIcon`s.** This sidesteps the bundler problem with Leaflet's
  default icon URLs entirely, and lets each stop type carry its own glyph and duty-status
  colour. Icons are cached by appearance, because react-leaflet calls `setIcon` whenever the
  prop identity changes, which rebuilds the marker element and drops any open popup.

- **The log sheet header is HTML, the grid is SVG.** Text layout, truncation and screen-reader
  behaviour are all better in HTML; the grid genuinely needs vector drawing. Both sit inside
  one `break-inside: avoid` block so a sheet still prints as a unit.

- **Quarter-hour ticks rise from each row's baseline**, with the half-hour mark twice the
  length of the quarter-hour ones. That hierarchy is what makes the grid read as a real RODS
  rather than as graph paper.

- **The fourth row label breaks over two lines.** `4. On Duty (not driving)` needs 115 px from
  an anchor at x=102, so on one line it started at x=-13 and the viewBox cut it off. The paper
  form breaks it too.

- **The grid stops shrinking at 68 rem and scrolls.** It previously halved from 811 px to 404
  px at exactly the 900 px breakpoint and did not recover until 1307 px, which put the row
  labels below 3 px, worse than on a phone.

- **Paper gets its own duty colours.** DOT amber is right on a dark screen and wrong on
  manila: it reaches 1.88:1 there, the faintest mark on the sheet, and sits 63 greyscale
  levels from the paper in print. The sheet uses darker amber and steel; the console keeps the
  originals.

- **Remark labels are placed by measured clearance, not by cycling rows.** What separates two
  parallel labels is their distance perpendicular to the -60 degree baseline. Wrapping from
  the last row back to the first moves a label up-and-right, almost exactly along the text, so
  it lands back on top of the one three remarks earlier. Placement now measures clearance
  directly and takes the first row that clears. Three rows still cannot hold more than about
  five labels 15 minutes apart; the engine's densest real output is four.

- **The remarks strip and the shipping block occupy separate bands.** They were laid out to
  overlapping ones. Measured across 2,114 rendered sheets, 5,550 of 8,409 rotated labels put
  ink back inside the duty grid, 579 leader lines ran through the divider, and 309 labels sat
  on top of the shipping text. The strip now uses 8 px type on baselines 326, 353 and 380,
  which is the band actually free between the hour-tick rule and the block. All four counts
  are now zero.

- **A production build with no `VITE_API_BASE_URL` says so.** The fallback is
  `127.0.0.1:8000`, which in a visitor's browser is their own machine, so every request failed
  as a network error and the copy blamed their connection for a misconfigured build. The check
  compiles away entirely when the variable is set.

---

## Tests

- **Regulatory constants are pinned to literals.** Every limit test originally asserted
  against the constant it was testing, so changing the 11-hour driving limit to twelve, or the
  8-hour break trigger to nine, left the suite fully green. That is the same failure mode as
  the fuel-interval bug, in the two most important numbers in Part 395.

- **Two tests asserted the wrong invariant.** One required a shift to fit inside 14 elapsed
  hours, which contradicts the guide's own worked example of a driver on duty past hour 14
  with no violation, and contradicts the project's own rule that only driving is gated. The
  other banned a remark at minute 0, which a genuine status change at midnight must produce.

- **The architectural guard is three tests, not one.** It began as a scan of
  `trips/domain/*.py` for a literal `import django`, which misses transitive imports, relative
  imports, `importlib` and subpackages, and never looked at `services/` at all, which is the
  direction the rule had actually been broken in. The runtime probe, importing each module in
  a clean subprocess and inspecting `sys.modules`, is the one that cannot be walked around.

- **`test_ors_client.py` is a separate file.** The client's parsing and failure translation is
  where coordinate-order and error-mapping bugs live, and it belongs neither in `test_geo.py`
  (geometry) nor in `test_api.py` (the HTTP surface).

- **Throttle tests monkeypatch the class, not the settings.** DRF binds `THROTTLE_RATES` to
  the settings dict when `rest_framework.throttling` is imported, so overriding
  `REST_FRAMEWORK` at run time never reaches it. The environment variable still works in
  production, because it is read before that import.
