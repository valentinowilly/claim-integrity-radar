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
AuditResult = Literal["confirmed_issue", "confirmed_no_issue"]
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
AUDIT_RESULT_LABELS = {
    "confirmed_issue": "Masalah dikonfirmasi oleh audit berwenang",
    "confirmed_no_issue": "Tidak ada masalah menurut audit berwenang",
}
# A reference code of the authorized audit record (e.g. "AUD-2026/014"), never claim data.
_AUDIT_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:-]{2,63}")
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


class RunReviewSummaryItem(BaseModel):
    case_id: str
    review_status: ReviewStatus
    review_outcome: ReviewOutcome | None
    updated_at: datetime
    audit_result: AuditResult | None = None


class RunReviewListResponse(BaseModel):
    run_id: str
    initial_status: ReviewStatus
    items: list[RunReviewSummaryItem]
    notice: str


class AuditConfirmationMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_result: AuditResult
    audit_reference: str = Field(min_length=3, max_length=64)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("audit_reference")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        value = value.strip()
        if (not _AUDIT_REFERENCE.fullmatch(value)
                # 9+ digits, also when split by separators (participant/visit number shapes).
                or re.search(r"\d(?:[-./:]?\d){8,}", value)
                # secret and identifier keywords, as for review notes.
                or _SENSITIVE_NOTE_PATTERNS[0].search(value)
                # long unbroken segments look like tokens or keys, not reference codes.
                or any(len(part) > 20 for part in re.split(r"[-./:]", value))):
            raise ValueError("Rujukan audit harus berupa kode rujukan singkat, bukan nomor peserta, rahasia, atau data klaim.")
        return value

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        return _validate_note_content(value)


class RunAuditConfirmation(BaseModel):
    confirmation_id: str
    audit_result: AuditResult
    audit_reference: str
    note: str | None
    recorded_at: datetime
    recorded_by_user_id: str


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
    data_source: Literal["synthetic_data_batch", "bpjs_fkrtl_local_sample"]
    review_id: str | None
    run_id: str
    case_id: str
    review_status: ReviewStatus
    review_status_label: str
    review_outcome: ReviewOutcome | None
    review_outcome_label: str | None
    audit_result: AuditResult | None = None
    audit_result_label: str | None = None
    audit_confirmations: list[RunAuditConfirmation] = Field(default_factory=list)
    # False when the caller lacks review:manage; audit_confirmations is then empty, audit_result still set.
    audit_details_visible: bool = False
    note: str | None
    created_at: datetime | None
    updated_at: datetime | None
    updated_by_user_id: str | None
    history: list[RunReviewEvent]
    notice: str
