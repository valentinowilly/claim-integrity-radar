"""Persistent run-scoped review state, independent from immutable run results."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterator
from uuid import uuid4


INITIAL_STATUS = "pending_review"
VALID_STATUSES = {"pending_review", "in_review", "awaiting_evidence", "escalated", "closed"}
VALID_OUTCOMES = {"signal_supported", "signal_not_supported", "inconclusive"}


class RunReviewStorageError(Exception):
    """Safe failure accessing run-scoped review persistence."""


class RunReviewNotFound(Exception):
    """Run or run-scoped candidate is not available to review."""


class RunNotReviewable(Exception):
    """Run exists but has no eligible persisted result to review."""


class RunReviewStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=20)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS run_case_reviews (
                    review_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id),
                    case_id TEXT NOT NULL,
                    review_status TEXT NOT NULL CHECK(review_status IN
                        ('pending_review','in_review','awaiting_evidence','escalated','closed')),
                    review_outcome TEXT CHECK(review_outcome IS NULL OR review_outcome IN
                        ('signal_supported','signal_not_supported','inconclusive')),
                    note TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    updated_by_user_id TEXT NOT NULL,
                    UNIQUE(run_id, case_id)
                );
                CREATE TABLE IF NOT EXISTS run_case_review_events (
                    event_id TEXT PRIMARY KEY,
                    review_id TEXT NOT NULL REFERENCES run_case_reviews(review_id),
                    run_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    actor_user_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK(event_type IN
                        ('status_changed','outcome_recorded','outcome_changed')),
                    previous_status TEXT,
                    new_status TEXT,
                    previous_outcome TEXT,
                    new_outcome TEXT,
                    note TEXT
                );
                CREATE TABLE IF NOT EXISTS run_review_security_audit_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    actor_user_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    event_type TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_run_case_reviews_run_case
                    ON run_case_reviews(run_id, case_id);
                CREATE INDEX IF NOT EXISTS idx_run_case_review_events_order
                    ON run_case_review_events(review_id, occurred_at, event_id);
                CREATE TRIGGER IF NOT EXISTS run_case_review_events_no_update
                BEFORE UPDATE ON run_case_review_events
                BEGIN SELECT RAISE(ABORT, 'review history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS run_case_review_events_no_delete
                BEFORE DELETE ON run_case_review_events
                BEGIN SELECT RAISE(ABORT, 'review history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS run_review_security_events_no_update
                BEFORE UPDATE ON run_review_security_audit_events
                BEGIN SELECT RAISE(ABORT, 'security audit events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS run_review_security_events_no_delete
                BEFORE DELETE ON run_review_security_audit_events
                BEGIN SELECT RAISE(ABORT, 'security audit events are append-only'); END;
                """
            )
            yield connection
            connection.commit()
        except (OSError, sqlite3.Error) as exc:
            if connection is not None:
                connection.rollback()
            raise RunReviewStorageError("Penyimpanan review run lokal tidak tersedia.") from exc
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _assert_candidate(connection: sqlite3.Connection, run_id: str, case_id: str) -> None:
        try:
            run = connection.execute(
                "SELECT execution_status,result_available FROM analysis_runs WHERE run_id=?", (run_id,),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                raise RunReviewNotFound from exc
            raise
        if run is None:
            raise RunReviewNotFound
        if run["execution_status"] not in {"completed", "partial"} or not run["result_available"]:
            raise RunNotReviewable
        try:
            result_row = connection.execute(
                "SELECT result_json FROM analysis_run_results WHERE run_id=?", (run_id,),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                raise RunNotReviewable from exc
            raise
        if result_row is None:
            raise RunNotReviewable
        try:
            cases = json.loads(result_row["result_json"]).get("cases")
        except (TypeError, json.JSONDecodeError) as exc:
            raise RunReviewStorageError("Hasil tersimpan tidak dapat dibaca.") from exc
        if not isinstance(cases, dict):
            raise RunNotReviewable
        if case_id not in cases:
            raise RunReviewNotFound

    @staticmethod
    def _state(connection: sqlite3.Connection, run_id: str, case_id: str) -> dict:
        review = connection.execute(
            "SELECT * FROM run_case_reviews WHERE run_id=? AND case_id=?", (run_id, case_id),
        ).fetchone()
        events = []
        if review is not None:
            events = [dict(row) for row in connection.execute(
                "SELECT event_id,event_type,occurred_at,actor_user_id,previous_status,new_status,"
                "previous_outcome,new_outcome,note FROM run_case_review_events "
                "WHERE review_id=? ORDER BY rowid", (review["review_id"],),
            ).fetchall()]
        return {
            "review_id": review["review_id"] if review else None,
            "run_id": run_id,
            "case_id": case_id,
            "review_status": review["review_status"] if review else INITIAL_STATUS,
            "review_outcome": review["review_outcome"] if review else None,
            "note": review["note"] if review else None,
            "created_at": review["created_at"] if review else None,
            "updated_at": review["updated_at"] if review else None,
            "updated_by_user_id": review["updated_by_user_id"] if review else None,
            "history": events,
        }

    def get_review(self, run_id: str, case_id: str) -> dict:
        with self._connection() as connection:
            self._assert_candidate(connection, run_id, case_id)
            return self._state(connection, run_id, case_id)

    def set_status(self, run_id: str, case_id: str, status: str, note: str | None,
                   actor_user_id: str) -> dict:
        if status not in VALID_STATUSES:
            raise ValueError("Status review tidak dikenal.")
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_candidate(connection, run_id, case_id)
            current = connection.execute(
                "SELECT * FROM run_case_reviews WHERE run_id=? AND case_id=?", (run_id, case_id),
            ).fetchone()
            previous_status = current["review_status"] if current else INITIAL_STATUS
            previous_outcome = current["review_outcome"] if current else None
            review_id = current["review_id"] if current else f"rvr_{uuid4().hex}"
            if current is None:
                connection.execute(
                    "INSERT INTO run_case_reviews VALUES (?,?,?,?,NULL,?,?,?,?)",
                    (review_id, run_id, case_id, status, note, now, now, actor_user_id),
                )
            else:
                connection.execute(
                    "UPDATE run_case_reviews SET review_status=?,note=?,updated_at=?,updated_by_user_id=? "
                    "WHERE review_id=?", (status, note, now, actor_user_id, review_id),
                )
            event_id = f"rve_{uuid4().hex}"
            connection.execute(
                "INSERT INTO run_case_review_events VALUES (?,?,?,?,?,?, 'status_changed',?,?,?,?,?)",
                (event_id, review_id, run_id, case_id, actor_user_id, now,
                 previous_status, status, previous_outcome, previous_outcome, note),
            )
            connection.execute(
                "INSERT INTO run_review_security_audit_events VALUES (?,?,?,?,?,?)",
                (f"sec_{uuid4().hex}", run_id, case_id, actor_user_id, now, "run_review_status_changed"),
            )
            return self._state(connection, run_id, case_id)

    def set_outcome(self, run_id: str, case_id: str, outcome: str, note: str | None,
                    actor_user_id: str) -> dict:
        if outcome not in VALID_OUTCOMES:
            raise ValueError("Outcome review tidak dikenal.")
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_candidate(connection, run_id, case_id)
            current = connection.execute(
                "SELECT * FROM run_case_reviews WHERE run_id=? AND case_id=?", (run_id, case_id),
            ).fetchone()
            previous_status = current["review_status"] if current else INITIAL_STATUS
            previous_outcome = current["review_outcome"] if current else None
            review_id = current["review_id"] if current else f"rvr_{uuid4().hex}"
            if current is None:
                connection.execute(
                    "INSERT INTO run_case_reviews VALUES (?,?,?,?,?,?,?, ?,?)",
                    (review_id, run_id, case_id, INITIAL_STATUS, outcome, note, now, now, actor_user_id),
                )
                event_type = "outcome_recorded"
            else:
                connection.execute(
                    "UPDATE run_case_reviews SET review_outcome=?,note=?,updated_at=?,updated_by_user_id=? "
                    "WHERE review_id=?", (outcome, note, now, actor_user_id, review_id),
                )
                event_type = "outcome_recorded" if previous_outcome is None else "outcome_changed"
            connection.execute(
                "INSERT INTO run_case_review_events VALUES (?,?,?,?,?,?, ?,?,?,?,?,?)",
                (f"rve_{uuid4().hex}", review_id, run_id, case_id, actor_user_id, now, event_type,
                 previous_status, previous_status, previous_outcome, outcome, note),
            )
            connection.execute(
                "INSERT INTO run_review_security_audit_events VALUES (?,?,?,?,?,?)",
                (f"sec_{uuid4().hex}", run_id, case_id, actor_user_id, now, "run_review_outcome_changed"),
            )
            return self._state(connection, run_id, case_id)
