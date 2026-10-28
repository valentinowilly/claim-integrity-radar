"""Light work sharing: take or release a claim, and see who holds which claim of an analysis."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from app.api.errors import ApiError
from app.security.auth import AuthStore, Principal
from app.security.dependencies import require_csrf, require_permission
from app.services.assignments import AssignedToSomeoneElse, AssignmentStorageError, AssignmentStore
from app.services.run_reviews import RunNotReviewable, RunReviewNotFound, RunReviewStorageError, RunReviewStore

router = APIRouter(prefix="/api/v1/runs", tags=["assignments"])


class AssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["take", "release"]


def _view(request: Request, rows: dict[str, dict], principal: Principal) -> dict[str, dict]:
    names = AuthStore(request.app.state.auth_db_path).usernames({row["assignee_user_id"] for row in rows.values()})
    return {case_id: {"user_id": row["assignee_user_id"], "username": names.get(row["assignee_user_id"], "petugas lain"),
                      "assigned_at": row["assigned_at"], "is_me": row["assignee_user_id"] == principal.user_id}
            for case_id, row in rows.items()}


@router.get("/{run_id}/assignments")
def list_assignments(run_id: str, request: Request, principal: Principal = Depends(require_permission("review:read"))):
    try:
        rows = AssignmentStore(request.app.state.run_db_path).for_run(run_id)
    except AssignmentStorageError as exc:
        raise ApiError(503, "RUN_REVIEW_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    return {"run_id": run_id, "items": _view(request, rows, principal)}


@router.post("/{run_id}/cases/{case_id}/assignment")
def change_assignment(run_id: str, case_id: str, payload: AssignmentRequest, request: Request,
                      principal: Principal = Depends(require_permission("review:write")),
                      _csrf: Principal = Depends(require_csrf)):
    try:
        RunReviewStore(request.app.state.run_db_path).get_review(run_id, case_id)  # the claim must be in this run
    except RunReviewNotFound as exc:
        raise ApiError(404, "RUN_CASE_REVIEW_NOT_FOUND", "Run atau kandidat pada run tersebut tidak ditemukan.", {}) from exc
    except RunNotReviewable as exc:
        raise ApiError(409, "RUN_NOT_REVIEWABLE", "Hasil run belum tersedia untuk ditinjau.", {}) from exc
    except RunReviewStorageError as exc:
        raise ApiError(503, "RUN_REVIEW_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    store = AssignmentStore(request.app.state.run_db_path)
    try:
        if payload.action == "take":
            store.take(run_id, case_id, principal.user_id)
        else:
            store.release(run_id, case_id, principal.user_id)
        row = store.get(case_id)
    except AssignedToSomeoneElse as exc:
        name = AuthStore(request.app.state.auth_db_path).usernames({exc.assignee_user_id}).get(exc.assignee_user_id, "petugas lain")
        raise ApiError(409, "CASE_ASSIGNED_TO_OTHER", f"Klaim ini sedang ditangani {name}.", {}) from exc
    except AssignmentStorageError as exc:
        raise ApiError(503, "RUN_REVIEW_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    return {"case_id": case_id, "assignment": _view(request, {case_id: row}, principal)[case_id] if row else None}
