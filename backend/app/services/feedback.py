"""User feedback: whether the explanation of a claim helped, and questions or suggestions from the help page.

This is how the system measures the satisfaction of its own users (verifiers, audit leads, data operators).
One vote per person per claim: voting again replaces the earlier vote. Messages are free text written by staff,
limited in length and never mixed with claim data; the form asks users not to write participant data.
The role is stored with each entry so the summary can be read per role without joining the account store.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from app.db import DatabaseError, connect_operational, sqlite_script, write_lock

CONTEXTS = ("claim_explanation", "help_question", "general")
MAX_MESSAGE_LENGTH = 500
RECENT_LIMIT = 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_feedback (
    feedback_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    context TEXT NOT NULL CHECK(context IN ('claim_explanation','help_question','general')),
    run_id TEXT,
    case_id TEXT,
    helpful INTEGER CHECK(helpful IS NULL OR helpful IN (0, 1)),
    message TEXT
);
CREATE INDEX IF NOT EXISTS idx_user_feedback_created ON user_feedback(created_at);
CREATE INDEX IF NOT EXISTS idx_user_feedback_claim ON user_feedback(user_id, run_id, case_id);
"""


class FeedbackStorageError(RuntimeError):
    """The operational database is unavailable."""


def clean_message(value: str | None) -> str | None:
    """Trimmed message, or None when empty. Length is checked by the API schema."""
    if value is None:
        return None
    text = " ".join(value.split())
    return text or None


class FeedbackStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        connection = None
        try:
            connection = connect_operational(self.path, timeout=20)
            sqlite_script(connection, SCHEMA)
            yield connection
            connection.commit()
        except DatabaseError as exc:
            if connection is not None:
                connection.rollback()
            raise FeedbackStorageError("Penyimpanan masukan pengguna tidak tersedia.") from exc
        finally:
            if connection is not None:
                connection.close()

    def vote_on_claim(self, run_id: str, case_id: str, user_id: str, role: str, helpful: bool,
                      message: str | None) -> dict[str, Any]:
        """Record (or replace) this person's vote on the explanation of one claim."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            write_lock(connection)
            current = connection.execute(
                "SELECT feedback_id FROM user_feedback WHERE context='claim_explanation' AND user_id=? AND run_id=? AND case_id=?",
                (user_id, run_id, case_id)).fetchone()
            if current is None:
                feedback_id = f"fb_{uuid4().hex}"
                connection.execute("INSERT INTO user_feedback VALUES (?,?,?,?,?,?,?,?,?,?)",
                                   (feedback_id, now, now, user_id, role, "claim_explanation", run_id, case_id,
                                    int(helpful), message))
            else:
                feedback_id = current["feedback_id"]
                connection.execute("UPDATE user_feedback SET updated_at=?, role=?, helpful=?, message=? WHERE feedback_id=?",
                                   (now, role, int(helpful), message, feedback_id))
            row = connection.execute("SELECT * FROM user_feedback WHERE feedback_id=?", (feedback_id,)).fetchone()
        return _public(dict(row))

    def claim_vote(self, run_id: str, case_id: str, user_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM user_feedback WHERE context='claim_explanation' AND user_id=? AND run_id=? AND case_id=?",
                (user_id, run_id, case_id)).fetchone()
        return _public(dict(row)) if row is not None else None

    def add_message(self, context: str, user_id: str, role: str, message: str) -> dict[str, Any]:
        """A question or suggestion from the help page (not tied to a claim)."""
        if context not in ("help_question", "general"):
            raise ValueError("context")
        now = datetime.now(timezone.utc).isoformat()
        feedback_id = f"fb_{uuid4().hex}"
        with self._connection() as connection:
            connection.execute("INSERT INTO user_feedback VALUES (?,?,?,?,?,?,?,?,?,?)",
                               (feedback_id, now, now, user_id, role, context, None, None, None, message))
            row = connection.execute("SELECT * FROM user_feedback WHERE feedback_id=?", (feedback_id,)).fetchone()
        return _public(dict(row))

    def summary(self, days: int = 30, now: datetime | None = None) -> dict[str, Any]:
        """Satisfaction over the last ``days`` days: votes, share helpful, per role, and the latest messages."""
        now = now or datetime.now(timezone.utc)
        since = (now - timedelta(days=days)).isoformat()
        with self._connection() as connection:
            rows = [dict(row) for row in connection.execute(
                "SELECT * FROM user_feedback WHERE updated_at >= ? ORDER BY updated_at DESC, feedback_id DESC", (since,))]
        votes = [row for row in rows if row["context"] == "claim_explanation" and row["helpful"] is not None]
        helpful = sum(1 for row in votes if row["helpful"])
        by_role: dict[str, dict[str, int]] = {}
        for row in votes:
            entry = by_role.setdefault(row["role"], {"votes": 0, "helpful": 0})
            entry["votes"] += 1
            entry["helpful"] += int(bool(row["helpful"]))
        messages = [row for row in rows if row["message"]]
        return {
            "period_days": days,
            "since": since,
            "votes": len(votes),
            "helpful": helpful,
            "not_helpful": len(votes) - helpful,
            "helpful_share": helpful / len(votes) if votes else None,
            "people": len({row["user_id"] for row in rows}),
            "questions": sum(1 for row in rows if row["context"] == "help_question"),
            "suggestions": sum(1 for row in rows if row["context"] == "general"),
            "by_role": [{"role": role, **counts} for role, counts in sorted(by_role.items())],
            "recent_messages": [_public(row) for row in messages[:RECENT_LIMIT]],
        }


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "feedback_id": row["feedback_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "user_id": row["user_id"],
        "role": row["role"],
        "context": row["context"],
        "run_id": row["run_id"],
        "case_id": row["case_id"],
        "helpful": None if row["helpful"] is None else bool(row["helpful"]),
        "message": row["message"],
    }
