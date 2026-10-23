"""Synthetic CSV import and DataBatch metadata API."""

from fastapi import APIRouter, Depends, Request, Response

from app.api.errors import ApiError
from app.data_sources.synthetic_csv import SYNTHETIC_CSV_MAPPING_VERSION, SYNTHETIC_CSV_SCHEMA_VERSION
from app.schemas.batches import BatchDetailResponse, BatchImportResponse, BatchListResponse
from app.security.auth import Principal
from app.security.dependencies import require_csrf, require_permission
from app.services.batches import (
    BatchStorageError, BatchStore, configured_upload_limits,
)


router = APIRouter(prefix="/api/v1/batches", tags=["synthetic data batches"])


async def _read_bounded_body(request: Request, limit: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > limit:
                raise ApiError(413, "UPLOAD_TOO_LARGE", "Ukuran CSV melewati batas konfigurasi.",
                               {"max_bytes": limit})
        except ValueError as exc:
            raise ApiError(400, "INVALID_CONTENT_LENGTH", "Header Content-Length tidak valid.", {}) from exc
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > limit:
            raise ApiError(413, "UPLOAD_TOO_LARGE", "Ukuran CSV melewati batas konfigurasi.",
                           {"max_bytes": limit})
        content.extend(chunk)
    return bytes(content)


def _store(request: Request) -> BatchStore:
    return BatchStore(request.app.state.batch_db_path)


def _validate_headers(request: Request) -> tuple[str, str, str]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "text/csv":
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "Import hanya menerima Content-Type text/csv.", {})
    batch_key = request.headers.get("x-batch-key", "")
    schema = request.headers.get("x-synthetic-schema-version", "")
    mapping = request.headers.get("x-synthetic-mapping-version", "")
    classification = request.headers.get("x-data-classification", "")
    if not batch_key or not schema or not mapping or not classification:
        raise ApiError(422, "INVALID_PAYLOAD", "Header versi dan identitas batch wajib disertakan.",
                       {"required_headers": ["X-Batch-Key", "X-Synthetic-Schema-Version",
                                             "X-Synthetic-Mapping-Version", "X-Data-Classification"]})
    if classification != "synthetic_only":
        raise ApiError(422, "SYNTHETIC_DATA_REQUIRED", "Importer hanya menerima klasifikasi synthetic_only.", {})
    return batch_key, schema, mapping


@router.post("/import", response_model=BatchImportResponse)
async def import_synthetic_csv(request: Request, response: Response,
                               principal: Principal = Depends(require_permission("batches:write")),
                               _csrf: Principal = Depends(require_csrf)):
    batch_key, schema, mapping = _validate_headers(request)
    try:
        max_bytes, max_rows = configured_upload_limits()
    except ValueError as exc:
        raise ApiError(503, "BATCH_CONFIGURATION_INVALID", "Konfigurasi batas import tidak valid.", {}) from exc
    raw = await _read_bounded_body(request, max_bytes)
    try:
        batch, reused = _store(request).import_csv(
            raw, batch_key=batch_key, creator_user_id=principal.user_id,
            schema_version=schema, mapping_version=mapping, max_rows=max_rows,
        )
    except ValueError as exc:
        raise ApiError(422, "INVALID_BATCH_METADATA", str(exc), {}) from exc
    except BatchStorageError as exc:
        raise ApiError(503, "BATCH_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    response.status_code = 200 if reused else 201
    return {
        "batch": batch, "reused_existing": reused,
        "notice": ("Batch sintetis tersimpan; bukan data BPJS." if batch["status"] != "rejected"
                   else "Upaya impor ditolak; ringkasan validasi tidak memuat nilai baris."),
    }


@router.get("", response_model=BatchListResponse)
def list_batches(request: Request, limit: int = 50, offset: int = 0,
                 _principal: Principal = Depends(require_permission("batches:read"))):
    if not 1 <= limit <= 100 or offset < 0:
        raise ApiError(400, "INVALID_FILTER", "limit harus 1-100 dan offset tidak boleh negatif.", {})
    try:
        result = _store(request).list_batches(limit, offset)
    except BatchStorageError as exc:
        raise ApiError(503, "BATCH_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    return {**result, "limit": limit, "offset": offset, "availability": "available"}


@router.get("/{batch_id}", response_model=BatchDetailResponse)
def get_batch(batch_id: str, request: Request,
              _principal: Principal = Depends(require_permission("batches:read"))):
    try:
        batch = _store(request).get_batch(batch_id)
    except BatchStorageError as exc:
        raise ApiError(503, "BATCH_STORAGE_UNAVAILABLE", str(exc), {}) from exc
    if batch is None:
        raise ApiError(404, "BATCH_NOT_FOUND", "Batch tidak ditemukan.", {})
    return {"batch": batch, "availability": "available",
            "notice": "Hanya metadata validasi yang tersedia; isi CSV tidak disajikan melalui API."}

