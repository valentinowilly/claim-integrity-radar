export type Availability = "available" | "not_configured" | "insufficient_data" | "unavailable";
export type IndicatorCode = "repeat_billing_candidate" | "similar_claim_pattern_candidate"
  | "near_duplicate_claim_candidate" | "synthetic_capacity_candidate"
  | "temporal_pattern_candidate" | "supporting_evidence_completeness_candidate";
export type CaseStatus = "pending" | "in_review" | "resolved";
export type ReviewStatus = "pending_review" | "needs_more_evidence" | "not_substantiated" | "escalated";
export type RunReviewStatus = "pending_review" | "in_review" | "awaiting_evidence" | "escalated" | "closed";
export type ReviewOutcome = "signal_supported" | "signal_not_supported" | "inconclusive";
export type RiskLevel = "high" | "medium" | "low" | null;
export type AppRole = "platform_admin" | "data_operator" | "verifikator" | "audit_lead";
export interface AuthUser { user_id: string; username: string; role: AppRole; is_active: boolean; }
export interface AuthSession { user: AuthUser; permissions: string[]; expires_at: string; csrf_token: string; }

let csrfToken: string | null = null;
export function setCsrfToken(value: string | null): void { csrfToken = value; }
export function isAuthSession(value: unknown): value is AuthSession {
  if (!isRecord(value) || !isRecord(value.user)) return false;
  const user = value.user;
  return isString(user.user_id) && isString(user.username)
    && (user.role === "platform_admin" || user.role === "data_operator" || user.role === "verifikator" || user.role === "audit_lead")
    && typeof user.is_active === "boolean" && isStringArray(value.permissions)
    && isString(value.expires_at) && isString(value.csrf_token);
}

export function notifySessionExpired(): void { window.dispatchEvent(new Event("cir:session-expired")); }

export const reviewStatusLabels: Record<ReviewStatus, string> = {
  pending_review: "Menunggu Tinjauan",
  needs_more_evidence: "Perlu Bukti Tambahan",
  not_substantiated: "Selesai — Indikasi Tidak Cukup",
  escalated: "Dieskalasikan",
};

export const runReviewStatusLabels: Record<RunReviewStatus, string> = {
  pending_review: "Menunggu Tinjauan", in_review: "Dalam Tinjauan",
  awaiting_evidence: "Menunggu Bukti Tambahan", escalated: "Dieskalasikan", closed: "Ditutup",
};
export const reviewOutcomeLabels: Record<ReviewOutcome, string> = {
  signal_supported: "Sinyal didukung oleh tinjauan",
  signal_not_supported: "Sinyal tidak didukung oleh tinjauan",
  inconclusive: "Belum dapat disimpulkan",
};

