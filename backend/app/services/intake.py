"""Claim packages from several sources: E-Klaim CSV, RME/SATUSEHAT FHIR JSON and facility PDF documents.

A package is a set of files received together. Processing (in the background, with visible progress):

1. claim data is read from the CSV and FHIR files into canonical rows (the BPJS column format);
2. every PDF is read (text layer or OCR), typed, and its facts extracted with page citations;
3. documents are linked to their claim by visit number; their facts fill what the claim data lacks (clinical
   note, supporting-evidence inventory, ...) and are cross-checked against what the data already says. A claim
   that exists only as documents is built from them;
4. the combined rows go through the same validated import as any upload and are analysed.

The claim data wins a disagreement with a document; the disagreement is recorded for the verifier, never silently
resolved. When the same claim arrives both as CSV (E-Klaim) and as FHIR (RME), the FHIR row is used and the columns
on which they differ are recorded. A file that is not claim data (an unknown file, a JSON that is not a FHIR Bundle,
a FHIR Bundle without visits) is listed with its reason and the rest of the package goes on.

Packages are processed one at a time (others wait in a queue with their position). A package can be cancelled
while it is being uploaded, and a finished one can be cancelled too: its analysis is archived and its documents are
released from the claims. Packages left in "uploading" for a day are cleaned up.
Documents are stored on disk under ``CIR_DOCUMENT_DIR`` (named by content hash) with their page texts, facts and
checks in the operational database, keyed by the pseudonymous case reference.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import re
import threading
import time
import zipfile
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from app.data_sources.bpjs_csv import (
    BPJS_CSV_MAPPING_VERSION, BPJS_CSV_SCHEMA_VERSION, NOTE_COLUMN, OPERATIONAL_COLUMNS, SECONDARY_COLUMN,
    UPLOAD_PSEUDONYM_SECRET, is_bpjs_csv,
)
from app.data_sources.bpjs_fkrtl_adapter import FKRTL_SOURCE_COLUMNS, pseudonymous_case_id
from app.db import DatabaseError, connect_operational, is_postgres, sqlite_script
from app.intake import documents as docs
from app.intake.fhir import FhirReadError, bundle_to_rows
from app.intake.pdf_reader import PdfReadError, read_pdf
from app.services import llm

_log = logging.getLogger("cir.intake")
DOCUMENT_DIR_VARIABLE = "CIR_DOCUMENT_DIR"
MAX_FILES = 3000
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_DATA_BYTES = 200 * 1024 * 1024
MAX_PACKAGE_BYTES = 1024 * 1024 * 1024
MAX_LISTED = 200
ABANDONED_AFTER_HOURS = 24
# One package is processed at a time: OCR and the analysis use every core, and two at once only slow both down.
_WORKER = threading.Lock()
_QUEUE: list[str] = []
_QUEUE_LOCK = threading.Lock()
CANONICAL_COLUMNS = [*FKRTL_SOURCE_COLUMNS[:16], *FKRTL_SOURCE_COLUMNS[17:], "FKL47", SECONDARY_COLUMN, NOTE_COLUMN,
                     *OPERATIONAL_COLUMNS]
REQUIRED_EVIDENCE = {"physiotherapy": "clinical_note;therapy_session_log", "special_drug": "prescription;dispensing_record",
                     "special_device": "device_order;delivery_record"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS intake_packages (
    package_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    creator_user_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('uploading','processing','ready','failed','cancelled')),
    stage TEXT,
    progress_done INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    file_count INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT,
    batch_id TEXT,
    run_id TEXT,
    message_code TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_intake_packages_created ON intake_packages(created_at DESC);
CREATE TABLE IF NOT EXISTS claim_documents (
    document_id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL,
    case_id TEXT,
    file_name TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    page_count INTEGER NOT NULL,
    scanned_pages INTEGER NOT NULL,
    ocr_confidence REAL,
    doc_type TEXT NOT NULL,
    reader TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('linked','unlinked','unreadable')),
    facts_json TEXT NOT NULL,
    pages_json TEXT NOT NULL,
    checks_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claim_documents_case ON claim_documents(case_id);
CREATE INDEX IF NOT EXISTS idx_claim_documents_package ON claim_documents(package_id);
"""


class IntakeStorageError(RuntimeError):
    """The operational database or the document folder is unavailable."""


