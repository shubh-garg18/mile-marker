import { useId } from "react";

import { hoursAsClock, miles, shortDate } from "../format";
import {
  DUTY_STATUS_LABELS,
  DUTY_STATUS_ORDER,
  type LogHeader,
  type Remark,
  type RodsDay,
} from "../types/trip";
import {
  DateBoxes,
  FromTo,
  GRID_BOTTOM,
  GRID_LEFT,
  GRID_RIGHT,
  GridRules,
  HeaderField,
  HOUR_BAND_BOTTOM,
  INK,
  Masthead,
  PAPER_STATUS_COLORS,
  QuarterHourTicks,
  RecapStrip,
  RemarksScaffold,
  rowCenter,
  ShippingBlock,
  TOTALS_RIGHT,
  VIEW_HEIGHT,
  VIEW_WIDTH,
  x,
} from "./SheetGrid";

/**
 * One day's Record of Duty Status, drawn to the geometry of the paper form in
 * `docs/reference/blank-paper-log.png`.
 *
 * The hairline rules and the tick hierarchy are not decoration. Reproducing them
 * is what makes the output read as a real RODS rather than as graph paper. The
 * duty-status trace is one continuous path, a horizontal run on each row's
 * centerline plus a vertical connector at every transition, because a gap or an
 * overlap is the visual tell of an invalid log.
 *
 * When a plan arrives the trace inks itself in from midnight to midnight — an
 * animated clip, not a redraw — and the totals and remarks settle after it. The
 * finished state is identical to the unanimated sheet, so reduced motion and
 * print simply show it at once.
 */

const REMARK_LABEL_MAX_CHARS = 26;

/**
 * Rotated remark labels are staggered across three baselines. At -60 degrees a
 * label's ink is 8 px tall, while two remarks 15 minutes apart sit only 7.8 px
 * apart perpendicular to the baseline. Consecutive labels on one row therefore
 * overlap, and a busy sheet becomes a hatch of diagonal text over the leader
 * lines. Moving to another row whenever the previous remark is close pulls them
 * apart.
 *
 * The three baselines have to fit between the rule under the hour ticks and the
 * shipping block, because a -60 degree label reaches up and to the right: a
 * 26-character label at 8 px rises about 111 px above its own baseline. Below
 * 326 the ink climbs back into the duty grid; past 380 it lands in the shipping
 * block. Both used to happen, since the strip and the block were laid out to
 * overlapping bands.
 */
const REMARK_FONT_SIZE = 8;
const REMARK_BASELINES = [326, 353, 380] as const;

/** How long each sheet waits before its trace starts to draw, by sheet index. */
const traceDelaySeconds = (dayNumber: number) => 0.25 + Math.min(dayNumber - 1, 4) * 0.35;

interface LogSheetProps {
  day: RodsDay;
  header: LogHeader;
  totalDays: number;
}

