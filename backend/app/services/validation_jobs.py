"""Background FKRTL source validation jobs (status, progress and outcome; counts only).

A validation scans the whole configured file, which takes minutes on the actual sample,
so the API starts a job and returns immediately; clients poll the job state. Jobs live in
the operational database next to the stored validations.

Coordination works across worker processes because it lives in the database:

* Claiming is one transaction under an exclusive lock (a PostgreSQL advisory lock, or
  ``BEGIN IMMEDIATE`` on SQLite): recover stale jobs, check for an active job, insert the new
  one. A unique partial index also refuses a second pending/running job, whichever worker
  asks. Only the worker that inserted a job runs it; its ``owner`` is recorded.
* The running worker renews ``heartbeat_at`` every few seconds. A job whose heartbeat is
  older than ``CIR_VALIDATION_JOB_STALE_SECONDS`` (default 120) belongs to a worker that
  stopped; it is marked failed with ``FKRTL_VALIDATION_INTERRUPTED`` (at startup, when a job
  is requested, and when the state is read). The thread itself is not durable: an
  interrupted job is never resumed, it must be requested again.
* Completion writes the report and the job status in one transaction, and only while the
  worker still owns a running job, so a job already declared interrupted is not revived.

The job records the source fingerprint taken when it was requested; its report is stored
with that fingerprint, so a file or configuration change during or after the scan makes the
validation stale for the run gate.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import socket
import threading
from typing import Any, Callable
from uuid import uuid4

from app.db import (
    VALIDATION_JOB_LOCK, DatabaseError, configured_database, connect_operational, is_postgres, write_lock,
)
from app.services.source_validations import (
    SourceValidationStorageError, ensure_sqlite_schema as ensure_validation_schema, insert_validation,
)

ACTIVE_STATUSES = ("pending", "running")
STALE_SECONDS_VARIABLE = "CIR_VALIDATION_JOB_STALE_SECONDS"
_PROGRESS_INTERVAL_ROWS = 100_000
_HEARTBEAT_SECONDS = 15.0
_threads: dict[str, threading.Thread] = {}
_WORKER = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS fkrtl_validation_jobs (
    job_id TEXT PRIMARY KEY,
    fingerprint TEXT,
    status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed')),
    requested_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    rows_scanned INTEGER NOT NULL DEFAULT 0,
    rows_total INTEGER,
    error_code TEXT,
    validation_id TEXT,
    owner TEXT,
    heartbeat_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_validation_job ON fkrtl_validation_jobs ((status IN ('pending','running')))
    WHERE status IN ('pending','running');
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def stale_after_seconds() -> float:
    try:
        return max(5.0, float(os.environ.get(STALE_SECONDS_VARIABLE, "120")))
    except ValueError:
        return 120.0


def _connect(path: str | Path):
    connection = connect_operational(path, timeout=20)
    if not is_postgres(connection):
        ensure_validation_schema(connection)  # the job writes reports in its own transaction
        connection.executescript(_SQLITE_SCHEMA)
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(fkrtl_validation_jobs)")}
        for column in ("owner", "heartbeat_at"):  # files created before job ownership
            if column not in columns:
                connection.execute(f"ALTER TABLE fkrtl_validation_jobs ADD COLUMN {column} TEXT")
        connection.commit()
    return connection


def _run_sql(path: str | Path, operation: Callable[[Any], Any]) -> Any:
    try:
        connection = _connect(path)
        try:
            with connection:
                return operation(connection)
        finally:
            connection.close()
    except (OSError, *DatabaseError) as exc:
        raise SourceValidationStorageError("Status validasi tidak dapat disimpan atau dibaca.") from exc


def _public(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in ("job_id", "status", "requested_at", "started_at", "finished_at",
                                      "rows_scanned", "rows_total", "error_code")}


def _recover_stale(connection) -> int:
    cutoff = (_now() - timedelta(seconds=stale_after_seconds())).isoformat()
    cursor = connection.execute(
        "UPDATE fkrtl_validation_jobs SET status='failed', error_code='FKRTL_VALIDATION_INTERRUPTED', finished_at=? "
        "WHERE status IN ('pending','running') AND COALESCE(heartbeat_at, requested_at) < ?",
        (_now().isoformat(), cutoff))
    return cursor.rowcount or 0


def _latest(connection):
    return connection.execute(
        "SELECT * FROM fkrtl_validation_jobs ORDER BY requested_at DESC, rowid DESC LIMIT 1").fetchone()


def latest_job(path: str | Path) -> dict[str, Any] | None:
    """Latest job; an active job whose worker stopped is first marked interrupted."""
    def read(connection):
        if connection.execute("SELECT 1 FROM fkrtl_validation_jobs WHERE status IN ('pending','running') "
                              "AND COALESCE(heartbeat_at, requested_at) < ? LIMIT 1",
                              ((_now() - timedelta(seconds=stale_after_seconds())).isoformat(),)).fetchone():
            write_lock(connection, VALIDATION_JOB_LOCK)
            _recover_stale(connection)
        return _public(_latest(connection))
    return _run_sql(path, read)


def mark_interrupted_jobs(path: str | Path) -> int:
    """Startup recovery: mark jobs whose heartbeat stopped as interrupted (live jobs of other
    workers keep running). Does nothing when the SQLite database does not exist yet."""
    if configured_database() is None and not Path(path).is_file():
        return 0

    def recover(connection):
        write_lock(connection, VALIDATION_JOB_LOCK)
        return _recover_stale(connection)
    return _run_sql(path, recover)


def start_validation_job(
    path: str | Path, fingerprint: str | None, validate: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """Claim and start a job unless one is active anywhere; returns (job, started)."""
    job_id = f"vjob_{uuid4().hex}"

    def claim(connection):
        write_lock(connection, VALIDATION_JOB_LOCK)
        _recover_stale(connection)
        active = connection.execute(
            "SELECT * FROM fkrtl_validation_jobs WHERE status IN ('pending','running') LIMIT 1").fetchone()
        if active is not None:
            return _public(active), False
        now = _now().isoformat()
        connection.execute(
            "INSERT INTO fkrtl_validation_jobs(job_id,fingerprint,status,requested_at,owner,heartbeat_at) "
            "VALUES (?,?,?,?,?,?)", (job_id, fingerprint, "pending", now, _WORKER, now))
        return None, True

    active, started = _run_sql(path, claim)
    if not started:
        return active, False
    thread = threading.Thread(target=_run, args=(path, job_id, fingerprint, validate),
                              name=f"fkrtl-validation-{job_id[-6:]}", daemon=True)
    _threads[job_id] = thread
    thread.start()
    return latest_job(path), True


def _owned_update(path: str | Path, job_id: str, sql: str, params: tuple) -> int:
    """Update a job only while this worker owns it and it is still active."""
    def update(connection):
        cursor = connection.execute(sql + " WHERE job_id=? AND owner=? AND status IN ('pending','running')",
                                    (*params, job_id, _WORKER))
        return cursor.rowcount or 0
    return _run_sql(path, update)


def _run(path: str | Path, job_id: str, fingerprint: str | None, validate: Callable[..., dict[str, Any]]) -> None:
    last_reported = [0]
    finished = threading.Event()

    def heartbeat() -> None:
        while not finished.wait(_HEARTBEAT_SECONDS):
            try:
                _heartbeat(path, job_id)
            except SourceValidationStorageError:
                pass

    def progress(rows_scanned: int, rows_total: int | None) -> None:
        if rows_scanned - last_reported[0] >= _PROGRESS_INTERVAL_ROWS or rows_scanned == rows_total:
            last_reported[0] = rows_scanned
            _owned_update(path, job_id, "UPDATE fkrtl_validation_jobs SET rows_scanned=?, rows_total=?, heartbeat_at=?",
                          (rows_scanned, rows_total, _now().isoformat()))

    beat = threading.Thread(target=heartbeat, name=f"fkrtl-validation-heartbeat-{job_id[-6:]}", daemon=True)
    try:
        now = _now().isoformat()
        if not _owned_update(path, job_id, "UPDATE fkrtl_validation_jobs SET status='running', started_at=?, heartbeat_at=?",
                             (now, now)):
            return  # no longer ours (interrupted meanwhile): do not scan
        beat.start()
        report = validate(progress=progress)

        def complete(connection):
            write_lock(connection, VALIDATION_JOB_LOCK)
            owned = connection.execute(
                "SELECT 1 FROM fkrtl_validation_jobs WHERE job_id=? AND owner=? AND status='running'",
                (job_id, _WORKER)).fetchone()
            if owned is None:
                return False  # declared interrupted meanwhile: its report is not recorded
            entry = insert_validation(connection, fingerprint, report)
            scan = report.get("scan") or {}
            connection.execute(
                "UPDATE fkrtl_validation_jobs SET status='completed', finished_at=?, validation_id=?, heartbeat_at=?, "
                "rows_scanned=COALESCE(?, rows_scanned) WHERE job_id=?",
                (_now().isoformat(), entry["validation_id"], _now().isoformat(), scan.get("rows_total"), job_id))
            return True
        _run_sql(path, complete)
    except Exception:
        # Source problems are reported inside the report; reaching here means the job itself
        # failed (storage or an unexpected error). No exception text is stored.
        try:
            _owned_update(path, job_id, "UPDATE fkrtl_validation_jobs SET status='failed', finished_at=?, "
                                "error_code='FKRTL_VALIDATION_JOB_FAILED'", (_now().isoformat(),))
        except SourceValidationStorageError:
            pass
    finally:
        finished.set()
        _threads.pop(job_id, None)


def _heartbeat(path: str | Path, job_id: str) -> None:
    def beat(connection):
        connection.execute("UPDATE fkrtl_validation_jobs SET heartbeat_at=? WHERE job_id=? AND owner=? "
                           "AND status IN ('pending','running')", (_now().isoformat(), job_id, _WORKER))
    _run_sql(path, beat)


def wait_for_validation_jobs(timeout: float = 60.0) -> None:
    """Join running job threads of this process (tests and scripts)."""
    for thread in list(_threads.values()):
        thread.join(timeout)
