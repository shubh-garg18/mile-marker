import { miles } from "../format";
import type { LogHeader, RodsDay, TripTotals } from "../types/trip";
import LogSheet from "./LogSheet";

interface LogSheetStackProps {
  days: RodsDay[];
  header: LogHeader;
  trip: TripTotals;
}

export default function LogSheetStack({ days, header, trip }: LogSheetStackProps) {
  return (
    <section aria-label="Daily log sheets" className="flex flex-col gap-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 print:hidden">
        <h2 className="font-display text-xs tracking-widest text-steel uppercase">
          Records of duty status · {days.length} {days.length === 1 ? "sheet" : "sheets"}
        </h2>
        <p className="font-data text-xs text-steel">
          {miles(trip.total_distance_miles)} mi · every sheet totals 24:00
        </p>
      </div>

      {days.map((day) => (
        <LogSheet key={day.date} day={day} header={header} totalDays={days.length} />
      ))}
    </section>
  );
}
