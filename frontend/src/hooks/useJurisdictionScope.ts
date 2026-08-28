import { useEffect, useMemo, useState } from "react";
import type { ComplaintSummary } from "../types/domain";

/**
 * There is no `GET /v1/jurisdictions` list endpoint and no jurisdiction
 * `name` field anywhere in the API - investigator/supervisor are always
 * scoped to their own JWT jurisdiction_id, but auditor/admin have none and
 * must pick one to view (the risk-field and WS endpoints both require it).
 * Rather than hardcode a UUID->name table that would drift on every reseed,
 * selectable options are derived honestly from jurisdiction_ids actually
 * seen in loaded complaint data.
 */
export function useJurisdictionScope(fixedJurisdictionId: string | null, seen: ComplaintSummary[] | null) {
  const options = useMemo(() => {
    if (fixedJurisdictionId) return [fixedJurisdictionId];
    const set = new Set<string>();
    (seen ?? []).forEach((c) => {
      if (c.jurisdiction_id) set.add(c.jurisdiction_id);
    });
    return Array.from(set);
  }, [fixedJurisdictionId, seen]);

  const [selected, setSelected] = useState<string | null>(fixedJurisdictionId);

  useEffect(() => {
    if (fixedJurisdictionId) {
      setSelected(fixedJurisdictionId);
      return;
    }
    setSelected((prev) => (prev && options.includes(prev) ? prev : options[0] ?? null));
  }, [fixedJurisdictionId, options]);

  return { options, selected, setSelected, isFixed: !!fixedJurisdictionId };
}

export function shortJurisdiction(id: string | null): string {
  if (!id) return "—";
  return `${id.slice(0, 8)}…`;
}
