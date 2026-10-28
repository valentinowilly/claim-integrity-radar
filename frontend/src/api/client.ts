export type Availability = "available" | "not_configured" | "insufficient_data" | "unavailable";
export type IndicatorCode = "repeat_billing_candidate" | "similar_claim_pattern_candidate"
  | "near_duplicate_claim_candidate" | "synthetic_capacity_candidate"
  | "temporal_pattern_candidate" | "supporting_evidence_completeness_candidate"
  | "length_of_stay_extreme_candidate" | "rapid_readmission_candidate" | "unusual_severity_candidate"
  | "cloned_clinical_note_candidate" | "severity_without_secondary_candidate" | "unusual_special_topup_candidate";
export type CaseStatus = "pending" | "in_review" | "resolved";
export type ReviewStatus = "pending_review" | "needs_more_evidence" | "not_substantiated" | "escalated";
export type RunReviewStatus = "pending_review" | "in_review" | "awaiting_evidence" | "escalated" | "closed";
export type ReviewOutcome = "signal_supported" | "signal_not_supported" | "inconclusive";
/** Result of an authorized audit; recorded separately from the reviewer outcome. */
export type AuditResult = "confirmed_issue" | "confirmed_no_issue";
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

/** English wording for known server error codes; unknown codes keep the server message. */
const ERROR_MESSAGES: Record<string, string> = {
  INVALID_CREDENTIALS: "Nama pengguna atau kata sandi salah.",
  AUTHENTICATION_REQUIRED: "Sesi Anda telah berakhir. Silakan masuk kembali.",
  CSRF_VALIDATION_FAILED: "Halaman sudah terlalu lama terbuka. Muat ulang halaman lalu coba lagi.",
  PERMISSION_DENIED: "Peran Anda tidak diizinkan melakukan tindakan ini.",
  RATE_LIMITED: "Terlalu banyak percobaan. Tunggu sebentar lalu coba lagi.",
  BATCH_NOT_FOUND: "File tidak ditemukan.",
  RUN_NOT_FOUND: "Analisis tidak ditemukan.",
  RUN_CASE_NOT_FOUND: "Klaim ini tidak termasuk dalam analisis yang dipilih.",
  RUN_CASE_REVIEW_NOT_FOUND: "Klaim ini tidak termasuk dalam analisis yang dipilih.",
  RUN_NOT_REVIEWABLE: "Analisis ini belum punya hasil untuk ditinjau.",
  RUN_SOURCE_BATCH_MISMATCH: "Sumber data tidak cocok dengan analisis ini.",
  UPLOAD_TOO_LARGE: "Ukuran file terlalu besar untuk diunggah.",
  UNSUPPORTED_MEDIA_TYPE: "Hanya file CSV yang dapat diunggah.",
  SYNTHETIC_DATA_REQUIRED: "Berkas ini tidak sesuai kebijakan data lingkungan ini (nomor peserta harus anonim, berawalan SYN).",
  ANALYSIS_RUN_FAILED: "Analisis gagal. Silakan jalankan ulang.",
  AUTH_STORAGE_UNAVAILABLE: "Layanan masuk sedang tidak tersedia.",
  RUN_STORAGE_UNAVAILABLE: "Penyimpanan hasil analisis sedang tidak tersedia.",
  BATCH_STORAGE_UNAVAILABLE: "Penyimpanan data sedang tidak tersedia.",
  RUN_REVIEW_STORAGE_UNAVAILABLE: "Penyimpanan tinjauan sedang tidak tersedia.",
  NOTIFICATIONS_UNAVAILABLE: "Notifikasi sedang tidak tersedia.",
  RUN_STILL_RUNNING: "Analisis yang masih berjalan tidak dapat diarsipkan.",
  INBOX_NOT_CONFIGURED: "Folder kiriman belum diatur di server. Hubungi administrator sistem.",
  INBOX_BUSY: "Pengambilan file sedang berjalan. Tunggu sebentar.",
  // Per-row and per-file problems of an uploaded claim file (codes only, never cell values).
  real_participant_not_allowed: "Nomor peserta harus anonim (berawalan SYN) sesuai kebijakan data lingkungan ini",
  post_verification_amount_forbidden: "Kolom FKL48 (biaya setelah verifikasi) tidak boleh ada di file",
  missing_required_column: "Kolom wajib tidak ada",
  missing_required_value: "Isian wajib kosong",
  duplicate_visit: "Kunjungan yang sama tercatat dua kali",
  invalid_service_date: "Tanggal masuk tidak valid",
  ground_truth_column_forbidden: "File berisi kolom kunci jawaban; hapus kolom itu",
  malformed_row_width: "Jumlah kolom pada baris tidak sesuai",
  malformed_csv: "Format CSV rusak",
  invalid_encoding: "File bukan teks UTF-8",
  empty_file: "File kosong",
  row_limit_exceeded: "Jumlah baris melebihi batas",
  unexpected_column: "Ada kolom yang tidak dikenal",
  duplicate_header: "Ada nama kolom yang ganda",
  FKRTL_SOURCE_NOT_CONFIGURED: "Data klaim belum tersedia di server. Hubungi administrator sistem.",
  FKRTL_SOURCE_FILE_UNAVAILABLE: "File data klaim tidak ditemukan di server. Hubungi administrator sistem.",
  FKRTL_READER_UNAVAILABLE: "Server belum dapat membaca data klaim. Hubungi administrator sistem.",
  FKRTL_PSEUDONYM_KEY_INVALID: "Pengaman identitas peserta di server belum siap. Hubungi administrator sistem.",
  FKRTL_CONFIGURATION_INVALID: "Pengaturan data klaim di server salah. Hubungi administrator sistem.",
  FKRTL_DATE_WINDOW_NOT_CONFIGURED: "Periode data klaim belum diatur di server. Hubungi administrator sistem.",
  FKRTL_SOURCE_READ_FAILED: "Data klaim tidak dapat dibaca. Hubungi administrator sistem.",
  FKRTL_REQUIRED_COLUMNS_MISSING: "Ada kolom wajib yang tidak ditemukan di data klaim.",
  FKRTL_DUPLICATE_VISITS: "Ada kunjungan yang tercatat lebih dari sekali di data.",
  FKRTL_WINDOW_EMPTY: "Tidak ada klaim pada periode ini.",
  FKRTL_WINDOW_EXCEEDS_CAP: "Jumlah klaim pada periode ini melebihi kapasitas. Persingkat periodenya.",
  FKRTL_OPTIONAL_COLUMNS_MISSING: "Beberapa kolom pelengkap tidak ada, jadi sebagian pemeriksaan dilewati.",
  FKRTL_INVALID_DATES: "Sebagian tanggal masuk atau pulang salah; lama rawat klaim tersebut tidak diperiksa.",
  FKRTL_PROCEDURE_BLANK: "Sebagian kode prosedur kosong; klaim tersebut tidak diperiksa untuk layanan berulang.",
  FKRTL_SOURCE_VALIDATION_FAILED: "Pemeriksaan kualitas data gagal. Perbaiki datanya lalu proses ulang.",
  FKRTL_SOURCE_NOT_VALIDATED: "Klik Proses data klaim terlebih dahulu.",
  FKRTL_SOURCE_VALIDATION_STALE: "Data berubah sejak terakhir diproses. Klik Proses data klaim lagi.",
  FKRTL_SOURCE_VALIDATION_IN_PROGRESS: "Pemeriksaan kualitas data masih berjalan. Tunggu hingga selesai.",
};

