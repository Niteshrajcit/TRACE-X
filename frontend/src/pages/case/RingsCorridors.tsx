import { useEffect, useMemo, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { cellToLatLng } from "h3-js";
import { GitBranch, Info, Target } from "lucide-react";
import { getRiskField } from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { useCase } from "../../context/CaseContext";
import { useInvestigationFocus } from "../../context/InvestigationFocusContext";
import { useLiveEventsContext } from "../../context/LiveEventsContext";
import { useApi } from "../../hooks/useApi";
import { RiskMap, type MapMarker } from "../../components/map/RiskMap";
import { BearingCompass, ConfidenceBar } from "../../components/ui/charts";
import { EmptyState, ErrorBlock, LoadingBlock, Panel, Pill, RiskPill, StatCard, riskLevelFromScore } from "../../components/ui/primitives";
import type { RingSummary } from "../../types/domain";

/**
 * F4 — Ring + Corridor Intelligence. The investigative story this page
 * tells, top to bottom: SUSPICIOUS RING -> MONEY MOVEMENT PATTERN ->
 * PREDICTED DIRECTION -> PREDICTED CORRIDOR -> CONFIDENCE -> POSSIBLE EXIT
 * AREA. Every number on this page traces to a real backend field (rings:
 * GET /v1/complaints/{id}/rings; corridor: complaint.latest_prediction).
 * Nothing here is fabricated - where the backend has a real gap (no h3_cell
 * for a ring's *observed* exit channels, no per-ring prediction endpoint),
 * this page says so in place of guessing.
 */

// Confidence-cone -> qualitative label is a frontend convenience for
// scanability, not a backend-calibrated confidence score - same disclosed
// pattern as riskLevelFromScore's thresholds elsewhere in this app (see
// FRONTEND_F1_READINESS.md §4.6). Narrower cone = the model is more
// certain about the direction, per the F2 readiness report's own framing.
function coneConfidenceLabel(coneDeg: number): { label: string; tone: "ok" | "decision" | "neutral" } {
  if (coneDeg <= 30) return { label: "Narrow — higher confidence", tone: "ok" };
  if (coneDeg <= 60) return { label: "Moderate", tone: "decision" };
  return { label: "Wide — lower confidence", tone: "neutral" };
}

export function RingsCorridors() {
  const { auth } = useAuth();
  const { complaint, rings } = useCase();
  const focus = useInvestigationFocus();
  const { keyedEvents } = useLiveEventsContext();
  const navigate = useNavigate();

  const riskFieldState = useApi(
    () => (complaint.jurisdiction_id ? getRiskField(auth!.token, complaint.jurisdiction_id) : Promise.resolve(null)),
    [auth!.token, complaint.jurisdiction_id]
  );

  const prediction = complaint.latest_prediction;

  // Highest-cohesion ring first - a real, ordering-only use of a real
  // field, not a fabricated ranking.
  const sortedRings = useMemo(
    () => [...rings].sort((a, b) => Number(b.cohesion_score) - Number(a.cohesion_score)),
    [rings]
  );

  // If nothing is focused yet when this page is opened directly (rather
  // than arriving from Network Investigation with a ring already
  // selected), default to the strongest real ring instead of an empty
  // panel - a real default, not a fabricated one, and it never fights an
  // explicit deselection (only runs once, and only when focus is empty).
  const didAutoFocus = useRef(false);
  useEffect(() => {
    if (!didAutoFocus.current && !focus.selectedRingId && sortedRings.length > 0) {
      didAutoFocus.current = true;
      focus.setRingFocus(sortedRings[0].ring_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sortedRings]);

  const selectedRing: RingSummary | null = rings.find((r) => r.ring_id === focus.selectedRingId) ?? null;

  // Honest attribution, not a guess: the REST prediction response carries
  // no ring_id (AI_ML_ARCHITECTURE.md §3's corridor stage takes "the
  // ring's hop sequence" as input, but the frozen API_CONTRACT.md response
  // shape never exposes which ring). The live `corridor_prediction.completed`
  // WS event does carry both `prediction_id` and `ring_id` - so if that
  // exact event was actually received this session, we can attribute the
  // current prediction to a real ring. Otherwise this stays honestly
  // unknown rather than assumed.
  const attributedRingId = useMemo(() => {
    if (!prediction) return null;
    const match = keyedEvents.find(
      (k) =>
        k.event.type === "corridor_prediction.completed" &&
        k.event.complaint_id === complaint.complaint_id &&
        k.event.prediction_id === prediction.prediction_id
    );
    return match && match.event.type === "corridor_prediction.completed" ? match.event.ring_id : null;
  }, [keyedEvents, prediction, complaint.complaint_id]);

  // Real geometry: each ranked exit channel's h3_cell decodes to a real
  // lat/lon centroid via h3-js - a predicted candidate, never a confirmed
  // location.
  const exitChannelMarkers: MapMarker[] = useMemo(() => {
    if (!prediction?.ranked_locations) return [];
    return prediction.ranked_locations.map((loc, i) => {
      const [lat, lon] = cellToLatLng(loc.h3_cell);
      return {
        id: loc.exit_channel_id,
        lat,
        lon,
        kind: "exit_channel",
        label: loc.channel_type,
        rank: i + 1,
        highlighted: focus.selectedExitChannelId === loc.exit_channel_id,
        onClick: () => focus.selectExitChannel(loc.exit_channel_id),
      };
    });
  }, [prediction, focus.selectedExitChannelId, focus.selectExitChannel]);

  const originMarkers: MapMarker[] =
    complaint.location_lat != null && complaint.location_lon != null
      ? [{ id: "incident", lat: complaint.location_lat, lon: complaint.location_lon, kind: "victim", label: "Known origin — observed" }]
      : [];

  const confidence = prediction ? coneConfidenceLabel(prediction.exit_vector.confidence_cone_deg) : null;
  const revealKey = `${focus.selectedRingId ?? "none"}::${prediction?.prediction_id ?? "none"}`;

  return (
    <div className="stack">
      {/* -------------------------------------------------------------- */}
      {/* Ring selector strip - compact, not a card dashboard             */}
      {/* -------------------------------------------------------------- */}
      <Panel
        title={
          <span className="row" style={{ gap: 8 }}>
            <GitBranch size={15} style={{ color: "var(--accent)" }} />
            Suspicious rings
          </span>
        }
        meta={rings.length ? `${rings.length} detected in this case` : undefined}
      >
        {rings.length === 0 && (
          <EmptyState title="No rings detected yet" description="Ring detection runs once the transaction graph has enough structure." />
        )}
        {rings.length > 0 && (
          <div className="row wrap" style={{ gap: 8 }}>
            {sortedRings.map((r) => {
              const isFocused = focus.selectedRingId === r.ring_id;
              return (
                <button
                  key={r.ring_id}
                  className={`ring-chip${isFocused ? " active" : ""}`}
                  onClick={() => focus.selectRing(r.ring_id)}
                  style={{ display: "inline-flex", alignItems: "center", gap: 7 }}
                >
                  {r.ring_id.slice(0, 8)}… · {r.member_count}m · cohesion {Number(r.cohesion_score).toFixed(2)}
                </button>
              );
            })}
          </div>
        )}
        {focus.selectedRingId && (
          <p className="hint" style={{ marginTop: 10 }}>
            Focused — preserved across Network, Prediction and this tab.{" "}
            <button className="link-button" onClick={() => focus.selectRing(null)}>
              Clear
            </button>
          </p>
        )}
      </Panel>

      {/* -------------------------------------------------------------- */}
      {/* Ring intelligence | Prediction summary                         */}
      {/* -------------------------------------------------------------- */}
      <div className="grid grid-cols-2">
        <Panel
          title="Ring intelligence"
          meta={selectedRing ? `algorithm ${selectedRing.algorithm_name} ${selectedRing.algorithm_version}` : undefined}
        >
          {!selectedRing && <EmptyState title="No ring selected" description="Select a ring above to inspect its statistics." />}
          {selectedRing && (
            <div className="stack" style={{ gap: 12 }}>
              <div className="row between wrap">
                <span className="mono dim" style={{ fontSize: "0.72rem" }}>
                  {selectedRing.ring_id}
                </span>
                <RiskPill level={riskLevelFromScore(Number(selectedRing.cohesion_score))} label={`cohesion ${Number(selectedRing.cohesion_score).toFixed(2)}`} />
              </div>
              <ConfidenceBar value={Number(selectedRing.cohesion_score)} color="var(--accent)" />

              <div className="grid grid-cols-3" style={{ gap: 8 }}>
                <StatCard label="Members" value={selectedRing.member_count} />
                <StatCard label="Transactions" value={selectedRing.transaction_count} />
                <StatCard label="Total moved" value={`₹${Number(selectedRing.total_amount).toLocaleString("en-IN")}`} />
              </div>

              <div className="row wrap" style={{ gap: 6 }}>
                <Pill>{selectedRing.device_count} device</Pill>
                <Pill>{selectedRing.ip_count} IP</Pill>
                <Pill>{selectedRing.phone_count} phone</Pill>
                <Pill>{selectedRing.vpa_count} VPA shared</Pill>
              </div>

              <p className="hint">Detected {new Date(selectedRing.detected_at).toLocaleString()}</p>
            </div>
          )}
        </Panel>

        <Panel
          title={
            <span className="row" style={{ gap: 8 }}>
              <Target size={15} style={{ color: "var(--decision)" }} />
              Predicted corridor
            </span>
          }
          meta={prediction ? `generated ${new Date(prediction.generated_at).toLocaleString()}` : undefined}
        >
          {!prediction && (
            <EmptyState title="No prediction yet" description="A corridor prediction has not been generated for this case." />
          )}
          {prediction && (
            <div className="stack" style={{ gap: 14 }}>
              <div className="row" style={{ gap: 16, alignItems: "center" }}>
                <BearingCompass bearingDeg={prediction.exit_vector.bearing_deg} coneDeg={prediction.exit_vector.confidence_cone_deg} size={104} />
                <div className="stack" style={{ gap: 8, flex: 1 }}>
                  <div className="row between">
                    <span className="dim" style={{ fontSize: "0.75rem" }}>
                      Direction
                    </span>
                    <span className="tabular decision-text" style={{ fontWeight: 700 }}>
                      {prediction.exit_vector.bearing_deg.toFixed(0)}°
                    </span>
                  </div>
                  <div className="row between">
                    <span className="dim" style={{ fontSize: "0.75rem" }}>
                      Distance band
                    </span>
                    <span className="tabular" style={{ fontWeight: 600 }}>
                      {prediction.exit_vector.distance_range_km[0].toFixed(1)}–{prediction.exit_vector.distance_range_km[1].toFixed(1)} km
                    </span>
                  </div>
                  <div className="row between">
                    <span className="dim" style={{ fontSize: "0.75rem" }}>
                      Confidence cone
                    </span>
                    {confidence && <Pill tone={confidence.tone}>{prediction.exit_vector.confidence_cone_deg.toFixed(0)}° — {confidence.label}</Pill>}
                  </div>
                </div>
              </div>
              <p className="hint">
                Predicted exit channel type: <strong>{prediction.exit_vector.exit_channel_type.replace(/_/g, " ")}</strong>
              </p>
              <p className="hint" style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
                <Info size={12} style={{ marginTop: 2, flexShrink: 0, color: "var(--decision)" }} />
                <span>
                  {attributedRingId ? (
                    <>
                      Attributed to ring <span className="mono">{attributedRingId.slice(0, 8)}…</span> from a live corridor-prediction
                      event received this session.
                    </>
                  ) : (
                    <>
                      This is the case's latest corridor prediction. The prediction API does not expose which specific ring it was
                      generated from — that attribution is only available when the live <span className="mono">corridor_prediction.completed</span> event
                      is captured in the same session.
                    </>
                  )}
                </span>
              </p>
              <div className="row" style={{ gap: 8 }}>
                {/* Absolute, not navigate("prediction") - live browser
                    verification during F7 found that a bare relative
                    string here resolves incorrectly in this app's route
                    tree and lands on the wildcard "*" -> /report redirect,
                    even though the case-tab <NavLink to="prediction">
                    resolves fine. Sidestepped entirely with an absolute
                    path built from the real complaint_id. */}
                <button className="btn btn-sm" onClick={() => navigate(`/cases/${complaint.complaint_id}/prediction`)}>
                  Open Prediction &amp; Explanation
                </button>
                <button className="btn btn-sm btn-ghost" onClick={() => navigate("/risk-intelligence")}>
                  Open jurisdiction Risk Heatmap
                </button>
              </div>
            </div>
          )}
        </Panel>
      </div>

      {/* -------------------------------------------------------------- */}
      {/* Large corridor map - the primary visual on this page            */}
      {/* -------------------------------------------------------------- */}
      <AnimatePresence mode="wait">
        <motion.div
          key={revealKey}
          initial={{ opacity: 0, scale: 0.985 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.48, ease: [0.4, 0, 0.2, 1] }}
        >
          <Panel
            className="panel-hero"
            title="Corridor map"
            meta="observed origin · predicted corridor · candidate exits"
          >
            {riskFieldState.loading && <LoadingBlock label="Computing risk field…" />}
            {riskFieldState.error && <ErrorBlock message={riskFieldState.error} onRetry={riskFieldState.reload} />}
            {!riskFieldState.loading && !riskFieldState.error && riskFieldState.data && riskFieldState.data.h3_cells.length > 0 && (
              <RiskMap
                cells={riskFieldState.data.h3_cells}
                height={560}
                corridor={
                  prediction && complaint.location_lat != null && complaint.location_lon != null
                    ? {
                        fromLat: complaint.location_lat,
                        fromLon: complaint.location_lon,
                        bearingDeg: prediction.exit_vector.bearing_deg,
                        distanceKm: prediction.exit_vector.distance_range_km as [number, number],
                        coneDeg: prediction.exit_vector.confidence_cone_deg,
                      }
                    : null
                }
                markers={[...originMarkers, ...exitChannelMarkers]}
              />
            )}
            {!riskFieldState.loading && !riskFieldState.error && (!riskFieldState.data || riskFieldState.data.h3_cells.length === 0) && (
              <EmptyState title="No risk field available" description="This jurisdiction has no computed risk field yet." />
            )}
            <div className="row wrap" style={{ gap: 16, marginTop: 10 }}>
              <span className="row" style={{ gap: 6, fontSize: "0.75rem" }}>
                <span className="dot" style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--text-0)", display: "inline-block" }} />
                <span className="muted">Observed — real reported location</span>
              </span>
              <span className="row" style={{ gap: 6, fontSize: "0.75rem" }}>
                <span className="dot" style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--decision)", display: "inline-block" }} />
                <span className="muted">Predicted — corridor cone &amp; candidate exit channels, investigative leads only</span>
              </span>
            </div>
            {exitChannelMarkers.length > 0 && (
              <p className="hint" style={{ marginTop: 6 }}>
                Numbered pins are ranked candidate exit channels — click one to focus it on the Prediction tab too.
              </p>
            )}
          </Panel>
        </motion.div>
      </AnimatePresence>

      {/* -------------------------------------------------------------- */}
      {/* Movement signals | Corridor metrics | Ring evidence             */}
      {/* -------------------------------------------------------------- */}
      <div className="grid grid-cols-3">
        <Panel title="Movement signals" meta="money movement pattern">
          {!selectedRing && <EmptyState title="No ring selected" />}
          {selectedRing && (
            <div className="stack" style={{ gap: 12 }}>
              <StatCard
                label="Velocity"
                value={selectedRing.transaction_velocity != null ? Number(selectedRing.transaction_velocity).toFixed(2) : "—"}
                unit={selectedRing.transaction_velocity != null ? "txn/hr" : undefined}
              />
              <StatCard
                label="Average transaction"
                value={selectedRing.average_transaction_amount != null ? `₹${Number(selectedRing.average_transaction_amount).toLocaleString("en-IN")}` : "—"}
              />
              {selectedRing.burst_ratio != null && (
                <div>
                  <div className="row between" style={{ marginBottom: 4 }}>
                    <span className="dim" style={{ fontSize: "0.72rem" }}>
                      Burst ratio
                    </span>
                    <span className="tabular" style={{ fontSize: "0.72rem" }}>
                      {Number(selectedRing.burst_ratio).toFixed(2)}
                    </span>
                  </div>
                  <ConfidenceBar value={Number(selectedRing.burst_ratio)} color="var(--risk-high)" />
                </div>
              )}
              <div className="stack" style={{ gap: 6 }}>
                <FanBar
                  label="Fan-in"
                  count={selectedRing.fan_in_count}
                  amount={Number(selectedRing.fan_in_amount)}
                  max={Math.max(Number(selectedRing.fan_in_amount), Number(selectedRing.fan_out_amount), 1)}
                  color="var(--ok)"
                />
                <FanBar
                  label="Fan-out"
                  count={selectedRing.fan_out_count}
                  amount={Number(selectedRing.fan_out_amount)}
                  max={Math.max(Number(selectedRing.fan_in_amount), Number(selectedRing.fan_out_amount), 1)}
                  color="var(--decision)"
                />
              </div>
            </div>
          )}
        </Panel>

        <Panel title="Corridor metrics" meta="prediction provenance">
          {!prediction && <EmptyState title="No prediction yet" />}
          {prediction && (
            <div className="stack" style={{ gap: 8, fontSize: "0.8rem" }}>
              <div className="row between">
                <span className="dim">Bearing</span>
                <span className="tabular">{prediction.exit_vector.bearing_deg.toFixed(1)}°</span>
              </div>
              <div className="row between">
                <span className="dim">Distance band</span>
                <span className="tabular">
                  {prediction.exit_vector.distance_range_km[0].toFixed(1)}–{prediction.exit_vector.distance_range_km[1].toFixed(1)} km
                </span>
              </div>
              <div className="row between">
                <span className="dim">Confidence cone</span>
                <span className="tabular">{prediction.exit_vector.confidence_cone_deg.toFixed(0)}°</span>
              </div>
              <div className="row between">
                <span className="dim">Exit channel type</span>
                <span>{prediction.exit_vector.exit_channel_type.replace(/_/g, " ")}</span>
              </div>
              <div className="row between">
                <span className="dim">Candidate exits scored</span>
                <span className="tabular">{prediction.ranked_locations?.length ?? 0}</span>
              </div>
              <hr className="divider" style={{ margin: "4px 0" }} />
              <div className="row between">
                <span className="dim">Corridor model</span>
                <span className="mono" style={{ fontSize: "0.72rem" }}>
                  {prediction.model_versions.corridor ?? "—"}
                </span>
              </div>
              <p className="hint">{prediction.disclaimer}</p>
            </div>
          )}
        </Panel>

        <Panel title="Ring evidence" meta="entity-sharing & observed exits">
          {!selectedRing && <EmptyState title="No ring selected" />}
          {selectedRing && (
            <div className="stack" style={{ gap: 10 }}>
              {selectedRing.geographic_spread_km != null && (
                <div className="row between">
                  <span className="dim" style={{ fontSize: "0.8rem" }}>
                    Geographic spread
                  </span>
                  <span className="tabular">{Number(selectedRing.geographic_spread_km).toFixed(1)} km</span>
                </div>
              )}
              <div className="row wrap" style={{ gap: 6 }}>
                <Pill>{selectedRing.device_count} shared device</Pill>
                <Pill>{selectedRing.ip_count} shared IP</Pill>
                <Pill>{selectedRing.phone_count} shared phone</Pill>
                <Pill>{selectedRing.vpa_count} shared VPA</Pill>
              </div>
              <hr className="divider" style={{ margin: "2px 0" }} />
              <div>
                <span className="dim" style={{ fontSize: "0.75rem" }}>
                  Observed exit channels (real, from members' own past transactions)
                </span>
                {selectedRing.exit_channel_ids.length === 0 ? (
                  <p className="hint" style={{ marginTop: 6 }}>
                    None yet — no ring member has an observed <span className="mono">EXITED_VIA</span> edge.
                  </p>
                ) : (
                  <>
                    <div className="row wrap mono" style={{ gap: 6, marginTop: 6 }}>
                      {selectedRing.exit_channel_ids.map((id) => (
                        <span key={id} className="pill pill-ok" style={{ fontSize: "0.68rem" }}>
                          {id.slice(0, 8)}…
                        </span>
                      ))}
                    </div>
                    <p className="hint" style={{ marginTop: 6 }}>
                      Distinct from the predicted candidates on the map above — these already happened. This endpoint does not expose
                      their coordinates, so they are listed here by ID only, not plotted.
                    </p>
                  </>
                )}
              </div>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}

function FanBar({ label, count, amount, max, color }: { label: string; count: number; amount: number; max: number; color: string }) {
  const pct = Math.max(0, Math.min(1, amount / max)) * 100;
  return (
    <div className="row" style={{ gap: 8 }}>
      <span className="dim" style={{ fontSize: "0.7rem", width: 46 }}>
        {label}
      </span>
      <div style={{ flex: 1, height: 6, borderRadius: 999, background: "var(--bg-3)" }}>
        <div style={{ height: "100%", width: `${pct}%`, borderRadius: 999, background: color, transition: "width var(--duration-reveal) var(--ease-standard)" }} />
      </div>
      <span className="tabular dim" style={{ fontSize: "0.7rem", width: 100, textAlign: "right" }}>
        {count} · ₹{amount.toLocaleString("en-IN")}
      </span>
    </div>
  );
}
