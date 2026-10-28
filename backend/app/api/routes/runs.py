"""Persistent AnalysisRun API; GET handlers only read stored snapshots."""

from fastapi import APIRouter, Depends, Request, Response

from app.analytics.action_policy import get_action_policy_config
from app.api.errors import ApiError
from app.api.routes.sources import job_supersedes, latest_fkrtl_validation, latest_fkrtl_validation_job
from app.data_sources.fkrtl_local_source import FKRTL_SOURCE_TYPE, FkrtlSourceUnavailable, current_source_fingerprint
from app.schemas.runs import RunCaseListResponse, RunCreateRequest, RunCreateResponse, RunDetailResponse, RunListResponse, RunTrendResponse
from app.security.auth import Principal
from app.security.dependencies import require_csrf, require_permission
from app.services.run_results import MAX_PAGE_SIZE, SORT_KEYS
from app.services.run_reviews import (
    VALID_STATUSES, RunNotReviewable, RunReviewNotFound, RunReviewStorageError, RunReviewStore,
)
from app.services.assignments import AssignmentStorageError, AssignmentStore
from app.services.retention import archive_reasons
from app.services.runs import (
    AnalysisRunStore, RunExecutionError, RunInputError, RunStorageError, create_analysis_run,
)

_REVIEW_FILTERS = {"not_started", "has_outcome"} | VALID_STATUSES


router = APIRouter(prefix="/api/v1/runs", tags=["analysis runs"])
_NOTICES = {
    "synthetic_csv": ("Hasil analisis berkas unggahan tersimpan; temuan adalah petunjuk tinjauan, bukan bukti kecurangan.",
                      "Hasil analisis berkas unggahan; temuan adalah petunjuk tinjauan, bukan bukti kecurangan."),
    FKRTL_SOURCE_TYPE: ("Hasil run sampel FKRTL BPJS lokal tersimpan; sinyal adalah kandidat tinjauan, bukan bukti fraud.",
                        None),  # detail notice is built from the run's recorded selection
}
_FKRTL_NOTICE_TAIL = (
    " Cakupan tiap pemeriksaan bergantung pada konfigurasi dan field yang tersedia (lihat status cakupan). "
    "Sinyal bukan bukti fraud dan tidak ada label fraud terkonfirmasi. GET tidak menjalankan ulang pipeline."
)


def _detail_notice(run: dict) -> str:
    if run["source_type"] != FKRTL_SOURCE_TYPE:
        return _NOTICES[run["source_type"]][1]
    source = (run.get("configuration") or {}).get("source") or {}
    selection = source.get("selection") if isinstance(source, dict) else None
    if isinstance(selection, dict) and selection.get("strategy") == "admission_date_window" \
            and isinstance(selection.get("date_from"), str) and isinstance(selection.get("date_to"), str):
        return (
            f"Hasil tersimpan dari sampel FKRTL BPJS lokal untuk klaim dengan tanggal masuk (FKL03) "
            f"{selection['date_from']} s.d. {selection['date_to']} (inklusif); hasil hanya berlaku untuk jendela "
            "ini, bukan seluruh sampel. Jendela yang melebihi batas jumlah record ditolak, tidak dipotong."
            + _FKRTL_NOTICE_TAIL
        )
    # Runs saved before date windows used the first rows in file order.
    return ("Hasil tersimpan dari sampel FKRTL BPJS lokal untuk seleksi baris awal pada run lama (bukan jendela "
            "tanggal); hasil tidak mewakili seluruh sampel." + _FKRTL_NOTICE_TAIL)


def _manifest(run: dict) -> dict:
    return {key: value for key, value in run.items() if key not in {"result", "served_from"}}


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


