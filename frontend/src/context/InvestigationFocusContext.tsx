import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

/**
 * The thing every case-scoped page above the level of "which case is
 * open" was missing (readiness report §11): a single, shared notion of
 * "what is currently under investigation" - a ring, an account, a
 * candidate exit channel - so selecting something on one tab has a real
 * effect when the investigator switches to another, instead of each of
 * the six case pages living in total isolation from one another.
 *
 * Scoped per case (provided inside CaseWorkspace, not at the app root) -
 * focus is naturally case-specific and should reset when the
 * investigator moves to a different case, not leak between them.
 */
export interface InvestigationFocus {
  selectedRingId: string | null;
  selectedAccountId: string | null;
  selectedExitChannelId: string | null;
}

interface InvestigationFocusContextValue extends InvestigationFocus {
  /** Toggling setters - for a direct click on the thing itself (a ring
   * card, a graph node, a ranked-location row): clicking an
   * already-selected item deselects it. */
  selectRing: (ringId: string | null) => void;
  selectAccount: (accountId: string | null) => void;
  selectExitChannel: (exitChannelId: string | null) => void;
  /** Non-toggling setter - for deriving one selection from another (e.g.
   * NetworkInvestigation setting the owning ring when an account is
   * clicked). Using the toggling setter here would accidentally clear an
   * already-matching selection instead of confirming it. */
  setRingFocus: (ringId: string | null) => void;
  clear: () => void;
}

const InvestigationFocusContext = createContext<InvestigationFocusContextValue | undefined>(undefined);

export function InvestigationFocusProvider({ children }: { children: ReactNode }) {
  const [selectedRingId, setSelectedRingId] = useState<string | null>(null);
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);
  const [selectedExitChannelId, setSelectedExitChannelId] = useState<string | null>(null);

  const value = useMemo<InvestigationFocusContextValue>(
    () => ({
      selectedRingId,
      selectedAccountId,
      selectedExitChannelId,
      selectRing: (id) => setSelectedRingId((prev) => (prev === id ? null : id)),
      selectAccount: (id) => setSelectedAccountId((prev) => (prev === id ? null : id)),
      selectExitChannel: (id) => setSelectedExitChannelId((prev) => (prev === id ? null : id)),
      setRingFocus: (id) => setSelectedRingId(id),
      clear: () => {
        setSelectedRingId(null);
        setSelectedAccountId(null);
        setSelectedExitChannelId(null);
      },
    }),
    [selectedRingId, selectedAccountId, selectedExitChannelId]
  );

  return <InvestigationFocusContext.Provider value={value}>{children}</InvestigationFocusContext.Provider>;
}

export function useInvestigationFocus(): InvestigationFocusContextValue {
  const ctx = useContext(InvestigationFocusContext);
  if (!ctx) {
    throw new Error("useInvestigationFocus must be used within an InvestigationFocusProvider");
  }
  return ctx;
}
