"""Public metadata-only schemas for DataBatch operations."""

from typing import Any, Literal

from pydantic import BaseModel


BatchStatus = Literal["ready", "ready_with_warnings", "rejected"]


class ValidationSummary(BaseModel):
    error_count: int
    error_counts: dict[str, int]
    errors: list[dict[str, Any]]
    errors_truncated: bool
    row_count: int | None
    warning_counts: dict[str, Any]


class BatchMetadata(BaseModel):
    batch_id: str
    batch_key: str
    batch_version: int
    created_at: str
    creator_user_id: str
    source_type: Literal["synthetic_csv", "bpjs_fkrtl_local"]
    schema_version: str
    mapping_version: str
    row_count: int | None
    status: BatchStatus
    validation: ValidationSummary


class BatchImportResponse(BaseModel):
    batch: BatchMetadata
    reused_existing: bool
    notice: str


class BatchListResponse(BaseModel):
    items: list[BatchMetadata]
    total_items: int
    limit: int
    offset: int
    availability: Literal["available"]


class BatchDetailResponse(BaseModel):
    batch: BatchMetadata
    availability: Literal["available"]
    notice: str

