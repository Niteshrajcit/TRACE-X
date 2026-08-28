/**
 * Hand-mirrored from the backend Pydantic schemas (backend/app/modules/**\/schemas.py,
 * backend/app/graph/schemas.py, backend/app/auth/schemas.py, backend/app/db/models/enums.py,
 * backend/app/events/topics.py). Every shape here was confirmed against the real running
 * backend or its schema source during the frontend build - nothing here is speculative.
 */

// --- enums --------------------------------------------------------------------

export type FraudType =
  | "upi_fraud"
  | "phishing"
  | "investment_scam"
  | "loan_app_fraud"
  | "other";

export type InstitutionType = "bank" | "wallet" | "merchant" | "exchange" | "other";

export type ComplaintStatus =
  | "new"
  | "graph_building"
  | "predicted"
  | "action_recommended"
  | "approved"
  | "rejected"
  | "closed";

export type UserRole =
  | "citizen_portal"
  | "investigator"
  | "supervisor"
  | "bank_liaison"
  | "auditor"
  | "admin"
  | "service";

export type ExitChannelType = "atm_cash" | "crypto_p2p" | "ecommerce_merchant";

export type TransactionChannel = "upi" | "imps" | "neft" | "card" | "cash_withdrawal";

export type InterventionActionType =
  | "physical_team_deployment"
  | "exchange_freeze_request"
  | "merchant_hold_request";

export type OptimizerMode = "coverage_maximization" | "resource_allocation";

export type DeploymentStatus = "proposed" | "approved" | "rejected";

export type AlertChannel =
  | "dashboard"
  | "sms_sim"
  | "email_sim"
  | "bank_webhook_sim"
  | "i4c_webhook_sim"
  | "exchange_webhook_sim"
  | "merchant_webhook_sim";

export type OutcomeResult =
  | "cash_out_prevented"
  | "cash_out_occurred_elsewhere"
  | "no_activity"
  | "funds_recovered_partial"
  | "funds_recovered_full";

export type ModelStage =
  | "ring_detector"
  | "corridor_predictor"
  | "location_scorer"
  | "time_window_model";

// --- complaints / cases ---------------------------------------------------------

export interface ComplaintCreateRequest {
  incident_datetime: string; // ISO 8601
  fraud_type: FraudType;
  amount: string; // Decimal, sent as string to avoid float precision loss
  location_text: string;
  location_lat?: number | null;
  location_lon?: number | null;
  institution_name: string;
  institution_type: InstitutionType;
  transaction_reference?: string | null;
  victim_account_number?: string | null;
  victim_phone?: string | null;
  victim_email?: string | null;
  description: string;
  evidence_notes: string[];
  jurisdiction_hint?: string | null;
  idempotency_key?: string | null;
}

export interface ComplaintCreateResponse {
  complaint_id: string;
  incident_reference: string;
  status: ComplaintStatus;
  filed_at: string;
}

export interface ComplaintSummary {
  complaint_id: string;
  incident_reference: string;
  fraud_type: FraudType;
  amount: string;
  status: ComplaintStatus;
  filed_at: string;
  jurisdiction_id: string | null;
  assigned_investigator_id: string | null;
}

export interface GraphSummary {
  ring_count: number;
  total_members: number;
}

export interface DeploymentHistoryEntry {
  deployment_id: string;
  optimizer_mode: OptimizerMode | null;
  status: DeploymentStatus;
  expected_coverage_total: number | null;
  naive_baseline_coverage: number | null;
  decided_by: string | null;
  decided_at: string | null;
}

export interface ComplaintDetail extends ComplaintSummary {
  incident_datetime: string;
  location_text: string;
  location_lat: number | null;
  location_lon: number | null;
  institution_name: string;
  institution_type: InstitutionType;
  transaction_reference: string | null;
  description: string;
  evidence_notes: string[];
  is_demo_data: boolean;
  latest_prediction: PredictionResponse | null;
  graph_summary: GraphSummary | null;
  deployment_history: DeploymentHistoryEntry[];
}

export interface AssignCaseRequest {
  investigator_id: string;
}

export interface CloseCaseRequest {
  reason: string;
}

// --- rings / network -------------------------------------------------------------

