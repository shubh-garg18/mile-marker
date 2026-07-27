import { useEffect, useRef, useState } from "react";

import { ApiError, checkHealth, planTrip } from "./api/client";
import BlankSheet from "./components/BlankSheet";
import LogSheetStack from "./components/LogSheetStack";
import RouteMap from "./components/RouteMap";
import StopItinerary from "./components/StopItinerary";
import TripForm from "./components/TripForm";
import TripSummary from "./components/TripSummary";
import { miles } from "./format";
import type { TripPlan, TripPlanRequest } from "./types/trip";

/** How long a request may run before we explain that the server is waking. */
const COLD_START_HINT_MS = 3000;

export default function App() {
  const [plan, setPlan] = useState<TripPlan | null>(null);
  const [isPlanning, setIsPlanning] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [showColdStartHint, setShowColdStartHint] = useState(false);
  const requestId = useRef(0);
  const results = useRef<HTMLElement>(null);

  // Below the desk breakpoint the layout is one column, so a finished plan lands
  // under the form and off the bottom of a phone screen: the button appears to
  // do nothing. Two columns need no scroll, because the result is already in
  // view beside the form.
  useEffect(() => {
    if (!plan || window.matchMedia("(min-width: 900px)").matches) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    results.current?.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "start" });
  }, [plan]);

  // Wake the free-tier backend before anyone has finished typing.
  useEffect(() => {
    void checkHealth();
  }, []);

  async function handleSubmit(request: TripPlanRequest) {
    const id = ++requestId.current;
    setIsPlanning(true);
    setError(null);
    setShowColdStartHint(false);

    const hintTimer = setTimeout(() => {
      if (requestId.current === id) setShowColdStartHint(true);
    }, COLD_START_HINT_MS);

    try {
      const result = await planTrip(request);
      if (requestId.current === id) setPlan(result);
    } catch (caught) {
      if (requestId.current === id) {
        setError(
          caught instanceof ApiError
            ? caught
            : new ApiError("INTERNAL_ERROR", "Something went wrong. Please try again."),
        );
      }
    } finally {
      clearTimeout(hintTimer);
      if (requestId.current === id) {
        setIsPlanning(false);
        setShowColdStartHint(false);
      }
    }
  }

  const origin = plan?.waypoints.find((point) => point.role === "current");

  // A polite live region is only reliably announced when it already exists and
  // its contents change. Rendering it only while planning would mount the region
  // and its text in one commit, which screen readers commonly miss.
  const announcement = isPlanning
    ? "Routing and simulating hours of service."
    : plan
      ? `Plan ready. ${plan.trip.days_count} log ${
          plan.trip.days_count === 1 ? "sheet" : "sheets"
        }, ${plan.stops.length} stops.`
      : error
        ? `Could not plan that trip. ${error.message}`
        : "";

  return (
    <div className="min-h-screen bg-console">
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>

      {/* The sheets run to several screens, so tabbing from the form to the
          results means passing every field and every stop. Visible only when
          focused, as a skip link should be. */}
      {plan ? (
        <a
          href="#log-sheets"
          className="sr-only rounded-sm bg-signal px-4 py-2 font-display text-sm font-semibold text-console focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-[1001]"
        >
          Skip to the log sheets
        </a>
      ) : null}

      {/* Identity on the left, actions on the right, and nothing else. The
          descriptive line that used to sit here was onboarding copy in permanent
          chrome; it now lives in the empty state, where it is read once and then
          replaced by the plan. Sticky because the sheets make the page long, so
          Print and the running totals stay reachable from the bottom of day
          three. Above Leaflet's controls, which sit at z-index 800. */}
      <header className="sticky top-0 z-[1000] border-b border-hairline/40 bg-console/85 backdrop-blur-md print:hidden">
        <div className="mx-auto flex max-w-[110rem] items-center gap-4 px-5 py-3 desk:px-8">
          <h1 className="flex items-center gap-2.5">
            <SheetMark />
            <span className="font-display text-base font-bold tracking-tight text-bright">
              Mile Marker
            </span>
          </h1>

          {plan ? (
            <div className="ml-auto flex items-center gap-3 desk:gap-5">
              <p className="hidden font-data text-xs tabular-nums text-steel desk:block">
                {miles(plan.trip.total_distance_miles)} mi
                <span className="mx-2 text-hairline">·</span>
                {plan.trip.days_count} {plan.trip.days_count === 1 ? "sheet" : "sheets"}
              </p>
              <button
                type="button"
                onClick={() => window.print()}
                className="rounded-sm border border-hairline px-3 py-1.5 font-display text-xs tracking-widest text-steel uppercase transition-colors hover:border-signal hover:text-signal"
              >
                Print
              </button>
            </div>
          ) : null}
        </div>
      </header>

      <main className="mx-auto grid max-w-[110rem] gap-8 px-5 pt-8 pb-8 desk:grid-cols-[22rem_minmax(0,1fr)] desk:px-8">
        <aside className="flex flex-col gap-8 print:hidden">
          <div className="rounded-sm border border-hairline bg-console-2 p-5">
            <TripForm
              onSubmit={handleSubmit}
              isPlanning={isPlanning}
              errorField={error?.field ?? null}
              errorMessage={error?.message ?? null}
            />
            {isPlanning ? <PlanningNotice showColdStartHint={showColdStartHint} /> : null}
            {error && !error.field ? <ErrorNotice message={error.message} /> : null}
          </div>

          {plan ? (
            <>
              <div className="rounded-sm border border-hairline bg-console-2 p-5">
                <TripSummary trip={plan.trip} warnings={plan.warnings} />
              </div>
              <div className="rounded-sm border border-hairline bg-console-2 p-5">
                <StopItinerary
                  stops={plan.stops}
                  originLabel={origin?.label ?? "Origin"}
                  departure={plan.trip.start_datetime}
                />
              </div>
            </>
          ) : null}
        </aside>

        <section ref={results} className="flex min-w-0 scroll-mt-20 flex-col gap-8">
          {plan ? (
            <div className="print:hidden">
              <RouteMap route={plan.route} stops={plan.stops} waypoints={plan.waypoints} />
            </div>
          ) : (
            <BlankSheet isPlanning={isPlanning} />
          )}
        </section>
      </main>

      {/* The sheets sit outside the two-column grid because a log sheet is a
          document: it is 68rem wide at its readable minimum, which does not fit
          beside a 22rem sidebar until the viewport passes 1536px. In the column
          it scrolled horizontally on any ordinary laptop, clipping the grid. */}
      {plan ? (
        <section
          id="log-sheets"
          className="mx-auto min-w-0 max-w-[110rem] scroll-mt-20 px-5 pb-8 desk:px-8"
        >
          <LogSheetStack days={plan.days} header={plan.log_header} trip={plan.trip} />
        </section>
      ) : null}
    </div>
  );
}

