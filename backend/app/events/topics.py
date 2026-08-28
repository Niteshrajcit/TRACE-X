"""
Canonical event names, locked in docs/PRODUCT_EXPERIENCE.md §4 and
docs/ARCHITECTURE.md §4. Phase 1 only ever publishes COMPLAINT_CREATED;
the rest are declared here now so Phase 2+ never has to invent a name that
doesn't match what the docs and the frontend contract already promise.
"""

COMPLAINT_CREATED = "complaint.created"
INTELLIGENCE_STARTED = "intelligence.started"
TRANSACTION_INGESTED = "transaction.ingested"  # [Phase 2A] was referenced throughout the docs
# (ARCHITECTURE.md, API_CONTRACT.md, AI_ML_ARCHITECTURE.md) but missing from this module -
# added now that POST /v1/transactions/ingest actually emits it.
GRAPH_UPDATED = "graph.updated"
RING_DETECTED = "ring.detected"  # [Phase 2B] new - not in the original PRODUCT_EXPERIENCE.md §4
# event table, which stopped at graph.updated -> exit_prediction.completed. Added here and in
# that table (see PRODUCT_EXPERIENCE.md's Phase 2B note) because ring detection is a genuine
# pipeline stage between the graph builder and the corridor predictor.
CORRIDOR_PREDICTION_COMPLETED = "corridor_prediction.completed"  # [Phase 2C] explicit event
# for AI_ML_ARCHITECTURE.md §3's Corridor/Exit-Vector Predictor - deliberately its own name,
# not a reuse of EXIT_PREDICTION_COMPLETED below. Pipeline: RING_DETECTED -> corridor predictor
# -> persist prediction -> CORRIDOR_PREDICTION_COMPLETED.
EXIT_PREDICTION_COMPLETED = "exit_prediction.completed"  # reserved for Phase 2D (§4, Exit-Channel
# + Time-Window Scorer) - not emitted by Phase 2C's corridor predictor.
SPATIOTEMPORAL_PREDICTION_COMPLETED = "spatiotemporal_prediction.completed"
RISK_FIELD_UPDATED = "risk_field.updated"
EXPLANATION_GENERATED = "explanation.generated"
INTERVENTION_RECOMMENDED = "intervention.recommended"
APPROVAL_REQUIRED = "approval.required"
INTERVENTION_APPROVED = "intervention.approved"
INTERVENTION_REJECTED = "intervention.rejected"
ACTION_DISPATCHED = "action.dispatched"
OUTCOME_RECORDED = "outcome.recorded"
FEEDBACK_CREATED = "feedback.created"
