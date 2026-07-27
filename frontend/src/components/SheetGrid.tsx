/**
 * The paper form's shared anatomy, drawn once and used by both the filled log
 * sheet and the blank empty-state sheet.
 *
 * Everything here reproduces `docs/reference/blank-paper-log.png`: the black
 * hour-band masthead, the tick hierarchy, the remarks bar, the shipping block
 * and the recap strip are the printed matter of the real RODS form. Keeping
 * them in one module is what guarantees the blank sheet and the filled sheet
 * are the same piece of paper.
 */

import type { ReactElement } from "react";

import { DUTY_STATUS_LABELS, DUTY_STATUS_ORDER, type DutyStatus } from "../types/trip";

// --------------------------------------------------------------------------- //
// Geometry, per spec section 13.2
// --------------------------------------------------------------------------- //

export const VIEW_WIDTH = 1100;
export const VIEW_HEIGHT = 430;

export const GRID_LEFT = 110; // row label gutter occupies 0 → 110
export const GRID_RIGHT = 974; // 864 px for 24 h
export const TOTALS_RIGHT = 1060;
export const PX_PER_HOUR = (GRID_RIGHT - GRID_LEFT) / 24; // 36
export const PX_PER_MINUTE = PX_PER_HOUR / 60;

export const HOUR_BAND_BOTTOM = 28;
export const ROW_HEIGHT = 44;
export const GRID_BOTTOM = HOUR_BAND_BOTTOM + ROW_HEIGHT * 4; // 204

/** Top of the shipping block. The remarks strip must not reach it. */
export const SHIPPING_DIVIDER_Y = VIEW_HEIGHT - 46;

export const INK = "var(--color-ink)";
export const PAPER = "var(--color-paper)";

/** Amber is unreadable on manila; the sheet uses the darker paper variants. */
export const PAPER_STATUS_COLORS: Record<DutyStatus, string> = {
  off_duty: "var(--color-steel-ink)",
  sleeper_berth: "var(--color-berth-ink)",
  driving: "var(--color-signal-ink)",
  on_duty_not_driving: "var(--color-onduty-ink)",
};

/** Minute from midnight to an x coordinate. */
export const x = (minute: number) => GRID_LEFT + minute * PX_PER_MINUTE;

/** The centerline of a status row: 50, 94, 138, 182. */
export const rowCenter = (status: DutyStatus) =>
  HOUR_BAND_BOTTOM + ROW_HEIGHT * DUTY_STATUS_ORDER.indexOf(status) + ROW_HEIGHT / 2;

export const rowTop = (index: number) => HOUR_BAND_BOTTOM + ROW_HEIGHT * index;

export const HOURS = Array.from({ length: 25 }, (_, hour) => hour);

// --------------------------------------------------------------------------- //
// The masthead: the reference form's hour band is black with white numerals
// --------------------------------------------------------------------------- //

export function Masthead() {
  // The band caps extend past the first and last hour, as on the form, and the
  // left cap gives the stacked "Mid-night" label a ground to sit on.
  const capLeft = GRID_LEFT - 28;
  return (
    <g>
      <rect x={capLeft} y={0} width={TOTALS_RIGHT - capLeft} height={HOUR_BAND_BOTTOM} fill={INK} />
      <g fontSize="8.5" fill={PAPER} textAnchor="middle">
        {HOURS.map((hour) => {
          const at = x(hour * 60);
          if (hour === 0 || hour === 24) {
            return (
              <text key={hour} x={at} y={10}>
                <tspan x={at} dy="0">
                  Mid-
                </tspan>
                <tspan x={at} dy="9">
                  night
                </tspan>
              </text>
            );
          }
          return (
            <text key={hour} x={at} y={19}>
              {hour === 12 ? "Noon" : hour % 12}
            </text>
          );
        })}
        <text x={(GRID_RIGHT + TOTALS_RIGHT) / 2} y={10} fontSize="7.5">
          <tspan x={(GRID_RIGHT + TOTALS_RIGHT) / 2} dy="0">
            Total
          </tspan>
          <tspan x={(GRID_RIGHT + TOTALS_RIGHT) / 2} dy="9">
            Hours
          </tspan>
        </text>
      </g>
    </g>
  );
}

// --------------------------------------------------------------------------- //
// The grid
// --------------------------------------------------------------------------- //

