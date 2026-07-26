import { clockTime, decimalHours, miles, shortDate } from "../format";
import type { TripTotals } from "../types/trip";

interface TripSummaryProps {
  trip: TripTotals;
  warnings: string[];
}

export default function TripSummary({ trip, warnings }: TripSummaryProps) {
  // Derived from the payload rather than hard-coding 70. Every number the
  // simulation depends on lives in the backend's constants module.
  const cycleLimit = trip.cycle_used_end_hours + trip.cycle_remaining_hours;
  const cycleFraction = cycleLimit > 0 ? Math.min(trip.cycle_used_end_hours / cycleLimit, 1) : 0;
  const nearlyOutOfHours = trip.cycle_remaining_hours < 8;

  return (
    <section aria-label="Trip summary" className="flex flex-col gap-4">
      <h2 className="font-display text-xs tracking-widest text-steel uppercase">Trip</h2>

      <dl className="flex flex-col gap-2">
        <Row label="Distance" value={`${miles(trip.total_distance_miles)} mi`} />
        <Row label="Driving" value={decimalHours(trip.total_driving_hours)} />
        <Row label="On duty" value={decimalHours(trip.total_on_duty_hours)} />
        <Row label="Log sheets" value={String(trip.days_count)} />
        <Row
          label="Departs"
          value={`${shortDate(trip.start_datetime)} ${clockTime(trip.start_datetime)}`}
        />
        <Row
          label="Arrives"
          value={`${shortDate(trip.end_datetime)} ${clockTime(trip.end_datetime)}`}
        />
      </dl>

      <div className="flex flex-col gap-2 border-t border-hairline pt-4">
        <div className="flex items-baseline justify-between">
          <span className="font-display text-xs tracking-widest text-steel uppercase">
            70-hour cycle
          </span>
          <span className="font-data text-sm text-white">
            {decimalHours(trip.cycle_used_end_hours)}
            <span className="text-steel"> / {cycleLimit}</span>
          </span>
        </div>

        <div
          className="h-1.5 w-full overflow-hidden rounded-full bg-console"
          role="meter"
          aria-valuenow={trip.cycle_used_end_hours}
          aria-valuemin={0}
          aria-valuemax={cycleLimit}
          aria-label="Cycle hours used at the end of the trip"
        >
          <div
            className={nearlyOutOfHours ? "h-full bg-flag" : "h-full bg-signal"}
            style={{ width: `${cycleFraction * 100}%` }}
          />
        </div>

        <p className="font-data text-xs text-steel">
          {decimalHours(trip.cycle_remaining_hours)} remaining on arrival
        </p>
      </div>

      <p className="text-xs leading-relaxed text-steel">
        All times are {trip.timezone} home-terminal time, as §395.8 requires, even where the
        route crosses a time zone.
      </p>

      {warnings.length > 0 ? (
        <ul className="flex flex-col gap-1.5 border-t border-hairline pt-4">
          {warnings.map((warning) => (
            <li key={warning} className="text-xs leading-relaxed text-signal">
              {warning}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-sm text-steel">{label}</dt>
      <dd className="font-data text-sm text-white tabular-nums">{value}</dd>
    </div>
  );
}