export interface BatchValidation {
  error_count: number;
  error_counts: Record<string, number>;
  errors: Array<{ code: string; row?: number; column?: string }>;
  errors_truncated: boolean;
  row_count: number | null;
  warning_counts: Record<string, unknown>;
}
export interface BatchMetadata {
  batch_id: string; batch_key: string; batch_version: number; created_at: string;
  creator_user_id: string; source_type: "synthetic_csv"; schema_version: string;
  mapping_version: string; row_count: number | null;
  status: "ready" | "ready_with_warnings" | "rejected"; validation: BatchValidation;
}
export interface BatchImportResponse { batch: BatchMetadata; reused_existing: boolean; notice: string; }
export interface BatchListResponse { items: BatchMetadata[]; total_items: number; limit: number; offset: number; availability: "available"; }
export interface BatchDetailResponse { batch: BatchMetadata; availability: "available"; notice: string; }
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export interface RunManifest {
  run_id: string; batch_id: string; batch_version: number; content_checksum: string;
  source_type: "synthetic_csv"; source_schema_version: string; source_mapping_version: string;
  creator_user_id: string; retry_of_run_id: string | null; created_at: string; started_at: string;
  completed_at: string | null; execution_status: "running" | "completed" | "partial" | "failed";
  failure_category: string | null; detector_suite_version: string | null; scoring_version: string | null;
  priority_version: string | null; action_policy_version: string | null;
  configuration: Record<string, JsonValue>; coverage: JsonValue[] | null;
  result_available: boolean; result_storage_reference: string | null;
}
export interface RunCase {
  case_id: string; risk_score: number | null; score_status: string; indicators: string[];
  indicator_coverage: Array<{ indicator: string; status: string; reason: string | null }>;
  reasons: Array<{ indicator: string; summary: string; evidence: string[]; limitations: string[] }>;
  limitations: string[];
}
export interface RunResult {
  availability: string; execution_status: string; data_source: DataSource;
  records_considered: number; records_eligible: number;
  indicators: Array<{ code: string; name: string; status: string; candidate_count: number | null; candidate_group_count: number | null; eligible_count: number; not_applicable_count: number; unassessed_count: number; search_truncated: boolean; definition: string; limitations: string[] }>;
  indicator_coverage: Array<{ indicator: string; status: string; records_assessed: number; records_not_applicable: number; records_unassessed: number; search_truncated: boolean; candidate_group_count: number | null; limitations: string[] }>;
  risk_scoring: { version: string; weights: Record<string, number>; weight_basis: string; unassessable_case_count: number; limitations: string[] };
  audit_priority: { status: string; priority_version: string; unit: string; formula: string; items: JsonValue[]; eligibility_reasons: string[]; limitations: string[] };
  cases: Record<string, RunCase>;
  action_policy: { status: string; unit: string; policy_version: string; input_assessment_status: string; lane_counts: Record<string, number>; cases: Record<string, { lane: string; policy_version: string; input_assessment_status: string; reasons: string[]; limitations: string[] }>; limitations: string[] };
  limitations: string[];
}
export interface RunCreateResponse { run: RunManifest; notice: string; }
export interface RunListResponse { items: RunManifest[]; total_items: number; limit: number; offset: number; availability: "available"; }
export interface RunDetailResponse { availability: "available"; run: RunManifest; result: RunResult | null; notice: string; }
export interface RunReviewEvent {
  event_id: string; event_type: "status_changed" | "outcome_recorded" | "outcome_changed";
  occurred_at: string; actor_user_id: string; previous_status: RunReviewStatus | null;
  new_status: RunReviewStatus | null; previous_outcome: ReviewOutcome | null;
  new_outcome: ReviewOutcome | null; note: string | null;
}
export interface RunReviewResponse {
  availability: "available"; data_source: "synthetic_data_batch"; review_id: string | null;
  run_id: string; case_id: string; review_status: RunReviewStatus; review_status_label: string;
  review_outcome: ReviewOutcome | null; review_outcome_label: string | null; note: string | null;
  created_at: string | null; updated_at: string | null; updated_by_user_id: string | null;
  history: RunReviewEvent[]; notice: string;
}

export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
}

export interface DataSource {
  kind: "synthetic" | "local" | "none";
  label: string | null;
}

export interface IndicatorCount {
  indicator: IndicatorCode;
  candidate_groups: number | null;
  candidate_records: number | null;
  status: "complete" | "partial" | "unavailable" | "not_applicable";
}

export interface DashboardSummaryResponse {
  availability: Availability;
  execution_status: "completed" | "partial" | "failed";
  data_source: DataSource;
  generated_at: string;
  period: { from: string | null; to: string | null };
  summary: {
    claims_reviewed: number | null;
    cases_in_queue: number | null;
    risk_level_counts: { high: number | null; medium: number | null; low: number | null };
    indicator_counts: IndicatorCount[];
  };
  notice: string;
}

export interface AnalysisIndicator {
  code: IndicatorCode;
  name: string;
  status: "complete" | "partial" | "unavailable" | "not_applicable";
  candidate_count: number | null;
  candidate_group_count: number | null;
  eligible_count: number;
  not_applicable_count: number;
  unassessed_count: number;
  search_truncated: boolean;
  definition: string;
  limitations: string[];
}

export interface IndicatorCoverage {
  indicator: IndicatorCode;
  status: "complete" | "partial" | "unavailable" | "not_applicable";
  records_assessed: number;
  records_not_applicable: number;
  records_unassessed: number;
  search_truncated: boolean;
  candidate_group_count: number | null;
  limitations: string[];
}

export interface RiskScoringSummary {
  version: string;
  weights: Record<string, number>;
  weight_basis: string;
  unassessable_case_count: number;
  limitations: string[];
}

export interface AuditPrioritySummary {
  status: "available" | "partial" | "not_assessable";
  priority_version: string;
  unit: string;
  formula: string;
  sorted_by: string[];
  items: Record<string, unknown>[];
  unit_count: number;
  eligible_unit_count?: number;
  unassigned_triggered_case_count: number;
  eligibility_reasons?: string[];
  limitations: string[];
}

export interface PlannedIndicator {
  code: string;
  name: string;
  status: "planned";
  definition: string;
}

export interface AnalysisResponse {
  availability: Availability;
  execution_status: "completed" | "partial" | "failed";
  data_source: DataSource;
  generated_at: string;
  filters: { period_from: string | null; period_to: string | null; indicator: IndicatorCode | null };
  coverage: { records_considered: number; records_eligible: number };
  indicators: AnalysisIndicator[];
  planned_indicators: PlannedIndicator[];
  indicator_coverage: IndicatorCoverage[];
  risk_scoring: RiskScoringSummary;
  audit_priority: AuditPrioritySummary;
  limitations: string[];
}

