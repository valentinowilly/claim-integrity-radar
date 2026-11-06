"""User feedback (was the explanation helpful?, questions, suggestions) and the administrators' activity history."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.errors import ApiError
from app.security.auth import AuthenticationStorageError, AuthStore, Principal
from app.security.dependencies import require_csrf, require_permission
from app.security.rate_limit import user_rate_limit
from app.services.activity import ActivityStorageError, recent_activity
from app.services.feedback import MAX_MESSAGE_LENGTH, FeedbackStorageError, FeedbackStore, clean_message
from app.services.run_reviews import RunNotReviewable, RunReviewNotFound, RunReviewStorageError, RunReviewStore

router = APIRouter(prefix="/api/v1", tags=["feedback"])

STORAGE_ERROR = ("FEEDBACK_STORAGE_UNAVAILABLE", "Penyimpanan masukan pengguna sedang tidak tersedia.")


class ClaimVoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    helpful: bool
    message: str | None = Field(default=None, max_length=MAX_MESSAGE_LENGTH)


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context: Literal["help_question", "general"]
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)


def _store(request: Request) -> FeedbackStore:
    return FeedbackStore(request.app.state.run_db_path)


def _storage_error(exc: Exception) -> ApiError:
    return ApiError(503, STORAGE_ERROR[0], STORAGE_ERROR[1], {})


def _own(item: dict | None) -> dict | None:
    """A person's own entry, without account ids."""
    if item is None:
        return None
    return {key: item[key] for key in ("feedback_id", "created_at", "updated_at", "context", "helpful", "message")}


def _claim_in_run(request: Request, run_id: str, case_id: str) -> None:
    try:
        RunReviewStore(request.app.state.run_db_path).get_review(run_id, case_id)
    except RunReviewNotFound as exc:
        raise ApiError(404, "RUN_CASE_REVIEW_NOT_FOUND", "Run atau kandidat pada run tersebut tidak ditemukan.", {}) from exc
    except RunNotReviewable as exc:
        raise ApiError(409, "RUN_NOT_REVIEWABLE", "Hasil run belum tersedia untuk ditinjau.", {}) from exc
    except RunReviewStorageError as exc:
        raise ApiError(503, "RUN_REVIEW_STORAGE_UNAVAILABLE", str(exc), {}) from exc


@router.get("/runs/{run_id}/cases/{case_id}/feedback")
def my_claim_vote(run_id: str, case_id: str, request: Request,
                  principal: Principal = Depends(require_permission("feedback:write"))):
    """This person's vote on the explanation of one claim (null when they have not voted)."""
    try:
        vote = _store(request).claim_vote(run_id, case_id, principal.user_id)
    except FeedbackStorageError as exc:
        raise _storage_error(exc) from exc
    return {"run_id": run_id, "case_id": case_id, "mine": _own(vote)}


@router.post("/runs/{run_id}/cases/{case_id}/feedback")
def vote_on_claim(run_id: str, case_id: str, payload: ClaimVoteRequest, request: Request,
                  principal: Principal = Depends(require_permission("feedback:write")),
                  _csrf: Principal = Depends(require_csrf),
                  _rate: None = Depends(user_rate_limit("feedback"))):
    """Record whether the explanation of this claim helped; voting again replaces the earlier vote."""
    _claim_in_run(request, run_id, case_id)
    try:
        vote = _store(request).vote_on_claim(run_id, case_id, principal.user_id, principal.role, payload.helpful,
                                             clean_message(payload.message))
    except FeedbackStorageError as exc:
        raise _storage_error(exc) from exc
    return {"run_id": run_id, "case_id": case_id, "mine": _own(vote)}


@router.post("/feedback", status_code=201)
def send_message(payload: MessageRequest, request: Request,
                 principal: Principal = Depends(require_permission("feedback:write")),
                 _csrf: Principal = Depends(require_csrf),
                 _rate: None = Depends(user_rate_limit("feedback"))):
    """A question or suggestion from the help page."""
    message = clean_message(payload.message)
    if message is None:
        raise ApiError(422, "FEEDBACK_MESSAGE_EMPTY", "Tulis pertanyaan atau masukan terlebih dahulu.", {})
    try:
        item = _store(request).add_message(payload.context, principal.user_id, principal.role, message)
    except FeedbackStorageError as exc:
        raise _storage_error(exc) from exc
    return {"item": _own(item)}


@router.get("/feedback/summary")
def feedback_summary(request: Request, days: int = Query(default=30, ge=1, le=365),
                     _principal: Principal = Depends(require_permission("feedback:read"))):
    """How satisfied users are with the explanations, per role, and the latest questions and suggestions."""
    try:
        summary = _store(request).summary(days=days)
    except FeedbackStorageError as exc:
        raise _storage_error(exc) from exc
    names = AuthStore(request.app.state.auth_db_path).usernames({item["user_id"] for item in summary["recent_messages"]})
    summary["recent_messages"] = [
        {**_own(item), "role": item["role"], "author": names.get(item["user_id"], "akun dihapus"),
         "run_id": item["run_id"], "case_id": item["case_id"]}
        for item in summary["recent_messages"]]
    return summary


@router.get("/activity")
def activity(request: Request, limit: int = Query(default=200, ge=1, le=500),
             category: Literal["akun", "data", "analisis", "tinjauan", "lainnya"] | None = None,
             _principal: Principal = Depends(require_permission("security_audit:read"))):
    """Who did what and when (sign-in, data, analyses, reviews), newest first; event details are left out."""
    try:
        return recent_activity(AuthStore(request.app.state.auth_db_path), request.app.state.run_db_path,
                               limit=limit, category=category)
    except (ActivityStorageError, AuthenticationStorageError) as exc:
        raise ApiError(503, "ACTIVITY_UNAVAILABLE", "Riwayat aktivitas sedang tidak tersedia.", {}) from exc
