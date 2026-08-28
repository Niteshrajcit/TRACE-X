import { useState } from "react";
import { AlertCircle, CheckCircle2, Fingerprint, GitBranch, ShieldCheck, UserCheck } from "lucide-react";
import { assignCase, closeCase, listAuditEvents } from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { useCase } from "../../context/CaseContext";
import { useApi } from "../../hooks/useApi";
import { decodeToken } from "../../lib/jwt";
import { computeSuspiciousIndicators } from "../../lib/suspiciousIndicators";
import { EmptyState, ErrorBlock, LoadingBlock, Panel, Pill, StatCard, Timeline } from "../../components/ui/primitives";

const AUDIT_EVENT_LABEL: Record<string, string> = {
  "complaint.created": "Complaint filed",
  "intervention.approved": "Intervention approved",
  "intervention.rejected": "Intervention rejected",
  "outcome.recorded": "Outcome recorded",
};

export function CaseOverview() {
  const { auth } = useAuth();
  const { complaint, rings, reloadComplaint } = useCase();
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [closeReason, setCloseReason] = useState("");
  const [showClose, setShowClose] = useState(false);

  const auditState = useApi(
    () => listAuditEvents(auth!.token, { subjectId: complaint.complaint_id, subjectType: "complaint" }),
    [auth!.token, complaint.complaint_id]
  );

  const canManage = auth!.role === "investigator" || auth!.role === "supervisor" || auth!.role === "admin";
  const myUserId = decodeToken(auth!.token)?.sub;
  const isMine = complaint.assigned_investigator_id === myUserId;

  async function handleAssignToMe() {
    if (!myUserId) return;
    setBusy(true);
    setActionError(null);
    try {
      await assignCase(auth!.token, complaint.complaint_id, { investigator_id: myUserId });
      reloadComplaint();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Could not assign case.");
    } finally {
      setBusy(false);
    }
  }

  async function handleClose() {
    if (closeReason.trim().length < 3) return;
    setBusy(true);
    setActionError(null);
    try {
      await closeCase(auth!.token, complaint.complaint_id, { reason: closeReason.trim() });
      reloadComplaint();
      setShowClose(false);
      setCloseReason("");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Could not close case.");
    } finally {
      setBusy(false);
    }
  }

  const indicators = computeSuspiciousIndicators(rings, complaint);

  return (
    <div className="stack">
      <div className="grid grid-cols-4">
        <StatCard label="Amount reported" value={`₹${Number(complaint.amount).toLocaleString("en-IN")}`} icon={<Fingerprint size={18} />} />
        <StatCard label="Rings linked" value={complaint.graph_summary?.ring_count ?? 0} icon={<GitBranch size={18} />} />
        <StatCard label="Entities in rings" value={complaint.graph_summary?.total_members ?? 0} icon={<UserCheck size={18} />} />
        <StatCard
          label="Deployments so far"
          value={complaint.deployment_history.length}
          icon={<ShieldCheck size={18} />}
        />
      </div>

      <div className="split">
        <div className="stack">
          <Panel title="Complaint details">
            <dl className="grid grid-cols-2" style={{ rowGap: 12, columnGap: 16, fontSize: "0.85rem" }}>
              <div>
                <div className="dim" style={{ fontSize: "0.72rem" }}>
                  Fraud type
                </div>
                <div>{complaint.fraud_type.replace(/_/g, " ")}</div>
              </div>
              <div>
                <div className="dim" style={{ fontSize: "0.72rem" }}>
                  Incident date/time
                </div>
                <div>{new Date(complaint.incident_datetime).toLocaleString()}</div>
              </div>
              <div>
                <div className="dim" style={{ fontSize: "0.72rem" }}>
                  Institution
                </div>
                <div>
                  {complaint.institution_name} ({complaint.institution_type})
                </div>
              </div>
              <div>
                <div className="dim" style={{ fontSize: "0.72rem" }}>
                  Transaction reference
                </div>
                <div className="mono">{complaint.transaction_reference ?? "—"}</div>
              </div>
              <div style={{ gridColumn: "1 / -1" }}>
                <div className="dim" style={{ fontSize: "0.72rem" }}>
                  Location
                </div>
                <div>{complaint.location_text}</div>
              </div>
              <div style={{ gridColumn: "1 / -1" }}>
                <div className="dim" style={{ fontSize: "0.72rem" }}>
                  Description
                </div>
                <div>{complaint.description}</div>
              </div>
              <div style={{ gridColumn: "1 / -1" }}>
                <div className="dim" style={{ fontSize: "0.72rem", marginBottom: 4 }}>
                  Evidence noted by citizen
                </div>
                {complaint.evidence_notes.length > 0 ? (
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {complaint.evidence_notes.map((note, i) => (
                      <li key={i}>{note}</li>
                    ))}
                  </ul>
                ) : (
                  <span className="dim">None noted</span>
                )}
              </div>
            </dl>
          </Panel>

          <Panel title="Suspicious indicators">
            <div className="stack" style={{ gap: 8 }}>
              {indicators.map((text, i) => (
                <div key={i} className="row" style={{ gap: 8, fontSize: "0.83rem" }}>
                  <AlertCircle size={14} style={{ color: "var(--decision)", flexShrink: 0, marginTop: 2 }} />
                  <span>{text}</span>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div className="stack">
          <Panel title="Case actions">
            {actionError && <p className="error-text" style={{ marginBottom: 10 }}>{actionError}</p>}
            <div className="stack" style={{ gap: 8 }}>
              {canManage && !isMine && complaint.status !== "closed" && (
                <button className="btn btn-primary btn-block" disabled={busy} onClick={handleAssignToMe}>
                  <UserCheck size={14} />
                  Assign to me
                </button>
              )}
              {isMine && <Pill tone="ok">Assigned to you</Pill>}
              {canManage && complaint.status !== "closed" && !showClose && (
                <button className="btn btn-block" onClick={() => setShowClose(true)}>
                  <CheckCircle2 size={14} />
                  Close case
                </button>
              )}
              {showClose && (
                <div className="stack" style={{ gap: 8 }}>
                  <textarea
                    rows={3}
                    placeholder="Reason for closing this case…"
                    value={closeReason}
                    onChange={(e) => setCloseReason(e.target.value)}
                  />
                  <div className="row" style={{ gap: 8 }}>
                    <button className="btn btn-primary" disabled={busy || closeReason.trim().length < 3} onClick={handleClose}>
                      Confirm close
                    </button>
                    <button className="btn btn-ghost" onClick={() => setShowClose(false)}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
              {complaint.status === "closed" && <Pill>Case closed</Pill>}
            </div>
          </Panel>

          <Panel title="Case timeline" meta="from the audit log">
            {auditState.loading && <LoadingBlock label="Loading timeline…" />}
            {auditState.error && <ErrorBlock message={auditState.error} />}
            {auditState.data && auditState.data.length === 0 && (
              <EmptyState title="No audit events yet" description="Events appear here as the case progresses." />
            )}
            {auditState.data && auditState.data.length > 0 && (
              <Timeline
                events={auditState.data.map((e) => ({
                  id: e.event_id,
                  title: AUDIT_EVENT_LABEL[e.event_type] ?? e.event_type.replace(/_/g, " ").replace(/\./g, " · "),
                  time: new Date(e.occurred_at).toLocaleString(),
                  tone: e.event_type.startsWith("intervention") ? "decision" : "done",
                }))}
              />
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
