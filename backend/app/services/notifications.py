"""In-app notifications derived from the append-only history the stores already keep.

Nothing is written: validation jobs, run completions, review escalations, outcomes and
authorized audit results are read from their own tables and filtered by the reader's
permissions. A person is not notified of their own review actions. Items carry structured
fields only (kind, time, status, run and case references), never notes, audit references or
source values; the client composes the text.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.db import DatabaseError, connect_operational, table_exists

# The next cursor overlaps the previous window so an event committed just after a read (its
# timestamp is taken before its commit) is not missed; clients drop duplicates by id.
CURSOR_OVERLAP = timedelta(seconds=30)
# Events older than this are not reported, however old the client's cursor is.
MAX_LOOKBACK = timedelta(days=7)


class NotificationStorageError(Exception):
    """Safe failure reading notifications."""


def _cursor(since: str | None, now: datetime) -> str:
    floor = now - MAX_LOOKBACK
    if not since:
        return now.isoformat()  # no cursor yet: only what happens from now on
    parsed = datetime.fromisoformat(since)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(parsed.astimezone(timezone.utc), floor).isoformat()


def notifications_for(path: str | Path, *, user_id: str, permissions: frozenset[str], since: str | None,
                      limit: int = 20) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    cursor = _cursor(since, now)
    items: list[dict[str, Any]] = []
    try:
        connection = connect_operational(path, timeout=10)
        try:
            # For the people who start validations (operators, admins); readers cannot act on it.
            if "batches:write" in permissions and table_exists(connection, "fkrtl_validation_jobs"):
                join = table_exists(connection, "fkrtl_source_validations")
                rows = connection.execute(
                    "SELECT j.job_id, j.status, j.error_code, j.finished_at, "
                    + ("v.status AS report_status " if join else "NULL AS report_status ")
                    + "FROM fkrtl_validation_jobs j "
                    + ("LEFT JOIN fkrtl_source_validations v ON v.validation_id = j.validation_id " if join else "")
                    + "WHERE j.finished_at > ? AND j.status IN ('completed','failed') ORDER BY j.finished_at DESC LIMIT ?",
                    (cursor, limit)).fetchall()
                items += [{"id": f"validation:{row['job_id']}", "kind": "validation_finished", "occurred_at": row["finished_at"],
                           "status": row["report_status"] if row["status"] == "completed" else "job_failed",
                           "error_code": row["error_code"]} for row in rows]
            if "runs:read" in permissions and table_exists(connection, "analysis_runs"):
                rows = connection.execute(
                    "SELECT run_id, source_type, execution_status, completed_at FROM analysis_runs "
                    "WHERE completed_at > ? AND execution_status IN ('completed','partial','failed') "
                    "ORDER BY completed_at DESC LIMIT ?", (cursor, limit)).fetchall()
                items += [{"id": f"run:{row['run_id']}", "kind": "run_finished", "occurred_at": row["completed_at"],
                           "status": row["execution_status"], "source_type": row["source_type"], "run_id": row["run_id"]}
                          for row in rows]
            if "review:read" in permissions and table_exists(connection, "run_case_review_events"):
                rows = connection.execute(
                    "SELECT event_id, run_id, case_id, occurred_at, event_type, new_status, new_outcome "
                    "FROM run_case_review_events WHERE occurred_at > ? AND actor_user_id <> ? AND "
                    "((event_type = 'status_changed' AND new_status = 'escalated') "
                    "OR event_type IN ('outcome_recorded','outcome_changed')) "
                    "ORDER BY occurred_at DESC LIMIT ?", (cursor, user_id, limit)).fetchall()
                items += [{"id": f"review:{row['event_id']}",
                           "kind": "case_escalated" if row["event_type"] == "status_changed" else "outcome_recorded",
                           "occurred_at": row["occurred_at"], "status": row["new_outcome"] or row["new_status"],
                           "run_id": row["run_id"], "case_id": row["case_id"]} for row in rows]
            if "review:read" in permissions and table_exists(connection, "run_case_audit_confirmations"):
                rows = connection.execute(
                    "SELECT confirmation_id, run_id, case_id, audit_result, recorded_at FROM run_case_audit_confirmations "
                    "WHERE recorded_at > ? AND recorded_by_user_id <> ? ORDER BY recorded_at DESC LIMIT ?",
                    (cursor, user_id, limit)).fetchall()
                items += [{"id": f"audit:{row['confirmation_id']}", "kind": "audit_result_recorded",
                           "occurred_at": row["recorded_at"], "status": row["audit_result"],
                           "run_id": row["run_id"], "case_id": row["case_id"]} for row in rows]
            connection.commit()
        finally:
            connection.close()
    except (OSError, *DatabaseError) as exc:
        raise NotificationStorageError("Notifikasi tidak dapat dibaca.") from exc
    items.sort(key=lambda item: (item["occurred_at"], item["id"]), reverse=True)
    return {"items": items[:limit], "next_since": (now - CURSOR_OVERLAP).isoformat(), "server_time": now.isoformat()}
