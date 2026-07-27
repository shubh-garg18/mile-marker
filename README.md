# Mile Marker

**Truck-legal routing with a drawn FMCSA log sheet for every day of the trip.**

![Python](https://img.shields.io/badge/python-3.12-blue)
![Django](https://img.shields.io/badge/Django-5.2%20LTS-092E20)
![DRF](https://img.shields.io/badge/DRF-3.16-a30000)
![React](https://img.shields.io/badge/React-19-61DAFB)
![tests](https://img.shields.io/badge/tests-146%20passing-brightgreen)

Give it where a truck is, where it is picking up, where it is dropping off, and how many hours
of the driver's 70-hour cycle are already spent. It routes the trip on a `driving-hgv` profile,
simulates it against the hours-of-service limits in 49 CFR Part 395, and returns the route, every
stop the regulations force, and a filled Record of Duty Status for each calendar day the trip
spans. The compliance simulator is the product; the map and the sheets are how it shows its
working.

```
POST /api/v1/trips/plan   {"current_location": "Dallas, TX",
                           "pickup_location": "Oklahoma City, OK",
                           "dropoff_location": "Denver, CO",
                           "current_cycle_used_hours": 12.5}

  856 mi · 22.00 h driving · 24.00 h on duty · 2 log sheets · cycle 12.5 -> 36.5

  mi  212   pickup    Tue 14:00 -> 15:00   Oklahoma City, OK
  mi  413   rest      Tue 20:00 -> 06:00   Harper County, OK
  mi  735   break     Wed 14:00 -> 14:30   Kit Carson County, CO
  mi  856   dropoff   Wed 17:30 -> 18:30   Denver, CO

  2026-07-28   413 mi   off 8.00  sb 4.00  drive 11.00  on 1.00  = 24.00
  2026-07-29   443 mi   off 6.00  sb 6.00  drive 11.00  on 1.00  = 24.00
```

**Live app:** <https://mile-marker-ebon.vercel.app>
**API:** <https://mile-marker.onrender.com> (health check at `/api/v1/health`)

The API runs on a free instance that sleeps when idle, so the first request after a quiet spell
takes about a minute to wake. The app pings the health endpoint on load to start that early.

## Contents

- [Why it is interesting](#why-it-is-interesting)
- [Stack](#stack)
- [What goes in, what comes out](#what-goes-in-what-comes-out)
- [The hours-of-service rules implemented](#the-hours-of-service-rules-implemented)
- [Assumptions](#assumptions)
- [Out of scope](#out-of-scope)
- [Quickstart](#quickstart)
- [API](#api)
- [Configuration](#configuration)
- [Testing](#testing)
- [Deployment](#deployment)
- [Project structure](#project-structure)
- [Docs](#docs)
- [Attributions](#attributions)

## Why it is interesting

- **The 14-hour window never pauses.** It is elapsed wall time, so a driver can run out of
  window while still holding unused driving hours. This is the rule most often modelled wrong,
  and the simulator produces that outcome rather than quietly extending the day.
- **Only driving is gated.** On-duty non-driving work is always permitted, including past the
  14-hour window and past the 70-hour cycle, exactly as the FMCSA guide's own worked example
  shows. A pickup or a dropoff is never blocked.
- **The engine is pure Python.** `trips/domain/` imports no Django, no `requests`, no clock.
  Given the same activities it returns the same timeline, and its tests run with
  `DJANGO_SETTINGS_MODULE` unset. Three tests enforce the boundary, one of them at runtime.
- **Every sheet totals 24:00, or nothing is returned.** A log that does not add up is worse
  than no log, because it looks authoritative and is wrong. All arithmetic is integer minutes
  on the same 15-minute lattice the paper grid is drawn in, so limits are hit exactly.

---

## What goes in, what comes out

Four inputs:

| Field | Notes |
| --- | --- |
| Current location | Free text, geocoded. US locations. |
| Pickup location | Free text, geocoded. |
| Dropoff location | Free text, geocoded. |
| Current cycle used (hrs) | `0` to `70`, snapped up to the quarter hour. |

Departure time is optional and defaults to 08:00 tomorrow. It exists so that a plan is
reproducible, which is what makes it testable.

Two outputs:

1. **A routed map with its stops.** The truck route as a single polyline, with a marker for the
   pickup, the dropoff, every fuel stop, every 30-minute break, every 10-hour rest and any
   34-hour restart. An itinerary lists each one with its clock time, its cumulative mileage and
   the reason it exists.
2. **One Record of Duty Status per calendar day.** The duty-status grid drawn as a single
   continuous line across a 24-hour timeline, per-status totals summing to exactly 24:00, and a
   remarks strip naming the location of every status change. Longer trips produce more sheets. A
   print stylesheet puts one sheet on each letter-landscape page.

---

## Stack

| | |
| --- | --- |
| Backend | Django 5.2 LTS, Django REST Framework 3.16, Python 3.12 |
| Frontend | React 19, Vite, TypeScript, Tailwind v4, Leaflet |
| Routing | OpenRouteService `driving-hgv` (directions, geocoding, reverse geocoding) |
| Hosting | Render (API), Vercel (SPA) |

No database. The API is a stateless compute endpoint: inputs in, plan out, nothing stored.

`docs/architecture.md` covers the layering and how the engine works.
`docs/design-choices.md` records the non-obvious choices and why they were made.

---

## The hours-of-service rules implemented

Four limits run concurrently. Any one can stop driving, and the binding one is whichever expires
first. They are modelled as four independent counters.

| Rule | Citation | Implementation |
| --- | --- | --- |
| 11-hour driving limit | §395.3(a)(3) | At most 11 hours driving after 10 consecutive hours off. Loading, fuelling and paperwork do not count against it. |
| 14-hour window | §395.3(a)(2) | No driving past the 14th consecutive hour after coming on duty. Elapsed wall time; it never pauses, not for the break, not for fuel, not for a short off-duty period. |
| 30-minute break | §395.3(a)(3)(ii) | Required once 8 cumulative driving hours pass without a 30-consecutive-minute interruption. Since the 2020 rule change the interruption may be off duty, sleeper berth or on duty not driving, so a fuel stop qualifies. |
| 10-hour reset | §395.3(a)(1) | Ten consecutive hours off duty or sleeper berth. Resets driving, window and break. Does not touch the cycle. |
| 70-hour / 8-day cycle | §395.3(b)(2) | No driving once 70 on-duty hours are used. The starting figure arrives as a scalar and is debited as the trip proceeds. |
| 34-hour restart | §395.3(c) | Thirty-four consecutive hours off duty returns the cycle to zero, and resets everything else with it. |

Two properties are the ones most often modelled wrong, and both have tests named after them:

- **The 14-hour window is elapsed wall time and never pauses.** A driver can run out of window
  while still holding unused driving hours, and this simulator produces that outcome.
- **Only driving is gated.** On-duty non-driving work is always permitted, including past the
  14-hour window and past the 70-hour cycle. The FMCSA guide's own worked example shows the same.
  A pickup or a dropoff is never blocked.

When driving is blocked, the remedy is chosen in a fixed precedence order, because a remedy that
does not address the binding constraint resolves nothing:

1. Cycle exhausted, so a 34-hour restart (the only thing that restores cycle hours).
2. Driving limit or window exhausted, so a 10-hour reset.
3. Break due, so a 30-minute break.

---

## Assumptions

Given by the brief and treated as fixed: property-carrying driver, 70 hours / 8 days, no adverse
driving conditions, fuel at least once every 1,000 miles, one hour each for pickup and dropoff.

Chosen by this implementation:

1. The trip begins at **08:00 home-terminal time**. No separate pre-trip inspection is modelled;
   the driver goes on duty and departs.
2. A fuel stop costs **30 minutes of on-duty (not driving) time**. Thirty consecutive non-driving
   minutes also satisfies the break requirement, which is realistic and is why fuel stops and
   breaks often coincide.
3. Pickup and dropoff are **one hour each** of on-duty (not driving) time, per the brief.
4. Driving durations come from OpenRouteService's `driving-hgv` profile rather than a flat
   average speed. Within a leg, a constant implied speed maps mileage to time for fuel-stop
   placement.
5. **All times are the driver's home-terminal time zone** for the whole trip, as §395.8(a)
   requires, even where the route crosses time zones.
6. 10-hour resets are logged as **sleeper berth**; a 34-hour restart is logged as **off duty**.
7. All durations sit on the **15-minute lattice** the log grid uses. Leg durations round up, so
   driving time is never under-reported. Fuel stops land up to one quantum of driving early and
   the next interval is measured from where the stop happened, so the distance between two fuel
   stops never exceeds 1,000 miles.
8. Driver, carrier, vehicle and shipping-document values on the sheets are **placeholders** from
   configuration, since the brief provides none. Override them with the `LOG_*` environment
   variables below.

---

## Out of scope

Recorded so the boundary is explicit.

- **Split sleeper-berth provisions, §395.1(g).** Pairing a 7-hour-or-longer berth period with a
  2-hour-or-longer period, excluding the paired periods from the 14-hour window, and recomputing
  the calculation point after each pair. Left out deliberately: it is the most error-prone corner
  of the domain, and a subtly wrong implementation would be worse than a clearly scoped absence.
  Sleeper berth is treated here as a valid form of the 10-hour reset.
- **Adverse driving conditions, §395.1(b)(1).** Two extra driving hours and two extra window
  hours. Would need a per-leg flag on the input.
- **Short-haul exceptions, Hazmat, team drivers, Alaska and Hawaii variants.**
- **The rolling 8-day recap.** The app receives a single scalar rather than eight days of prior
  logs, so hours cannot drop off mid-trip. Only a 34-hour restart restores cycle time.
- **Persistence, accounts, saved trips, real ELD telematics.**

---

## Quickstart

You will need Python 3.12, Node 22 or newer, and a free OpenRouteService API key from
<https://openrouteservice.org/dev/#/signup>.

Backend:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then set ORS_API_KEY
python manage.py runserver    # http://127.0.0.1:8000
```

Frontend:

```bash
cd frontend
npm install
cp .env.example .env          # VITE_API_BASE_URL=http://127.0.0.1:8000
npm run dev                   # http://localhost:5173
```

## Configuration

| Variable | Where | Required | Notes |
| --- | --- | --- | --- |
| `ORS_API_KEY` | backend | yes | Secret. Server-side only; never reaches the browser. |
| `SECRET_KEY` | backend | in production | Generate one per environment. |
| `DEBUG` | backend | no | Defaults to `False`. |
| `ALLOWED_HOSTS` | backend | no | Comma-separated. Render's hostname is appended automatically. |
| `CORS_ALLOWED_ORIGINS` | backend | in production | Comma-separated exact origins. Never a wildcard. |
| `HOME_TERMINAL_TIMEZONE` | backend | no | The terminal's own zone. Sets the default departure date and is shown in the trip summary; no time is converted against it. Defaults to `America/Chicago`. |
| `ORS_TIMEOUT_SECONDS` | backend | no | Seconds before a single OpenRouteService call is abandoned. Defaults to 15. |
| `PLAN_RATE_LIMIT` | backend | no | Throttle rate for anonymous clients. Defaults to `12/min`. |
| `LOG_DRIVER_NAME`, `LOG_CARRIER_NAME`, `LOG_OFFICE_ADDRESS`, `LOG_TERMINAL_ADDRESS`, `LOG_TRACTOR_NUMBER`, `LOG_TRAILER_NUMBER`, `LOG_SHIPPING_DOCUMENT`, `LOG_SHIPPER_COMMODITY` | backend | no | Placeholder header values on the log sheets. |
| `VITE_API_BASE_URL` | frontend | yes | Public by design. It contains no secrets, which is why the ORS key is not a `VITE_` variable. |

---

## Testing

```bash
cd backend
pytest                                # the whole suite
pytest trips/tests/test_hos.py -v     # the engine alone
```

146 tests. The engine tests are the proof of correctness and are where the effort went. They run
with `DJANGO_SETTINGS_MODULE` unset, because `trips/domain/` imports no framework.

| File | Covers |
| --- | --- |
| `test_hos.py` | Eleven named scenarios, a 200-trip randomised property test asserting the limits hold, and three guards proving `trips/domain` imports neither `django` nor `requests`. |
| `test_rods.py` | Every sheet totalling 24:00 across every fixture; midnight splitting with mileage divided in proportion to minutes; one remark per status change; the mileage column totalling the trip. |
| `test_geo.py` | Haversine against published great-circle distances; interpolation at zero, at the midpoint, at full length and clamped beyond the end. |
| `test_ors_client.py` | Coordinate order, caching, and every upstream failure translating to the right error code. |
| `test_api.py` | The full payload shape, the acceptance criteria, and every documented error code reaching its documented HTTP status. |

The frontend is typechecked as part of its build:

```bash
cd frontend
npm run build     # tsc -b && vite build
```

---

## API

Two endpoints.

```
GET  /api/v1/health      -> {"status": "ok"}
POST /api/v1/trips/plan
```

Request:

```json
{
  "current_location": "Dallas, TX",
  "pickup_location": "Oklahoma City, OK",
  "dropoff_location": "Denver, CO",
  "current_cycle_used_hours": 12.5,
  "start_datetime": "2026-07-28T08:00:00"
}
```

`start_datetime` is optional and must carry no UTC offset, since every time in the system is
home-terminal local. The response carries `trip` totals, `waypoints`, `route` geometry and legs,
`stops`, one entry in `days` per calendar day, `log_header`, and any `warnings`. The TypeScript
types in `frontend/src/types/trip.ts` mirror it field for field.

## Errors

Every failure leaves the API in one shape, with copy written for a dispatcher rather than a
developer. No stack traces, no raw upstream payloads, no bare 500s.

```json
{ "error": { "code": "GEOCODE_NOT_FOUND",
             "message": "We couldn't find \"Dalas TX\". Try adding a state or ZIP code.",
             "field": "current_location" } }
```

| Code | HTTP | Trigger |
| --- | --- | --- |
| `VALIDATION_ERROR` | 400 | Missing field, or cycle hours outside 0 to 70. |
| `GEOCODE_NOT_FOUND` | 422 | No geocoder match. `field` names the input to blame. |
| `ROUTE_NOT_FOUND` | 422 | ORS cannot connect the waypoints. |
| `ROUTE_TOO_LONG` | 422 | Route exceeds the 6,000 km profile cap. |
| `UPSTREAM_RATE_LIMITED` | 503 | ORS daily quota (403) or per-minute limit (429). |
| `UPSTREAM_ERROR` | 502 | ORS 5xx, timeout, an unreadable payload, or a rejected API key. |
| `NOT_FOUND` | 404 | No such endpoint. |
| `METHOD_NOT_ALLOWED` | 405 | Wrong verb for the endpoint. |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | Body was not JSON. |
| `RATE_LIMITED` | 429 | This API's own per-client throttle. |
| `INTERNAL_ERROR` | 500 | Anything unforeseen. Logged with a traceback server-side; the client gets a sentence. |

The frontend adds three codes of its own for failures that never reach the server:
`NETWORK_ERROR`, `TIMEOUT` and `NOT_CONFIGURED`.

Where a failure is cosmetic the app degrades instead of failing. If reverse geocoding is
unavailable, stops fall back to route mile markers, the plan is returned anyway, and a warning
explains why the labels look like that.

---

## Deployment

Two free-tier services: the Django API on Render, the React SPA on Vercel. Do the backend first,
because the frontend needs its URL.

### 1. Backend on Render

Render dashboard, New, Web Service, connect the repo.

| Field | Value |
| --- | --- |
| Root directory | `backend` |
| Runtime | Python 3 |
| Build command | `./build.sh` |
| Start command | `gunicorn config.wsgi:application --workers 2 --threads 4 --timeout 90` |
| Instance type | Free |

The flags matter. Bare `gunicorn` runs one sync worker with a 30-second timeout, and a long trip
makes several sequential OpenRouteService calls, so a single slow plan would kill the only worker
and take every other in-flight request with it. Two threaded workers give the planner room, and
the planner itself caps its optional reverse lookups at 8 seconds.

The 90-second timeout matches the browser, which also gives up at 90. A plan makes four required
upstream calls in sequence, each allowed one retry, so the worst case is roughly
`4 x (2 x ORS_TIMEOUT_SECONDS + backoff)`, about 123 seconds at the default 15. A healthy ORS
answers in one or two, so this only bites when the upstream is degraded. If your platform caps
the timeout below 90, lower `ORS_TIMEOUT_SECONDS` to match rather than leaving the two numbers
inconsistent.

Environment variables:

| Key | Value |
| --- | --- |
| `PYTHON_VERSION` | `3.12.3` |
| `SECRET_KEY` | generate one, see below |
| `DEBUG` | `False` |
| `ORS_API_KEY` | your OpenRouteService key |
| `CORS_ALLOWED_ORIGINS` | your Vercel origins, comma-separated. Fill in after step 2. |

```bash
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

`ALLOWED_HOSTS` needs no value, because `settings.py` appends Render's own
`RENDER_EXTERNAL_HOSTNAME` automatically. There is no `migrate` step because there are no models.

Confirm with `curl https://<your-service>.onrender.com/api/v1/health`.

### 2. Frontend on Vercel

Vercel, Add New, Project, import the same repo.

| Field | Value |
| --- | --- |
| Root directory | `frontend` |
| Framework preset | Vite |
| Build command | `npm run build` |
| Output directory | `dist` |

Set `VITE_API_BASE_URL` to `https://<your-service>.onrender.com` with no trailing slash, for
Production and for Preview if you plan to demo from a preview URL. A production build with this
unset will tell the visitor so rather than silently failing against their own machine.

`vercel.json` rewrites every path to `/index.html` for SPA routing.

### 3. Close the loop

Set `CORS_ALLOWED_ORIGINS` on Render to the exact Vercel origins, comma-separated, no trailing
slash, then redeploy:

```
https://your-project.vercel.app,https://your-project-git-main-you.vercel.app
```

`CORS_ALLOW_ALL_ORIGINS` is never used. If the browser reports a CORS failure, the origin string
does not match exactly.

### 4. Cold start

A Render free instance spins down after 15 minutes idle and takes roughly a minute to wake. The
app handles that in two layers: the frontend fires `GET /api/v1/health` on mount, so the server
starts waking before anyone finishes typing, and a plan request still open after three seconds
explains that the server is waking. A slow first request is a cold start, not a bug.

Optionally point a free external cron at `/api/v1/health` every 10 minutes to keep it warm.

---

## Project structure

```
backend/
  config/            Django project (settings, urls, wsgi)
  trips/
    domain/          pure simulation: constants, models, hos.py, rods.py
    services/        side effects: ors_client.py, geo.py, planner.py, errors.py
    api/             serializers, two thin views, the error envelope
    tests/           146 tests
frontend/
  src/components/    TripForm, RouteMap, StopItinerary, TripSummary, LogSheet
  src/types/         mirrors the API contract field for field
docs/                architecture and design notes, FMCSA reference material
```

## Docs

- [docs/architecture.md](docs/architecture.md): layering, request lifecycle, the engine, the
  RODS pipeline.
- [docs/design-choices.md](docs/design-choices.md): the decisions and trade-offs.

## Attributions

- Routing, geocoding and reverse geocoding by
  [OpenRouteService](https://openrouteservice.org/), on the `driving-hgv` profile.
- Map tiles and place data from [OpenStreetMap](https://www.openstreetmap.org/copyright)
  contributors.
- Hours-of-service rules from 49 CFR Part 395 and the FMCSA
  [Interstate Truck Driver's Guide to Hours of Service](https://www.fmcsa.dot.gov/).
- The log sheet reproduces the standard US DOT driver's daily log form.