export interface CaseReason {
  indicator: IndicatorCode;
  summary: string;
  evidence: string[];
  limitations: string[];
  supporting_values: Record<string, unknown>;
}
export type IndicatorState = "triggered" | "not_triggered" | "not_applicable" | "not_assessed";
export type ScoreStatus = "assessed" | "assessed_no_signal" | "partial_coverage" | "not_assessable";
export interface CaseIndicatorCoverage { indicator: IndicatorCode; status: IndicatorState; reason: string | null; }

export interface CaseListItem {
  case_id: string;
  risk_level: RiskLevel;
  risk_score: number | null;
  score_status: ScoreStatus;
  scoring_version: string;
  indicators: IndicatorCode[];
  assessed_indicators: IndicatorCode[];
  not_applicable_indicators: IndicatorCode[];
  not_assessed_indicators: IndicatorCode[];
  indicator_coverage: CaseIndicatorCoverage[];
  status: CaseStatus;
  review_status: ReviewStatus;
  detected_at: string | null;
  reasons: CaseReason[];
}
type CaseCore = Omit<CaseListItem, "review_status">;

export interface CasesResponse {
  availability: Availability;
  execution_status: "completed" | "partial" | "failed";
  data_source: DataSource;
  items: CaseListItem[];
  pagination: { page: number; page_size: number; total_items: number; total_pages: number };
  applied_filters: {
    risk_level: RiskLevel;
    indicator: IndicatorCode | null;
    status: CaseStatus | null;
    review_status: ReviewStatus | null;
    sort_by: "risk_score" | "detected_at";
    sort_order: "asc" | "desc";
  };
  notice: string;
}

export interface CaseDetailResponse {
  availability: Availability;
  execution_status: "completed" | "partial" | "failed";
  data_source: DataSource;
  case: CaseCore & {
    limitations: string[];
    review: { decision: string | null; reviewed_at: string | null };
  };
  notice: string;
}

export interface EvaluationResponse {
  availability: Availability;
  data_source: DataSource;
  generated_at: string;
  evaluation: Record<string, unknown> | null;
  requirements_missing: string[];
  notice: string;
}

export interface PeriodFilters {
  period_from?: string;
  period_to?: string;
}

export interface CaseQuery {
  page: number;
  page_size: number;
  risk_level?: Exclude<RiskLevel, null>;
  indicator?: IndicatorCode;
  status?: CaseStatus;
  review_status?: ReviewStatus;
  sort_by: "risk_score" | "detected_at";
  sort_order: "asc" | "desc";
}

export interface ReviewHistoryEntry {
  changed_at: string;
  previous_status: ReviewStatus | null;
  status: ReviewStatus;
  note: string | null;
  reviewer_label: string;
}

export interface CaseReviewResponse {
  availability: "available";
  data_source: DataSource;
  case_id: string;
  status: ReviewStatus;
  status_label: string;
  note: string | null;
  reviewer_label: string | null;
  updated_at: string | null;
  history: ReviewHistoryEntry[];
}

export interface ReviewUpdateRequest {
  status: ReviewStatus;
  note?: string | null;
}

export class ApiClientError extends Error {
  readonly status: number | null;
  readonly code: string | null;
  readonly requestId: string | null;

