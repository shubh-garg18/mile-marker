import { clockTime, shortDate, miles } from "../format";
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
 *
 * Multi-day trips group the rail under day headers whose numbers match the log
 * sheets — "Day 2" here is "Sheet 2" below — and the break in the rail at each
 * header is the night. With the date carried by the header, the entries
 * themselves list only clock times.
 */
export default function StopItinerary({ stops, originLabel, departure }: StopItineraryProps) {
  const entries: EntryProps[] = [
    {
      iso: departure,
      mileage: "0",
      time: clockTime(departure),
      color: "var(--color-steel)",
      title: "Departure",
      location: originLabel,
      detail: "On duty; trip begins",
    },
    ...stops.map((stop) => ({
      iso: stop.arrive,
      mileage: miles(stop.at_mile),
      time: clockTime(stop.arrive),
      color: DUTY_STATUS_COLORS[stop.duty_status],
      title: STOP_LABELS[stop.type],
      location: stop.label,
      detail: `${stop.reason} · ${formatDuration(stop.duration_hours)}`,
      departsAt: stop.duration_hours >= 1 ? clockTime(stop.depart) : undefined,
    })),
  ];

  const days = groupByDay(entries, departure);

  return (
    <section aria-label="Stops" className="flex flex-col gap-3">
      <h2 className="font-display text-xs tracking-widest text-steel uppercase">
        Itinerary · {stops.length} stops
      </h2>

      {days.map((day) => (
        <div key={day.date}>
          {days.length > 1 ? (
            <h3 className="flex items-baseline gap-2 pt-1 pb-1.5">
              <span className="font-display text-[0.625rem] tracking-widest text-steel uppercase">
                Day {day.dayNumber}
              </span>
              <span aria-hidden className="h-px flex-1 bg-hairline/60" />
              <span className="font-data text-[0.65rem] text-steel">{shortDate(day.date)}</span>
            </h3>
          ) : null}

          <ol className="relative flex flex-col">
            {/* The rail itself, behind the markers. */}
            <span
              aria-hidden
              className="absolute top-2 bottom-2 left-[4.8125rem] w-px bg-hairline"
            />
            {day.entries.map((entry) => (
              <Entry key={`${entry.iso}-${entry.title}`} {...entry} />
            ))}
          </ol>
        </div>
      ))}
    </section>
  );
}

interface EntryProps {
  iso: string;
  mileage: string;
  time: string;
  color: string;
  title: string;
  location: string;
  detail: string;
  departsAt?: string;
}

interface DayGroup {
  date: string;
  dayNumber: number;
  entries: EntryProps[];
}

/**
 * Sequential grouping by calendar date. Day numbers count from the trip's start
 * date rather than from the groups themselves, so a day spent entirely inside a
 * 34-hour restart — which produces a sheet but no stop — still leaves "Day 4"
 * agreeing with "Sheet 4".
 */
function groupByDay(entries: EntryProps[], departure: string): DayGroup[] {
  const groups: DayGroup[] = [];
  for (const entry of entries) {
    const date = entry.iso.slice(0, 10);
    const last = groups[groups.length - 1];
    if (last && last.date === date) {
      last.entries.push(entry);
    } else {
      groups.push({ date, dayNumber: dayNumber(date, departure), entries: [entry] });
    }
  }
  return groups;
}

function dayNumber(date: string, departure: string): number {
  const asUtc = (iso: string) =>
    Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10)));
  return Math.round((asUtc(date) - asUtc(departure)) / 86_400_000) + 1;
}

function Entry({ mileage, time, color, title, location, detail, departsAt }: EntryProps) {
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
        <p className="font-display text-sm font-medium text-bright">{title}</p>
        <p className="truncate text-sm text-steel">{location}</p>
        <p className="font-data text-xs text-steel">{detail}</p>
      </div>

      <span className="shrink-0 text-right font-data text-xs tabular-nums">
        <span className="block text-bright">{time}</span>
        {departsAt ? <span className="block text-steel">→ {departsAt}</span> : null}
      </span>
    </li>
  );
}

function formatDuration(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)} min`;
  return Number.isInteger(hours) ? `${hours} h` : `${hours.toFixed(2).replace(/0$/, "")} h`;
}
