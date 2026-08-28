import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import type { RingSummary } from "../../types/domain";

export type GraphNodeKind = "victim" | "hop" | "ring_member" | "predicted_exit";

interface GraphNode extends SimulationNodeDatum {
  id: string;
  kind: GraphNodeKind;
  label: string;
  ringId?: string;
  cohesion?: number;
}

interface GraphLink extends SimulationLinkDatum<GraphNode> {
  kind: "real" | "inferred";
}

const NODE_COLOR: Record<GraphNodeKind, string> = {
  victim: "#eef2f7",
  hop: "#8b96a5",
  ring_member: "#22d3ee",
  predicted_exit: "#f5c451",
};

const NODE_RADIUS: Record<GraphNodeKind, number> = {
  victim: 11,
  hop: 7,
  ring_member: 6.5,
  predicted_exit: 11,
};

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3.5;

function shortId(id: string): string {
  return id.length > 10 ? `${id.slice(0, 4)}…${id.slice(-4)}` : id;
}

export function NetworkGraph({
  realPath,
  predictedExitChannelId,
  rings,
  height = 620,
  onSelectNode,
  selectedNodeId,
  highlightRingId,
  isolateRingId,
}: {
  realPath: string[];
  predictedExitChannelId?: string | null;
  rings: RingSummary[];
  height?: number;
  onSelectNode?: (nodeId: string | null) => void;
  /** Controlled selection - pass the shared investigation focus's selected
   * account so this graph reflects a selection made elsewhere without
   * requiring a click here first. Omit to let the component manage its
   * own click-selection state (existing standalone behavior). */
  selectedNodeId?: string | null;
  /** Emphasize a ring's members even when nothing has been clicked in
   * this graph - lets opening Network after selecting a ring on Rings &
   * Corridors immediately show why that ring is suspicious. */
  highlightRingId?: string | null;
  /** Filter mode: exclude every other ring's members from the graph
   * entirely (the real verified path is always kept - it's the
   * authoritative thread regardless of which ring is being isolated). */
  isolateRingId?: string | null;
}) {
  const [internalSelected, setInternalSelected] = useState<string | null>(null);
  const selected = selectedNodeId !== undefined ? selectedNodeId : internalSelected;
  const width = 1100;

  const { nodes, links, ringGroups } = useMemo(() => {
    const nodeMap = new Map<string, GraphNode>();
    const links: GraphLink[] = [];

    realPath.forEach((accountId, i) => {
      const isFirst = i === 0;
      const isLast = i === realPath.length - 1 && !!predictedExitChannelId;
      const kind: GraphNodeKind = isFirst ? "victim" : isLast ? "predicted_exit" : "hop";
      if (!nodeMap.has(accountId)) {
        nodeMap.set(accountId, { id: accountId, kind, label: isFirst ? "Victim account" : shortId(accountId) });
      }
      if (i > 0) {
        links.push({ source: realPath[i - 1], target: accountId, kind: "real" });
      }
    });

    if (predictedExitChannelId && !nodeMap.has(predictedExitChannelId)) {
      nodeMap.set(predictedExitChannelId, {
        id: predictedExitChannelId,
        kind: "predicted_exit",
        label: `Exit · ${shortId(predictedExitChannelId)}`,
      });
      const last = realPath[realPath.length - 1];
      if (last) links.push({ source: last, target: predictedExitChannelId, kind: "real" });
    }

    const ringGroups: { ringId: string; cohesion: number; memberIds: string[] }[] = [];
    rings.forEach((ring) => {
      // Ring isolation excludes this ring's own members from the graph
      // entirely when a different ring is being isolated - but the
      // verified real-path chain is never excluded, isolated or not.
      if (isolateRingId && ring.ring_id !== isolateRingId) return;

      const cohesion = Number(ring.cohesion_score) || 0;
      const memberIds: string[] = [];
      ring.member_account_ids.forEach((accountId) => {
        memberIds.push(accountId);
        if (!nodeMap.has(accountId)) {
          nodeMap.set(accountId, {
            id: accountId,
            kind: "ring_member",
            label: shortId(accountId),
            ringId: ring.ring_id,
            cohesion,
          });
        } else {
          const existing = nodeMap.get(accountId)!;
          existing.ringId = existing.ringId ?? ring.ring_id;
          existing.cohesion = existing.cohesion ?? cohesion;
        }
      });
      // Honest disclosure: no per-pair transaction edge is known within a
      // ring, only aggregate cohesion/entity-sharing signals - so members
      // are linked as an inferred star around a synthetic cluster anchor,
      // never as fabricated one-to-one transaction edges.
      for (let i = 1; i < memberIds.length; i++) {
        links.push({ source: memberIds[0], target: memberIds[i], kind: "inferred" });
      }
      ringGroups.push({ ringId: ring.ring_id, cohesion, memberIds });
    });

    const nodes = Array.from(nodeMap.values());

    const sim = forceSimulation(nodes)
      .force(
        "link",
        forceLink<GraphNode, GraphLink>(links)
          .id((d) => d.id)
          .distance((l) => (l.kind === "real" ? 110 : 56))
          .strength((l) => (l.kind === "real" ? 0.9 : 0.35))
      )
      .force("charge", forceManyBody().strength(-220))
      .force("center", forceCenter(width / 2, height / 2))
      .force("collide", forceCollide().radius((d) => NODE_RADIUS[(d as GraphNode).kind] + 12))
      .stop();

    for (let i = 0; i < 340; i++) sim.tick();

    return { nodes, links, ringGroups };
  }, [realPath, predictedExitChannelId, rings, height, isolateRingId]);

  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const connected = useMemo(() => {
    if (!selected) return null;
    const s = new Set<string>([selected]);
    links.forEach((l) => {
      const sourceId = typeof l.source === "object" ? (l.source as GraphNode).id : (l.source as string);
      const targetId = typeof l.target === "object" ? (l.target as GraphNode).id : (l.target as string);
      if (sourceId === selected) s.add(targetId);
      if (targetId === selected) s.add(sourceId);
    });
    return s;
  }, [selected, links]);

  const ringHighlightIds = useMemo(() => {
    if (!highlightRingId || selected) return null;
    const group = ringGroups.find((g) => g.ringId === highlightRingId);
    return group ? new Set(group.memberIds) : null;
  }, [highlightRingId, selected, ringGroups]);

  function select(id: string | null) {
    if (selectedNodeId === undefined) setInternalSelected(id);
    onSelectNode?.(id);
  }

  // --- zoom / pan -----------------------------------------------------------
  // Hand-rolled (no d3-zoom dependency) - a transform applied to a <g> that
  // wraps the already force-simulated content. Wheel zooms toward the
  // cursor; dragging the background rect (painted first, so nodes on top
  // still receive their own click before this) pans.
  const [view, setView] = useState({ k: 1, x: 0, y: 0 });
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ startX: number; startY: number; viewX: number; viewY: number } | null>(null);

  function clampK(k: number) {
    return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, k));
  }

  function zoomBy(factor: number, centerX = width / 2, centerY = height / 2) {
    setView((prev) => {
      const nextK = clampK(prev.k * factor);
      const scaleRatio = nextK / prev.k;
      return {
        k: nextK,
        x: centerX - (centerX - prev.x) * scaleRatio,
        y: centerY - (centerY - prev.y) * scaleRatio,
      };
    });
  }

  // React attaches its own `wheel` listener as passive (for scroll
  // performance), so `event.preventDefault()` inside a React `onWheel`
  // handler is silently ignored and throws a console warning on every
  // tick - a well-known React footgun. A native, explicitly non-passive
  // listener is the correct fix, not a workaround.
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    function onWheel(e: globalThis.WheelEvent) {
      e.preventDefault();
      const rect = svg!.getBoundingClientRect();
      const px = ((e.clientX - rect.left) / rect.width) * width;
      const py = ((e.clientY - rect.top) / rect.height) * height;
      zoomBy(e.deltaY < 0 ? 1.15 : 1 / 1.15, px, py);
    }
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]);

  function handlePointerDown(e: PointerEvent<SVGRectElement>) {
    dragRef.current = { startX: e.clientX, startY: e.clientY, viewX: view.x, viewY: view.y };
    (e.target as Element).setPointerCapture(e.pointerId);
  }

  function handlePointerMove(e: PointerEvent<SVGRectElement>) {
    const drag = dragRef.current;
    if (!drag) return;
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const scaleX = width / rect.width;
    const scaleY = height / rect.height;
    // Capture the drag-start values into locals now, synchronously - the
    // setView updater below runs later, during React's own commit, by
    // which point a fast pointerup could already have reset dragRef.current
    // to null (a real, if rare, race on quick drags/flicks otherwise).
    const { viewX, viewY, startX, startY } = drag;
    setView((prev) => ({
      ...prev,
      x: viewX + (e.clientX - startX) * scaleX,
      y: viewY + (e.clientY - startY) * scaleY,
    }));
  }

  function handlePointerUp() {
    dragRef.current = null;
  }

  function resetView() {
    setView({ k: 1, x: 0, y: 0 });
  }

  // Recenter whenever the underlying graph actually changes shape (new
  // case, new ring isolation) rather than leaving the investigator zoomed
  // into empty space after a filter change.
  useEffect(() => {
    resetView();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [realPath, isolateRingId]);

  return (
    <div style={{ position: "relative", width: "100%", height }}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height="100%"
        style={{ display: "block", touchAction: "none" }}
      >
        <defs>
          <radialGradient id="networkVignette" cx="50%" cy="42%" r="75%">
            <stop offset="0%" stopColor="var(--bg-2)" />
            <stop offset="100%" stopColor="var(--bg-0)" />
          </radialGradient>
          <radialGradient id="nodeSelectionGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.5" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </radialGradient>
        </defs>
        <rect x={0} y={0} width={width} height={height} fill="url(#networkVignette)" rx={8} />
        <rect
          x={0}
          y={0}
          width={width}
          height={height}
          fill="transparent"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          style={{ cursor: "grab" }}
        />

        <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
          {ringGroups.map((g) => {
            const pts = g.memberIds.map((id) => nodeById.get(id)).filter(Boolean) as GraphNode[];
            if (pts.length === 0) return null;
            const cx = pts.reduce((a, n) => a + (n.x ?? 0), 0) / pts.length;
            const cy = pts.reduce((a, n) => a + (n.y ?? 0), 0) / pts.length;
            const r = Math.max(...pts.map((n) => Math.hypot((n.x ?? 0) - cx, (n.y ?? 0) - cy))) + 30;
            const isHighlighted = highlightRingId === g.ringId || isolateRingId === g.ringId;
            return (
              <circle
                key={g.ringId}
                cx={cx}
                cy={cy}
                r={r}
                fill="var(--accent)"
                fillOpacity={isHighlighted ? 0.16 + g.cohesion * 0.08 : 0.05 + g.cohesion * 0.05}
                stroke="var(--accent)"
                strokeWidth={isHighlighted ? 2.5 : 1}
                strokeOpacity={isHighlighted ? 0.8 : 0.25}
                strokeDasharray={isHighlighted ? undefined : "3 4"}
                style={{ transition: "all var(--duration-panel) var(--ease-standard)" }}
              />
            );
          })}

          {links.map((l, i) => {
            const source = typeof l.source === "object" ? (l.source as GraphNode) : nodeById.get(l.source as string);
            const target = typeof l.target === "object" ? (l.target as GraphNode) : nodeById.get(l.target as string);
            if (!source || !target) return null;
            const dimBySelection = selected && connected && !(connected.has(source.id) && connected.has(target.id));
            const dimByRing = ringHighlightIds && !(ringHighlightIds.has(source.id) && ringHighlightIds.has(target.id));
            const dim = dimBySelection || dimByRing;
            return (
              <line
                key={i}
                x1={source.x}
                y1={source.y}
                x2={target.x}
                y2={target.y}
                stroke={l.kind === "real" ? "var(--text-1)" : "var(--border-strong)"}
                strokeWidth={l.kind === "real" ? 1.8 : 1}
                strokeDasharray={l.kind === "inferred" ? "3 3" : undefined}
                opacity={dim ? 0.12 : l.kind === "real" ? 0.85 : 0.45}
                style={{ transition: "opacity var(--duration-panel) var(--ease-standard)" }}
              />
            );
          })}

          {nodes.map((n) => {
            const dimBySelection = selected && connected && !connected.has(n.id);
            const dimByRing = ringHighlightIds && !ringHighlightIds.has(n.id);
            const dim = dimBySelection || dimByRing;
            const isSelected = selected === n.id;
            return (
              <g
                key={n.id}
                transform={`translate(${n.x},${n.y})`}
                style={{ cursor: "pointer", transition: "opacity var(--duration-panel) var(--ease-standard)" }}
                opacity={dim ? 0.22 : 1}
                onClick={() => select(isSelected ? null : n.id)}
              >
                {n.kind === "predicted_exit" && (
                  <circle r={NODE_RADIUS[n.kind] + 7} fill="none" stroke="var(--decision)" strokeWidth={1.5} strokeDasharray="2 3" />
                )}
                {isSelected && (
                  <>
                    {/* Selection glow - the selected node becomes the
                        visual center of the graph, not just a thinly
                        outlined circle among equals. */}
                    <circle r={NODE_RADIUS[n.kind] + 22} fill="url(#nodeSelectionGlow)" className="hex-pulse" />
                    <circle r={NODE_RADIUS[n.kind] + 5} fill="none" stroke="var(--text-0)" strokeWidth={1} strokeOpacity={0.4} />
                  </>
                )}
                <circle
                  r={NODE_RADIUS[n.kind]}
                  fill={NODE_COLOR[n.kind]}
                  stroke={isSelected ? "var(--text-0)" : "var(--bg-0)"}
                  strokeWidth={isSelected ? 2.5 : 1.5}
                  style={{ transition: "r var(--duration-micro) var(--ease-standard)" }}
                />
                <circle r={2} fill="var(--bg-0)" opacity={n.kind === "victim" || n.kind === "predicted_exit" ? 0.5 : 0} />
                <text
                  y={NODE_RADIUS[n.kind] + 15}
                  textAnchor="middle"
                  fontSize={10.5}
                  fontFamily="var(--font-mono)"
                  fill="var(--text-2)"
                >
                  {n.label}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      <div className="graph-zoom-controls">
        <button className="btn btn-ghost btn-sm" onClick={() => zoomBy(1.25)} aria-label="Zoom in">
          <ZoomIn size={14} />
        </button>
        <button className="btn btn-ghost btn-sm" onClick={() => zoomBy(1 / 1.25)} aria-label="Zoom out">
          <ZoomOut size={14} />
        </button>
        <button className="btn btn-ghost btn-sm" onClick={resetView} aria-label="Reset view">
          <Maximize2 size={14} />
        </button>
      </div>

      <div className="row wrap" style={{ position: "absolute", left: 14, bottom: 12, gap: 10, fontSize: "0.7rem" }}>
        {(
          [
            ["victim", "Victim account"],
            ["hop", "Real transfer hop"],
            ["ring_member", "Detected ring member"],
            ["predicted_exit", "Predicted exit"],
          ] as [GraphNodeKind, string][]
        ).map(([kind, label]) => (
          <span key={kind} className="pill pill-neutral" style={{ background: "var(--bg-1)" }}>
            <span className="dot" style={{ background: NODE_COLOR[kind] }} />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}
