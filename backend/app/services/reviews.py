"""Local, minimized persistence for auditor review workflow metadata."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4


DEFAULT_REVIEW_DB_PATH = Path(__file__).resolve().parents[2] / "outputs" / "review_workflow.sqlite3"
INITIAL_STATUS = "pending_review"
STATUS_LABELS = {
    "pending_review": "Menunggu Tinjauan",
    "needs_more_evidence": "Perlu Bukti Tambahan",
    "not_substantiated": "Selesai — indikasi tidak cukup setelah peninjauan",
    "escalated": "Dieskalasikan",
}


class ReviewStorageError(Exception):
    """Raised when local review state cannot be read or persisted."""


def configured_review_db_path() -> Path:
    configured = os.environ.get("CIR_REVIEW_DB_PATH")
    return Path(configured).expanduser() if configured else DEFAULT_REVIEW_DB_PATH


class ReviewStore:
    """SQLite store; construction is side-effect free and opens no database."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=5)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS review_cases (
                    case_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    note TEXT,
                    reviewer_label TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL REFERENCES review_cases(case_id),
                    changed_at TEXT NOT NULL,
                    previous_status TEXT,
                    status TEXT NOT NULL,
                    note TEXT,
                    reviewer_label TEXT NOT NULL,
                    actor_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_review_history_case_id_id
                    ON review_history(case_id, id);
                CREATE TABLE IF NOT EXISTS security_audit_events (
                    event_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    actor_user_id TEXT,
                    event_type TEXT NOT NULL,
                    target_type TEXT,
                    target_id TEXT,
                    metadata_json TEXT NOT NULL
                );
                """
            )
            history_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(review_history)").fetchall()
            }
            if "actor_id" not in history_columns:
                connection.execute("ALTER TABLE review_history ADD COLUMN actor_id TEXT")
            yield connection
            connection.commit()
        except (OSError, sqlite3.Error) as exc:
            if connection is not None:
                connection.rollback()
            raise ReviewStorageError("Penyimpanan tinjauan lokal tidak tersedia.") from exc
        finally:
            if connection is not None:
                connection.close()

    def get_review(self, case_id: str) -> dict:
        with self._connection() as connection:
            current = connection.execute(
                "SELECT status, note, reviewer_label, updated_at "
                "FROM review_cases WHERE case_id = ?",
                (case_id,),
            ).fetchone()
            history_rows = connection.execute(
                "SELECT changed_at, previous_status, status, note, reviewer_label, actor_id "
                "FROM review_history WHERE case_id = ? ORDER BY id",
                (case_id,),
            ).fetchall()

        if current is None:
            return {
                "status": INITIAL_STATUS,
                "note": None,
                "reviewer_label": None,
                "updated_at": None,
                "history": [],
            }
        return {
            "status": current["status"],
            "note": current["note"],
            "reviewer_label": current["reviewer_label"],
            "updated_at": current["updated_at"],
            "history": [dict(row) for row in history_rows],
        }

    def get_statuses(self, case_ids: list[str]) -> dict[str, str]:
        if not case_ids:
            return {}
        placeholders = ",".join("?" for _ in case_ids)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT case_id, status FROM review_cases WHERE case_id IN ({placeholders})",
                tuple(case_ids),
            ).fetchall()
        stored = {row["case_id"]: row["status"] for row in rows}
        return {case_id: stored.get(case_id, INITIAL_STATUS) for case_id in case_ids}

    def update_review(self, case_id: str, status: str, note: str | None,
                      actor_id: str, reviewer_label: str) -> dict:
        changed_at = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM review_cases WHERE case_id = ?", (case_id,)
            ).fetchone()
            previous_status = row["status"] if row else INITIAL_STATUS
            if row is None:
                connection.execute(
                    "INSERT INTO review_cases "
                    "(case_id, status, note, reviewer_label, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (case_id, status, note, reviewer_label, changed_at),
                )
            else:
                connection.execute(
                    "UPDATE review_cases SET status = ?, note = ?, reviewer_label = ?, "
                    "updated_at = ? WHERE case_id = ?",
                    (status, note, reviewer_label, changed_at, case_id),
                )
            connection.execute(
                "INSERT INTO review_history "
                "(case_id, changed_at, previous_status, status, note, reviewer_label, actor_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (case_id, changed_at, previous_status, status, note, reviewer_label, actor_id),
            )
            connection.execute(
                "INSERT INTO security_audit_events VALUES (?, ?, ?, 'review_updated', 'case', ?, ?)",
                (f"evt_{uuid4().hex}", changed_at, actor_id, case_id,
                 json.dumps({"status": status}, sort_keys=True)),
            )
        return self.get_review(case_id)
