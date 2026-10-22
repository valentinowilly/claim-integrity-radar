"""Pydantic response models for analytics endpoints."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


Availability = Literal["available", "not_configured", "insufficient_data", "unavailable"]
IndicatorCode = Literal["repeat_billing_candidate", "similar_claim_pattern_candidate"]
RiskLevel = Literal["high", "medium", "low"] | None
CaseStatus = Literal["pending", "in_review", "resolved"]
ReviewStatus = Literal[
    "pending_review", "needs_more_evidence", "not_substantiated", "escalated"
]


class DataSource(BaseModel):
    kind: Literal["synthetic", "local", "none"]
    label: str | None


class IndicatorCount(BaseModel):
    indicator: IndicatorCode
    candidate_groups: int
    candidate_records: int


class DashboardMetrics(BaseModel):
    claims_reviewed: int | None
    cases_in_queue: int | None
    risk_level_counts: dict[Literal["high", "medium", "low"], int | None]
    indicator_counts: list[IndicatorCount]


class DashboardSummaryResponse(BaseModel):
    availability: Availability
    data_source: DataSource
    generated_at: datetime
    period: dict[str, str | None]
    summary: DashboardMetrics
    notice: str


class AnalysisIndicator(BaseModel):
    code: IndicatorCode
    name: str
    candidate_count: int
    candidate_group_count: int
    eligible_count: int
    definition: str
    limitations: list[str]


class PlannedIndicator(BaseModel):
    code: str
    name: str
    status: Literal["planned"]
    definition: str


class AnalysisResponse(BaseModel):
    availability: Availability
    data_source: DataSource
    generated_at: datetime
    filters: dict[str, str | None]
    coverage: dict[str, int]
    indicators: list[AnalysisIndicator]
    planned_indicators: list[PlannedIndicator]
    limitations: list[str]


class CaseReason(BaseModel):
    indicator: IndicatorCode
    summary: str
    evidence: list[str]
    limitations: list[str]


class CaseListItem(BaseModel):
    case_id: str
    risk_level: RiskLevel
    risk_score: float | None
    indicators: list[IndicatorCode]
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
    status: CaseStatus
    detected_at: datetime | None
    indicators: list[IndicatorCode]
    reasons: list[CaseReason]
    limitations: list[str]
    review: ReviewState


class CaseDetailResponse(BaseModel):
    availability: Availability
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