def _require_current_fkrtl_validation(request: Request) -> None:
    """A run of the local FKRTL source needs a non-failed validation of the same file and settings.

    An unconfigured or unreadable source is left to the run path, which reports its own
    actionable configuration error.
    """
    current = current_source_fingerprint()
    if current is None:
        return
    latest = latest_fkrtl_validation(request)
    job = latest_fkrtl_validation_job(request)
    details = {"source_type": FKRTL_SOURCE_TYPE}
    # A newer validation job decides first: a run never starts on an older result while the
    # latest validation is still pending/running, or after it failed.
    if job_supersedes(job, latest) and job["status"] in ("pending", "running"):
        raise ApiError(409, "FKRTL_SOURCE_VALIDATION_IN_PROGRESS",
                       "Validasi sumber FKRTL sedang berjalan; tunggu hingga selesai sebelum membuat run.", details)
    if job_supersedes(job, latest) and job["status"] == "failed":
        raise ApiError(409, "FKRTL_SOURCE_VALIDATION_FAILED",
                       "Validasi terakhir untuk sumber FKRTL tidak selesai; validasi ulang sebelum membuat run.", details)
    if latest is None:
        raise ApiError(409, "FKRTL_SOURCE_NOT_VALIDATED",
                       "Validasi sumber FKRTL terlebih dahulu sebelum membuat run.", details)
    if latest["fingerprint"] != current:
        raise ApiError(409, "FKRTL_SOURCE_VALIDATION_STALE",
                       "Berkas atau konfigurasi FKRTL berubah sejak validasi terakhir; validasi ulang sebelum membuat run.",
                       details)
    if latest["report"]["status"] == "failed":
        raise ApiError(409, "FKRTL_SOURCE_VALIDATION_FAILED",
                       "Validasi terakhir untuk sumber FKRTL ini gagal; perbaiki penyebabnya dan validasi ulang "
                       "sebelum membuat run.", details)


