import { hoursAsClock, miles, shortDate } from "../format";
import {
  DUTY_STATUS_LABELS,
  DUTY_STATUS_ORDER,
  type DutyStatus,
  type LogHeader,
  type Remark,
  type RodsDay,
} from "../types/trip";

/**
 * One day's Record of Duty Status, drawn to the geometry of the paper form in
 * `docs/reference/blank-paper-log.png`.
 *
 * The hairline rules and the tick hierarchy are not decoration. Reproducing them
 * is what makes the output read as a real RODS rather than as graph paper. The
 * duty-status trace is one continuous path, a horizontal run on each row's
 * centerline plus a vertical connector at every transition, because a gap or an
 * overlap is the visual tell of an invalid log.
 */

const VIEW_WIDTH = 1100;
const VIEW_HEIGHT = 430;

const GRID_LEFT = 110; // row label gutter occupies 0 → 110
const GRID_RIGHT = 974; // 864 px for 24 h
const TOTALS_RIGHT = 1060;
const PX_PER_HOUR = (GRID_RIGHT - GRID_LEFT) / 24; // 36
const PX_PER_MINUTE = PX_PER_HOUR / 60;

const HOUR_BAND_BOTTOM = 28;
const ROW_HEIGHT = 44;
const GRID_BOTTOM = HOUR_BAND_BOTTOM + ROW_HEIGHT * 4; // 204

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

/** Top of the shipping block. The remarks strip must not reach it. */
const SHIPPING_DIVIDER_Y = VIEW_HEIGHT - 46;

const HAIRLINE = "var(--color-ink)";

/** Amber is unreadable on manila; the sheet uses the darker paper variant. */
const PAPER_STATUS_COLORS: Record<DutyStatus, string> = {
  off_duty: "var(--color-steel-ink)",
  sleeper_berth: "var(--color-berth-ink)",
  driving: "var(--color-signal-ink)",
  on_duty_not_driving: "var(--color-onduty-ink)",
};

/** Minute from midnight to an x coordinate. */
const x = (minute: number) => GRID_LEFT + minute * PX_PER_MINUTE;

/** The centerline of a status row: 50, 94, 138, 182. */
const rowCenter = (status: DutyStatus) =>
  HOUR_BAND_BOTTOM + ROW_HEIGHT * DUTY_STATUS_ORDER.indexOf(status) + ROW_HEIGHT / 2;

const rowTop = (index: number) => HOUR_BAND_BOTTOM + ROW_HEIGHT * index;

interface LogSheetProps {
  day: RodsDay;
  header: LogHeader;
  totalDays: number;
}

export default function LogSheet({ day, header, totalDays }: LogSheetProps) {
  return (
    <article
      aria-label={`Driver\u0027s daily log for ${day.date}`}
      className="break-inside-avoid rounded-sm bg-paper p-6 text-ink shadow-sm print:rounded-none print:p-4 print:shadow-none"
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
          <HourLabels />
          <GridRules />
          <QuarterHourTicks />
          <DutyTrace day={day} />
          <TotalsColumn day={day} />
          <RemarksStrip day={day} header={header} />
        </svg>
      </div>

      <Legend />
    </article>
  );
}

// --------------------------------------------------------------------------- //
// Header: the paper form's top block
// --------------------------------------------------------------------------- //

function SheetHeader({ day, header, totalDays }: LogSheetProps) {
  return (
    <header className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b-2 border-ink pb-2">
        <h3 className="font-display text-lg font-semibold tracking-tight">Driver's Daily Log</h3>
        <p className="font-data text-sm">
          {shortDate(day.date)} <span className="opacity-60">· {day.date}</span>
        </p>
        <p className="font-data text-xs opacity-70">
          Sheet {day.day_number} of {totalDays} · Original, file at home terminal
        </p>
      </div>

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

function HeaderField({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 border-b border-ink/25 pb-1">
      <dt className="text-[0.6rem] tracking-wider uppercase opacity-55">{label}</dt>
      <dd className="truncate" title={value}>
        {value}
      </dd>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// The grid
// --------------------------------------------------------------------------- //

const HOURS = Array.from({ length: 25 }, (_, hour) => hour);

function HourLabels() {
  return (
    <g fontSize="8.5" fill={HAIRLINE} textAnchor="middle">
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
    </g>
  );
}

function GridRules() {
  return (
    <g stroke={HAIRLINE} fill="none">
      {/* Row labels in the gutter. */}
      {/* "4. On Duty (not driving)" is 24 characters, 115 px at this size, which
          starts at x = -13 and is clipped by the viewBox. The reference form
          breaks it over two lines, so this does too. */}
      <g fontSize="8" fill={HAIRLINE} stroke="none" textAnchor="end">
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
      <text
        x={(GRID_RIGHT + TOTALS_RIGHT) / 2}
        y={19}
        fontSize="8"
        fill={HAIRLINE}
        stroke="none"
        textAnchor="middle"
      >
        Total Hours
      </text>
    </g>
  );
}

/**
 * The 15-, 30- and 45-minute subdivisions, rising from each row's baseline.
 * Their differing lengths make the grid readable at a glance, with half-hours
 * standing proud of the quarter-hours.
 */
function QuarterHourTicks() {
  const marks: React.ReactElement[] = [];

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
    <g stroke={HAIRLINE} strokeWidth={0.5}>
      {marks}
    </g>
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
    <g fontSize="11" fill={HAIRLINE} textAnchor="end">
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

function RemarksStrip({ day, header }: { day: RodsDay; header: LogHeader }) {
  return (
    <g>
      <text x={0} y={GRID_BOTTOM + 15} fontSize="9" fill={HAIRLINE}>
        Remarks
      </text>

      {/* The hour ticks repeat here, as they do on the paper form. */}
      <g stroke={HAIRLINE} strokeWidth={0.5}>
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
              stroke={HAIRLINE}
              strokeWidth={0.6}
            />
            <text
              x={at + 4}
              y={baseline}
              fontSize={REMARK_FONT_SIZE}
              fill={HAIRLINE}
              transform={`rotate(-60, ${at + 4}, ${baseline})`}
            >
              {label}
            </text>
          </g>
        );
      })}

      <ShippingBlock header={header} />
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

/**
 * The blocks the reference form carries below the remarks: shipping documents on
 * the left, the home-terminal time-standard instruction across the middle.
 * Without them the bottom fifth of every sheet prints as blank manila.
 */
function ShippingBlock({ header }: { header: LogHeader }) {
  return (
    <g fontSize="8" fill={HAIRLINE}>
      <line
        x1={0}
        x2={VIEW_WIDTH}
        y1={SHIPPING_DIVIDER_Y}
        y2={SHIPPING_DIVIDER_Y}
        stroke={HAIRLINE}
        strokeWidth={0.8}
      />
      <text x={0} y={VIEW_HEIGHT - 30}>
        <tspan fill={HAIRLINE} opacity={0.6}>
          Shipping documents:{" "}
        </tspan>
        <tspan>{header.shipping_document}</tspan>
      </text>
      <text x={0} y={VIEW_HEIGHT - 16}>
        <tspan fill={HAIRLINE} opacity={0.6}>
          Shipper &amp; commodity:{" "}
        </tspan>
        <tspan>{header.shipper_commodity}</tspan>
      </text>
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

function splitRowLabel(index: number, label: string): [string, string | null] {
  const [head, tail] = label.split(" (");
  return tail ? [`${index}. ${head}`, `(${tail}`] : [`${index}. ${label}`, null];
}

function truncate(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}

function minuteAsClock(minute: number): string {
  return `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
}
