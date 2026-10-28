"""Readiness of server-configured local data sources; never exposes paths or rows."""

from fastapi import APIRouter, Depends, Request

from app.api.errors import ApiError
from app.data_sources.fkrtl_local_source import (
    current_source_fingerprint, fkrtl_source_status, validate_fkrtl_local_source,
)
from app.schemas.sources import FkrtlValidationState, LocalSourceStatus
from app.security.auth import Principal
from app.security.dependencies import require_csrf, require_permission
from app.services.source_validations import SourceValidationStorageError, latest_validation
from app.services.validation_jobs import latest_job, start_validation_job


router = APIRouter(prefix="/api/v1/sources", tags=["data sources"])


@router.get("/fkrtl-local", response_model=LocalSourceStatus)
def get_fkrtl_local_source(request: Request, _principal: Principal = Depends(require_permission("batches:read"))):
    """Configuration check only; the .dta file is opened when a run is created."""
    return {**fkrtl_source_status(), "ml_model": request.app.state.ml_model_status}


def latest_fkrtl_validation(request: Request) -> dict | None:
    """Latest stored validation (aggregates only); persisted in the run SQLite file across restarts."""
    try:
        return latest_validation(request.app.state.run_db_path)
    except SourceValidationStorageError as exc:
        raise ApiError(503, "SOURCE_VALIDATION_STORAGE_UNAVAILABLE", str(exc), {}) from exc


def latest_fkrtl_validation_job(request: Request) -> dict | None:
    try:
        return latest_job(request.app.state.run_db_path)
    except SourceValidationStorageError as exc:
        raise ApiError(503, "SOURCE_VALIDATION_STORAGE_UNAVAILABLE", str(exc), {}) from exc


def job_supersedes(job: dict | None, latest: dict | None) -> bool:
    """A job requested after the latest stored validation decides the state (active or failed)."""
    if job is None or job["status"] == "completed":
        return False
    return latest is None or job["requested_at"] > latest["validated_at"].isoformat()


def _state(request: Request) -> dict:
    latest = latest_fkrtl_validation(request)
    job = latest_fkrtl_validation_job(request)
    state: dict = {"state": "not_validated", "job": job, "phase": "not_validated"}
    if latest is not None:
        current = latest["fingerprint"] is not None and latest["fingerprint"] == current_source_fingerprint()
        state.update({"state": "validated", "current": current, "validated_at": latest["validated_at"],
                      "report": latest["report"], "phase": latest["report"]["status"] if current else "stale"})
    if job_supersedes(job, latest):
        state["phase"] = job["status"]  # pending, running, or failed (job error)
    return state


@router.get("/fkrtl-local/validation", response_model=FkrtlValidationState)
def get_fkrtl_validation(request: Request, _principal: Principal = Depends(require_permission("batches:read"))):
    return _state(request)


@router.post("/fkrtl-local/validation", response_model=FkrtlValidationState, status_code=202)
def validate_fkrtl_source(request: Request, _principal: Principal = Depends(require_permission("batches:write")),
                          _csrf: Principal = Depends(require_csrf)):
    """Start a background validation (counts only) and return at once; poll GET for its state.

    A scan of the full sample takes minutes. While a job is pending or running, another
    request returns that job instead of starting a second one.
    """
    try:
        start_validation_job(request.app.state.run_db_path, current_source_fingerprint(), validate_fkrtl_local_source)
    except SourceValidationStorageError as exc:
        raise ApiError(503, "SOURCE_VALIDATION_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    return _state(request)
