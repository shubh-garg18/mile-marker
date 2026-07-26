/**
 * Mirrors the API response contract field for field.
 *
 * If the contract changes, this file changes in the same commit. Nothing is
 * optional for convenience: a field the backend always sends is required here,
 * so a missing one is a type error rather than a blank cell.
 */

export type DutyStatus = "off_duty" | "sleeper_berth" | "driving" | "on_duty_not_driving";

export type StopType = "pickup" | "dropoff" | "fuel" | "break" | "rest" | "restart";

export type WaypointRole = "current" | "pickup" | "dropoff";

/** `[latitude, longitude]`, Leaflet's order. Converted once, server-side. */
export type LatLng = [number, number];

export interface TripTotals {
  start_datetime: string;
  end_datetime: string;
  timezone: string;
  total_distance_miles: number;
  total_driving_hours: number;
  total_on_duty_hours: number;
  days_count: number;
  cycle_used_start_hours: number;
  cycle_used_end_hours: number;
  cycle_remaining_hours: number;
}

export interface Waypoint {
  role: WaypointRole;
  label: string;
  resolved_name: string;
  coord: LatLng;
}

export interface RouteLeg {
  from: string;
  to: string;
  distance_miles: number;
  driving_hours: number;
}

export interface Route {
  geometry: LatLng[];
  /** `[min_lat, min_lon, max_lat, max_lon]` */
  bbox: [number, number, number, number];
  legs: RouteLeg[];
}

export interface Stop {
  seq: number;
  type: StopType;
  label: string;
  coord: LatLng;
  at_mile: number;
  arrive: string;
  depart: string;
  duration_hours: number;
  duty_status: DutyStatus;
  reason: string;
}

export interface RodsSegment {
  status: DutyStatus;
  /** Minutes from that day's midnight, 0 to 1440. */
  start_minute: number;
  end_minute: number;
  kind: string;
  miles: number;
}

export interface Remark {
  minute: number;
  location: string;
  note: string;
}

export type RodsTotals = Record<DutyStatus, number> & { total: number };

export interface RodsDay {
  date: string;
  day_number: number;
  driving_miles: number;
  segments: RodsSegment[];
  totals: RodsTotals;
  remarks: Remark[];
}

export interface LogHeader {
  driver_name: string;
  carrier_name: string;
  office_address: string;
  terminal_address: string;
  tractor_number: string;
  trailer_number: string;
  shipping_document: string;
  shipper_commodity: string;
}

export interface TripPlan {
  trip: TripTotals;
  waypoints: Waypoint[];
  route: Route;
  stops: Stop[];
  days: RodsDay[];
  log_header: LogHeader;
  warnings: string[];
}

export interface TripPlanRequest {
  current_location: string;
  pickup_location: string;
  dropoff_location: string;
  current_cycle_used_hours: number;
  start_datetime?: string;
}

/** The four rows of a log sheet, in the order the form prints them. */
export const DUTY_STATUS_ORDER: readonly DutyStatus[] = [
  "off_duty",
  "sleeper_berth",
  "driving",
  "on_duty_not_driving",
];

export const DUTY_STATUS_LABELS: Record<DutyStatus, string> = {
  off_duty: "Off Duty",
  sleeper_berth: "Sleeper Berth",
  driving: "Driving",
  on_duty_not_driving: "On Duty (not driving)",
};

/** Maps onto the `@theme` colour tokens in `styles/index.css`. */
export const DUTY_STATUS_COLORS: Record<DutyStatus, string> = {
  off_duty: "var(--color-steel)",
  sleeper_berth: "var(--color-berth)",
  driving: "var(--color-signal)",
  on_duty_not_driving: "var(--color-onduty)",
};

export const STOP_LABELS: Record<StopType, string> = {
  pickup: "Pickup",
  dropoff: "Dropoff",
  fuel: "Fuel",
  break: "30-min break",
  rest: "10-hour rest",
  restart: "34-hour restart",
};
