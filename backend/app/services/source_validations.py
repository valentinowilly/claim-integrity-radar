"""Persisted FKRTL source validations (aggregate reports only; no paths, rows or identifiers).

Stored in the operational database (PostgreSQL when configured, else the run/batch SQLite
file) so a validation survives an API restart; the run gate compares the stored fingerprint
with the currently configured file and settings.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.db import DatabaseError, connect_operational, is_postgres


class SourceValidationStorageError(Exception):
    """Safe failure accessing stored validations."""


def ensure_sqlite_schema(connection) -> None:
    """SQLite only (PostgreSQL has the migrated schema)."""
    if not is_postgres(connection):
        connection.execute(
            """CREATE TABLE IF NOT EXISTS fkrtl_source_validations (
                   validation_id TEXT PRIMARY KEY,
                   fingerprint TEXT,
                   validated_at TEXT NOT NULL,
                   status TEXT NOT NULL,
                   report_json TEXT NOT NULL
               )"""
        )


def _connect(path: str | Path):
    connection = connect_operational(path, timeout=20)
    ensure_sqlite_schema(connection)
    return connection


def insert_validation(connection, fingerprint: str | None, report: dict[str, Any]) -> dict[str, Any]:
    """Insert one validation in the caller's transaction."""
    entry = {"validation_id": f"val_{uuid4().hex}", "fingerprint": fingerprint,
             "validated_at": datetime.now(timezone.utc), "report": report}
    connection.execute(
        "INSERT INTO fkrtl_source_validations(validation_id,fingerprint,validated_at,status,report_json) "
        "VALUES (?,?,?,?,?)",
        (entry["validation_id"], fingerprint, entry["validated_at"].isoformat(), report["status"],
         json.dumps(report, sort_keys=True)),
    )
    return entry


def record_validation(path: str | Path, fingerprint: str | None, report: dict[str, Any]) -> dict[str, Any]:
    try:
        connection = _connect(path)
        try:
            with connection:
                entry = insert_validation(connection, fingerprint, report)
        finally:
            connection.close()
    except (OSError, *DatabaseError) as exc:
        raise SourceValidationStorageError("Hasil validasi tidak dapat disimpan.") from exc
    return entry


def latest_validation(path: str | Path) -> dict[str, Any] | None:
    try:
        connection = _connect(path)
        try:
            row = connection.execute(
                "SELECT fingerprint, validated_at, report_json FROM fkrtl_source_validations "
                "ORDER BY validated_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
            connection.commit()
        finally:
            connection.close()
    except (OSError, *DatabaseError) as exc:
        raise SourceValidationStorageError("Hasil validasi tidak dapat dibaca.") from exc
    if row is None:
        return None
    return {"fingerprint": row[0], "validated_at": datetime.fromisoformat(row[1]), "report": json.loads(row[2])}