export function GridRules() {
  return (
    <g stroke={INK} fill="none">
      {/* Row labels in the gutter. */}
      {/* "4. On Duty (not driving)" is 24 characters, 115 px at this size, which
          starts at x = -13 and is clipped by the viewBox. The reference form
          breaks it over two lines, so this does too. */}
      <g fontSize="8" fill={INK} stroke="none" textAnchor="end">
        {DUTY_STATUS_ORDER.map((status, index) => {
          const [first, second] = splitRowLabel(index + 1, DUTY_STATUS_LABELS[status]);
          return (
            <text key={status} x={GRID_LEFT - 8} y={rowCenter(status) + (second ? -1 : 3)}>
              <tspan x={GRID_LEFT - 8}>{first}</tspan>
              {second ? (
                <tspan x={GRID_LEFT - 8} dy="9">
                  {second}
                </tspan>
              ) : null}
            </text>
          );
        })}
      </g>

      {/* Horizontal rules: the four row bands. */}
      {[0, 1, 2, 3, 4].map((index) => (
        <line
          key={index}
          x1={GRID_LEFT}
          x2={TOTALS_RIGHT}
          y1={rowTop(index)}
          y2={rowTop(index)}
          strokeWidth={index === 0 || index === 4 ? 1.2 : 0.6}
        />
      ))}

      {/* Vertical rules: every hour boundary, full height. */}
      {HOURS.map((hour) => (
        <line
          key={hour}
          x1={x(hour * 60)}
          x2={x(hour * 60)}
          y1={HOUR_BAND_BOTTOM}
          y2={GRID_BOTTOM}
          strokeWidth={hour % 6 === 0 ? 1.2 : 0.6}
        />
      ))}

      {/* The totals column. */}
      <line
        x1={TOTALS_RIGHT}
        x2={TOTALS_RIGHT}
        y1={HOUR_BAND_BOTTOM}
        y2={GRID_BOTTOM}
        strokeWidth={1.2}
      />
    </g>
  );
}

/**
 * The 15-, 30- and 45-minute subdivisions, rising from each row's baseline.
 * Their differing lengths make the grid readable at a glance, with half-hours
 * standing proud of the quarter-hours.
 */
export function QuarterHourTicks() {
  const marks: ReactElement[] = [];

  DUTY_STATUS_ORDER.forEach((_status, row) => {
    const baseline = rowTop(row + 1);
    for (let hour = 0; hour < 24; hour += 1) {
      for (const [quarter, length] of [
        [15, 7],
        [30, 14],
        [45, 7],
      ] as const) {
        const at = x(hour * 60 + quarter);
        marks.push(
          <line
            key={`${row}-${hour}-${quarter}`}
            x1={at}
            x2={at}
            y1={baseline}
            y2={baseline - length}
          />,
        );
      }
    }
  });

  return (
    <g stroke={INK} strokeWidth={0.5}>
      {marks}
    </g>
  );
}

// --------------------------------------------------------------------------- //
// Remarks scaffold and the printed blocks beneath it
// --------------------------------------------------------------------------- //

export function RemarksScaffold() {
  return (
    <g>
      {/* The reference form marks the remarks region with a heavy bar. */}
      <rect x={0} y={GRID_BOTTOM + 6} width={3} height={SHIPPING_DIVIDER_Y - GRID_BOTTOM - 14} fill={INK} />
      <text x={9} y={GRID_BOTTOM + 15} fontSize="9" fill={INK}>
        Remarks
      </text>

      {/* The hour ticks repeat here, as they do on the paper form. */}
      <g stroke={INK} strokeWidth={0.5}>
        {HOURS.map((hour) => (
          <line
            key={hour}
            x1={x(hour * 60)}
            x2={x(hour * 60)}
            y1={GRID_BOTTOM + 2}
            y2={GRID_BOTTOM + 10}
          />
        ))}
        <line
          x1={GRID_LEFT}
          x2={GRID_RIGHT}
          y1={GRID_BOTTOM + 10}
          y2={GRID_BOTTOM + 10}
          strokeWidth={0.8}
        />
      </g>
    </g>
  );
}

/**
 * The blocks the reference form carries below the remarks: shipping documents on
 * the left, the home-terminal time-standard instruction across the middle. On
 * the blank sheet the values are empty writing lines, exactly as the pad prints
 * them.
 */
export function ShippingBlock({
  shippingDocument,
  shipperCommodity,
}: {
  shippingDocument?: string;
  shipperCommodity?: string;
}) {
  return (
    <g fontSize="8" fill={INK}>
      <line
        x1={0}
        x2={VIEW_WIDTH}
        y1={SHIPPING_DIVIDER_Y}
        y2={SHIPPING_DIVIDER_Y}
        stroke={INK}
        strokeWidth={0.8}
      />
      <BlockLine y={VIEW_HEIGHT - 30} label="Shipping documents:" value={shippingDocument} />
      <BlockLine y={VIEW_HEIGHT - 16} label="Shipper & commodity:" value={shipperCommodity} />
      <text x={VIEW_WIDTH} y={VIEW_HEIGHT - 30} textAnchor="end" opacity={0.75}>
        Enter name of place you reported and where released from work, and when and where each
        change of duty status occurred.
      </text>
      <text x={VIEW_WIDTH} y={VIEW_HEIGHT - 16} textAnchor="end" opacity={0.75}>
        Use time standard of home terminal.
      </text>
    </g>
  );
}

