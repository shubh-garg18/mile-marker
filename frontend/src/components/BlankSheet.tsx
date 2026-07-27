/**
 * The empty and loading state: a complete, unfilled Record of Duty Status.
 *
 * A driver's day starts as a blank paper log, so the app does too. Showing the
 * whole artifact — masthead, grid, remarks strip, shipping block, recap — before
 * anything is typed says what the product makes far faster than a paragraph
 * does, and it is assembled from the same shared pieces as the finished sheet,
 * so nothing here is a mock-up of something that looks different once it is
 * real. The only differences from a filled sheet are the absences: no ink.
 *
 * While a plan is running, an amber sweep crosses the grid from midnight to
 * midnight. The progress indicator is the subject: 24 hours being simulated.
 */

import {
  DateBoxes,
  FromTo,
  GRID_BOTTOM,
  GRID_LEFT,
  GridRules,
  HeaderField,
  Masthead,
  QuarterHourTicks,
  RecapStrip,
  RemarksScaffold,
  ShippingBlock,
  VIEW_HEIGHT,
  VIEW_WIDTH,
} from "./SheetGrid";

export default function BlankSheet({ isPlanning }: { isPlanning: boolean }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="font-display text-xs tracking-widest text-steel uppercase">
          Record of duty status
        </h2>
        <p className="font-data text-xs text-steel" aria-live="polite">
          {isPlanning ? "Simulating 24 hours at a time…" : "Awaiting a trip"}
        </p>
      </div>

      <div className="sheet-lift rounded-sm bg-paper p-6 text-ink [color-scheme:light]">
        <BlankHeader />

        <div className="sheet-scroll mt-4 overflow-x-auto">
          <svg
            viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
            width="100%"
            role="img"
            aria-label={
              isPlanning
                ? "Planning the trip and drawing the daily log sheets"
                : "An empty driver's daily log sheet, waiting for a trip"
            }
            className="block min-w-[68rem] font-data"
          >
            <Masthead />
            <GridRules />
            <QuarterHourTicks />
            <RemarksScaffold />
            <ShippingBlock />
            {isPlanning ? <Sweep /> : null}
          </svg>
        </div>

        <RecapStrip />
      </div>

      <p className="max-w-prose text-sm leading-relaxed text-steel">
        {isPlanning
          ? "Routing on a truck profile, then placing every stop the regulations require."
          : "Enter a trip on the left. You get the route, every required stop, and one of these sheets filled out for each calendar day the trip spans."}
      </p>
    </div>
  );
}

/** The form's header block with every field left as a blank writing line. */
function BlankHeader() {
  return (
    <header className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2 border-b-2 border-ink pb-2.5">
        <div>
          <h3 className="font-display text-lg leading-tight font-semibold tracking-tight">
            Driver's Daily Log
          </h3>
          <p className="text-[0.6rem] tracking-wider uppercase opacity-55">
            One calendar day — 24 hours
          </p>
        </div>
        <DateBoxes />
        <div className="text-right font-data text-[0.6rem] leading-relaxed opacity-70">
          <p>Original — file at home terminal.</p>
          <p>Duplicate — driver retains for eight days.</p>
        </div>
      </div>

      <FromTo />

      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 font-data text-xs desk:grid-cols-4">
        <HeaderField label="Driver" />
        <HeaderField label="Carrier" />
        <HeaderField label="Main office" />
        <HeaderField label="Home terminal" />
        <HeaderField label="Total miles driving today" />
        <HeaderField label="Tractor / trailer" />
        <HeaderField label="Shipping document" />
        <HeaderField label="Shipper & commodity" />
      </dl>
    </header>
  );
}

/** One amber pass across the day, only while a plan is in flight. */
function Sweep() {
  return (
    <g className="sheet-sweep">
      <defs>
        <linearGradient id="sweep-trail" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor="var(--color-signal-ink)" stopOpacity="0" />
          <stop offset="100%" stopColor="var(--color-signal-ink)" stopOpacity="0.28" />
        </linearGradient>
      </defs>
      <rect x={GRID_LEFT - 120} y={0} width={120} height={GRID_BOTTOM} fill="url(#sweep-trail)" />
      <line
        x1={GRID_LEFT}
        y1={0}
        x2={GRID_LEFT}
        y2={GRID_BOTTOM}
        stroke="var(--color-signal-ink)"
        strokeWidth={1.5}
      />
    </g>
  );
}