export function issueMessage(code: string, fallback: string): string {
  return ERROR_MESSAGES[code] ?? fallback;
}

export function notifySessionExpired(): void { window.dispatchEvent(new Event("cir:session-expired")); }

export const reviewStatusLabels: Record<ReviewStatus, string> = {
  pending_review: "Menunggu tinjauan",
  needs_more_evidence: "Minta klarifikasi",
  not_substantiated: "Selesai, tidak ada masalah",
  escalated: "Masuk antrean audit",
};

export const runReviewStatusLabels: Record<RunReviewStatus, string> = {
  pending_review: "Belum ditinjau", in_review: "Sedang ditinjau",
  awaiting_evidence: "Minta klarifikasi", escalated: "Masuk antrean audit", closed: "Selesai",
};
export const auditResultLabels: Record<AuditResult, string> = {
  confirmed_issue: "Audit resmi: ada masalah",
  confirmed_no_issue: "Audit resmi: tidak ada masalah",
};
export const reviewOutcomeLabels: Record<ReviewOutcome, string> = {
  signal_supported: "Benar, perlu ditindaklanjuti",
  signal_not_supported: "Ternyata wajar",
  inconclusive: "Belum bisa disimpulkan",
};

export interface BatchValidation {
  error_count: number;
  error_counts: Record<string, number>;
  errors: Array<{ code: string; row?: number; column?: string }>;
  errors_truncated: boolean;
  row_count: number | null;
  warning_counts: Record<string, unknown>;
}
export type RunSourceType = "synthetic_csv" | "bpjs_fkrtl_local";
export interface BatchMetadata {
  batch_id: string; batch_key: string; batch_version: number; created_at: string;
  creator_user_id: string; source_type: RunSourceType; schema_version: string;
  mapping_version: string; row_count: number | null;
  status: "ready" | "ready_with_warnings" | "rejected"; validation: BatchValidation;
}
export interface BatchImportResponse { batch: BatchMetadata; reused_existing: boolean; notice: string; }
export interface BatchListResponse { items: BatchMetadata[]; total_items: number; limit: number; offset: number; availability: "available"; }
export interface BatchDetailResponse { batch: BatchMetadata; availability: "available"; notice: string; }
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export interface RunManifest {
  archive_reason?: "manual" | "superseded" | "older" | null;
  run_id: string; batch_id: string; batch_version: number; content_checksum: string;
  source_type: RunSourceType; source_classification: "synthetic_only_declared" | "bpjs_sample_local";
  source_schema_version: string; source_mapping_version: string;
  creator_user_id: string; retry_of_run_id: string | null; created_at: string; started_at: string;
  completed_at: string | null; execution_status: "running" | "completed" | "partial" | "failed";
  failure_category: string | null; detector_suite_version: string | null; scoring_version: string | null;
  priority_version: string | null; action_policy_version: string | null;
  configuration: Record<string, JsonValue>; coverage: JsonValue[] | null;
  result_available: boolean; result_storage_reference: string | null;
}
/** Competition rank: tied scores share a rank; tie_count is absent on runs saved before ties were reported. */
export interface MlAnomalyRank {
  rank: number; tie_count?: number; anomaly_score: number; anomaly_percentile: number;
  /** Pretrained-artifact runs only: share of training claims with a lower score (higher score = more unusual). */
  reference_percentile?: number; model_version?: string; inference_status?: string; score_direction?: string;
  /** Pretrained-artifact runs: the claim's most extreme features against the training data. */
  supporting_signals?: Array<{ feature: string; description: string; training_percentile: number }>;
}
/** A claim the model could not score (missing prerequisite); not a negative result. */
export interface MlInferenceStatus { inference_status: string; reason: string; model_version: string; }
export interface MlAnomalyItem extends MlAnomalyRank {
  case_id: string; explanation: string;
  top_deviations: Array<{ feature: string; description: string; percentile: number }>;
}
export interface MlAnomaly {
  status: string; model_version: string; model?: string; score_type?: string;
  records_considered: number; records_scored: number; items: MlAnomalyItem[]; items_truncated: boolean;
  features?: Array<{ name: string; description: string }>; excluded_fields?: string[]; limitations: string[];
  /** "pretrained_artifact" when scored by the offline-trained model; absent on per-run rankings. */
  mode?: string; feature_pipeline_version?: string; score_direction?: string; artifact_checksum?: string; error_code?: string;
  records_not_assessed?: number; not_assessed_reason_counts?: Record<string, number>; share_above_training_p99?: number;
  training_reference?: { source_classification?: string | null; date_from?: string | null; date_to?: string | null; rows_eligible?: number | null; trained_at?: string | null };
}
export interface DurationCandidate {
  case_id: string; span_days: number; peer_group_definition: string; peer_support: number;
  peer_threshold_days: number; peer_median_days: number; share_of_peers_with_shorter_span: number; explanation: string;
}
export interface DurationScreen {
  status: string; version: string; label?: string;
  method?: { upper_percentile: number; min_peer_group_size: number; quantile: string; comparison: string; reference: string };
  input_record_count: number; assessed_count: number; unassessed_count: number;
  unassessed_reason_counts?: Record<string, number>; peer_groups_assessed?: number; peer_groups_below_support?: number;
  candidate_count: number; candidates_per_1000_assessed?: number | null; candidates: DurationCandidate[]; limitations: string[];
}
export interface RunCase {
  ml_anomaly?: MlAnomalyRank | null;
  ml_inference?: MlInferenceStatus;
  /** Present when the claim is also a duration-screen candidate (runs from Phase 5 on). */
  length_of_stay?: DurationCandidate | null;
  /** Present on scoring v2 runs; absent on persisted v1 runs. */
  score_basis?: { assessed_indicator_count: number; minimum_assessed_indicators: number } | null;
  case_id: string; risk_score: number | null; score_status: string; indicators: string[];
  indicator_coverage: Array<{ indicator: string; status: string; reason: string | null }>;
  reasons: Array<{ indicator: string; summary: string; evidence: string[]; limitations: string[]; supporting_values?: Record<string, unknown> }>;
  limitations: string[];
}
export interface RunResult {
  availability: string; execution_status: string; data_source: DataSource;
  records_considered: number; records_eligible: number;
  indicators: Array<{ code: string; name: string; status: string; candidate_count: number | null; candidate_group_count: number | null; eligible_count: number; not_applicable_count: number; unassessed_count: number; search_truncated: boolean; definition: string; limitations: string[]; interpretation?: Record<string, string> | null }>;
  indicator_coverage: Array<{ indicator: string; status: string; records_assessed: number; records_not_applicable: number; records_unassessed: number; unassessed_reason_counts?: Record<string, number>; search_truncated: boolean; candidate_group_count: number | null; limitations: string[] }>;
  risk_scoring: {
    version: string; weights: Record<string, number>; weight_basis: string; unassessable_case_count: number; limitations: string[];
    /** Scoring v2 only. */
    insufficient_indicator_case_count?: number; minimum_assessed_indicators?: number;
  };
  audit_priority: { status: string; priority_version: string; unit: string; formula: string; items: JsonValue[]; eligibility_reasons: string[]; limitations: string[] };
  cases: Record<string, RunCase>;
  action_policy: { status: string; unit: string; policy_version: string; input_assessment_status: string; lane_counts: Record<string, number>; cases: Record<string, { lane: string; policy_version: string; input_assessment_status: string; reasons: string[]; limitations: string[] }>; limitations: string[] };
  limitations?: string[];
  ml_anomaly?: MlAnomaly;
  /** Standalone exploratory duration screen; absent on older runs. */
  length_of_stay?: DurationScreen;
  /** Flagged claims rolled up per facility group (facility-group-v1); absent on older runs. */
  facility_groups?: FacilityGroups;
  /**
   * Set when the server returned a partial view of the stored result. In a "summary" view `cases`
   * is empty on purpose: use `case_count` and the paged case list, never treat it as "no flagged claims".
   * In a "case" view `cases` holds only the requested claim.
   */
  result_view?: RunResultView;
}
export type LaneEntry = RunResult["action_policy"]["cases"][string];
export type Lane = "red" | "yellow" | "green";
export interface FacilityGroup {
  group_id: string; rank: number; title: string; region: string; facility_type: string;
  claim_count: number; flagged_count: number; lane_counts: Record<Lane, number>;
  indicator_counts: Record<string, number>; records_to_request: number; findings_per_record: number;
  max_ml_percentile: number; sample_case_ids: string[]; sample_lanes: Record<string, string>;
  sample_findings?: Record<string, string[]>;
  /** Shares well above the groups of the same class in the same province (reasons only; absent on older runs). */
  peer_signals?: Array<{ kind: "severity" | "special"; share: number; peer_share: number; ratio: number | null; peer_groups: number; text: string }>;
  /** Display only: billed value of the group's high/medium-risk claims (absent on older runs). */
  billed_high_or_medium?: number;
  level: "high" | "medium" | "low"; verdict: string;
}
export interface FacilityGroups {
  status: string; version: string; min_claims: number; group_count: number;
  level_counts: Record<"high" | "medium" | "low", number>; hidden_group_count: number; hidden_claim_count: number;
  groups: FacilityGroup[]; groups_truncated: boolean; limitations: string[];
  /** High/medium-risk share per province, facility class and ownership; absent on older runs. */
  fairness?: Fairness;
  exposure?: Exposure;
}
/** Billed value per risk level; a value awaiting re-verification, not a loss, and never used for scoring. */
export interface Exposure {
  status: string; amount_source: string; claims_with_amount: number; billed_total: number;
  billed_high: number; billed_medium: number; billed_high_or_medium: number; share_of_billed: number | null; note: string;
}
export interface CalibrationResponse {
  availability: "available"; run_id: string; flagged: number; feedback_visible: boolean;
  bins: Array<{ specific: number; ai_bin: number | null; count: number }>;
  feedback: Array<{ specific: number; ai_bin: number | null; outcome: "signal_supported" | "signal_not_supported"; count: number }>;
}
function isCalibrationResponse(value: unknown): value is CalibrationResponse {
  return isRecord(value) && value.availability === "available" && isNumber(value.flagged)
    && Array.isArray(value.bins) && Array.isArray(value.feedback);
}
export function getRunCalibration(runId: string, signal?: AbortSignal): Promise<CalibrationResponse> {
  return getJson(`/api/v1/runs/${encodeURIComponent(runId)}/calibration`, isCalibrationResponse, signal);
}
export interface FairnessRow { label: string; claims: number; high: number; medium: number; share: number; ratio_to_overall: number | null }
export interface Fairness {
  overall_share: number; claims: number; high_or_medium: number; min_claims: number; note: string;
  dimensions: Array<{ field: string; title: string; rows: FairnessRow[]; hidden_categories: number }>;
}
/** Report of scripts/evaluate_current_pipeline.py (synthetic, labelled). */
export interface PipelineTally {
  claims: number; detected_by_rules: number; detected_share: number | null; high: number; medium: number; high_or_medium_share: number | null;
  rules_only_high?: number; rules_only_medium?: number;
  flagged_by_ai?: number; flagged_by_ai_share?: number | null; detected_any?: number; detected_any_share?: number | null;
}
export interface AiRoutineCheck {
  report: string; window: string[]; model_version?: string; claims: number; common_codes_share_of_claims: number | null;
  common_codes: { claims: number; share_ai_high: number | null }; rare_codes: { claims: number; share_ai_high: number | null };
  all_claims: { claims: number; share_ai_high: number | null }; definition: string;
}
export interface PipelineReport {
  report: string; generated_at: string;
  configuration: { claims: number; facilities: number; seed: number; generator_version?: string; action_policy_version?: string };
  population: { claims: number; fraud_claims: number; base_rate: number; facilities: number; fraud_facilities: number };
  scenarios: Record<string, PipelineTally>; honest_claims: PipelineTally; honest_facility_claims: PipelineTally;
  legitimate_repeat_control: PipelineTally;
  honest_lookalikes?: Record<string, PipelineTally>;
  ai_routine_check?: AiRoutineCheck;
  workload: { high: number; high_or_medium: number; high_or_medium_share_of_claims: number | null };
  precision: { high: number | null; high_or_medium: number | null; lift_high_vs_random: number | null };
  facility_ranking: { top_fifth: number; fraud_facilities_in_top_fifth: number; precision_top_fifth: number | null; fraud_facility_share: number | null };
  /** Random audit vs a simple rule vs the Radar on the same labelled data (absent in older reports). */
  method_comparison?: {
    k: number;
    methods: Array<{
      name: string; description: string; reviewed_claims: number; precision_at_k: number | null; fraud_per_100: number | null;
      recall: number | null; honest_kept_green: number | null; honest_flagged: number | null;
    }>;
  };
  limitations: string[];
}
export function isPipelineReport(value: unknown): value is PipelineReport {
  return isRecord(value) && value.report === "cir-current-pipeline-synthetic-v1" && isRecord(value.scenarios)
    && isRecord(value.precision) && isRecord(value.population) && isRecord(value.honest_claims);
}
export interface RunResultView {
  kind: "summary" | "case"; case_count: number; case_id?: string;
  case_preview?: RunCase[]; case_preview_lanes?: Record<string, LaneEntry>;
  rule_flagged_listed_case_ids?: string[]; indicator_reason_summaries?: Record<string, string[]>;
}
export interface RunCaseListResponse {
  availability: "available"; run_id: string; items: Array<{ case: RunCase; lane: LaneEntry | null }>;
  total_matching: number; total_cases: number; reviewed_case_count: number | null; offset: number; limit: number; sort: string;
}
export type RunCaseSort = "rule_index" | "checks" | "similarity_rarity" | "ml_rank" | "review_updated" | "case_ref" | "stored";
export interface RunCaseQuery {
  offset: number; limit: number; sort: RunCaseSort; indicator?: string; search?: string; review_filter?: string; lane?: Lane;
  assigned?: "me" | "none";
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
export interface RunAuditConfirmation {
  confirmation_id: string; audit_result: AuditResult; audit_reference: string; note: string | null;
  recorded_at: string; recorded_by_user_id: string;
}
export interface RunReviewResponse {
  availability: "available"; data_source: "synthetic_data_batch" | "bpjs_fkrtl_local_sample"; review_id: string | null;
  run_id: string; case_id: string; review_status: RunReviewStatus; review_status_label: string;
  review_outcome: ReviewOutcome | null; review_outcome_label: string | null; note: string | null;
  created_at: string | null; updated_at: string | null; updated_by_user_id: string | null;
  history: RunReviewEvent[]; notice: string;
  /** Absent from servers that predate authorized audit results. */
  audit_result?: AuditResult | null; audit_result_label?: string | null; audit_confirmations?: RunAuditConfirmation[];
  /** False when the signed-in role may see the audit result but not its reference, remarks or recorder. */
  audit_details_visible?: boolean;
}

export interface FkrtlSourceStatus {
  source_type: "bpjs_fkrtl_local"; label: string; classification: "bpjs_sample_local";
  schema_profile: string; mapping_version: string; configured: boolean; available: boolean;
  max_rows: number | null; date_from?: string | null; date_to?: string | null;
  issues: Array<{ code: string; message: string }>;
  /** Offline-trained ML artifact status; absent on older servers. Does not block runs. */
  ml_model?: { available: boolean; model_version: string; error_code: string | null } | null;
}

export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
}