  constructor(message: string, status: number | null = null, code: string | null = null, requestId: string | null = null) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

type Guard<T> = (value: unknown) => value is T;
type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string { return typeof value === "string"; }
function isNullableString(value: unknown): value is string | null { return value === null || isString(value); }
function isNumber(value: unknown): value is number { return typeof value === "number" && Number.isFinite(value); }
function isNullableNumber(value: unknown): value is number | null { return value === null || isNumber(value); }
function isStringArray(value: unknown): value is string[] { return Array.isArray(value) && value.every(isString); }
function isJsonValue(value: unknown): value is JsonValue {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(isJsonValue);
  return isRecord(value) && Object.values(value).every(isJsonValue);
}
function isRunReviewStatus(value: unknown): value is RunReviewStatus {
  return value === "pending_review" || value === "in_review" || value === "awaiting_evidence" || value === "escalated" || value === "closed";
}
function isReviewOutcome(value: unknown): value is ReviewOutcome {
  return value === "signal_supported" || value === "signal_not_supported" || value === "inconclusive";
}
function isBatchMetadata(value: unknown): value is BatchMetadata {
  if (!isRecord(value) || !isString(value.batch_id) || !isString(value.batch_key) || !isNumber(value.batch_version)
    || !isString(value.created_at) || !isString(value.creator_user_id) || value.source_type !== "synthetic_csv"
    || !isString(value.schema_version) || !isString(value.mapping_version)
    || !(value.row_count === null || isNumber(value.row_count))
    || !(value.status === "ready" || value.status === "ready_with_warnings" || value.status === "rejected")
    || !isRecord(value.validation)) return false;
  const validation = value.validation;
  return isNumber(validation.error_count) && isRecord(validation.error_counts)
    && Object.values(validation.error_counts).every(isNumber) && Array.isArray(validation.errors)
    && validation.errors.every(item => isRecord(item) && isString(item.code)
      && (item.row === undefined || isNumber(item.row)) && (item.column === undefined || isString(item.column)))
    && typeof validation.errors_truncated === "boolean"
    && (validation.row_count === null || isNumber(validation.row_count)) && isRecord(validation.warning_counts);
}
function isBatchImportResponse(value: unknown): value is BatchImportResponse {
  return isRecord(value) && isBatchMetadata(value.batch) && typeof value.reused_existing === "boolean" && isString(value.notice);
}
function isBatchListResponse(value: unknown): value is BatchListResponse {
  return isRecord(value) && value.availability === "available" && Array.isArray(value.items)
    && value.items.every(isBatchMetadata) && isNumber(value.total_items) && isNumber(value.limit) && isNumber(value.offset);
}
function isBatchDetailResponse(value: unknown): value is BatchDetailResponse {
  return isRecord(value) && value.availability === "available" && isBatchMetadata(value.batch) && isString(value.notice);
}
function isRunManifest(value: unknown): value is RunManifest {
  return isRecord(value) && isString(value.run_id) && isString(value.batch_id) && isNumber(value.batch_version)
    && isString(value.content_checksum) && value.source_type === "synthetic_csv"
    && isString(value.source_schema_version) && isString(value.source_mapping_version)
    && isString(value.creator_user_id) && isNullableString(value.retry_of_run_id)
    && isString(value.created_at) && isString(value.started_at) && isNullableString(value.completed_at)
    && (value.execution_status === "running" || value.execution_status === "completed" || value.execution_status === "partial" || value.execution_status === "failed")
    && isNullableString(value.failure_category) && isNullableString(value.detector_suite_version)
    && isNullableString(value.scoring_version) && isNullableString(value.priority_version)
    && isNullableString(value.action_policy_version) && isRecord(value.configuration)
    && Object.values(value.configuration).every(isJsonValue)
    && (value.coverage === null || Array.isArray(value.coverage) && value.coverage.every(isJsonValue))
    && typeof value.result_available === "boolean" && isNullableString(value.result_storage_reference);
}
function isRunListResponse(value: unknown): value is RunListResponse {
  return isRecord(value) && value.availability === "available" && Array.isArray(value.items)
    && value.items.every(isRunManifest) && isNumber(value.total_items) && isNumber(value.limit) && isNumber(value.offset);
}
function isRunCase(value: unknown): value is RunCase {
  return isRecord(value) && isString(value.case_id) && isNullableNumber(value.risk_score)
    && isString(value.score_status) && isStringArray(value.indicators)
    && Array.isArray(value.indicator_coverage) && value.indicator_coverage.every(item => isRecord(item)
      && isString(item.indicator) && isString(item.status) && isNullableString(item.reason))
    && Array.isArray(value.reasons) && value.reasons.every(item => isRecord(item)
      && isString(item.indicator) && isString(item.summary) && isStringArray(item.evidence)
      && isStringArray(item.limitations)) && isStringArray(value.limitations);
}
function isRunResult(value: unknown): value is RunResult {
  if (!isRecord(value) || !isString(value.availability) || !isString(value.execution_status)
    || !isSource(value.data_source) || !isNumber(value.records_considered) || !isNumber(value.records_eligible)
    || !Array.isArray(value.indicators) || !Array.isArray(value.indicator_coverage)
    || !isRecord(value.risk_scoring) || !isRecord(value.audit_priority) || !isRecord(value.cases)
    || !isRecord(value.action_policy) || !isStringArray(value.limitations)) return false;
  const scoring = value.risk_scoring;
  const priority = value.audit_priority;
  const policy = value.action_policy;
  return value.indicators.every(item => isRecord(item) && isString(item.code) && isString(item.name)
    && isString(item.status) && isNullableNumber(item.candidate_count) && isNullableNumber(item.candidate_group_count)
    && isNumber(item.eligible_count) && isNumber(item.not_applicable_count) && isNumber(item.unassessed_count)
    && typeof item.search_truncated === "boolean" && isString(item.definition) && isStringArray(item.limitations))
    && value.indicator_coverage.every(item => isRecord(item) && isString(item.indicator) && isString(item.status)
      && isNumber(item.records_assessed) && isNumber(item.records_not_applicable) && isNumber(item.records_unassessed)
      && typeof item.search_truncated === "boolean" && isNullableNumber(item.candidate_group_count) && isStringArray(item.limitations))
    && isString(scoring.version) && isRecord(scoring.weights) && Object.values(scoring.weights).every(isNumber)
    && isString(scoring.weight_basis) && isNumber(scoring.unassessable_case_count) && isStringArray(scoring.limitations)
    && isString(priority.status) && isString(priority.priority_version) && isString(priority.unit)
    && isString(priority.formula) && Array.isArray(priority.items) && priority.items.every(isJsonValue)
    && isStringArray(priority.eligibility_reasons) && isStringArray(priority.limitations)
    && Object.values(value.cases).every(isRunCase)
    && isString(policy.status) && isString(policy.unit) && isString(policy.policy_version)
    && isString(policy.input_assessment_status) && isRecord(policy.lane_counts)
    && Object.values(policy.lane_counts).every(isNumber) && isRecord(policy.cases)
    && Object.values(policy.cases).every(item => isRecord(item) && isString(item.lane)
      && isString(item.policy_version) && isString(item.input_assessment_status)
      && isStringArray(item.reasons) && isStringArray(item.limitations)) && isStringArray(policy.limitations);
}
function isRunDetailResponse(value: unknown): value is RunDetailResponse {
  return isRecord(value) && value.availability === "available" && isRunManifest(value.run)
    && (value.result === null || isRunResult(value.result))
    && isString(value.notice);
}
function isRunReviewResponse(value: unknown): value is RunReviewResponse {
  if (!isRecord(value) || value.availability !== "available" || value.data_source !== "synthetic_data_batch"
    || !isNullableString(value.review_id) || !isString(value.run_id) || !isString(value.case_id)
    || !isRunReviewStatus(value.review_status) || !isString(value.review_status_label)
    || !(value.review_outcome === null || isReviewOutcome(value.review_outcome))
    || !isNullableString(value.review_outcome_label) || !isNullableString(value.note)
    || !isNullableString(value.created_at) || !isNullableString(value.updated_at)
    || !isNullableString(value.updated_by_user_id) || !isString(value.notice) || !Array.isArray(value.history)) return false;
  return value.history.every(item => isRecord(item) && isString(item.event_id)
    && (item.event_type === "status_changed" || item.event_type === "outcome_recorded" || item.event_type === "outcome_changed")
    && isString(item.occurred_at) && isString(item.actor_user_id)
    && (item.previous_status === null || isRunReviewStatus(item.previous_status))
    && (item.new_status === null || isRunReviewStatus(item.new_status))
    && (item.previous_outcome === null || isReviewOutcome(item.previous_outcome))
    && (item.new_outcome === null || isReviewOutcome(item.new_outcome)) && isNullableString(item.note));
}
function isRunCreateResponse(value: unknown): value is RunCreateResponse {
  return isRecord(value) && isRunManifest(value.run) && isString(value.notice);
}
function isAvailability(value: unknown): value is Availability {
  return value === "available" || value === "not_configured" || value === "insufficient_data" || value === "unavailable";
}
function isExecutionStatus(value: unknown): value is "completed" | "partial" | "failed" {
  return value === "completed" || value === "partial" || value === "failed";
}
function isIndicator(value: unknown): value is IndicatorCode {
  return value === "repeat_billing_candidate" || value === "similar_claim_pattern_candidate"
    || value === "near_duplicate_claim_candidate" || value === "synthetic_capacity_candidate"
    || value === "temporal_pattern_candidate" || value === "supporting_evidence_completeness_candidate";
}
function isStatus(value: unknown): value is CaseStatus {
  return value === "pending" || value === "in_review" || value === "resolved";
}
function isReviewStatus(value: unknown): value is ReviewStatus {
  return value === "pending_review" || value === "needs_more_evidence"
    || value === "not_substantiated" || value === "escalated";
}
function isRisk(value: unknown): value is RiskLevel {
  return value === null || value === "high" || value === "medium" || value === "low";
}
function isSource(value: unknown): value is DataSource {
  return isRecord(value) && (value.kind === "synthetic" || value.kind === "local" || value.kind === "none") && isNullableString(value.label);
}
function isReason(value: unknown): value is CaseReason {
  return isRecord(value) && isIndicator(value.indicator) && isString(value.summary)
    && isStringArray(value.evidence) && isStringArray(value.limitations)
    && isRecord(value.supporting_values);
}
function isIndicatorState(value: unknown): value is IndicatorState {
  return value === "triggered" || value === "not_triggered" || value === "not_applicable" || value === "not_assessed";
}
function isScoreStatus(value: unknown): value is ScoreStatus {
  return value === "assessed" || value === "assessed_no_signal" || value === "partial_coverage" || value === "not_assessable";
}
function isCaseCore(value: unknown): value is UnknownRecord & CaseCore {
  return isRecord(value) && isString(value.case_id) && isRisk(value.risk_level) && isNullableNumber(value.risk_score)
    && isScoreStatus(value.score_status) && isString(value.scoring_version)
    && Array.isArray(value.indicators) && value.indicators.every(isIndicator) && isStatus(value.status)
    && Array.isArray(value.assessed_indicators) && value.assessed_indicators.every(isIndicator)
    && Array.isArray(value.not_applicable_indicators) && value.not_applicable_indicators.every(isIndicator)
    && Array.isArray(value.not_assessed_indicators) && value.not_assessed_indicators.every(isIndicator)
    && Array.isArray(value.indicator_coverage) && value.indicator_coverage.every(item => isRecord(item)
      && isIndicator(item.indicator) && isIndicatorState(item.status) && isNullableString(item.reason))
    && isNullableString(value.detected_at) && Array.isArray(value.reasons) && value.reasons.every(isReason);
}
function isCaseListItem(value: unknown): value is CaseListItem {
  return isCaseCore(value) && isReviewStatus(value.review_status);
}

function isHealthResponse(value: unknown): value is HealthResponse {
  return isRecord(value) && value.status === "ok" && isString(value.service) && isString(value.version);
}
function isDashboardResponse(value: unknown): value is DashboardSummaryResponse {
  if (!isRecord(value) || !isAvailability(value.availability) || !isExecutionStatus(value.execution_status) || !isSource(value.data_source)
    || !isString(value.generated_at) || !isRecord(value.period) || !isRecord(value.summary) || !isString(value.notice)) return false;
  const summary = value.summary;
  const levels = summary.risk_level_counts;
  return isNullableString(value.period.from) && isNullableString(value.period.to)
    && (summary.claims_reviewed === null || isNumber(summary.claims_reviewed))
    && (summary.cases_in_queue === null || isNumber(summary.cases_in_queue))
    && isRecord(levels) && isNullableNumber(levels.high) && isNullableNumber(levels.medium) && isNullableNumber(levels.low)
    && Array.isArray(summary.indicator_counts) && summary.indicator_counts.every(item => isRecord(item)
      && isIndicator(item.indicator) && isNullableNumber(item.candidate_groups) && isNullableNumber(item.candidate_records)
      && (item.status === "complete" || item.status === "partial" || item.status === "unavailable" || item.status === "not_applicable"));
}
function isAnalysisResponse(value: unknown): value is AnalysisResponse {
  if (!isRecord(value) || !isAvailability(value.availability) || !isExecutionStatus(value.execution_status) || !isSource(value.data_source)
    || !isString(value.generated_at) || !isRecord(value.filters) || !isRecord(value.coverage)
    || !Array.isArray(value.indicators) || !Array.isArray(value.planned_indicators) || !isStringArray(value.limitations)) return false;
  return isNullableString(value.filters.period_from) && isNullableString(value.filters.period_to)
    && (value.filters.indicator === null || isIndicator(value.filters.indicator))
    && isNumber(value.coverage.records_considered) && isNumber(value.coverage.records_eligible)
    && value.indicators.every(item => isRecord(item) && isIndicator(item.code) && isString(item.name)
      && (item.status === "complete" || item.status === "partial" || item.status === "unavailable" || item.status === "not_applicable")
      && isNullableNumber(item.candidate_count) && isNullableNumber(item.candidate_group_count) && isNumber(item.eligible_count)
      && isNumber(item.not_applicable_count) && isNumber(item.unassessed_count) && typeof item.search_truncated === "boolean"
      && isString(item.definition) && isStringArray(item.limitations))
    && value.planned_indicators.every(item => isRecord(item) && isString(item.code) && isString(item.name)
      && item.status === "planned" && isString(item.definition))
    && Array.isArray(value.indicator_coverage) && value.indicator_coverage.every(item => isRecord(item)
      && isIndicator(item.indicator) && (item.status === "complete" || item.status === "partial" || item.status === "unavailable" || item.status === "not_applicable")
      && isNumber(item.records_assessed) && isNumber(item.records_not_applicable) && isNumber(item.records_unassessed)
      && typeof item.search_truncated === "boolean" && isNullableNumber(item.candidate_group_count) && isStringArray(item.limitations))
    && isRecord(value.risk_scoring) && isString(value.risk_scoring.version) && isRecord(value.risk_scoring.weights)
    && isString(value.risk_scoring.weight_basis) && isNumber(value.risk_scoring.unassessable_case_count)
    && isStringArray(value.risk_scoring.limitations)
    && isRecord(value.audit_priority) && (value.audit_priority.status === "available" || value.audit_priority.status === "partial" || value.audit_priority.status === "not_assessable")
    && isString(value.audit_priority.priority_version) && isString(value.audit_priority.unit)
    && isString(value.audit_priority.formula) && isStringArray(value.audit_priority.sorted_by)
    && Array.isArray(value.audit_priority.items) && value.audit_priority.items.every(isRecord)
    && isNumber(value.audit_priority.unit_count) && isNumber(value.audit_priority.unassigned_triggered_case_count)
    && isStringArray(value.audit_priority.limitations);
}
function isCasesResponse(value: unknown): value is CasesResponse {
  if (!isRecord(value) || !isAvailability(value.availability) || !isExecutionStatus(value.execution_status) || !isSource(value.data_source)
    || !Array.isArray(value.items) || !isRecord(value.pagination) || !isRecord(value.applied_filters) || !isString(value.notice)) return false;
  const page = value.pagination;
  const filters = value.applied_filters;
  return value.items.every(isCaseListItem) && isNumber(page.page) && isNumber(page.page_size)
    && isNumber(page.total_items) && isNumber(page.total_pages)
    && isRisk(filters.risk_level) && (filters.indicator === null || isIndicator(filters.indicator))
    && (filters.status === null || isStatus(filters.status))
    && (filters.review_status === null || isReviewStatus(filters.review_status))
    && (filters.sort_by === "risk_score" || filters.sort_by === "detected_at")
    && (filters.sort_order === "asc" || filters.sort_order === "desc");
}
function isCaseDetailResponse(value: unknown): value is CaseDetailResponse {
  if (!isRecord(value) || !isAvailability(value.availability) || !isExecutionStatus(value.execution_status) || !isSource(value.data_source)
    || !isString(value.notice) || !isRecord(value.case)) return false;
  const detail = value.case;
  if (!isCaseCore(detail) || !isStringArray(detail.limitations) || !isRecord(detail.review)) return false;
  return isNullableString(detail.review.decision) && isNullableString(detail.review.reviewed_at);
}
function isEvaluationResponse(value: unknown): value is EvaluationResponse {
  return isRecord(value) && isAvailability(value.availability) && isSource(value.data_source)
    && isString(value.generated_at) && (value.evaluation === null || isRecord(value.evaluation))
    && isStringArray(value.requirements_missing) && isString(value.notice);
}

function isReviewHistoryEntry(value: unknown): value is ReviewHistoryEntry {
  return isRecord(value) && isString(value.changed_at)
    && (value.previous_status === null || isReviewStatus(value.previous_status))
    && isReviewStatus(value.status) && isNullableString(value.note)
    && isString(value.reviewer_label);
}

function isCaseReviewResponse(value: unknown): value is CaseReviewResponse {
  return isRecord(value) && value.availability === "available" && isSource(value.data_source)
    && isString(value.case_id) && isReviewStatus(value.status) && isString(value.status_label)
    && isNullableString(value.note) && isNullableString(value.reviewer_label)
    && isNullableString(value.updated_at) && Array.isArray(value.history)
    && value.history.every(isReviewHistoryEntry);
}

async function getJson<T>(path: string, guard: Guard<T>, signal?: AbortSignal): Promise<T> {
  return requestJson(path, guard, { method: "GET", signal });
}

async function requestJson<T>(path: string, guard: Guard<T>, init: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
        ...(csrfToken && init.method && init.method !== "GET" && init.method !== "HEAD" ? { "X-CSRF-Token": csrfToken } : {}),
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiClientError("Backend tidak dapat dihubungi. Periksa server FastAPI dan proxy lokal.");
  }

