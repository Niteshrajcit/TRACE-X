import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { cellToLatLng, getResolution, latLngToCell } from "h3-js";
import { ArrowUpRight, Clock, Crosshair, MapPin, Radio, RefreshCw } from "lucide-react";
import { getComplaint, getRiskField, listComplaints } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useLiveEventsContext } from "../context/LiveEventsContext";
import { useApi } from "../hooks/useApi";
import { useJurisdictionScope, shortJurisdiction } from "../hooks/useJurisdictionScope";
import { AppShell } from "../layout/AppShell";
import { RiskMap, type MapMarker } from "../components/map/RiskMap";
import { IndiaInset } from "../components/map/IndiaInset";
import { EmptyState, ErrorBlock, LoadingBlock, PageHeader, Panel, Pill, RiskPill, riskLevelFromScore } from "../components/ui/primitives";
import type { ComplaintDetail } from "../types/domain";

/**
 * F5 — Risk Heatmap Dashboard (SIH deliverable B). The narrative this page
 * tells, top to bottom: WHERE IS THE RISK -> HOW STRONG IS IT -> WHEN WAS
 * IT ACTIVE -> WHAT CASE IS RELATED -> WHAT SHOULD I INVESTIGATE NEXT.
 * Every value traces to GET /v1/jurisdictions/{id}/risk-field (live or
 * ?at= historical replay) or to complaint data already fetched elsewhere
 * in this app. No hotspot, score, boundary, or case link is invented.
 */

const RISK_FLOORS: Record<string, number> = { all: 0, low: 0, medium: 0.25, high: 0.5, critical: 0.75 };
const DETAIL_CAP = 30;

/** Fixed heights per device class, matching the app's existing convention
 * of a literal px height per RiskMap usage (no page currently makes this
 * responsive via JS) - but F5 explicitly asks for the map to stay dominant
 * and usable down to mobile, so this page alone tracks viewport width to
 * pick a sensible height rather than shipping one desktop-sized constant
 * everywhere. */