export interface DataSource {
  kind: "synthetic" | "local" | "none";
  label: string | null;
  classification?: string;
  source_schema_profile?: string;
  mapping_version?: string;
  limitations?: string[];
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
  /** Present for pattern-only checks; repeat_billing "not_established" means no billing evidence. */
  interpretation?: Record<string, string> | null;
}

export interface IndicatorCoverage {
  indicator: IndicatorCode;
  status: "complete" | "partial" | "unavailable" | "not_applicable";
  records_assessed: number;
  records_not_applicable: number;
  records_unassessed: number;
  /** Reason code -> records, each unassessed record counted once; absent in older saved runs. */
  unassessed_reason_counts?: Record<string, number>;
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
function isAuditResult(value: unknown): value is AuditResult {
  return value === "confirmed_issue" || value === "confirmed_no_issue";
}
function isAuditConfirmations(value: unknown): boolean {
  return value === undefined || (Array.isArray(value) && value.every(item => isRecord(item) && isString(item.confirmation_id)
    && isAuditResult(item.audit_result) && isString(item.audit_reference) && isNullableString(item.note)
    && isString(item.recorded_at) && isString(item.recorded_by_user_id)));
}
function isReviewOutcome(value: unknown): value is ReviewOutcome {
  return value === "signal_supported" || value === "signal_not_supported" || value === "inconclusive";
}
function isRunSourceType(value: unknown): value is RunSourceType {
  return value === "synthetic_csv" || value === "bpjs_fkrtl_local";
}
function isBatchMetadata(value: unknown): value is BatchMetadata {
  if (!isRecord(value) || !isString(value.batch_id) || !isString(value.batch_key) || !isNumber(value.batch_version)
    || !isString(value.created_at) || !isString(value.creator_user_id) || !isRunSourceType(value.source_type)
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
    && isString(value.content_checksum) && isRunSourceType(value.source_type)
    && (value.source_classification === "synthetic_only_declared" || value.source_classification === "bpjs_sample_local")
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
function isMlAnomalyRank(value: unknown): value is MlAnomalyRank {
  return isRecord(value) && isNumber(value.rank) && isNumber(value.anomaly_score) && isNumber(value.anomaly_percentile);
}
function isDurationCandidate(value: unknown): value is DurationCandidate {
  return isRecord(value) && isString(value.case_id) && isNumber(value.span_days) && isString(value.peer_group_definition)
    && isNumber(value.peer_support) && isNumber(value.peer_threshold_days) && isNumber(value.peer_median_days)
    && isNumber(value.share_of_peers_with_shorter_span) && isString(value.explanation);
}
function isDurationScreen(value: unknown): value is DurationScreen {
  return isRecord(value) && isString(value.status) && isString(value.version) && isNumber(value.input_record_count)
    && isNumber(value.assessed_count) && isNumber(value.unassessed_count) && isNumber(value.candidate_count)
    && Array.isArray(value.candidates) && value.candidates.every(isDurationCandidate) && isStringArray(value.limitations);
}
function isMlAnomaly(value: unknown): value is MlAnomaly {
  return isRecord(value) && isString(value.status) && isString(value.model_version)
    && isNumber(value.records_considered) && isNumber(value.records_scored)
    && typeof value.items_truncated === "boolean" && isStringArray(value.limitations)
    && Array.isArray(value.items) && value.items.every(item => isMlAnomalyRank(item) && isRecord(item)
      && isString(item.case_id) && isString(item.explanation) && Array.isArray(item.top_deviations)
      && item.top_deviations.every(d => isRecord(d) && isString(d.feature) && isString(d.description) && isNumber(d.percentile)));
}
function isRunCase(value: unknown): value is RunCase {
  return isRecord(value) && (value.ml_anomaly === undefined || value.ml_anomaly === null || isMlAnomalyRank(value.ml_anomaly))
    && isString(value.case_id) && isNullableNumber(value.risk_score)
    && isString(value.score_status) && isStringArray(value.indicators)
    && Array.isArray(value.indicator_coverage) && value.indicator_coverage.every(item => isRecord(item)
      && isString(item.indicator) && isString(item.status) && isNullableString(item.reason))
    && Array.isArray(value.reasons) && value.reasons.every(item => isRecord(item)
      && isString(item.indicator) && isString(item.summary) && isStringArray(item.evidence)
      && isStringArray(item.limitations)) && isStringArray(value.limitations);
}
function isRunResult(value: unknown): value is RunResult {
  if (!isRecord(value)) return false;
  const baseShape = {
    availability: isString(value.availability), execution_status: isString(value.execution_status),
    data_source: isSource(value.data_source), records_considered: isNumber(value.records_considered),
    records_eligible: isNumber(value.records_eligible), indicators: Array.isArray(value.indicators),
    indicator_coverage: Array.isArray(value.indicator_coverage), risk_scoring: isRecord(value.risk_scoring),
    audit_priority: isRecord(value.audit_priority), cases: isRecord(value.cases),
    action_policy: isRecord(value.action_policy),
    limitations: value.limitations === undefined || isStringArray(value.limitations),
    // Runs persisted before the ML ranking existed have no ml_anomaly section.
    ml_anomaly: value.ml_anomaly === undefined || isMlAnomaly(value.ml_anomaly),
    length_of_stay: value.length_of_stay === undefined || isDurationScreen(value.length_of_stay),
  };
  if (!Object.values(baseShape).every(Boolean)) return false;
  if (!Array.isArray(value.indicators) || !Array.isArray(value.indicator_coverage)
    || !isRecord(value.risk_scoring) || !isRecord(value.audit_priority)
    || !isRecord(value.cases) || !isRecord(value.action_policy)) return false;
  const scoring = value.risk_scoring;
  const priority = value.audit_priority;
  const policy = value.action_policy;
  const shape = {
    indicators: value.indicators.every(item => isRecord(item) && isString(item.code) && isString(item.name)
    && isString(item.status) && isNullableNumber(item.candidate_count) && isNullableNumber(item.candidate_group_count)
    && isNumber(item.eligible_count) && isNumber(item.not_applicable_count) && isNumber(item.unassessed_count)
    && typeof item.search_truncated === "boolean" && isString(item.definition) && isStringArray(item.limitations)),
    coverage: value.indicator_coverage.every(item => isRecord(item) && isString(item.indicator) && isString(item.status)
      && isNumber(item.records_assessed) && isNumber(item.records_not_applicable) && isNumber(item.records_unassessed)
      && typeof item.search_truncated === "boolean" && isNullableNumber(item.candidate_group_count) && isStringArray(item.limitations)),
    scoring: isString(scoring.version) && isRecord(scoring.weights) && Object.values(scoring.weights).every(isNumber)
      && isString(scoring.weight_basis) && isNumber(scoring.unassessable_case_count) && isStringArray(scoring.limitations),
    priority: isString(priority.status) && isString(priority.priority_version) && isString(priority.unit)
    && isString(priority.formula) && Array.isArray(priority.items) && priority.items.every(isJsonValue)
    && isStringArray(priority.eligibility_reasons) && isStringArray(priority.limitations),
    cases: Object.values(value.cases).every(isRunCase),
    action_policy: isString(policy.status) && isString(policy.unit) && isString(policy.policy_version)
    && isString(policy.input_assessment_status) && isRecord(policy.lane_counts)
    && Object.values(policy.lane_counts).every(isNumber) && isRecord(policy.cases)
    && Object.values(policy.cases).every(item => isRecord(item) && isString(item.lane)
      && isString(item.policy_version) && isString(item.input_assessment_status)
      && isStringArray(item.reasons) && isStringArray(item.limitations)) && isStringArray(policy.limitations),
    result_view: value.result_view === undefined || isRunResultView(value.result_view),
  };
  return Object.values(shape).every(Boolean);
}
function isRunResultView(value: unknown): value is RunResultView {
  return isRecord(value) && (value.kind === "summary" || value.kind === "case") && isNumber(value.case_count)
    && (value.case_preview === undefined || (Array.isArray(value.case_preview) && value.case_preview.every(isRunCase)))
    && (value.rule_flagged_listed_case_ids === undefined || isStringArray(value.rule_flagged_listed_case_ids));
}
function isRunCaseListResponse(value: unknown): value is RunCaseListResponse {
  return isRecord(value) && value.availability === "available" && isString(value.run_id) && Array.isArray(value.items)
    && value.items.every(item => isRecord(item) && isRunCase(item.case) && (item.lane === null || isRecord(item.lane)))
    && isNumber(value.total_matching) && isNumber(value.total_cases) && isNullableNumber(value.reviewed_case_count)
    && isNumber(value.offset) && isNumber(value.limit) && isString(value.sort);
}
function isRunDetailResponse(value: unknown): value is RunDetailResponse {
  if (!isRecord(value)) return false;
  const valid = {
    availability: value.availability === "available", manifest: isRunManifest(value.run),
    result: value.result === null || isRunResult(value.result), notice: isString(value.notice),
  };
  return Object.values(valid).every(Boolean);
}
function isRunReviewResponse(value: unknown): value is RunReviewResponse {
  if (!isRecord(value) || value.availability !== "available"
    || !(value.data_source === "synthetic_data_batch" || value.data_source === "bpjs_fkrtl_local_sample")
    || !isNullableString(value.review_id) || !isString(value.run_id) || !isString(value.case_id)
    || !isRunReviewStatus(value.review_status) || !isString(value.review_status_label)
    || !(value.review_outcome === null || isReviewOutcome(value.review_outcome))
    || !isNullableString(value.review_outcome_label) || !isNullableString(value.note)
    || !isNullableString(value.created_at) || !isNullableString(value.updated_at)
    || !isNullableString(value.updated_by_user_id) || !isString(value.notice) || !Array.isArray(value.history)
    || !(value.audit_result === undefined || value.audit_result === null || isAuditResult(value.audit_result))
    || !isAuditConfirmations(value.audit_confirmations)
    || !(value.audit_details_visible === undefined || typeof value.audit_details_visible === "boolean")) return false;
  return value.history.every(item => isRecord(item) && isString(item.event_id)
    && (item.event_type === "status_changed" || item.event_type === "outcome_recorded" || item.event_type === "outcome_changed")
    && isString(item.occurred_at) && isString(item.actor_user_id)
    && (item.previous_status === null || isRunReviewStatus(item.previous_status))
    && (item.new_status === null || isRunReviewStatus(item.new_status))
    && (item.previous_outcome === null || isReviewOutcome(item.previous_outcome))
    && (item.new_outcome === null || isReviewOutcome(item.new_outcome)) && isNullableString(item.note));
}
export interface RunReviewSummaryItem {
  case_id: string; review_status: RunReviewStatus; review_outcome: ReviewOutcome | null; updated_at: string;
  audit_result?: AuditResult | null;
}
export interface RunReviewListResponse {
  run_id: string; initial_status: RunReviewStatus; items: RunReviewSummaryItem[]; notice: string;
}
function isRunReviewListResponse(value: unknown): value is RunReviewListResponse {
  return isRecord(value) && isString(value.run_id) && isRunReviewStatus(value.initial_status) && isString(value.notice)
    && Array.isArray(value.items) && value.items.every(item => isRecord(item) && isString(item.case_id)
      && isRunReviewStatus(item.review_status) && (item.review_outcome === null || isReviewOutcome(item.review_outcome))
      && isString(item.updated_at) && (item.audit_result === undefined || item.audit_result === null || isAuditResult(item.audit_result)));
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
    || value === "temporal_pattern_candidate" || value === "supporting_evidence_completeness_candidate"
    || value === "length_of_stay_extreme_candidate" || value === "rapid_readmission_candidate"
    || value === "unusual_severity_candidate" || value === "cloned_clinical_note_candidate"
    || value === "severity_without_secondary_candidate" || value === "unusual_special_topup_candidate";
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
    throw new ApiClientError("Server tidak dapat dihubungi. Periksa koneksi lalu coba lagi.");
  }

  if (response.status === 204) return undefined as T;
  let payload: unknown;
  try {
    const text = await response.text();
    // A successful reply without a body (e.g. 202 "accepted, running in the background") is a success.
    if (response.ok && !text.trim()) return undefined as T;
    payload = JSON.parse(text) as unknown;
  } catch {
    throw new ApiClientError(`Terjadi gangguan di server. Coba lagi beberapa saat lagi (kode ${response.status}).`, response.status);
  }

  if (!response.ok) {
    const errorBody = isRecord(payload) && isRecord(payload.error) ? payload.error : null;
    const code = errorBody && isString(errorBody.code) ? errorBody.code : null;
    const serverMessage = errorBody && isString(errorBody.message) ? errorBody.message : null;
    const message = (code && ERROR_MESSAGES[code]) ?? serverMessage ?? `Permintaan gagal. Coba lagi beberapa saat lagi (kode ${response.status}).`;
    const requestId = errorBody && isString(errorBody.request_id) ? errorBody.request_id : null;
    if (response.status === 401 && code === "AUTHENTICATION_REQUIRED") notifySessionExpired();
    throw new ApiClientError(message, response.status, code, requestId);
  }

  if (!guard(payload)) {
    throw new ApiClientError(`Terjadi gangguan di server. Coba lagi beberapa saat lagi (kode ${response.status}).`, response.status);
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

export function getBatches(limit = 50, offset = 0, signal?: AbortSignal, removed = false): Promise<BatchListResponse> {
  return getJson(`/api/v1/batches${queryString({ limit, offset, ...(removed ? { removed: "true" } : {}) })}`, isBatchListResponse, signal);
}
export function getBatch(batchId: string, signal?: AbortSignal): Promise<BatchDetailResponse> {
  return getJson(`/api/v1/batches/${encodeURIComponent(batchId)}`, isBatchDetailResponse, signal);
}
/** A file whose header uses the BPJS claim column names (PSTV01, FKL02, ...) is sent as the BPJS format. */
async function csvFormat(file: File): Promise<[string, string]> {
  const header = (await file.slice(0, 4096).text()).replace(/^﻿/, "").split(/\r?\n/, 1)[0] ?? "";
  return header.split(",").map(cell => cell.trim()).includes("PSTV01")
    ? ["bpjs-fkrtl-csv-v1", "bpjs-fkrtl-sample-map-v2"]
    : ["synthetic-claims-v1", "synthetic-canonical-v1"];
}
export async function importSyntheticCsv(file: File, batchKey: string): Promise<BatchImportResponse> {
  const [schema, mapping] = await csvFormat(file);
  return requestJson("/api/v1/batches/import", isBatchImportResponse, {
    method: "POST", body: file,
    headers: {
      "Content-Type": "text/csv",
      "X-Batch-Key": batchKey,
      "X-Synthetic-Schema-Version": schema,
      "X-Synthetic-Mapping-Version": mapping,
      "X-Data-Classification": "synthetic_only",
    },
  });
}
export function getRuns(limit = 50, offset = 0, batchId?: string, signal?: AbortSignal, archived = false): Promise<RunListResponse> {
  return getJson(`/api/v1/runs${queryString({ limit, offset, batch_id: batchId, ...(archived ? { archived: "true" } : {}) })}`, isRunListResponse, signal);
}
function isFkrtlSourceStatus(value: unknown): value is FkrtlSourceStatus {
  return isRecord(value) && value.source_type === "bpjs_fkrtl_local" && isString(value.label)
    && value.classification === "bpjs_sample_local" && isString(value.schema_profile) && isString(value.mapping_version)
    && typeof value.configured === "boolean" && typeof value.available === "boolean" && isNullableNumber(value.max_rows)
    && Array.isArray(value.issues) && value.issues.every(item => isRecord(item) && isString(item.code) && isString(item.message));
}
export function getFkrtlSourceStatus(signal?: AbortSignal): Promise<FkrtlSourceStatus> {
  return getJson("/api/v1/sources/fkrtl-local", isFkrtlSourceStatus, signal);
}
export interface FkrtlCheckReadiness {
  check: string; status: "applicable" | "not_applicable"; required_columns: string[]; optional_columns: string[];
  rule: string; rows_in_window: number; rows_meeting_prerequisites: number;
  /** Rows failing the detector's own row-level prerequisite, by reason code. */
  rows_excluded: Record<string, number>;
}
/** Counts, column names and the admission-date range only; the server never returns rows, IDs or paths. */
export interface FkrtlValidationReport {
  status: "passed" | "passed_with_warnings" | "failed";
  errors: Array<{ code: string; message: string }>; warnings: Array<{ code: string; message: string }>;
  date_window?: { from: string; to: string } | null; max_rows?: number | null;
  scan: {
    rows_total?: number; rows_in_window?: number; columns_present?: string[]; columns_missing?: string[];
    missing_value_counts?: Record<string, number>; admission_date_invalid?: number; discharge_date_invalid?: number;
    duplicate_visit_rows?: number; admission_date_range?: { from: string; to: string } | null;
  } | null;
  checks: FkrtlCheckReadiness[];
}
export interface FkrtlValidationJob {
  job_id: string; status: "pending" | "running" | "completed" | "failed"; requested_at: string;
  started_at: string | null; finished_at: string | null; rows_scanned: number; rows_total: number | null; error_code: string | null;
}
export interface FkrtlValidationState {
  state: "not_validated" | "validated"; current: boolean | null; validated_at: string | null;
  report: FkrtlValidationReport | null;
  /** Background validation job (absent on older servers) and the combined phase the run gate uses. */
  job?: FkrtlValidationJob | null;
  phase?: "not_validated" | "pending" | "running" | "passed" | "passed_with_warnings" | "failed" | "stale";
}
export function validationJobActive(validation: FkrtlValidationState | null): boolean {
  return validation?.job?.status === "pending" || validation?.job?.status === "running";
}
function isFkrtlValidationState(value: unknown): value is FkrtlValidationState {
  if (!isRecord(value) || (value.state !== "not_validated" && value.state !== "validated")) return false;
  if (value.job !== undefined && value.job !== null && !(isRecord(value.job) && isString(value.job.job_id)
    && ["pending", "running", "completed", "failed"].includes(String(value.job.status)) && isNumber(value.job.rows_scanned))) return false;
  if (value.report === null || value.report === undefined) return value.state === "not_validated";
  const report = value.report;
  return isRecord(report) && ["passed", "passed_with_warnings", "failed"].includes(String(report.status))
    && Array.isArray(report.errors) && Array.isArray(report.warnings) && Array.isArray(report.checks)
    && (report.scan === null || isRecord(report.scan));
}
export function getFkrtlValidation(signal?: AbortSignal): Promise<FkrtlValidationState> {
  return getJson("/api/v1/sources/fkrtl-local/validation", isFkrtlValidationState, signal);
}
export type NotificationKind = "validation_finished" | "run_finished" | "case_escalated" | "outcome_recorded" | "audit_result_recorded";
export interface NotificationItem {
  id: string; kind: NotificationKind; occurred_at: string; status: string | null;
  run_id?: string; case_id?: string; source_type?: string; error_code?: string | null;
}
export interface NotificationsResponse { availability: "available"; items: NotificationItem[]; next_since: string; server_time: string; }
function isNotificationsResponse(value: unknown): value is NotificationsResponse {
  return isRecord(value) && value.availability === "available" && isString(value.next_since) && Array.isArray(value.items)
    && value.items.every(item => isRecord(item) && isString(item.id) && isString(item.kind) && isString(item.occurred_at));
}
/** Events after `since` that the signed-in user may see (structured fields only). Without `since`, only what happens next. */
export function getNotifications(since: string | null, signal?: AbortSignal): Promise<NotificationsResponse> {
  const query = since ? `?since=${encodeURIComponent(since)}` : "";
  return getJson(`/api/v1/notifications${query}`, isNotificationsResponse, signal);
}
/** Starts a background validation (HTTP 202) and returns at once; poll getFkrtlValidation for the outcome. */
export function validateFkrtlSource(): Promise<FkrtlValidationState> {
  return requestJson("/api/v1/sources/fkrtl-local/validation", isFkrtlValidationState, { method: "POST" });
}
export function createRun(payload: { batch_id?: string; source_type?: RunSourceType; retry_of_run_id?: string; action_policy_version?: string }): Promise<RunCreateResponse> {
  return requestJson("/api/v1/runs", isRunCreateResponse, { method: "POST", body: JSON.stringify(payload) });
}
/** Hide a finished run from the history; its result and reviews stay stored. */
export function archiveRun(runId: string): Promise<void> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(runId)}/archive`, (_value): _value is void => true, { method: "POST" });
}
export interface InboxFile {
  file_name: string; received_at: string; finished_at: string | null; trigger: string;
  status: "processing" | "analysed" | "rejected" | "failed"; row_count: number | null; run_id: string | null; message_code: string | null;
}
export interface InboxState {
  configured: boolean; folder_name: string | null; daily_at: string; scheduler_active: boolean; running: boolean;
  next_pull_at: string | null; last_pull: { started_at: string; finished_at: string | null; trigger: string; files_found: number; files_processed: number } | null;
  waiting_files: string[]; waiting_count: number; files: InboxFile[];
}
function isInboxState(value: unknown): value is InboxState {
  return isRecord(value) && typeof value.configured === "boolean" && typeof value.running === "boolean"
    && Array.isArray(value.files) && Array.isArray(value.waiting_files) && isString(value.daily_at);
}
/** The automatic intake folder: schedule, waiting files and the files already taken. */
export function getInbox(signal?: AbortSignal): Promise<InboxState> {
  return getJson("/api/v1/inbox", isInboxState, signal);
}
/** Take the files waiting in the intake folder now (runs in the background on the server). */
export function pullInbox(): Promise<void> {
  return requestJson("/api/v1/inbox/pull", (_value): _value is void => true, { method: "POST" });
}
export interface CaseAssignment { user_id: string; username: string; assigned_at: string; is_me: boolean; }
/** Who holds which claim of this analysis (claims nobody took are absent). */
export function getRunAssignments(runId: string, signal?: AbortSignal): Promise<{ run_id: string; items: Record<string, CaseAssignment> }> {
  return getJson(`/api/v1/runs/${encodeURIComponent(runId)}/assignments`,
    (value): value is { run_id: string; items: Record<string, CaseAssignment> } => isRecord(value) && isRecord(value.items), signal);
}
/** Take a claim (so others see it is being handled) or release it. */
export function changeAssignment(runId: string, caseId: string, action: "take" | "release"): Promise<{ case_id: string; assignment: CaseAssignment | null }> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}/assignment`,
    (value): value is { case_id: string; assignment: CaseAssignment | null } => isRecord(value) && isString(value.case_id),
    { method: "POST", body: JSON.stringify({ action }) });
}
/** Show an archived run in the history again. */
export function restoreRun(runId: string): Promise<void> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(runId)}/archive`, (_value): _value is void => true, { method: "DELETE" });
}
/** Show a removed CSV file in the list again. */
export function restoreBatch(batchId: string): Promise<void> {
  return requestJson(`/api/v1/batches/${encodeURIComponent(batchId)}/restore`, (_value): _value is void => true, { method: "POST" });
}
/** Hide an uploaded CSV file from the list; its rows and runs stay stored. */
export function removeBatch(batchId: string): Promise<void> {
  return requestJson(`/api/v1/batches/${encodeURIComponent(batchId)}`, (_value): _value is void => true, { method: "DELETE" });
}
/** Run manifest and result summary; per-case objects are loaded separately (see getRunCases/getRunCase). */
export function getRun(runId: string, signal?: AbortSignal): Promise<RunDetailResponse> {
  return getJson(`/api/v1/runs/${encodeURIComponent(runId)}?view=summary`, isRunDetailResponse, signal);
}
/** One page of rule-flagged claims from the stored result (server-side order and filters). */
export function getRunCases(runId: string, query: RunCaseQuery, signal?: AbortSignal): Promise<RunCaseListResponse> {
  return getJson(`/api/v1/runs/${encodeURIComponent(runId)}/cases${queryString(query)}`, isRunCaseListResponse, signal);
}
/** The stored result scoped to one claim (rule case, ML-ranked item or duration candidate). */
export function getRunCase(runId: string, caseId: string, signal?: AbortSignal): Promise<RunDetailResponse> {
  return getJson(`/api/v1/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}`, isRunDetailResponse, signal);
}
/** Number of rule-flagged claims, whether the result is a full snapshot or a summary view. */
export function flaggedCaseCount(result: RunResult): number {
  return result.result_view?.case_count ?? Object.keys(result.cases).length;
}
/** Rule-flagged IDs among the ML-ranked and duration-screen lists (complete in every view). */
export function ruleFlaggedListedIds(result: RunResult): Set<string> {
  return new Set(result.result_view?.rule_flagged_listed_case_ids ?? Object.keys(result.cases));
}
export function getRunReviews(runId: string, signal?: AbortSignal): Promise<RunReviewListResponse> {
  return getJson(`/api/v1/runs/${encodeURIComponent(runId)}/reviews`, isRunReviewListResponse, signal);
}
export function getRunCaseReview(runId: string, caseId: string, signal?: AbortSignal): Promise<RunReviewResponse> {
  return getJson(`/api/v1/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}/review`, isRunReviewResponse, signal);
}
export function updateRunCaseReview(runId: string, caseId: string, payload: { review_status: RunReviewStatus; note?: string | null }): Promise<RunReviewResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}/review`, isRunReviewResponse,
    { method: "PATCH", body: JSON.stringify(payload) });
}
export function recordRunCaseAuditConfirmation(runId: string, caseId: string, payload: { audit_result: AuditResult; audit_reference: string; note?: string | null }): Promise<RunReviewResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}/review/audit-confirmation`, isRunReviewResponse,
    { method: "POST", body: JSON.stringify(payload) });
}
export function recordRunCaseOutcome(runId: string, caseId: string, payload: { review_outcome: ReviewOutcome; note?: string | null }): Promise<RunReviewResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}/review/outcome`, isRunReviewResponse,
    { method: "POST", body: JSON.stringify(payload) });
}

