"""Backend-agnostic helpers for tests that read or poke the operational database directly.

They use the configured backend (a test's SQLite file, or the per-test PostgreSQL schema),
so the same assertions run on both.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import re
import sqlite3

from app.db import configured_database, connect_operational, is_postgres


def on_postgres() -> bool:
    return configured_database() is not None


@contextmanager
def db_connection(path):
    """Connection to the operational database; committed and closed afterwards."""
    connection = connect_operational(path, timeout=20)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def assert_rejected(connection, sql: str, params: tuple = (), match: str | None = None) -> None:
    """The statement must be refused by a trigger or constraint (rolled back, nothing changes).

    On PostgreSQL it runs in a savepoint so a later statement is not hidden behind an aborted
    transaction, and only a genuine rejection counts (not "current transaction is aborted").
    """
    if is_postgres(connection):
        import psycopg
        from psycopg import errors

        connection.execute("SAVEPOINT expect_rejected")
        try:
            connection.execute(sql, params)
        except (errors.RaiseException, errors.RestrictViolation, errors.IntegrityError) as exc:
            connection.execute("ROLLBACK TO SAVEPOINT expect_rejected")
            if match:
                assert re.search(match, str(exc)), str(exc)
            return
        except psycopg.Error as exc:  # anything else is a test failure, not a rejection
            raise AssertionError(f"unexpected database error: {type(exc).__name__}") from exc
        raise AssertionError("statement was not rejected")
    try:
        connection.execute(sql, params)
    except sqlite3.DatabaseError as exc:
        if match:
            assert re.search(match, str(exc)), str(exc)
        return
    raise AssertionError("statement was not rejected")


def seed_reviewable_runs(run_db, runs, result: dict) -> None:
    """Runs with stored results for review tests: [(run_id, status, result_available)].

    SQLite keeps the minimal legacy-shaped tables these tests were written against; PostgreSQL
    (full schema, triggers active) replays the real lifecycle: batch, running run, result,
    terminal status.
    """
    if not on_postgres():
        with sqlite3.connect(run_db) as connection:
            connection.executescript("""
                CREATE TABLE analysis_runs (
                    run_id TEXT PRIMARY KEY,
                    execution_status TEXT NOT NULL,
                    result_available INTEGER NOT NULL
                );
                CREATE TABLE analysis_run_results (
                    run_id TEXT PRIMARY KEY REFERENCES analysis_runs(run_id),
                    result_json TEXT NOT NULL
                );
            """)
            for run_id, status, available in runs:
                connection.execute("INSERT INTO analysis_runs VALUES (?,?,?)", (run_id, status, available))
                if available:
                    connection.execute("INSERT INTO analysis_run_results VALUES (?,?)",
                                       (run_id, json.dumps(result, sort_keys=True)))
        return
    now = datetime.now(timezone.utc).isoformat()
    with db_connection(run_db) as connection:
        connection.execute(
            "INSERT INTO data_batches(batch_id,batch_key,batch_version,created_at,creator_user_id,source_type,"
            "schema_version,mapping_version,content_checksum,row_count,validation_summary_json,status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("bat_seed", "synthetic-seed", 1, now, "test-setup", "synthetic_csv", "seed", "seed", "seed", 0, "{}",
             "rejected"))
        for run_id, status, available in runs:
            connection.execute(
                "INSERT INTO analysis_runs(run_id,batch_id,batch_version,content_checksum,source_type,"
                "source_schema_version,source_mapping_version,creator_user_id,created_at,started_at,"
                "execution_status,configuration_json,result_available) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, "bat_seed", 1, "seed", "synthetic_csv", "seed", "seed", "test-setup", now, now,
                 "running", "{}", 0))
            if available:
                connection.execute("INSERT INTO analysis_run_results VALUES (?,?)",
                                   (run_id, json.dumps(result, sort_keys=True)))
            connection.execute("UPDATE analysis_runs SET execution_status=?, result_available=?, completed_at=? "
                               "WHERE run_id=?", (status, available, now, run_id))
