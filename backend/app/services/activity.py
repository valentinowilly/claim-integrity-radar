"""Activity history for administrators: who did what, and when, across the append-only security logs.

The events are already written by each part of the system (sign-in, data intake, analyses, reviews); this
module only reads and merges them. It returns the event type, the time, the actor and the kind and reference
of the object acted on. Event details (metadata) are left out: they are not needed to answer "who did what"
and may hold more than a reader of this page should see. Nothing here writes or changes the logs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.db import DatabaseError, connect_operational, table_exists
from app.security.auth import AuthStore

MAX_LIMIT = 500
SYSTEM_ACTORS = {
    "system-inbox": "Pengambilan otomatis",
    "system-archive": "Pengarsipan otomatis",
    "system-continuity": "Sistem (lanjutan tinjauan)",
}
# Category of every known event; unknown events fall into "lainnya" so a new event never disappears.
CATEGORIES: dict[str, str] = {
    "admin_bootstrap_completed": "akun", "login_failed": "akun", "login_succeeded": "akun",
    "logout_session_revoked": "akun", "session_expired": "akun", "session_revoked_inactive_account": "akun",
    "user_created": "akun", "user_updated": "akun",
    "batch_imported": "data", "batch_import_rejected": "data", "batch_import_reused": "data",
    "local_source_registered": "data", "local_source_reused": "data",
    "batch_removed_from_list": "data", "batch_restored_to_list": "data",
    "analysis_run_created": "analisis", "analysis_run_retry_created": "analisis", "analysis_run_completed": "analisis",
    "analysis_run_partial": "analisis", "analysis_run_failed": "analisis", "run_archived": "analisis",
    "run_restored": "analisis", "run_superseded": "analisis", "run_archived_auto": "analisis",
    "review_updated": "tinjauan", "run_review_status_changed": "tinjauan", "run_review_outcome_changed": "tinjauan",
    "run_audit_confirmation_recorded": "tinjauan", "run_review_carried_over": "tinjauan",
    "case_taken": "tinjauan", "case_released": "tinjauan",
}
CATEGORY_NAMES = ("akun", "data", "analisis", "tinjauan", "lainnya")


class ActivityStorageError(RuntimeError):
    """A log store is unavailable."""


def _run_events(run_db_path: Path, limit: int) -> list[dict[str, Any]]:
    queries = (
        ("batch_security_audit_events",
         "SELECT event_id, occurred_at, actor_user_id, event_type, 'data_file' AS target_type, target_id "
         "FROM batch_security_audit_events ORDER BY occurred_at DESC, event_id DESC LIMIT ?"),
        ("analysis_run_audit_events",
         "SELECT event_id, occurred_at, actor_user_id, event_type, 'analysis' AS target_type, target_run_id AS target_id "
         "FROM analysis_run_audit_events ORDER BY occurred_at DESC, event_id DESC LIMIT ?"),
        ("run_review_security_audit_events",
         "SELECT event_id, occurred_at, actor_user_id, event_type, 'claim' AS target_type, case_id AS target_id "
         "FROM run_review_security_audit_events ORDER BY occurred_at DESC, event_id DESC LIMIT ?"),
    )
    connection = None
    try:
        connection = connect_operational(run_db_path, timeout=20)
        rows: list[dict[str, Any]] = []
        for table, sql in queries:
            if table_exists(connection, table):
                rows += [dict(row) for row in connection.execute(sql, (limit,)).fetchall()]
        return rows
    except DatabaseError as exc:
        raise ActivityStorageError("Riwayat aktivitas tidak dapat dibaca.") from exc
    finally:
        if connection is not None:
            connection.close()


def recent_activity(auth_store: AuthStore, run_db_path: str | Path, limit: int = 200,
                    category: str | None = None) -> dict[str, Any]:
    """The latest ``limit`` events of every log, newest first, optionally of one category."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    # Each source is cut to ``limit`` before merging, so the merged newest ``limit`` are complete.
    auth_rows = [{key: row[key] for key in ("event_id", "occurred_at", "actor_user_id", "event_type", "target_type", "target_id")}
                 for row in auth_store.list_audit_events(limit=limit)]
    rows = auth_rows + _run_events(Path(run_db_path), limit)
    for row in rows:
        row["category"] = CATEGORIES.get(row["event_type"], "lainnya")
    rows.sort(key=lambda row: (row["occurred_at"], row["event_id"]), reverse=True)
    # Counts describe the latest ``limit`` events of every category, so the filter chips stay comparable.
    counts = {name: sum(1 for row in rows[:limit] if row["category"] == name) for name in CATEGORY_NAMES}
    if category:
        rows = [row for row in rows if row["category"] == category]
    rows = rows[:limit]
    people = {row["actor_user_id"] for row in rows if row["actor_user_id"] and row["actor_user_id"] not in SYSTEM_ACTORS}
    names = auth_store.usernames(people)
    items = []
    for row in rows:
        actor = row["actor_user_id"]
        if actor in SYSTEM_ACTORS:
            actor_name, actor_kind = SYSTEM_ACTORS[actor], "system"
        elif actor:
            actor_name, actor_kind = names.get(actor, "akun dihapus"), "user"
        else:
            actor_name, actor_kind = "tidak dikenal", "unknown"
        items.append({
            "event_id": row["event_id"], "occurred_at": row["occurred_at"], "event_type": row["event_type"],
            "category": row["category"], "actor_name": actor_name, "actor_kind": actor_kind,
            "target_type": row["target_type"], "target_id": row["target_id"],
        })
    return {"items": items, "limit": limit, "category": category, "counts": counts}
