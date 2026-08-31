import { useEffect, useMemo } from "react";
import { cellToBoundary } from "h3-js";
import { MapContainer, TileLayer, Polygon, Polyline, useMap, Tooltip, Marker } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { RiskFieldCell } from "../../types/domain";

export interface MapMarker {
  id: string;
  lat: number;
  lon: number;
  kind: "victim" | "exit_channel" | "ring" | "team";
  label: string;
  rank?: number;
  highlighted?: boolean;
  onClick?: () => void;
  onHoverChange?: (hovering: boolean) => void;
}

function riskColor(n: number): string {
  const stops: [number, string][] = [
    [0, "#34d399"],
    [0.35, "#fbbf24"],
    [0.65, "#fb923c"],
    [1, "#f4574f"],
  ];
  for (let i = 0; i < stops.length - 1; i++) {
    const [p0, c0] = stops[i];
    const [p1, c1] = stops[i + 1];
    if (n >= p0 && n <= p1) {
      const t = (n - p0) / (p1 - p0 || 1);
      return mixHex(c0, c1, t);
    }
  }
  return stops[stops.length - 1][1];
}

function mixHex(a: string, b: string, t: number): string {
  const pa = parseInt(a.slice(1), 16);
  const pb = parseInt(b.slice(1), 16);
  const ar = (pa >> 16) & 255, ag = (pa >> 8) & 255, ab = pa & 255;
  const br = (pb >> 16) & 255, bg = (pb >> 8) & 255, bb = pb & 255;
  const r = Math.round(ar + (br - ar) * t);
  const g = Math.round(ag + (bg - ag) * t);
  const bl = Math.round(ab + (bb - ab) * t);
  return `#${[r, g, bl].map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

const MARKER_META: Record<MapMarker["kind"], { color: string; label: string }> = {
  victim: { color: "var(--text-0)", label: "Victim Origin" },
  exit_channel: { color: "var(--decision)", label: "TARGET LOCATION" },
  ring: { color: "var(--accent)", label: "Ring member cluster" },
  team: { color: "var(--ok)", label: "Response team" },
};

const createTacticalIcon = (color: string, highlighted: boolean) => L.divIcon({
  html: `<div style="width: ${highlighted ? 24 : 16}px; height: ${highlighted ? 24 : 16}px; border: 2px solid ${color}; border-radius: 50%; position: relative; background: rgba(0,0,0,0.4); box-shadow: 0 0 8px ${color};">
           <div style="position: absolute; top: 50%; left: -6px; width: ${highlighted ? 36 : 28}px; height: 1px; background: ${color};"></div>
           <div style="position: absolute; left: 50%; top: -6px; width: 1px; height: ${highlighted ? 36 : 28}px; background: ${color};"></div>
           <div style="position: absolute; top: 50%; left: 50%; width: 4px; height: 4px; background: ${color}; transform: translate(-50%, -50%); border-radius: 50%;"></div>
         </div>`,
  className: "tactical-crosshair",
  iconSize: [highlighted ? 24 : 16, highlighted ? 24 : 16],
  iconAnchor: [highlighted ? 12 : 8, highlighted ? 12 : 8]
});

function MapBoundsController({
  cells,
  markers,
  corridor
}: {
  cells: RiskFieldCell[];
  markers: MapMarker[];
  corridor: any;
}) {
  const map = useMap();

  useEffect(() => {
    const bounds = L.latLngBounds([]);
    
    cells.forEach((c) => {
      const boundary = cellToBoundary(c.h3_cell, false) as [number, number][];
      boundary.forEach((p) => bounds.extend(p));
    });
    
    markers.forEach((m) => bounds.extend([m.lat, m.lon]));
    
    if (corridor) {
      const kmToDeg = corridor.distanceKm[1] / 111;
      const rad = ((corridor.bearingDeg - 90) * Math.PI) / 180;
      bounds.extend([corridor.fromLat + kmToDeg * Math.sin(-rad), corridor.fromLon + kmToDeg * Math.cos(rad)]);
      bounds.extend([corridor.fromLat, corridor.fromLon]);
    }

    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [40, 40], animate: false });
    }
  }, [map, cells, markers, corridor]);

  return null;
}

export function RiskMap({
  cells,
  markers = [],
  selectedCell,
  onSelectCell,
  corridor,
  height = 460,
}: {
  cells: RiskFieldCell[];
  markers?: MapMarker[];
  selectedCell?: string | null;
  onSelectCell?: (cell: string | null) => void;
  corridor?: { fromLat: number; fromLon: number; bearingDeg: number; distanceKm: [number, number]; coneDeg: number } | null;
  height?: number;
}) {
  
  const { normalizedCells } = useMemo(() => {
    const scores = cells.map((c) => c.score);
    const min = Math.min(...scores, 0);
    const max = Math.max(...scores, 1);
    const range = max - min || 1;
    
    const normalized = cells.map(c => {
      const boundary = cellToBoundary(c.h3_cell, false) as [number, number][];
      const norm = (c.score - min) / range;
      return { ...c, boundary, normalized: norm };
    });
    
    return { normalizedCells: normalized, minScore: min, maxScore: max };
  }, [cells]);

  const hottest = [...normalizedCells].sort((a, b) => b.normalized - a.normalized).slice(0, 3);
  const hottestIds = new Set(hottest.map((h) => h.h3_cell));

  const corridorElements = useMemo(() => {
    if (!corridor) return null;
    const from: [number, number] = [corridor.fromLat, corridor.fromLon];
    const kmToDeg = corridor.distanceKm[1] / 111;
    const rad = ((corridor.bearingDeg - 90) * Math.PI) / 180;
    const to: [number, number] = [corridor.fromLat + kmToDeg * Math.sin(-rad), corridor.fromLon + kmToDeg * Math.cos(rad)];
    
    const coneA = ((corridor.bearingDeg - corridor.coneDeg / 2 - 90) * Math.PI) / 180;
    const coneB = ((corridor.bearingDeg + corridor.coneDeg / 2 - 90) * Math.PI) / 180;
    const distPx = kmToDeg; // approximate using same distance
    const p1: [number, number] = [corridor.fromLat + distPx * Math.sin(-coneA), corridor.fromLon + distPx * Math.cos(coneA)];
    const p2: [number, number] = [corridor.fromLat + distPx * Math.sin(-coneB), corridor.fromLon + distPx * Math.cos(coneB)];

    return { from, to, conePolygon: [from, p1, p2] as [number, number][] };
  }, [corridor]);

  return (
    <div style={{ position: "relative", width: "100%", height, borderRadius: "var(--radius)", overflow: "hidden" }}>
      <MapContainer 
        center={[20, 0]} 
        zoom={2} 
        style={{ width: "100%", height: "100%", background: "#191a1a", zIndex: 1 }}
        zoomControl={false}
        attributionControl={false}
      >
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          className="osm-dark-map"
        />
        
        <MapBoundsController cells={cells} markers={markers} corridor={corridor} />

        {corridorElements && (
          <>
            <Polygon 
              positions={corridorElements.conePolygon}
              color="var(--decision)"
              fillOpacity={0.12}
              weight={0}
            />
            <Polyline
              positions={[corridorElements.from, corridorElements.to]}
              color="var(--decision)"
              weight={2}
              dashArray="6, 5"
              opacity={0.85}
            />
          </>
        )}

        {normalizedCells.map((c) => {
          const isHot = hottestIds.has(c.h3_cell);
          const isSelected = selectedCell === c.h3_cell;
          const color = riskColor(c.normalized);
          
          return (
            <Polygon
              key={c.h3_cell}
              positions={c.boundary}
              fillColor={color}
              fillOpacity={isSelected ? 0.85 : 0.42 + c.normalized * 0.28}
              color={isSelected ? "var(--text-0)" : color}
              weight={isSelected ? 2 : (isHot ? 1.5 : 0.75)}
              opacity={isSelected ? 1 : (isHot ? 0.8 : 0.6)}
              eventHandlers={{
                click: () => onSelectCell?.(isSelected ? null : c.h3_cell)
              }}
            >
              <Tooltip sticky>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.8rem", color: "var(--text-0)" }}>
                  <div><strong>{c.h3_cell}</strong></div>
                  <div>Risk: {c.score.toFixed(3)}</div>
                </div>
              </Tooltip>
            </Polygon>
          );
        })}

        {markers.map((m) => {
          const meta = MARKER_META[m.kind];
          return (
            <Marker
              key={m.id}
              position={[m.lat, m.lon]}
              icon={createTacticalIcon(meta.color, !!m.highlighted)}
              eventHandlers={{
                click: () => m.onClick?.(),
                mouseover: () => m.onHoverChange?.(true),
                mouseout: () => m.onHoverChange?.(false)
              }}
            >
              <Tooltip direction="top" offset={[0, -15]} opacity={1}>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.8rem", color: "var(--text-0)", fontWeight: "bold" }}>
                  <div>{meta.label} {m.rank ? `(#${m.rank})` : ""}</div>
                  <div style={{ fontSize: "0.65rem", color: "var(--accent)", marginTop: 4 }}>
                    LAT: {m.lat.toFixed(4)}° N<br/>
                    LON: {m.lon.toFixed(4)}° E
                  </div>
                </div>
              </Tooltip>
            </Marker>
          );
        })}
      </MapContainer>

      <div className="row" style={{ position: "absolute", right: 12, top: 12, gap: 6, zIndex: 1000, pointerEvents: "none" }}>
        {markers.length > 0 &&
          Array.from(new Set(markers.map((m) => m.kind))).map((kind) => (
            <span key={kind} className="pill pill-neutral" style={{ background: "var(--bg-1)", border: "1px solid rgba(255,255,255,0.1)", boxShadow: "0 2px 4px rgba(0,0,0,0.5)" }}>
              <span className="dot" style={{ background: MARKER_META[kind].color }} />
              {MARKER_META[kind].label}
            </span>
          ))}
      </div>

      <div
        className="row"
        style={{
          position: "absolute",
          left: 12,
          top: 12,
          gap: 10,
          background: "var(--bg-1)",
          border: "1px solid rgba(255,255,255,0.1)",
          borderRadius: 999,
          padding: "5px 12px",
          fontSize: "0.68rem",
          zIndex: 1000,
          boxShadow: "0 2px 4px rgba(0,0,0,0.5)",
          pointerEvents: "none"
        }}
      >
        <span className="muted">Risk</span>
        <span style={{ width: 90, height: 6, borderRadius: 999, background: "linear-gradient(90deg,#34d399,#fbbf24,#fb923c,#f4574f)" }} />
      </div>
    </div>
  );
}
