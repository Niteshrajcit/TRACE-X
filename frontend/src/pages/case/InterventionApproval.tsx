import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { cellToLatLng } from "h3-js";
import {
  ArrowUpRight,
  CheckCircle2,
  Clock,
  Info,
  ListChecks,
  Milestone,
  Navigation,
  Radio,
  Send,
  ShieldAlert,
  Sparkles,
  Target,
  Users,
  XCircle,
} from "lucide-react";
import { ApiError, decideDeployment, getRiskField, optimizeDeployment } from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { useCase } from "../../context/CaseContext";
import { useLiveEventsContext } from "../../context/LiveEventsContext";
import { useApi } from "../../hooks/useApi";
import { RiskMap, type MapMarker } from "../../components/map/RiskMap";
import { CoverageBar } from "../../components/ui/charts";
import { EmptyState, ErrorBlock, LoadingBlock, Panel, Pill } from "../../components/ui/primitives";
import type { DeploymentHistoryEntry, LatLon, LiveEvent } from "../../types/domain";

/**
 * F7 — Intervention + Approval. The law-enforcement decision workspace
 * (SIH deliverable C). Story: PREDICTION -> AVAILABLE RESOURCES ->
 * OPTIMIZED COVERAGE -> RECOMMENDED DEPLOYMENT -> HUMAN APPROVAL -> ACTION.
 * Every value traces to POST .../optimize-deployment, POST
 * .../deployments/{id}/decision, or GET .../complaints/{id}. Nothing here
 * is fabricated - the optimizer is a classical algorithm operating on a
 * real prediction, not a second ML model, and every visual says so.
 */

// app/graph/optimizer.py::determine_mode - the mode is auto-selected
// server-side from the top-ranked exit channel's intervention_action_type.
function modeFor(exitChannelType: string): "coverage_maximization" | "resource_allocation" {
  return exitChannelType === "atm_cash" ? "coverage_maximization" : "resource_allocation";
}

const STATUS_TONE: Record<DeploymentHistoryEntry["status"], "neutral" | "decision" | "ok"> = {
  proposed: "decision",
  approved: "ok",
  rejected: "neutral",
};

// --- The real, honest shape of a POST .../optimize-deployment response ---
// backend/app/graph/schemas.py::OptimizeDeploymentResponse declares
// `assignment: list[dict]` - genuinely polymorphic per mode
// (API_CONTRACT.md §4). The shared frontend type (types/domain.ts's
// DeploymentAssignment) only models the coverage_maximization shape - it
// was never exercised for resource_allocation mode by any existing page,
// so that gap was silent until now. Corrected locally here, not by
// touching the shared type file for every other page's sake.
interface CoverageAssignmentRow {
  team_id: string;
  exit_channel_id: string;
  expected_coverage: number;
  travel_time_min: number;
}
interface AllocationAssignmentRow {
  exit_channel_id: string;
  priority_rank: number;
  expected_value: number;
  hazard_at_request_time: number;
}
type AssignmentRow = CoverageAssignmentRow | AllocationAssignmentRow;
interface RealOptimizeResponse {
  deployment_id: string;
  optimizer_mode: "coverage_maximization" | "resource_allocation";
  assignment: AssignmentRow[];
  expected_coverage_total: number;
  naive_baseline_coverage: number;
}
function isCoverageRow(r: AssignmentRow): r is CoverageAssignmentRow {
  return "team_id" in r;
}

interface FreshResult {
  result: RealOptimizeResponse;
  // The exact real coordinates the investigator entered for THIS run -
  // the optimizer response never echoes team locations back, so this is
  // captured client-side at generation time, not derived after the fact.
  teamLocationsUsed: LatLon[] | null;
}

const DEPLOYMENT_EVENT_TYPES = new Set([
  "intervention.recommended",
  "approval.required",
  "intervention.approved",
  "intervention.rejected",
]);
function isDeploymentEvent(
  e: LiveEvent
): e is Extract<LiveEvent, { complaint_id: string; deployment_id: string }> {
  return DEPLOYMENT_EVENT_TYPES.has(e.type) && "deployment_id" in e;
}

