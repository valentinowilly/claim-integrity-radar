"""Persistent run-scoped review state, independent from immutable run results."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterator
from uuid import uuid4

from app.db import DatabaseError, UndefinedTable, connect_operational, is_missing_table, is_postgres, sqlite_script
from app.services.run_results import has_case_rows, is_missing, stored_case_is_listed, stored_result



INITIAL_STATUS = "pending_review"
# Actor of review records brought from an earlier analysis of the same claim.
CONTINUITY_USER = "system-continuity"
VALID_STATUSES = {"pending_review", "in_review", "awaiting_evidence", "escalated", "closed"}
VALID_OUTCOMES = {"signal_supported", "signal_not_supported", "inconclusive"}
# Results of an authorized audit, recorded separately from the reviewer's outcome.
VALID_AUDIT_RESULTS = {"confirmed_issue", "confirmed_no_issue"}


class RunReviewStorageError(Exception):
    """Safe failure accessing run-scoped review persistence."""


class RunReviewNotFound(Exception):
    """Run or run-scoped candidate is not available to review."""


class AuditConfirmationRequiresReview(Exception):
    """An authorized audit result can only follow a recorded human review of the case."""


class RunNotReviewable(Exception):
    """Run exists but has no eligible persisted result to review."""


class RunReviewStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = connect_operational(self.path, timeout=20)
            sqlite_script(connection, 
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
                CREATE TABLE IF NOT EXISTS run_case_audit_confirmations (
                    confirmation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    audit_result TEXT NOT NULL CHECK(audit_result IN ('confirmed_issue','confirmed_no_issue')),
                    audit_reference TEXT NOT NULL,
                    note TEXT,
                    recorded_at TEXT NOT NULL,
                    recorded_by_user_id TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_run_case_audit_confirmations
                    ON run_case_audit_confirmations(run_id, case_id, recorded_at);
                CREATE TRIGGER IF NOT EXISTS run_case_audit_confirmations_no_update
                BEFORE UPDATE ON run_case_audit_confirmations
                BEGIN SELECT RAISE(ABORT, 'audit confirmations are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS run_case_audit_confirmations_no_delete
                BEFORE DELETE ON run_case_audit_confirmations
                BEGIN SELECT RAISE(ABORT, 'audit confirmations are append-only'); END;
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
        except (OSError, *DatabaseError) as exc:
            if connection is not None:
                connection.rollback()
            raise RunReviewStorageError("Penyimpanan review run lokal tidak tersedia.") from exc
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _reviewable_result(connection: sqlite3.Connection, run_id: str) -> dict | None:
        """Raise unless the run is reviewable. Returns the parsed stored result only for runs
        without per-case rows (older runs); runs with rows return None and are never parsed."""
        try:
            run = connection.execute(
                "SELECT execution_status,result_available FROM analysis_runs WHERE run_id=?", (run_id,),
            ).fetchone()
        except UndefinedTable as exc:
            if is_missing_table(exc):
                raise RunReviewNotFound from exc
            raise
        if run is None:
            raise RunReviewNotFound
        if run["execution_status"] not in {"completed", "partial"} or not run["result_available"]:
            raise RunNotReviewable
        if has_case_rows(connection, run_id):
            return None
        try:
            result = stored_result(connection, run_id)
        except UndefinedTable as exc:
            if is_missing_table(exc):
                raise RunNotReviewable from exc
            raise
        except (TypeError, json.JSONDecodeError) as exc:
            raise RunReviewStorageError("Hasil tersimpan tidak dapat dibaca.") from exc
        if is_missing(result):
            raise RunNotReviewable
        try:
            cases = result.get("cases")
        except (TypeError, AttributeError, json.JSONDecodeError) as exc:
            raise RunReviewStorageError("Hasil tersimpan tidak dapat dibaca.") from exc
        if not isinstance(cases, dict):
            raise RunNotReviewable
        return result

    @classmethod
    def _assert_candidate(cls, connection: sqlite3.Connection, run_id: str, case_id: str) -> None:
        result = cls._reviewable_result(connection, run_id)
        if result is None:
            if not stored_case_is_listed(connection, run_id, case_id):
                raise RunReviewNotFound
            return
        cases = result["cases"]
        # Records in the persisted ML anomaly ranking are reviewable too; the
        # ranking is a triage aid, so review state stays run-scoped as usual.
        ml_items = (result.get("ml_anomaly") or {}).get("items") if isinstance(result.get("ml_anomaly"), dict) else None
        ml_case_ids = {item.get("case_id") for item in ml_items or [] if isinstance(item, dict)}
        # Duration-screen candidates are reviewable on their own as well.
        los = result.get("length_of_stay") if isinstance(result.get("length_of_stay"), dict) else {}
        los_case_ids = {item.get("case_id") for item in los.get("candidates") or [] if isinstance(item, dict)}
        if case_id not in cases and case_id not in ml_case_ids and case_id not in los_case_ids:
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
        confirmations = [dict(row) for row in connection.execute(
            "SELECT confirmation_id,audit_result,audit_reference,note,recorded_at,recorded_by_user_id "
            "FROM run_case_audit_confirmations WHERE run_id=? AND case_id=? ORDER BY rowid", (run_id, case_id),
        ).fetchall()]
        try:
            source = connection.execute(
                "SELECT source_type FROM analysis_runs WHERE run_id=?", (run_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            source = None  # pre-source_type schema: synthetic batches only
        return {
            "source_type": source["source_type"] if source else None,
            "review_id": review["review_id"] if review else None,
            "run_id": run_id,
            "case_id": case_id,
            "review_status": review["review_status"] if review else INITIAL_STATUS,
            "review_outcome": review["review_outcome"] if review else None,
            # The latest authorized audit result; never derived from the reviewer outcome.
            "audit_result": confirmations[-1]["audit_result"] if confirmations else None,
            "audit_confirmations": confirmations,
            "note": review["note"] if review else None,
            "created_at": review["created_at"] if review else None,
            "updated_at": review["updated_at"] if review else None,
            "updated_by_user_id": review["updated_by_user_id"] if review else None,
            "history": events,
        }

    def list_reviews(self, run_id: str) -> list[dict]:
        """Current review state of every reviewed case in one run (cases without a row are pending)."""
        with self._connection() as connection:
            self._reviewable_result(connection, run_id)
            return [dict(row) for row in connection.execute(
                "SELECT r.case_id,r.review_status,r.review_outcome,r.updated_at,"
                "(SELECT a.audit_result FROM run_case_audit_confirmations a WHERE a.run_id=r.run_id "
                "AND a.case_id=r.case_id ORDER BY a.rowid DESC LIMIT 1) AS audit_result "
                "FROM run_case_reviews r WHERE r.run_id=? ORDER BY r.case_id", (run_id,),
            ).fetchall()]

    def get_review(self, run_id: str, case_id: str) -> dict:
        with self._connection() as connection:
            self._assert_candidate(connection, run_id, case_id)
            return self._state(connection, run_id, case_id)

    def carry_over(self, run_id: str) -> int:
        """Bring the latest review of each claim from earlier analyses into a new analysis.

        The same claim (same case reference) keeps its status, decision and official audit result when it
        appears again, e.g. in the next day's file. The copies are recorded as events by ``system-continuity``
        with a note naming the date of the earlier decision; nothing in the earlier analysis changes.
        Returns the number of claims carried over.
        """
        now = datetime.now(timezone.utc).isoformat()
        carried = 0
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._reviewable_result(connection, run_id) is not None:
                return 0  # analyses stored before per-claim rows: nothing is carried
            listed = {row["case_id"] for row in connection.execute(
                "SELECT case_id FROM analysis_run_cases WHERE run_id=?", (run_id,))}
            view = connection.execute("SELECT listed_case_ids_json FROM analysis_run_result_views WHERE run_id=?",
                                      (run_id,)).fetchone()
            if view is not None:
                listed |= set(json.loads(view[0]))
            listed -= {row["case_id"] for row in connection.execute(
                "SELECT case_id FROM run_case_reviews WHERE run_id=?", (run_id,))}
            latest: dict[str, dict] = {}
            ordered = sorted(listed)
            for start in range(0, len(ordered), 500):
                chunk = ordered[start:start + 500]
                rows = connection.execute(
                    "SELECT * FROM run_case_reviews WHERE run_id<>? AND case_id IN (" + ",".join("?" * len(chunk)) + ") "
                    "ORDER BY updated_at DESC", (run_id, *chunk)).fetchall()
                for row in rows:
                    latest.setdefault(row["case_id"], dict(row))
            for case_id, source in sorted(latest.items()):
                if source["review_status"] == INITIAL_STATUS and source["review_outcome"] is None:
                    continue
                note = f"Dibawa dari analisis sebelumnya (keputusan terakhir {source['updated_at'][:10]})."
                review_id = f"rvr_{uuid4().hex}"
                connection.execute("INSERT INTO run_case_reviews VALUES (?,?,?,?,?,?,?,?,?)",
                                   (review_id, run_id, case_id, source["review_status"], source["review_outcome"], note,
                                    now, now, CONTINUITY_USER))
                connection.execute(
                    "INSERT INTO run_case_review_events VALUES (?,?,?,?,?,?, 'status_changed',?,?,?,?,?)",
                    (f"rve_{uuid4().hex}", review_id, run_id, case_id, CONTINUITY_USER, now,
                     INITIAL_STATUS, source["review_status"], None, None, note))
                if source["review_outcome"] is not None:
                    connection.execute(
                        "INSERT INTO run_case_review_events VALUES (?,?,?,?,?,?, 'outcome_recorded',?,?,?,?,?)",
                        (f"rve_{uuid4().hex}", review_id, run_id, case_id, CONTINUITY_USER, now,
                         source["review_status"], source["review_status"], None, source["review_outcome"], note))
                audit = connection.execute(
                    "SELECT * FROM run_case_audit_confirmations WHERE run_id=? AND case_id=? ORDER BY recorded_at DESC LIMIT 1",
                    (source["run_id"], case_id)).fetchone()
                if audit is not None:
                    connection.execute(
                        "INSERT INTO run_case_audit_confirmations VALUES (?,?,?,?,?,?,?,?)",
                        (f"rac_{uuid4().hex}", run_id, case_id, audit["audit_result"], audit["audit_reference"],
                         f"Dibawa dari analisis sebelumnya; dicatat oleh {audit['recorded_by_user_id']} pada "
                         f"{audit['recorded_at'][:10]}." + (f" {audit['note']}" if audit["note"] else ""),
                         now, CONTINUITY_USER))
                connection.execute("INSERT INTO run_review_security_audit_events VALUES (?,?,?,?,?,?)",
                                   (f"sec_{uuid4().hex}", run_id, case_id, CONTINUITY_USER, now, "run_review_carried_over"))
                carried += 1
        return carried

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

    def record_audit_confirmation(self, run_id: str, case_id: str, audit_result: str, audit_reference: str,
                                  note: str | None, actor_user_id: str) -> dict:
        """Append the result of an authorized audit (reference required); the review state is unchanged."""
        if audit_result not in VALID_AUDIT_RESULTS:
            raise ValueError("Hasil audit tidak dikenal.")
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_candidate(connection, run_id, case_id)
            if connection.execute(
                "SELECT 1 FROM run_case_reviews WHERE run_id=? AND case_id=?", (run_id, case_id),
            ).fetchone() is None:
                raise AuditConfirmationRequiresReview
            connection.execute(
                "INSERT INTO run_case_audit_confirmations VALUES (?,?,?,?,?,?,?,?)",
                (f"aud_{uuid4().hex}", run_id, case_id, audit_result, audit_reference, note, now, actor_user_id),
            )
            connection.execute(
                "INSERT INTO run_review_security_audit_events VALUES (?,?,?,?,?,?)",
                (f"sec_{uuid4().hex}", run_id, case_id, actor_user_id, now, "run_audit_confirmation_recorded"),
            )
            return self._state(connection, run_id, case_id)