function useMapHeight(): number {
  const [height, setHeight] = useState(() => (typeof window === "undefined" ? 640 : pickHeight(window.innerWidth)));
  useEffect(() => {
    const onResize = () => setHeight(pickHeight(window.innerWidth));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return height;
}
function pickHeight(width: number): number {
  if (width >= 1024) return 640;
  if (width >= 768) return 520;
  return 400;
}

export function RiskHeatmap() {
  const { auth } = useAuth();
  const token = auth!.token;
  const navigate = useNavigate();

  const complaintsState = useApi(() => listComplaints(token), [token]);
  const scope = useJurisdictionScope(auth!.jurisdictionId, complaintsState.data);
  const { keyedEvents, setActiveJurisdiction } = useLiveEventsContext();

  const [historicalAt, setHistoricalAt] = useState("");
  const [minLevel, setMinLevel] = useState<keyof typeof RISK_FLOORS>("all");
  const [selectedCell, setSelectedCell] = useState<string | null>(null);
  const mapHeight = useMapHeight();

  // auditor/admin have no fixed jurisdiction claim - this page is one of
  // the places (alongside a case being opened) that sets one explicitly so
  // the live WS connection can subscribe (mirrors CaseWorkspace's own
  // pattern for the same reason).
  useEffect(() => {
    if (!auth!.jurisdictionId && scope.selected) setActiveJurisdiction(scope.selected);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.selected]);

  const riskFieldState = useApi(
    () =>
      scope.selected
        ? getRiskField(token, scope.selected, historicalAt ? new Date(historicalAt).toISOString() : undefined)
        : Promise.resolve(null),
    [token, scope.selected, historicalAt]
  );

  const isLive = !historicalAt;

  // -- Live intelligence: risk_field.updated -----------------------------
  // Never silently apply a new value - the field the investigator is
  // looking at only changes when they explicitly refresh, so a stale
  // banner can't be mistaken for the map having already updated itself.
  const [dismissedEventKey, setDismissedEventKey] = useState(0);
  const latestUpdateEvent = useMemo(
    () => keyedEvents.find((k) => k.event.type === "risk_field.updated" && k.event.jurisdiction_id === scope.selected),
    [keyedEvents, scope.selected]
  );
  const pendingUpdate =
    isLive && latestUpdateEvent && latestUpdateEvent.event.type === "risk_field.updated" && latestUpdateEvent.key > dismissedEventKey
      ? latestUpdateEvent.event
      : null;

  // A fresh successful load means "caught up" - reset what counts as
  // "new" so switching jurisdiction/replay time doesn't carry over a
  // stale banner from a different context.
  useEffect(() => {
    if (!riskFieldState.loading) setDismissedEventKey(latestUpdateEvent?.key ?? 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [riskFieldState.data, scope.selected, historicalAt]);

  const cells = riskFieldState.data?.h3_cells ?? [];
  const scores = cells.map((c) => c.score);
  const min = Math.min(...scores, 0);
  const max = Math.max(...scores, 1);
  const range = max - min || 1;
  const floor = RISK_FLOORS[minLevel];
  const filteredCells = cells.filter((c) => (c.score - min) / range >= floor);
  const resolution = cells[0] ? getResolution(cells[0].h3_cell) : null;

  const scopedComplaints = useMemo(
    () => (complaintsState.data ?? []).filter((c) => !scope.selected || c.jurisdiction_id === scope.selected).slice(0, DETAIL_CAP),
    [complaintsState.data, scope.selected]
  );
  const detailsState = useApi(
    () => Promise.all(scopedComplaints.map((c) => getComplaint(token, c.complaint_id))),
    [token, scopedComplaints.map((c) => c.complaint_id).join(",")]
  );

  // Client-derived geographic match, explicitly labeled as such everywhere
  // it's shown - the backend has no concept of "which cases fall in which
  // cell." Real coordinates, real h3-js function, honest about being a
  // frontend derivation.
  const geolocatedComplaints = useMemo(
    () => (detailsState.data ?? []).filter((d) => d.location_lat != null && d.location_lon != null),
    [detailsState.data]
  );
  const complaintCellOf = useMemo(() => {
    const map = new Map<string, string>();
    if (resolution === null) return map;
    geolocatedComplaints.forEach((d) => {
      map.set(d.complaint_id, latLngToCell(d.location_lat!, d.location_lon!, resolution));
    });
    return map;
  }, [geolocatedComplaints, resolution]);

  const relatedCases: ComplaintDetail[] = useMemo(() => {
    if (!selectedCell) return [];
    return geolocatedComplaints.filter((d) => complaintCellOf.get(d.complaint_id) === selectedCell);
  }, [selectedCell, geolocatedComplaints, complaintCellOf]);

  const markers: MapMarker[] = geolocatedComplaints.map((d) => ({
    id: d.complaint_id,
    lat: d.location_lat!,
    lon: d.location_lon!,
    kind: "victim",
    label: d.incident_reference,
    highlighted: selectedCell != null && complaintCellOf.get(d.complaint_id) === selectedCell,
    onClick: () => setSelectedCell(complaintCellOf.get(d.complaint_id) ?? null),
  }));

  const hotspots = [...cells].sort((a, b) => b.score - a.score).slice(0, 6);
  const selectedCellData = cells.find((c) => c.h3_cell === selectedCell) ?? null;
  const selectedCentroid = selectedCellData ? cellToLatLng(selectedCellData.h3_cell) : null;

  // Real India-context inset - the centroid of the jurisdiction's own real
  // cells, not a fabricated point. Reuses the exact IndiaInset component
  // already established (and disclosed) elsewhere in the app.
  const jurisdictionCentroid = useMemo(() => {
    if (cells.length === 0) return { lat: null as number | null, lon: null as number | null };
    const pts = cells.map((c) => cellToLatLng(c.h3_cell));
    const lat = pts.reduce((s, [la]) => s + la, 0) / pts.length;
    const lon = pts.reduce((s, [, lo]) => s + lo, 0) / pts.length;
    return { lat, lon };
  }, [cells]);

  const revealKey = `${scope.selected ?? "none"}::${historicalAt || "live"}::${riskFieldState.data?.generated_for ?? ""}`;

  return (
    <AppShell>
      <PageHeader
        eyebrow="Risk Intelligence · Predictive Analytics Engine"
        title="Geospatial risk heatmap"
        subtitle="A live, H3-indexed fusion of exit-corridor predictions across the jurisdiction — the same field the optimizer scores candidate interventions against."
      />

      {/* ---------------------------------------------------------------- */}
      {/* Primary row: dominant map + India context / live-replay status   */}
      {/* ---------------------------------------------------------------- */}
      <div className="split" style={{ marginBottom: 16 }}>
        <Panel
          className="panel-hero"
          title={
            <span className="row" style={{ gap: 8 }}>
              <Crosshair size={15} style={{ color: "var(--accent)" }} />
              Risk field
            </span>
          }
          actions={
            <div className="row" style={{ gap: 8 }}>
              {isLive ? (
                <Pill tone="ok">
                  <span className="dot hex-pulse" />
                  LIVE
                </Pill>
              ) : (
                <Pill tone="decision">HISTORICAL REPLAY</Pill>
              )}
              {selectedCell && (
                <span className="pill pill-accent" style={{ fontFamily: "var(--font-mono)" }}>
                  {selectedCell.slice(0, 10)}…
                  <button
                    className="link-button"
                    style={{ marginLeft: 4, color: "inherit" }}
                    onClick={() => setSelectedCell(null)}
                    aria-label="Clear selected cell"
                  >
                    ×
                  </button>
                </span>
              )}
            </div>
          }
        >
          <AnimatePresence>
            {pendingUpdate && (
              <motion.div
                initial={{ opacity: 0, height: 0, marginBottom: 0 }}
                animate={{ opacity: 1, height: "auto", marginBottom: 10 }}
                exit={{ opacity: 0, height: 0, marginBottom: 0 }}
                transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
                className="row between"
                style={{
                  padding: "8px 12px",
                  borderRadius: "var(--radius)",
                  background: "var(--accent-dim)",
                  border: "1px solid color-mix(in srgb, var(--accent) 40%, transparent)",
                  fontSize: "0.8rem",
                }}
              >
                <span className="row" style={{ gap: 8 }}>
                  <Radio size={14} style={{ color: "var(--accent)" }} />
                  Risk field updated — {pendingUpdate.changed_cells.length} cell{pendingUpdate.changed_cells.length === 1 ? "" : "s"} changed
                </span>
                <button className="btn btn-sm btn-primary" onClick={() => riskFieldState.reload()}>
                  <RefreshCw size={13} />
                  Refresh
                </button>
              </motion.div>
            )}
          </AnimatePresence>

          {riskFieldState.loading && <LoadingBlock label="Computing risk field…" />}
          {riskFieldState.error && <ErrorBlock message={riskFieldState.error} onRetry={riskFieldState.reload} />}
          {!riskFieldState.loading && !riskFieldState.error && !scope.selected && (
            <EmptyState title="No jurisdiction selected" description="Select a jurisdiction to view its risk field." />
          )}
          {!riskFieldState.loading && !riskFieldState.error && scope.selected && filteredCells.length === 0 && (
            <EmptyState
              title="No cells at this risk level"
              description={cells.length > 0 ? "Try lowering the minimum risk level filter." : "This jurisdiction has no computed risk field yet."}
            />
          )}
          {!riskFieldState.loading && !riskFieldState.error && filteredCells.length > 0 && (
            <AnimatePresence mode="wait">
              <motion.div
                key={revealKey}
                initial={{ opacity: 0, scale: 0.99 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.4, ease: [0.4, 0, 0.2, 1] }}
              >
                <RiskMap cells={filteredCells} markers={markers} selectedCell={selectedCell} onSelectCell={setSelectedCell} height={mapHeight} />
              </motion.div>
            </AnimatePresence>
          )}

          {riskFieldState.data && (
            <p className="hint" style={{ marginTop: 10 }}>
              <Clock size={11} style={{ verticalAlign: -1.5, marginRight: 4 }} />
              {isLive ? "Generated for" : "Historical snapshot for"} {new Date(riskFieldState.data.generated_for).toLocaleString()}
              {resolution !== null && ` · H3 resolution ${resolution}`} · {cells.length} cell{cells.length === 1 ? "" : "s"} in field
            </p>
          )}
        </Panel>

        <div className="stack">
          <Panel title="Where in India">
            <IndiaInset lat={jurisdictionCentroid.lat} lon={jurisdictionCentroid.lon} />
          </Panel>

          <Panel title="Field state">
            <div className="stack" style={{ gap: 8, fontSize: "0.8rem" }}>
              <div className="row between">
                <span className="dim">Mode</span>
                {isLive ? <Pill tone="ok">Live</Pill> : <Pill tone="decision">Historical replay</Pill>}
              </div>
              {!isLive && (
                <div className="row between">
                  <span className="dim">Viewing</span>
                  <span className="tabular">{new Date(historicalAt).toLocaleString()}</span>
                </div>
              )}
              <div className="row between">
                <span className="dim">Cells in field</span>
                <span className="tabular">{cells.length}</span>
              </div>
              <div className="row between">
                <span className="dim">Incidents plotted</span>
                <span className="tabular">{markers.length}</span>
              </div>
              {isLive && (
                <p className="hint" style={{ marginTop: 2 }}>
                  Recomputed incrementally whenever a transaction lands on an active complaint in this jurisdiction — a real{" "}
                  <span className="mono">risk_field.updated</span> event, not a poll.
                </p>
              )}
            </div>
          </Panel>
        </div>
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Time / Filters | Cell Intelligence | Related Cases                */}
      {/* ---------------------------------------------------------------- */}
      <div className="grid grid-cols-3">
        <Panel title="Time & filters">
          <div className="stack" style={{ gap: 12 }}>
            {!scope.isFixed && scope.options.length > 0 && (
              <label style={{ margin: 0 }}>
                Jurisdiction
                <select
                  value={scope.selected ?? ""}
                  onChange={(e) => {
                    setSelectedCell(null);
                    scope.setSelected(e.target.value);
                  }}
                >
                  {scope.options.map((id) => (
                    <option key={id} value={id}>
                      Jurisdiction {shortJurisdiction(id)}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label style={{ margin: 0 }}>
              Minimum risk level
              <select value={minLevel} onChange={(e) => setMinLevel(e.target.value as keyof typeof RISK_FLOORS)}>
                <option value="all">All risk levels</option>
                <option value="medium">Medium and above</option>
                <option value="high">High and above</option>
                <option value="critical">Critical only</option>
              </select>
            </label>
            <label style={{ margin: 0 }}>
              Replay at (historical)
              <input type="datetime-local" value={historicalAt} onChange={(e) => setHistoricalAt(e.target.value)} />
            </label>
            {historicalAt ? (
              <button className="btn btn-sm btn-ghost" onClick={() => setHistoricalAt("")}>
                <RefreshCw size={13} />
                Back to live
              </button>
            ) : (
              <p className="hint">Choosing a time above fetches the real, historically-fused field for that moment — not an animated guess.</p>
            )}
          </div>
        </Panel>

        <Panel
          title="Cell intelligence"
          meta={selectedCell ? "selected" : `top ${hotspots.length} by score`}
        >
          <AnimatePresence mode="wait">
            <motion.div
              key={selectedCell ?? "hotspots"}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
            >
              {selectedCellData && selectedCentroid ? (
                <div className="stack" style={{ gap: 10 }}>
                  <div className="row between">
                    <span className="mono" style={{ fontSize: "0.72rem" }}>
                      {selectedCellData.h3_cell}
                    </span>
                    <RiskPill level={riskLevelFromScore((selectedCellData.score - min) / range)} />
                  </div>
                  <div className="row between">
                    <span className="dim" style={{ fontSize: "0.78rem" }}>
                      Risk score
                    </span>
                    <span className="tabular" style={{ fontWeight: 700 }}>
                      {selectedCellData.score.toFixed(3)}
                    </span>
                  </div>
                  <div className="row between">
                    <span className="dim" style={{ fontSize: "0.78rem" }}>
                      Centroid
                    </span>
                    <span className="tabular" style={{ fontSize: "0.75rem" }}>
                      {selectedCentroid[0].toFixed(4)}, {selectedCentroid[1].toFixed(4)}
                    </span>
                  </div>
                  {resolution !== null && (
                    <div className="row between">
                      <span className="dim" style={{ fontSize: "0.78rem" }}>
                        H3 resolution
                      </span>
                      <span className="tabular">{resolution}</span>
                    </div>
                  )}
                  <button className="link-button" style={{ alignSelf: "flex-start" }} onClick={() => setSelectedCell(null)}>
                    Clear selection
                  </button>
                </div>
              ) : (
                <>
                  {hotspots.length === 0 && <EmptyState title="No hotspots" description="No risk field is loaded for this jurisdiction yet." />}
                  {hotspots.length > 0 && (
                    <div className="stack" style={{ gap: 0 }}>
                      {hotspots.map((h) => {
                        const normalized = (h.score - min) / range;
                        return (
                          <div
                            key={h.h3_cell}
                            className="row between"
                            role="button"
                            tabIndex={0}
                            style={{ padding: "8px 4px", cursor: "pointer", borderBottom: "1px solid var(--border-subtle)" }}
                            onClick={() => setSelectedCell(h.h3_cell)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault();
                                setSelectedCell(h.h3_cell);
                              }
                            }}
                          >
                            <span className="mono" style={{ fontSize: "0.72rem" }}>
                              {h.h3_cell}
                            </span>
                            <RiskPill level={riskLevelFromScore(normalized)} label={h.score.toFixed(2)} />
                          </div>
                        );
                      })}
                    </div>
                  )}
                </>
              )}
            </motion.div>
          </AnimatePresence>
        </Panel>

        <Panel title="Related cases" meta="client-derived geographic match">
          {!selectedCell && <EmptyState title="Select a cell" description="Click a hex cell on the map or a hotspot row to see cases located in it." icon={<MapPin size={26} strokeWidth={1.5} />} />}
          {selectedCell && detailsState.loading && <LoadingBlock label="Matching cases…" />}
          {selectedCell && !detailsState.loading && relatedCases.length === 0 && (
            <EmptyState
              title="No linked case in current case set."
              description={`Checked against ${geolocatedComplaints.length} of ${scopedComplaints.length} reviewed case(s) with a known location (fan-out capped at ${DETAIL_CAP}).`}
            />
          )}
          {selectedCell && !detailsState.loading && relatedCases.length > 0 && (
            <div className="stack" style={{ gap: 0 }}>
              {relatedCases.map((c) => (
                <div
                  key={c.complaint_id}
                  className="row between"
                  role="button"
                  tabIndex={0}
                  style={{ padding: "10px 4px", cursor: "pointer", borderBottom: "1px solid var(--border-subtle)" }}
                  onClick={() => navigate(`/cases/${c.complaint_id}`)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") navigate(`/cases/${c.complaint_id}`);
                  }}
                >
                  <div>
                    <div className="mono" style={{ fontSize: "0.78rem" }}>
                      {c.incident_reference}
                    </div>
                    <div className="dim" style={{ fontSize: "0.72rem" }}>
                      {c.fraud_type.replace(/_/g, " ")} · ₹{Number(c.amount).toLocaleString("en-IN")}
                    </div>
                  </div>
                  <ArrowUpRight size={15} style={{ color: "var(--accent)", flexShrink: 0 }} />
                </div>
              ))}
              <p className="hint" style={{ marginTop: 8 }}>
                Matched by decoding each case's real reported coordinate to an H3 cell at this field's resolution — a frontend
                derivation, not a backend-recorded relationship.
              </p>
            </div>
          )}
        </Panel>
      </div>
    </AppShell>
  );
}