export default function LogSheet({ day, header, totalDays }: LogSheetProps) {
  // SVG clip ids are document-global, and every sheet on the page needs its own.
  const clipId = `trace-${useId().replace(/:/g, "")}`;
  const traceDelay = `${traceDelaySeconds(day.day_number)}s`;
  const inkDelay = `${traceDelaySeconds(day.day_number) + 0.9}s`;

  return (
    <article
      aria-label={`Driver's daily log for ${day.date}`}
      className="sheet-lift break-inside-avoid rounded-sm bg-paper p-6 text-ink [color-scheme:light] print:rounded-none print:p-4"
    >
      <SheetHeader day={day} header={header} totalDays={totalDays} />

      {/* The grid stops shrinking at 68rem and scrolls instead. Left to scale
          freely it renders at 404 px the moment the two-column desktop layout
          engages, putting the row labels at under 3 px, worse than the phone. */}
      <div className="sheet-scroll mt-4 overflow-x-auto">
        <svg
          viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
          width="100%"
          role="img"
          aria-label={`Duty status grid for ${day.date}: ${DUTY_STATUS_ORDER.map(
            (status) => `${DUTY_STATUS_LABELS[status]} ${hoursAsClock(day.totals[status])}`,
          ).join(", ")}`}
          className="block min-w-[68rem] font-data"
        >
          <defs>
            {/* The reveal: a rect that widens across the day. Its resting width
                is the full grid, so a browser that cannot animate SVG geometry,
                a print run, or reduced motion all get the finished trace. */}
            <clipPath id={clipId}>
              <rect
                className="trace-draw"
                style={{ animationDelay: traceDelay }}
                x={GRID_LEFT - 4}
                y={HOUR_BAND_BOTTOM - 4}
                width={GRID_RIGHT - GRID_LEFT + 8}
                height={GRID_BOTTOM - HOUR_BAND_BOTTOM + 8}
              />
            </clipPath>
          </defs>

          <Masthead />
          <GridRules />
          <QuarterHourTicks />
          <g clipPath={`url(#${clipId})`}>
            <DutyTrace day={day} />
          </g>
          <g className="ink-fade" style={{ animationDelay: inkDelay }}>
            <TotalsColumn day={day} />
          </g>
          <RemarksStrip day={day} header={header} inkDelay={inkDelay} />
        </svg>
      </div>

      <RecapStrip
        onDutyToday={hoursAsClock(day.totals.driving + day.totals.on_duty_not_driving)}
      />
      <Legend />
    </article>
  );
}

// --------------------------------------------------------------------------- //
// Header: the paper form's top block
// --------------------------------------------------------------------------- //

function SheetHeader({ day, header, totalDays }: LogSheetProps) {
  // The form's From / To: where the day's duty began and ended. A day spent
  // entirely inside a rest has no status changes and prints them blank, exactly
  // as the pad would.
  const from = day.remarks[0]?.location;
  const to = day.remarks[day.remarks.length - 1]?.location;

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
        <DateBoxes iso={day.date} />
        <div className="text-right font-data text-[0.6rem] leading-relaxed opacity-70">
          <p>Original — file at home terminal.</p>
          <p>Duplicate — driver retains for eight days.</p>
          <p className="mt-0.5 font-semibold">
            {shortDate(day.date)} · Sheet {day.day_number} of {totalDays}
          </p>
        </div>
      </div>

      <FromTo from={from} to={to} />

      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 font-data text-xs desk:grid-cols-4">
        <HeaderField label="Driver" value={header.driver_name} />
        <HeaderField label="Carrier" value={header.carrier_name} />
        <HeaderField label="Main office" value={header.office_address} />
        <HeaderField label="Home terminal" value={header.terminal_address} />
        <HeaderField label="Total miles driving today" value={miles(day.driving_miles)} />
        <HeaderField
          label="Tractor / trailer"
          value={`${header.tractor_number} / ${header.trailer_number}`}
        />
        <HeaderField label="Shipping document" value={header.shipping_document} />
        <HeaderField label="Shipper & commodity" value={header.shipper_commodity} />
      </dl>
    </header>
  );
}

// --------------------------------------------------------------------------- //
// The duty-status trace
// --------------------------------------------------------------------------- //

function DutyTrace({ day }: { day: RodsDay }) {
  return (
    <g strokeWidth={3} strokeLinecap="square" fill="none">
      {day.segments.map((segment) => (
        <line
          key={`run-${segment.start_minute}`}
          x1={x(segment.start_minute)}
          x2={x(segment.end_minute)}
          y1={rowCenter(segment.status)}
          y2={rowCenter(segment.status)}
          stroke={PAPER_STATUS_COLORS[segment.status]}
        />
      ))}

      {day.segments.slice(0, -1).map((segment, index) => {
        const next = day.segments[index + 1];
        return (
          <line
            key={`step-${segment.end_minute}`}
            x1={x(segment.end_minute)}
            x2={x(segment.end_minute)}
            y1={rowCenter(segment.status)}
            y2={rowCenter(next.status)}
            stroke={PAPER_STATUS_COLORS[next.status]}
          />
        );
      })}
    </g>
  );
}

