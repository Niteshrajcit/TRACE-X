import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { getResolution, latLngToCell } from "h3-js";
import { AlertTriangle, ArrowUpRight, GitBranch, RefreshCw, Send, ShieldAlert, Target } from "lucide-react";
import { getComplaint, getRiskField, listComplaints } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useLiveEventsContext } from "../context/LiveEventsContext";
import { useApi } from "../hooks/useApi";
import { useJurisdictionScope, shortJurisdiction } from "../hooks/useJurisdictionScope";
import { AppShell } from "../layout/AppShell";
import { RiskMap, type MapMarker } from "../components/map/RiskMap";
import { EmptyState, ErrorBlock, LoadingBlock, PageHeader, Pill } from "../components/ui/primitives";
import { Sparkline } from "../components/ui/charts";
import { eventComplaintId, eventLabel } from "../lib/eventLabels";
import type { ComplaintDetail, ComplaintSummary } from "../types/domain";

const DETAIL_FANOUT_CAP = 24;
const TOP_PRIORITY_TIER = 3;

interface PriorityCase {
  complaint: ComplaintDetail;
  pendingApprovals: number;
  ringCount: number;
  coneDeg: number;
  amount: number;
}

/**
 * Readiness report §3/§6: ranked by real, already-fetched fields only -
 * pending approvals first (needs a human decision right now), then ring
 * activity, then prediction confidence, then financial exposure. This is
 * a transparent multi-key sort, not a weighted composite score, precisely
 * so it never reads as a fabricated "AI risk score" - every row shows the
 * real values it was ranked on, not an opaque number.
 */
function buildPriorityQueue(details: ComplaintDetail[]): PriorityCase[] {
  return details
    .filter((d) => d.latest_prediction != null)
    .map((d) => ({
      complaint: d,
      pendingApprovals: d.deployment_history.filter((dep) => dep.status === "proposed").length,
      ringCount: d.graph_summary?.ring_count ?? 0,
      coneDeg: d.latest_prediction!.exit_vector.confidence_cone_deg,
      amount: Number(d.amount),
    }))
    .sort((a, b) => {
      const aPending = a.pendingApprovals > 0 ? 1 : 0;
      const bPending = b.pendingApprovals > 0 ? 1 : 0;
      if (aPending !== bPending) return bPending - aPending;
      if (b.ringCount !== a.ringCount) return b.ringCount - a.ringCount;
      if (a.coneDeg !== b.coneDeg) return a.coneDeg - b.coneDeg;
      return b.amount - a.amount;
    });
}

