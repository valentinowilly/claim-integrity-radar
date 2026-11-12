"""Claim packages from several sources (CSV, FHIR JSON, PDF), a claim's documents, and questions about them."""

from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.errors import ApiError
from app.api.routes.clinical_ai import _claim
from app.intake.pdf_reader import OCR_ENGINE_NAME
from app.security.auth import Principal
from app.security.dependencies import require_csrf, require_permission
from app.security.rate_limit import user_rate_limit
from app.services import document_qa, intake, llm, samples

router = APIRouter(prefix="/api/v1", tags=["claim intake"])
MAX_FILE_BYTES = intake.MAX_DATA_BYTES
_MESSAGES = {
    "PACKAGE_NOT_FOUND": (404, "Paket klaim tidak ditemukan."),
    "PACKAGE_NOT_OPEN": (409, "Paket ini sudah diproses; buat paket baru untuk berkas lain."),
    "PACKAGE_EMPTY": (422, "Paket belum berisi berkas."),
    "EMPTY_FILE": (422, "Berkas kosong."),
    "TOO_MANY_FILES": (413, "Jumlah berkas melewati batas satu paket."),
    "DOCUMENT_NOT_FOUND": (404, "Berkas tidak ditemukan."),
    "DOCUMENT_FILE_MISSING": (404, "Isi berkas tidak tersedia di penyimpanan."),
    "PACKAGE_BUSY": (409, "Paket sedang diproses dan tidak dapat dibatalkan sekarang. Setelah selesai, hasilnya bisa dibatalkan."),
}


class PackageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=400)


def _fail(exc: Exception) -> ApiError:
    if isinstance(exc, intake.IntakeInputError):
        status, message = _MESSAGES.get(exc.code, (422, "Permintaan tidak dapat diproses."))
        return ApiError(status, exc.code, message, {})
    return ApiError(503, "INTAKE_STORAGE_UNAVAILABLE", str(exc), {})


@router.get("/intake/status")
def intake_status(_principal: Principal = Depends(require_permission("batches:read"))):
    """What reads the documents here: the OCR engine and the language model (name only)."""
    return {"sources": ["csv", "fhir", "pdf", "zip"], "ocr_engine": OCR_ENGINE_NAME, "model": llm.describe(),
            "limits": {"max_files": intake.MAX_FILES, "max_pdf_bytes": intake.MAX_PDF_BYTES,
                       "max_data_bytes": intake.MAX_DATA_BYTES},
            "retention": intake.retention_policy()}


@router.get("/intake/samples")
def list_samples(_principal: Principal = Depends(require_permission("batches:read"))):
    """Example files to try the upload with (synthetic; the answer keys are never included)."""
    return {"items": samples.available()}


@router.get("/intake/samples/{sample_id}")
def download_sample(sample_id: str, _principal: Principal = Depends(require_permission("batches:read"))):
    try:
        content, name, media_type = samples.content(sample_id)
    except (samples.SampleUnavailable, OSError) as exc:
        raise ApiError(404, "SAMPLE_NOT_FOUND", "Contoh berkas tidak tersedia di server ini.", {}) from exc
    return Response(content=content, media_type=media_type, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}", "Cache-Control": "private, no-store"})


@router.post("/intake/packages", status_code=201)
def create_package(payload: PackageCreate, request: Request,
                   principal: Principal = Depends(require_permission("batches:write")),
                   _csrf: Principal = Depends(require_csrf)):
    try:
        return {"package": intake.create_package(request.app.state.run_db_path, principal.user_id, payload.name)}
    except (intake.IntakeInputError, intake.IntakeStorageError) as exc:
        raise _fail(exc) from exc


@router.get("/intake/packages")
def list_packages(request: Request, limit: int = 20,
                  _principal: Principal = Depends(require_permission("batches:read"))):
    try:
        return {"items": intake.list_packages(request.app.state.run_db_path, max(1, min(limit, 50)))}
    except intake.IntakeStorageError as exc:
        raise _fail(exc) from exc


@router.get("/intake/packages/{package_id}")
def get_package(package_id: str, request: Request,
                _principal: Principal = Depends(require_permission("batches:read"))):
    try:
        return {"package": intake.get_package(request.app.state.run_db_path, package_id)}
    except (intake.IntakeInputError, intake.IntakeStorageError) as exc:
        raise _fail(exc) from exc


