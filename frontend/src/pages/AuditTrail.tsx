import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import { listAuditEvents, listModels, verifyAuditChain } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useApi } from "../hooks/useApi";
import { AppShell } from "../layout/AppShell";
import { EmptyState, LoadingBlock, PageHeader, Panel, Pill } from "../components/ui/primitives";

export function AuditTrail() {
  const { auth } = useAuth();
  const isFullAudit = auth!.role === "auditor" || auth!.role === "admin";

  if (!isFullAudit) {
    return (
      <AppShell>
        <PageHeader eyebrow="Governance" title="Audit trail" />
        <Panel>
          <EmptyState
            title="Per-case audit only"
            description="Your role can view the audit trail for a specific case you have access to — open a case and use its Action & Audit tab. Full, unscoped audit browsing is restricted to auditor and admin roles."
            icon={<ShieldCheck size={26} />}
          />
        </Panel>
      </AppShell>
    );
  }

  return <FullAuditTrail />;
}

function FullAuditTrail() {
  const { auth } = useAuth();
  const token = auth!.token;
  const eventsState = useApi(() => listAuditEvents(token), [token]);
  const modelsState = useApi(() => listModels(token), [token]);
  const [chainResult, setChainResult] = useState<{ valid: boolean; broken_at_seq: number | null } | null>(null);
  const [verifying, setVerifying] = useState(false);

  async function runVerify() {
    setVerifying(true);
    try {
      setChainResult(await verifyAuditChain(token));
    } finally {
      setVerifying(false);
    }
  }

  return (
    <AppShell>
      <PageHeader
        eyebrow="Governance"
        title="Audit trail"
        subtitle="Every state-changing event across TRACE-X, cryptographically chained so tampering is detectable."
        actions={
          <button className="btn btn-primary btn-sm" disabled={verifying} onClick={runVerify}>
            {verifying ? "Verifying…" : "Verify chain integrity"}
          </button>
        }
      />

      {chainResult && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <p className={chainResult.valid ? "ok-text" : "error-text"}>
            {chainResult.valid ? "Chain verified end-to-end — no tampering detected." : `Chain integrity broken at sequence ${chainResult.broken_at_seq}.`}
          </p>
        </div>
      )}

      <div className="split">
        <Panel title="Event log" meta={eventsState.data ? `${eventsState.data.length} events (max 500)` : undefined}>
          {eventsState.loading && <LoadingBlock label="Loading audit events…" />}
          {eventsState.data && eventsState.data.length === 0 && <EmptyState title="No audit events yet" />}
          {eventsState.data && eventsState.data.length > 0 && (
            <div className="scroll-x">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Seq</th>
                    <th>Event</th>
                    <th>Subject</th>
                    <th>Occurred</th>
                    <th>Hash</th>
                  </tr>
                </thead>
                <tbody>
                  {[...eventsState.data]
                    .sort((a, b) => b.seq_no - a.seq_no)
                    .slice(0, 100)
                    .map((e) => (
                      <tr key={e.event_id}>
                        <td className="tabular dim">{e.seq_no}</td>
                        <td>{e.event_type.replace(/[._]/g, " ")}</td>
                        <td className="mono dim" style={{ fontSize: "0.72rem" }}>
                          {e.subject_type} · {e.subject_id?.slice(0, 8) ?? "—"}
                        </td>
                        <td className="dim">{new Date(e.occurred_at).toLocaleString()}</td>
                        <td className="mono dim" style={{ fontSize: "0.7rem" }}>
                          {e.this_hash.slice(0, 10)}…
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel title="Model registry">
          {modelsState.loading && <LoadingBlock label="Loading models…" />}
          {modelsState.data && modelsState.data.length === 0 && (
            <EmptyState title="No models registered" description="The retraining/registration job is a separate offline batch process — none has run yet." />
          )}
          {modelsState.data && modelsState.data.length > 0 && (
            <div className="stack" style={{ gap: 10 }}>
              {modelsState.data.map((m) => (
                <div key={m.model_id} className="row between" style={{ fontSize: "0.82rem" }}>
                  <div>
                    <div>{m.stage.replace(/_/g, " ")}</div>
                    <div className="mono dim" style={{ fontSize: "0.72rem" }}>
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
    </AppShell>
  );
}
