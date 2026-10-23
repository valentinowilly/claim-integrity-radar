"""SQLite persistence for immutable, synthetic-only data batches."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator
from uuid import uuid4

from app.data_sources.synthetic_csv import (
    CsvImportError, SYNTHETIC_CSV_MAPPING_VERSION, SYNTHETIC_CSV_SCHEMA_VERSION,
    parse_synthetic_csv,
)


DEFAULT_BATCH_DB_PATH = Path(__file__).resolve().parents[2] / "outputs" / "data_batches.sqlite3"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_IMPORT_ROWS = 120_000
BATCH_KEY_RE = re.compile(r"^synthetic-[a-z0-9][a-z0-9-]{0,60}$")
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class BatchStorageError(Exception):
    """A safe local batch-storage failure."""


def configured_batch_db_path() -> Path:
    configured = os.environ.get("CIR_BATCH_DB_PATH")
    return Path(configured).expanduser() if configured else DEFAULT_BATCH_DB_PATH


def configured_upload_limits() -> tuple[int, int]:
    """Read bounded local import limits; invalid environment config fails closed."""
    try:
        max_bytes = int(os.environ.get("CIR_BATCH_MAX_BYTES", str(MAX_UPLOAD_BYTES)))
        max_rows = int(os.environ.get("CIR_BATCH_MAX_ROWS", str(MAX_IMPORT_ROWS)))
    except ValueError as exc:
        raise ValueError("Batas import batch harus berupa bilangan bulat.") from exc
    if not 1_024 <= max_bytes <= 512 * 1024 * 1024 or not 1 <= max_rows <= 1_000_000:
        raise ValueError("Batas import batch berada di luar rentang yang diizinkan.")
    return max_bytes, max_rows


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BatchStore:
    """Side-effect-free until a public store operation opens SQLite."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=10)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS data_batches (
                    batch_id TEXT PRIMARY KEY,
                    batch_key TEXT NOT NULL,
                    batch_version INTEGER NOT NULL CHECK(batch_version > 0),
                    created_at TEXT NOT NULL,
                    creator_user_id TEXT NOT NULL,
                    source_type TEXT NOT NULL CHECK(source_type = 'synthetic_csv'),
                    schema_version TEXT NOT NULL,
                    mapping_version TEXT NOT NULL,
                    content_checksum TEXT NOT NULL,
                    row_count INTEGER,
                    validation_summary_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('validating','ready','ready_with_warnings','rejected')),
                    UNIQUE(batch_key, batch_version),
                    UNIQUE(batch_key, content_checksum, schema_version, mapping_version)
                );
                CREATE TABLE IF NOT EXISTS data_batch_records (
                    batch_id TEXT NOT NULL REFERENCES data_batches(batch_id),
                    claim_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    PRIMARY KEY(batch_id, claim_id),
                    UNIQUE(batch_id, case_id)
                );
                CREATE TABLE IF NOT EXISTS batch_security_audit_events (
                    event_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    actor_user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_data_batches_created
                    ON data_batches(created_at DESC, batch_id);
                CREATE TRIGGER IF NOT EXISTS ready_batch_metadata_immutable_update
                BEFORE UPDATE ON data_batches WHEN OLD.status IN ('ready','ready_with_warnings')
                BEGIN SELECT RAISE(ABORT, 'ready batch is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS ready_batch_metadata_immutable_delete
                BEFORE DELETE ON data_batches WHEN OLD.status IN ('ready','ready_with_warnings')
                BEGIN SELECT RAISE(ABORT, 'ready batch is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS ready_batch_records_immutable_update
                BEFORE UPDATE ON data_batch_records
                WHEN (SELECT status FROM data_batches WHERE batch_id = OLD.batch_id) IN ('ready','ready_with_warnings')
                BEGIN SELECT RAISE(ABORT, 'ready batch records are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS ready_batch_records_immutable_insert
                BEFORE INSERT ON data_batch_records
                WHEN (SELECT status FROM data_batches WHERE batch_id = NEW.batch_id) IN ('ready','ready_with_warnings')
                BEGIN SELECT RAISE(ABORT, 'ready batch records are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS ready_batch_records_immutable_delete
                BEFORE DELETE ON data_batch_records
                WHEN (SELECT status FROM data_batches WHERE batch_id = OLD.batch_id) IN ('ready','ready_with_warnings')
                BEGIN SELECT RAISE(ABORT, 'ready batch records are immutable'); END;
                """
            )
            yield connection
            connection.commit()
        except (OSError, sqlite3.Error) as exc:
            if connection is not None:
                connection.rollback()
            raise BatchStorageError("Penyimpanan batch lokal tidak tersedia.") from exc
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _summary(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "batch_id": row["batch_id"], "batch_key": row["batch_key"],
            "batch_version": row["batch_version"], "created_at": row["created_at"],
            "creator_user_id": row["creator_user_id"], "source_type": row["source_type"],
            "schema_version": row["schema_version"], "mapping_version": row["mapping_version"],
            "row_count": row["row_count"], "status": row["status"],
            "validation": json.loads(row["validation_summary_json"]),
        }

    def import_csv(self, raw: bytes, *, batch_key: str, creator_user_id: str,
                   schema_version: str, mapping_version: str,
                   max_rows: int = MAX_IMPORT_ROWS) -> tuple[dict[str, Any], bool]:
        if not BATCH_KEY_RE.fullmatch(batch_key):
            raise ValueError("batch_key harus berupa label synthetic- dengan huruf kecil, angka, atau tanda hubung.")
        if not VERSION_RE.fullmatch(schema_version) or not VERSION_RE.fullmatch(mapping_version):
            raise ValueError("Versi skema atau mapping tidak memiliki format yang diizinkan.")

        checksum = hashlib.sha256(raw).hexdigest()
        fingerprint = hashlib.sha256(
            f"{batch_key}\0{checksum}\0{schema_version}\0{mapping_version}".encode("utf-8")
        ).hexdigest()
        batch_id = f"bat_{fingerprint[:32]}"
        records: list[dict[str, Any]] = []
        if schema_version != SYNTHETIC_CSV_SCHEMA_VERSION:
            summary = {
                "error_count": 1, "error_counts": {"unsupported_schema_version": 1},
                "errors": [{"code": "unsupported_schema_version"}], "errors_truncated": False,
                "row_count": None, "warning_counts": {},
            }
            status = "rejected"
        elif mapping_version != SYNTHETIC_CSV_MAPPING_VERSION:
            summary = {
                "error_count": 1, "error_counts": {"unsupported_mapping_version": 1},
                "errors": [{"code": "unsupported_mapping_version"}], "errors_truncated": False,
                "row_count": None, "warning_counts": {},
            }
            status = "rejected"
        else:
            try:
                records, summary = parse_synthetic_csv(raw, max_rows=max_rows)
                status = "ready_with_warnings" if summary["warning_counts"] else "ready"
            except CsvImportError as exc:
                summary = exc.summary
                status = "rejected"

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM data_batches WHERE batch_key=? AND content_checksum=? "
                "AND schema_version=? AND mapping_version=?",
                (batch_key, checksum, schema_version, mapping_version),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    "INSERT INTO batch_security_audit_events VALUES (?, ?, ?, 'batch_import_reused', ?, ?)",
                    (f"evt_{uuid4().hex}", utc_now(), creator_user_id, existing["batch_id"],
                     json.dumps({"status": existing["status"]}, sort_keys=True)),
                )
                return self._summary(existing), True
            version = connection.execute(
                "SELECT COALESCE(MAX(batch_version),0)+1 FROM data_batches WHERE batch_key=?",
                (batch_key,),
            ).fetchone()[0]
            created_at = utc_now()
            persisted_status = "validating" if status in {"ready", "ready_with_warnings"} else status
            connection.execute(
                "INSERT INTO data_batches VALUES (?, ?, ?, ?, ?, 'synthetic_csv', ?, ?, ?, ?, ?, ?)",
                (batch_id, batch_key, version, created_at, creator_user_id, schema_version,
                 mapping_version, checksum, summary.get("row_count"),
                 json.dumps(summary, sort_keys=True, separators=(",", ":")), persisted_status),
            )
            if status in {"ready", "ready_with_warnings"}:
                connection.executemany(
                    "INSERT INTO data_batch_records(batch_id,claim_id,case_id,record_json) VALUES (?,?,?,?)",
                    [(batch_id, row["claim_id"], row["case_id"],
                      json.dumps(row, sort_keys=True, separators=(",", ":"))) for row in records],
                )
                connection.execute("UPDATE data_batches SET status=? WHERE batch_id=?", (status, batch_id))
            event_type = "batch_imported" if status != "rejected" else "batch_import_rejected"
            connection.execute(
                "INSERT INTO batch_security_audit_events VALUES (?, ?, ?, ?, ?, ?)",
                (f"evt_{fingerprint[:24]}_{version}", created_at, creator_user_id, event_type,
                 batch_id, json.dumps({"status": status, "row_count": summary.get("row_count")}, sort_keys=True)),
            )
            row = connection.execute("SELECT * FROM data_batches WHERE batch_id=?", (batch_id,)).fetchone()
            return self._summary(row), False

    def list_batches(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        with self._connection() as connection:
            total = connection.execute("SELECT COUNT(*) FROM data_batches").fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM data_batches ORDER BY created_at DESC,batch_id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return {"items": [self._summary(row) for row in rows], "total_items": total}

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM data_batches WHERE batch_id=?", (batch_id,)).fetchone()
        return self._summary(row) if row is not None else None

    def get_record_count(self, batch_id: str) -> int:
        """Internal data-model check; no record values are exposed by the API."""
        with self._connection() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM data_batch_records WHERE batch_id=?", (batch_id,)
            ).fetchone()[0]

    def get_execution_input(self, batch_id: str) -> dict[str, Any] | None:
        """Load a ready batch and its normalized feature rows for internal execution only.

        This method is deliberately separate from the public metadata API. Callers
        must keep returned participant tokens inside the detector boundary and
        must never serialize these source rows into an API response or run result.
        """
        with self._connection() as connection:
            batch = connection.execute(
                "SELECT * FROM data_batches WHERE batch_id=?", (batch_id,)
            ).fetchone()
            if batch is None:
                return None
            records = connection.execute(
                "SELECT record_json FROM data_batch_records WHERE batch_id=? ORDER BY claim_id",
                (batch_id,),
            ).fetchall()
        metadata = self._summary(batch)
        metadata["content_checksum"] = batch["content_checksum"]
        return {"batch": metadata, "records": [json.loads(row["record_json"]) for row in records]}

