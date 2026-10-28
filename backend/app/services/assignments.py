"""Light work sharing: a reviewer takes a claim so that two people do not review it at the same time.

An assignment belongs to the claim (its case reference), not to one analysis, so a claim taken today stays
with the same reviewer when it appears in tomorrow's analysis. Taking and releasing are written to the
append-only review security log. A claim taken by someone else can only be released by that person.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from app.db import DatabaseError, connect_operational, sqlite_script, write_lock

SCHEMA = """
CREATE TABLE IF NOT EXISTS case_assignments (
    case_id TEXT PRIMARY KEY,
    assignee_user_id TEXT NOT NULL,
    assigned_at TEXT NOT NULL,
    assigned_in_run_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_case_assignments_user ON case_assignments(assignee_user_id);
"""


class AssignmentStorageError(RuntimeError):
    """The operational database is unavailable."""


class AssignedToSomeoneElse(RuntimeError):
    def __init__(self, assignee_user_id: str):
        super().__init__("assigned")
        self.assignee_user_id = assignee_user_id


class AssignmentStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        from app.services.run_reviews import RunReviewStore

        with RunReviewStore(self.path)._connection():  # the review security log lives in the review schema
            pass
        connection = None
        try:
            connection = connect_operational(self.path, timeout=20)
            sqlite_script(connection, SCHEMA)
            yield connection
            connection.commit()
        except DatabaseError as exc:
            if connection is not None:
                connection.rollback()
            raise AssignmentStorageError("Penyimpanan penugasan tidak tersedia.") from exc
        finally:
            if connection is not None:
                connection.close()

    def take(self, run_id: str, case_id: str, user_id: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            write_lock(connection)
            current = connection.execute("SELECT * FROM case_assignments WHERE case_id=?", (case_id,)).fetchone()
            if current is not None and current["assignee_user_id"] != user_id:
                raise AssignedToSomeoneElse(current["assignee_user_id"])
            if current is None:
                connection.execute("INSERT INTO case_assignments VALUES (?,?,?,?)", (case_id, user_id, now, run_id))
                self._log(connection, run_id, case_id, user_id, now, "case_taken")
            row = connection.execute("SELECT * FROM case_assignments WHERE case_id=?", (case_id,)).fetchone()
        return dict(row)

    def release(self, run_id: str, case_id: str, user_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            write_lock(connection)
            current = connection.execute("SELECT * FROM case_assignments WHERE case_id=?", (case_id,)).fetchone()
            if current is None:
                return
            if current["assignee_user_id"] != user_id:
                raise AssignedToSomeoneElse(current["assignee_user_id"])
            connection.execute("DELETE FROM case_assignments WHERE case_id=?", (case_id,))
            self._log(connection, run_id, case_id, user_id, now, "case_released")

    @staticmethod
    def _log(connection: Any, run_id: str, case_id: str, user_id: str, now: str, event: str) -> None:
        connection.execute("INSERT INTO run_review_security_audit_events VALUES (?,?,?,?,?,?)",
                           (f"sec_{uuid4().hex}", run_id, case_id, user_id, now, event))

    def for_run(self, run_id: str) -> dict[str, dict[str, Any]]:
        """Assignments of the claims listed in this analysis."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT a.* FROM case_assignments a JOIN analysis_run_cases c ON c.case_id = a.case_id WHERE c.run_id=?",
                (run_id,)).fetchall()
        return {row["case_id"]: dict(row) for row in rows}

    def get(self, case_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM case_assignments WHERE case_id=?", (case_id,)).fetchone()
        return dict(row) if row is not None else None

    def case_ids(self, user_id: str | None = None) -> set[str]:
        """Claims taken by this reviewer, or by anybody when ``user_id`` is None."""
        with self._connection() as connection:
            rows = (connection.execute("SELECT case_id FROM case_assignments WHERE assignee_user_id=?", (user_id,))
                    if user_id else connection.execute("SELECT case_id FROM case_assignments"))
            return {row["case_id"] for row in rows}
