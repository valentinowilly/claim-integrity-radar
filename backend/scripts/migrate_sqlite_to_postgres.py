"""Copy CIR operational data from SQLite files into the PostgreSQL database (CIR_DATABASE_URL).

    python -m scripts.migrate_sqlite_to_postgres --batch-db PATH [--auth-db PATH] [--review-db PATH]
                                                 [--dry-run | --verify-only]

Sources are the SQLite files the stores used (``CIR_BATCH_DB_PATH``, ``CIR_AUTH_DB_PATH``,
``CIR_REVIEW_DB_PATH``); pass the exact files. They are opened read-only and never changed.
The target schema must be migrated first (``python -m scripts.db_migrate``).

What is copied: users, auth metadata, security/audit events, legacy reviews, synthetic CSV
batches and their records, action policies, analysis runs with their stored result text
(byte-identical), per-case rows and summaries, run reviews, review history, audit
confirmations, source validations and validation jobs.

What is not copied or is deliberately changed:

* No source data: records of an FKRTL batch would be raw BPJS rows, so the migration refuses
  to run if any exist (FKRTL batches are metadata-only by design). ``.dta`` files are never read.
* Sessions are not copied; users sign in again after cutover.
* Validation fingerprints are cleared: an old validation is shown as history but never counts
  as current in the new environment, so every run after cutover needs a fresh validation.
* Pending/running validation jobs become failed with ``FKRTL_VALIDATION_INTERRUPTED`` (finished at
  their last heartbeat).
* ``security_audit_events`` from the auth and review files are merged into one table; their
  insertion order is kept per source (ordered by time, then original rowid).

Everything happens in one transaction: either all data is copied and verified (row counts,
a canonical digest per table, SHA-256 of every stored result) and the run is recorded in
``data_migration_runs``, or nothing is written. Re-running is idempotent: rows already present
are skipped if they are identical and the migration aborts if they differ. Immutability
triggers stay active: terminal runs are written through their normal lifecycle (running run,
result, case rows, terminal status). Prints table names and counts only.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Callable
from uuid import uuid4

from app.db import DatabaseConfigurationError, configured_database
from app.db_migrations import schema_status

_MIGRATION_LOCK = 0x43_49_52_44  # "CIRD"
_INTERRUPTED = "FKRTL_VALIDATION_INTERRUPTED"


class MigrationError(Exception):
    """Safe, actionable failure (no values, paths or credentials)."""


# (source, table, primary key, keep source rowid as the "rowid" column)
TABLES: list[tuple[str, str, tuple[str, ...], bool]] = [
    ("auth", "auth_users", ("user_id",), False),
    ("auth", "auth_metadata", ("metadata_key",), False),
    ("review", "review_cases", ("case_id",), False),
    ("review", "review_history", ("id",), False),
    ("batch", "data_batches", ("batch_id",), False),
    ("batch", "data_batch_records", ("batch_id", "claim_id"), False),
    ("batch", "batch_security_audit_events", ("event_id",), True),
    ("batch", "action_policy_configurations", ("version",), False),
    ("batch", "analysis_runs", ("run_id",), False),
    ("batch", "analysis_run_results", ("run_id",), False),
    ("batch", "analysis_run_cases", ("run_id", "case_id"), False),
    ("batch", "analysis_run_result_views", ("run_id",), False),
    ("batch", "analysis_run_audit_events", ("event_id",), True),
    ("batch", "run_case_reviews", ("review_id",), False),
    ("batch", "run_case_review_events", ("event_id",), True),
    ("batch", "run_review_security_audit_events", ("event_id",), True),
    ("batch", "run_case_audit_confirmations", ("confirmation_id",), True),
    ("batch", "fkrtl_source_validations", ("validation_id",), True),
    ("batch", "fkrtl_validation_jobs", ("job_id",), True),
    ("batch", "data_batch_removals", ("batch_id",), False),
    ("batch", "analysis_run_archives", ("run_id",), False),
    ("batch", "inbox_files", ("file_id",), False),
    ("batch", "inbox_pulls", ("pull_id",), False),
    ("batch", "case_assignments", ("case_id",), False),
    ("batch", "clinical_ai_reviews", ("review_id",), True),
]
# Merged from the auth and review files; new rowids in (occurred_at, source, rowid) order.
MERGED_EVENTS = "security_audit_events"
SKIPPED = {"auth_sessions": "sessions are not migrated; users sign in again"}


def _open_source(path: Path | None) -> sqlite3.Connection | None:
    if path is None:
        return None
    if not path.is_file():
        raise MigrationError(f"Berkas SQLite sumber tidak ditemukan: {path.name}")
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_tables(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _target_columns(target, table: str) -> list[str]:
    rows = target.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name = ? ORDER BY ordinal_position", (table,)).fetchall()
    return [row[0] for row in rows]


def _transform(table: str, row: dict[str, Any], now: str) -> dict[str, Any]:
    """Deliberate changes for the new environment (documented above)."""
    if table in ("fkrtl_source_validations", "fkrtl_validation_jobs"):
        row["fingerprint"] = None
    if table == "fkrtl_validation_jobs":
        row.setdefault("owner", None)
        row["owner"] = None
        if row.get("status") in ("pending", "running"):
            # Finished at its last sign of life (deterministic, so a re-run compares equal).
            last_seen = row.get("heartbeat_at") or row.get("started_at") or row["requested_at"]
            row.update(status="failed", error_code=_INTERRUPTED, finished_at=last_seen)
    return row


def _read_rows(source: sqlite3.Connection, table: str, columns: list[str], keep_rowid: bool,
               now: str) -> list[dict[str, Any]]:
    available = [column for column in columns if column != "rowid"]
    present = {row["name"] for row in source.execute(f"PRAGMA table_info({table})")}
    selected = [column for column in available if column in present]
    sql = f"SELECT {', '.join(selected)}{', rowid AS rowid' if keep_rowid else ''} FROM {table} ORDER BY rowid"
    return [_transform(table, dict(row), now) for row in source.execute(sql)]


def _key(row: dict[str, Any], primary_key: tuple[str, ...]) -> tuple:
    return tuple(row[column] for column in primary_key)


def _canonical(rows: list[dict[str, Any]], columns: list[str], primary_key: tuple[str, ...]) -> str:
    ordered = sorted(rows, key=lambda item: json.dumps(_key(item, primary_key), default=str))
    payload = [[row.get(column) for column in columns] for row in ordered]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _insert(target, table: str, row: dict[str, Any]) -> None:
    columns = list(row)
    target.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                   tuple(row[column] for column in columns))


def _existing(target, table: str, primary_key: tuple[str, ...], columns: list[str]) -> dict[tuple, dict]:
    rows = target.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
    return {tuple(row[column] for column in primary_key): {column: row[column] for column in columns} for row in rows}


def _same(source_row: dict[str, Any], target_row: dict[str, Any], compared: list[str]) -> bool:
    return all(source_row.get(column) == target_row.get(column) for column in compared)


def migrate(sources: dict[str, Path | None], *, dry_run: bool = False, verify_only: bool = False) -> dict[str, Any]:
    database = configured_database()
    if database is None:
        raise MigrationError("CIR_DATABASE_URL belum diset; tidak ada database PostgreSQL tujuan.")
    status = schema_status(database)
    if not status["ok"]:
        raise MigrationError("Skema PostgreSQL tujuan belum sesuai; jalankan python -m scripts.db_migrate terlebih dahulu.")
    opened = {name: _open_source(path) for name, path in sources.items()}
    if opened.get("review") is not None and sources["review"] == sources.get("auth"):
        opened["review"] = None  # one file holding both stores is read once
    now = datetime.now(timezone.utc).isoformat()
    report: dict[str, Any] = {"mode": "verify-only" if verify_only else "dry-run" if dry_run else "migrate",
                              "tables": {}, "skipped": dict(SKIPPED), "notes": []}
    target = database.connect()
    try:
        target.lock(_MIGRATION_LOCK)
        tables = {name: _source_tables(connection) for name, connection in opened.items() if connection}
        batch = opened.get("batch")
        if batch is not None and {"data_batches", "data_batch_records"} <= tables["batch"]:
            raw = batch.execute("SELECT COUNT(*) FROM data_batch_records r JOIN data_batches b ON b.batch_id=r.batch_id "
                                "WHERE b.source_type='bpjs_fkrtl_local'").fetchone()[0]
            if raw:
                raise MigrationError("Sumber berisi record batch FKRTL (data mentah); migrasi ditolak.")
        plan: list[tuple[str, str, tuple[str, ...], bool, list[str], list[dict[str, Any]]]] = []
        for source_name, table, primary_key, keep_rowid in TABLES:
            source = opened.get(source_name)
            if source is None or table not in tables[source_name]:
                continue
            columns = _target_columns(target, table)
            rows = _read_rows(source, table, columns, keep_rowid, now)
            plan.append((source_name, table, primary_key, keep_rowid, columns, rows))
        merged = []
        for order, source_name in enumerate(("auth", "review")):
            source = opened.get(source_name)
            if source is not None and MERGED_EVENTS in tables[source_name]:
                columns = _target_columns(target, MERGED_EVENTS)
                merged += [(row["occurred_at"], order, row["rowid"], row)
                           for row in _read_rows(source, MERGED_EVENTS, columns, True, now)]
        merged_rows = [row for *_ignored, row in sorted(merged, key=lambda item: item[:3])]
        for row in merged_rows:
            row.pop("rowid")

        if not verify_only:
            _write(target, plan, merged_rows, report)
        _verify(target, plan, merged_rows, report)
        if report["verification"]["ok"] is not True:
            raise MigrationError("Verifikasi gagal: " + ", ".join(report["verification"]["mismatches"]))
        digests = {name: _file_digest(path) for name, path in sources.items() if path is not None}
        if not verify_only and not dry_run:
            target.execute("INSERT INTO data_migration_runs VALUES (?,?,?,?,?)",
                           (f"mig_{uuid4().hex}", now, datetime.now(timezone.utc).isoformat(),
                            json.dumps(digests, sort_keys=True), json.dumps(report, sort_keys=True)))
            target.commit()
        else:
            target.rollback()  # dry run and verification write nothing
        report["source_files"] = {name: Path(path).name for name, path in sources.items() if path is not None}
        return report
    except BaseException:
        target.rollback()
        raise
    finally:
        target.close()
        for connection in opened.values():
            if connection is not None:
                connection.close()


def _write(target, plan, merged_rows, report) -> None:
    lifecycles: dict[str, Callable] = {"data_batches": _write_batches, "analysis_runs": _write_runs}
    by_table = {table: (primary_key, keep_rowid, columns, rows) for _s, table, primary_key, keep_rowid, columns, rows in plan}
    handled = set()
    for _source, table, primary_key, keep_rowid, columns, rows in plan:
        if table in handled:
            continue
        if table in lifecycles:
            handled |= lifecycles[table](target, by_table, report)
            continue
        inserted, skipped = _copy_rows(target, table, primary_key, columns, rows)
        report["tables"][table] = {"source_rows": len(rows), "inserted": inserted, "already_present": skipped}
        handled.add(table)
        if keep_rowid:
            _sync_identity(target, table, "rowid")
        if table == "review_history":
            _sync_identity(target, table, "id")
    if merged_rows:
        existing = _existing(target, MERGED_EVENTS, ("event_id",), [c for c in _target_columns(target, MERGED_EVENTS) if c != "rowid"])
        inserted = skipped = 0
        for row in merged_rows:
            current = existing.get((row["event_id"],))
            if current is None:
                _insert(target, MERGED_EVENTS, row)
                inserted += 1
            elif _same(row, current, list(row)):
                skipped += 1
            else:
                raise MigrationError(f"Baris berbeda sudah ada di tujuan: {MERGED_EVENTS}")
        report["tables"][MERGED_EVENTS] = {"source_rows": len(merged_rows), "inserted": inserted, "already_present": skipped}


def _copy_rows(target, table, primary_key, columns, rows) -> tuple[int, int]:
    if not rows:
        return 0, 0
    compared = [column for column in rows[0] if column != "rowid"]
    existing = _existing(target, table, primary_key, [column for column in columns if column in rows[0]])
    inserted = skipped = 0
    for row in rows:
        current = existing.get(_key(row, primary_key))
        if current is None:
            _insert(target, table, row)
            inserted += 1
        elif _same(row, current, compared):
            skipped += 1
        else:
            raise MigrationError(f"Baris berbeda sudah ada di tujuan: {table}")
    return inserted, skipped


def _sync_identity(target, table: str, column: str) -> None:
    target.execute(f"SELECT setval(pg_get_serial_sequence('{table}', '{column}'), "
                   f"GREATEST((SELECT COALESCE(MAX({column}), 0) FROM {table}), 1))")


def _write_batches(target, by_table, report) -> set[str]:
    """Ready batches are immutable once ready: insert as validating, add records, then set status."""
    primary_key, _keep, columns, batches = by_table["data_batches"]
    records = by_table.get("data_batch_records", ((), False, [], []))[3]
    existing = _existing(target, "data_batches", primary_key, [c for c in columns if batches and c in batches[0]])
    existing_records = _existing(target, "data_batch_records", ("batch_id", "claim_id"),
                                 ["batch_id", "claim_id", "case_id", "record_json"]) if records else {}
    inserted = skipped = records_inserted = records_skipped = 0
    for batch in batches:
        own = [row for row in records if row["batch_id"] == batch["batch_id"]]
        current = existing.get((batch["batch_id"],))
        if current is not None:
            if not _same(batch, current, list(batch)):
                raise MigrationError("Baris berbeda sudah ada di tujuan: data_batches")
            skipped += 1
            for row in own:
                if existing_records.get((row["batch_id"], row["claim_id"])) != row:
                    raise MigrationError("Record batch di tujuan tidak sama dengan sumber: data_batch_records")
                records_skipped += 1
            continue
        _insert(target, "data_batches", {**batch, "status": "validating"})
        for row in own:
            _insert(target, "data_batch_records", row)
            records_inserted += 1
        if batch["status"] != "validating":
            target.execute("UPDATE data_batches SET status=? WHERE batch_id=?", (batch["status"], batch["batch_id"]))
        inserted += 1
    report["tables"]["data_batches"] = {"source_rows": len(batches), "inserted": inserted, "already_present": skipped}
    report["tables"]["data_batch_records"] = {"source_rows": len(records), "inserted": records_inserted,
                                              "already_present": records_skipped}
    return {"data_batches", "data_batch_records"}


_TERMINAL_FIELDS = ("completed_at", "execution_status", "failure_category", "detector_suite_version", "scoring_version",
                    "priority_version", "action_policy_version", "configuration_json", "coverage_summary_json",
                    "result_available")


def _write_runs(target, by_table, report) -> set[str]:
    """Terminal runs are immutable: replay running -> result -> case rows -> terminal status."""
    primary_key, _keep, columns, runs = by_table["analysis_runs"]
    results = {row["run_id"]: row for row in by_table.get("analysis_run_results", ((), False, [], []))[3]}
    cases = by_table.get("analysis_run_cases", ((), False, [], []))[3]
    views = {row["run_id"]: row for row in by_table.get("analysis_run_result_views", ((), False, [], []))[3]}
    run_columns = [c for c in columns if runs and c in runs[0]]
    existing = _existing(target, "analysis_runs", primary_key, run_columns)
    counts = {"analysis_runs": [0, 0], "analysis_run_results": [0, 0], "analysis_run_cases": [0, 0],
              "analysis_run_result_views": [0, 0]}
    remaining = sorted(runs, key=lambda row: (row["created_at"], row["run_id"]))
    done: set[str] = set(existing)  # keys are 1-tuples
    done = {key[0] for key in done}
    while remaining:  # retries reference an earlier run (self foreign key)
        progressed, deferred = False, []
        for run in remaining:
            if run.get("retry_of_run_id") and run["retry_of_run_id"] not in done and run["retry_of_run_id"] in {r["run_id"] for r in remaining}:
                deferred.append(run)
                continue
            progressed = True
            current = existing.get((run["run_id"],))
            own_cases = sorted((row for row in cases if row["run_id"] == run["run_id"]), key=lambda row: row["position"])
            if current is not None:
                if not _same(run, current, list(run)):
                    raise MigrationError("Baris berbeda sudah ada di tujuan: analysis_runs")
                counts["analysis_runs"][1] += 1
                stored = target.execute("SELECT result_json FROM analysis_run_results WHERE run_id=?", (run["run_id"],)).fetchone()
                source_result = results.get(run["run_id"])
                if (stored[0] if stored else None) != (source_result["result_json"] if source_result else None):
                    raise MigrationError("Hasil run di tujuan tidak sama dengan sumber: analysis_run_results")
                counts["analysis_run_results"][1] += int(source_result is not None)
                counts["analysis_run_cases"][1] += len(own_cases)
                counts["analysis_run_result_views"][1] += int(run["run_id"] in views)
                done.add(run["run_id"])
                continue
            terminal = {field: run.get(field) for field in _TERMINAL_FIELDS if field in run}
            first = {**run, "execution_status": "running", "result_available": 0, "completed_at": None,
                     "failure_category": None}
            _insert(target, "analysis_runs", first)
            counts["analysis_runs"][0] += 1
            if run["run_id"] in results:
                _insert(target, "analysis_run_results", results[run["run_id"]])
                counts["analysis_run_results"][0] += 1
                for row in own_cases:
                    _insert(target, "analysis_run_cases", row)
                counts["analysis_run_cases"][0] += len(own_cases)
                if run["run_id"] in views:
                    _insert(target, "analysis_run_result_views", views[run["run_id"]])
                    counts["analysis_run_result_views"][0] += 1
            if terminal.get("execution_status") != "running":
                assignments = ", ".join(f"{field}=?" for field in terminal)
                target.execute(f"UPDATE analysis_runs SET {assignments} WHERE run_id=?",
                               (*terminal.values(), run["run_id"]))
            done.add(run["run_id"])
        if not progressed:
            raise MigrationError("Rantai retry run tidak dapat diurutkan.")
        remaining = deferred
    sources = {"analysis_runs": runs, "analysis_run_results": list(results.values()), "analysis_run_cases": cases,
               "analysis_run_result_views": list(views.values())}
    for table, (inserted, skipped) in counts.items():
        report["tables"][table] = {"source_rows": len(sources[table]), "inserted": inserted, "already_present": skipped}
    report["runs_left_running"] = sum(run["execution_status"] == "running" for run in runs)
    return set(counts)


def _verify(target, plan, merged_rows, report) -> None:
    mismatches: list[str] = []
    for _source, table, primary_key, _keep, _columns, rows in plan:
        if not rows:
            continue
        compared = list(rows[0])
        keys = {_key(row, primary_key) for row in rows}
        present = [row for key, row in _existing(target, table, primary_key, compared).items() if key in keys]
        if len(present) != len(rows) or _canonical(present, compared, primary_key) != _canonical(rows, compared, primary_key):
            mismatches.append(table)
        report["tables"].setdefault(table, {})["verified_rows"] = len(present)
    if merged_rows:
        compared = list(merged_rows[0])
        keys = {(row["event_id"],) for row in merged_rows}
        present = [row for key, row in _existing(target, MERGED_EVENTS, ("event_id",), compared).items() if key in keys]
        if _canonical(present, compared, ("event_id",)) != _canonical(merged_rows, compared, ("event_id",)):
            mismatches.append(MERGED_EVENTS)
        report["tables"].setdefault(MERGED_EVENTS, {})["verified_rows"] = len(present)
    results = next((rows for _s, table, _p, _k, _c, rows in plan if table == "analysis_run_results"), [])
    stored = {row[0]: row[1] for row in target.execute("SELECT run_id, result_json FROM analysis_run_results").fetchall()}
    result_mismatch = sum(hashlib.sha256((stored.get(row["run_id"]) or "").encode()).digest()
                          != hashlib.sha256(row["result_json"].encode()).digest() for row in results)
    if result_mismatch:
        mismatches.append("analysis_run_results(sha256)")
    report["verification"] = {"ok": not mismatches, "mismatches": mismatches,
                              "result_json_sha256_checked": len(results), "result_json_sha256_mismatches": result_mismatch}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch-db", type=Path, required=True, help="SQLite file of batches, runs and reviews")
    parser.add_argument("--auth-db", type=Path, help="SQLite file of users (CIR_AUTH_DB_PATH)")
    parser.add_argument("--review-db", type=Path, help="SQLite file of the legacy review workflow (CIR_REVIEW_DB_PATH)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="copy and verify inside a transaction, then roll back")
    mode.add_argument("--verify-only", action="store_true", help="compare source and target without writing")
    args = parser.parse_args()
    try:
        report = migrate({"batch": args.batch_db, "auth": args.auth_db, "review": args.review_db},
                         dry_run=args.dry_run, verify_only=args.verify_only)
    except (MigrationError, DatabaseConfigurationError) as exc:
        print(json.dumps({"ok": False, "error": str(exc), "written": False}))
        return 1
    except Exception as exc:  # database failure: type only, nothing was committed
        print(json.dumps({"ok": False, "error": f"migrasi gagal ({type(exc).__name__}); tidak ada data yang ditulis",
                          "written": False}))
        return 1
    print(json.dumps({"ok": True, **report}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
