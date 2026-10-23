"""Run-scoped human review contracts."""

from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ReviewStatus = Literal[
    "pending_review", "in_review", "awaiting_evidence", "escalated", "closed",
]
ReviewOutcome = Literal[
    "signal_supported", "signal_not_supported", "inconclusive",
]
ReviewEventType = Literal[
    "status_changed", "outcome_recorded", "outcome_changed",
]

STATUS_LABELS = {
    "pending_review": "Menunggu Tinjauan",
    "in_review": "Dalam Tinjauan",
    "awaiting_evidence": "Menunggu Bukti Tambahan",
    "escalated": "Dieskalasikan",
    "closed": "Ditutup",
}
OUTCOME_LABELS = {
    "signal_supported": "Sinyal didukung oleh tinjauan",
    "signal_not_supported": "Sinyal tidak didukung oleh tinjauan",
    "inconclusive": "Belum dapat disimpulkan",
}
_SENSITIVE_NOTE_PATTERNS = (
    re.compile(r"(?i)\b(?:PSTV01|participant[_ -]?token|token peserta|signature|api[_ -]?key|password|secret|authorization|bearer)\b"),
    re.compile(r"\b\d[\d -]{8,}\d\b"),
    re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b"),
)


def _validate_note_content(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    lines = value.splitlines()
    if len(lines) > 1 or any(line.count(",") >= 3 for line in lines):
        raise ValueError("Catatan harus berupa ringkasan teks, bukan baris data.")
    if any(pattern.search(value) for pattern in _SENSITIVE_NOTE_PATTERNS):
        raise ValueError("Catatan tampak memuat identifier atau rahasia; gunakan ringkasan sintetis yang aman.")
    return value


class ReviewMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_status: ReviewStatus
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        return _validate_note_content(value)


class OutcomeMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_outcome: ReviewOutcome
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        return _validate_note_content(value)


class RunReviewEvent(BaseModel):
    event_id: str
    event_type: ReviewEventType
    occurred_at: datetime
    actor_user_id: str
    previous_status: ReviewStatus | None
    new_status: ReviewStatus | None
    previous_outcome: ReviewOutcome | None
    new_outcome: ReviewOutcome | None
    note: str | None


class RunReviewResponse(BaseModel):
    availability: Literal["available"]
    data_source: Literal["synthetic_data_batch"]
    review_id: str | None
    run_id: str
    case_id: str
    review_status: ReviewStatus
    review_status_label: str
    review_outcome: ReviewOutcome | None
    review_outcome_label: str | None
    note: str | None
    created_at: datetime | None
    updated_at: datetime | None
    updated_by_user_id: str | None
    history: list[RunReviewEvent]
    notice: str
