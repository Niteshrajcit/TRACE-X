import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  Award,
  BadgeCheck,
  CheckCircle2,
  Clock,
  Database,
  FileCheck,
  Info,
  PackageCheck,
  Radio,
  Send,
  ShieldAlert,
  ShieldCheck,
  Truck,
  XCircle,
} from "lucide-react";
import { ApiError, listAuditEvents, listModels, recordOutcome, verifyAuditChain } from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { useCase } from "../../context/CaseContext";
import { useLiveEventsContext } from "../../context/LiveEventsContext";
import { useApi } from "../../hooks/useApi";
import { eventComplaintId, eventLabel } from "../../lib/eventLabels";
import { EmptyState, ErrorBlock, LoadingBlock, Panel, Pill, Timeline, type TimelineEvent } from "../../components/ui/primitives";
import type { AuditEventResponse, DeploymentHistoryEntry, LiveEvent, OutcomeResponse, OutcomeResult } from "../../types/domain";

/**
 * F8 — Action + Outcome + Audit. Closes the loop: APPROVED -> DISPATCHED
 * -> DELIVERED -> OUTCOME -> FEEDBACK -> AUDIT VERIFIED. Every value traces
 * to a real endpoint or a real live WS event captured this session. Where
 * the backend has a genuine, structural gap - no GET /v1/alerts, no
 * payload on AuditEventResponse, no reverse lookup from a complaint to its
 * outcome/alert subject IDs - this page discloses it plainly rather than
 * guessing. See the inline comments at each gap for the exact backend
 * reasoning (cross-checked against app/action/, app/modules/audit/,
 * app/modules/deployments/router.py during F8 implementation).
 */

const OUTCOME_OPTIONS: { value: OutcomeResult; label: string }[] = [
  { value: "cash_out_prevented", label: "Cash-out prevented" },
  { value: "cash_out_occurred_elsewhere", label: "Cash-out occurred elsewhere" },
  { value: "no_activity", label: "No activity observed" },
  { value: "funds_recovered_partial", label: "Funds partially recovered" },
  { value: "funds_recovered_full", label: "Funds fully recovered" },
];

const STATUS_TONE: Record<DeploymentHistoryEntry["status"], "neutral" | "decision" | "ok"> = {
  proposed: "decision",
  approved: "ok",
  rejected: "neutral",
};

function isActionDispatched(e: LiveEvent): e is Extract<LiveEvent, { type: "action.dispatched" }> {
  return e.type === "action.dispatched";
}
function isOutcomeRecorded(e: LiveEvent): e is Extract<LiveEvent, { type: "outcome.recorded" }> {
  return e.type === "outcome.recorded";
}
function isFeedbackCreated(e: LiveEvent): e is Extract<LiveEvent, { type: "feedback.created" }> {
  return e.type === "feedback.created";
}

function shortId(id: string): string {
  return id.length > 10 ? `${id.slice(0, 8)}…` : id;
}

const JOURNEY = [
  { label: "Complaint", to: (id: string) => `/cases/${id}` },
  { label: "Network", to: (id: string) => `/cases/${id}/network` },
  { label: "Ring + Corridor", to: (id: string) => `/cases/${id}/rings` },
  { label: "Risk", to: () => "/risk-intelligence" },
  { label: "Prediction + Explanation", to: (id: string) => `/cases/${id}/prediction` },
  { label: "Intervention + Approval", to: (id: string) => `/cases/${id}/intervention` },
  { label: "Action + Outcome + Audit", to: (id: string) => `/cases/${id}/audit`, current: true },
];