function BlockLine({ y, label, value }: { y: number; label: string; value?: string }) {
  return (
    <>
      <text x={0} y={y}>
        <tspan opacity={0.6}>{label} </tspan>
        {value ? <tspan>{value}</tspan> : null}
      </text>
      {value ? null : (
        <line x1={96} x2={280} y1={y + 2} y2={y + 2} stroke={INK} strokeWidth={0.5} opacity={0.5} />
      )}
    </>
  );
}

// --------------------------------------------------------------------------- //
// HTML pieces of the form: header fields, date boxes, From/To, recap
// --------------------------------------------------------------------------- //

/** One labelled field of the header block. No value renders a blank line. */
export function HeaderField({ label, value }: { label: string; value?: string }) {
  return (
    <div className="min-w-0 border-b border-ink/25 pb-1">
      <dt className="text-[0.6rem] tracking-wider uppercase opacity-55">{label}</dt>
      <dd className="truncate" title={value || undefined}>
        {value || " "}
      </dd>
    </div>
  );
}

/** The form's boxed date: month / day / year, each over its own printed label. */
export function DateBoxes({ iso }: { iso?: string }) {
  const [year, month, day] = iso ? iso.slice(0, 10).split("-") : ["", "", ""];
  return (
    <div className="flex items-start gap-1.5 font-data text-sm">
      <DateBox value={month} label="month" width="min-w-[2.5ch]" />
      <span className="opacity-40">/</span>
      <DateBox value={day} label="day" width="min-w-[2.5ch]" />
      <span className="opacity-40">/</span>
      <DateBox value={year} label="year" width="min-w-[4.5ch]" />
    </div>
  );
}

function DateBox({ value, label, width }: { value: string; label: string; width: string }) {
  return (
    <span className="flex flex-col items-center gap-0.5">
      <span className={`${width} border-b border-ink/40 text-center leading-tight`}>
        {value || " "}
      </span>
      <span className="text-[0.5rem] tracking-wider uppercase opacity-50">({label})</span>
    </span>
  );
}

/** The form's From / To row: where the day's work started and ended. */
export function FromTo({ from, to }: { from?: string; to?: string }) {
  return (
    <div className="grid grid-cols-2 gap-x-6 font-data text-xs">
      <FromToField label="From" value={from} />
      <FromToField label="To" value={to} />
    </div>
  );
}

function FromToField({ label, value }: { label: string; value?: string }) {
  return (
    <span className="flex min-w-0 items-baseline gap-2 border-b border-ink/25 pb-1">
      <span className="shrink-0 text-[0.6rem] tracking-wider uppercase opacity-55">{label}</span>
      <span className="truncate" title={value || undefined}>
        {value || " "}
      </span>
    </span>
  );
}

/**
 * The recap strip along the form's bottom edge. Only "on duty today" can be
 * filled from a single sheet — it is the sum of lines 3 and 4, printed right on
 * the form. The A/B/C figures need the eight-day history the API deliberately
 * does not model (it takes one scalar), so they stay blank printed fields, as on
 * the pad; the app-level cycle arithmetic lives in the trip summary instead.
 */
export function RecapStrip({ onDutyToday }: { onDutyToday?: string }) {
  return (
    <div className="mt-3 flex flex-wrap items-baseline gap-x-5 gap-y-1 border-t border-ink/25 pt-2 font-data text-[0.6rem] leading-relaxed text-ink/70">
      <span className="font-display tracking-widest uppercase">Recap · 70 hour / 8 day</span>
      <span>
        On duty today, lines 3 &amp; 4:{" "}
        {onDutyToday ? <span className="font-semibold text-ink">{onDutyToday}</span> : <BlankRule />}
      </span>
      <span>
        A. On duty last 7 days <BlankRule />
      </span>
      <span>
        B. Available tomorrow, 70 hr − A <BlankRule />
      </span>
      <span>
        C. On duty last 5 days <BlankRule />
      </span>
    </div>
  );
}

function BlankRule() {
  return <span className="inline-block w-8 border-b border-ink/40 align-baseline">{" "}</span>;
}

export function splitRowLabel(index: number, label: string): [string, string | null] {
  const [head, tail] = label.split(" (");
  return tail ? [`${index}. ${head}`, `(${tail}`] : [`${index}. ${label}`, null];
}