class IntakeInputError(ValueError):
    def __init__(self, code: str, detail: dict[str, Any] | None = None):
        super().__init__(code)
        self.code = code
        self.detail = detail or {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def document_directory(db_path: str | Path) -> Path:
    configured = os.environ.get(DOCUMENT_DIR_VARIABLE, "").strip()
    return Path(configured).expanduser() if configured else Path(db_path).expanduser().parent / "documents"


@contextmanager
def _connection(db_path: str | Path) -> Iterator[Any]:
    connection = None
    try:
        connection = connect_operational(Path(db_path), timeout=20)
        sqlite_script(connection, SCHEMA)
        _upgrade_sqlite(connection)
        yield connection
        connection.commit()
    except DatabaseError as exc:
        if connection is not None:
            connection.rollback()
        raise IntakeStorageError("Penyimpanan paket klaim tidak tersedia.") from exc
    finally:
        if connection is not None:
            connection.close()


def _upgrade_sqlite(connection: Any) -> None:
    """A SQLite file made before packages could be cancelled gets the wider status check (PostgreSQL: 0012)."""
    if is_postgres(connection):
        return
    row = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='intake_packages'").fetchone()
    if row is None or "'cancelled'" in row[0]:
        return
    connection.executescript(
        "ALTER TABLE intake_packages RENAME TO intake_packages_old;"
        + SCHEMA.split("CREATE TABLE IF NOT EXISTS claim_documents")[0]
        + "INSERT INTO intake_packages SELECT * FROM intake_packages_old; DROP TABLE intake_packages_old;"
        "CREATE INDEX IF NOT EXISTS idx_intake_packages_created ON intake_packages(created_at DESC);")


def _queue_position(package_id: str) -> int | None:
    with _QUEUE_LOCK:
        return _QUEUE.index(package_id) + 1 if package_id in _QUEUE else None


def _package(row: Any) -> dict[str, Any]:
    return {"package_id": row["package_id"], "name": row["name"], "created_at": row["created_at"], "status": row["status"],
            "queue_position": _queue_position(row["package_id"]) if row["status"] == "processing" else None,
            "stage": row["stage"], "progress_done": row["progress_done"], "progress_total": row["progress_total"],
            "file_count": row["file_count"], "summary": json.loads(row["summary_json"]) if row["summary_json"] else None,
            "batch_id": row["batch_id"], "run_id": row["run_id"], "message_code": row["message_code"],
            "finished_at": row["finished_at"]}


def _staging(db_path: str | Path, package_id: str) -> Path:
    return document_directory(db_path) / "_staging" / package_id


# ---- package lifecycle
def create_package(db_path: str | Path, user_id: str, name: str) -> dict[str, Any]:
    name = re.sub(r"\s+", " ", name).strip()[:80] or "Paket klaim"
    cleanup_abandoned(db_path)
    package_id = f"pkg_{uuid4().hex}"
    try:
        _staging(db_path, package_id).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise IntakeStorageError("Folder berkas tidak dapat dibuat.") from exc
    with _connection(db_path) as connection:
        connection.execute("INSERT INTO intake_packages(package_id,name,created_at,creator_user_id,status) VALUES (?,?,?,?,'uploading')",
                           (package_id, name, _now(), user_id))
    return get_package(db_path, package_id)


def get_package(db_path: str | Path, package_id: str) -> dict[str, Any]:
    with _connection(db_path) as connection:
        row = connection.execute("SELECT * FROM intake_packages WHERE package_id=?", (package_id,)).fetchone()
    if row is None:
        raise IntakeInputError("PACKAGE_NOT_FOUND")
    return _package(row)


def list_packages(db_path: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    with _connection(db_path) as connection:
        rows = connection.execute("SELECT * FROM intake_packages ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_package(row) for row in rows]


def add_file(db_path: str | Path, package_id: str, file_name: str, raw: bytes) -> dict[str, Any]:
    package = get_package(db_path, package_id)
    if package["status"] != "uploading":
        raise IntakeInputError("PACKAGE_NOT_OPEN")
    if not raw:
        raise IntakeInputError("EMPTY_FILE")
    if package["file_count"] >= MAX_FILES:
        raise IntakeInputError("TOO_MANY_FILES")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(file_name).name)[-120:] or "berkas"
    folder = _staging(db_path, package_id)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{package['file_count']:05d}__{safe}").write_bytes(raw)
    except OSError as exc:
        raise IntakeStorageError("Berkas tidak dapat disimpan.") from exc
    with _connection(db_path) as connection:
        connection.execute("UPDATE intake_packages SET file_count=file_count+1 WHERE package_id=?", (package_id,))
    return get_package(db_path, package_id)


def _update(db_path: str | Path, package_id: str, **values: Any) -> None:
    columns = ", ".join(f"{key}=?" for key in values)
    with _connection(db_path) as connection:
        connection.execute(f"UPDATE intake_packages SET {columns} WHERE package_id=?", (*values.values(), package_id))


def start_processing(db_path: str | Path, package_id: str, user_id: str, *, background: bool = True) -> dict[str, Any]:
    package = get_package(db_path, package_id)
    if package["status"] != "uploading":
        raise IntakeInputError("PACKAGE_NOT_OPEN")
    if not package["file_count"]:
        raise IntakeInputError("PACKAGE_EMPTY")
    with _QUEUE_LOCK:
        _QUEUE.append(package_id)
    _update(db_path, package_id, status="processing", stage="Menunggu giliran" if _WORKER.locked() else "Menyiapkan berkas")
    if background:
        threading.Thread(target=_run, args=(db_path, package_id, user_id), name=f"intake-{package_id[-6:]}", daemon=True).start()
    else:
        _run(db_path, package_id, user_id)
    return get_package(db_path, package_id)


def mark_interrupted_packages(db_path: str | Path) -> None:
    """At startup: a package whose worker stopped with the process cannot finish; say so instead of 'processing'.
    Does nothing when the SQLite database does not exist yet (startup never creates it)."""
    from app.db import configured_database

    if configured_database() is None and not Path(db_path).is_file():
        return
    try:
        with _connection(db_path) as connection:
            connection.execute("UPDATE intake_packages SET status='failed', message_code='PROCESS_INTERRUPTED', finished_at=? "
                               "WHERE status='processing'", (_now(),))
        cleanup_abandoned(db_path)
    except IntakeStorageError:
        _log.warning("Intake packages could not be checked at startup.")


def _run(db_path: str | Path, package_id: str, user_id: str) -> None:
    with _WORKER:
        with _QUEUE_LOCK:
            if package_id in _QUEUE:
                _QUEUE.remove(package_id)
        _run_now(db_path, package_id, user_id)


def _run_now(db_path: str | Path, package_id: str, user_id: str) -> None:
    try:
        _update(db_path, package_id, stage="Menyiapkan berkas")
        summary, batch_id, run_id = _process(db_path, package_id, user_id)
        _update(db_path, package_id, status="ready", stage="Selesai", summary_json=json.dumps(summary, ensure_ascii=False),
                batch_id=batch_id, run_id=run_id, finished_at=_now())
    except IntakeInputError as exc:
        # What went wrong and with which file, so the message can name it (never file contents).
        _update(db_path, package_id, status="failed", message_code=exc.code, finished_at=_now(),
                summary_json=json.dumps({"failure": exc.detail}, ensure_ascii=False) if exc.detail else None)
    except Exception as exc:  # never leave a package "processing"; the type only, no content
        _log.exception("Intake package failed (%s).", type(exc).__name__)
        try:
            _update(db_path, package_id, status="failed", message_code="PROCESS_FAILED", finished_at=_now())
        except IntakeStorageError:
            pass
    finally:
        _remove_staging(db_path, package_id)


def _remove_staging(db_path: str | Path, package_id: str) -> None:
    folder = _staging(db_path, package_id)
    for path in folder.glob("*") if folder.is_dir() else []:
        try:
            path.unlink()
        except OSError:
            pass
    try:
        folder.rmdir()
    except OSError:
        pass


def cancel_package(db_path: str | Path, package_id: str, user_id: str) -> dict[str, Any]:
    """Cancel a package. While uploading: its staged files are removed. When finished: its analysis is archived
    and its documents are released from the claims. A package being processed cannot be cancelled (it is short);
    its result can be cancelled once it is ready."""
    package = get_package(db_path, package_id)
    if package["status"] == "processing":
        raise IntakeInputError("PACKAGE_BUSY")
    if package["status"] == "cancelled":
        return package
    if package["run_id"]:
        from app.services.runs import AnalysisRunStore, RunInputError

        try:
            AnalysisRunStore(db_path).archive_run(package["run_id"], user_id)
        except RunInputError:
            pass  # the analysis is gone already; the documents are still released below
    with _connection(db_path) as connection:
        connection.execute("UPDATE claim_documents SET status='unlinked' WHERE package_id=? AND status='linked'", (package_id,))
        connection.execute("UPDATE intake_packages SET status='cancelled', stage=NULL, message_code='CANCELLED', finished_at=? "
                           "WHERE package_id=?", (_now(), package_id))
    _remove_staging(db_path, package_id)
    return get_package(db_path, package_id)


def cleanup_abandoned(db_path: str | Path, max_age_hours: float = ABANDONED_AFTER_HOURS) -> int:
    """Packages left in "uploading" longer than ``max_age_hours`` (a closed tab, an expired session) are cancelled
    and their staged files removed. Returns how many were cleaned up."""
    cutoff = datetime.now(timezone.utc).timestamp() - max_age_hours * 3600
    with _connection(db_path) as connection:
        rows = connection.execute("SELECT package_id, created_at FROM intake_packages WHERE status='uploading'").fetchall()
        stale = [row["package_id"] for row in rows if datetime.fromisoformat(row["created_at"]).timestamp() < cutoff]
        for package_id in stale:
            connection.execute("UPDATE intake_packages SET status='cancelled', message_code='ABANDONED', finished_at=? "
                               "WHERE package_id=?", (_now(), package_id))
    for package_id in stale:
        _remove_staging(db_path, package_id)
    return len(stale)


# ---- processing
def _expand(folder: Path) -> list[tuple[str, bytes]]:
    """Staged files in upload order, ZIP archives expanded one level (names only, never extracted to disk)."""
    files: list[tuple[str, bytes]] = []
    total = 0
    for path in sorted(folder.glob("*")):
        name = path.name.split("__", 1)[-1]
        raw = path.read_bytes()
        if raw[:4] == b"PK\x03\x04":
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    for info in archive.infolist():
                        if info.is_dir() or info.file_size > MAX_DATA_BYTES:
                            continue
                        total += info.file_size
                        if total > MAX_PACKAGE_BYTES or len(files) >= MAX_FILES:
                            raise IntakeInputError("PACKAGE_TOO_LARGE")
                        files.append((Path(info.filename).name, archive.read(info)))
            except zipfile.BadZipFile:
                files.append((name, b""))
            continue
        total += len(raw)
        if total > MAX_PACKAGE_BYTES or len(files) >= MAX_FILES:
            raise IntakeInputError("PACKAGE_TOO_LARGE")
        files.append((name, raw))
    return files


def _kind(name: str, raw: bytes) -> str:
    if raw.startswith(b"%PDF"):
        return "pdf"
    head = raw[:2048].lstrip(b"\xef\xbb\xbf \r\n\t")
    if head.startswith(b"{") and b'"resourceType"' in raw[:4096]:
        return "fhir"
    if is_bpjs_csv(raw):
        return "csv"
    return "unknown"


def _ignored_reason(name: str, raw: bytes) -> str:
    """Why a file is not used, in terms of what the user sent."""
    suffix = Path(name).suffix.lower()
    head = raw[:2048].lstrip(b"\xef\xbb\xbf \r\n\t")
    if not raw:
        return "EMPTY_FILE"
    if suffix == ".pdf":
        return "NOT_A_PDF"
    if suffix == ".json" or head[:1] in (b"{", b"["):
        return "JSON_NOT_FHIR"
    if suffix == ".csv":
        return "CSV_NOT_CLAIM_DATA"
    if suffix == ".zip":
        return "ZIP_UNREADABLE"
    return "UNSUPPORTED_FILE"


def _csv_rows(raw: bytes) -> tuple[list[dict[str, str]], list[str]]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IntakeInputError("CSV_INVALID_ENCODING") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = [header.strip() for header in (reader.fieldnames or [])]
    rows = []
    for raw_row in reader:
        rows.append({str(key).strip(): value.strip() for key, value in raw_row.items() if key and isinstance(value, str) and value.strip()})
    return rows, headers


def _same_value(column: str, data: str, document: str) -> bool:
    if column == NOTE_COLUMN:
        return SequenceMatcher(None, docs._plain(data), docs._plain(document), autojunk=False).ratio() >= 0.9
    if column == SECONDARY_COLUMN:
        split = lambda value: {code.replace(".", "").upper() for code in re.split(r"[;|,\s]+", value) if code}  # noqa: E731
        return split(data) == split(document)
    if column == "FKL47":
        try:
            return int(float(data)) == int(float(document))
        except ValueError:
            return False
    return docs._plain(data).replace(" ", "").replace(".", "") == docs._plain(document).replace(" ", "").replace(".", "")


def _process(db_path: str | Path, package_id: str, user_id: str) -> tuple[dict[str, Any], str, str]:
    from app.services.batches import BatchStorageError, BatchStore, configured_upload_limits
    from app.services.runs import RunExecutionError, RunInputError, RunStorageError, create_analysis_run

    started = time.monotonic()
    package = get_package(db_path, package_id)
    files = _expand(_staging(db_path, package_id))
    fingerprint = hashlib.sha256("".join(sorted(hashlib.sha256(raw).hexdigest() for _name, raw in files)).encode()).hexdigest()
    earlier = _same_content(db_path, package_id, fingerprint)
    kinds = [(name, raw, _kind(name, raw)) for name, raw in files]
    file_counts = Counter(kind for _name, _raw, kind in kinds)
    pdfs = [(name, raw) for name, raw, kind in kinds if kind == "pdf"]
    _update(db_path, package_id, stage="Membaca data klaim", progress_done=0, progress_total=len(pdfs))

    # 1. claim data
    rows: dict[tuple[str, str], dict[str, str]] = {}
    source: dict[tuple[str, str], str] = {}
    origin: dict[tuple[str, str], str] = {}  # the file each claim row came from, to name it in a message
    seen_columns: set[str] = set()
    duplicates = 0
    source_conflicts: list[dict[str, Any]] = []
    conflict_count = 0
    ignored = [{"file_name": name, "reason": _ignored_reason(name, raw)} for name, raw, kind in kinds if kind == "unknown"]
    # CSV first, then FHIR: the electronic medical record replaces the E-Klaim row of the same claim.
    for name, raw, kind in sorted(kinds, key=lambda item: item[2] == "fhir"):
        if kind == "csv":
            try:
                parsed, headers = _csv_rows(raw)
            except IntakeInputError as exc:
                ignored.append({"file_name": name, "reason": exc.code})
                continue
            seen_columns.update(headers)
        elif kind == "fhir":
            try:
                parsed, _summary = bundle_to_rows(raw)
            except FhirReadError as exc:
                ignored.append({"file_name": name, "reason": exc.code})
                continue
            if not parsed:
                ignored.append({"file_name": name, "reason": "FHIR_NO_ENCOUNTERS"})
                continue
            # FHIR carries diagnoses and documents as resources: the columns exist even when a claim has none.
            seen_columns.update({SECONDARY_COLUMN, NOTE_COLUMN, "BUKTI_TERCATAT"})
        else:
            continue
        for row in parsed:
            key = (row.get("PSTV01", ""), row.get("FKL02", ""))
            if not all(key):
                key = (f"?{len(rows)}", f"?{len(rows)}")  # kept so the validated import reports the missing value
            if key in rows:
                duplicates += 1
                if kind == "fhir" and source[key] == "csv":
                    differing = sorted(column for column in set(row) & set(rows[key])
                                       if row[column] and rows[key][column] and not _same_value(column, rows[key][column], row[column]))
                    if differing:
                        conflict_count += 1
                        if len(source_conflicts) < MAX_LISTED:
                            source_conflicts.append({"case_id": pseudonymous_case_id(key[0], key[1], secret=UPLOAD_PSEUDONYM_SECRET),
                                                     "columns": differing[:12], "csv_file": origin[key], "fhir_file": name})
                    rows[key] = {**rows[key], **row}  # FHIR values win; CSV-only columns are kept
                    source[key], origin[key] = "fhir", name
                continue
            rows[key] = row
            source[key] = kind
            origin[key] = name
    by_visit = {key[1]: key for key in rows}

    # 2. documents
    model_used = llm.configured()
    read: list[dict[str, Any]] = []
    ocr_seconds = 0.0
    confidences: list[float] = []
    for index, (name, raw) in enumerate(pdfs, start=1):
        _update(db_path, package_id, stage="Membaca berkas PDF", progress_done=index - 1)
        item: dict[str, Any] = {"file_name": name, "raw": raw, "sha256": hashlib.sha256(raw).hexdigest()}
        if len(raw) > MAX_PDF_BYTES:
            item.update(status="unreadable", reason="PDF_TOO_LARGE")
        else:
            try:
                reading = read_pdf(raw)
                result = docs.read_document(reading)
                item.update(reading=reading, result=result)
                if reading.scanned_pages:
                    ocr_seconds += reading.seconds
                    confidences += [page.confidence for page in reading.pages if page.confidence is not None]
            except PdfReadError as exc:
                item.update(status="unreadable", reason=exc.code)
        read.append(item)
    _update(db_path, package_id, stage="Mencocokkan berkas dengan klaim", progress_done=len(pdfs))

    # 3. link, enrich, cross-check
    by_claim: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in read:
        if "result" not in item:
            continue
        result = item["result"]
        visit, participant = result.value("nomor_kunjungan"), result.value("nomor_peserta")
        key = by_visit.get(visit or "") or ((participant, visit) if participant and visit else None)
        if key is None:
            item.update(status="unlinked", reason="NO_VISIT_NUMBER" if result.doc_type != "lainnya" else "NOT_A_CLAIM_DOCUMENT")
            continue
        if participant and key[0] != participant:
            # The visit number matches a claim of another participant: never attach a document to the wrong person.
            item.update(status="unlinked", reason="PARTICIPANT_MISMATCH")
            continue
        item["key"] = key
        by_claim.setdefault(key, []).append(item)

    mismatches: list[dict[str, Any]] = []
    filled = Counter()
    pdf_only = 0
    for key, items in by_claim.items():
        row = rows.get(key)
        if row is None:  # the claim exists only as documents
            # A claim is built from documents only when at least two of them state the same identity: one misread
            # page must not create a claim that does not exist.
            agreeing = [item for item in items if item["result"].value("nomor_peserta") == key[0]
                        and item["result"].value("nomor_kunjungan") == key[1]]
            if len(agreeing) < 2:
                for item in items:
                    item.update(status="unlinked", reason="SINGLE_DOCUMENT_CLAIM")
                continue
            row = {"PSTV01": key[0], "FKL02": key[1]}
            rows[key] = row
            source[key] = "pdf"
            origin[key] = items[0]["file_name"]
            pdf_only += 1
        case_id = pseudonymous_case_id(key[0], key[1], secret=UPLOAD_PSEUDONYM_SECRET)
        evidence = {code for code in re.split(r"[;|,]+", row.get("BUKTI_TERCATAT", "")) if code and code != "-"}
        for item in items:
            item.update(status="linked", case_id=case_id, checks=[])
            result = item["result"]
            code = docs.DOC_TYPES.get(result.doc_type, {}).get("evidence")
            if code:
                evidence.add(code)
            for fact in result.facts:
                column = docs.FIELDS.get(fact.field, {}).get("column")
                if not column or not fact.verified or column in ("PSTV01", "FKL02"):
                    continue
                current = row.get(column)
                if not current:
                    row[column] = fact.value
                    seen_columns.add(column)
                    filled[column] += 1
                elif not _same_value(column, current, fact.value):
                    check = {"field": fact.field, "label": docs.FIELDS[fact.field]["label"], "column": column,
                             "data_value": current[:120], "document_value": fact.value[:120], "page": fact.page}
                    item["checks"].append(check)
                    mismatches.append({**check, "case_id": case_id, "file_name": item["file_name"]})
        if row.get("JENIS_LAYANAN") in REQUIRED_EVIDENCE:
            row["BUKTI_TERCATAT"] = ";".join(sorted(evidence)) or "-"
            seen_columns.add("BUKTI_TERCATAT")
        if source[key] == "pdf" and not row.get("FKL03"):
            for item in items:
                item.update(status="unlinked", reason="CLAIM_DATA_INCOMPLETE", case_id=None)
            del rows[key], source[key]
            pdf_only -= 1
    for row in rows.values():  # what the service type requires, when the source did not say
        service = row.get("JENIS_LAYANAN")
        if service in REQUIRED_EVIDENCE:
            row.setdefault("BUKTI_WAJIB", REQUIRED_EVIDENCE[service])
            if row.get("BUKTI_TERCATAT"):
                row.setdefault("STATUS_BUKTI", "tercatat")
            seen_columns.update({"BUKTI_WAJIB", "STATUS_BUKTI"} if row.get("STATUS_BUKTI") else {"BUKTI_WAJIB"})
    if not rows:
        raise IntakeInputError("NO_CLAIM_DATA", {"ignored_files": ignored[:MAX_LISTED]})

    # 4. one validated import, then the analysis
    _update(db_path, package_id, stage="Memvalidasi dan menyimpan klaim")
    header = [column for column in CANONICAL_COLUMNS if column in seen_columns or column in ("PSTV01", "FKL02", "FKL03")]
    header += sorted(seen_columns - set(header) - {""})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=header, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows.values())
    combined = buffer.getvalue().encode("utf-8")
    _max_bytes, max_rows = configured_upload_limits()
    slug = re.sub(r"[^a-z0-9]+", "-", package["name"].lower()).strip("-")[:50] or "paket-klaim"
    try:
        batch, _reused = BatchStore(db_path).import_csv(combined, batch_key=f"synthetic-{slug}", creator_user_id=user_id,
                                                       schema_version=BPJS_CSV_SCHEMA_VERSION,
                                                       mapping_version=BPJS_CSV_MAPPING_VERSION, max_rows=max_rows)
    except (ValueError, BatchStorageError) as exc:
        raise IntakeInputError("BATCH_IMPORT_FAILED") from exc
    if batch["status"] == "rejected":
        validation = batch.get("validation") or {}
        codes = sorted(validation.get("error_counts") or {"rejected": 1})
        # Name the files behind the rejected rows (row 2 is the first claim of the combined file).
        keys = list(rows)
        files = sorted({origin.get(keys[error["row"] - 2], "") for error in validation.get("errors") or []
                        if isinstance(error.get("row"), int) and 0 <= error["row"] - 2 < len(keys)} - {""})
        raise IntakeInputError(f"CLAIM_DATA_REJECTED:{codes[0]}", {"code": codes[0], "files": files[:20],
                                                                    "error_count": validation.get("error_count")})
    _save_documents(db_path, package_id, read)
    _update(db_path, package_id, stage="Menganalisis klaim", batch_id=batch["batch_id"])
    try:
        run = create_analysis_run(db_path, batch["batch_id"], user_id)
    except (RunInputError, RunStorageError, RunExecutionError) as exc:
        raise IntakeInputError("ANALYSIS_RUN_FAILED") from exc

    linked = [item for item in read if item.get("status") == "linked"]
    sources = Counter(source.values())
    summary = {
        "fingerprint": fingerprint,
        "same_as": earlier,
        "files": {"csv": file_counts["csv"], "fhir": file_counts["fhir"], "pdf": file_counts["pdf"], "ignored": len(ignored)},
        "ignored_files": ignored[:MAX_LISTED],
        "source_conflicts": {"count": conflict_count, "items": source_conflicts},
        "claims": {"total": len(rows), "from_csv": sources["csv"], "from_fhir": sources["fhir"], "from_pdf_only": sources["pdf"],
                   "duplicates_across_sources": duplicates},
        "documents": {
            "total": len(read), "linked": len(linked),
            "unlinked": sum(item.get("status") == "unlinked" for item in read),
            "unreadable": sum(item.get("status") == "unreadable" for item in read),
            "scanned": sum(bool(item["reading"].scanned_pages) for item in read if "reading" in item),
            "pages": sum(len(item["reading"].pages) for item in read if "reading" in item),
            "by_type": dict(Counter(item["result"].doc_type for item in read if "result" in item).most_common()),
            "ocr_seconds": round(ocr_seconds, 1),
            "ocr_confidence": round(sum(confidences) / len(confidences), 4) if confidences else None,
            "low_confidence": sum(bool(item["result"].warnings) for item in read if "result" in item),
        },
        "enrichment": {"claims_with_documents": len({item["case_id"] for item in linked}),
                       "notes_from_documents": filled[NOTE_COLUMN], "fields_filled": sum(filled.values()),
                       "filled_by_column": dict(filled.most_common())},
        "mismatch_count": len(mismatches), "mismatches": mismatches[:MAX_LISTED],
        "problem_files": [{"file_name": item["file_name"], "status": item["status"], "reason": item.get("reason")}
                          for item in read if item.get("status") in ("unlinked", "unreadable")][:MAX_LISTED],
        "reader": {"ocr_engine": next((item["reading"].ocr_engine for item in read if "reading" in item and item["reading"].ocr_engine), None),
                   "model": llm.describe() if model_used else None,
                   "model_errors": sum(bool(item["result"].llm_error) for item in read if "result" in item)},
        "seconds": round(time.monotonic() - started, 1),
    }
    return summary, batch["batch_id"], run["run_id"]


def _same_content(db_path: str | Path, package_id: str, fingerprint: str) -> dict[str, Any] | None:
    """An earlier finished package with exactly the same files, so the user is told it was analysed before."""
    with _connection(db_path) as connection:
        rows = connection.execute("SELECT package_id, name, finished_at, summary_json FROM intake_packages "
                                  "WHERE status='ready' AND package_id<>? ORDER BY created_at DESC", (package_id,)).fetchall()
    for row in rows:
        if row["summary_json"] and json.loads(row["summary_json"]).get("fingerprint") == fingerprint:
            return {"package_id": row["package_id"], "name": row["name"], "finished_at": row["finished_at"]}
    return None


def _save_documents(db_path: str | Path, package_id: str, read: list[dict[str, Any]]) -> None:
    directory = document_directory(db_path)
    now = _now()
    with _connection(db_path) as connection:
        for item in read:
            reading, result = item.get("reading"), item.get("result")
            if item.get("status") != "unreadable":
                try:
                    target = directory / item["sha256"][:2] / f"{item['sha256']}.pdf"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        target.write_bytes(item["raw"])
                except OSError as exc:
                    raise IntakeStorageError("Berkas tidak dapat disimpan.") from exc
            confidences = [page.confidence for page in reading.pages if page.confidence is not None] if reading else []
            checks = {"mismatches": item.get("checks", []), "warnings": result.warnings if result else [],
                      "reason": item.get("reason"), "model": result.llm if result else None,
                      "model_error": result.llm_error if result else None}
            connection.execute(
                "INSERT INTO claim_documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"doc_{uuid4().hex}", package_id, item.get("case_id"), item["file_name"][:200], item["sha256"], len(item["raw"]),
                 len(reading.pages) if reading else 0, reading.scanned_pages if reading else 0,
                 round(sum(confidences) / len(confidences), 4) if confidences else None,
                 result.doc_type if result else "lainnya", result.reader if result else "-", item.get("status", "unlinked"),
                 json.dumps([fact.to_dict() for fact in result.facts] if result else [], ensure_ascii=False),
                 json.dumps([{"number": page.number, "method": page.method, "confidence": page.confidence, "text": page.text}
                             for page in reading.pages] if reading else [], ensure_ascii=False),
                 json.dumps(checks, ensure_ascii=False), now))


