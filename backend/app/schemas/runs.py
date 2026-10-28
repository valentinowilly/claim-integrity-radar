"""Schemas for persistent AnalysisRun operations (synthetic CSV or configured FKRTL sample)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ExecutionStatus = Literal["running", "completed", "partial", "failed"]
RunSourceType = Literal["synthetic_csv", "bpjs_fkrtl_local"]


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str | None = Field(default=None, min_length=1, max_length=80)
    source_type: str = Field(default="synthetic_csv", min_length=1, max_length=40)
    retry_of_run_id: str | None = Field(default=None, min_length=1, max_length=80)
    action_policy_version: str | None = Field(
        default=None, min_length=1, max_length=80,
        pattern=r"^action-policy-[a-z0-9][a-z0-9._-]{0,60}-provisional$",
    )

    @model_validator(mode="after")
    def require_batch_or_retry(self):
        # The configured FKRTL source has no client-selected batch or path.
        if self.source_type == "bpjs_fkrtl_local":
            return self
        if self.batch_id is None and self.retry_of_run_id is None:
            raise ValueError("batch_id atau retry_of_run_id wajib diisi")
        return self


class RunManifest(BaseModel):
    # Only in archive listings: "manual", "superseded" or "older".
    archive_reason: str | None = None
    run_id: str
    batch_id: str
    batch_version: int
    content_checksum: str
    source_type: RunSourceType
    source_classification: Literal["synthetic_only_declared", "bpjs_sample_local"]
    source_schema_version: str
    source_mapping_version: str
    creator_user_id: str
    retry_of_run_id: str | None
    created_at: datetime
    started_at: datetime
    completed_at: datetime | None
    execution_status: ExecutionStatus
    failure_category: str | None
    detector_suite_version: str | None
    scoring_version: str | None
    priority_version: str | None
    action_policy_version: str | None
    configuration: dict[str, Any]
    coverage: list[dict[str, Any]] | None
    result_available: bool
    result_storage_reference: str | None


class RunCreateResponse(BaseModel):
    run: RunManifest
    notice: str


class RunDetailResponse(BaseModel):
    availability: Literal["available"]
    run: RunManifest
    result: dict[str, Any] | None
    notice: str


class RunCaseListItem(BaseModel):
    case: dict[str, Any]
    lane: dict[str, Any] | None


class RunCaseListResponse(BaseModel):
    """One page of rule-flagged claims read from the stored result (no detection rerun)."""
    availability: Literal["available"]
    run_id: str
    items: list[RunCaseListItem]
    total_matching: int
    total_cases: int
    reviewed_case_count: int | None
    offset: int
    limit: int
    sort: str


class RunListResponse(BaseModel):
    items: list[RunManifest]
    total_items: int
    limit: int
    offset: int
    availability: Literal["available"]
