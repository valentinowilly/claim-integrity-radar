"""Run-scoped review and outcome routes; legacy review routes remain unchanged."""

from fastapi import APIRouter, Depends, Request

from app.api.errors import ApiError
from app.schemas.run_reviews import (
    OUTCOME_LABELS, STATUS_LABELS, OutcomeMutation, ReviewMutation, RunReviewResponse,
)
from app.security.auth import Principal
from app.security.dependencies import require_csrf, require_permission
from app.services.run_reviews import (
    RunNotReviewable, RunReviewNotFound, RunReviewStorageError, RunReviewStore,
)


router = APIRouter(prefix="/api/v1/runs/{run_id}/cases/{case_id}/review", tags=["run-scoped review"])


def _response(run_id: str, case_id: str, state: dict) -> dict:
    return {
        "availability": "available",
        "data_source": "synthetic_data_batch",
        **state,
        "review_status_label": STATUS_LABELS[state["review_status"]],
        "review_outcome_label": OUTCOME_LABELS[state["review_outcome"]]
        if state["review_outcome"] else None,
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
    if isinstance(exc, RunReviewStorageError):
        raise ApiError(503, "RUN_REVIEW_STORAGE_UNAVAILABLE", str(exc), {}) from exc


@router.get("", response_model=RunReviewResponse)
def get_run_case_review(run_id: str, case_id: str, request: Request,
                        _principal: Principal = Depends(require_permission("review:read"))):
    try:
        state = _store(request).get_review(run_id, case_id)
    except (RunReviewNotFound, RunNotReviewable, RunReviewStorageError) as exc:
        _translate(exc)
    return _response(run_id, case_id, state)


@router.patch("", response_model=RunReviewResponse)
def update_run_case_review(run_id: str, case_id: str, payload: ReviewMutation, request: Request,
                           principal: Principal = Depends(require_permission("review:write")),
                           _csrf: Principal = Depends(require_csrf)):
    try:
        state = _store(request).set_status(run_id, case_id, payload.review_status, payload.note, principal.user_id)
    except (RunReviewNotFound, RunNotReviewable, RunReviewStorageError) as exc:
        _translate(exc)
    return _response(run_id, case_id, state)


@router.post("/outcome", response_model=RunReviewResponse)
def record_run_case_outcome(run_id: str, case_id: str, payload: OutcomeMutation, request: Request,
                            principal: Principal = Depends(require_permission("review:manage")),
                            _csrf: Principal = Depends(require_csrf)):
    try:
        state = _store(request).set_outcome(run_id, case_id, payload.review_outcome, payload.note, principal.user_id)
    except (RunReviewNotFound, RunNotReviewable, RunReviewStorageError) as exc:
        _translate(exc)
    return _response(run_id, case_id, state)
