import { createContext, useContext } from "react";
import type { ComplaintDetail, RingSummary } from "../types/domain";

export interface CaseContextValue {
  complaint: ComplaintDetail;
  rings: RingSummary[];
  reloadComplaint: () => void;
  reloadRings: () => void;
}

const CaseContext = createContext<CaseContextValue | undefined>(undefined);

export const CaseContextProvider = CaseContext.Provider;

export function useCase(): CaseContextValue {
  const ctx = useContext(CaseContext);
  if (!ctx) {
    throw new Error("useCase must be used within a CaseWorkspace");
  }
  return ctx;
}
