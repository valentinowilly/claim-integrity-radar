"""Schemas for server-configured local data-source readiness."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class SourceIssue(BaseModel):
    code: str
    message: str


class LocalSourceStatus(BaseModel):
    source_type: Literal["bpjs_fkrtl_local"]
    label: str
    classification: Literal["bpjs_sample_local"]
    schema_profile: str
    mapping_version: str
    configured: bool
    available: bool
    max_rows: int | None
    date_from: str | None = None
    date_to: str | None = None
    issues: list[SourceIssue]
    # Status of the offline-trained ML artifact (does not block runs; rules work without it).
    ml_model: dict[str, Any] | None = None


class SourceCheckReadiness(BaseModel):
    check: str
    status: Literal["applicable", "not_applicable"]
    required_columns: list[str]
    optional_columns: list[str]
    rule: str
    rows_in_window: int
    # Rows that meet the detector's own row-level prerequisite function.
    rows_meeting_prerequisites: int
    # Rows that do not, by reason code (e.g. "missing:procedure_code", "too_few_attributes").
    rows_excluded: dict[str, int]


class FkrtlValidationReport(BaseModel):
    source_type: Literal["bpjs_fkrtl_local"]
    classification: Literal["bpjs_sample_local"]
    schema_profile: str
    mapping_version: str
    status: Literal["passed", "passed_with_warnings", "failed"]
    errors: list[SourceIssue]
    warnings: list[SourceIssue]
    date_window: dict[str, str] | None = None
    max_rows: int | None = None
    # Aggregate counts, column names and the admission-date range only; never values or IDs.
    scan: dict[str, Any] | None
    checks: list[SourceCheckReadiness]
    post_verification_amount: str | None = None


class FkrtlValidationJob(BaseModel):
    """Background validation job; counts only."""
    job_id: str
    status: Literal["pending", "running", "completed", "failed"]
    requested_at: str
    started_at: str | None = None
    finished_at: str | None = None
    rows_scanned: int = 0
    rows_total: int | None = None
    error_code: str | None = None


class FkrtlValidationState(BaseModel):
    state: Literal["not_validated", "validated"]
    # Latest background job and the combined phase a client shows: not_validated, pending,
    # running, passed, passed_with_warnings, failed (report or job), or stale.
    job: FkrtlValidationJob | None = None
    phase: str = "not_validated"
    # False when the configured file or selection changed after this validation.
    current: bool | None = None
    validated_at: datetime | None = None
    report: FkrtlValidationReport | None = None
