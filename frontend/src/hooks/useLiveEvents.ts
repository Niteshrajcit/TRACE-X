import { useEffect, useMemo, useRef, useState } from "react";
import { WS_BASE_URL } from "../api/client";
import type { LiveEvent } from "../types/domain";

export type ConnectionStatus = "connecting" | "live" | "reconnecting" | "closed";

/** A live event tagged with a stable, client-assigned sequence key - the
 * WS payload itself carries no unique id, but a list that prepends new
 * events needs one so an entrance animation can tell "a new item arrived"
 * apart from "an existing item's position shifted" (see readiness report
 * §12: live-event entry animation). */
export interface KeyedLiveEvent {
  key: number;
  event: LiveEvent;
}

/**
 * A single, general WS connection handling the full real event set
 * (app/events/topics.py) instead of just complaint.created. The backend
 * (app/ws/router.py) scopes investigator/supervisor to their own JWT
 * jurisdiction automatically; auditor/admin have no fixed jurisdiction and
 * MUST supply one explicitly or the server closes the connection
 * (WS_1008_POLICY_VIOLATION) - callers pass the jurisdiction currently
 * being investigated for those roles.
 */
export function useLiveEvents(token: string | null, jurisdictionId: string | null | undefined) {
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [lastEvent, setLastEvent] = useState<LiveEvent | null>(null);
  const [keyedEvents, setKeyedEvents] = useState<KeyedLiveEvent[]>([]);
  const socketRef = useRef<WebSocket | null>(null);
  const seqRef = useRef(0);

  useEffect(() => {
    // app/ws/router.py always requires a jurisdiction to scope the channel
    // to - investigator/supervisor supply their own automatically via the
    // JWT, but auditor/admin have none until a page sets one explicitly
    // (WS_1008_POLICY_VIOLATION otherwise). Skip connecting rather than
    // opening a socket that is guaranteed to be rejected.
    if (!token || !jurisdictionId) {
      setStatus("closed");
      return;
    }

    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      setStatus((prev) => (prev === "live" ? "reconnecting" : "connecting"));
      const query = `token=${encodeURIComponent(token)}&jurisdiction_id=${encodeURIComponent(jurisdictionId)}`;
      const socket = new WebSocket(`${WS_BASE_URL}/v1/ws?${query}`);
      socketRef.current = socket;

      socket.onopen = () => {
        if (!cancelled) setStatus("live");
      };

      socket.onmessage = (event) => {
        if (cancelled) return;
        try {
          const payload = JSON.parse(event.data) as LiveEvent;
          setLastEvent(payload);
          seqRef.current += 1;
          setKeyedEvents((prev) => [{ key: seqRef.current, event: payload }, ...prev].slice(0, 200));
        } catch {
          // ignore malformed frames
        }
      };

      socket.onclose = () => {
        if (cancelled) return;
        setStatus("reconnecting");
        retryTimer = setTimeout(connect, 2000);
      };

      socket.onerror = () => {
        socket.close();
      };
    };

    connect();

    return () => {
      cancelled = true;
      clearTimeout(retryTimer);
      socketRef.current?.close();
    };
  }, [token, jurisdictionId]);

  const events = useMemo(() => keyedEvents.map((k) => k.event), [keyedEvents]);

  return { status, lastEvent, events, keyedEvents };
}
