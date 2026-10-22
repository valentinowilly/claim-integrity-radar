"""Human-in-the-loop review status and append-only history routes."""

from fastapi import APIRouter, Request

from app.api.errors import ApiError
from app.schemas.analytics import CaseReviewResponse, ReviewUpdateRequest
from app.services.analytics import DATA_SOURCE, build_analytics_snapshot
from app.services.reviews import ReviewStorageError, ReviewStore, STATUS_LABELS


router = APIRouter(prefix="/api/v1/cases/{case_id}/review", tags=["review"])


def _candidate_exists(case_id: str) -> None:
    if case_id not in build_analytics_snapshot()["cases"]:
        raise ApiError(404, "CASE_NOT_FOUND", "Kasus tidak ditemukan.", {})


def _response(case_id: str, state: dict) -> dict:
    return {
        "availability": "available",
        "data_source": DATA_SOURCE,
        "case_id": case_id,
        **state,
        "status_label": STATUS_LABELS[state["status"]],
    }


@router.get("", response_model=CaseReviewResponse)
def get_case_review(case_id: str, request: Request):
    _candidate_exists(case_id)
    try:
        state = ReviewStore(request.app.state.review_db_path).get_review(case_id)
    except ReviewStorageError as exc:
        raise ApiError(503, "REVIEW_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    return _response(case_id, state)


@router.post("", response_model=CaseReviewResponse)
def update_case_review(case_id: str, payload: ReviewUpdateRequest, request: Request):
    _candidate_exists(case_id)
    try:
        state = ReviewStore(request.app.state.review_db_path).update_review(
            case_id, payload.status, payload.note
        )
    except ReviewStorageError as exc:
        raise ApiError(503, "REVIEW_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    return _response(case_id, state)