export interface RingSummary {
  ring_id: string;
  detected_at: string;
  algorithm_name: string;
  algorithm_version: string;
  member_count: number;
  member_account_ids: string[];
  transaction_count: number;
  total_amount: string;
  average_transaction_amount: string | null;
  transaction_velocity: string | null;
  burst_ratio: string | null;
  fan_in_count: number;
  fan_out_count: number;
  fan_in_amount: string;
  fan_out_amount: string;
  device_count: number;
  ip_count: number;
  phone_count: number;
  vpa_count: number;
  geographic_spread_km: string | null;
  cohesion_score: string;
  exit_channel_ids: string[];
}

export interface RingListResponse {
  rings: RingSummary[];
}

// --- prediction --------------------------------------------------------------

export interface ExitVector {
  bearing_deg: number;
  distance_range_km: number[];
  confidence_cone_deg: number;
  exit_channel_type: string;
}

export interface ModelVersions {
  ring: string | null;
  corridor: string | null;
  exit_channel: string | null;
  time_window: string | null;
}

export interface RankedLocation {
  exit_channel_id: string;
  h3_cell: string;
  channel_type: ExitChannelType;
  probability: number;
  time_window_min: [number, number];
  confidence_interval: [number, number];
}

export interface PredictionResponse {
  prediction_id: string;
  generated_at: string;
  exit_vector: ExitVector;
  ranked_locations: RankedLocation[] | null;
  model_versions: ModelVersions;
  disclaimer: string;
}

// --- explanation ---------------------------------------------------------------

export interface TopFactor {
  feature: string;
  weight: number;
  direction: "increases_risk" | "decreases_risk" | string;
}

export interface GraphPath {
  real_path: string[];
  predicted_exit_channel_id: string | null;
  path_complete: boolean;
}

export interface ComparableCase {
  complaint_id: string;
  similarity_score: number;
  summary: string;
}

export interface ExplanationResponse {
  available: boolean;
  reason: string | null;
  prediction_id: string | null;
  exit_channel_id: string | null;
  top_factors: TopFactor[];
  graph_path: GraphPath | null;
  comparable_cases: ComparableCase[];
  plain_language: string | null;
}

// --- optimizer / deployments -----------------------------------------------------

export interface LatLon {
  lat: number;
  lon: number;
}

export interface OptimizeDeploymentRequest {
  team_count?: number | null;
  team_locations?: LatLon[] | null;
  request_slot_count?: number | null;
}

export interface DeploymentAssignment {
  team_id: string;
  exit_channel_id: string;
  expected_coverage: number;
  travel_time_min: number;
}

export interface OptimizeDeploymentResponse {
  deployment_id: string;
  optimizer_mode: OptimizerMode;
  assignment: DeploymentAssignment[];
  expected_coverage_total: number;
  naive_baseline_coverage: number;
}

export interface DecisionRequest {
  decision: "approved" | "rejected";
  justification: string;
}

export interface DecisionResponse {
  deployment_id: string;
  status: string;
  decided_by: string | null;
  decided_at: string | null;
}

export interface OutcomeRequest {
  result: OutcomeResult;
  notes?: string | null;
}

export interface OutcomeResponse {
  outcome_id: string;
  deployment_id: string;
  result: OutcomeResult;
  recorded_by: string;
  recorded_at: string;
  feature_snapshot_id: string | null;
}

// --- risk field ------------------------------------------------------------------

export interface RiskFieldCell {
  h3_cell: string;
  score: number;
}

export interface RiskFieldResponse {
  h3_cells: RiskFieldCell[];
  generated_for: string;
}

// --- audit / models ----------------------------------------------------------------

export interface AuditEventResponse {
  event_id: string;
  seq_no: number;
  event_type: string;
  actor_id: string | null;
  subject_type: string;
  subject_id: string | null;
  occurred_at: string;
  this_hash: string;
}

export interface VerifyChainResponse {
  valid: boolean;
  broken_at_seq: number | null;
}

export interface ModelRegistryEntryResponse {
  model_id: string;
  stage: ModelStage;
  version: string;
  trained_at: string;
  metrics: Record<string, number>;
  is_active: boolean;
}

// --- auth ------------------------------------------------------------------------

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  role: UserRole;
  jurisdiction_id: string | null;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    request_id: string | null;
  };
}