export function MissionControl() {
  const { auth } = useAuth();
  const token = auth!.token;
  const navigate = useNavigate();

  const complaintsState = useApi(() => listComplaints(token), [token]);
  const scope = useJurisdictionScope(auth!.jurisdictionId, complaintsState.data);

  const scoped = useMemo(
    () => (complaintsState.data ?? []).filter((c) => !scope.selected || c.jurisdiction_id === scope.selected),
    [complaintsState.data, scope.selected]
  );

  const detailTargets = useMemo(() => scoped.slice(0, DETAIL_FANOUT_CAP), [scoped]);
  const detailsState = useApi(
    () => Promise.all(detailTargets.map((c) => getComplaint(token, c.complaint_id))),
    [token, detailTargets.map((c) => c.complaint_id).join(",")]
  );

  const riskFieldState = useApi(
    () => (scope.selected ? getRiskField(token, scope.selected) : Promise.resolve(null)),
    [token, scope.selected]
  );

  const { events, keyedEvents, lastEvent, setActiveJurisdiction } = useLiveEventsContext();
  useEffect(() => {
    if (scope.selected) setActiveJurisdiction(scope.selected);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.selected]);

  // risk_field.updated is a real signal that the field this map is
  // showing is now stale - rather than silently re-fetch (which would
  // yank the map out from under someone mid-look) or ignore it (a "live"
  // map that never visibly changes), surface it as an explicit refresh
  // affordance the investigator controls.
  const [fieldStale, setFieldStale] = useState(false);
  useEffect(() => {
    if (
      lastEvent?.type === "risk_field.updated" &&
      scope.selected &&
      lastEvent.jurisdiction_id === scope.selected
    ) {
      setFieldStale(true);
    }
  }, [lastEvent, scope.selected]);
  useEffect(() => {
    setFieldStale(false);
  }, [riskFieldState.data]);

  const details: ComplaintDetail[] = detailsState.data ?? [];
  const ringCount = details.reduce((sum, d) => sum + (d.graph_summary?.ring_count ?? 0), 0);
  const priorityQueue = useMemo(() => buildPriorityQueue(details), [details]);
  const highRisk = priorityQueue.filter((p) => p.coneDeg <= 40).length;
  const pendingApprovals = priorityQueue.reduce((sum, p) => sum + p.pendingApprovals, 0);
  const activeCount = scoped.filter((c) => !["closed", "rejected"].includes(c.status)).length;

  const topPriorityIds = useMemo(
    () => new Set(priorityQueue.slice(0, TOP_PRIORITY_TIER).map((p) => p.complaint.complaint_id)),
    [priorityQueue]
  );

  const [hoveredCaseId, setHoveredCaseId] = useState<string | null>(null);
  const [selectedCell, setSelectedCell] = useState<string | null>(null);

  // Real coordinate -> real H3 index, at the same resolution the fetched
  // risk field is already using - lets a hex click filter the priority
  // queue to "cases located in this area" without the backend ever having
  // associated a case with a cell (it doesn't - this is a client-side
  // derivation from real lat/lon, disclosed as such in the UI copy below).
  const resolution = riskFieldState.data?.h3_cells[0] ? getResolution(riskFieldState.data.h3_cells[0].h3_cell) : null;
  const caseCell = useMemo(() => {
    const map = new Map<string, string>();
    if (resolution == null) return map;
    details.forEach((d) => {
      if (d.location_lat != null && d.location_lon != null) {
        map.set(d.complaint_id, latLngToCell(d.location_lat, d.location_lon, resolution));
      }
    });
    return map;
  }, [details, resolution]);

  const visibleQueue = useMemo(
    () => (selectedCell ? priorityQueue.filter((p) => caseCell.get(p.complaint.complaint_id) === selectedCell) : priorityQueue),
    [priorityQueue, selectedCell, caseCell]
  );

  const markers: MapMarker[] = details
    .filter((d) => d.location_lat != null && d.location_lon != null)
    .map((d) => ({
      id: d.complaint_id,
      lat: d.location_lat!,
      lon: d.location_lon!,
      kind: "victim",
      label: d.incident_reference,
      highlighted: topPriorityIds.has(d.complaint_id) || hoveredCaseId === d.complaint_id,
      onClick: () => navigate(`/cases/${d.complaint_id}`),
      onHoverChange: (hovering) => setHoveredCaseId(hovering ? d.complaint_id : null),
    }));

  const trend = useMemo(() => {
    const buckets = new Map<string, number>();
    scoped.forEach((c) => {
      const day = c.filed_at.slice(0, 10);
      buckets.set(day, (buckets.get(day) ?? 0) + 1);
    });
    return Array.from(buckets.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .slice(-14)
      .map(([, v]) => v);
  }, [scoped]);

  const recentCases = [...scoped].sort((a, b) => new Date(b.filed_at).getTime() - new Date(a.filed_at).getTime()).slice(0, 8);

  const complaintById = useMemo(() => {
    const map = new Map<string, ComplaintSummary>();
    scoped.forEach((c) => map.set(c.complaint_id, c));
    return map;
  }, [scoped]);

  return (
    <AppShell>
      <PageHeader
        eyebrow="Mission Control"
        title="Investigation overview"
        subtitle="A live read of everything moving through TRACE-X right now — detection, prediction, and intervention in one place."
        actions={
          !scope.isFixed && scope.options.length > 0 ? (
            <select value={scope.selected ?? ""} onChange={(e) => scope.setSelected(e.target.value)} style={{ width: 220 }}>
              {scope.options.map((id) => (
                <option key={id} value={id}>
                  Jurisdiction {shortJurisdiction(id)}
                </option>
              ))}
            </select>
          ) : undefined
        }
      />

      <div className="mission-banner" style={{ marginBottom: 16 }}>
        <div className="mission-banner-item">
          <span className="mission-banner-label">
            <ShieldAlert size={13} /> Active investigations
          </span>
          <span className="mission-banner-value">{activeCount}</span>
        </div>
        <div className="mission-banner-item">
          <span className="mission-banner-label">
            <GitBranch size={13} /> Rings detected
          </span>
          <span className="mission-banner-value accent-text">
            {ringCount}
            <span className="unit">/ {details.length} reviewed</span>
          </span>
        </div>
        <div className="mission-banner-item">
          <span className="mission-banner-label">
            <AlertTriangle size={13} /> High-confidence predictions
          </span>
          <span className="mission-banner-value">{highRisk}</span>
        </div>
        <div className="mission-banner-item">
          <span className="mission-banner-label">
            <Send size={13} /> Pending approvals
          </span>
          <span className="mission-banner-value decision-text">{pendingApprovals}</span>
        </div>
      </div>

      <div className="split" style={{ marginBottom: 16 }}>
        <div className="panel-hero">
          <div className="panel-header">
            <h2>Jurisdiction risk field</h2>
            <div className="row" style={{ gap: 10 }}>
              {fieldStale && (
                <button className="link-button" onClick={() => riskFieldState.reload()} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <RefreshCw size={12} /> Field updated — refresh
                </button>
              )}
              <Link to="/risk-intelligence" className="link-button">
                Open full Risk Intelligence <ArrowUpRight size={12} style={{ verticalAlign: -1 }} />
              </Link>
            </div>
          </div>
          {riskFieldState.loading && <LoadingBlock label="Computing risk field…" />}
          {riskFieldState.error && <ErrorBlock message={riskFieldState.error} onRetry={riskFieldState.reload} />}
          {!riskFieldState.loading && !riskFieldState.error && riskFieldState.data && riskFieldState.data.h3_cells.length > 0 && (
            <>
              <RiskMap
                cells={riskFieldState.data.h3_cells}
                markers={markers}
                selectedCell={selectedCell}
                onSelectCell={setSelectedCell}
                height={540}
              />
              <p className="hint" style={{ marginTop: 10 }}>
                Pulsing pins are this jurisdiction's top {TOP_PRIORITY_TIER} priority cases (see queue) — click any pin to
                open that case. Click a hex to see cases located in that area.
              </p>
              {selectedCell && (
                <p className="hint" style={{ marginTop: 4 }}>
                  Showing cases whose reported location falls in cell <span className="mono">{selectedCell}</span> — a
                  client-derived match by coordinate, not a backend association.{" "}
                  <button className="link-button" onClick={() => setSelectedCell(null)}>
                    Clear
                  </button>
                </p>
              )}
            </>
          )}
          {!riskFieldState.loading && !riskFieldState.error && (!riskFieldState.data || riskFieldState.data.h3_cells.length === 0) && (
            <EmptyState title="No risk field yet" description="This jurisdiction has no computed risk cells yet." icon={<Target size={26} />} />
          )}
        </div>

        <div className="stack">
          <div className="panel">
            <div className="panel-header">
              <h3>Investigative priority</h3>
              <span className="meta">
                {detailsState.loading ? "…" : `${visibleQueue.length}${selectedCell ? ` of ${priorityQueue.length}` : ""}`}
              </span>
            </div>
            <p className="hint" style={{ marginBottom: 10 }}>
              Ranked by pending approvals, ring activity, and prediction confidence — a derived ordering from real case
              data, not a backend risk score.
            </p>
            {detailsState.loading && <LoadingBlock label="Reviewing cases…" />}
            {detailsState.error && <ErrorBlock message={detailsState.error} onRetry={detailsState.reload} />}
            {!detailsState.loading && !detailsState.error && details.length === 0 && (
              <EmptyState title="No cases yet" description="No complaints have been filed in this jurisdiction." />
            )}
            {!detailsState.loading && !detailsState.error && details.length > 0 && priorityQueue.length === 0 && (
              <EmptyState
                title="No cases with active predictions yet"
                description="Intelligence is still building for these cases — check back once a corridor prediction has run."
              />
            )}
            {!detailsState.loading && !detailsState.error && priorityQueue.length > 0 && visibleQueue.length === 0 && (
              <EmptyState
                title="No cases in this area"
                description="None of the reviewed cases' reported locations fall in the selected hex."
                action={
                  <button className="btn btn-sm" onClick={() => setSelectedCell(null)}>
                    Clear selection
                  </button>
                }
              />
            )}
            {visibleQueue.length > 0 && (
              <div className="stack" style={{ gap: 2, maxHeight: 260, overflowY: "auto" }}>
                {visibleQueue.slice(0, 8).map((p, i) => (
                  <div
                    key={p.complaint.complaint_id}
                    className="priority-row"
                    role="button"
                    tabIndex={0}
                    onClick={() => navigate(`/cases/${p.complaint.complaint_id}`)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        navigate(`/cases/${p.complaint.complaint_id}`);
                      }
                    }}
                    onMouseEnter={() => setHoveredCaseId(p.complaint.complaint_id)}
                    onMouseLeave={() => setHoveredCaseId(null)}
                  >
                    <span className={`priority-rank${topPriorityIds.has(p.complaint.complaint_id) ? " top" : ""}`}>{i + 1}</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="row between">
                        <span className="mono" style={{ fontWeight: 600, fontSize: "0.82rem" }}>
                          {p.complaint.incident_reference}
                        </span>
                        <span className="tabular dim" style={{ fontSize: "0.72rem" }}>
                          ₹{p.amount.toLocaleString("en-IN")}
                        </span>
                      </div>
                      <div className="row wrap" style={{ gap: 5, marginTop: 4 }}>
                        {p.pendingApprovals > 0 && (
                          <Pill tone="decision">
                            {p.pendingApprovals} pending approval{p.pendingApprovals > 1 ? "s" : ""}
                          </Pill>
                        )}
                        <Pill tone="accent">{p.ringCount} ring{p.ringCount !== 1 ? "s" : ""}</Pill>
                        <Pill>{p.coneDeg.toFixed(0)}° cone</Pill>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="panel">
            <div className="panel-header">
              <h3>Live activity</h3>
            </div>
            {events.length === 0 ? (
              <p className="hint">Waiting for pipeline events…</p>
            ) : (
              <div className="stack" style={{ gap: 6, maxHeight: 200, overflowY: "auto" }}>
                <AnimatePresence initial={false}>
                  {keyedEvents.slice(0, 10).map(({ key, event: e }) => {
                    const cid = eventComplaintId(e);
                    const ref = cid ? complaintById.get(cid)?.incident_reference : undefined;
                    return (
                      <motion.button
                        key={key}
                        className="live-feed-item"
                        disabled={!ref}
                        onClick={() => cid && navigate(`/cases/${cid}`)}
                        initial={{ opacity: 0, x: -8, height: 0 }}
                        animate={{ opacity: 1, x: 0, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
                      >
                        <span className="live-feed-label">{eventLabel(e)}</span>
                        {ref ? <span className="mono live-feed-ref">{ref}</span> : <Pill tone="accent">live</Pill>}
                      </motion.button>
                    );
                  })}
                </AnimatePresence>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2">
        <div className="panel">
          <div className="panel-header">
            <h3>Filing trend</h3>
            <span className="meta">last {trend.length} days</span>
          </div>
          <Sparkline values={trend.length > 1 ? trend : [0, 0]} width={280} height={48} />
        </div>

        <div className="panel">
          <div className="panel-header">
            <h2>Recent cases</h2>
            <Link to="/cases" className="link-button">
              View all cases <ArrowUpRight size={12} style={{ verticalAlign: -1 }} />
            </Link>
          </div>
          {complaintsState.loading && <LoadingBlock />}
          {complaintsState.error && <ErrorBlock message={complaintsState.error} onRetry={complaintsState.reload} />}
          {!complaintsState.loading && !complaintsState.error && recentCases.length === 0 && (
            <EmptyState title="No cases yet" description="No complaints have been filed in this jurisdiction." />
          )}
          {recentCases.length > 0 && (
            <div className="scroll-x">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Incident</th>
                    <th>Fraud type</th>
                    <th>Amount</th>
                    <th>Status</th>
                    <th>Filed</th>
                  </tr>
                </thead>
                <tbody>
                  {recentCases.map((c) => (
                    <tr
                      key={c.complaint_id}
                      className="clickable"
                      role="button"
                      tabIndex={0}
                      onClick={() => navigate(`/cases/${c.complaint_id}`)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          navigate(`/cases/${c.complaint_id}`);
                        }
                      }}
                    >
                      <td className="mono">{c.incident_reference}</td>
                      <td>{c.fraud_type.replace(/_/g, " ")}</td>
                      <td className="tabular">₹{Number(c.amount).toLocaleString("en-IN")}</td>
                      <td>
                        <Pill>{c.status.replace(/_/g, " ")}</Pill>
                      </td>
                      <td className="dim">{new Date(c.filed_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
