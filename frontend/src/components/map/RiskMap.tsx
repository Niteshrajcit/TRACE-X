import { useMemo, useState } from "react";
import { cellToBoundary, cellToLatLng } from "h3-js";
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

type Projector = (lat: number, lon: number) => [number, number];

interface Projected {
  cell: string;
  score: number;
  normalized: number;
  points: string;
  centroid: [number, number];
}

const VIEW_W = 900;
const VIEW_H = 620;
const PAD = 0.14;

function riskColor(n: number): string {
  // continuous low -> medium -> high -> critical ramp, not four flat buckets
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
  const ar = (pa >> 16) & 255,
    ag = (pa >> 8) & 255,
    ab = pa & 255;
  const br = (pb >> 16) & 255,
    bg = (pb >> 8) & 255,
    bb = pb & 255;
  const r = Math.round(ar + (br - ar) * t);
  const g = Math.round(ag + (bg - ag) * t);
  const bl = Math.round(ab + (bb - ab) * t);
  return `#${[r, g, bl].map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

const MARKER_META: Record<MapMarker["kind"], { color: string; label: string }> = {
  victim: { color: "var(--text-0)", label: "Victim" },
  exit_channel: { color: "var(--decision)", label: "Candidate exit" },
  ring: { color: "var(--accent)", label: "Ring member cluster" },
  team: { color: "var(--ok)", label: "Response team" },
};

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
  const [hovered, setHovered] = useState<Projected | null>(null);

  const { projected, project } = useMemo(() => {
    const allLatLon: [number, number][] = [];
    const boundaries = cells.map((c) => {
      const boundary = cellToBoundary(c.h3_cell, false) as [number, number][];
      boundary.forEach((p) => allLatLon.push(p));
      const [clat, clon] = cellToLatLng(c.h3_cell);
      return { cell: c.h3_cell, score: c.score, boundary, centroid: [clat, clon] as [number, number] };
    });
    markers.forEach((m) => allLatLon.push([m.lat, m.lon]));
    if (corridor) {
      const kmToDeg = corridor.distanceKm[1] / 111;
      const rad = ((corridor.bearingDeg - 90) * Math.PI) / 180;
      allLatLon.push([corridor.fromLat + kmToDeg * Math.sin(-rad), corridor.fromLon + kmToDeg * Math.cos(rad)]);
      allLatLon.push([corridor.fromLat, corridor.fromLon]);
    }

    if (allLatLon.length === 0) {
      return { projected: [] as Projected[], project: null as Projector | null };
    }

    let minLat = Math.min(...allLatLon.map((p) => p[0]));
    let maxLat = Math.max(...allLatLon.map((p) => p[0]));
    let minLon = Math.min(...allLatLon.map((p) => p[1]));
    let maxLon = Math.max(...allLatLon.map((p) => p[1]));
    const latPad = (maxLat - minLat) * PAD || 0.01;
    const lonPad = (maxLon - minLon) * PAD || 0.01;
    minLat -= latPad;
    maxLat += latPad;
    minLon -= lonPad;
    maxLon += lonPad;

    const avgLat = (minLat + maxLat) / 2;
    const lonScale = Math.cos((avgLat * Math.PI) / 180);
    const latSpan = maxLat - minLat;
    const lonSpan = (maxLon - minLon) * lonScale;
    const scale = Math.min(VIEW_W / (lonSpan || 1), VIEW_H / (latSpan || 1));
    const usedW = lonSpan * scale;
    const usedH = latSpan * scale;
    const offX = (VIEW_W - usedW) / 2;
    const offY = (VIEW_H - usedH) / 2;

    const proj = (lat: number, lon: number): [number, number] => {
      const x = offX + (lon - minLon) * lonScale * scale;
      const y = offY + (maxLat - lat) * scale;
      return [x, y];
    };

    const scores = cells.map((c) => c.score);
    const min = Math.min(...scores, 0);
    const max = Math.max(...scores, 1);
    const range = max - min || 1;

    const proj2: Projected[] = boundaries.map((b) => ({
      cell: b.cell,
      score: b.score,
      normalized: (b.score - min) / range,
      points: b.boundary.map(([lat, lon]) => proj(lat, lon).join(",")).join(" "),
      centroid: proj(b.centroid[0], b.centroid[1]),
    }));

    return { projected: proj2, project: proj as Projector | null };
  }, [cells, markers, corridor]);

  if (!project) {
    return null;
  }

  const hottest = [...projected].sort((a, b) => b.normalized - a.normalized).slice(0, 3);
  const hottestIds = new Set(hottest.map((h) => h.cell));

  const corridorLine = corridor
    ? (() => {
        const from = project(corridor.fromLat, corridor.fromLon);
        const kmToDeg = corridor.distanceKm[1] / 111;
        const rad = ((corridor.bearingDeg - 90) * Math.PI) / 180;
        const to = project(corridor.fromLat + kmToDeg * Math.sin(-rad), corridor.fromLon + kmToDeg * Math.cos(rad));
        const coneA = ((corridor.bearingDeg - corridor.coneDeg / 2 - 90) * Math.PI) / 180;
        const coneB = ((corridor.bearingDeg + corridor.coneDeg / 2 - 90) * Math.PI) / 180;
        const distPx = Math.hypot(to[0] - from[0], to[1] - from[1]);
        const p1: [number, number] = [from[0] + distPx * Math.cos(coneA), from[1] + distPx * Math.sin(coneA)];
        const p2: [number, number] = [from[0] + distPx * Math.cos(coneB), from[1] + distPx * Math.sin(coneB)];
        return { from, to, p1, p2 };
      })()
    : null;

  return (
    <div style={{ position: "relative", width: "100%", height }}>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        width="100%"
        height="100%"
        style={{ display: "block", background: "var(--bg-0)", borderRadius: "var(--radius)" }}
        onMouseLeave={() => setHovered(null)}
      >
        <defs>
          <pattern id="riskgrid" width="60" height="60" patternUnits="userSpaceOnUse">
            <path d="M 60 0 L 0 0 0 60" fill="none" stroke="var(--border-subtle)" strokeWidth="0.5" />
          </pattern>
          <radialGradient id="mapVignette" cx="50%" cy="38%" r="75%">
            <stop offset="0%" stopColor="var(--bg-2)" />
            <stop offset="100%" stopColor="var(--bg-0)" />
          </radialGradient>
          <radialGradient id="hotspotGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#f4574f" stopOpacity="0.55" />
            <stop offset="100%" stopColor="#f4574f" stopOpacity="0" />
          </radialGradient>
        </defs>
        {/* Depth vignette first, then a faint reference grid on top - the
            field itself should read as an intelligence surface with depth,
            not flat graph paper with colored polygons on it. */}
        <rect width={VIEW_W} height={VIEW_H} fill="url(#mapVignette)" />
        <rect width={VIEW_W} height={VIEW_H} fill="url(#riskgrid)" opacity={0.5} />

        {corridorLine && (
          <g>
            <path
              d={`M${corridorLine.from[0]},${corridorLine.from[1]} L${corridorLine.p1[0]},${corridorLine.p1[1]} L${corridorLine.p2[0]},${corridorLine.p2[1]} Z`}
              fill="var(--decision)"
              opacity={0.12}
            />
            <line
              x1={corridorLine.from[0]}
              y1={corridorLine.from[1]}
              x2={corridorLine.to[0]}
              y2={corridorLine.to[1]}
              stroke="var(--decision)"
              strokeWidth={2}
              strokeDasharray="6 5"
              opacity={0.85}
            />
          </g>
        )}

        {projected.map((p) => {
          const isHot = hottestIds.has(p.cell);
          const isSelected = selectedCell === p.cell;
          return (
            <g key={p.cell}>
              {isHot && <circle cx={p.centroid[0]} cy={p.centroid[1]} r={34} fill="url(#hotspotGlow)" className="hex-pulse" />}
              <polygon
                points={p.points}
                fill={riskColor(p.normalized)}
                fillOpacity={isSelected ? 0.85 : 0.42 + p.normalized * 0.28}
                stroke={isSelected ? "var(--text-0)" : riskColor(p.normalized)}
                strokeWidth={isSelected ? 2 : 0.75}
                strokeOpacity={isSelected ? 1 : 0.6}
                style={{ cursor: onSelectCell ? "pointer" : "default", transition: "fill-opacity 0.4s ease" }}
                onMouseEnter={() => setHovered(p)}
                onClick={() => onSelectCell?.(isSelected ? null : p.cell)}
              />
            </g>
          );
        })}

        {markers.map((m) => {
          const [x, y] = project(m.lat, m.lon);
          const meta = MARKER_META[m.kind];
          return (
            <g
              key={m.id}
              transform={`translate(${x},${y})`}
              style={{ cursor: m.onClick ? "pointer" : "default" }}
              onClick={m.onClick}
              onMouseEnter={() => m.onHoverChange?.(true)}
              onMouseLeave={() => m.onHoverChange?.(false)}
            >
              {/* Invisible, larger hit-area - the visible marker (r=6/8) is
                  too small a touch target on its own; this keeps the visual
                  size unchanged while giving touch/tablet users something
                  reasonable to tap (readiness report §10.1). */}
              {m.onClick && <circle r={16} fill="transparent" />}
              {m.highlighted && (
                <circle r={11} fill="none" stroke={meta.color} strokeWidth={1.5} strokeDasharray="2 3" className="hex-pulse" />
              )}
              <circle r={m.highlighted ? 8 : 6} fill="var(--bg-0)" stroke={meta.color} strokeWidth={m.highlighted ? 3 : 2} />
              <circle r={2} fill={meta.color} />
              {m.rank !== undefined && (
                <text
                  y={-13}
                  textAnchor="middle"
                  fontSize={m.highlighted ? 11.5 : 10}
                  fontFamily="var(--font-mono)"
                  fill={meta.color}
                  fontWeight={700}
                >
                  #{m.rank}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {hovered && (
        <div
          className="panel"
          style={{
            position: "absolute",
            left: 12,
            bottom: 12,
            padding: "10px 12px",
            pointerEvents: "none",
            minWidth: 180,
          }}
        >
          <div className="row between" style={{ marginBottom: 4 }}>
            <span className="mono dim" style={{ fontSize: "0.68rem" }}>
              {hovered.cell}
            </span>
          </div>
          <div className="row between">
            <span className="muted" style={{ fontSize: "0.75rem" }}>
              Risk score
            </span>
            <span className="tabular" style={{ fontWeight: 700, color: riskColor(hovered.normalized) }}>
              {hovered.score.toFixed(3)}
            </span>
          </div>
        </div>
      )}

      <div className="row" style={{ position: "absolute", right: 12, top: 12, gap: 6 }}>
        {markers.length > 0 &&
          Array.from(new Set(markers.map((m) => m.kind))).map((kind) => (
            <span key={kind} className="pill pill-neutral" style={{ background: "var(--bg-1)" }}>
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
          border: "1px solid var(--border-subtle)",
          borderRadius: 999,
          padding: "5px 12px",
          fontSize: "0.68rem",
        }}
      >
        <span className="muted">Risk</span>
        <span style={{ width: 90, height: 6, borderRadius: 999, background: "linear-gradient(90deg,#34d399,#fbbf24,#fb923c,#f4574f)" }} />
      </div>
    </div>
  );
}
