"""Automatic intake: claim files dropped in a server folder are checked and analysed on a daily schedule.

The claim system (or an operator) exports the day's claims as CSV into ``CIR_INBOX_DIR``. Every
``CIR_INBOX_DAILY_AT`` (local server time, default 06:00), or when a user asks for it, each new file goes
through exactly the same path as an upload: the importer (example data only, FKL48 refused), then an
analysis run. Processed files move to ``selesai/`` or ``gagal/`` inside the folder.

Each file is recorded once by its content checksum (a unique key), so a file is never processed twice,
even by two server processes. The folder path stays on the server: the API shows only the folder name.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, time, timedelta
import hashlib
import logging
import os
from pathlib import Path
import re
import threading
from typing import Any, Iterator
from uuid import uuid4

from app.db import cluster_lock, DatabaseError, connect_operational, sqlite_script
from app.data_sources.bpjs_csv import BPJS_CSV_MAPPING_VERSION, BPJS_CSV_SCHEMA_VERSION, is_bpjs_csv
from app.data_sources.synthetic_csv import SYNTHETIC_CSV_MAPPING_VERSION, SYNTHETIC_CSV_SCHEMA_VERSION

INBOX_DIR_VARIABLE = "CIR_INBOX_DIR"
INBOX_TIME_VARIABLE = "CIR_INBOX_DAILY_AT"
SCHEDULER_VARIABLE = "CIR_INBOX_SCHEDULER"
SYSTEM_USER = "system-inbox"
DONE_FOLDER, FAILED_FOLDER = "selesai", "gagal"
RECENT_LIMIT = 30
_log = logging.getLogger("cir.inbox")
_pull_lock = threading.Lock()
_scheduler_started = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS inbox_files (
    file_id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    checksum TEXT NOT NULL UNIQUE,
    received_at TEXT NOT NULL,
    finished_at TEXT,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('processing','analysed','rejected','failed')),
    row_count INTEGER,
    batch_id TEXT,
    run_id TEXT,
    message_code TEXT
);
CREATE TABLE IF NOT EXISTS inbox_pulls (
    pull_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    trigger TEXT NOT NULL,
    actor_user_id TEXT NOT NULL,
    files_found INTEGER NOT NULL DEFAULT 0,
    files_processed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_inbox_files_received ON inbox_files(received_at DESC);
"""


class InboxStorageError(RuntimeError):
    """The operational database is unavailable."""


class InboxBusy(RuntimeError):
    """A pull is already running in this process."""


def now() -> datetime:
    return datetime.now().astimezone()


def inbox_directory() -> Path | None:
    value = os.environ.get(INBOX_DIR_VARIABLE, "").strip()
    return Path(value).expanduser() if value else None


def daily_time() -> time:
    value = os.environ.get(INBOX_TIME_VARIABLE, "").strip() or "06:00"
    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", value)
    return time(int(match.group(1)), int(match.group(2))) if match else time(6, 0)


def next_scheduled(after: datetime) -> datetime:
    at = after.replace(hour=daily_time().hour, minute=daily_time().minute, second=0, microsecond=0)
    return at if at > after else at + timedelta(days=1)


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
        raise InboxStorageError("Penyimpanan folder kiriman tidak tersedia.") from exc
    finally:
        if connection is not None:
            connection.close()


