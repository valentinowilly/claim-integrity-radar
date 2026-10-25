"""Schemas for persistent synthetic AnalysisRun operations."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ExecutionStatus = Literal["running", "completed", "partial", "failed"]


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
        if self.batch_id is None and self.retry_of_run_id is None:
            raise ValueError("batch_id atau retry_of_run_id wajib diisi")
        return self


class RunManifest(BaseModel):
    run_id: str
    batch_id: str
    batch_version: int
    content_checksum: str
    source_type: Literal["synthetic_csv"]
    source_classification: Literal["synthetic_only_declared"]
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


class RunListResponse(BaseModel):
    items: list[RunManifest]
    total_items: int
    limit: int
    offset: int
    availability: Literal["available"]
