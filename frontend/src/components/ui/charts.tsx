/**
 * Small hand-rolled SVG chart primitives. Deliberately not a charting
 * library: each of these renders exactly one real, specific investigative
 * quantity (a probability, a confidence interval, a bearing, a time
 * window) with a bespoke visual treatment, which a generic chart component
 * would either not support or would make look like every other dashboard.
 */

export function ProbabilityRing({
  value,
  size = 72,
  stroke = 7,
  color = "var(--accent)",
  label,
}: {
  value: number; // 0..1
  size?: number;
  stroke?: number;
  color?: string;
  label?: string;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(1, value));
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="var(--border-subtle)"
        strokeWidth={stroke}
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - pct)}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dashoffset 0.6s ease" }}
      />
      <text
        x="50%"
        y="50%"
        textAnchor="middle"
        dominantBaseline="central"
        fontFamily="var(--font-mono)"
        fontSize={size * 0.24}
        fontWeight={700}
        fill="var(--text-0)"
      >
        {label ?? `${Math.round(pct * 100)}%`}
      </text>
    </svg>
  );
}

export function ConfidenceBar({
  value,
  color = "var(--accent)",
  height = 6,
}: {
  value: number; // 0..1
  color?: string;
  height?: number;
}) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div
      style={{
        height,
        borderRadius: 999,
        background: "var(--bg-3)",
        overflow: "hidden",
        width: "100%",
      }}
    >
      <div
        style={{
          height: "100%",
          width: `${pct}%`,
          background: color,
          borderRadius: 999,
          transition: "width 0.6s ease",
        }}
      />
    </div>
  );
}

export function CoverageBar({
  optimized,
  baseline,
}: {
  optimized: number; // 0..1
  baseline: number; // 0..1
}) {
  const o = Math.max(0, Math.min(1, optimized)) * 100;
  const b = Math.max(0, Math.min(1, baseline)) * 100;
  return (
    <div className="stack" style={{ gap: 6, width: "100%" }}>
      <div className="row between" style={{ fontSize: "0.7rem" }}>
        <span className="muted">Baseline</span>
        <span className="tabular dim">{b.toFixed(0)}%</span>
      </div>
      <div style={{ height: 5, borderRadius: 999, background: "var(--bg-3)", position: "relative" }}>
        <div style={{ height: "100%", width: `${b}%`, borderRadius: 999, background: "var(--text-3)" }} />
      </div>
      <div className="row between" style={{ fontSize: "0.7rem" }}>
        <span className="accent-text">Optimized</span>
        <span className="tabular accent-text">{o.toFixed(0)}%</span>
      </div>
      <div style={{ height: 5, borderRadius: 999, background: "var(--bg-3)", position: "relative" }}>
        <div style={{ height: "100%", width: `${o}%`, borderRadius: 999, background: "var(--accent)" }} />
      </div>
    </div>
  );
}

export function TimeWindowBar({
  rangeMin,
  totalMin = 180,
}: {
  rangeMin: [number, number];
  totalMin?: number;
}) {
  const [lo, hi] = rangeMin;
  const left = Math.max(0, Math.min(100, (lo / totalMin) * 100));
  const width = Math.max(1, Math.min(100 - left, ((hi - lo) / totalMin) * 100));
  return (
    <div style={{ width: "100%" }}>
      <div
        style={{
          position: "relative",
          height: 10,
          borderRadius: 999,
          background: "var(--bg-3)",
        }}
      >
        <div
          style={{
            position: "absolute",
            left: `${left}%`,
            width: `${width}%`,
            height: "100%",
            borderRadius: 999,
            background: "var(--decision)",
          }}
        />
      </div>
      <div className="row between" style={{ marginTop: 4 }}>
        <span className="tabular dim" style={{ fontSize: "0.68rem" }}>
          {lo}m
        </span>
        <span className="tabular dim" style={{ fontSize: "0.68rem" }}>
          {hi}m
        </span>
      </div>
    </div>
  );
}

/** Sparkline over a small numeric series (e.g. investigation activity trend). */
export function Sparkline({
  values,
  width = 120,
  height = 32,
  color = "var(--accent)",
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
}) {
  if (values.length < 2) {
    return <svg width={width} height={height} />;
  }
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = max - min || 1;
  const step = width / (values.length - 1);
  const points = values.map((v, i) => [i * step, height - ((v - min) / range) * (height - 4) - 2]);
  const path = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const areaPath = `${path} L${width},${height} L0,${height} Z`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <path d={areaPath} fill={color} opacity={0.12} />
      <path d={path} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={points[points.length - 1][0]} cy={points[points.length - 1][1]} r={2.5} fill={color} />
    </svg>
  );
}

/** A compass showing a predicted corridor bearing + confidence cone. */
export function BearingCompass({
  bearingDeg,
  coneDeg,
  size = 120,
}: {
  bearingDeg: number;
  coneDeg: number;
  size?: number;
}) {
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 10;
  const toRad = (deg: number) => ((deg - 90) * Math.PI) / 180;
  const tip = [cx + r * Math.cos(toRad(bearingDeg)), cy + r * Math.sin(toRad(bearingDeg))];
  const coneA = bearingDeg - coneDeg / 2;
  const coneB = bearingDeg + coneDeg / 2;
  const p1 = [cx + r * Math.cos(toRad(coneA)), cy + r * Math.sin(toRad(coneA))];
  const p2 = [cx + r * Math.cos(toRad(coneB)), cy + r * Math.sin(toRad(coneB))];
  const largeArc = coneDeg > 180 ? 1 : 0;

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--border-subtle)" strokeDasharray="2 4" />
      {[0, 90, 180, 270].map((deg) => {
        const p = [cx + r * Math.cos(toRad(deg)), cy + r * Math.sin(toRad(deg))];
        return <circle key={deg} cx={p[0]} cy={p[1]} r={1.5} fill="var(--text-3)" />;
      })}
      <path
        d={`M${cx},${cy} L${p1[0]},${p1[1]} A${r},${r} 0 ${largeArc} 1 ${p2[0]},${p2[1]} Z`}
        fill="var(--decision)"
        opacity={0.18}
      />
      <line x1={cx} y1={cy} x2={tip[0]} y2={tip[1]} stroke="var(--decision)" strokeWidth={2} strokeLinecap="round" />
      <circle cx={tip[0]} cy={tip[1]} r={4} fill="var(--decision)" />
      <circle cx={cx} cy={cy} r={2.5} fill="var(--text-1)" />
      <text x={cx} y={10} textAnchor="middle" fontSize={9} fill="var(--text-3)" fontFamily="var(--font-mono)">
        N
      </text>
    </svg>
  );
}
