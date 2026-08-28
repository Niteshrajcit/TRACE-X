import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertCircle, Info, Radio } from "lucide-react";
import { getComplaintExplanation } from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { useCase } from "../../context/CaseContext";
import { useInvestigationFocus } from "../../context/InvestigationFocusContext";
import { useLiveEventsContext } from "../../context/LiveEventsContext";
import { useApi } from "../../hooks/useApi";
import { NetworkGraph, type GraphNodeKind } from "../../components/graph/NetworkGraph";
import { IndiaInset } from "../../components/map/IndiaInset";
import { ConfidenceBar } from "../../components/ui/charts";
import { EmptyState, ErrorBlock, LoadingBlock, Panel, Pill, StatCard } from "../../components/ui/primitives";
import { computeSuspiciousIndicators } from "../../lib/suspiciousIndicators";
import type { RingSummary } from "../../types/domain";

const NODE_KIND_LABEL: Record<GraphNodeKind, string> = {
  victim: "Victim account",
  hop: "Real transfer hop",
  ring_member: "Detected ring member",
  predicted_exit: "Predicted exit channel",
};

function classifyNode(id: string, realPath: string[], predictedExitChannelId: string | null): GraphNodeKind {
  if (realPath[0] === id) return "victim";
  if (predictedExitChannelId === id) return "predicted_exit";
  if (realPath.includes(id)) return "hop";
  return "ring_member";
}

