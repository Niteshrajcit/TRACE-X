import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Bell } from "lucide-react";
import { useLiveEventsContext } from "../context/LiveEventsContext";
import { eventComplaintId, eventLabel } from "../lib/eventLabels";

/**
 * Readiness report §2.5/§6: there was no notification surface at all -
 * live events were only visible on whichever page happened to render its
 * own feed panel. This is the one, global place every real WS event
 * (already flowing through LiveEventsContext) is visible regardless of
 * what page the investigator is looking at.
 */
export function NotificationCenter() {
  const { events, keyedEvents } = useLiveEventsContext();
  const [open, setOpen] = useState(false);
  const [seenCount, setSeenCount] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  const unread = Math.max(0, events.length - seenCount);

  useEffect(() => {
    function onClickAway(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickAway);
    return () => document.removeEventListener("mousedown", onClickAway);
  }, []);

  function toggle() {
    setOpen((prev) => {
      const next = !prev;
      if (next) setSeenCount(events.length);
      return next;
    });
  }

  return (
    <div className="notif-root" ref={rootRef}>
      <button className="btn btn-ghost btn-sm notif-bell" onClick={toggle} aria-label="Notifications">
        <Bell size={16} />
        {unread > 0 && <span className="notif-badge">{unread > 9 ? "9+" : unread}</span>}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            className="notif-panel"
            role="region"
            aria-label="Live notifications"
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.16, ease: [0.4, 0, 0.2, 1] }}
          >
            <div className="notif-panel-header">
              <span>Live intelligence feed</span>
              <span className="dim" style={{ fontSize: "var(--text-xs)" }}>
                {events.length} event{events.length === 1 ? "" : "s"} this session
              </span>
            </div>
            {events.length === 0 ? (
              <div className="notif-empty">No events yet — this fills in as the pipeline runs.</div>
            ) : (
              <div className="notif-list">
                {keyedEvents.slice(0, 30).map(({ key, event: e }) => {
                  const complaintId = eventComplaintId(e);
                  return (
                    <button
                      key={key}
                      className="notif-item"
                      disabled={!complaintId}
                      onClick={() => {
                        if (complaintId) {
                          navigate(`/cases/${complaintId}`);
                          setOpen(false);
                        }
                      }}
                    >
                      <span className="notif-dot" />
                      <span className="notif-item-label">{eventLabel(e)}</span>
                      {complaintId && <span className="notif-item-meta">{complaintId.slice(0, 8)}…</span>}
                    </button>
                  );
                })}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