function shortId(id: string): string {
  return id.length > 10 ? `${id.slice(0, 8)}…` : id;
}

function TeamLocationsInput({
  teamCount,
  setTeamCount,
  locations,
  setLocations,
  incidentLat,
  incidentLon,
}: {
  teamCount: number;
  setTeamCount: (n: number) => void;
  locations: LatLon[];
  setLocations: (locs: LatLon[]) => void;
  incidentLat: number | null;
  incidentLon: number | null;
}) {
  function resize(n: number) {
    const bounded = Math.max(1, Math.min(20, n || 1));
    setTeamCount(bounded);
    const next = [...locations];
    while (next.length < bounded) next.push({ lat: NaN, lon: NaN });
    setLocations(next.slice(0, bounded));
  }

  function update(i: number, field: "lat" | "lon", value: string) {
    const next = [...locations];
    next[i] = { ...next[i], [field]: Number(value) };
    setLocations(next);
  }

  return (
    <div className="stack" style={{ gap: 10 }}>
      <div>
        <span className="dim" style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
          Available teams
        </span>
        <div className="row" style={{ gap: 8, marginTop: 4 }}>
          <input type="number" min={1} max={20} value={teamCount} onChange={(e) => resize(Number(e.target.value))} style={{ width: 70 }} />
          {incidentLat != null && incidentLon != null && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setLocations(Array.from({ length: teamCount }, () => ({ lat: incidentLat, lon: incidentLon })))}
            >
              Start all at incident location
            </button>
          )}
        </div>
      </div>
      <div>
        <span className="dim" style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
          Team locations — your input, never assumed
        </span>
        <div className="stack" style={{ gap: 6, marginTop: 4 }}>
          {locations.map((loc, i) => (
            <div key={i} className="row" style={{ gap: 6 }}>
              <span className="dim mono" style={{ fontSize: "0.72rem", width: 52 }}>
                team-{i + 1}
              </span>
              <input
                type="number"
                step="any"
                placeholder="lat"
                value={Number.isNaN(loc.lat) ? "" : loc.lat}
                onChange={(e) => update(i, "lat", e.target.value)}
                style={{ width: 110 }}
              />
              <input
                type="number"
                step="any"
                placeholder="lon"
                value={Number.isNaN(loc.lon) ? "" : loc.lon}
                onChange={(e) => update(i, "lon", e.target.value)}
                style={{ width: 110 }}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function DecisionForm({
  deploymentId,
  onDecided,
}: {
  deploymentId: string;
  onDecided: (decision: "approved" | "rejected", justification: string) => void;
}) {
  const { auth } = useAuth();
  const [justification, setJustification] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function decide(decision: "approved" | "rejected") {
    if (justification.trim().length < 3) {
      setError("A short justification is required before a decision can be recorded.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      // Never assume success before this resolves - the state machine
      // only advances after the backend actually confirms it.
      await decideDeployment(auth!.token, deploymentId, { decision, justification: justification.trim() });
      onDecided(decision, justification.trim());
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status} — ${err.message}` : err instanceof Error ? err.message : "Could not record decision.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ gap: 10 }}>
      <span className="dim" style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
        Human decision required — nothing below happens automatically
      </span>
      <textarea
        rows={2}
        placeholder="Justification for approving or rejecting this recommendation…"
        value={justification}
        onChange={(e) => setJustification(e.target.value)}
      />
      {error && <p className="error-text">{error}</p>}
      <div className="row" style={{ gap: 8 }}>
        <button className="btn btn-decision" disabled={busy} onClick={() => decide("approved")}>
          <CheckCircle2 size={14} />
          {busy ? "Recording…" : "Approve deployment"}
        </button>
        <button className="btn btn-danger" disabled={busy} onClick={() => decide("rejected")}>
          <XCircle size={14} />
          Reject
        </button>
      </div>
    </div>
  );
}

export function InterventionApproval() {
  const { auth } = useAuth();
  const { complaint, reloadComplaint } = useCase();
  const { keyedEvents } = useLiveEventsContext();
  const navigate = useNavigate();

  const [teamCount, setTeamCount] = useState(2);
  const [teamLocations, setTeamLocations] = useState<LatLon[]>([
    { lat: NaN, lon: NaN },
    { lat: NaN, lon: NaN },
  ]);
  const [requestSlotCount, setRequestSlotCount] = useState(2);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [freshResults, setFreshResults] = useState<Record<string, FreshResult>>({});
  const [sessionDecisions, setSessionDecisions] = useState<Record<string, { decision: "approved" | "rejected"; justification: string }>>({});
  const [focusedId, setFocusedId] = useState<string | null>(null);

  const canDecide = auth!.role === "investigator" || auth!.role === "supervisor";
  const prediction = complaint.latest_prediction;
  const mode = prediction ? modeFor(prediction.exit_vector.exit_channel_type) : null;
  const history = complaint.deployment_history;

  const riskFieldState = useApi(
    () => (complaint.jurisdiction_id ? getRiskField(auth!.token, complaint.jurisdiction_id) : Promise.resolve(null)),
    [auth!.token, complaint.jurisdiction_id]
  );

  // Default focus, once: an actionable proposed deployment first (what
  // needs a decision right now), else whichever the backend lists first.
  // Deliberately a one-time ref-guarded init (same pattern as F4/F6's
  // auto-select), NOT a reactive effect keyed on [history, focusedId] -
  // a reactive version raced with handleGenerate below: it could fire on
  // the render where focusedId had already been set to a freshly-generated
  // deployment_id but reloadComplaint()'s fetch hadn't resolved yet, see
  // that id wasn't in the still-stale `history`, and stomp focusedId back
  // to an old one - desyncing it from `freshResults`' key and silently
  // losing the just-cached assignment detail. Running once, only while
  // focusedId is still null, can't race an explicit focus change.
  const didAutoFocus = useRef(false);
  useEffect(() => {
    if (didAutoFocus.current || focusedId || history.length === 0) return;
    didAutoFocus.current = true;
    const proposed = history.find((d) => d.status === "proposed");
    setFocusedId(proposed?.deployment_id ?? history[0].deployment_id);
  }, [history, focusedId]);

  const focused = history.find((d) => d.deployment_id === focusedId) ?? null;
  const fresh = focusedId ? freshResults[focusedId] : undefined;
  const sessionDecision = focusedId ? sessionDecisions[focusedId] : undefined;

  const teamLocationsValid = teamLocations.length === teamCount && teamLocations.every((l) => !Number.isNaN(l.lat) && !Number.isNaN(l.lon));
  const canGenerate = mode === "coverage_maximization" ? teamLocationsValid : mode === "resource_allocation" ? requestSlotCount > 0 : false;

  async function handleGenerate() {
    setGenerating(true);
    setGenError(null);
    try {
      const raw = await optimizeDeployment(
        auth!.token,
        complaint.complaint_id,
        mode === "coverage_maximization" ? { team_count: teamCount, team_locations: teamLocations } : { request_slot_count: requestSlotCount }
      );
      const result = raw as unknown as RealOptimizeResponse;
      setFreshResults((prev) => ({
        ...prev,
        [result.deployment_id]: { result, teamLocationsUsed: mode === "coverage_maximization" ? teamLocations : null },
      }));
      setFocusedId(result.deployment_id);
      reloadComplaint();
    } catch (err) {
      setGenError(err instanceof ApiError ? `${err.status} — ${err.message}` : err instanceof Error ? err.message : "Could not generate a recommendation.");
    } finally {
      setGenerating(false);
    }
  }

  function handleDecided(decision: "approved" | "rejected", justification: string) {
    if (focusedId) setSessionDecisions((prev) => ({ ...prev, [focusedId]: { decision, justification } }));
    reloadComplaint();
  }

  // -- Live events for this complaint's deployments -----------------------
  const liveDeploymentEvents = useMemo(
    () => keyedEvents.filter((k) => isDeploymentEvent(k.event) && k.event.complaint_id === complaint.complaint_id).slice(0, 6),
    [keyedEvents, complaint.complaint_id]
  );
  const lastProcessedKey = useRef(liveDeploymentEvents[0]?.key ?? 0);
  useEffect(() => {
    const newest = liveDeploymentEvents[0];
    if (newest && newest.key > lastProcessedKey.current) {
      lastProcessedKey.current = newest.key;
      reloadComplaint();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveDeploymentEvents]);

  // -- Map markers ----------------------------------------------------------
  const rankedLocations = prediction?.ranked_locations ?? [];
  const selectedTargetIds = useMemo(() => new Set(fresh?.result.assignment.map((a) => a.exit_channel_id) ?? []), [fresh]);

  const targetMarkers: MapMarker[] = useMemo(
    () =>
      rankedLocations.map((loc, i) => {
        const [lat, lon] = cellToLatLng(loc.h3_cell);
        return {
          id: loc.exit_channel_id,
          lat,
          lon,
          kind: "exit_channel",
          label: loc.channel_type,
          rank: i + 1,
          highlighted: selectedTargetIds.has(loc.exit_channel_id),
        };
      }),
    [rankedLocations, selectedTargetIds]
  );

  const teamMarkers: MapMarker[] = useMemo(
    () =>
      (fresh?.teamLocationsUsed ?? [])
        .filter((l) => !Number.isNaN(l.lat) && !Number.isNaN(l.lon))
        .map((loc, i) => ({ id: `team-${i + 1}`, lat: loc.lat, lon: loc.lon, kind: "team" as const, label: `Team ${i + 1} — investigator input` })),
    [fresh]
  );

  const originMarkers: MapMarker[] =
    complaint.location_lat != null && complaint.location_lon != null
      ? [{ id: "incident", lat: complaint.location_lat, lon: complaint.location_lon, kind: "victim", label: "Known origin — observed" }]
      : [];

  if (!prediction) {
    return (
      <Panel>
        <EmptyState title="No prediction available" description="Intervention optimization needs a real prediction to operate on — none exists for this case yet." />
      </Panel>
    );
  }

  return (
    <div className="stack">
      {/* ---------------------------------------------------------------- */}
      {/* Hero: prediction context | recommendation status                 */}
      {/* ---------------------------------------------------------------- */}
      <div className="grid grid-cols-2">
        <Panel
          title={
            <span className="row" style={{ gap: 8 }}>
              <Target size={15} style={{ color: "var(--decision)" }} />
              Prediction context
            </span>
          }
          actions={
            // Absolute, not navigate("prediction") - a bare relative
            // string resolves incorrectly in this app's route tree and
            // lands on the wildcard redirect (confirmed via live browser
            // testing this phase; the same fix applied to F4/F6's
            // equivalent cross-tab links).
            <button className="link-button" onClick={() => navigate(`/cases/${complaint.complaint_id}/prediction`)}>
              View full prediction <ArrowUpRight size={12} />
            </button>
          }
        >
          <div className="stack" style={{ gap: 10 }}>
            <div className="row wrap" style={{ gap: 8 }}>
              <Pill tone="decision">{mode?.replace(/_/g, " ")}</Pill>
              <span className="dim" style={{ fontSize: "0.78rem" }}>
                auto-selected by the top-ranked candidate's real action type
              </span>
            </div>
            {rankedLocations[0] ? (
              <p className="hint">
                Top candidate: <strong>{rankedLocations[0].channel_type.replace(/_/g, " ")}</strong> ·{" "}
                {(rankedLocations[0].probability * 100).toFixed(1)}% probability · <span className="mono">{rankedLocations[0].h3_cell}</span>
              </p>
            ) : (
              <p className="hint">Corridor-stage prediction only — bearing {prediction.exit_vector.bearing_deg.toFixed(0)}°, no ranked candidates yet.</p>
            )}
            <p className="hint" style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
              <Info size={12} style={{ marginTop: 2, flexShrink: 0, color: "var(--accent)" }} />
              <span>
                This stage is a classical optimization algorithm (greedy coverage-maximization / ranked resource allocation) operating on
                the prediction above — not a second machine-learning model.
              </span>
            </p>
          </div>
        </Panel>

        <Panel
          title={
            <span className="row" style={{ gap: 8 }}>
              <Milestone size={15} style={{ color: "var(--accent)" }} />
              Recommendation status
            </span>
          }
          meta={history.length ? `${history.length} recommendation(s)` : undefined}
        >
          {history.length === 0 && <EmptyState title="No recommendation generated yet" description="Use Resource constraints below to generate one." icon={<Send size={26} />} />}
          {history.length > 0 && (
            <div className="stack" style={{ gap: 12 }}>
              {history.length > 1 && (
                <div className="row wrap" style={{ gap: 6 }}>
                  {history.map((d) => (
                    <button
                      key={d.deployment_id}
                      className={`ring-chip${focusedId === d.deployment_id ? " active" : ""}`}
                      onClick={() => setFocusedId(d.deployment_id)}
                    >
                      {shortId(d.deployment_id)} · {d.status}
                    </button>
                  ))}
                </div>
              )}
              {focused && (
                <div className="row" style={{ gap: 6, alignItems: "center" }}>
                  {(["proposed", "approved", "rejected"] as const)
                    .filter((s) => s === "proposed" || s === focused.status)
                    .map((s, i, arr) => (
                      <span key={s} className="row" style={{ gap: 6 }}>
                        <Pill tone={focused.status === s ? STATUS_TONE[s] : "neutral"}>{s}</Pill>
                        {i < arr.length - 1 && <ArrowUpRight size={12} style={{ transform: "rotate(90deg)", color: "var(--text-3)" }} />}
                      </span>
                    ))}
                </div>
              )}
              {liveDeploymentEvents.length > 0 && (
                <div className="stack" style={{ gap: 4 }}>
                  <span className="dim" style={{ fontSize: "0.68rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    Live
                  </span>
                  <AnimatePresence initial={false}>
                    {liveDeploymentEvents.map(({ key, event }) => (
                      <motion.div
                        key={key}
                        initial={{ opacity: 0, x: -8 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ duration: 0.25 }}
                        className="row"
                        style={{ gap: 6, fontSize: "0.75rem" }}
                      >
                        <Radio size={11} style={{ color: "var(--accent)", flexShrink: 0 }} />
                        <span className="mono dim">{event.type}</span>
                        {"deployment_id" in event && <span className="dim">· {shortId(event.deployment_id)}</span>}
                      </motion.div>
                    ))}
                  </AnimatePresence>
                </div>
              )}
            </div>
          )}
        </Panel>
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Deployment map - dominant                                        */}
      {/* ---------------------------------------------------------------- */}
      <AnimatePresence mode="wait">
        <motion.div
          key={`${focusedId ?? "none"}::${targetMarkers.length}`}
          initial={{ opacity: 0, scale: 0.99 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.42, ease: [0.4, 0, 0.2, 1] }}
        >
          <Panel
            className="panel-hero"
            title={
              <span className="row" style={{ gap: 8 }}>
                <Navigation size={15} style={{ color: "var(--decision)" }} />
                Deployment map
              </span>
            }
            meta="observed origin · predicted candidates · recommended targets · your team input"
          >
            {riskFieldState.loading && <LoadingBlock label="Loading jurisdiction context…" />}
            {riskFieldState.error && <ErrorBlock message={riskFieldState.error} onRetry={riskFieldState.reload} />}
            {!riskFieldState.loading && !riskFieldState.error && (
              <RiskMap cells={riskFieldState.data?.h3_cells ?? []} height={560} markers={[...originMarkers, ...targetMarkers, ...teamMarkers]} />
            )}
            <div className="row wrap" style={{ gap: 16, marginTop: 10, fontSize: "0.75rem" }}>
              <span className="muted">◎ Predicted candidates (gold, ranked)</span>
              <span className="muted">◎ pulsing = recommended target for the focused deployment</span>
              {mode === "coverage_maximization" && <span className="muted">● Team markers = your real input, not backend data</span>}
            </div>
            <p className="hint" style={{ marginTop: 4 }}>
              No coverage-radius geometry is drawn — the optimizer's coverage radius is an internal server setting, never returned by this
              endpoint, so a circle here would be a guess. Coverage is instead reported as the real computed ratio below.
            </p>
          </Panel>
        </motion.div>
      </AnimatePresence>

      {/* ---------------------------------------------------------------- */}
      {/* Resource constraints | Coverage result | Decision                */}
      {/* ---------------------------------------------------------------- */}
      <div className="grid grid-cols-3">
        <Panel
          title={
            <span className="row" style={{ gap: 8 }}>
              <Users size={15} style={{ color: "var(--accent)" }} />
              Resource constraints
            </span>
          }
        >
          <div className="stack" style={{ gap: 12 }}>
            <p className="hint">
              This case needs {mode === "coverage_maximization" ? "physical team locations" : "a request-slot count"} — entered by you, never
              defaulted. Each run persists a new deployment; nothing is overwritten.
            </p>
            {mode === "coverage_maximization" && (
              <TeamLocationsInput
                teamCount={teamCount}
                setTeamCount={setTeamCount}
                locations={teamLocations}
                setLocations={setTeamLocations}
                incidentLat={complaint.location_lat}
                incidentLon={complaint.location_lon}
              />
            )}
            {mode === "resource_allocation" && (
              <div>
                <span className="dim" style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  Request slots
                </span>
                <div style={{ marginTop: 4 }}>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={requestSlotCount}
                    onChange={(e) => setRequestSlotCount(Number(e.target.value))}
                    style={{ width: 70 }}
                  />
                </div>
              </div>
            )}
            <button className="btn btn-primary" disabled={!canGenerate || generating} onClick={handleGenerate}>
              <Sparkles size={14} />
              {generating ? "Optimizing…" : "Optimize deployment"}
            </button>
            {genError && <p className="error-text">{genError}</p>}
          </div>
        </Panel>

        <Panel
          title={
            <span className="row" style={{ gap: 8 }}>
              <ListChecks size={15} style={{ color: "var(--accent)" }} />
              Coverage result
            </span>
          }
        >
          {!focused && <EmptyState title="No deployment focused" description="Generate or select a recommendation to see its coverage." />}
          {focused && focused.expected_coverage_total != null && focused.naive_baseline_coverage != null && (
            <div className="stack" style={{ gap: 12 }}>
              <CoverageBar optimized={focused.expected_coverage_total} baseline={focused.naive_baseline_coverage} />
              <p className="hint">
                {focused.expected_coverage_total > focused.naive_baseline_coverage
                  ? `+${((focused.expected_coverage_total - focused.naive_baseline_coverage) * 100).toFixed(1)} points over the naive "top-N by score" baseline.`
                  : "No improvement over the naive baseline for this run — reported honestly, not hidden."}
              </p>
              {fresh ? (
                <div className="stack" style={{ gap: 6 }}>
                  <span className="dim" style={{ fontSize: "0.72rem" }}>
                    Assignment ({fresh.result.assignment.length})
                  </span>
                  {fresh.result.assignment.map((a, i) =>
                    isCoverageRow(a) ? (
                      <div key={i} className="row between" style={{ fontSize: "0.78rem" }}>
                        <span className="mono">{a.team_id}</span>
                        <span className="dim">→ {shortId(a.exit_channel_id)}</span>
                        <span className="tabular">{a.travel_time_min.toFixed(0)} min</span>
                      </div>
                    ) : (
                      <div key={i} className="row between" style={{ fontSize: "0.78rem" }}>
                        <span className="tabular">#{a.priority_rank}</span>
                        <span className="dim">{shortId(a.exit_channel_id)}</span>
                        <span className="tabular">value {a.expected_value.toFixed(2)}</span>
                      </div>
                    )
                  )}
                </div>
              ) : (
                <p className="hint">
                  Target-level assignment detail is only available immediately after generation — this endpoint doesn't persist it, so a
                  reloaded/older deployment shows totals only, honestly.
                </p>
              )}
            </div>
          )}
        </Panel>

        <Panel
          title={
            <span className="row" style={{ gap: 8 }}>
              <ShieldAlert size={15} style={{ color: "var(--decision)" }} />
              Decision
            </span>
          }
        >
          {!focused && <EmptyState title="No deployment focused" />}
          {focused && (
            <div className="stack" style={{ gap: 8, fontSize: "0.8rem" }}>
              <div className="row between">
                <span className="dim">Deployment</span>
                <span className="mono">{shortId(focused.deployment_id)}</span>
              </div>
              <div className="row between">
                <span className="dim">Status</span>
                <Pill tone={STATUS_TONE[focused.status]}>{focused.status}</Pill>
              </div>
              <div className="row between">
                <span className="dim">Mode</span>
                <span>{focused.optimizer_mode?.replace(/_/g, " ") ?? "—"}</span>
              </div>
              {focused.decided_by ? (
                <p className="hint">
                  Decided by <span className="mono">{shortId(focused.decided_by)}</span> at {new Date(focused.decided_at!).toLocaleString()}
                  {sessionDecision && ` — "${sessionDecision.justification}" (recorded this session)`}
                </p>
              ) : (
                <p className="hint">
                  <Clock size={11} style={{ verticalAlign: -1.5, marginRight: 4 }} />
                  Awaiting human decision.
                </p>
              )}
            </div>
          )}
        </Panel>
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Approval / action                                                */}
      {/* ---------------------------------------------------------------- */}
      <Panel title="Approval & action">
        {!focused && <EmptyState title="Nothing to approve yet" description="Generate a recommendation above first." />}
        {focused && focused.status === "proposed" && (
          <>
            <div
              className="row"
              style={{
                gap: 14,
                alignItems: "center",
                marginBottom: 14,
                padding: "14px 16px",
                borderRadius: "var(--radius)",
                background: "var(--decision-dim)",
                border: "1px solid color-mix(in srgb, var(--decision) 40%, transparent)",
              }}
            >
              <ShieldAlert size={26} style={{ color: "var(--decision)", flexShrink: 0 }} />
              <div>
                <div className="decision-text" style={{ fontWeight: 700, fontSize: "var(--text-lg)", letterSpacing: "0.01em" }}>
                  Approval required
                </div>
                <p className="hint" style={{ marginTop: 2 }}>
                  Deployment <span className="mono">{shortId(focused.deployment_id)}</span> ·{" "}
                  {focused.optimizer_mode?.replace(/_/g, " ")} · expected coverage{" "}
                  <strong style={{ color: "var(--text-0)" }}>
                    {focused.expected_coverage_total != null ? `${(focused.expected_coverage_total * 100).toFixed(0)}%` : "—"}
                  </strong>
                </p>
              </div>
            </div>
            {canDecide ? (
              <DecisionForm deploymentId={focused.deployment_id} onDecided={handleDecided} />
            ) : (
              <p className="hint">
                Approval requires the investigator or supervisor role — you are viewing as <strong>{auth!.role.replace(/_/g, " ")}</strong>,
                read-only here per the backend's own RBAC.
              </p>
            )}
          </>
        )}
        {focused && focused.status === "approved" && (
          <div className="stack" style={{ gap: 10 }}>
            <p className="hint">
              <CheckCircle2 size={13} style={{ verticalAlign: -2, marginRight: 4, color: "var(--ok)" }} />
              Approved. The Action module dispatches automatically on approval — no separate button triggers it.
            </p>
            <button className="btn btn-decision" style={{ alignSelf: "flex-start" }} onClick={() => navigate(`/cases/${complaint.complaint_id}/audit`)}>
              Continue to Action &amp; Audit
              <ArrowUpRight size={14} />
            </button>
          </div>
        )}
        {focused && focused.status === "rejected" && (
          <p className="hint">
            <XCircle size={13} style={{ verticalAlign: -2, marginRight: 4, color: "var(--danger)" }} />
            Rejected — retained for audit, exactly like an approved one. Generate a new recommendation above if circumstances changed.
          </p>
        )}
      </Panel>
    </div>
  );
}
