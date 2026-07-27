import L from "leaflet";
import { useEffect, useMemo } from "react";
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from "react-leaflet";

import "leaflet/dist/leaflet.css";

import { clockTime, miles, shortDate } from "../format";
import {
  DUTY_STATUS_COLORS,
  STOP_LABELS,
  type LatLng,
  type Route,
  type Stop,
  type StopType,
  type Waypoint,
} from "../types/trip";

interface RouteMapProps {
  route: Route;
  stops: Stop[];
  waypoints: Waypoint[];
}

/** Single-character glyphs, so a marker stays legible at map scale. */
const STOP_GLYPHS: Record<StopType, string> = {
  pickup: "P",
  dropoff: "D",
  fuel: "F",
  break: "B",
  rest: "R",
  restart: "34",
};

/** Hoisted so Leaflet sees a stable identity and does not redraw the line. */
const ROUTE_LINE = { color: "var(--color-signal)", weight: 4, opacity: 0.9 } as const;

/** Icons are cached by appearance. react-leaflet calls setIcon whenever the prop
 *  identity changes, which rebuilds the marker element and drops any open popup.
 *  A fresh divIcon per render made that happen on every parent update. */
const ICON_CACHE = new Map<string, L.DivIcon>();

function icon(color: string, glyph: string): L.DivIcon {
  const key = `${color}|${glyph}`;
  const cached = ICON_CACHE.get(key);
  if (cached) return cached;
  const built = buildIcon(color, glyph);
  ICON_CACHE.set(key, built);
  return built;
}

export default function RouteMap({ route, stops, waypoints }: RouteMapProps) {
  const [minLat, minLon, maxLat, maxLon] = route.bbox;
  const bounds = useMemo<[LatLng, LatLng]>(
    () => [
      [minLat, minLon],
      [maxLat, maxLon],
    ],
    [minLat, minLon, maxLat, maxLon],
  );

  const origin = waypoints.find((point) => point.role === "current");

  return (
    <div role="region" aria-label="Route map with required stops" className="flex flex-col gap-2.5">
      <MapContainer
        bounds={bounds}
        scrollWheelZoom={false}
        className="h-[26rem] w-full rounded-sm border border-hairline bg-console-2"
      >
        <FitToRoute bounds={bounds} />

        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          maxZoom={19}
        />

        <Polyline positions={route.geometry} pathOptions={ROUTE_LINE} />

        {origin ? (
          <Marker position={origin.coord} icon={icon(DUTY_STATUS_COLORS.off_duty, "S")}>
            <Popup>
              <MarkerBody title="Start" location={origin.label} detail={origin.resolved_name} />
            </Popup>
          </Marker>
        ) : null}

        {stops.map((stop) => (
          <Marker
            key={stop.seq}
            position={stop.coord}
            icon={icon(DUTY_STATUS_COLORS[stop.duty_status], STOP_GLYPHS[stop.type])}
          >
            <Popup>
              <MarkerBody
                title={`${stop.seq}. ${STOP_LABELS[stop.type]}`}
                location={stop.label}
                detail={`${shortDate(stop.arrive)} ${clockTime(stop.arrive)}–${clockTime(
                  stop.depart,
                )} · mile ${miles(stop.at_mile)}`}
              />
            </Popup>
          </Marker>
        ))}
      </MapContainer>

      <MapLegend stops={stops} hasOrigin={origin !== undefined} />
    </div>
  );
}

/**
 * A key for the marker glyphs, listing only what this trip actually contains.
 * The markers are single characters so they stay legible at map scale, which
 * leaves "R" and "34" meaningless without one. A fixed legend would advertise
 * stop types most trips never produce.
 */
function MapLegend({ stops, hasOrigin }: { stops: Stop[]; hasOrigin: boolean }) {
  const seen = new Map<StopType, Stop>();
  for (const stop of stops) if (!seen.has(stop.type)) seen.set(stop.type, stop);

  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-2">
      {hasOrigin ? (
        <LegendItem glyph="S" color={DUTY_STATUS_COLORS.off_duty} label="Start" />
      ) : null}
      {[...seen.values()].map((stop) => (
        <LegendItem
          key={stop.type}
          glyph={STOP_GLYPHS[stop.type]}
          color={DUTY_STATUS_COLORS[stop.duty_status]}
          label={STOP_LABELS[stop.type]}
        />
      ))}
    </ul>
  );
}

function LegendItem({ glyph, color, label }: { glyph: string; color: string; label: string }) {
  return (
    <li className="flex items-center gap-1.5">
      <span
        aria-hidden="true"
        className="flex h-4 w-4 items-center justify-center rounded-full font-data text-[0.5rem] font-semibold text-console"
        style={{ background: color }}
      >
        {glyph}
      </span>
      <span className="text-xs text-steel">{label}</span>
    </li>
  );
}

/** Leaflet needs an imperative nudge when a new plan arrives under the same map. */
function FitToRoute({ bounds }: { bounds: [LatLng, LatLng] }) {
  const map = useMap();

  useEffect(() => {
    map.fitBounds(bounds, { padding: [32, 32] });
  }, [map, bounds]);

  return null;
}

/**
 * A `divIcon` rather than the default marker image. It sidesteps the bundler
 * problem with Leaflet's icon URLs and lets each stop type carry its own
 * duty-status colour.
 */
function buildIcon(color: string, glyph: string): L.DivIcon {
  return L.divIcon({
    className: "",
    iconSize: [24, 24],
    iconAnchor: [12, 12],
    popupAnchor: [0, -14],
    html: `<span style="
      display:flex; align-items:center; justify-content:center;
      width:24px; height:24px; border-radius:50%;
      background:${color}; color:var(--color-console);
      border:2px solid var(--color-console); box-shadow:0 0 0 1px ${color};
      font:600 ${glyph.length > 1 ? 9 : 11}px 'IBM Plex Mono', ui-monospace, monospace;
    ">${glyph}</span>`,
  });
}

function MarkerBody({
  title,
  location,
  detail,
}: {
  title: string;
  location: string;
  detail: string;
}) {
  return (
    <span className="block font-body text-ink">
      <strong className="block text-sm">{title}</strong>
      <span className="block text-sm">{location}</span>
      <span className="block font-data text-xs opacity-70">{detail}</span>
    </span>
  );
}
