"""PostgreSQL-specific behaviour on a real server (needs CIR_TEST_DATABASE_URL)."""

from contextlib import contextmanager
import multiprocessing
import os
from pathlib import Path
import time

import pytest

from app import db
from app.db_migrations import schema_status, upgrade
from app.services import run_reviews, runs as runs_service
from app.services.run_results import SORT_KEYS
from tests.db_helpers import db_connection
from tests.test_analysis_runs import call, create_run, import_batch, operator_session, setup, verifier_session

pytestmark = pytest.mark.postgres


@contextmanager
def sqlite_mode():
    saved = {name: os.environ.pop(name, None) for name in ("CIR_DATABASE_URL", "CIR_DATABASE_SCHEMA")}
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value


def test_schema_is_created_from_an_empty_database_and_versions_are_checked(operational_database):
    database = db.configured_database()
    status = schema_status(database)
    assert status["ok"] and status["applied"] == ["0001_initial", "0002_event_insertion_order", "0003_data_migration_log",
                                             "0004_list_visibility", "0005_inbox",
                                             "0006_retention", "0007_case_assignments",
                                             "0008_drop_retention", "0009_clinical_ai", "0010_rate_limits"]
    assert upgrade(database) == []  # idempotent
    with db_connection("unused") as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")}
    assert {"analysis_runs", "analysis_run_cases", "analysis_run_result_views", "run_case_reviews",
            "fkrtl_validation_jobs", "fkrtl_source_validations", "auth_users", "data_migration_runs",
            "data_batch_removals", "analysis_run_archives", "inbox_files", "inbox_pulls", "case_assignments", "clinical_ai_reviews", "rate_limit_hits"} <= tables
    assert "retention_purges" not in tables  # dropped again by 0008
    # A migration whose recorded checksum differs from the file is refused, not re-run.
    with db_connection("unused") as connection:
        connection.execute("UPDATE schema_migrations SET sha256='tampered' WHERE version='0002_event_insertion_order'")
    with pytest.raises(db.DatabaseConfigurationError, match="0002_event_insertion_order"):
        upgrade(database)


def test_startup_refuses_an_unmigrated_schema_and_an_unreachable_server_without_leaking_the_url(tmp_path, monkeypatch):
    from app.main import create_app

    with db_connection("unused") as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version='0003_data_migration_log'")
    with pytest.raises(db.DatabaseConfigurationError, match="db_migrate"):
        create_app(tmp_path / "r.sqlite3", tmp_path / "a.sqlite3", cookie_secure=False, batch_db_path=tmp_path / "b.sqlite3")
    monkeypatch.setenv("CIR_DATABASE_URL", "postgresql://cir_admin:not-the-password@127.0.0.1:1/cir_test")
    monkeypatch.setenv(db.POOL_TIMEOUT_VARIABLE, "2")
    with pytest.raises(db.DatabaseConfigurationError) as raised:
        create_app(tmp_path / "r.sqlite3", tmp_path / "a.sqlite3", cookie_secure=False, batch_db_path=tmp_path / "b.sqlite3")
    assert "not-the-password" not in str(raised.value) and "127.0.0.1" not in str(raised.value)


def test_a_database_failure_during_a_request_is_a_controlled_503(tmp_path, monkeypatch):
    import psycopg

    app, _batch_db, users = setup(tmp_path)
    verifier = verifier_session(app, users)

    def unavailable(self):
        raise psycopg.OperationalError("connection to server at 127.0.0.1 failed: password=hunter2 rejected")
    monkeypatch.setattr(db.PostgresDatabase, "connect", unavailable)
    response = call(app, "GET", "/api/v1/runs", cookies=verifier)
    assert response.status_code in (401, 503)  # session lookup or run storage, both controlled
    assert "hunter2" not in response.text and "127.0.0.1" not in response.text


def test_runs_created_on_postgresql_and_sqlite_give_identical_views(tmp_path, monkeypatch):
    def views(base):
        app, batch_db, users = setup(base)
        operator = operator_session(app, users)
        batch, _ = import_batch(app, batch_db, operator)
        run_id = create_run(app, operator, batch["batch_id"]).json()["run"]["run_id"]
        verifier = verifier_session(app, users)
        out = {"summary": call(app, "GET", f"/api/v1/runs/{run_id}?view=summary", cookies=verifier).json()["result"]}
        out["summary"].pop("generated_at", None)
        for sort in SORT_KEYS:
            page = call(app, "GET", f"/api/v1/runs/{run_id}/cases?limit=9&offset=2&sort={sort}&search=syn",
                        cookies=verifier).json()
            page.pop("run_id")
            out[sort] = page
        first = out["stored"]["items"][0]["case"]["case_id"]
        case = call(app, "GET", f"/api/v1/runs/{run_id}/cases/{first}", cookies=verifier).json()["result"]
        case.pop("generated_at", None)
        out["case"] = case
        return out

    (tmp_path / "pg").mkdir()
    (tmp_path / "sqlite").mkdir()
    on_postgres = views(tmp_path / "pg")
    with sqlite_mode():
        on_sqlite = views(tmp_path / "sqlite")
    assert on_postgres == on_sqlite


