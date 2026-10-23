"""Pydantic response models for analytics endpoints."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


Availability = Literal["available", "not_configured", "insufficient_data", "unavailable"]
AnalysisExecutionStatus = Literal["completed", "partial", "failed"]
IndicatorCode = Literal[
    "repeat_billing_candidate", "similar_claim_pattern_candidate",
    "near_duplicate_claim_candidate", "synthetic_capacity_candidate",
    "temporal_pattern_candidate", "supporting_evidence_completeness_candidate",
]
RiskLevel = Literal["high", "medium", "low"] | None
CaseStatus = Literal["pending", "in_review", "resolved"]
IndicatorRunStatus = Literal["complete", "partial", "unavailable", "not_applicable"]
IndicatorState = Literal["triggered", "not_triggered", "not_applicable", "not_assessed"]
ScoreStatus = Literal["assessed", "assessed_no_signal", "partial_coverage", "not_assessable"]
ReviewStatus = Literal[
    "pending_review", "needs_more_evidence", "not_substantiated", "escalated"
]


class DataSource(BaseModel):
    kind: Literal["synthetic", "local", "none"]
    label: str | None


class IndicatorCount(BaseModel):
    indicator: IndicatorCode
    candidate_groups: int | None
    candidate_records: int | None
    status: IndicatorRunStatus


class DashboardMetrics(BaseModel):
    claims_reviewed: int | None
    cases_in_queue: int | None
    risk_level_counts: dict[Literal["high", "medium", "low"], int | None]
    indicator_counts: list[IndicatorCount]


class DashboardSummaryResponse(BaseModel):
    availability: Availability
    execution_status: AnalysisExecutionStatus
    data_source: DataSource
    generated_at: datetime
    period: dict[str, str | None]
    summary: DashboardMetrics
    notice: str


class AnalysisIndicator(BaseModel):
    code: IndicatorCode
    name: str
    status: IndicatorRunStatus
    candidate_count: int | None
    candidate_group_count: int | None
    eligible_count: int
    not_applicable_count: int
    unassessed_count: int
    search_truncated: bool
    definition: str
    limitations: list[str]


class IndicatorCoverage(BaseModel):
    indicator: IndicatorCode
    status: IndicatorRunStatus
    records_assessed: int
    records_not_applicable: int
    records_unassessed: int
    search_truncated: bool
    candidate_group_count: int | None
    limitations: list[str]


class RiskScoringSummary(BaseModel):
    version: str
    weights: dict[str, float]
    weight_basis: str
    unassessable_case_count: int
    limitations: list[str]


class AuditPrioritySummary(BaseModel):
    status: Literal["available", "partial", "not_assessable"]
    priority_version: str
    unit: str
    formula: str
    sorted_by: list[str]
    items: list[dict[str, Any]]
    unit_count: int
    eligible_unit_count: int
    unassigned_triggered_case_count: int
    eligibility_reasons: list[str]
    limitations: list[str]


class PlannedIndicator(BaseModel):
    code: str
    name: str
    status: Literal["planned"]
    definition: str


class AnalysisResponse(BaseModel):
    availability: Availability
    execution_status: AnalysisExecutionStatus
    data_source: DataSource
    generated_at: datetime
    filters: dict[str, str | None]
    coverage: dict[str, int]
    indicators: list[AnalysisIndicator]
    planned_indicators: list[PlannedIndicator]
    indicator_coverage: list[IndicatorCoverage]
    risk_scoring: RiskScoringSummary
    audit_priority: AuditPrioritySummary
    limitations: list[str]


class CaseReason(BaseModel):
    indicator: IndicatorCode
    summary: str
    evidence: list[str]
    limitations: list[str]
    supporting_values: dict[str, Any] = Field(default_factory=dict)


class CaseIndicatorCoverage(BaseModel):
    indicator: IndicatorCode
    status: IndicatorState
    reason: str | None


class CaseListItem(BaseModel):
    case_id: str
    risk_level: RiskLevel
    risk_score: float | None
    score_status: ScoreStatus
    scoring_version: str
    indicators: list[IndicatorCode]
    assessed_indicators: list[IndicatorCode]
    not_applicable_indicators: list[IndicatorCode]
    not_assessed_indicators: list[IndicatorCode]
    indicator_coverage: list[CaseIndicatorCoverage]
    status: CaseStatus
    review_status: ReviewStatus
    detected_at: datetime | None
    reasons: list[CaseReason]


class Pagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class AppliedFilters(BaseModel):
    risk_level: RiskLevel
    indicator: IndicatorCode | None
    status: CaseStatus | None
    review_status: ReviewStatus | None
    sort_by: Literal["risk_score", "detected_at"]
    sort_order: Literal["asc", "desc"]


class CasesResponse(BaseModel):
    availability: Availability
    execution_status: AnalysisExecutionStatus
    data_source: DataSource
    items: list[CaseListItem]
    pagination: Pagination
    applied_filters: AppliedFilters
    notice: str


class ReviewState(BaseModel):
    decision: str | None
    reviewed_at: datetime | None


class CaseDetail(BaseModel):
    case_id: str
    risk_level: RiskLevel
    risk_score: float | None
    score_status: ScoreStatus
    scoring_version: str
    status: CaseStatus
    detected_at: datetime | None
    indicators: list[IndicatorCode]
    assessed_indicators: list[IndicatorCode]
    not_applicable_indicators: list[IndicatorCode]
    not_assessed_indicators: list[IndicatorCode]
    indicator_coverage: list[CaseIndicatorCoverage]
    reasons: list[CaseReason]
    limitations: list[str]
    review: ReviewState


class CaseDetailResponse(BaseModel):
    availability: Availability
    execution_status: AnalysisExecutionStatus
    data_source: DataSource
    case: CaseDetail
    notice: str


class EvaluationResponse(BaseModel):
    availability: Availability
    data_source: DataSource
    generated_at: datetime
    evaluation: dict[str, Any] | None
    requirements_missing: list[str]
    notice: str


class ReviewUpdateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    status: ReviewStatus
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class ReviewHistoryEntry(BaseModel):
    changed_at: datetime
    previous_status: ReviewStatus | None
    status: ReviewStatus
    note: str | None
    reviewer_label: str
    actor_id: str | None = None


class CaseReviewResponse(BaseModel):
    availability: Literal["available"]
    data_source: DataSource
    case_id: str
    status: ReviewStatus
    status_label: str
    note: str | None
    reviewer_label: str | None
    updated_at: datetime | None
    history: list[ReviewHistoryEntry]