export function NetworkInvestigation() {
  const { auth } = useAuth();
  const { complaint, rings } = useCase();
  const focus = useInvestigationFocus();
  const { keyedEvents } = useLiveEventsContext();
  const [isolate, setIsolate] = useState(false);

  const explanationState = useApi(
    () => getComplaintExplanation(auth!.token, complaint.complaint_id),
    [auth!.token, complaint.complaint_id]
  );

  const realPath = explanationState.data?.graph_path?.real_path ?? [];
  const predictedExit = explanationState.data?.graph_path?.predicted_exit_channel_id ?? null;
  const hasAnything = realPath.length > 0 || rings.length > 0;

  const selectedAccountRings = focus.selectedAccountId
    ? rings.filter((r) => r.member_account_ids.includes(focus.selectedAccountId!))
    : [];

  const inspectedRing: RingSummary | null = rings.find((r) => r.ring_id === focus.selectedRingId) ?? null;

  function handleSelectNode(nodeId: string | null) {
    focus.selectAccount(nodeId);
    // Selecting an account that belongs to a ring also focuses that ring,
    // so switching to Rings & Corridors immediately shows it (F1's
    // cross-panel focus, preserved here per the F3 brief's own requirement
    // that this bridge into F4 must keep working).
    if (nodeId) {
      const owningRing = rings.find((r) => r.member_account_ids.includes(nodeId));
      focus.setRingFocus(owningRing?.ring_id ?? null);
    } else {
      focus.setRingFocus(null);
    }
  }

  // If the isolated ring gets cleared some other way (e.g. from the Rings
  // & Corridors tab), don't leave the graph silently filtered to nothing.
  useEffect(() => {
    if (!focus.selectedRingId) setIsolate(false);
  }, [focus.selectedRingId]);

  const liveTxnEvents = useMemo(
    () =>
      keyedEvents.filter(
        (k) => k.event.type === "transaction.ingested" && k.event.complaint_id === complaint.complaint_id
      ),
    [keyedEvents, complaint.complaint_id]
  );

  const ringAggregate = useMemo(
    () => ({
      transactionCount: rings.reduce((sum, r) => sum + r.transaction_count, 0),
      totalAmount: rings.reduce((sum, r) => sum + Number(r.total_amount), 0),
    }),
    [rings]
  );

  const indicators = computeSuspiciousIndicators(rings, complaint);

  return (
    <div className="stack">
      <div className="split">
        <Panel
          className="panel-hero"
          title="Financial crime network"
          meta={hasAnything ? `${realPath.length} verified hop(s) · ${rings.length} ring(s)` : undefined}
        >
          {!hasAnything && !explanationState.loading && !explanationState.error && (
            <EmptyState
              title="No network intelligence yet"
              description="The graph builder has not produced a transfer chain or detected ring for this case yet."
            />
          )}
          {explanationState.loading && <LoadingBlock label="Loading verified transfer path…" />}
          {explanationState.error && <ErrorBlock message={explanationState.error} onRetry={explanationState.reload} />}
          {!explanationState.loading && !explanationState.error && hasAnything && (
            <>
              <NetworkGraph
                realPath={realPath}
                predictedExitChannelId={predictedExit}
                rings={rings}
                height={620}
                selectedNodeId={focus.selectedAccountId}
                highlightRingId={!isolate ? focus.selectedRingId : null}
                isolateRingId={isolate ? focus.selectedRingId : null}
                onSelectNode={handleSelectNode}
              />
              <div className="row" style={{ gap: 8, marginTop: 10, alignItems: "flex-start" }}>
                <Info size={13} style={{ color: "var(--accent)", marginTop: 2, flexShrink: 0 }} />
                <p className="hint">
                  Solid lines are a Neo4j-verified transfer chain. Dashed lines inside a ring cluster are{" "}
                  <strong>inferred</strong> from aggregate cohesion/entity-sharing signals, not individually-verified
                  transactions. Scroll to zoom, drag to pan.
                </p>
              </div>
            </>
          )}
        </Panel>

        <div className="stack">
          <Panel title="Case context">
            <div className="stack" style={{ gap: 8, fontSize: "0.82rem" }}>
              <div className="row between">
                <span className="dim">Incident</span>
                <span className="mono">{complaint.incident_reference}</span>
              </div>
              <div className="row between">
                <span className="dim">Fraud type</span>
                <span>{complaint.fraud_type.replace(/_/g, " ")}</span>
              </div>
              <div className="row between">
                <span className="dim">Amount</span>
                <span className="tabular">₹{Number(complaint.amount).toLocaleString("en-IN")}</span>
              </div>
              <div className="row between">
                <span className="dim">Status</span>
                <Pill>{complaint.status.replace(/_/g, " ")}</Pill>
              </div>
              <div className="row between">
                <span className="dim">Jurisdiction</span>
                <span className="mono dim" style={{ fontSize: "0.72rem" }}>
                  {complaint.jurisdiction_id ? `${complaint.jurisdiction_id.slice(0, 8)}…` : "—"}
                </span>
              </div>
            </div>
            <hr className="divider" />
            <div className="stack" style={{ gap: 6 }}>
              {indicators.map((text, i) => (
                <div key={i} className="row" style={{ gap: 6, alignItems: "flex-start" }}>
                  <AlertCircle size={12} style={{ color: "var(--decision)", flexShrink: 0, marginTop: 2 }} />
                  <span style={{ fontSize: "0.78rem" }}>{text}</span>
                </div>
              ))}
            </div>
          </Panel>

          {focus.selectedAccountId && (
            <Panel
              title="Selected node"
              actions={
                <button className="link-button" onClick={() => handleSelectNode(null)}>
                  Clear
                </button>
              }
            >
              <div className="stack" style={{ gap: 8 }}>
                <Pill tone="accent">{NODE_KIND_LABEL[classifyNode(focus.selectedAccountId, realPath, predictedExit)]}</Pill>
                <p className="mono" style={{ fontSize: "0.72rem", wordBreak: "break-all" }}>
                  {focus.selectedAccountId}
                </p>
                {selectedAccountRings.length === 0 && <p className="hint">Not a member of any detected ring.</p>}
                {selectedAccountRings.map((r) => (
                  <div key={r.ring_id} className="row between">
                    <span className="dim" style={{ fontSize: "0.75rem" }}>
                      Ring {r.ring_id.slice(0, 8)}…
                    </span>
                    {focus.selectedRingId === r.ring_id ? (
                      <Pill tone="accent">inspecting</Pill>
                    ) : (
                      <button className="link-button" onClick={() => focus.setRingFocus(r.ring_id)}>
                        Inspect
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </Panel>
          )}

          <Panel title="Ring intelligence" meta={rings.length ? `${rings.length} detected` : undefined}>
            {rings.length === 0 && <EmptyState title="No rings detected yet" description="Ring detection runs once the graph has enough structure." />}
            {rings.length > 0 && (
              <>
                <div className="row wrap" style={{ gap: 6, marginBottom: 12 }}>
                  {rings.map((r) => (
                    <button
                      key={r.ring_id}
                      className={`ring-chip${focus.selectedRingId === r.ring_id ? " active" : ""}`}
                      onClick={() => focus.selectRing(r.ring_id)}
                    >
                      {r.ring_id.slice(0, 6)}… · {r.member_count}m
                    </button>
                  ))}
                </div>

                {!inspectedRing && <p className="hint">Select a ring above, or a node in the graph, to inspect its statistics.</p>}

                {inspectedRing && (
                  <div className="stack" style={{ gap: 12 }}>
                    <label className="row" style={{ gap: 8, margin: 0, fontWeight: 500, fontSize: "0.78rem" }}>
                      <input type="checkbox" checked={isolate} onChange={(e) => setIsolate(e.target.checked)} style={{ width: "auto" }} />
                      Isolate this ring in the graph
                    </label>

                    <div>
                      <div className="row between" style={{ marginBottom: 4 }}>
                        <span className="dim" style={{ fontSize: "0.72rem" }}>
                          Structural cohesion
                        </span>
                        <span className="tabular" style={{ fontSize: "0.72rem" }}>
                          {Number(inspectedRing.cohesion_score).toFixed(2)}
                        </span>
                      </div>
                      <ConfidenceBar value={Number(inspectedRing.cohesion_score)} color="var(--accent)" />
                    </div>

                    <div className="grid grid-cols-3" style={{ gap: 8 }}>
                      <StatCard label="Members" value={inspectedRing.member_count} />
                      <StatCard label="Transactions" value={inspectedRing.transaction_count} />
                      <StatCard label="Total" value={`₹${Number(inspectedRing.total_amount).toLocaleString("en-IN")}`} />
                    </div>

                    {(inspectedRing.fan_in_count > 0 || inspectedRing.fan_out_count > 0) && (
                      <div className="stack" style={{ gap: 6 }}>
                        <span className="dim" style={{ fontSize: "0.72rem" }}>
                          Fan-in / fan-out
                        </span>
                        <FanBar label="In" count={inspectedRing.fan_in_count} amount={Number(inspectedRing.fan_in_amount)} max={Math.max(Number(inspectedRing.fan_in_amount), Number(inspectedRing.fan_out_amount), 1)} color="var(--ok)" />
                        <FanBar label="Out" count={inspectedRing.fan_out_count} amount={Number(inspectedRing.fan_out_amount)} max={Math.max(Number(inspectedRing.fan_in_amount), Number(inspectedRing.fan_out_amount), 1)} color="var(--decision)" />
                      </div>
                    )}

                    {inspectedRing.burst_ratio != null && (
                      <div>
                        <div className="row between" style={{ marginBottom: 4 }}>
                          <span className="dim" style={{ fontSize: "0.72rem" }}>
                            Burst ratio
                          </span>
                          <span className="tabular" style={{ fontSize: "0.72rem" }}>
                            {Number(inspectedRing.burst_ratio).toFixed(2)}
                          </span>
                        </div>
                        <ConfidenceBar value={Number(inspectedRing.burst_ratio)} color="var(--risk-high)" />
                      </div>
                    )}

                    <div className="row wrap" style={{ gap: 6 }}>
                      <Pill>{inspectedRing.device_count} device</Pill>
                      <Pill>{inspectedRing.ip_count} IP</Pill>
                      <Pill>{inspectedRing.phone_count} phone</Pill>
                      <Pill>{inspectedRing.vpa_count} VPA</Pill>
                      {inspectedRing.geographic_spread_km != null && (
                        <Pill>{Number(inspectedRing.geographic_spread_km).toFixed(1)} km spread</Pill>
                      )}
                    </div>

                    <p className="hint">
                      Algorithm: {inspectedRing.algorithm_name} {inspectedRing.algorithm_version}
                    </p>
                  </div>
                )}
              </>
            )}
          </Panel>

          <Panel title="Geographic context">
            <IndiaInset lat={complaint.location_lat} lon={complaint.location_lon} />
          </Panel>
        </div>
      </div>

      <Panel title="Transaction activity">
        <div className="split">
          <div>
            <span className="eyebrow">Aggregate · historical</span>
            <p className="hint" style={{ margin: "6px 0 12px" }}>
              Summed across {rings.length} detected ring{rings.length === 1 ? "" : "s"} — real ring-level statistics,
              not a transaction-by-transaction record (no such endpoint exists on the backend).
            </p>
            {rings.length === 0 ? (
              <EmptyState title="No ring statistics yet" />
            ) : (
              <div className="grid grid-cols-2">
                <StatCard label="Ring transactions" value={ringAggregate.transactionCount} />
                <StatCard label="Ring transaction total" value={`₹${ringAggregate.totalAmount.toLocaleString("en-IN")}`} />
              </div>
            )}
          </div>

          <div>
            <span className="eyebrow">Live · this session</span>
            <p className="hint" style={{ margin: "6px 0 12px" }}>
              Real <span className="mono">transaction.ingested</span> events for this case, received while connected —
              not a historical record.
            </p>
            {liveTxnEvents.length === 0 ? (
              <EmptyState
                title="No live transactions yet"
                description="Real transaction.ingested events for this case will appear here as they arrive."
                icon={<Radio size={22} />}
              />
            ) : (
              <div className="stack" style={{ gap: 6, maxHeight: 200, overflowY: "auto" }}>
                <AnimatePresence initial={false}>
                  {liveTxnEvents.map(({ key, event }) =>
                    event.type === "transaction.ingested" ? (
                      <motion.div
                        key={key}
                        className="live-feed-item"
                        style={{ cursor: "default" }}
                        initial={{ opacity: 0, x: -8, height: 0 }}
                        animate={{ opacity: 1, x: 0, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
                      >
                        <span className="live-feed-label">
                          {event.channel} · hop {event.hop_index}
                        </span>
                        <span className="tabular live-feed-ref">₹{Number(event.amount).toLocaleString("en-IN")}</span>
                      </motion.div>
                    ) : null
                  )}
                </AnimatePresence>
              </div>
            )}
          </div>
        </div>
      </Panel>
    </div>
  );
}

function FanBar({ label, count, amount, max, color }: { label: string; count: number; amount: number; max: number; color: string }) {
  const pct = Math.max(0, Math.min(1, amount / max)) * 100;
  return (
    <div className="row" style={{ gap: 8 }}>
      <span className="dim" style={{ fontSize: "0.7rem", width: 24 }}>
        {label}
      </span>
      <div style={{ flex: 1, height: 6, borderRadius: 999, background: "var(--bg-3)" }}>
        <div style={{ height: "100%", width: `${pct}%`, borderRadius: 999, background: color, transition: "width var(--duration-reveal) var(--ease-standard)" }} />
      </div>
      <span className="tabular dim" style={{ fontSize: "0.7rem", width: 90, textAlign: "right" }}>
        {count} · ₹{amount.toLocaleString("en-IN")}
      </span>
    </div>
  );
}
