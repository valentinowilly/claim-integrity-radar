"""Persistent AnalysisRun API; GET handlers only read stored snapshots."""

from fastapi import APIRouter, Depends, Request

from app.analytics.action_policy import get_action_policy_config
from app.api.errors import ApiError
from app.schemas.runs import RunCreateRequest, RunCreateResponse, RunDetailResponse, RunListResponse
from app.security.auth import Principal
from app.security.dependencies import require_csrf, require_permission
from app.services.runs import (
    AnalysisRunStore, RunExecutionError, RunInputError, RunStorageError, create_analysis_run,
)


router = APIRouter(prefix="/api/v1/runs", tags=["analysis runs"])


def _manifest(run: dict) -> dict:
    return {key: value for key, value in run.items() if key != "result"}


def _raise_input_error(error: RunInputError) -> None:
    code = str(error)
    if code == "BATCH_NOT_FOUND":
        raise ApiError(404, "BATCH_NOT_FOUND", "Batch tidak ditemukan.", {})
    if code == "RETRY_RUN_NOT_FOUND":
        raise ApiError(404, "RUN_NOT_FOUND", "AnalysisRun tidak ditemukan.", {})
    if code in {"BATCH_NOT_RUNNABLE", "BATCH_VERSION_MISMATCH", "BATCH_RECORD_COUNT_MISMATCH",
                "RUN_NOT_RETRYABLE", "RETRY_BATCH_MISMATCH", "RUN_TERMINAL",
                "ACTION_POLICY_VERSION_CONFLICT"}:
        raise ApiError(409, code, "Batch atau AnalysisRun tidak memenuhi kondisi operasi.", {})
    if code == "BATCH_ID_REQUIRED":
        raise ApiError(422, "INVALID_PAYLOAD", "batch_id wajib untuk AnalysisRun baru.", {})
    if code == "RUN_SOURCE_UNSUPPORTED":
        raise ApiError(422, "RUN_SOURCE_UNSUPPORTED", "Sumber AnalysisRun yang diminta belum didukung.", {})
    if code == "RUN_SOURCE_BATCH_MISMATCH":
        raise ApiError(409, "RUN_SOURCE_BATCH_MISMATCH", "Jenis sumber tidak sesuai dengan batch yang dipilih.", {})
    raise ApiError(422, "INVALID_RUN_REFERENCE", "Referensi AnalysisRun tidak valid.", {})


@router.post("", response_model=RunCreateResponse, status_code=201)
def create_run(payload: RunCreateRequest, request: Request,
               principal: Principal = Depends(require_permission("runs:write")),
               _csrf: Principal = Depends(require_csrf)):
    try:
        try:
            action_policy = get_action_policy_config(payload.action_policy_version) if payload.action_policy_version else None
        except ValueError as exc:
            raise ApiError(422, "ACTION_POLICY_VERSION_UNKNOWN", "Versi policy tidak tersedia.", {}) from exc
        run = create_analysis_run(
            request.app.state.run_db_path, payload.batch_id, principal.user_id, payload.retry_of_run_id,
            action_policy, source_type=payload.source_type,
        )
    except RunInputError as exc:
        _raise_input_error(exc)
    except RunStorageError as exc:
        raise ApiError(503, "RUN_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    except RunExecutionError as exc:
        raise ApiError(500, "ANALYSIS_RUN_FAILED", "Analisis gagal; status terminal tersimpan.",
                       {"run_id": exc.run_id}) from exc
    return {"run": _manifest(run),
            "notice": "Hasil run sintetis tersimpan; sinyal bukan bukti fraud dan bukan hasil data BPJS."}


@router.get("", response_model=RunListResponse)
def list_runs(request: Request, limit: int = 50, offset: int = 0, batch_id: str | None = None,
              _principal: Principal = Depends(require_permission("runs:read"))):
    if not 1 <= limit <= 100 or offset < 0:
        raise ApiError(400, "INVALID_FILTER", "limit harus 1-100 dan offset tidak boleh negatif.", {})
    try:
        data = AnalysisRunStore(request.app.state.run_db_path).list_runs(limit, offset, batch_id)
    except RunStorageError as exc:
        raise ApiError(503, "RUN_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    return {"items": [_manifest(item) for item in data["items"]], "total_items": data["total_items"],
            "limit": limit, "offset": offset, "availability": "available"}


@router.get("/{run_id}", response_model=RunDetailResponse)
def get_run(run_id: str, request: Request,
            _principal: Principal = Depends(require_permission("runs:results:read"))):
    try:
        run = AnalysisRunStore(request.app.state.run_db_path).get_run(run_id)
    except RunStorageError as exc:
        raise ApiError(503, "RUN_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    if run is None:
        raise ApiError(404, "RUN_NOT_FOUND", "AnalysisRun tidak ditemukan.", {})
    return {"availability": "available", "run": _manifest(run), "result": run["result"],
            "notice": "Hasil tersimpan dari data sintetis; GET tidak menjalankan ulang pipeline."}
