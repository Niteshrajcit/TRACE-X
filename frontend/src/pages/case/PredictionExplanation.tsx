import { useEffect, useMemo, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { cellToLatLng } from "h3-js";
import { ArrowRight, ArrowUpRight, CircleDot, Compass, Gauge, Info, ListOrdered, Route, Target } from "lucide-react";
import { getComplaintExplanation, getRiskField } from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { useCase } from "../../context/CaseContext";
import { useInvestigationFocus } from "../../context/InvestigationFocusContext";
import { useApi } from "../../hooks/useApi";
import { RiskMap, type MapMarker } from "../../components/map/RiskMap";
import { BearingCompass, ConfidenceBar, ProbabilityRing, TimeWindowBar } from "../../components/ui/charts";
import { EmptyState, ErrorBlock, LoadingBlock, Panel, Pill } from "../../components/ui/primitives";
import type { RankedLocation, TopFactor } from "../../types/domain";

/**
 * F6 — Prediction + Explanation. The primary frontend demonstration of the
 * Predictive Analytics Engine (SIH deliverable A). Story, top to bottom:
 * WHAT WILL LIKELY HAPPEN -> WHERE -> WHEN -> HOW CONFIDENT -> WHY -> WHAT
 * REAL EVIDENCE. Every number traces to GET /v1/complaints/{id}/prediction
 * or /explanation. Nothing here is fabricated - where the backend has a
 * real gap (no ranked_locations yet, no feature snapshot, no comparable
 * case), this page says so instead of inventing one.
 */

// Same disclosed, frontend-only convenience as F4's coneConfidenceLabel -
// narrower cone = the corridor model is more certain about direction, not
// a backend-calibrated confidence score.
function coneConfidenceLabel(coneDeg: number): { label: string; tone: "ok" | "decision" | "neutral" } {
  if (coneDeg <= 30) return { label: "Narrow — higher confidence", tone: "ok" };
  if (coneDeg <= 60) return { label: "Moderate", tone: "decision" };
  return { label: "Wide — lower confidence", tone: "neutral" };
}

// The backend contract is exactly {feature, weight, direction}, direction
// being "increases_risk" | "decreases_risk" | (future/other real string).
// The previous version of this page collapsed anything that wasn't
// literally "increases_risk" into "decreases risk" - silently reinterpreting
// a value it didn't recognize. This never does that: an unrecognized real
// direction is shown as-is, honestly, in a neutral tone.
function factorPresentation(direction: TopFactor["direction"]): { label: string; tone: "decision" | "ok" | "neutral"; barColor: string } {
  if (direction === "increases_risk") return { label: "increases risk", tone: "decision", barColor: "var(--risk-high)" };
  if (direction === "decreases_risk") return { label: "decreases risk", tone: "ok", barColor: "var(--ok)" };
  return { label: direction.replace(/_/g, " "), tone: "neutral", barColor: "var(--text-2)" };
}

function shortId(id: string): string {
  return id.length > 10 ? `${id.slice(0, 6)}…${id.slice(-4)}` : id;
}

export function PredictionExplanation() {
  const { auth } = useAuth();
  const { complaint } = useCase();
  const focus = useInvestigationFocus();
  const navigate = useNavigate();
  const selectedChannel = focus.selectedExitChannelId;
  const prediction = complaint.latest_prediction;

  const explanationState = useApi(
    () =>
      prediction
        ? getComplaintExplanation(auth!.token, complaint.complaint_id, {
            predictionId: prediction.prediction_id,
            exitChannelId: selectedChannel ?? undefined,
          })
        : Promise.resolve(null),
    [auth!.token, complaint.complaint_id, prediction?.prediction_id, selectedChannel]
  );

  const riskFieldState = useApi(
    () => (complaint.jurisdiction_id ? getRiskField(auth!.token, complaint.jurisdiction_id) : Promise.resolve(null)),
    [auth!.token, complaint.jurisdiction_id]
  );

  const ranked = useMemo(
    () => (prediction?.ranked_locations ? [...prediction.ranked_locations].sort((a, b) => b.probability - a.probability) : []),
    [prediction]
  );
  const topCandidate: RankedLocation | null = ranked[0] ?? null;

  // Default to the top-ranked real candidate on first arrival, exactly
  // like F4's ring default - never fights an explicit deselection, only
  // runs once.
  const didAutoSelect = useRef(false);
  useEffect(() => {
    if (!didAutoSelect.current && !focus.selectedExitChannelId && topCandidate) {
      didAutoSelect.current = true;
      focus.selectExitChannel(topCandidate.exit_channel_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topCandidate]);

  const selectedCandidate = ranked.find((r) => r.exit_channel_id === selectedChannel) ?? topCandidate;

  const candidateMarkers: MapMarker[] = useMemo(
    () =>
      ranked.map((loc, i) => {
        const [lat, lon] = cellToLatLng(loc.h3_cell);
        return {
          id: loc.exit_channel_id,
          lat,
          lon,
          kind: "exit_channel",
          label: loc.channel_type,
          rank: i + 1,
          highlighted: selectedChannel === loc.exit_channel_id,
          onClick: () => focus.selectExitChannel(loc.exit_channel_id),
        };
      }),
    [ranked, selectedChannel, focus.selectExitChannel]
  );

  const originMarkers: MapMarker[] =
    complaint.location_lat != null && complaint.location_lon != null
      ? [{ id: "incident", lat: complaint.location_lat, lon: complaint.location_lon, kind: "victim", label: "Known origin — observed" }]
      : [];

  // A real derived clock window: the backend's own generated_at timestamp
  // plus its own minute offsets - never an invented precision. Shown
  // alongside the raw relative range, not instead of it.
  const absoluteWindow = useMemo(() => {
    if (!prediction || !selectedCandidate) return null;
    const base = new Date(prediction.generated_at).getTime();
    const [loMin, hiMin] = selectedCandidate.time_window_min;
    return {
      from: new Date(base + loMin * 60_000),
      to: new Date(base + hiMin * 60_000),
    };
  }, [prediction, selectedCandidate]);

  const confidence = prediction ? coneConfidenceLabel(prediction.exit_vector.confidence_cone_deg) : null;
  const explanation = explanationState.data;
  const predictedExitId = explanation?.graph_path?.predicted_exit_channel_id ?? null;

  if (!prediction) {
    return (
      <Panel>
        <EmptyState title="No prediction available" description="This case has no corridor prediction yet — intelligence may still be processing." />
      </Panel>
    );
  }

  return (
    <div className="stack">
      {/* ---------------------------------------------------------------- */}
      {/* Hero: prediction status | confidence & time window               */}
      {/* ---------------------------------------------------------------- */}
      <div className="grid grid-cols-2">
        <Panel
          title={
            <span className="row" style={{ gap: 8 }}>
              <Target size={15} style={{ color: "var(--decision)" }} />
              Predicted exit
            </span>
          }
          meta={`generated ${new Date(prediction.generated_at).toLocaleString()}`}
        >
          <div className="stack" style={{ gap: 12 }}>
            <div className="row wrap" style={{ gap: 8 }}>
              <Pill tone="decision">MODEL PREDICTION</Pill>
              <span className="dim" style={{ fontSize: "0.78rem" }}>
                not a confirmed location
              </span>
            </div>
            <h2 style={{ margin: 0, textTransform: "capitalize" }}>{prediction.exit_vector.exit_channel_type.replace(/_/g, " ")}</h2>
            {topCandidate ? (
              <p className="hint">
                Top-ranked of {ranked.length} candidate{ranked.length === 1 ? "" : "s"} — H3 cell{" "}
                <span className="mono">{topCandidate.h3_cell}</span>
              </p>
            ) : (
              <p className="hint">
                Exit-channel scoring hasn't run for this prediction yet — this is the corridor-stage estimate only (direction and
                distance band, below).
              </p>
            )}
            <div className="row wrap" style={{ gap: 6 }}>
              <Pill>ring model {prediction.model_versions.ring ?? "—"}</Pill>
              <Pill>corridor {prediction.model_versions.corridor ?? "—"}</Pill>
              <Pill>exit-channel {prediction.model_versions.exit_channel ?? "—"}</Pill>
              <Pill>time-window {prediction.model_versions.time_window ?? "—"}</Pill>
            </div>
          </div>
        </Panel>

        <Panel
          title={
            <span className="row" style={{ gap: 8 }}>
              <Gauge size={15} style={{ color: "var(--accent)" }} />
              Confidence &amp; time window
            </span>
          }
        >
          <div className="row" style={{ gap: 20, alignItems: "center", flexWrap: "wrap" }}>
            {selectedCandidate ? (
              <ProbabilityRing
                value={selectedCandidate.probability}
                size={96}
                color="var(--decision)"
                label={`${(selectedCandidate.probability * 100).toFixed(1)}%`}
              />
            ) : (
              <BearingCompass bearingDeg={prediction.exit_vector.bearing_deg} coneDeg={prediction.exit_vector.confidence_cone_deg} size={96} />
            )}
            <div className="stack" style={{ gap: 8, flex: 1, minWidth: 200 }}>
              {selectedCandidate ? (
                <>
                  <div>
                    <span className="dim" style={{ fontSize: "0.75rem" }}>
                      Estimated probability
                    </span>
                    <div className="hero-number decision-text" style={{ fontSize: "var(--text-3xl)" }}>
                      {(selectedCandidate.probability * 100).toFixed(1)}
                      <span style={{ fontSize: "var(--text-lg)", fontWeight: 600 }}>%</span>
                    </div>
                  </div>
                  <div className="row between">
                    <span className="dim" style={{ fontSize: "0.75rem" }}>
                      Confidence interval
                    </span>
                    <span className="tabular">
                      {(selectedCandidate.confidence_interval[0] * 100).toFixed(0)}–{(selectedCandidate.confidence_interval[1] * 100).toFixed(0)}%
                    </span>
                  </div>
                </>
              ) : (
                confidence && (
                  <div className="row between">
                    <span className="dim" style={{ fontSize: "0.75rem" }}>
                      Confidence cone
                    </span>
                    <Pill tone={confidence.tone}>{prediction.exit_vector.confidence_cone_deg.toFixed(0)}° — {confidence.label}</Pill>
                  </div>
                )
              )}
            </div>
          </div>

          {selectedCandidate && (
            <div className="stack" style={{ gap: 6, marginTop: 16 }}>
              <div className="row between">
                <span className="dim" style={{ fontSize: "0.75rem" }}>
                  Predicted window
                </span>
                <span className="tabular" style={{ fontSize: "0.75rem" }}>
                  {selectedCandidate.time_window_min[0]}–{selectedCandidate.time_window_min[1]} min from generation
                </span>
              </div>
              <TimeWindowBar rangeMin={selectedCandidate.time_window_min} />
              {absoluteWindow && (
                <p className="hint">
                  Derived clock estimate: <strong>{absoluteWindow.from.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</strong> –{" "}
                  <strong>{absoluteWindow.to.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</strong> (generation time + the
                  backend's own window — never invented precision)
                </p>
              )}
            </div>
          )}
          <p className="hint" style={{ marginTop: 10 }}>{prediction.disclaimer}</p>
        </Panel>
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Exit prediction map - dominant                                   */}
      {/* ---------------------------------------------------------------- */}
      <AnimatePresence mode="wait">
        <motion.div
          key={`${prediction.prediction_id}::${selectedChannel ?? "top"}`}
          initial={{ opacity: 0, scale: 0.99 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.45, ease: [0.4, 0, 0.2, 1] }}
        >
          <Panel
            className="panel-hero"
            title={
              <span className="row" style={{ gap: 8 }}>
                <Compass size={15} style={{ color: "var(--decision)" }} />
                Exit prediction map
              </span>
            }
            meta="observed origin · predicted corridor · ranked candidates"
          >
            {riskFieldState.loading && <LoadingBlock label="Loading jurisdiction context…" />}
            {riskFieldState.error && <ErrorBlock message={riskFieldState.error} onRetry={riskFieldState.reload} />}
            {!riskFieldState.loading && !riskFieldState.error && (
              <RiskMap
                cells={riskFieldState.data?.h3_cells ?? []}
                height={560}
                corridor={
                  complaint.location_lat != null && complaint.location_lon != null
                    ? {
                        fromLat: complaint.location_lat,
                        fromLon: complaint.location_lon,
                        bearingDeg: prediction.exit_vector.bearing_deg,
                        distanceKm: prediction.exit_vector.distance_range_km as [number, number],
                        coneDeg: prediction.exit_vector.confidence_cone_deg,
                      }
                    : null
                }
                markers={[...originMarkers, ...candidateMarkers]}
              />
            )}
            {ranked.length === 0 && (
              <p className="hint" style={{ marginTop: 8 }}>
                No ranked candidate exit channels yet — the map shows the predicted corridor direction only.
              </p>
            )}
          </Panel>
        </motion.div>
      </AnimatePresence>

      {/* ---------------------------------------------------------------- */}
      {/* Ranked candidates | Why the model believes this                  */}
      {/* ---------------------------------------------------------------- */}
      <div className="grid grid-cols-2">
        <Panel
          title={
            <span className="row" style={{ gap: 8 }}>
              <ListOrdered size={15} style={{ color: "var(--accent)" }} />
              Ranked exit candidates
            </span>
          }
          meta={ranked.length ? `${ranked.length} candidate(s)` : undefined}
        >
          {ranked.length === 0 && (
            <EmptyState
              title="Exit-channel ranking not available"
              description="This prediction only covers the corridor stage — location/time-window scoring has not run for it yet."
            />
          )}
          {ranked.length > 0 && (
            <div className="stack" style={{ gap: 4 }}>
              {ranked.map((loc, i) => {
                const isTop = i === 0;
                const isSelected = selectedChannel === loc.exit_channel_id;
                return (
                  <motion.div
                    key={loc.exit_channel_id}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.28, delay: Math.min(i, 6) * 0.05, ease: [0.4, 0, 0.2, 1] }}
                    role="button"
                    tabIndex={0}
                    onClick={() => focus.selectExitChannel(loc.exit_channel_id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") focus.selectExitChannel(loc.exit_channel_id);
                    }}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: isTop ? 18 : 12,
                      padding: isTop ? "16px 14px" : "8px 10px",
                      borderRadius: "var(--radius)",
                      cursor: "pointer",
                      background: isSelected ? (isTop ? "color-mix(in srgb, var(--decision) 10%, var(--bg-2))" : "var(--bg-2)") : "transparent",
                      border: isTop ? "1px solid color-mix(in srgb, var(--decision) 35%, var(--border-subtle))" : "1px solid transparent",
                    }}
                  >
                    <span
                      className="tabular"
                      style={{
                        fontSize: isTop ? "1.4rem" : "0.85rem",
                        fontWeight: 700,
                        color: isTop ? "var(--decision)" : "var(--text-3)",
                        width: isTop ? 32 : 20,
                        flexShrink: 0,
                        fontFamily: "var(--font-mono)",
                      }}
                    >
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <ProbabilityRing value={loc.probability} size={isTop ? 68 : 38} stroke={isTop ? 8 : 5} color={isTop ? "var(--decision)" : "var(--accent)"} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="row between">
                        <span style={{ fontWeight: isTop ? 700 : 500, fontSize: isTop ? "0.95rem" : "0.8rem", textTransform: "capitalize" }}>
                          {loc.channel_type.replace(/_/g, " ")}
                        </span>
                        <span className="mono dim" style={{ fontSize: "0.68rem" }}>
                          {shortId(loc.h3_cell)}
                        </span>
                      </div>
                      {isTop && (
                        <div style={{ marginTop: 8 }}>
                          <TimeWindowBar rangeMin={loc.time_window_min} />
                        </div>
                      )}
                      {!isTop && (
                        <span className="dim" style={{ fontSize: "0.7rem" }}>
                          {loc.time_window_min[0]}–{loc.time_window_min[1]} min
                        </span>
                      )}
                    </div>
                  </motion.div>
                );
              })}
            </div>
          )}
        </Panel>

        <Panel
          title={
            <span className="row" style={{ gap: 8 }}>
              <Info size={15} style={{ color: "var(--accent)" }} />
              Why the model believes this
            </span>
          }
          meta={selectedChannel ? "for selected candidate" : "top-ranked candidate"}
        >
          {explanationState.loading && <LoadingBlock label="Generating explanation…" />}
          {explanationState.error && <ErrorBlock message={explanationState.error} onRetry={explanationState.reload} />}
          {!explanationState.loading && !explanationState.error && explanation && !explanation.available && (
            <EmptyState title="Explanation unavailable" description={explanation.reason ?? "This prediction predates explanation persistence."} />
          )}
          {!explanationState.loading && !explanationState.error && explanation?.available && (
            <>
              {explanation.top_factors.length === 0 && <EmptyState title="No factors reported" description="This explanation has no attributed factors." />}
              <div className="stack" style={{ gap: 12 }}>
                {explanation.top_factors.map((f, i) => {
                  const p = factorPresentation(f.direction);
                  return (
                    <motion.div
                      key={f.feature}
                      initial={{ opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.25, delay: Math.min(i, 8) * 0.04 }}
                    >
                      <div className="row between" style={{ marginBottom: 4 }}>
                        <span style={{ fontSize: "0.82rem", fontWeight: 500, textTransform: "capitalize" }}>{f.feature.replace(/_/g, " ")}</span>
                        <Pill tone={p.tone}>
                          {p.label} · {f.weight.toFixed(2)}
                        </Pill>
                      </div>
                      <ConfidenceBar value={Math.min(1, Math.abs(f.weight) / 3)} color={p.barColor} />
                    </motion.div>
                  );
                })}
              </div>
            </>
          )}
        </Panel>
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Real graph path                                                  */}
      {/* ---------------------------------------------------------------- */}
      <Panel
        title={
          <span className="row" style={{ gap: 8 }}>
            <Route size={15} style={{ color: "var(--accent)" }} />
            Real graph path
          </span>
        }
        meta={explanation?.graph_path ? (explanation.graph_path.path_complete ? "complete" : "partial") : undefined}
      >
        {(!explanation?.graph_path || explanation.graph_path.real_path.length === 0) && (
          <EmptyState title="No verified path yet" description="No Neo4j-confirmed transfer chain is available for this explanation." />
        )}
        {explanation?.graph_path && explanation.graph_path.real_path.length > 0 && (
          <div className="stack" style={{ gap: 10 }}>
            <div className="row wrap" style={{ gap: 0, alignItems: "center" }}>
              {explanation.graph_path.real_path.map((accountId, i) => (
                <motion.div
                  key={accountId}
                  className="row"
                  style={{ gap: 0, alignItems: "center" }}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.25, delay: i * 0.06 }}
                >
                  {i > 0 && <ArrowRight size={14} style={{ color: "var(--accent)", margin: "0 4px", flexShrink: 0 }} />}
                  <button
                    className="pill pill-accent"
                    style={{ fontFamily: "var(--font-mono)", cursor: "pointer", border: focus.selectedAccountId === accountId ? "1px solid var(--accent-strong)" : undefined }}
                    onClick={() => focus.selectAccount(accountId)}
                    title={i === 0 ? "Victim account (observed)" : "Real transfer hop (Neo4j-verified)"}
                  >
                    <CircleDot size={10} />
                    {i === 0 ? "Victim" : `Hop ${i}`} · {shortId(accountId)}
                  </button>
                </motion.div>
              ))}
              {predictedExitId && (
                <motion.div
                  className="row"
                  style={{ gap: 0, alignItems: "center" }}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.25, delay: explanation.graph_path.real_path.length * 0.06 }}
                >
                  <span
                    style={{
                      display: "inline-block",
                      width: 28,
                      height: 0,
                      borderTop: "2px dashed var(--decision)",
                      margin: "0 4px",
                    }}
                  />
                  <span className="pill pill-decision" style={{ fontFamily: "var(--font-mono)" }}>
                    <Target size={10} />
                    Predicted exit · {shortId(predictedExitId)}
                  </span>
                </motion.div>
              )}
            </div>
            <p className="hint" style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
              <Info size={12} style={{ marginTop: 2, flexShrink: 0, color: "var(--accent)" }} />
              <span>
                Solid arrows are a real, Neo4j-verified transfer chain — <strong>observed</strong>. The dashed connector to the predicted
                exit is never merged into the real path — it hasn't happened, and this graph never invents an edge implying that it has.
                {!explanation.graph_path.path_complete && " This chain is partial — not every hop between the victim and the last known account is confirmed."}
              </span>
            </p>
          </div>
        )}
      </Panel>

      {/* ---------------------------------------------------------------- */}
      {/* Investigative interpretation                                     */}
      {/* ---------------------------------------------------------------- */}
      <Panel title="Investigative interpretation">
        {explanationState.loading && <LoadingBlock label="Generating explanation…" />}
        {!explanationState.loading && explanation?.available && (
          <div className="stack" style={{ gap: 16 }}>
            {explanation.plain_language && (
              <blockquote
                style={{
                  margin: 0,
                  padding: "14px 18px",
                  borderLeft: "3px solid var(--decision)",
                  background: "var(--bg-2)",
                  borderRadius: "var(--radius-sm)",
                  fontSize: "0.95rem",
                  lineHeight: 1.6,
                }}
              >
                {explanation.plain_language}
              </blockquote>
            )}

            <div className="row between wrap" style={{ gap: 12 }}>
              <span className="row" style={{ gap: 6, fontSize: "0.8rem" }}>
                <span className="dim">Explanation reproducibility</span>
                <Pill tone="ok">SNAPSHOT AVAILABLE</Pill>
              </span>
              <span className="hint">Derived from this exact prediction's persisted feature snapshot — the same values used to score it, not recomputed.</span>
            </div>

            <div>
              <span className="dim" style={{ fontSize: "0.78rem" }}>
                Comparable cases
              </span>
              {explanation.comparable_cases.length === 0 ? (
                <p className="hint" style={{ marginTop: 6 }}>
                  None yet — honestly empty. No resolved case with a similar real feature vector exists in this system yet.
                </p>
              ) : (
                <div className="stack" style={{ gap: 6, marginTop: 6 }}>
                  {explanation.comparable_cases.map((c) => (
                    <div key={c.complaint_id} className="row between" style={{ fontSize: "0.82rem" }}>
                      <span>{c.summary}</span>
                      <span className="tabular dim">{(c.similarity_score * 100).toFixed(0)}% similar</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
        {!explanationState.loading && explanation && !explanation.available && (
          <p className="hint">
            Explanation snapshot unavailable for this prediction — {explanation.reason ?? "no feature snapshot was persisted."}
          </p>
        )}

        <hr className="divider" />
        <div className="row wrap" style={{ gap: 10 }}>
          {/* Absolute, not navigate("intervention") - see RingsCorridors.tsx's
              identical comment: a bare relative string resolved incorrectly
              in this app and landed on the wildcard redirect, found via
              live browser verification during F7. */}
          <button className="btn btn-decision" onClick={() => navigate(`/cases/${complaint.complaint_id}/intervention`)}>
            Continue to Intervention &amp; Approval
            <ArrowUpRight size={14} />
          </button>
          <button className="btn btn-ghost" onClick={() => navigate("/risk-intelligence")}>
            Open jurisdiction Risk Heatmap
            <ArrowUpRight size={14} />
          </button>
        </div>
      </Panel>
    </div>
  );
}