def test_run_finalization_is_atomic(tmp_path, monkeypatch):
    app, _batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _ = import_batch(app, _batch_db, operator)

    def broken_rows(*_args, **_kwargs):
        raise RuntimeError("failure after the result row was written")
    monkeypatch.setattr(runs_service, "write_case_rows", broken_rows)
    response = create_run(app, operator, batch["batch_id"])
    assert response.status_code >= 500
    with db_connection("unused") as connection:
        [(run_id, status)] = connection.execute("SELECT run_id, execution_status FROM analysis_runs").fetchall()
        assert status == "running"  # no terminal state without its result
        for table in ("analysis_run_results", "analysis_run_cases", "analysis_run_result_views"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table} WHERE run_id=?", (run_id,)).fetchone()[0] == 0, table


def test_a_review_write_is_atomic(tmp_path, monkeypatch):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _ = import_batch(app, batch_db, operator)
    run_id = create_run(app, operator, batch["batch_id"]).json()["run"]["run_id"]
    verifier = verifier_session(app, users)
    case_id = call(app, "GET", f"/api/v1/runs/{run_id}/cases?limit=1", cookies=verifier).json()["items"][0]["case"]["case_id"]

    class FixedId:
        hex = "0" * 32
    monkeypatch.setattr(run_reviews, "uuid4", lambda: FixedId())  # the second event id collides
    url = f"/api/v1/runs/{run_id}/cases/{case_id}/review"
    headers = {"X-CSRF-Token": verifier["cir_csrf"]}
    assert call(app, "PATCH", url, cookies=verifier, json_body={"review_status": "in_review"}, headers=headers).status_code == 200
    failed = call(app, "PATCH", url, cookies=verifier, json_body={"review_status": "escalated"}, headers=headers)
    assert failed.status_code == 503
    with db_connection("unused") as connection:
        assert connection.execute("SELECT review_status FROM run_case_reviews").fetchone()[0] == "in_review"
        assert connection.execute("SELECT COUNT(*) FROM run_case_review_events").fetchone()[0] == 1


def _slow_validation(progress=None):
    time.sleep(30)
    return {"status": "passed", "errors": [], "warnings": [], "scan": None, "checks": []}


def _claim_in_child(url: str, schema: str, barrier, results) -> None:
    os.environ["CIR_DATABASE_URL"] = url
    os.environ["CIR_DATABASE_SCHEMA"] = schema
    from app.services.validation_jobs import start_validation_job

    barrier.wait(30)
    job, started = start_validation_job(Path("unused"), "fingerprint", _slow_validation)
    results.put((started, job["job_id"]))


def test_concurrent_validation_requests_from_separate_processes_start_one_job(operational_database):
    context = multiprocessing.get_context("spawn")
    workers = 4
    barrier, results = context.Barrier(workers), context.Queue()
    processes = [context.Process(target=_claim_in_child,
                                 args=(os.environ["CIR_DATABASE_URL"], operational_database, barrier, results))
                 for _ in range(workers)]
    for process in processes:
        process.start()
    outcomes = [results.get(timeout=120) for _ in processes]
    for process in processes:
        process.join(30)
    assert sum(started for started, _job in outcomes) == 1
    assert len({job for _started, job in outcomes}) == 1  # everyone sees the same job
    with db_connection("unused") as connection:
        assert connection.execute("SELECT COUNT(*) FROM fkrtl_validation_jobs").fetchone()[0] == 1
        active = connection.execute("SELECT COUNT(*) FROM fkrtl_validation_jobs WHERE status IN ('pending','running')")
        assert active.fetchone()[0] == 1


def test_the_database_itself_refuses_a_second_active_job(operational_database):
    from app.db import is_postgres
    from psycopg import errors

    with db_connection("unused") as connection:
        assert is_postgres(connection)
        connection.execute("INSERT INTO fkrtl_validation_jobs(job_id,status,requested_at) VALUES ('a','running','2026')")
        with pytest.raises(errors.UniqueViolation):
            connection.execute("INSERT INTO fkrtl_validation_jobs(job_id,status,requested_at) VALUES ('b','pending','2026')")
