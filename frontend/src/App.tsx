import { lazy, Suspense, type ReactElement } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { LiveEventsProvider } from "./context/LiveEventsContext";
import { RecentCasesProvider } from "./context/RecentCasesContext";
import { ComplaintPortal } from "./pages/ComplaintPortal";
import { Login } from "./pages/Login";
import { LoadingBlock } from "./components/ui/primitives";

// Route-level code splitting: everything behind auth pulls in the heavier
// visualization dependencies (d3-force, h3-js, framer-motion) that the
// public login/intake pages never need. Readiness report §2.6/§8 flagged
// the single eagerly-bundled JS file as a real, growing cost; this is the
// cheapest fix that scales as more pages/visualizations are added.
const MissionControl = lazy(() => import("./pages/MissionControl").then((m) => ({ default: m.MissionControl })));
const CaseList = lazy(() => import("./pages/CaseList").then((m) => ({ default: m.CaseList })));
const RiskHeatmap = lazy(() => import("./pages/RiskHeatmap").then((m) => ({ default: m.RiskHeatmap })));
const AuditTrail = lazy(() => import("./pages/AuditTrail").then((m) => ({ default: m.AuditTrail })));
const CaseWorkspace = lazy(() => import("./layout/CaseWorkspace").then((m) => ({ default: m.CaseWorkspace })));
const CaseOverview = lazy(() => import("./pages/case/CaseOverview").then((m) => ({ default: m.CaseOverview })));
const NetworkInvestigation = lazy(() =>
  import("./pages/case/NetworkInvestigation").then((m) => ({ default: m.NetworkInvestigation }))
);
const RingsCorridors = lazy(() => import("./pages/case/RingsCorridors").then((m) => ({ default: m.RingsCorridors })));
const PredictionExplanation = lazy(() =>
  import("./pages/case/PredictionExplanation").then((m) => ({ default: m.PredictionExplanation }))
);
const InterventionApproval = lazy(() =>
  import("./pages/case/InterventionApproval").then((m) => ({ default: m.InterventionApproval }))
);
const ActionOutcomeAudit = lazy(() =>
  import("./pages/case/ActionOutcomeAudit").then((m) => ({ default: m.ActionOutcomeAudit }))
);

function RequireAuth({ children }: { children: ReactElement }) {
  const { auth } = useAuth();
  if (!auth) return <Navigate to="/login" replace />;
  return children;
}

function RouteFallback() {
  return (
    <div style={{ padding: 48 }}>
      <LoadingBlock />
    </div>
  );
}

function AppRoutes() {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        <Route path="/" element={<Navigate to="/report" replace />} />
        <Route path="/report" element={<ComplaintPortal />} />
        <Route path="/login" element={<Login />} />

        <Route path="/mission-control" element={<RequireAuth><MissionControl /></RequireAuth>} />
        <Route path="/cases" element={<RequireAuth><CaseList /></RequireAuth>} />
        <Route path="/risk-intelligence" element={<RequireAuth><RiskHeatmap /></RequireAuth>} />
        <Route path="/audit" element={<RequireAuth><AuditTrail /></RequireAuth>} />

        <Route
          path="/cases/:complaintId"
          element={
            <RequireAuth>
              <CaseWorkspace />
            </RequireAuth>
          }
        >
          <Route index element={<CaseOverview />} />
          <Route path="network" element={<NetworkInvestigation />} />
          <Route path="rings" element={<RingsCorridors />} />
          <Route path="prediction" element={<PredictionExplanation />} />
          <Route path="intervention" element={<InterventionApproval />} />
          <Route path="audit" element={<ActionOutcomeAudit />} />
        </Route>

        <Route path="*" element={<Navigate to="/report" replace />} />
      </Routes>
    </Suspense>
  );
}

export function App() {
  return (
    <AuthProvider>
      <LiveEventsProvider>
        <RecentCasesProvider>
          <AppRoutes />
        </RecentCasesProvider>
      </LiveEventsProvider>
    </AuthProvider>
  );
}
