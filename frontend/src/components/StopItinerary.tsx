import { clockTime, miles, shortDate } from "../format";
import { DUTY_STATUS_COLORS, STOP_LABELS, type Stop } from "../types/trip";

interface StopItineraryProps {
  stops: Stop[];
  originLabel: string;
  departure: string;
}

/**
 * A vertical mile-marker rail: cumulative mileage on the left of each stop, clock
 * time on the right. The stops are an ordered sequence and the order is
 * information the reader needs, so they are numbered.
 */
export default function StopItinerary({ stops, originLabel, departure }: StopItineraryProps) {
  return (
    <section aria-label="Stops" className="flex flex-col gap-4">
      <h2 className="font-display text-xs tracking-widest text-steel uppercase">
        Itinerary · {stops.length} stops
      </h2>

      <ol className="relative flex flex-col">
        {/* The rail itself, behind the markers. */}
        <span aria-hidden className="absolute top-2 bottom-2 left-[4.8125rem] w-px bg-hairline" />

        <Entry
          mileage="0"
          time={clockTime(departure)}
          date={shortDate(departure)}
          color="var(--color-steel)"
          title="Departure"
          location={originLabel}
          detail="On duty; trip begins"
        />

        {stops.map((stop) => (
          <Entry
            key={stop.seq}
            mileage={miles(stop.at_mile)}
            time={clockTime(stop.arrive)}
            date={shortDate(stop.arrive)}
            color={DUTY_STATUS_COLORS[stop.duty_status]}
            title={STOP_LABELS[stop.type]}
            location={stop.label}
            detail={`${stop.reason} · ${formatDuration(stop.duration_hours)}`}
            departsAt={stop.duration_hours >= 1 ? clockTime(stop.depart) : undefined}
          />
        ))}
      </ol>
    </section>
  );
}

interface EntryProps {
  mileage: string;
  time: string;
  date: string;
  color: string;
  title: string;
  location: string;
  detail: string;
  departsAt?: string;
}

function Entry({
  mileage,
  time,
  date,
  color,
  title,
  location,
  detail,
  departsAt,
}: EntryProps) {
  return (
    <li className="relative flex items-start gap-4 py-2.5">
      <span className="w-14 shrink-0 pt-0.5 text-right font-data text-xs text-steel tabular-nums">
        {mileage}
        <span className="text-steel"> mi</span>
      </span>

      <span
        aria-hidden
        className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ring-4 ring-console-2"
        style={{ backgroundColor: color }}
      />

      <div className="min-w-0 flex-1">
        <p className="font-display text-sm font-medium text-white">{title}</p>
        <p className="truncate text-sm text-steel">{location}</p>
        <p className="font-data text-xs text-steel">{detail}</p>
      </div>

      <span className="shrink-0 text-right font-data text-xs tabular-nums">
        <span className="block text-white">{time}</span>
        {departsAt ? <span className="block text-steel">→ {departsAt}</span> : null}
        <span className="block text-steel">{date}</span>
      </span>
    </li>
  );
}

function formatDuration(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)} min`;
  return Number.isInteger(hours) ? `${hours} h` : `${hours.toFixed(2).replace(/0$/, "")} h`;
}
