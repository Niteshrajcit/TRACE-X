import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export interface RecentCase {
  complaintId: string;
  incidentReference: string;
  status: string;
  openedAt: string; // ISO timestamp - most recent first
}

interface RecentCasesContextValue {
  recentCases: RecentCase[];
  activeCaseId: string | null;
  touchCase: (c: Omit<RecentCase, "openedAt">) => void;
  setActiveCaseId: (id: string | null) => void;
}

const STORAGE_KEY = "tracex.recentCases";
const MAX_RECENT = 6;

const RecentCasesContext = createContext<RecentCasesContextValue | undefined>(undefined);

/**
 * Readiness report §7/§16: a single "last case" value isn't a case
 * switcher - opening a second case silently retargets every nav link away
 * from the first, with no way back except the Cases list. This tracks a
 * small most-recently-used list instead, so the global nav can offer a
 * real switcher between whichever cases the investigator has actually
 * had open recently, not just the one they happen to be looking at now.
 */
export function RecentCasesProvider({ children }: { children: ReactNode }) {
  const [recentCases, setRecentCases] = useState<RecentCase[]>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? (JSON.parse(raw) as RecentCase[]) : [];
    } catch {
      return [];
    }
  });
  const [activeCaseId, setActiveCaseId] = useState<string | null>(null);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(recentCases));
  }, [recentCases]);

  function touchCase(c: Omit<RecentCase, "openedAt">) {
    setRecentCases((prev) => {
      const withoutThis = prev.filter((r) => r.complaintId !== c.complaintId);
      return [{ ...c, openedAt: new Date().toISOString() }, ...withoutThis].slice(0, MAX_RECENT);
    });
    setActiveCaseId(c.complaintId);
  }

  return (
    <RecentCasesContext.Provider value={{ recentCases, activeCaseId, touchCase, setActiveCaseId }}>
      {children}
    </RecentCasesContext.Provider>
  );
}

export function useRecentCases(): RecentCasesContextValue {
  const ctx = useContext(RecentCasesContext);
  if (!ctx) {
    throw new Error("useRecentCases must be used within a RecentCasesProvider");
  }
  return ctx;
}