@router.post("", response_model=RunCreateResponse, status_code=201)
def create_run(payload: RunCreateRequest, request: Request,
               principal: Principal = Depends(require_permission("runs:write")),
               _csrf: Principal = Depends(require_csrf)):
    try:
        try:
            action_policy = get_action_policy_config(payload.action_policy_version) if payload.action_policy_version else None
        except ValueError as exc:
            raise ApiError(422, "ACTION_POLICY_VERSION_UNKNOWN", "Versi policy tidak tersedia.", {}) from exc
        if payload.source_type == FKRTL_SOURCE_TYPE:
            _require_current_fkrtl_validation(request)
        run = create_analysis_run(
            request.app.state.run_db_path, payload.batch_id, principal.user_id, payload.retry_of_run_id,
            action_policy, source_type=payload.source_type,
        )
    except RunInputError as exc:
        _raise_input_error(exc)
    except FkrtlSourceUnavailable as exc:
        raise ApiError(503, exc.code, exc.message, {"source_type": FKRTL_SOURCE_TYPE}) from exc
    except RunStorageError as exc:
        raise ApiError(503, "RUN_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    except RunExecutionError as exc:
        raise ApiError(500, "ANALYSIS_RUN_FAILED", "Analisis gagal; status terminal tersimpan.",
                       {"run_id": exc.run_id}) from exc
    return {"run": _manifest(run), "notice": _NOTICES[run["source_type"]][0]}


@router.get("", response_model=RunListResponse)
def list_runs(request: Request, limit: int = 50, offset: int = 0, batch_id: str | None = None,
              archived: bool = False, _principal: Principal = Depends(require_permission("runs:read"))):
    if not 1 <= limit <= 100 or offset < 0:
        raise ApiError(400, "INVALID_FILTER", "limit harus 1-100 dan offset tidak boleh negatif.", {})
    try:
        data = AnalysisRunStore(request.app.state.run_db_path).list_runs(limit, offset, batch_id, archived)
        if archived:
            reasons = archive_reasons(request.app.state.run_db_path, [item["run_id"] for item in data["items"]])
            data["items"] = [{**item, "archive_reason": reasons.get(item["run_id"])} for item in data["items"]]
    except RunStorageError as exc:
        raise ApiError(503, "RUN_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    return {"items": [_manifest(item) for item in data["items"]], "total_items": data["total_items"],
            "limit": limit, "offset": offset, "availability": "available"}


@router.get("/trend", response_model=RunTrendResponse)
def run_trend(request: Request, limit: int = 8,
              _principal: Principal = Depends(require_permission("runs:results:read"))):
    """Lane counts and billed value of the latest listed runs, for comparisons on the overview."""
    if not 2 <= limit <= 30:
        raise ApiError(400, "INVALID_FILTER", "limit harus 2-30.", {})
    try:
        items = AnalysisRunStore(request.app.state.run_db_path).run_trend(limit)
    except RunStorageError as exc:
        raise ApiError(503, "RUN_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    return {"items": items, "availability": "available"}


@router.get("/review-accuracy")
def review_accuracy(request: Request, weeks: int = 12,
                    _principal: Principal = Depends(require_permission("review:read"))):
    """Weekly share of decided claims that verifiers found worth following up, with rules-version changes."""
    if not 4 <= weeks <= 52:
        raise ApiError(400, "INVALID_FILTER", "weeks harus 4-52.", {})
    try:
        data = RunReviewStore(request.app.state.run_db_path).accuracy_by_week(weeks)
    except RunReviewStorageError as exc:
        raise ApiError(503, "REVIEW_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    return {"availability": "available", **data}


def _stored_run(request: Request, run_id: str) -> dict:
    try:
        run = AnalysisRunStore(request.app.state.run_db_path).get_run(run_id)
    except RunStorageError as exc:
        raise ApiError(503, "RUN_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    if run is None:
        raise ApiError(404, "RUN_NOT_FOUND", "AnalysisRun tidak ditemukan.", {})
    return run


@router.get("/{run_id}", response_model=RunDetailResponse)
def get_run(run_id: str, request: Request, view: str = "full",
            _principal: Principal = Depends(require_permission("runs:results:read"))):
    """``view=full`` (default) returns the whole stored result; ``view=summary`` omits per-case objects."""
    if view not in {"full", "summary"}:
        raise ApiError(400, "INVALID_FILTER", "view harus full atau summary.", {})
    run = _stored_run(request, run_id) if view == "full" else _stored_view(request, run_id, "summary")
    return {"availability": "available", "run": _manifest(run), "result": run["result"],
            "notice": _detail_notice(run)}


def _stored_view(request: Request, run_id: str, view: str, case_id: str | None = None) -> dict:
    try:
        run = AnalysisRunStore(request.app.state.run_db_path).get_run_view(run_id, view=view, case_id=case_id)
    except RunStorageError as exc:
        raise ApiError(503, "RUN_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    if run is None:
        raise ApiError(404, "RUN_NOT_FOUND", "AnalysisRun tidak ditemukan.", {})
    return run


@router.get("/{run_id}/calibration")
def run_calibration(run_id: str, request: Request,
                    principal: Principal = Depends(require_permission("runs:results:read"))):
    """Inputs for the threshold simulation: counts per (specific findings, AI bin) and reviewer outcomes.

    No case IDs, values or notes are returned; only counts of the two inputs of the risk rule.
    """
    try:
        inputs = AnalysisRunStore(request.app.state.run_db_path).calibration_inputs(run_id)
    except RunInputError:
        raise ApiError(404, "RUN_NOT_FOUND", "AnalysisRun tidak ditemukan.", {}) from None
    except RunStorageError as exc:
        raise ApiError(503, "RUN_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    if inputs is None:
        raise ApiError(409, "RUN_RESULT_NOT_AVAILABLE", "Run ini tidak memiliki hasil kandidat tersimpan.", {})
    counts: dict[tuple[int, int | None], int] = {}
    for key in inputs.values():
        counts[key] = counts.get(key, 0) + 1
    feedback: dict[tuple[int, int | None, str], int] = {}
    if "review:read" in principal.permissions:
        try:
            reviews = RunReviewStore(request.app.state.run_db_path).list_reviews(run_id)
        except (RunReviewNotFound, RunNotReviewable):
            reviews = []
        except RunReviewStorageError as exc:
            raise ApiError(503, "RUN_STORAGE_UNAVAILABLE", str(exc), {}) from exc
        for review in reviews:
            outcome = review.get("review_outcome")
            if outcome in ("signal_supported", "signal_not_supported") and review["case_id"] in inputs:
                key = (*inputs[review["case_id"]], outcome)
                feedback[key] = feedback.get(key, 0) + 1
    return {
        "availability": "available", "run_id": run_id, "flagged": len(inputs),
        "bins": [{"specific": specific, "ai_bin": ai_bin, "count": count} for (specific, ai_bin), count in sorted(counts.items(), key=str)],
        "feedback": [{"specific": specific, "ai_bin": ai_bin, "outcome": outcome, "count": count}
                     for (specific, ai_bin, outcome), count in sorted(feedback.items(), key=str)],
        "feedback_visible": "review:read" in principal.permissions,
    }


@router.get("/{run_id}/cases", response_model=RunCaseListResponse)
def list_run_cases(run_id: str, request: Request, offset: int = 0, limit: int = 10, sort: str = "rule_index",
                   indicator: str | None = None, search: str | None = None, review_filter: str | None = None,
                   lane: str | None = None, assigned: str | None = None,
                   principal: Principal = Depends(require_permission("runs:results:read"))):
    if not 1 <= limit <= MAX_PAGE_SIZE or offset < 0 or sort not in SORT_KEYS             or (review_filter is not None and review_filter not in _REVIEW_FILTERS)             or (lane is not None and lane not in ("red", "yellow", "green"))             or (search is not None and len(search) > 200):
        raise ApiError(400, "INVALID_FILTER", "Parameter halaman, urutan, atau filter tidak valid.", {})
    reviews = None
    if "review:read" in principal.permissions:
        try:
            reviews = {item["case_id"]: item for item in RunReviewStore(request.app.state.run_db_path).list_reviews(run_id)}
        except (RunReviewNotFound, RunNotReviewable):
            reviews = {}
        except RunReviewStorageError as exc:
            raise ApiError(503, "RUN_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    elif review_filter is not None or sort == "review_updated" or assigned is not None:
        raise ApiError(403, "PERMISSION_DENIED", "Filter atau urutan review memerlukan izin baca review.", {})
    if assigned not in (None, "me", "none"):
        raise ApiError(400, "INVALID_FILTER", "Parameter halaman, urutan, atau filter tidak valid.", {})
    scope: dict = {}
    if assigned is not None:
        try:
            taken = AssignmentStore(request.app.state.run_db_path)
            scope = ({"only_case_ids": taken.case_ids(principal.user_id)} if assigned == "me"
                     else {"except_case_ids": taken.case_ids()})
        except AssignmentStorageError as exc:
            raise ApiError(503, "RUN_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    try:
        page = AnalysisRunStore(request.app.state.run_db_path).get_case_page(
            run_id, reviews=reviews, sort=sort, offset=offset, limit=limit, indicator=indicator, search=search,
            review_filter=review_filter, lane=lane, **scope)
    except RunInputError:
        raise ApiError(404, "RUN_NOT_FOUND", "AnalysisRun tidak ditemukan.", {}) from None
    except RunStorageError as exc:
        raise ApiError(503, "RUN_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    if page is None:
        raise ApiError(409, "RUN_RESULT_NOT_AVAILABLE", "Run ini tidak memiliki hasil kandidat tersimpan.", {})
    return {"availability": "available", "run_id": run_id, **page}


@router.get("/{run_id}/cases/{case_id}", response_model=RunDetailResponse)
def get_run_case(run_id: str, case_id: str, request: Request,
                 _principal: Principal = Depends(require_permission("runs:results:read"))):
    """The stored result scoped to one claim: its case, lane, ML item and duration candidate."""
    run = _stored_view(request, run_id, "case", case_id)
    if run["result"] is None:
        raise ApiError(404, "RUN_CASE_NOT_FOUND", "Klaim tidak ada pada hasil run ini.", {})
    return {"availability": "available", "run": _manifest(run), "result": run["result"], "notice": _detail_notice(run)}


@router.post("/{run_id}/archive", status_code=204)
def archive_run(run_id: str, request: Request,
                principal: Principal = Depends(require_permission("runs:write")),
                _csrf: Principal = Depends(require_csrf)):
    """Hide a finished run from the history; its result, reviews and audit records stay intact."""
    try:
        AnalysisRunStore(request.app.state.run_db_path).archive_run(run_id, principal.user_id)
    except RunStorageError as exc:
        raise ApiError(503, "RUN_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    except RunInputError as exc:
        if str(exc) == "RUN_NOT_FOUND":
            raise ApiError(404, "RUN_NOT_FOUND", "AnalysisRun tidak ditemukan.", {}) from exc
        raise ApiError(409, "RUN_STILL_RUNNING", "Analisis yang masih berjalan tidak dapat diarsipkan.", {}) from exc
    return Response(status_code=204)


@router.delete("/{run_id}/archive", status_code=204)
def restore_run(run_id: str, request: Request,
                principal: Principal = Depends(require_permission("runs:write")),
                _csrf: Principal = Depends(require_csrf)):
    """Show an archived run in the history again."""
    try:
        AnalysisRunStore(request.app.state.run_db_path).restore_run(run_id, principal.user_id)
    except RunStorageError as exc:
        raise ApiError(503, "RUN_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    except RunInputError as exc:
        raise ApiError(404, "RUN_NOT_FOUND", "AnalysisRun tidak ditemukan.", {}) from exc
    return Response(status_code=204)
