"""Run-scoped review and outcome routes; legacy review routes remain unchanged."""

from fastapi import APIRouter, Depends, Request

from app.api.errors import ApiError
from app.schemas.run_reviews import (
    AUDIT_RESULT_LABELS, OUTCOME_LABELS, STATUS_LABELS, AuditConfirmationMutation, OutcomeMutation, ReviewMutation,
    RunReviewListResponse, RunReviewResponse,
)
from app.security.auth import Principal
from app.security.dependencies import require_csrf, require_permission
from app.security.rate_limit import user_rate_limit
from app.services.run_reviews import (
    INITIAL_STATUS, AuditConfirmationRequiresReview, RunNotReviewable, RunReviewNotFound, RunReviewStorageError,
    RunReviewStore,
)


router = APIRouter(prefix="/api/v1/runs/{run_id}/cases/{case_id}/review", tags=["run-scoped review"])
# Read-only review state of a whole run, for the review queue.
summary_router = APIRouter(prefix="/api/v1/runs/{run_id}/reviews", tags=["run-scoped review"])


# Audit reference, remarks and recorder are audit-management metadata; other review roles see only the result.
AUDIT_DETAIL_PERMISSION = "review:manage"


def _response(run_id: str, case_id: str, state: dict, principal: Principal) -> dict:
    details_visible = AUDIT_DETAIL_PERMISSION in principal.permissions
    if not details_visible:
        state["audit_confirmations"] = []
    return {
        "availability": "available",
        **state,
        "audit_details_visible": details_visible,
        "data_source": ("bpjs_fkrtl_local_sample" if state.pop("source_type", None) == "bpjs_fkrtl_local"
                        else "synthetic_data_batch"),
        "review_status_label": STATUS_LABELS[state["review_status"]],
        "review_outcome_label": OUTCOME_LABELS[state["review_outcome"]]
        if state["review_outcome"] else None,
        "audit_result_label": AUDIT_RESULT_LABELS[state["audit_result"]] if state.get("audit_result") else None,
        "notice": "Status dan outcome adalah metadata tinjauan manusia, bukan penetapan fraud. "
                  "Jangan masukkan informasi peserta atau klaim sensitif ke catatan.",
    }


def _store(request: Request) -> RunReviewStore:
    return RunReviewStore(request.app.state.run_db_path)


def _translate(exc: Exception) -> None:
    if isinstance(exc, RunReviewNotFound):
        raise ApiError(404, "RUN_CASE_REVIEW_NOT_FOUND", "Run atau kandidat pada run tersebut tidak ditemukan.", {}) from exc
    if isinstance(exc, RunNotReviewable):
        raise ApiError(409, "RUN_NOT_REVIEWABLE", "Hasil run belum tersedia untuk ditinjau.", {}) from exc
    if isinstance(exc, AuditConfirmationRequiresReview):
        raise ApiError(409, "RUN_AUDIT_CONFIRMATION_REQUIRES_REVIEW",
                       "Hasil audit hanya dapat dicatat setelah kasus memiliki rekaman tinjauan.", {}) from exc
    if isinstance(exc, RunReviewStorageError):
        raise ApiError(503, "RUN_REVIEW_STORAGE_UNAVAILABLE", str(exc), {}) from exc


@summary_router.get("", response_model=RunReviewListResponse)
def list_run_reviews(run_id: str, request: Request,
                     _principal: Principal = Depends(require_permission("review:read"))):
    try:
        items = _store(request).list_reviews(run_id)
    except (RunReviewNotFound, RunNotReviewable, RunReviewStorageError) as exc:
        _translate(exc)
    return {
        "run_id": run_id, "initial_status": INITIAL_STATUS, "items": items,
        "notice": "Status dan outcome adalah metadata tinjauan manusia, bukan hasil algoritma atau penetapan fraud.",
    }


@router.get("", response_model=RunReviewResponse)
def get_run_case_review(run_id: str, case_id: str, request: Request,
                        principal: Principal = Depends(require_permission("review:read"))):
    try:
        state = _store(request).get_review(run_id, case_id)
    except (RunReviewNotFound, RunNotReviewable, RunReviewStorageError) as exc:
        _translate(exc)
    return _response(run_id, case_id, state, principal)


@router.patch("", response_model=RunReviewResponse)
def update_run_case_review(run_id: str, case_id: str, payload: ReviewMutation, request: Request,
                           principal: Principal = Depends(require_permission("review:write")),
                           _csrf: Principal = Depends(require_csrf),
                           _rate: None = Depends(user_rate_limit("review_write"))):
    try:
        state = _store(request).set_status(run_id, case_id, payload.review_status, payload.note, principal.user_id)
    except (RunReviewNotFound, RunNotReviewable, RunReviewStorageError) as exc:
        _translate(exc)
    return _response(run_id, case_id, state, principal)


@router.post("/outcome", response_model=RunReviewResponse)
def record_run_case_outcome(run_id: str, case_id: str, payload: OutcomeMutation, request: Request,
                            principal: Principal = Depends(require_permission("review:manage")),
                            _csrf: Principal = Depends(require_csrf),
                            _rate: None = Depends(user_rate_limit("review_write"))):
    try:
        state = _store(request).set_outcome(run_id, case_id, payload.review_outcome, payload.note, principal.user_id)
    except (RunReviewNotFound, RunNotReviewable, RunReviewStorageError) as exc:
        _translate(exc)
    return _response(run_id, case_id, state, principal)


@router.post("/audit-confirmation", response_model=RunReviewResponse)
def record_run_case_audit_confirmation(run_id: str, case_id: str, payload: AuditConfirmationMutation, request: Request,
                                       principal: Principal = Depends(require_permission("review:manage")),
                                       _csrf: Principal = Depends(require_csrf),
                                       _rate: None = Depends(user_rate_limit("audit_confirmation"))):
    """Record the result of an authorized audit; requires a reference to that audit record."""
    try:
        state = _store(request).record_audit_confirmation(
            run_id, case_id, payload.audit_result, payload.audit_reference, payload.note, principal.user_id)
    except (RunReviewNotFound, RunNotReviewable, AuditConfirmationRequiresReview, RunReviewStorageError) as exc:
        _translate(exc)
    return _response(run_id, case_id, state, principal)
