import { useState, type ReactNode } from "react";
import { Menu } from "lucide-react";
import { GlobalNav, LiveIndicator } from "./GlobalNav";
import { GlobalSearch } from "./GlobalSearch";
import { NotificationCenter } from "./NotificationCenter";
import { useLiveEventsContext } from "../context/LiveEventsContext";

export function AppShell({
  children,
  crumb,
}: {
  children: ReactNode;
  crumb?: ReactNode;
}) {
  const [navOpen, setNavOpen] = useState(false);
  const { status: liveStatus } = useLiveEventsContext();

  return (
    <div className="app-shell">
      <GlobalNav className={navOpen ? "open" : ""} onNavigate={() => setNavOpen(false)} />
      {navOpen && <div className="nav-scrim" onClick={() => setNavOpen(false)} />}

      <div className="app-main">
        <header className="app-topbar">
          <button
            className="btn btn-ghost btn-sm nav-toggle-btn"
            onClick={() => setNavOpen((v) => !v)}
            aria-label="Toggle navigation"
          >
            <Menu size={16} />
          </button>
          {crumb && <div className="crumb">{crumb}</div>}
          <div className="app-topbar-spacer" />
          <GlobalSearch />
          <NotificationCenter />
          {liveStatus && <LiveIndicator status={liveStatus} />}
        </header>
        <main className="app-content">{children}</main>
      </div>
    </div>
  );
}
