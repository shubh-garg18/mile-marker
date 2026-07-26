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
    <div role="region" aria-label="Route map with required stops" className="contents">
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

      <Polyline
        positions={route.geometry}
        pathOptions={ROUTE_LINE}
      />

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
    </div>
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