  if (response.status === 204) return undefined as T;
  let payload: unknown;
  try {
    payload = await response.json() as unknown;
  } catch {
    throw new ApiClientError(`Respons API bukan JSON yang valid (HTTP ${response.status}).`, response.status);
  }

  if (!response.ok) {
    const errorBody = isRecord(payload) && isRecord(payload.error) ? payload.error : null;
    const message = errorBody && isString(errorBody.message) ? errorBody.message : `Permintaan gagal (HTTP ${response.status}).`;
    const code = errorBody && isString(errorBody.code) ? errorBody.code : null;
    const requestId = errorBody && isString(errorBody.request_id) ? errorBody.request_id : null;
    if (response.status === 401 && code === "AUTHENTICATION_REQUIRED") notifySessionExpired();
    throw new ApiClientError(message, response.status, code, requestId);
  }

  if (!guard(payload)) {
    throw new ApiClientError(`Struktur respons API tidak sesuai kontrak (HTTP ${response.status}).`, response.status);
  }
  return payload;
}

export function login(username: string, password: string): Promise<AuthSession> {
  return requestJson("/api/v1/auth/login", isAuthSession, { method: "POST", body: JSON.stringify({ username, password }) })
    .then(session => { setCsrfToken(session.csrf_token); return session; });
}
export function getCurrentUser(signal?: AbortSignal): Promise<AuthSession> {
  return getJson("/api/v1/auth/me", isAuthSession, signal).then(session => { setCsrfToken(session.csrf_token); return session; });
}
export function logout(): Promise<void> {
  return requestJson("/api/v1/auth/logout", (_value): _value is undefined => true, { method: "POST" })
    .then(() => { setCsrfToken(null); });
}

