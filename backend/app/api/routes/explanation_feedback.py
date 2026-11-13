"""Verifiers rate the reasons shown for a claim; the ratings are summed per check."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.errors import ApiError
from app.api.routes.clinical_ai import _claim
from app.security.auth import Principal
from app.security.dependencies import require_csrf, require_permission
from app.services import explanation_feedback as feedback

router = APIRouter(prefix="/api/v1", tags=["explanation feedback"])


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")
    helpful: bool
    reason: Literal["unclear", "not_matching", "too_long", "other"] | None = None


@router.post("/runs/{run_id}/cases/{case_id}/explanation-feedback")
def rate(run_id: str, case_id: str, payload: FeedbackIn, request: Request,
         principal: Principal = Depends(require_permission("review:write")),
         _csrf: Principal = Depends(require_csrf)):
    view, _record = _claim(request, run_id, case_id)  # the claim must belong to this run
    case = ((view.get("result") or {}).get("cases") or {}).get(case_id) or {}
    if payload.indicator not in (case.get("indicators") or []):
        raise ApiError(422, "INDICATOR_NOT_ON_CLAIM", "Pemeriksaan ini tidak menandai klaim tersebut.", {})
    try:
        return feedback.record(request.app.state.run_db_path, run_id=run_id, case_id=case_id, indicator=payload.indicator,
                               user_id=principal.user_id, helpful=payload.helpful, reason=payload.reason)
    except feedback.FeedbackStorageError as exc:
        raise ApiError(503, "FEEDBACK_STORAGE_UNAVAILABLE", str(exc), {}) from exc


@router.get("/runs/{run_id}/cases/{case_id}/explanation-feedback")
def my_ratings(run_id: str, case_id: str, request: Request,
               principal: Principal = Depends(require_permission("review:read"))):
    try:
        return {"items": feedback.mine(request.app.state.run_db_path, run_id=run_id, case_id=case_id, user_id=principal.user_id)}
    except feedback.FeedbackStorageError as exc:
        raise ApiError(503, "FEEDBACK_STORAGE_UNAVAILABLE", str(exc), {}) from exc


@router.get("/explanation-feedback/summary")
def ratings_summary(request: Request, run_id: str | None = None,
                    _principal: Principal = Depends(require_permission("review:read"))):
    """How often the reasons of each check helped, over all analyses or one."""
    try:
        return feedback.summary(request.app.state.run_db_path, run_id)
    except feedback.FeedbackStorageError as exc:
        raise ApiError(503, "FEEDBACK_STORAGE_UNAVAILABLE", str(exc), {}) from exc
