/**
 * The empty and loading state: a real, unfilled duty-status grid.
 *
 * A driver's day starts as a blank Record of Duty Status, so the app does too.
 * Showing the actual artifact before anything is typed says what the product
 * makes far faster than a paragraph does, and it uses the same geometry as the
 * finished sheet, so nothing here is a mock-up of something that looks different
 * once it is real.
 *
 * While a plan is running, an amber sweep crosses the grid from midnight to
 * midnight. The progress indicator is the subject: 24 hours being simulated.
 */

import { DUTY_STATUS_LABELS, DUTY_STATUS_ORDER } from "../types/trip";

const VIEW_WIDTH = 1100;
const VIEW_HEIGHT = 232;

const GRID_LEFT = 110;
const GRID_RIGHT = 974;
const PX_PER_HOUR = (GRID_RIGHT - GRID_LEFT) / 24;

const HOUR_BAND_BOTTOM = 28;
const ROW_HEIGHT = 44;
const GRID_BOTTOM = HOUR_BAND_BOTTOM + ROW_HEIGHT * 4;

const HAIRLINE = "var(--color-ink)";

/** Midnight, noon and midnight are named; the rest are numbered as on the form. */
function hourLabel(hour: number): string {
  if (hour === 0 || hour === 24) return "Mid-night";
  if (hour === 12) return "Noon";
  return String(hour > 12 ? hour - 12 : hour);
}

export default function BlankSheet({ isPlanning }: { isPlanning: boolean }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="font-display text-xs tracking-widest text-steel uppercase">
          Record of duty status
        </h2>
        <p className="font-data text-xs text-steel">
          {isPlanning ? "Simulating 24 hours at a time…" : "Awaiting a trip"}
        </p>
      </div>

      <div className="sheet-lift overflow-x-auto rounded-sm bg-paper p-4 desk:p-6">
        <svg
          viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
          className="block min-w-[44rem] font-data"
          role="img"
          aria-label={
            isPlanning
              ? "Planning the trip and drawing the daily log sheets"
              : "An empty driver's daily log grid, waiting for a trip"
          }
        >
          <HourBand />
          <Rows />
          {isPlanning ? <Sweep /> : null}
        </svg>
      </div>

      <p className="max-w-prose text-sm leading-relaxed text-steel">
        {isPlanning
          ? "Routing on a truck profile, then placing every stop the regulations require."
          : "Enter a trip on the left. You get the route, every required stop, and one of these sheets for each calendar day the trip spans."}
      </p>
    </div>
  );
}

function HourBand() {
  return (
    <g>
      <rect
        x={GRID_LEFT}
        y={0}
        width={GRID_RIGHT - GRID_LEFT}
        height={HOUR_BAND_BOTTOM}
        fill="none"
        stroke={HAIRLINE}
        strokeWidth={0.8}
      />
      {Array.from({ length: 25 }, (_, hour) => {
        const at = GRID_LEFT + hour * PX_PER_HOUR;
        const label = hourLabel(hour);
        const stacked = label === "Mid-night";
        return (
          <g key={hour}>
            {hour > 0 && hour < 24 ? (
              <line x1={at} y1={0} x2={at} y2={GRID_BOTTOM} stroke={HAIRLINE} strokeWidth={0.5} />
            ) : null}
            <text
              x={at}
              y={stacked ? 11 : 18}
              textAnchor="middle"
              fontSize={8}
              fill={HAIRLINE}
              opacity={0.75}
            >
              {stacked ? "Mid-" : label}
            </text>
            {stacked ? (
              <text x={at} y={21} textAnchor="middle" fontSize={8} fill={HAIRLINE} opacity={0.75}>
                night
              </text>
            ) : null}
          </g>
        );
      })}
    </g>
  );
}

function Rows() {
  return (
    <g>
      {DUTY_STATUS_ORDER.map((status, index) => {
        const top = HOUR_BAND_BOTTOM + index * ROW_HEIGHT;
        const centre = top + ROW_HEIGHT / 2;
        return (
          <g key={status}>
            <rect
              x={GRID_LEFT}
              y={top}
              width={GRID_RIGHT - GRID_LEFT}
              height={ROW_HEIGHT}
              fill="none"
              stroke={HAIRLINE}
              strokeWidth={0.8}
            />
            <text x={GRID_LEFT - 8} y={centre + 3} textAnchor="end" fontSize={9} fill={HAIRLINE}>
              {index + 1}. {DUTY_STATUS_LABELS[status]}
            </text>
            {/* Quarter-hour ticks, rising from the row baseline as on the form. */}
            {Array.from({ length: 96 }, (_, quarter) => {
              const at = GRID_LEFT + (quarter * PX_PER_HOUR) / 4;
              if (quarter % 4 === 0) return null;
              const height = quarter % 2 === 0 ? 10 : 6;
              return (
                <line
                  key={quarter}
                  x1={at}
                  y1={top + ROW_HEIGHT}
                  x2={at}
                  y2={top + ROW_HEIGHT - height}
                  stroke={HAIRLINE}
                  strokeWidth={0.4}
                  opacity={0.7}
                />
              );
            })}
          </g>
        );
      })}
    </g>
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