export type ClinicalVerdictCode = "sesuai" | "perlu_dicek" | "mencurigakan";
/** Stage 2 reading aid: a language model's (or the fallback's) reading of the note next to the billed codes. */
export interface ClinicalAnalysis {
  created_at: string;
  model: string;
  requested_by_user_id: string;
  requested_by: string;
  /** "llm": the language model read the note; "fallback": text rules, used when the model is off or failed. */
  engine: "llm" | "fallback";
  fallback_reason: string | null;
  /** Facts the model read from the note before judging; null for the fallback reading. */
  fakta_catatan?: {
    keparahan_menurut_catatan: "ringan" | "sedang" | "berat" | "tidak_disebut";
    komplikasi_atau_komorbid: "ya" | "tidak" | "tidak_disebut";
    lama_rawat_menurut_catatan_hari: number | null;
    menyebut_lanjutan_perawatan_sebelumnya: boolean;
  } | null;
  verdict: ClinicalVerdictCode;
  ringkasan: string;
  alasan: string[];
  yang_perlu_diperiksa: string[];
}
export interface ClinicalNoteResponse {
  run_id: string;
  case_id: string;
  clinical_note: string | null;
  source: "uploaded_example" | "bpjs_sample";
  ai_configured: boolean;
  ai_provider: "ollama" | "anthropic";
  ai_model: string;
  fallback_model: string;
  /** The coded facts the note is read against (names from the exported code dictionary, null when unknown). */
  claim: {
    primary_diagnosis: string | null; primary_diagnosis_name: string | null;
    claim_group: string | null; claim_group_name: string | null; stay_days: number | null;
  } | null;
  analysis: ClinicalAnalysis | null;
}
function isClinicalAnalysis(value: unknown): value is ClinicalAnalysis {
  return isRecord(value) && (value.verdict === "sesuai" || value.verdict === "perlu_dicek" || value.verdict === "mencurigakan")
    && isString(value.ringkasan) && isStringArray(value.alasan) && isStringArray(value.yang_perlu_diperiksa);
}
/** The claim's clinical note (uploaded files with a CATATAN_KLINIS column only) and the latest AI reading. */
export function getClinicalNote(runId: string, caseId: string, signal?: AbortSignal): Promise<ClinicalNoteResponse> {
  return getJson(`/api/v1/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}/clinical-note`,
    (value): value is ClinicalNoteResponse => isRecord(value) && (value.clinical_note === null || isString(value.clinical_note))
      && typeof value.ai_configured === "boolean" && (value.analysis === null || isClinicalAnalysis(value.analysis)), signal);
}
/** Ask the AI to read the note; the result is stored with the model name and the requesting user. */
export function requestClinicalAnalysis(runId: string, caseId: string): Promise<{ analysis: ClinicalAnalysis }> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}/clinical-analysis`,
    (value): value is { analysis: ClinicalAnalysis } => isRecord(value) && isClinicalAnalysis(value.analysis), { method: "POST" });
}