// --- realtime (app/events/topics.py) -----------------------------------------------

export interface ComplaintCreatedEvent {
  type: "complaint.created";
  complaint_id: string;
  incident_reference: string;
  fraud_type: FraudType;
  amount: string;
  status: ComplaintStatus;
  filed_at: string;
  jurisdiction_id: string | null;
}

// Every field below was re-checked directly against its real
// `dispatcher.publish(...)` call site in the backend (not just the topic
// name list in app/events/topics.py) - several of these had drifted from
// the real payload shape (missing real fields, or carrying a
// `jurisdiction_id` the backend never actually sends). Fixed here rather
// than left inaccurate, since Mission Control's live feed now resolves
// and displays these directly.

export interface IntelligenceStartedEvent {
  type: "intelligence.started";
  complaint_id: string;
  stage: string;
}

export interface GraphUpdatedEvent {
  type: "graph.updated";
  complaint_id: string;
  txn_id: string;
  hop_index: number;
}

export interface TransactionIngestedEvent {
  type: "transaction.ingested";
  txn_id: string;
  complaint_id: string;
  amount: string;
  channel: TransactionChannel;
  hop_index: number;
  occurred_at: string;
}

export interface RingDetectedEvent {
  type: "ring.detected";
  complaint_id: string;
  communities_detected: number;
  graph_nodes: number;
  graph_edges: number;
  modularity: number;
  algorithm: string;
}

export interface CorridorPredictionCompletedEvent {
  type: "corridor_prediction.completed";
  complaint_id: string;
  ring_id: string;
  prediction_id: string;
  exit_vector: ExitVector;
  model_version_corridor: string;
}

export interface ExitPredictionCompletedEvent {
  type: "exit_prediction.completed";
  complaint_id: string;
  ring_id: string;
  prediction_id: string;
  ranked_locations: RankedLocation[];
  model_version_location: string;
  model_version_time: string;
}

export interface RiskFieldUpdatedEvent {
  type: "risk_field.updated";
  jurisdiction_id: string | null;
  changed_cells: string[];
}

export interface ExplanationGeneratedEvent {
  type: "explanation.generated";
  complaint_id: string;
  prediction_id: string;
  jurisdiction_id: string | null;
}

export interface InterventionRecommendedEvent {
  type: "intervention.recommended";
  complaint_id: string;
  deployment_id: string;
  expected_coverage_total: number;
  jurisdiction_id: string | null;
}

export interface ApprovalRequiredEvent {
  type: "approval.required";
  complaint_id: string;
  deployment_id: string;
  jurisdiction_id: string | null;
}

export interface InterventionApprovedEvent {
  type: "intervention.approved";
  complaint_id: string;
  deployment_id: string;
  decision: "approved";
  jurisdiction_id: string | null;
}

export interface InterventionRejectedEvent {
  type: "intervention.rejected";
  complaint_id: string;
  deployment_id: string;
  decision: "rejected";
  jurisdiction_id: string | null;
}

export interface ActionDispatchedEvent {
  type: "action.dispatched";
  complaint_id: string;
  deployment_id: string;
  alert_id: string;
  channel: AlertChannel;
  delivered: boolean;
  jurisdiction_id: string | null;
}

export interface OutcomeRecordedEvent {
  type: "outcome.recorded";
  complaint_id: string;
  deployment_id: string;
  result: OutcomeResult;
  jurisdiction_id: string | null;
}

export interface FeedbackCreatedEvent {
  type: "feedback.created";
  complaint_id: string;
  feature_snapshot_id: string;
  jurisdiction_id: string | null;
}

export type LiveEvent =
  | ComplaintCreatedEvent
  | IntelligenceStartedEvent
  | GraphUpdatedEvent
  | TransactionIngestedEvent
  | RingDetectedEvent
  | CorridorPredictionCompletedEvent
  | ExitPredictionCompletedEvent
  | RiskFieldUpdatedEvent
  | ExplanationGeneratedEvent
  | InterventionRecommendedEvent
  | ApprovalRequiredEvent
  | InterventionApprovedEvent
  | InterventionRejectedEvent
  | ActionDispatchedEvent
  | OutcomeRecordedEvent
  | FeedbackCreatedEvent;