function queryString(values: object): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if ((typeof value === "string" || typeof value === "number") && value !== "") params.set(key, String(value));
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return getJson("/health", isHealthResponse, signal);
}

export function getDashboardSummary(filters: PeriodFilters = {}, signal?: AbortSignal): Promise<DashboardSummaryResponse> {
  return getJson(`/api/v1/dashboard/summary${queryString(filters)}`, isDashboardResponse, signal);
}

export function getAnalysis(filters: PeriodFilters & { indicator?: IndicatorCode } = {}, signal?: AbortSignal): Promise<AnalysisResponse> {
  return getJson(`/api/v1/analysis${queryString(filters)}`, isAnalysisResponse, signal);
}

export function getCases(query: CaseQuery, signal?: AbortSignal): Promise<CasesResponse> {
  return getJson(`/api/v1/cases${queryString(query)}`, isCasesResponse, signal);
}

export function getCaseReview(caseId: string, signal?: AbortSignal): Promise<CaseReviewResponse> {
  return getJson(`/api/v1/cases/${encodeURIComponent(caseId)}/review`, isCaseReviewResponse, signal);
}

export function updateCaseReview(caseId: string, payload: ReviewUpdateRequest): Promise<CaseReviewResponse> {
  return requestJson(
    `/api/v1/cases/${encodeURIComponent(caseId)}/review`,
    isCaseReviewResponse,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function getCaseDetail(caseId: string, signal?: AbortSignal): Promise<CaseDetailResponse> {
  return getJson(`/api/v1/cases/${encodeURIComponent(caseId)}`, isCaseDetailResponse, signal);
}

export function getEvaluation(signal?: AbortSignal): Promise<EvaluationResponse> {
  return getJson("/api/v1/evaluation", isEvaluationResponse, signal);
}

export function getBatches(limit = 50, offset = 0, signal?: AbortSignal): Promise<BatchListResponse> {
  return getJson(`/api/v1/batches${queryString({ limit, offset })}`, isBatchListResponse, signal);
}
export function getBatch(batchId: string, signal?: AbortSignal): Promise<BatchDetailResponse> {
  return getJson(`/api/v1/batches/${encodeURIComponent(batchId)}`, isBatchDetailResponse, signal);
}
export function importSyntheticCsv(file: File, batchKey: string): Promise<BatchImportResponse> {
  return requestJson("/api/v1/batches/import", isBatchImportResponse, {
    method: "POST", body: file,
    headers: {
      "Content-Type": "text/csv",
      "X-Batch-Key": batchKey,
      "X-Synthetic-Schema-Version": "synthetic-claims-v1",
      "X-Synthetic-Mapping-Version": "synthetic-canonical-v1",
      "X-Data-Classification": "synthetic_only",
    },
  });
}
export function getRuns(limit = 50, offset = 0, batchId?: string, signal?: AbortSignal): Promise<RunListResponse> {
  return getJson(`/api/v1/runs${queryString({ limit, offset, batch_id: batchId })}`, isRunListResponse, signal);
}
export function createRun(payload: { batch_id?: string; retry_of_run_id?: string; action_policy_version?: string }): Promise<RunCreateResponse> {
  return requestJson("/api/v1/runs", isRunCreateResponse, { method: "POST", body: JSON.stringify(payload) });
}
export function getRun(runId: string, signal?: AbortSignal): Promise<RunDetailResponse> {
  return getJson(`/api/v1/runs/${encodeURIComponent(runId)}`, isRunDetailResponse, signal);
}
export function getRunCaseReview(runId: string, caseId: string, signal?: AbortSignal): Promise<RunReviewResponse> {
  return getJson(`/api/v1/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}/review`, isRunReviewResponse, signal);
}
export function updateRunCaseReview(runId: string, caseId: string, payload: { review_status: RunReviewStatus; note?: string | null }): Promise<RunReviewResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}/review`, isRunReviewResponse,
    { method: "PATCH", body: JSON.stringify(payload) });
}
export function recordRunCaseOutcome(runId: string, caseId: string, payload: { review_outcome: ReviewOutcome; note?: string | null }): Promise<RunReviewResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}/review/outcome`, isRunReviewResponse,
    { method: "POST", body: JSON.stringify(payload) });
}