# ---- reading documents back
def _document(row: Any, *, pages: bool = False) -> dict[str, Any]:
    spec = docs.DOC_TYPES.get(row["doc_type"], docs.DOC_TYPES["lainnya"])
    checks = json.loads(row["checks_json"])
    facts = [{**fact, "label": docs.FIELDS.get(fact["field"], {}).get("label", fact["field"])} for fact in json.loads(row["facts_json"])]
    item = {"document_id": row["document_id"], "file_name": row["file_name"], "doc_type": row["doc_type"], "doc_type_label": spec["label"],
            "evidence_code": spec["evidence"], "page_count": row["page_count"], "scanned_pages": row["scanned_pages"],
            "ocr_confidence": row["ocr_confidence"], "reader": row["reader"], "status": row["status"], "size_bytes": row["size_bytes"],
            "facts": facts, "mismatches": checks.get("mismatches", []), "warnings": checks.get("warnings", []),
            "model": (checks.get("model") or {}).get("model")}
    if pages:
        item["pages"] = json.loads(row["pages_json"])
    return item


def documents_for_case(db_path: str | Path, case_id: str, *, run_id: str, pages: bool = False) -> list[dict[str, Any]]:
    """The claim's documents from the package behind this analysis (never another package's), one per file."""
    from app.db import configured_database

    if configured_database() is None and not Path(db_path).is_file():
        return []
    with _connection(db_path) as connection:
        rows = connection.execute(
            "SELECT d.* FROM claim_documents d JOIN intake_packages p ON p.package_id = d.package_id "
            "WHERE d.case_id=? AND d.status='linked' AND p.run_id=? ORDER BY d.created_at DESC",
            (case_id, run_id)).fetchall()
    seen: set[str] = set()
    items = []
    for row in rows:
        if row["sha256"] in seen:
            continue
        seen.add(row["sha256"])
        items.append(_document(row, pages=pages))
    order = list(docs.DOC_TYPES)
    return sorted(items, key=lambda item: (order.index(item["doc_type"]) if item["doc_type"] in order else 99, item["file_name"]))