def _batch_key(file_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", Path(file_name).stem.lower()).strip("-")[:60]
    return f"synthetic-{slug or 'kiriman'}"


def _move(path: Path, folder: str) -> None:
    try:
        target = path.parent / folder
        target.mkdir(exist_ok=True)
        destination = target / path.name
        if destination.exists():
            destination = target / f"{path.stem}-{uuid4().hex[:6]}{path.suffix}"
        path.replace(destination)
    except OSError:
        _log.warning("Inbox file could not be moved after processing.")


def _claim(db_path: str | Path, path: Path, checksum: str, trigger: str) -> str | None:
    """Record the file as being processed; None when this content was seen before."""
    file_id = f"inb_{uuid4().hex}"
    with _connection(db_path) as connection:
        if connection.execute("SELECT 1 FROM inbox_files WHERE checksum=?", (checksum,)).fetchone():
            return None
        try:
            connection.execute(
                "INSERT INTO inbox_files(file_id,file_name,checksum,received_at,trigger,status) VALUES (?,?,?,?,?,'processing')",
                (file_id, path.name, checksum, now().isoformat(timespec="seconds"), trigger))
        except DatabaseError:
            return None  # another process claimed the same content first
    return file_id


def _finish(db_path: str | Path, file_id: str, status: str, **values: Any) -> None:
    with _connection(db_path) as connection:
        connection.execute(
            "UPDATE inbox_files SET status=?, finished_at=?, row_count=?, batch_id=?, run_id=?, message_code=? WHERE file_id=?",
            (status, now().isoformat(timespec="seconds"), values.get("row_count"), values.get("batch_id"),
             values.get("run_id"), values.get("message_code"), file_id))


def _process(db_path: str | Path, path: Path, trigger: str) -> bool:
    from app.services.batches import BatchStorageError, BatchStore, configured_upload_limits
    from app.services.runs import RunExecutionError, RunInputError, RunStorageError, create_analysis_run

    max_bytes, max_rows = configured_upload_limits()
    if path.stat().st_size > max_bytes:
        raw = b""
    else:
        raw = path.read_bytes()
    checksum = hashlib.sha256(raw or path.name.encode()).hexdigest()
    file_id = _claim(db_path, path, checksum, trigger)
    if file_id is None:
        _move(path, DONE_FOLDER)
        return False
    if not raw:
        _finish(db_path, file_id, "rejected", message_code="UPLOAD_TOO_LARGE")
        _move(path, FAILED_FOLDER)
        return True
    schema, mapping = ((BPJS_CSV_SCHEMA_VERSION, BPJS_CSV_MAPPING_VERSION) if is_bpjs_csv(raw)
                       else (SYNTHETIC_CSV_SCHEMA_VERSION, SYNTHETIC_CSV_MAPPING_VERSION))
    try:
        batch, _reused = BatchStore(db_path).import_csv(raw, batch_key=_batch_key(path.name), creator_user_id=SYSTEM_USER,
                                                       schema_version=schema, mapping_version=mapping, max_rows=max_rows)
    except (ValueError, BatchStorageError):
        _finish(db_path, file_id, "failed", message_code="BATCH_IMPORT_FAILED")
        _move(path, FAILED_FOLDER)
        return True
    if batch["status"] == "rejected":
        codes = sorted((batch.get("validation") or {}).get("error_counts") or {"rejected": 1})
        _finish(db_path, file_id, "rejected", row_count=batch.get("row_count"), batch_id=batch["batch_id"], message_code=codes[0])
        _move(path, FAILED_FOLDER)
        return True
    try:
        run = create_analysis_run(db_path, batch["batch_id"], SYSTEM_USER)
        _finish(db_path, file_id, "analysed", row_count=batch.get("row_count"), batch_id=batch["batch_id"], run_id=run["run_id"])
        _move(path, DONE_FOLDER)
    except (RunInputError, RunStorageError, RunExecutionError) as exc:
        code = getattr(exc, "args", ["ANALYSIS_RUN_FAILED"])[0] if isinstance(exc, RunInputError) else "ANALYSIS_RUN_FAILED"
        _finish(db_path, file_id, "failed", row_count=batch.get("row_count"), batch_id=batch["batch_id"], message_code=str(code))
        _move(path, FAILED_FOLDER)
    return True


def pull_inbox(db_path: str | Path, *, trigger: str, actor_user_id: str) -> dict[str, Any]:
    """Process every new CSV in the folder once. Raises InboxBusy while another pull runs here."""
    directory = inbox_directory()
    if directory is None or not directory.is_dir():
        return {"configured": False, "files_found": 0, "files_processed": 0}
    if not _pull_lock.acquire(blocking=False):
        raise InboxBusy()
    pull_id = f"pull_{uuid4().hex}"
    try:
        with cluster_lock("inbox-pull") as held:
            if not held:  # another API process is pulling
                raise InboxBusy()
            if trigger == "schedule" and _scheduled_pull_done(db_path):
                return {"configured": True, "files_found": 0, "files_processed": 0}
            return _pull_files(db_path, directory, pull_id, trigger, actor_user_id)
    finally:
        _pull_lock.release()


def _pull_files(db_path: str | Path, directory: Path, pull_id: str, trigger: str, actor_user_id: str) -> dict[str, Any]:
    files = sorted(item for item in directory.iterdir() if item.is_file() and item.suffix.lower() == ".csv")
    with _connection(db_path) as connection:
        connection.execute("INSERT INTO inbox_pulls(pull_id,started_at,trigger,actor_user_id,files_found) VALUES (?,?,?,?,?)",
                           (pull_id, now().isoformat(timespec="seconds"), trigger, actor_user_id, len(files)))
    processed = 0
    for path in files:
        try:
            processed += int(_process(db_path, path, trigger))
        except Exception:  # one bad file never stops the others
            _log.exception("Inbox file could not be processed.")
    with _connection(db_path) as connection:
        connection.execute("UPDATE inbox_pulls SET finished_at=?, files_processed=? WHERE pull_id=?",
                           (now().isoformat(timespec="seconds"), processed, pull_id))
    return {"configured": True, "files_found": len(files), "files_processed": processed}


def start_pull_in_background(db_path: str | Path, actor_user_id: str) -> None:
    if _pull_lock.locked():
        raise InboxBusy()
    threading.Thread(target=lambda: _safe_pull(db_path, "manual", actor_user_id), name="cir-inbox-pull", daemon=True).start()


def _safe_pull(db_path: str | Path, trigger: str, actor_user_id: str) -> None:
    try:
        pull_inbox(db_path, trigger=trigger, actor_user_id=actor_user_id)
    except InboxBusy:
        pass
    except Exception:
        _log.exception("Inbox pull failed.")


def inbox_status(db_path: str | Path) -> dict[str, Any]:
    directory = inbox_directory()
    configured = directory is not None and directory.is_dir()
    with _connection(db_path) as connection:
        last = connection.execute(
            "SELECT * FROM inbox_pulls ORDER BY started_at DESC LIMIT 1").fetchone()
        last_scheduled = connection.execute(
            "SELECT started_at FROM inbox_pulls WHERE trigger='schedule' ORDER BY started_at DESC LIMIT 1").fetchone()
        rows = connection.execute(
            "SELECT file_name,received_at,finished_at,trigger,status,row_count,run_id,message_code FROM inbox_files "
            "ORDER BY received_at DESC, file_name DESC LIMIT ?", (RECENT_LIMIT,)).fetchall()
    waiting = sorted(item.name for item in directory.iterdir()
                     if item.is_file() and item.suffix.lower() == ".csv") if configured else []
    return {
        "configured": configured,
        "folder_name": directory.name if directory is not None else None,
        "daily_at": daily_time().strftime("%H:%M"),
        "scheduler_active": configured and _scheduler_started,
        # Any process's pull: an unfinished pull row from the last two hours, or one running here.
        "running": _pull_lock.locked() or (last is not None and last["finished_at"] is None
                                            and last["started_at"] >= (now() - timedelta(hours=2)).isoformat(timespec="seconds")),
        "next_pull_at": next_scheduled(now()).isoformat(timespec="minutes") if configured else None,
        "last_pull": dict(last) if last is not None else None,
        "last_scheduled_pull_at": last_scheduled["started_at"] if last_scheduled is not None else None,
        "waiting_files": waiting[:RECENT_LIMIT],
        "waiting_count": len(waiting),
        "files": [dict(row) for row in rows],
    }


def scheduled_tick(db_path: str | Path) -> bool:
    """Pull once if the most recent scheduled moment has no scheduled pull yet (a missed one is caught up)."""
    if inbox_directory() is None:
        return False
    if _scheduled_pull_done(db_path):
        return False
    _safe_pull(db_path, "schedule", SYSTEM_USER)
    return True


def _scheduled_pull_done(db_path: str | Path) -> bool:
    """Whether the most recent scheduled moment already has a scheduled pull (by any process)."""
    due = next_scheduled(now()) - timedelta(days=1)
    with _connection(db_path) as connection:
        return connection.execute("SELECT 1 FROM inbox_pulls WHERE trigger='schedule' AND started_at >= ?",
                                  (due.isoformat(timespec="seconds"),)).fetchone() is not None


def _scheduler_loop(db_path: str | Path, interval_seconds: float) -> None:
    import time as clock

    while True:
        clock.sleep(interval_seconds)
        try:
            scheduled_tick(db_path)
        except Exception:
            _log.exception("Inbox scheduler check failed.")


def start_scheduler(db_path: str | Path, interval_seconds: float = 30.0) -> bool:
    """Start the daily schedule once per process when a folder is configured (CIR_INBOX_SCHEDULER=off disables)."""
    global _scheduler_started
    if _scheduler_started or inbox_directory() is None or os.environ.get(SCHEDULER_VARIABLE, "").lower() == "off":
        return False
    _scheduler_started = True
    threading.Thread(target=_scheduler_loop, args=(db_path, interval_seconds), name="cir-inbox-scheduler", daemon=True).start()
    return True
