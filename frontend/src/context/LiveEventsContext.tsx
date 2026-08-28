import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useAuth } from "./AuthContext";
import { useLiveEvents, type ConnectionStatus, type KeyedLiveEvent } from "../hooks/useLiveEvents";
import type { LiveEvent } from "../types/domain";

interface LiveEventsContextValue {
  status: ConnectionStatus;
  events: LiveEvent[];
  keyedEvents: KeyedLiveEvent[];
  lastEvent: LiveEvent | null;
  activeJurisdiction: string | null;
  setActiveJurisdiction: (id: string | null) => void;
}

const LiveEventsContext = createContext<LiveEventsContextValue | undefined>(undefined);

/**
 * A single WebSocket connection for the whole authenticated session,
 * instead of a fresh one per page - so the live feed (and the "system is
 * thinking through the investigation" feeling the product is built
 * around) survives navigating between Mission Control, a case workspace,
 * and the audit trail, rather than resetting every time a component
 * mounts. investigator/supervisor are pinned to their own JWT
 * jurisdiction; auditor/admin have none by default until a page (Mission
 * Control, Risk Heatmap, or a case being opened) sets one.
 */
export function LiveEventsProvider({ children }: { children: ReactNode }) {
  const { auth } = useAuth();
  const [activeJurisdiction, setActiveJurisdiction] = useState<string | null>(auth?.jurisdictionId ?? null);

  useEffect(() => {
    if (auth?.jurisdictionId) setActiveJurisdiction(auth.jurisdictionId);
  }, [auth?.jurisdictionId]);

  const { status, events, keyedEvents, lastEvent } = useLiveEvents(auth?.token ?? null, activeJurisdiction);

  return (
    <LiveEventsContext.Provider value={{ status, events, keyedEvents, lastEvent, activeJurisdiction, setActiveJurisdiction }}>
      {children}
    </LiveEventsContext.Provider>
  );
}

export function useLiveEventsContext(): LiveEventsContextValue {
  const ctx = useContext(LiveEventsContext);
  if (!ctx) {
    throw new Error("useLiveEventsContext must be used within a LiveEventsProvider");
  }
  return ctx;
}
