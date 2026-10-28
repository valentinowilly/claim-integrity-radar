"""A claim's clinical note and the stage 2 reading aid (language model, or the fallback reading), for uploaded example data only."""

from datetime import date

from fastapi import APIRouter, Depends, Request

from app.analytics.ml_model import code_name
from app.api.errors import ApiError
from app.data_sources.bpjs_csv import BPJS_CSV_SCHEMA_VERSION
from app.security.auth import AuthStore, Principal
from app.security.dependencies import require_csrf, require_permission
from app.security.rate_limit import user_rate_limit
from app.services import clinical_ai
from app.services.batches import BatchStorageError, BatchStore
from app.services.runs import AnalysisRunStore, RunStorageError

router = APIRouter(prefix="/api/v1/runs", tags=["clinical notes"])



def _claim(request: Request, run_id: str, case_id: str) -> tuple[dict, dict | None]:
    """The run's one-claim view and the stored record of that claim (None for the server-side sample)."""
    try:
        view = AnalysisRunStore(request.app.state.run_db_path).get_run_view(run_id, view="case", case_id=case_id)
    except RunStorageError as exc:
        raise ApiError(503, "RUN_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    if view is None:
        raise ApiError(404, "RUN_NOT_FOUND", "AnalysisRun tidak ditemukan.", {})
    if view.get("result") is None:
        raise ApiError(404, "RUN_CASE_NOT_FOUND", "Klaim tidak ada pada hasil run ini.", {})
    # Only uploaded files in the BPJS column format carry notes; the BPJS sample is never sent anywhere.
    if view["source_type"] != "synthetic_csv" or view.get("source_schema_version") != BPJS_CSV_SCHEMA_VERSION:
        return view, None
    try:
        record = BatchStore(request.app.state.batch_db_path).record_for_case(view["batch_id"], case_id)
    except BatchStorageError as exc:
        raise ApiError(503, "BATCH_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    return view, record


def _with_name(request: Request, analysis: dict | None) -> dict | None:
    """Add the requesting user's name (the stored row keeps the user id)."""
    if analysis is None:
        return None
    user_id = analysis["requested_by_user_id"]
    name = AuthStore(request.app.state.auth_db_path).usernames({user_id}).get(user_id)
    return {**analysis, "requested_by": name or "petugas"}


def _stay(record: dict) -> int | None:
    try:
        return (date.fromisoformat(record["discharge_date"]) - date.fromisoformat(record["service_date"])).days
    except (KeyError, TypeError, ValueError):
        return None


def _code_names(record: dict) -> dict:
    """Names of the claim's codes from the exported code dictionary (None when unknown or not exported)."""
    return {"admission_diagnosis_name": code_name("diagnosis", record.get("admission_diagnosis")),
            "primary_diagnosis_name": code_name("diagnosis", record.get("primary_diagnosis")),
            "claim_group_name": code_name("claim_group", record.get("claim_group"))}


def _claim_summary(record: dict) -> dict:
    """The coded facts shown beside the note, so the reviewer reads the note against the same claim."""
    return {"primary_diagnosis": record.get("primary_diagnosis"), "claim_group": record.get("claim_group"),
            "stay_days": _stay(record), **_code_names(record)}


def _claim_facts(view: dict, record: dict) -> dict:
    result = view["result"]
    case = (result.get("cases") or {}).get(record["case_id"]) or {}
    ml_items = (result.get("ml_anomaly") or {}).get("items") or []
    ml = next((item for item in ml_items if item.get("case_id") == record["case_id"]), None) or case.get("ml_anomaly") or {}
    percentile = ml.get("reference_percentile", ml.get("anomaly_percentile"))
    factors = [item.get("description") for item in (ml.get("supporting_signals") or ml.get("top_deviations") or [])
               if item.get("description")]
    return {
        **{key: record.get(key) for key in ("admission_diagnosis", "primary_diagnosis", "claim_group", "procedure_code",
                                            "care_class", "service_date", "discharge_date", "clinical_note")},
        **_code_names(record),
        "stay_days": _stay(record),
        "findings": [reason.get("summary", "") for reason in case.get("reasons") or []][:4],
        "ai_score": round(percentile * 100, 1) if isinstance(percentile, (int, float)) else None,
        "ai_factors": factors[:4],
    }


@router.get("/{run_id}/cases/{case_id}/clinical-note")
def get_clinical_note(run_id: str, case_id: str, request: Request,
                      _principal: Principal = Depends(require_permission("review:read"))):
    _view, record = _claim(request, run_id, case_id)
    note = (record or {}).get("clinical_note")
    try:
        latest = clinical_ai.ClinicalAiStore(request.app.state.run_db_path).latest(run_id, case_id) if note else None
    except clinical_ai.ClinicalAiError:
        latest = None
    return {"run_id": run_id, "case_id": case_id, "clinical_note": note,
            "source": "uploaded_example" if record is not None else "bpjs_sample",
            "ai_configured": clinical_ai.configured(), "ai_provider": clinical_ai.provider(),
            "ai_model": clinical_ai.model_name(), "fallback_model": clinical_ai.FALLBACK_MODEL,
            "claim": _claim_summary(record) if note else None,
            "analysis": _with_name(request, latest)}


@router.post("/{run_id}/cases/{case_id}/clinical-analysis")
def analyse_clinical_note(run_id: str, case_id: str, request: Request,
                          principal: Principal = Depends(require_permission("review:write")),
                          _csrf: Principal = Depends(require_csrf),
                          _limit: None = Depends(user_rate_limit("clinical_ai"))):
    view, record = _claim(request, run_id, case_id)
    if record is None:
        raise ApiError(409, "CLINICAL_AI_SAMPLE_DATA_NOT_ALLOWED",
                       "Analisis AI catatan klinis hanya untuk file contoh berformat kolom BPJS yang diunggah; "
                       "data sampel BPJS tidak pernah dikirim ke layanan AI.", {})
    if not record.get("clinical_note"):
        raise ApiError(409, "CLINICAL_NOTE_MISSING", "Klaim ini tidak memiliki catatan klinis.", {})
    # The language model when available; otherwise, or when it fails, the fallback reading (never an error).
    reading = clinical_ai.read_note(_claim_facts(view, record))
    try:
        saved = clinical_ai.ClinicalAiStore(request.app.state.run_db_path).save(
            run_id, case_id, principal.user_id, reading["model"], reading["verdict"],
            engine=reading["engine"], fallback_reason=reading["fallback_reason"])
    except clinical_ai.ClinicalAiError as exc:
        raise ApiError(503, exc.code, "Penyimpanan hasil pembacaan sedang tidak tersedia.", {}) from exc
    return {"run_id": run_id, "case_id": case_id, "analysis": _with_name(request, saved)}