/**
 * The wordmark's glyph: the four duty rows of a log sheet, with the driving row
 * struck in amber. The product's own artifact at 18 px, rather than a road or a
 * truck, which would say "transport" without saying which part of it this is.
 */
function SheetMark() {
  const rows = [4.5, 7.75, 11, 14.25];
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" className="shrink-0">
      <rect
        x={0.75}
        y={0.75}
        width={16.5}
        height={16.5}
        rx={2}
        fill="none"
        stroke="var(--color-hairline)"
        strokeWidth={1}
      />
      {rows.map((y, index) => {
        const driving = index === 2;
        return (
          <line
            key={y}
            x1={3.75}
            y1={y}
            x2={driving ? 14.25 : 11}
            y2={y}
            stroke={driving ? "var(--color-signal)" : "var(--color-hairline)"}
            strokeWidth={driving ? 1.5 : 1}
            strokeLinecap="round"
          />
        );
      })}
    </svg>
  );
}

function PlanningNotice({ showColdStartHint }: { showColdStartHint: boolean }) {
  return (
    <div className="mt-4 border-t border-hairline pt-4">
      <p className="font-data text-sm text-signal">Routing and simulating hours of service…</p>
      {showColdStartHint ? (
        <p className="mt-1.5 text-xs leading-relaxed text-steel">
          The API runs on a free instance that sleeps when idle. Waking it can take up to a minute.
          This is not a failure.
        </p>
      ) : null}
    </div>
  );
}

function ErrorNotice({ message }: { message: string }) {
  return (
    <p
      role="alert"
      className="mt-4 border-t border-hairline pt-4 text-sm leading-relaxed text-flag"
    >
      {message}
    </p>
  );
}
