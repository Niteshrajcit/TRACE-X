import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import { listComplaints } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useApi } from "../hooks/useApi";
import { AppShell } from "../layout/AppShell";
import { EmptyState, ErrorBlock, LoadingBlock, PageHeader, Pill } from "../components/ui/primitives";
import type { ComplaintStatus } from "../types/domain";

const STATUS_OPTIONS: ComplaintStatus[] = [
  "new",
  "graph_building",
  "predicted",
  "action_recommended",
  "approved",
  "rejected",
  "closed",
];

export function CaseList() {
  const { auth } = useAuth();
  const token = auth!.token;
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState<ComplaintStatus | "">("");
  const [assignedToMe, setAssignedToMe] = useState(false);
  const [search, setSearch] = useState("");

  const { data, loading, error } = useApi(
    () => listComplaints(token, { status: statusFilter || undefined, assignedToMe }),
    [token, statusFilter, assignedToMe]
  );

  const filtered = useMemo(() => {
    if (!data) return [];
    const q = search.trim().toLowerCase();
    if (!q) return data;
    return data.filter((c) => c.incident_reference.toLowerCase().includes(q));
  }, [data, search]);

  return (
    <AppShell>
      <PageHeader eyebrow="Investigate" title="Cases" subtitle="Every complaint filed into TRACE-X, filterable by status and assignment." />

      <div className="panel">
        <div className="row wrap" style={{ marginBottom: 16, gap: 10 }}>
          <div style={{ position: "relative", flex: "1 1 220px" }}>
            <Search size={14} style={{ position: "absolute", left: 10, top: 11, color: "var(--text-3)" }} />
            <input
              placeholder="Search incident reference…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ paddingLeft: 30, width: "100%" }}
            />
          </div>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as ComplaintStatus | "")} style={{ width: 200 }}>
            <option value="">All statuses</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s.replace(/_/g, " ")}
              </option>
            ))}
          </select>
          {(auth!.role === "investigator" || auth!.role === "supervisor") && (
            <label className="row" style={{ margin: 0, fontWeight: 500, fontSize: "0.82rem" }}>
              <input type="checkbox" checked={assignedToMe} onChange={(e) => setAssignedToMe(e.target.checked)} style={{ width: "auto" }} />
              Assigned to me
            </label>
          )}
        </div>

        {loading && <LoadingBlock label="Loading cases…" />}
        {error && <ErrorBlock message={error} />}
        {!loading && !error && filtered.length === 0 && <EmptyState title="No cases match" description="Try a different filter." />}

        {!loading && filtered.length > 0 && (
          <div className="scroll-x">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Incident</th>
                  <th>Fraud type</th>
                  <th>Amount</th>
                  <th>Status</th>
                  <th>Assigned</th>
                  <th>Filed</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((c) => (
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
                    <td className="dim mono" style={{ fontSize: "0.75rem" }}>
                      {c.assigned_investigator_id ? c.assigned_investigator_id.slice(0, 8) : "—"}
                    </td>
                    <td className="dim">{new Date(c.filed_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AppShell>
  );
}
