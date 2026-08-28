import { useEffect } from "react";
import { NavLink, Outlet, useLocation, useParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { getComplaint, getComplaintRings } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { CaseContextProvider } from "../context/CaseContext";
import { InvestigationFocusProvider } from "../context/InvestigationFocusContext";
import { useApi } from "../hooks/useApi";
import { AppShell } from "./AppShell";
import { CASE_TABS } from "./caseTabs";
import { ErrorBlock, LoadingBlock, Pill, RiskPill } from "../components/ui/primitives";
import { useLiveEventsContext } from "../context/LiveEventsContext";
import { useRecentCases } from "../context/RecentCasesContext";

const STATUS_TONE: Record<string, "neutral" | "accent" | "decision" | "ok"> = {
  new: "neutral",
  graph_building: "accent",
  predicted: "accent",
  action_recommended: "decision",
  approved: "ok",
  rejected: "neutral",
  closed: "neutral",
};

export function CaseWorkspace() {
  const { auth } = useAuth();
  const { complaintId } = useParams<{ complaintId: string }>();
  const token = auth!.token;

  const complaintState = useApi(() => getComplaint(token, complaintId!), [token, complaintId]);
  const ringsState = useApi(() => getComplaintRings(token, complaintId!), [token, complaintId]);

  const { setActiveJurisdiction } = useLiveEventsContext();
  useEffect(() => {
    if (!auth!.jurisdictionId && complaintState.data?.jurisdiction_id) {
      setActiveJurisdiction(complaintState.data.jurisdiction_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [complaintState.data?.jurisdiction_id]);

  const { touchCase } = useRecentCases();
  useEffect(() => {
    if (complaintState.data) {
      touchCase({
        complaintId: complaintState.data.complaint_id,
        incidentReference: complaintState.data.incident_reference,
        status: complaintState.data.status,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [complaintState.data?.complaint_id, complaintState.data?.status]);

  const location = useLocation();
  const activeTab = CASE_TABS.find((tab) => {
    const suffix = tab.to ? `/${tab.to}` : "";
    return location.pathname === `/cases/${complaintId}${suffix}`;
  });

  // Only the true first load (no data has ever arrived yet) replaces the
  // tree with a full-page loading/error state. useApi's reload() sets
  // loading:true without clearing the previous data - so on every
  // subsequent reload (assign/close, and now F7's generate/approve/reject,
  // all call reloadComplaint()), complaintState.data was already
  // populated. Gating on `loading` alone unmounted this entire subtree -
  // InvestigationFocusProvider included - on every single reload, silently
  // wiping ring/account/exit-channel focus and any page-local state (F7's
  // session-cached optimizer results) each time. Found via live
  // verification of F7's generate-then-focus flow, not theoretical.
  if (!complaintState.data) {
    if (complaintState.loading) {
      return (
        <AppShell>
          <LoadingBlock label="Loading case…" />
        </AppShell>
      );
    }
    return (
      <AppShell>
        <ErrorBlock message={complaintState.error ?? "This case could not be loaded."} />
      </AppShell>
    );
  }

  const complaint = complaintState.data;

  return (
    <AppShell
      crumb={
        <>
          <span>Cases</span>
          <span className="sep">/</span>
          {activeTab && activeTab.to !== "" ? (
            <>
              <span>{complaint.incident_reference}</span>
              <span className="sep">/</span>
              <span className="current">{activeTab.label}</span>
            </>
          ) : (
            <span className="current">{complaint.incident_reference}</span>
          )}
        </>
      }
    >
      <CaseContextProvider
        value={{
          complaint,
          rings: ringsState.data?.rings ?? [],
          reloadComplaint: complaintState.reload,
          reloadRings: ringsState.reload,
        }}
      >
        <div className="stack" style={{ gap: 0, margin: "-24px -24px 0" }}>
          <div className="case-header">
            <div className="row between wrap" style={{ marginBottom: 10 }}>
              <div className="row" style={{ gap: 10 }}>
                <h1 className="mono">{complaint.incident_reference}</h1>
                <Pill tone={STATUS_TONE[complaint.status]}>{complaint.status.replace(/_/g, " ")}</Pill>
                {complaint.is_demo_data && <span className="badge-demo">Demo / synthetic</span>}
              </div>
              {complaint.latest_prediction && (
                <RiskPill
                  level={
                    complaint.latest_prediction.exit_vector.confidence_cone_deg <= 30
                      ? "critical"
                      : complaint.latest_prediction.exit_vector.confidence_cone_deg <= 60
                        ? "high"
                        : "medium"
                  }
                  label="active prediction"
                />
              )}
            </div>
            <div className="row wrap muted" style={{ gap: 18, fontSize: "0.8rem" }}>
              <span>
                <span className="dim">Fraud type </span>
                {complaint.fraud_type.replace(/_/g, " ")}
              </span>
              <span className="tabular">
                <span className="dim">Amount </span>₹{Number(complaint.amount).toLocaleString("en-IN")}
              </span>
              <span>
                <span className="dim">Filed </span>
                {new Date(complaint.filed_at).toLocaleString()}
              </span>
              <span>
                <span className="dim">Assigned </span>
                {complaint.assigned_investigator_id ? complaint.assigned_investigator_id.slice(0, 8) : "Unassigned"}
              </span>
            </div>
          </div>

          <nav className="case-tabs">
            {CASE_TABS.map((tab) => (
              <NavLink
                key={tab.to}
                to={tab.to}
                end={tab.end}
                className={({ isActive }) => `case-tab${isActive ? " active" : ""}`}
              >
                <tab.icon size={14} />
                {tab.label}
              </NavLink>
            ))}
          </nav>
        </div>

        <div style={{ paddingTop: 24 }}>
          <InvestigationFocusProvider key={complaintId}>
            <AnimatePresence mode="wait">
              <motion.div
                key={location.pathname}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.18, ease: [0.4, 0, 0.2, 1] }}
              >
                <Outlet />
              </motion.div>
            </AnimatePresence>
          </InvestigationFocusProvider>
        </div>
      </CaseContextProvider>
    </AppShell>
  );
}
