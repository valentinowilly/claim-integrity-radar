"""Whether the reasons shown for a claim helped the verifier ("Membantu" / "Tidak membantu").

Proposal indicator 20 (user satisfaction): every reason card asks one question; the answers are counted per check
so the explanations that do not help can be rewritten. One answer per person, claim and check (a new answer
replaces the old one). Only codes are stored (helpful yes/no and an optional reason code), never free text, so no
claim content can end up here.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from app.db import DatabaseError, connect_operational, sqlite_script

REASONS = ("unclear", "not_matching", "too_long", "other")
SCHEMA = """
CREATE TABLE IF NOT EXISTS explanation_feedback (
    feedback_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    indicator TEXT NOT NULL,
    user_id TEXT NOT NULL,
    helpful INTEGER NOT NULL CHECK(helpful IN (0,1)),
    reason TEXT CHECK(reason IS NULL OR reason IN ('unclear','not_matching','too_long','other')),
    recorded_at TEXT NOT NULL,
    UNIQUE(run_id, case_id, indicator, user_id)
);
CREATE INDEX IF NOT EXISTS idx_explanation_feedback_run ON explanation_feedback(run_id);
"""


class FeedbackStorageError(RuntimeError):
    """The operational database is unavailable."""


@contextmanager
def _connection(db_path: str | Path) -> Iterator[Any]:
    connection = None
    try:
        connection = connect_operational(Path(db_path), timeout=20)
        sqlite_script(connection, SCHEMA)
        yield connection
        connection.commit()
    except DatabaseError as exc:
        if connection is not None:
            connection.rollback()
        raise FeedbackStorageError("Penilaian penjelasan tidak dapat disimpan.") from exc
    finally:
        if connection is not None:
            connection.close()


def record(db_path: str | Path, *, run_id: str, case_id: str, indicator: str, user_id: str, helpful: bool,
           reason: str | None) -> dict[str, Any]:
    if reason is not None and reason not in REASONS:
        raise ValueError("Alasan tidak dikenal.")
    if helpful:
        reason = None
    now = datetime.now(timezone.utc).isoformat()
    with _connection(db_path) as connection:
        connection.execute("DELETE FROM explanation_feedback WHERE run_id=? AND case_id=? AND indicator=? AND user_id=?",
                           (run_id, case_id, indicator, user_id))
        connection.execute("INSERT INTO explanation_feedback VALUES (?,?,?,?,?,?,?,?)",
                           (f"fb_{uuid4().hex}", run_id, case_id, indicator, user_id, int(helpful), reason, now))
    return {"indicator": indicator, "helpful": helpful, "reason": reason, "recorded_at": now}


def mine(db_path: str | Path, *, run_id: str, case_id: str, user_id: str) -> dict[str, dict[str, Any]]:
    """This person's answers on one claim, per check."""
    with _connection(db_path) as connection:
        rows = connection.execute("SELECT indicator, helpful, reason FROM explanation_feedback WHERE run_id=? AND case_id=? AND user_id=?",
                                  (run_id, case_id, user_id)).fetchall()
    return {row["indicator"]: {"helpful": bool(row["helpful"]), "reason": row["reason"]} for row in rows}


def summary(db_path: str | Path, run_id: str | None = None) -> dict[str, Any]:
    """Answers per check (all analyses, or one), with the share that helped and the reasons it did not."""
    where, params = ("WHERE run_id=?", (run_id,)) if run_id else ("", ())
    with _connection(db_path) as connection:
        rows = connection.execute(
            f"SELECT indicator, helpful, reason, COUNT(*) AS n FROM explanation_feedback {where} GROUP BY indicator, helpful, reason",
            params).fetchall()
    per: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = per.setdefault(row["indicator"], {"indicator": row["indicator"], "helpful": 0, "not_helpful": 0, "reasons": {}})
        if row["helpful"]:
            item["helpful"] += row["n"]
        else:
            item["not_helpful"] += row["n"]
            if row["reason"]:
                item["reasons"][row["reason"]] = item["reasons"].get(row["reason"], 0) + row["n"]
    items = sorted(per.values(), key=lambda item: -(item["helpful"] + item["not_helpful"]))
    helpful = sum(item["helpful"] for item in items)
    total = helpful + sum(item["not_helpful"] for item in items)
    return {"total": total, "helpful": helpful, "share_helpful": round(helpful / total, 4) if total else None, "items": items}
