import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Search } from "lucide-react";
import { listComplaints } from "../api/client";
import { useAuth } from "../context/AuthContext";
import type { ComplaintSummary } from "../types/domain";

/**
 * Readiness report §2.5/§6: no way to jump to a case by reference from
 * anywhere except the Cases list's own filter. Searches over the
 * complaint list already scoped to this investigator's role/jurisdiction
 * by the real `GET /v1/complaints` endpoint - no new backend surface,
 * just a shell-level way to reach it from anywhere.
 */
export function GlobalSearch() {
  const { auth } = useAuth();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [complaints, setComplaints] = useState<ComplaintSummary[] | null>(null);
  const [loading, setLoading] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClickAway(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickAway);
    return () => document.removeEventListener("mousedown", onClickAway);
  }, []);

  function ensureLoaded() {
    if (complaints || loading) return;
    setLoading(true);
    listComplaints(auth!.token)
      .then(setComplaints)
      .finally(() => setLoading(false));
  }

  const results = useMemo(() => {
    if (!query.trim() || !complaints) return [];
    const q = query.trim().toLowerCase();
    return complaints
      .filter((c) => c.incident_reference.toLowerCase().includes(q) || c.fraud_type.replace(/_/g, " ").includes(q))
      .slice(0, 8);
  }, [query, complaints]);

  function go(complaintId: string) {
    navigate(`/cases/${complaintId}`);
    setOpen(false);
    setQuery("");
  }

  return (
    <div className="search-root" ref={rootRef}>
      <div className="search-box">
        <Search size={14} className="search-icon" />
        <input
          placeholder="Search cases by reference…"
          value={query}
          onFocus={() => {
            ensureLoaded();
            setOpen(true);
          }}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && results[0]) go(results[0].complaint_id);
            if (e.key === "Escape") setOpen(false);
          }}
        />
        <kbd className="kbd search-kbd">/</kbd>
      </div>

      <AnimatePresence>
        {open && query.trim() && (
          <motion.div
            className="notif-panel search-results"
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.16, ease: [0.4, 0, 0.2, 1] }}
          >
            {loading && <div className="notif-empty">Loading cases…</div>}
            {!loading && results.length === 0 && <div className="notif-empty">No matching cases.</div>}
            {!loading && results.length > 0 && (
              <div className="notif-list">
                {results.map((c) => (
                  <button key={c.complaint_id} className="notif-item" onClick={() => go(c.complaint_id)}>
                    <span className="notif-dot" />
                    <span className="notif-item-label mono">{c.incident_reference}</span>
                    <span className="notif-item-meta">{c.status.replace(/_/g, " ")}</span>
                  </button>
                ))}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
