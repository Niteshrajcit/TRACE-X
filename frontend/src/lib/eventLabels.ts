import type { LiveEvent } from "../types/domain";

/** Human-readable labels for every real event in app/events/topics.py -
 * shared between anywhere a live event needs to render as text (the
 * Mission Control feed, the notification center, per-case live feeds). */
export const EVENT_LABEL: Record<LiveEvent["type"], string> = {
  "complaint.created": "New complaint filed",
  "intelligence.started": "Intelligence pipeline started",
  "graph.updated": "Transaction graph updated",
  "transaction.ingested": "Transaction ingested",
  "ring.detected": "Fraud ring detected",
  "corridor_prediction.completed": "Corridor prediction computed",
  "exit_prediction.completed": "Exit prediction computed",
  "risk_field.updated": "Risk field refreshed",
  "explanation.generated": "Explanation generated",
  "intervention.recommended": "Intervention recommended",
  "approval.required": "Approval required",
  "intervention.approved": "Intervention approved",
  "intervention.rejected": "Intervention rejected",
  "action.dispatched": "Action dispatched",
  "outcome.recorded": "Outcome recorded",
  "feedback.created": "Feedback recorded for retraining",
};

export function eventLabel(event: LiveEvent): string {
  return EVENT_LABEL[event.type] ?? event.type;
}

/** Not every real event carries a complaint_id (risk_field.updated is
 * jurisdiction-scoped only) - this is the one place that distinction is
 * checked, instead of every consumer re-deriving it. */
export function eventComplaintId(event: LiveEvent): string | null {
  return "complaint_id" in event ? event.complaint_id : null;
}