def document_file(db_path: str | Path, document_id: str) -> tuple[bytes, str, str | None]:
    """Content, file name and case reference of a stored document."""
    with _connection(db_path) as connection:
        row = connection.execute("SELECT sha256, file_name, case_id FROM claim_documents WHERE document_id=?", (document_id,)).fetchone()
    if row is None:
        raise IntakeInputError("DOCUMENT_NOT_FOUND")
    path = document_directory(db_path) / row["sha256"][:2] / f"{row['sha256']}.pdf"
    try:
        return path.read_bytes(), row["file_name"], row["case_id"]
    except OSError as exc:
        raise IntakeInputError("DOCUMENT_FILE_MISSING") from exc


def document_counts(db_path: str | Path, case_ids: list[str], *, run_id: str) -> dict[str, dict[str, int]]:
    """Per claim: how many documents and how many disagreements with the claim data (for list badges)."""
    if not case_ids:
        return {}
    from app.db import configured_database

    if configured_database() is None and not Path(db_path).is_file():
        return {}
    marks = ",".join("?" for _ in case_ids)
    with _connection(db_path) as connection:
        rows = connection.execute(
            f"SELECT d.case_id, d.sha256, d.checks_json FROM claim_documents d JOIN intake_packages p ON p.package_id = d.package_id "
            f"WHERE d.status='linked' AND p.run_id=? AND d.case_id IN ({marks})", (run_id, *case_ids)).fetchall()
    out: dict[str, dict[str, int]] = {}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if (row["case_id"], row["sha256"]) in seen:
            continue
        seen.add((row["case_id"], row["sha256"]))
        entry = out.setdefault(row["case_id"], {"documents": 0, "mismatches": 0})
        entry["documents"] += 1
        entry["mismatches"] += len(json.loads(row["checks_json"]).get("mismatches", []))
    return out