@router.put("/intake/packages/{package_id}/files")
async def add_file(package_id: str, request: Request,
                   _principal: Principal = Depends(require_permission("batches:write")),
                   _csrf: Principal = Depends(require_csrf)):
    """One file per request as the raw body; the name travels in X-File-Name (percent-encoded)."""
    name = unquote(request.headers.get("x-file-name", "")).strip()
    if not name:
        raise ApiError(422, "INVALID_PAYLOAD", "Header X-File-Name wajib disertakan.", {})
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_FILE_BYTES:
            raise ApiError(413, "UPLOAD_TOO_LARGE", "Ukuran berkas melewati batas.", {"max_bytes": MAX_FILE_BYTES})
        content.extend(chunk)
    try:
        return {"package": intake.add_file(request.app.state.run_db_path, package_id, name, bytes(content))}
    except (intake.IntakeInputError, intake.IntakeStorageError) as exc:
        raise _fail(exc) from exc


@router.post("/intake/packages/{package_id}/process", status_code=202)
def process_package(package_id: str, request: Request,
                    principal: Principal = Depends(require_permission("batches:write")),
                    _csrf: Principal = Depends(require_csrf)):
    try:
        return {"package": intake.start_processing(request.app.state.run_db_path, package_id, principal.user_id)}
    except (intake.IntakeInputError, intake.IntakeStorageError) as exc:
        raise _fail(exc) from exc


@router.delete("/intake/packages/{package_id}")
def cancel_package(package_id: str, request: Request,
                   principal: Principal = Depends(require_permission("batches:write")),
                   _csrf: Principal = Depends(require_csrf)):
    """Cancel a package: while uploading its files are removed; once finished its analysis is archived and its
    documents are released from the claims."""
    try:
        return {"package": intake.cancel_package(request.app.state.run_db_path, package_id, principal.user_id)}
    except (intake.IntakeInputError, intake.IntakeStorageError) as exc:
        raise _fail(exc) from exc


@router.get("/runs/{run_id}/cases/{case_id}/documents")
def case_documents(run_id: str, case_id: str, request: Request,
                   _principal: Principal = Depends(require_permission("review:read"))):
    _claim(request, run_id, case_id)  # the claim must belong to this run
    try:
        items = intake.documents_for_case(request.app.state.run_db_path, case_id, run_id=run_id)
    except intake.IntakeStorageError as exc:
        raise _fail(exc) from exc
    return {"items": items, "mismatch_count": sum(len(item["mismatches"]) for item in items),
            "evidence_found": sorted({item["evidence_code"] for item in items if item["evidence_code"]}),
            "question_engine": "llm" if llm.configured() else "text_search", "model": llm.describe()["model"]}


@router.get("/runs/{run_id}/document-mismatches")
def run_document_mismatches(run_id: str, request: Request,
                            _principal: Principal = Depends(require_permission("review:read"))):
    """Claims of this run whose documents disagree with the claim data, flagged by a check or not."""
    try:
        return intake.run_mismatches(request.app.state.run_db_path, run_id)
    except intake.IntakeStorageError as exc:
        raise _fail(exc) from exc


@router.get("/documents/{document_id}/file")
def document_file(document_id: str, request: Request,
                  _principal: Principal = Depends(require_permission("review:read"))):
    try:
        content, name, _case_id = intake.document_file(request.app.state.run_db_path, document_id)
    except (intake.IntakeInputError, intake.IntakeStorageError) as exc:
        raise _fail(exc) from exc
    return Response(content=content, media_type="application/pdf", headers={
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(name)}", "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff"})


@router.post("/runs/{run_id}/cases/{case_id}/documents/ask")
def ask_documents(run_id: str, case_id: str, payload: Question, request: Request,
                  _principal: Principal = Depends(require_permission("review:write")),
                  _csrf: Principal = Depends(require_csrf),
                  _limit: None = Depends(user_rate_limit("clinical_ai"))):
    _claim(request, run_id, case_id)
    try:
        documents = intake.documents_for_case(request.app.state.run_db_path, case_id, run_id=run_id, pages=True)
    except intake.IntakeStorageError as exc:
        raise _fail(exc) from exc
    if not documents:
        raise ApiError(409, "CLAIM_HAS_NO_DOCUMENTS", "Klaim ini tidak memiliki berkas untuk ditanya.", {})
    return document_qa.answer_question(documents, payload.question.strip())
