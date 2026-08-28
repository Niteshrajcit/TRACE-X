import type {
  ApiErrorBody,
  AssignCaseRequest,
  AuditEventResponse,
  CloseCaseRequest,
  ComplaintCreateRequest,
  ComplaintCreateResponse,
  ComplaintDetail,
  ComplaintStatus,
  ComplaintSummary,
  DecisionRequest,
  DecisionResponse,
  ExplanationResponse,
  LoginRequest,
  LoginResponse,
  ModelRegistryEntryResponse,
  OptimizeDeploymentRequest,
  OptimizeDeploymentResponse,
  OutcomeRequest,
  OutcomeResponse,
  PredictionResponse,
  RingListResponse,
  RiskFieldResponse,
  VerifyChainResponse,
} from "../types/domain";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
export const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL ?? "ws://localhost:8000";

export class ApiError extends Error {
  status: number;
  code: string;
  requestId: string | null;

  constructor(status: number, body: ApiErrorBody) {
    super(body.error.message);
    this.status = status;
    this.code = body.error.code;
    this.requestId = body.error.request_id;
  }
}

async function request<T>(
  path: string,
  options: RequestInit & { token?: string } = {}
): Promise<T> {
  const { token, headers, ...rest } = options;
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
  });

  if (!response.ok) {
    let body: ApiErrorBody;
    try {
      body = await response.json();
    } catch {
      body = { error: { code: "UNKNOWN", message: response.statusText, request_id: null } };
    }
    throw new ApiError(response.status, body);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  if (entries.length === 0) return "";
  return "?" + entries.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&");
}

// --- auth --------------------------------------------------------------------

export function login(payload: LoginRequest): Promise<LoginResponse> {
  return request<LoginResponse>("/v1/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function checkHealth(): Promise<{ status: string; dependencies: Record<string, string> }> {
  return request("/health");
}

// --- complaints / cases --------------------------------------------------------

// Public, unauthenticated - stands in for NCRP intake.
export function createComplaint(payload: ComplaintCreateRequest): Promise<ComplaintCreateResponse> {
  return request<ComplaintCreateResponse>("/v1/complaints", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listComplaints(
  token: string,
  filters?: { status?: ComplaintStatus; assignedToMe?: boolean }
): Promise<ComplaintSummary[]> {
  const query = qs({ status: filters?.status, assigned_to_me: filters?.assignedToMe });
  return request<ComplaintSummary[]>(`/v1/complaints${query}`, { token });
}

export function getComplaint(token: string, complaintId: string): Promise<ComplaintDetail> {
  return request<ComplaintDetail>(`/v1/complaints/${complaintId}`, { token });
}

export function assignCase(
  token: string,
  complaintId: string,
  payload: AssignCaseRequest
): Promise<ComplaintSummary> {
  return request<ComplaintSummary>(`/v1/complaints/${complaintId}/assign`, {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  });
}

export function closeCase(
  token: string,
  complaintId: string,
  payload: CloseCaseRequest
): Promise<ComplaintSummary> {
  return request<ComplaintSummary>(`/v1/complaints/${complaintId}/close`, {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  });
}

export function getComplaintRings(token: string, complaintId: string): Promise<RingListResponse> {
  return request<RingListResponse>(`/v1/complaints/${complaintId}/rings`, { token });
}

export function getComplaintPrediction(
  token: string,
  complaintId: string,
  predictionId?: string
): Promise<PredictionResponse> {
  const query = qs({ prediction_id: predictionId });
  return request<PredictionResponse>(`/v1/complaints/${complaintId}/prediction${query}`, { token });
}

export function getComplaintExplanation(
  token: string,
  complaintId: string,
  opts?: { predictionId?: string; exitChannelId?: string }
): Promise<ExplanationResponse> {
  const query = qs({ prediction_id: opts?.predictionId, exit_channel_id: opts?.exitChannelId });
  return request<ExplanationResponse>(`/v1/complaints/${complaintId}/explanation${query}`, { token });
}

export function optimizeDeployment(
  token: string,
  complaintId: string,
  payload: OptimizeDeploymentRequest
): Promise<OptimizeDeploymentResponse> {
  return request<OptimizeDeploymentResponse>(`/v1/complaints/${complaintId}/optimize-deployment`, {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  });
}

// --- deployments / approval / outcome ------------------------------------------

export function decideDeployment(
  token: string,
  deploymentId: string,
  payload: DecisionRequest
): Promise<DecisionResponse> {
  return request<DecisionResponse>(`/v1/deployments/${deploymentId}/decision`, {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  });
}

export function recordOutcome(
  token: string,
  deploymentId: string,
  payload: OutcomeRequest
): Promise<OutcomeResponse> {
  return request<OutcomeResponse>(`/v1/deployments/${deploymentId}/outcome`, {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  });
}

// --- jurisdictions / risk field -------------------------------------------------

export function getRiskField(
  token: string,
  jurisdictionId: string,
  at?: string
): Promise<RiskFieldResponse> {
  const query = qs({ at });
  return request<RiskFieldResponse>(`/v1/jurisdictions/${jurisdictionId}/risk-field${query}`, { token });
}

// --- audit / models --------------------------------------------------------------

export function listAuditEvents(
  token: string,
  filters?: { subjectId?: string; subjectType?: string; from?: string; to?: string }
): Promise<AuditEventResponse[]> {
  const query = qs({
    subject_id: filters?.subjectId,
    subject_type: filters?.subjectType,
    from: filters?.from,
    to: filters?.to,
  });
  return request<AuditEventResponse[]>(`/v1/audit/events${query}`, { token });
}

export function verifyAuditChain(
  token: string,
  range?: { fromSeq?: number; toSeq?: number }
): Promise<VerifyChainResponse> {
  const query = qs({ from_seq: range?.fromSeq, to_seq: range?.toSeq });
  return request<VerifyChainResponse>(`/v1/audit/verify-chain${query}`, { token });
}

export function listModels(token: string): Promise<ModelRegistryEntryResponse[]> {
  return request<ModelRegistryEntryResponse[]>("/v1/models", { token });
}
