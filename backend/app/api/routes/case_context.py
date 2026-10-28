"""Context of one claim in its uploaded file: claims with an identical clinical note, and the participant's visits.

Uploaded example data in the BPJS column format only (as the clinical note); the BPJS sample stays server-side.
Claims are named by their pseudonymous case id; no participant identity is returned.
"""

from fastapi import APIRouter, Depends, Request

from app.api.errors import ApiError
from app.api.routes.clinical_ai import _claim
from app.security.auth import Principal
from app.security.dependencies import require_permission
from app.services import claim_context
from app.services.batches import BatchStorageError
from app.services.runs import AnalysisRunStore, RunStorageError

router = APIRouter(prefix="/api/v1/runs", tags=["claim context"])
UNAVAILABLE = "Hanya tersedia untuk berkas unggahan berformat kolom data klaim BPJS."


def _with_lanes(request: Request, run_id: str, items: list[dict]) -> list[dict]:
    try:
        lanes = AnalysisRunStore(request.app.state.run_db_path).case_lanes(run_id, [item["case_id"] for item in items])
    except RunStorageError as exc:
        raise ApiError(503, "RUN_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    # Claims without a flagged row were not flagged by this analysis: low risk.
    return [{**item, "lane": lanes.get(item["case_id"], "green")} for item in items]


@router.get("/{run_id}/cases/{case_id}/note-matches")
def note_matches(run_id: str, case_id: str, request: Request,
                 _principal: Principal = Depends(require_permission("review:read"))):
    view, record = _claim(request, run_id, case_id)
    if record is None:
        return {"run_id": run_id, "case_id": case_id, "available": False, "reason": UNAVAILABLE, "total_claims": 0,
                "distinct_participants": 0, "numbers": [], "matches": [], "matches_truncated": False}
    try:
        found = claim_context.note_matches(request.app.state.batch_db_path, view["batch_id"], case_id)
    except BatchStorageError as exc:
        raise ApiError(503, "BATCH_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    return {"run_id": run_id, "case_id": case_id, "available": True, "reason": None,
            **found, "matches": _with_lanes(request, run_id, found["matches"])}


@router.get("/{run_id}/cases/{case_id}/visits")
def participant_visits(run_id: str, case_id: str, request: Request,
                       _principal: Principal = Depends(require_permission("review:read"))):
    view, record = _claim(request, run_id, case_id)
    if record is None:
        return {"run_id": run_id, "case_id": case_id, "available": False, "reason": UNAVAILABLE, "total_visits": 0, "visits": []}
    try:
        found = claim_context.participant_visits(request.app.state.batch_db_path, view["batch_id"], case_id)
    except BatchStorageError as exc:
        raise ApiError(503, "BATCH_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    return {"run_id": run_id, "case_id": case_id, "available": True, "reason": None,
            **found, "visits": _with_lanes(request, run_id, found["visits"])}
