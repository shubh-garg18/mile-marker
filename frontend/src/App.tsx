import { useEffect, useRef, useState } from "react";

import { ApiError, checkHealth, planTrip } from "./api/client";
import BlankSheet from "./components/BlankSheet";
import LogSheetStack from "./components/LogSheetStack";
import RouteMap from "./components/RouteMap";
import StopItinerary from "./components/StopItinerary";
import TripForm from "./components/TripForm";
import TripSummary from "./components/TripSummary";
import type { TripPlan, TripPlanRequest } from "./types/trip";

/** How long a request may run before we explain that the server is waking. */
const COLD_START_HINT_MS = 3000;

export default function App() {
  const [plan, setPlan] = useState<TripPlan | null>(null);
  const [isPlanning, setIsPlanning] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [showColdStartHint, setShowColdStartHint] = useState(false);
  const requestId = useRef(0);

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

      <header className="border-b border-hairline print:hidden">
        <div className="mx-auto flex max-w-[110rem] flex-wrap items-baseline gap-x-4 gap-y-1 px-5 py-4 desk:px-8">
          <h1 className="flex items-baseline gap-2.5">
            <span className="font-display text-lg font-bold tracking-tight text-bright">
              Mile Marker
            </span>
            <span
              aria-hidden="true"
              className="hidden h-3.5 w-px self-center bg-hairline desk:block"
            />
            <span className="font-display text-xs tracking-[0.2em] text-signal uppercase">
              ELD trip planner
            </span>
          </h1>
          <p className="text-sm text-steel">
            Route, required stops, and a drawn FMCSA daily log for every day of the trip.
          </p>
          {plan ? (
            <button
              type="button"
              onClick={() => window.print()}
              className="ml-auto rounded-sm border border-hairline px-3 py-1.5 font-display text-xs tracking-widest text-steel uppercase transition-colors hover:border-signal hover:text-signal"
            >
              Print / Save as PDF
            </button>
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

        <section className="flex min-w-0 flex-col gap-8">
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
        <section className="mx-auto min-w-0 max-w-[110rem] px-5 pb-8 desk:px-8">
          <LogSheetStack days={plan.days} header={plan.log_header} trip={plan.trip} />
        </section>
      ) : null}
    </div>
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