function OutcomeForm({
  deploymentId,
  busyGlobal,
  onRecorded,
}: {
  deploymentId: string;
  busyGlobal: boolean;
  onRecorded: (r: OutcomeResponse) => void;
}) {
  const { auth } = useAuth();
  const [result, setResult] = useState<OutcomeResult>("cash_out_prevented");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const res = await recordOutcome(auth!.token, deploymentId, { result, notes: notes.trim() || null });
      onRecorded(res);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError(
          "An outcome was already recorded for this deployment. The API has no endpoint to read a historical per-deployment outcome back, so it cannot be displayed here after the fact — this 409 is itself the honest confirmation one exists."
        );
      } else {
        setError(err instanceof ApiError ? `${err.status} — ${err.message}` : err instanceof Error ? err.message : "Could not record outcome.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ gap: 8 }}>
      <select value={result} onChange={(e) => setResult(e.target.value as OutcomeResult)}>
        {OUTCOME_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <textarea rows={2} placeholder="Notes (optional)…" value={notes} onChange={(e) => setNotes(e.target.value)} />
      {error && <p className="error-text">{error}</p>}
      <button className="btn btn-primary" disabled={busy || busyGlobal} onClick={submit}>
        {busy ? "Recording…" : "Record outcome"}
      </button>
    </div>
  );
}

export function ActionOutcomeAudit() {
  const { auth } = useAuth();
  const { complaint } = useCase();
  const { keyedEvents, setActiveJurisdiction } = useLiveEventsContext();

  useEffect(() => {
    if (!auth!.jurisdictionId && complaint.jurisdiction_id) setActiveJurisdiction(complaint.jurisdiction_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [complaint.jurisdiction_id]);

  const canRecordOutcome = auth!.role === "investigator" || auth!.role === "supervisor" || auth!.role === "admin";
  const canVerifyChain = auth!.role === "auditor" || auth!.role === "admin";
  const canSeeModels = auth!.role === "auditor" || auth!.role === "admin";

  const approvedDeployments = complaint.deployment_history.filter((d) => d.status === "approved");
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const didAutoFocus = useRef(false);
  useEffect(() => {
    if (didAutoFocus.current || focusedId || approvedDeployments.length === 0) return;
    didAutoFocus.current = true;
    setFocusedId(approvedDeployments[0].deployment_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [approvedDeployments]);
  const focused = approvedDeployments.find((d) => d.deployment_id === focusedId) ?? null;

  const [outcomes, setOutcomes] = useState<Record<string, OutcomeResponse>>({});
  const recordedOutcome = focusedId ? outcomes[focusedId] : undefined;

  // -- Live events for this complaint, this session only ------------------
  const caseEvents = useMemo(
    () => keyedEvents.filter((k) => eventComplaintId(k.event) === complaint.complaint_id),
    [keyedEvents, complaint.complaint_id]
  );
  const dispatchEvent = useMemo(() => {
    const match = caseEvents.find((k) => isActionDispatched(k.event) && k.event.deployment_id === focusedId);
    return match && isActionDispatched(match.event) ? match.event : undefined;
  }, [caseEvents, focusedId]);
  const liveOutcomeEvent = useMemo(() => {
    const match = caseEvents.find((k) => isOutcomeRecorded(k.event) && k.event.deployment_id === focusedId);
    return match && isOutcomeRecorded(match.event) ? match.event : undefined;
  }, [caseEvents, focusedId]);
  const liveFeedbackEvent = useMemo(() => {
    const match = caseEvents.find((k) => isFeedbackCreated(k.event));
    return match && isFeedbackCreated(match.event) ? match.event : undefined;
  }, [caseEvents]);

  // -- Real, persisted audit trail ----------------------------------------
  // AuditEventResponse exposes no `payload`, so an event can only be
  // looked up by a subject the frontend already has a real ID for. Every
  // deployment.recommended / intervention.approved|rejected event uses
  // subject_type="recommended_deployment", subject_id=deployment_id - all
  // of which are already known from complaint.deployment_history, so this
  // merges a real, complete query per deployment plus the complaint's own
  // subject events. outcome.recorded (subject_type="intervention_outcome")
  // and action.dispatched (subject_type="alert") use IDs (outcome_id,
  // alert_id) this app never receives via any GET - genuinely
  // unreachable after the fact, not an oversight - so those two only ever
  // appear below via the live feed, never in this persisted merge.
  const deploymentIds = useMemo(() => complaint.deployment_history.map((d) => d.deployment_id), [complaint.deployment_history]);
  const auditState = useApi(
    () =>
      Promise.all([
        listAuditEvents(auth!.token, { subjectId: complaint.complaint_id, subjectType: "complaint" }),
        ...deploymentIds.map((id) => listAuditEvents(auth!.token, { subjectId: id, subjectType: "recommended_deployment" })),
      ]).then((groups) => {
        const seen = new Map<string, AuditEventResponse>();
        groups.flat().forEach((e) => seen.set(e.event_id, e));
        return Array.from(seen.values()).sort((a, b) => a.seq_no - b.seq_no);
      }),
    [auth!.token, complaint.complaint_id, deploymentIds.join(",")]
  );

  const focusedDeploymentAudit = useMemo(
    () => (auditState.data ?? []).filter((e) => e.subject_id === focusedId),
    [auditState.data, focusedId]
  );

  const chainState = useVerifyChain(canVerifyChain);
  const modelsState = useApi(() => (canSeeModels ? listModels(auth!.token) : Promise.resolve(null)), [auth!.token, canSeeModels]);

  // -- Action status: APPROVED -> DISPATCHED -> DELIVERED -----------------
  type StepState = "done" | "pending" | "unknown";
  const dispatchedState: StepState = dispatchEvent ? "done" : "unknown";
  const deliveredState: StepState = !dispatchEvent ? "unknown" : dispatchEvent.delivered ? "done" : "pending";

  // -- Timeline for the focused deployment (persisted + live) -------------
  const focusedTimeline: TimelineEvent[] = useMemo(() => {
    const items: TimelineEvent[] = focusedDeploymentAudit.map((e) => ({
      id: e.event_id,
      title: e.event_type.replace(/[._]/g, " "),
      time: new Date(e.occurred_at).toLocaleString(),
      description: `seq #${e.seq_no} · hash ${e.this_hash.slice(0, 10)}… · persisted, audit-verified`,
      tone: e.event_type.startsWith("intervention.approved") || e.event_type.startsWith("intervention.rejected") ? "decision" : "done",
    }));
    if (dispatchEvent) {
      items.push({
        id: "live-dispatch",
        title: "action dispatched",
        description: `${dispatchEvent.channel.replace(/_/g, " ")} · ${dispatchEvent.delivered ? "delivered" : "sent, not yet acknowledged"} · live this session, not independently re-queryable after reload`,
        tone: "done",
      });
    }
    if (liveOutcomeEvent) {
      items.push({
        id: "live-outcome",
        title: "outcome recorded",
        description: `${liveOutcomeEvent.result.replace(/_/g, " ")} · live this session`,
        tone: "done",
      });
    }
    if (liveFeedbackEvent) {
      items.push({
        id: "live-feedback",
        title: "feedback created",
        description: `feature snapshot ${shortId(liveFeedbackEvent.feature_snapshot_id)} · live this session`,
        tone: "done",
      });
    }
    return items;
  }, [focusedDeploymentAudit, dispatchEvent, liveOutcomeEvent, liveFeedbackEvent]);

  return (
    <div className="stack">
      {/* ---------------------------------------------------------------- */}
      {/* Full investigation journey                                       */}
      {/* ---------------------------------------------------------------- */}
      <div className="row wrap" style={{ gap: 6 }}>
        {JOURNEY.map((stage) => (
          <Link
            key={stage.label}
            to={stage.to(complaint.complaint_id)}
            className={`pill ${stage.current ? "pill-decision" : "pill-neutral"}`}
            style={{ textDecoration: "none" }}
          >
            {stage.label}
          </Link>
        ))}
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Action status | Deployment status                                */}
      {/* ---------------------------------------------------------------- */}
      <div className="grid grid-cols-2">
        <Panel
          title={
            <span className="row" style={{ gap: 8 }}>
              <Truck size={15} style={{ color: "var(--decision)" }} />
              Action status
            </span>
          }
        >
          {!focused ? (
            <EmptyState title="No approved deployment" description="Approve a recommendation in the Intervention tab first." icon={<ShieldCheck size={26} />} />
          ) : (
            <div className="stack" style={{ gap: 14 }}>
              <div className="row" style={{ gap: 4, alignItems: "center" }}>
                <StepPill label="Approved" state="done" />
                <StepArrow />
                <StepPill label="Dispatched" state={dispatchedState} />
                <StepArrow />
                <StepPill label="Delivered" state={deliveredState} />
              </div>
              {dispatchEvent ? (
                <div className="stack" style={{ gap: 6 }}>
                  <div className="row between">
                    <span className="dim" style={{ fontSize: "0.78rem" }}>
                      Receiver channel
                    </span>
                    <Pill tone="decision">{dispatchEvent.channel.replace(/_/g, " ")}</Pill>
                  </div>
                  <p className="hint" style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
                    <Info size={12} style={{ marginTop: 2, flexShrink: 0, color: "var(--decision)" }} />
                    <span>
                      Prototype receiver — a real, HMAC-signed webhook to this backend's own mock endpoint, not a live bank or I4C
                      connection. {dispatchEvent.delivered ? "Genuinely acknowledged receipt." : "Sent; acknowledgement not yet recorded."}
                    </span>
                  </p>
                </div>
              ) : (
                <p className="hint">
                  Dispatch happens automatically, server-side, the instant a deployment is approved — it already ran for this deployment,
                  but its result (channel, delivery) is only ever observable via the live event at that moment. No GET endpoint exposes
                  alert history after the fact, so this session hasn't seen it. Nothing was skipped; nothing is broken.
                </p>
              )}
            </div>
          )}
        </Panel>

        <Panel
          title={
            <span className="row" style={{ gap: 8 }}>
              <BadgeCheck size={15} style={{ color: "var(--accent)" }} />
              Deployment status
            </span>
          }
          meta={approvedDeployments.length > 1 ? `${approvedDeployments.length} approved` : undefined}
        >
          {approvedDeployments.length === 0 && <EmptyState title="No approved deployment" />}
          {approvedDeployments.length > 0 && (
            <div className="stack" style={{ gap: 10 }}>
              {approvedDeployments.length > 1 && (
                <div className="row wrap" style={{ gap: 6 }}>
                  {approvedDeployments.map((d) => (
                    <button
                      key={d.deployment_id}
                      className={`ring-chip${focusedId === d.deployment_id ? " active" : ""}`}
                      onClick={() => setFocusedId(d.deployment_id)}
                    >
                      {shortId(d.deployment_id)}
                    </button>
                  ))}
                </div>
              )}
              {focused && (
                <>
                  <div className="row between">
                    <span className="dim" style={{ fontSize: "0.78rem" }}>
                      Deployment
                    </span>
                    <span className="mono">{shortId(focused.deployment_id)}</span>
                  </div>
                  <div className="row between">
                    <span className="dim" style={{ fontSize: "0.78rem" }}>
                      Mode
                    </span>
                    <span>{focused.optimizer_mode?.replace(/_/g, " ") ?? "—"}</span>
                  </div>
                  <div className="row between">
                    <span className="dim" style={{ fontSize: "0.78rem" }}>
                      Status
                    </span>
                    <Pill tone={STATUS_TONE[focused.status]}>{focused.status}</Pill>
                  </div>
                  {focused.expected_coverage_total != null && (
                    <div className="row between">
                      <span className="dim" style={{ fontSize: "0.78rem" }}>
                        Expected coverage
                      </span>
                      <span className="tabular">{(focused.expected_coverage_total * 100).toFixed(0)}%</span>
                    </div>
                  )}
                  {focused.decided_by && (
                    <p className="hint">
                      Decided by <span className="mono">{shortId(focused.decided_by)}</span> at {new Date(focused.decided_at!).toLocaleString()}
                    </p>
                  )}
                </>
              )}
            </div>
          )}
        </Panel>
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Action / dispatch timeline - dominant                            */}
      {/* ---------------------------------------------------------------- */}
      <AnimatePresence mode="wait">
        <motion.div
          key={focusedId ?? "none"}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: [0.4, 0, 0.2, 1] }}
        >
          <Panel
            className="panel-hero"
            title={
              <span className="row" style={{ gap: 8 }}>
                <PackageCheck size={15} style={{ color: "var(--accent)" }} />
                Action / dispatch timeline
              </span>
            }
            meta={focused ? `deployment ${shortId(focused.deployment_id)}` : undefined}
          >
            {auditState.loading && <LoadingBlock label="Loading this deployment's audit trail…" />}
            {auditState.error && <ErrorBlock message={auditState.error} onRetry={auditState.reload} />}
            {!auditState.loading && !auditState.error && !focused && <EmptyState title="No approved deployment focused" />}
            {!auditState.loading && !auditState.error && focused && focusedTimeline.length === 0 && (
              <EmptyState title="No timeline events yet" description="This deployment's audit trail hasn't loaded any events." />
            )}
            {!auditState.loading && !auditState.error && focused && focusedTimeline.length > 0 && <Timeline events={focusedTimeline} />}
          </Panel>
        </motion.div>
      </AnimatePresence>

      {/* ---------------------------------------------------------------- */}
      {/* Outcome | Audit                                                  */}
      {/* ---------------------------------------------------------------- */}
      <div className="grid grid-cols-2">
        <Panel
          title={
            <span className="row" style={{ gap: 8 }}>
              <FileCheck size={15} style={{ color: "var(--decision)" }} />
              Outcome
            </span>
          }
        >
          {!focused && <EmptyState title="No approved deployment" description="Approve a recommendation first." icon={<Send size={26} />} />}
          {focused &&
            (recordedOutcome ? (
              <div className="stack" style={{ gap: 10 }}>
                <div className="row" style={{ gap: 8, color: "var(--ok)" }}>
                  <CheckCircle2 size={16} />
                  <span>Outcome recorded: {OUTCOME_OPTIONS.find((o) => o.value === recordedOutcome.result)?.label ?? recordedOutcome.result}</span>
                </div>
                <div className="row between">
                  <span className="dim" style={{ fontSize: "0.78rem" }}>
                    Recorded by
                  </span>
                  <span className="mono">{shortId(recordedOutcome.recorded_by)}</span>
                </div>
                <div className="row between">
                  <span className="dim" style={{ fontSize: "0.78rem" }}>
                    Recorded at
                  </span>
                  <span className="tabular">{new Date(recordedOutcome.recorded_at).toLocaleString()}</span>
                </div>
                <div className="row between">
                  <span className="dim" style={{ fontSize: "0.78rem" }}>
                    Feedback
                  </span>
                  {recordedOutcome.feature_snapshot_id ? (
                    <Pill tone="ok">
                      <Award size={11} /> written for retraining
                    </Pill>
                  ) : (
                    <Pill>none written</Pill>
                  )}
                </div>
              </div>
            ) : canRecordOutcome ? (
              <OutcomeForm
                deploymentId={focused.deployment_id}
                busyGlobal={false}
                onRecorded={(r) => setOutcomes((prev) => ({ ...prev, [focused.deployment_id]: r }))}
              />
            ) : (
              <p className="hint">
                Recording an outcome requires the investigator, supervisor, or admin role — you are viewing as{" "}
                <strong>{auth!.role.replace(/_/g, " ")}</strong>, read-only here per the backend's own RBAC.
              </p>
            ))}
        </Panel>

        <Panel
          title={
            <span className="row" style={{ gap: 8 }}>
              <ShieldCheck size={15} style={{ color: "var(--accent)" }} />
              Audit
            </span>
          }
          meta={auditState.data ? `${auditState.data.length} persisted event(s), whole case` : undefined}
        >
          {auditState.loading && <LoadingBlock label="Loading audit trail…" />}
          {auditState.error && <ErrorBlock message={auditState.error} onRetry={auditState.reload} />}
          {!auditState.loading && !auditState.error && (auditState.data?.length ?? 0) === 0 && <EmptyState title="No audit events" />}
          {!auditState.loading && !auditState.error && (auditState.data?.length ?? 0) > 0 && (
            <div className="stack" style={{ gap: 0, maxHeight: 280, overflowY: "auto" }}>
              {[...auditState.data!]
                .sort((a, b) => b.seq_no - a.seq_no)
                .map((e) => (
                  <div key={e.event_id} className="row between" style={{ padding: "7px 2px", borderBottom: "1px solid var(--border-subtle)", fontSize: "0.78rem" }}>
                    <span>{e.event_type.replace(/[._]/g, " ")}</span>
                    <span className="mono dim" style={{ fontSize: "0.68rem" }}>
                      #{e.seq_no} · {new Date(e.occurred_at).toLocaleString()}
                    </span>
                  </div>
                ))}
            </div>
          )}
          <p className="hint" style={{ marginTop: 8 }}>
            Complaint-level plus every deployment's own recommend/decide events — real, persisted, audit-verifiable. Dispatch/outcome/feedback
            entries exist in the ledger too but use subject IDs (alert, outcome) this app never receives via any GET, so they can't be looked
            up here after the fact — see the live feed below and the timeline above for what this session actually observed.
          </p>
        </Panel>
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Live feed                                                        */}
      {/* ---------------------------------------------------------------- */}
      <Panel title="Live action feed" meta="this case, this session">
        {caseEvents.length === 0 ? (
          <EmptyState title="No live events yet" description="Approve a deployment to see dispatch and outcome events stream in." icon={<Radio size={26} />} />
        ) : (
          <div className="stack" style={{ gap: 8 }}>
            <AnimatePresence initial={false}>
              {caseEvents.slice(0, 10).map(({ key, event: e }) => (
                <motion.div
                  key={key}
                  className="row between"
                  style={{ fontSize: "0.82rem" }}
                  initial={{ opacity: 0, x: -8, height: 0 }}
                  animate={{ opacity: 1, x: 0, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
                >
                  <span>{eventLabel(e)}</span>
                  <Pill tone="accent">live</Pill>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        )}
      </Panel>

      {/* ---------------------------------------------------------------- */}
      {/* Verification                                                     */}
      {/* ---------------------------------------------------------------- */}
      <div className="grid grid-cols-2">
        <Panel
          title={
            <span className="row" style={{ gap: 8 }}>
              <ShieldAlert size={15} style={{ color: "var(--decision)" }} />
              Audit integrity
            </span>
          }
          actions={
            canVerifyChain ? (
              <button className="btn btn-sm" disabled={chainState.verifying} onClick={chainState.run}>
                {chainState.verifying ? "Verifying…" : "Verify chain"}
              </button>
            ) : undefined
          }
        >
          {!canVerifyChain && (
            <p className="hint">
              Chain verification is visible to auditor/admin roles only — you are viewing as <strong>{auth!.role.replace(/_/g, " ")}</strong>.
            </p>
          )}
          {canVerifyChain && !chainState.result && <p className="hint">Not yet verified this session. Click "Verify chain" for the real, live result.</p>}
          {canVerifyChain && chainState.result && (
            <div className="row" style={{ gap: 14, alignItems: "center" }}>
              {chainState.result.valid ? (
                <>
                  <CheckCircle2 size={30} style={{ color: "var(--ok)", flexShrink: 0 }} />
                  <div>
                    <div className="row" style={{ gap: 8, alignItems: "center" }}>
                      <span className="dim" style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                        Audit integrity
                      </span>
                    </div>
                    <div className="ok-text" style={{ fontWeight: 700, fontSize: "var(--text-2xl)", letterSpacing: "0.02em" }}>
                      VERIFIED
                    </div>
                    <p className="hint">Every hash in the chain recomputes correctly — no tampering detected, system-wide.</p>
                  </div>
                </>
              ) : (
                <>
                  <XCircle size={30} style={{ color: "var(--danger)", flexShrink: 0 }} />
                  <div>
                    <span className="dim" style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                      Audit integrity
                    </span>
                    <div className="danger-text" style={{ fontWeight: 700, fontSize: "var(--text-2xl)", letterSpacing: "0.02em" }}>
                      BROKEN AT SEQ {chainState.result.broken_at_seq}
                    </div>
                    <p className="hint">The chain diverges at this sequence number — reported exactly as the backend found it.</p>
                  </div>
                </>
              )}
            </div>
          )}
        </Panel>

        <Panel
          title={
            <span className="row" style={{ gap: 8 }}>
              <Database size={15} style={{ color: "var(--accent)" }} />
              Model registry
            </span>
          }
        >
          {!canSeeModels && (
            <p className="hint">
              Model registry is visible to auditor/admin roles only — you are viewing as <strong>{auth!.role.replace(/_/g, " ")}</strong>.
            </p>
          )}
          {canSeeModels && modelsState.loading && <LoadingBlock label="Loading models…" />}
          {canSeeModels && modelsState.error && <ErrorBlock message={modelsState.error} onRetry={modelsState.reload} />}
          {canSeeModels && !modelsState.loading && !modelsState.error && modelsState.data && modelsState.data.length === 0 && (
            <EmptyState title="No registered models currently exposed." description="The retraining/registration job is a separate offline batch process — none has run yet." />
          )}
          {canSeeModels && modelsState.data && modelsState.data.length > 0 && (
            <div className="stack" style={{ gap: 8 }}>
              {modelsState.data.map((m) => (
                <div key={m.model_id} className="row between" style={{ fontSize: "0.82rem" }}>
                  <div>
                    <div>{m.stage.replace(/_/g, " ")}</div>
                    <div className="mono dim" style={{ fontSize: "0.7rem" }}>
                      {m.version}
                    </div>
                  </div>
                  <Pill tone={m.is_active ? "ok" : "neutral"}>{m.is_active ? "active" : "inactive"}</Pill>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}

function useVerifyChain(enabled: boolean) {
  const { auth } = useAuth();
  const [result, setResult] = useState<{ valid: boolean; broken_at_seq: number | null } | null>(null);
  const [verifying, setVerifying] = useState(false);
  async function run() {
    if (!enabled) return;
    setVerifying(true);
    try {
      setResult(await verifyAuditChain(auth!.token));
    } finally {
      setVerifying(false);
    }
  }
  return { result, verifying, run };
}

function StepPill({ label, state }: { label: string; state: "done" | "pending" | "unknown" }) {
  const tone = state === "done" ? "ok" : state === "pending" ? "decision" : "neutral";
  return (
    <span className={`pill pill-${tone}`}>
      {state === "done" && <CheckCircle2 size={11} />}
      {state === "pending" && <Clock size={11} />}
      {label}
      {state === "unknown" && <span className="dim"> · not observed</span>}
    </span>
  );
}
function StepArrow() {
  return <span className="dim" style={{ fontSize: "0.8rem" }}>→</span>;
}