function TotalsColumn({ day }: { day: RodsDay }) {
  return (
    <g fontSize="11" fill={INK} textAnchor="end">
      {DUTY_STATUS_ORDER.map((status) => (
        <text key={status} x={TOTALS_RIGHT - 10} y={rowCenter(status) + 4}>
          {hoursAsClock(day.totals[status])}
        </text>
      ))}
      <text x={TOTALS_RIGHT - 10} y={GRID_BOTTOM + 15} fontSize="11" fontWeight="600">
        = {hoursAsClock(day.totals.total)}
      </text>
    </g>
  );
}

// --------------------------------------------------------------------------- //
// Remarks
// --------------------------------------------------------------------------- //

function RemarksStrip({ day, header, inkDelay }: { day: RodsDay; header: LogHeader; inkDelay: string }) {
  return (
    <g>
      <RemarksScaffold />

      <g className="ink-fade" style={{ animationDelay: inkDelay }}>
        {stagger(day.remarks).map(({ remark, baseline }) => {
          const at = x(remark.minute);
          const label = truncate(remark.location, REMARK_LABEL_MAX_CHARS);
          return (
            <g key={`${remark.minute}-${remark.note}`}>
              <title>{`${minuteAsClock(remark.minute)} ${remark.location}: ${remark.note}`}</title>
              <line
                x1={at}
                x2={at}
                y1={GRID_BOTTOM + 10}
                y2={baseline - 4}
                stroke={INK}
                strokeWidth={0.6}
              />
              <text
                x={at + 4}
                y={baseline}
                fontSize={REMARK_FONT_SIZE}
                fill={INK}
                transform={`rotate(-60, ${at + 4}, ${baseline})`}
              >
                {label}
              </text>
            </g>
          );
        })}
      </g>

      <ShippingBlock
        shippingDocument={header.shipping_document}
        shipperCommodity={header.shipper_commodity}
      />
    </g>
  );
}

/**
 * Assign each remark the highest baseline that clears the labels already placed.
 *
 * What separates two parallel labels is their distance perpendicular to the -60
 * degree baseline, not their distance on the page. Cycling rows modulo three does
 * not reliably increase it. Dropping to the next row moves a label down, but the
 * later remark is also further right, and at -60 degrees right-and-up runs along
 * the text. Wrapping from the last row back to the first moves up-and-right,
 * almost exactly parallel, so the wrapped label lands back on top of the one
 * three remarks earlier. Measuring the clearance directly is simpler to reason
 * about and stays correct at any row spacing.
 */
const PERP_X = Math.sin(Math.PI / 3);
const PERP_Y = Math.cos(Math.PI / 3);

/** Ink height plus a hairline of air. */
const REMARK_CLEARANCE = REMARK_FONT_SIZE + 2;

function stagger(remarks: Remark[]): { remark: Remark; baseline: number }[] {
  const placed: number[] = [];

  return remarks.map((remark) => {
    const at = x(remark.minute) + 4;
    // Only the last few can still be near enough to matter, and there are only
    // three rows to place into.
    const recent = placed.slice(-REMARK_BASELINES.length);

    let chosen: number = REMARK_BASELINES[0];
    let roomiest = -Infinity;

    for (const baseline of REMARK_BASELINES) {
      const perp = at * PERP_X + baseline * PERP_Y;
      const clearance = recent.length
        ? Math.min(...recent.map((other) => Math.abs(perp - other)))
        : Infinity;

      if (clearance >= REMARK_CLEARANCE) {
        chosen = baseline;
        break;
      }
      if (clearance > roomiest) {
        roomiest = clearance;
        chosen = baseline;
      }
    }

    placed.push(at * PERP_X + chosen * PERP_Y);
    return { remark, baseline: chosen };
  });
}

function Legend() {
  return (
    <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 font-data text-[0.65rem] text-ink/75">
      {DUTY_STATUS_ORDER.map((status) => (
        <li key={status} className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="inline-block h-0.5 w-5"
            style={{ backgroundColor: PAPER_STATUS_COLORS[status] }}
          />
          {DUTY_STATUS_LABELS[status]}
        </li>
      ))}
    </ul>
  );
}

function truncate(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}

function minuteAsClock(minute: number): string {
  return `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
}
