import { NavLink, useNavigate } from "react-router-dom";
import { FolderKanban, LayoutDashboard, LogOut, Map as MapIcon, ScrollText } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useRecentCases } from "../context/RecentCasesContext";
import { CASE_TABS } from "./caseTabs";

const NAV_ITEMS = [
  { to: "/mission-control", label: "Mission Control", icon: LayoutDashboard },
  { to: "/cases", label: "Cases", icon: FolderKanban },
  { to: "/risk-intelligence", label: "Risk Intelligence", icon: MapIcon },
  { to: "/audit", label: "Audit Trail", icon: ScrollText },
];

export function GlobalNav({ onNavigate, className = "" }: { onNavigate?: () => void; className?: string }) {
  const { auth, logout } = useAuth();
  const { recentCases, activeCaseId, setActiveCaseId } = useRecentCases();
  const navigate = useNavigate();

  const activeCase = recentCases.find((c) => c.complaintId === activeCaseId) ?? recentCases[0] ?? null;

  function switchCase(complaintId: string) {
    setActiveCaseId(complaintId);
    navigate(`/cases/${complaintId}`);
    onNavigate?.();
  }

  return (
    <nav className={`global-nav ${className}`}>
      <div className="global-nav-brand">
        <span className="mark">TX</span>
        <div className="global-nav-text">
          <div className="name">TRACE-X</div>
          <div className="tagline">Intelligence Console</div>
        </div>
      </div>

      <div className="global-nav-section">
        <div className="global-nav-label">
          <span className="global-nav-text">Investigate</span>
        </div>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            onClick={onNavigate}
            className={({ isActive }) => `global-nav-link${isActive ? " active" : ""}`}
          >
            <item.icon size={16} />
            <span className="global-nav-text">{item.label}</span>
          </NavLink>
        ))}
      </div>

      <div className="global-nav-section">
        <div className="global-nav-label global-nav-text">Case workspace</div>

        {recentCases.length > 0 && (
          <div className="case-switcher global-nav-text">
            <select
              aria-label="Switch active case"
              value={activeCase?.complaintId ?? ""}
              onChange={(e) => switchCase(e.target.value)}
            >
              {recentCases.map((c) => (
                <option key={c.complaintId} value={c.complaintId}>
                  {c.incidentReference} · {c.status.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </div>
        )}

        {activeCase ? (
          CASE_TABS.map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to ? `/cases/${activeCase.complaintId}/${tab.to}` : `/cases/${activeCase.complaintId}`}
              onClick={onNavigate}
              className={({ isActive }) => `global-nav-link${isActive ? " active" : ""}`}
            >
              <tab.icon size={16} />
              <span className="global-nav-text">{tab.label}</span>
            </NavLink>
          ))
        ) : (
          <div className="global-nav-hint">
            {CASE_TABS.map((tab) => (
              <div key={tab.to} className="global-nav-link disabled">
                <tab.icon size={16} />
                <span className="global-nav-text">{tab.label}</span>
              </div>
            ))}
            <p className="hint global-nav-text" style={{ padding: "6px 10px 2px" }}>
              Open a case from the list to explore its network, corridors, predictions and interventions.
            </p>
          </div>
        )}
      </div>

      <div className="global-nav-footer">
        <div className="session-card">
          <span className="session-avatar">{(auth?.role ?? "?").slice(0, 2)}</span>
          <div className="session-meta global-nav-text">
            <div className="session-role">{auth?.role.replace(/_/g, " ")}</div>
            <div className="session-scope">
              {auth?.jurisdictionId ? "Jurisdiction-scoped" : "All jurisdictions"}
            </div>
          </div>
        </div>
        <button className="btn btn-ghost btn-sm btn-block nav-signout" style={{ marginTop: 8, justifyContent: "flex-start" }} onClick={logout}>
          <LogOut size={14} />
          <span className="global-nav-text">Sign out</span>
        </button>
      </div>
    </nav>
  );
}

export function LiveIndicator({ status }: { status: "connecting" | "live" | "reconnecting" | "closed" }) {
  const label =
    status === "live" ? "Live" : status === "reconnecting" ? "Reconnecting…" : status === "connecting" ? "Connecting…" : "Offline";
  return (
    <span className={`live-indicator ${status}`}>
      <span className="live-dot" />
      {label}
    </span>
  );
}
