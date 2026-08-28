import { useMemo } from "react";
import { INDIA_BOUNDS, INDIA_OUTLINE_LATLON } from "../../lib/indiaOutline";
import { EmptyState } from "../ui/primitives";

const VIEW_W = 200;
const VIEW_H = 240;
const PAD = 16;

/**
 * Compact geographic reference inset - readiness report §5: plots only
 * this case's own real coordinate against a static India outline. Never
 * implies the outline itself is backend data, and never shows any other
 * case's location (there is no jurisdiction-list/name endpoint to draw a
 * real multi-jurisdiction map from - see FRONTEND_F3_READINESS.md §2).
 */
export function IndiaInset({ lat, lon }: { lat: number | null; lon: number | null }) {
  const { outlinePoints, marker } = useMemo(() => {
    const { minLat, maxLat, minLon, maxLon } = INDIA_BOUNDS;
    const avgLat = (minLat + maxLat) / 2;
    const lonScale = Math.cos((avgLat * Math.PI) / 180);
    const latSpan = maxLat - minLat;
    const lonSpan = (maxLon - minLon) * lonScale;
    const scale = Math.min((VIEW_W - PAD * 2) / lonSpan, (VIEW_H - PAD * 2) / latSpan);
    const usedW = lonSpan * scale;
    const usedH = latSpan * scale;
    const offX = (VIEW_W - usedW) / 2;
    const offY = (VIEW_H - usedH) / 2;

    const project = (pLat: number, pLon: number): [number, number] => [
      offX + (pLon - minLon) * lonScale * scale,
      offY + (maxLat - pLat) * scale,
    ];

    const outlinePoints = INDIA_OUTLINE_LATLON.map(([pLat, pLon]) => project(pLat, pLon));
    const marker = lat != null && lon != null ? project(lat, lon) : null;

    return { outlinePoints, marker };
  }, [lat, lon]);

  if (lat == null || lon == null) {
    return <EmptyState title="No coordinate for this case" description="This complaint has no reported location to place geographically." />;
  }

  return (
    <div className="stack" style={{ alignItems: "center", gap: 6 }}>
      <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} width="100%" style={{ maxWidth: 200, display: "block" }}>
        <polygon
          points={outlinePoints.map(([x, y]) => `${x},${y}`).join(" ")}
          fill="var(--bg-3)"
          stroke="var(--border-strong)"
          strokeWidth={1}
          strokeLinejoin="round"
        />
        {marker && (
          <g transform={`translate(${marker[0]},${marker[1]})`}>
            <circle r={9} fill="none" stroke="var(--accent)" strokeWidth={1.5} className="hex-pulse" />
            <circle r={3.5} fill="var(--accent)" stroke="var(--bg-0)" strokeWidth={1.5} />
          </g>
        )}
      </svg>
      <p className="hint" style={{ textAlign: "center", fontSize: "var(--text-xs)" }}>
        Approximate location within India — reference outline, not a backend jurisdiction boundary.
      </p>
    </div>
  );
}