def run_mismatches(db_path: str | Path, run_id: str, limit: int = MAX_LISTED) -> dict[str, Any]:
    """Documents of the package behind this run whose values differ from the claim data, grouped by claim.

    A mismatch is a data-integrity matter, not a risk finding: it does not change a claim's lane, and it is listed
    for every claim of the run, including claims no check flagged (which never enter the review queue).
    """
    from app.db import configured_database

    if configured_database() is None and not Path(db_path).is_file():
        return {"claims": [], "claim_count": 0, "mismatch_count": 0}
    with _connection(db_path) as connection:
        rows = connection.execute(
            "SELECT d.case_id, d.sha256, d.file_name, d.doc_type, d.document_id, d.checks_json FROM claim_documents d "
            "JOIN intake_packages p ON p.package_id = d.package_id "
            "WHERE p.run_id=? AND d.status='linked' ORDER BY d.case_id, d.file_name", (run_id,)).fetchall()
    claims: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if (row["case_id"], row["sha256"]) in seen:
            continue
        seen.add((row["case_id"], row["sha256"]))
        for check in json.loads(row["checks_json"]).get("mismatches", []):
            claims.setdefault(row["case_id"], []).append({
                **check, "document_id": row["document_id"], "file_name": row["file_name"],
                "doc_type_label": docs.DOC_TYPES.get(row["doc_type"], docs.DOC_TYPES["lainnya"])["label"]})
    items = [{"case_id": case_id, "mismatches": found} for case_id, found in sorted(claims.items())]
    return {"claims": items[:limit], "claim_count": len(items), "mismatch_count": sum(len(item["mismatches"]) for item in items)}
