"""Keeping the analysis lists short. Nothing is ever deleted.

* Superseded: when the same file or FKRTL window is analysed again, the earlier analyses of it are archived.
* Active window: analyses older than ``CIR_ACTIVE_DAYS`` (default 30) are archived automatically once; an
  analysis a user restored from the archive is never archived automatically again.

Archived analyses keep their results, reviews and audit records and can be restored at any time.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any, Iterator
from uuid import uuid4

from app.db import cluster_lock, DatabaseError, connect_operational, sqlite_script

ACTIVE_DAYS_VARIABLE = "CIR_ACTIVE_DAYS"
MAINTENANCE_VARIABLE = "CIR_MAINTENANCE_SCHEDULER"
SYSTEM_USER = "system-archive"
CONTINUITY_USER = "system-continuity"
TERMINAL = ("completed", "partial", "failed")
_log = logging.getLogger("cir.retention")
_started = False

def _days(variable: str, default: int) -> int:
    try:
        value = int(os.environ.get(variable, "") or default)
    except ValueError:
        return default
    return value if value >= 1 else default


def active_days() -> int:
    return _days(ACTIVE_DAYS_VARIABLE, 30)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def _connection(db_path: str | Path) -> Iterator[Any]:
    # Opening the run and batch stores first creates their tables and guards on SQLite.
    from app.services.batches import BatchStore
    from app.services.run_reviews import RunReviewStore
    from app.services.runs import AnalysisRunStore

    for store in (BatchStore(db_path), AnalysisRunStore(db_path), RunReviewStore(db_path)):
        with store._connection():
            pass
    connection = None
    try:
        connection = connect_operational(Path(db_path), timeout=20)
        yield connection
        connection.commit()
    except DatabaseError:
        if connection is not None:
            connection.rollback()
        raise
    finally:
        if connection is not None:
            connection.close()


def _archive(connection: Any, run_id: str, actor: str, event_type: str, now: str, detail: dict[str, Any]) -> None:
    connection.execute("INSERT INTO analysis_run_archives VALUES (?, ?, ?)", (run_id, now, actor))
    connection.execute("INSERT INTO analysis_run_audit_events VALUES (?, ?, ?, ?, ?, ?)",
                       (f"evt_{uuid4().hex}", now, actor, event_type, run_id, json.dumps(detail, sort_keys=True)))


def supersede_earlier_runs(db_path: str | Path, run_id: str) -> int:
    """Archive the earlier, still listed analyses of the same file or window as ``run_id``."""
    now = utc_now().isoformat()
    with _connection(db_path) as connection:
        run = connection.execute("SELECT batch_id FROM analysis_runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None:
            return 0
        earlier = [row["run_id"] for row in connection.execute(
            "SELECT run_id FROM analysis_runs WHERE batch_id=? AND run_id<>? AND execution_status IN (?,?,?) "
            "AND run_id NOT IN (SELECT run_id FROM analysis_run_archives)", (run["batch_id"], run_id, *TERMINAL))]
        for earlier_id in earlier:
            _archive(connection, earlier_id, CONTINUITY_USER, "run_superseded", now, {"superseded_by": run_id})
    return len(earlier)


def sweep(db_path: str | Path, now: datetime | None = None) -> dict[str, int]:
    """Archive analyses older than the active window (once; restored ones stay listed)."""
    now = now or utc_now()
    stamp = now.isoformat()
    archive_before = (now - timedelta(days=active_days())).isoformat()
    with _connection(db_path) as connection:
        old = [row["run_id"] for row in connection.execute(
            "SELECT run_id FROM analysis_runs WHERE created_at < ? AND execution_status IN (?,?,?) "
            "AND run_id NOT IN (SELECT run_id FROM analysis_run_archives) "
            "AND run_id NOT IN (SELECT target_run_id FROM analysis_run_audit_events WHERE event_type='run_restored')",
            (archive_before, *TERMINAL))]
        for run_id in old:
            _archive(connection, run_id, SYSTEM_USER, "run_archived_auto", stamp, {"older_than_days": active_days()})
    return {"archived": len(old)}


def archive_reasons(db_path: str | Path, run_ids: list[str]) -> dict[str, str]:
    """Why each archived analysis was archived: by a user, superseded, or older than the active window."""
    if not run_ids:
        return {}
    labels = {"run_archived": "manual", "run_superseded": "superseded", "run_archived_auto": "older"}
    reasons: dict[str, str] = {}
    with _connection(db_path) as connection:
        for start in range(0, len(run_ids), 500):
            chunk = run_ids[start:start + 500]
            for row in connection.execute(
                    "SELECT target_run_id, event_type FROM analysis_run_audit_events WHERE event_type IN "
                    "('run_archived','run_superseded','run_archived_auto') AND target_run_id IN ("
                    + ",".join("?" * len(chunk)) + ") ORDER BY occurred_at", chunk):
                reasons[row["target_run_id"]] = labels[row["event_type"]]
    return reasons


def start_maintenance(db_path: str | Path, interval_seconds: float = 3600.0) -> bool:
    """Run the archive sweep once an hour in this process (CIR_MAINTENANCE_SCHEDULER=off disables; never under tests)."""
    global _started
    if _started or os.environ.get(MAINTENANCE_VARIABLE, "").lower() == "off" or "PYTEST_CURRENT_TEST" in os.environ:
        return False
    _started = True

    def loop() -> None:
        import time

        time.sleep(60)
        while True:
            try:
                with cluster_lock("retention-sweep") as held:  # another API process sweeps this round
                    counts = sweep(db_path) if held else {}
                if any(counts.values()):
                    _log.info("Retention sweep: %s", counts)
            except Exception:
                _log.exception("Retention sweep failed.")
            time.sleep(interval_seconds)

    threading.Thread(target=loop, name="cir-retention", daemon=True).start()
    return True
