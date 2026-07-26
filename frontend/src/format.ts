/**
 * Display formatting.
 *
 * Times, mileage and hour totals render in the mono data face, so they are
 * formatted to fixed widths here rather than left to the browser's defaults.
 * Columns of numbers that line up are what make the interface read as
 * instrumentation.
 */

/** `"14:30"` from an ISO datetime. Home-terminal time; never converted. */
export function clockTime(isoDatetime: string): string {
  return isoDatetime.slice(11, 16);
}

/** `"Mon 27 Jul"` from an ISO date or datetime. */
export function shortDate(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
  });
}

/** `"11:45"` from a decimal hour count, the notation the paper form uses. */
export function hoursAsClock(hours: number): string {
  const totalMinutes = Math.round(hours * 60);
  const whole = Math.floor(totalMinutes / 60);
  return `${whole}:${String(totalMinutes % 60).padStart(2, "0")}`;
}

/** `"1,123"`: thousands separated, no decimals. */
export function miles(value: number): string {
  return Math.round(value).toLocaleString("en-US");
}

/** `"18.75 h"`, for figures the reader will compare against a regulatory limit. */
export function decimalHours(hours: number): string {
  return `${hoursAsClock(hours)} h`;
}
