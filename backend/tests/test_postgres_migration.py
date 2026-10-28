"""SQLite -> PostgreSQL data migration on a real server (needs CIR_TEST_DATABASE_URL)."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
import sqlite3

import pytest

from app.services import runs as runs_service
from app.services.run_results import SORT_KEYS
from scripts.migrate_sqlite_to_postgres import MigrationError, migrate
from tests.db_helpers import db_connection
from tests.test_analysis_runs import call, create_run, import_batch, login, operator_session, setup, verifier_session

pytestmark = pytest.mark.postgres
PASSWORDS = {"verifier": "Synthetic-verifier-password-2026!", "lead": "Synthetic-lead-password-2026!"}


@contextmanager
def sqlite_mode():
    """Run part of a test against SQLite files (the migration source)."""
    saved = {name: os.environ.pop(name, None) for name in ("CIR_DATABASE_URL", "CIR_DATABASE_SCHEMA")}
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value


def _views(app, verifier, run_id):
    """Every read the UI uses, with values that differ per environment removed."""
    full = call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier).json()
    out = {"full_result": full["result"], "manifest": {k: v for k, v in full["run"].items()},
           "summary": call(app, "GET", f"/api/v1/runs/{run_id}?view=summary", cookies=verifier).json()["result"],
           "reviews": call(app, "GET", f"/api/v1/runs/{run_id}/reviews", cookies=verifier).json()}
    for sort in SORT_KEYS:
        for query in ("", "&review_filter=not_started", "&review_filter=in_review", "&search=SYN-CLAIM-00"):
            out[f"page:{sort}{query}"] = call(app, "GET", f"/api/v1/runs/{run_id}/cases?limit=7&offset=3&sort={sort}{query}",
                                              cookies=verifier).json()
    for case_id in list(full["result"]["cases"])[:3]:
        out[f"case:{case_id}"] = call(app, "GET", f"/api/v1/runs/{run_id}/cases/{case_id}", cookies=verifier).json()
        review = call(app, "GET", f"/api/v1/runs/{run_id}/cases/{case_id}/review", cookies=verifier).json()
        out[f"review:{case_id}"] = review
    return out


def _build_sqlite_source(tmp_path, monkeypatch):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _ = import_batch(app, batch_db, operator)
    run_id = create_run(app, operator, batch["batch_id"]).json()["run"]["run_id"]
    # A run stored before per-case rows existed (backfilled after migration).
    monkeypatch.setattr(runs_service, "write_case_rows", lambda *_args: False)
    legacy_run = create_run(app, operator, batch["batch_id"]).json()["run"]["run_id"]
    monkeypatch.undo()
    verifier, lead = verifier_session(app, users), verifier_session(app, users, "lead")
    first, second = list(call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier).json()["result"]["cases"])[:2]
    for case_id, status in ((first, "in_review"), (second, "escalated")):
        assert call(app, "PATCH", f"/api/v1/runs/{run_id}/cases/{case_id}/review", cookies=verifier,
                    json_body={"review_status": status, "note": "Synthetic note."},
                    headers={"X-CSRF-Token": verifier["cir_csrf"]}).status_code == 200
    assert call(app, "POST", f"/api/v1/runs/{run_id}/cases/{first}/review/outcome", cookies=lead,
                json_body={"review_outcome": "inconclusive", "note": None},
                headers={"X-CSRF-Token": lead["cir_csrf"]}).status_code == 200
    assert call(app, "POST", f"/api/v1/runs/{run_id}/cases/{first}/review/audit-confirmation", cookies=lead,
                json_body={"audit_result": "confirmed_no_issue", "audit_reference": "AUD-SYN-01", "note": None},
                headers={"X-CSRF-Token": lead["cir_csrf"]}).status_code == 200
    # Validation history and a job left running by a stopped process.
    from app.services.source_validations import record_validation
    from app.services.validation_jobs import _connect as jobs_connect
    record_validation(batch_db, "f" * 64, {"status": "passed", "errors": [], "warnings": [], "scan": None, "checks": []})
    connection = jobs_connect(batch_db)
    with connection:
        connection.execute("INSERT INTO fkrtl_validation_jobs(job_id,fingerprint,status,requested_at,started_at,owner,heartbeat_at) "
                           "VALUES ('vjob_left_running','f',  'running', ?, ?, 'old-host:1:x', ?)",
                           (datetime.now(timezone.utc).isoformat(),) * 3)
    connection.close()
    # Legacy analytics review workflow (its own SQLite file).
    from app.services.reviews import ReviewStore
    legacy_reviews = ReviewStore(tmp_path / "review.sqlite3")
    legacy_reviews.update_review("syn-claim-000001", "needs_more_evidence", "Synthetic.", "usr_test", "Verifikator")
    legacy_reviews.update_review("syn-claim-000001", "escalated", None, "usr_test", "Verifikator")
    views = {run_id: _views(app, verifier, run_id), legacy_run: _views(app, verifier, legacy_run),
             "legacy_review": legacy_reviews.get_review("syn-claim-000001")}
    sources = {"batch": batch_db, "auth": tmp_path / "auth.sqlite3", "review": tmp_path / "review.sqlite3"}
    return app, users, sources, (run_id, legacy_run), views


def _comparable(views):
    """Drop what legitimately differs: request ids and server-side cache/manifest fields stay equal."""
    return json.loads(json.dumps(views, sort_keys=True))


def test_migration_preserves_every_view_and_is_idempotent(tmp_path, monkeypatch):
    with sqlite_mode():
        app_sqlite, users, sources, (run_id, legacy_run), expected = _build_sqlite_source(tmp_path, monkeypatch)
        digests_before = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sources.items()}
    report = migrate(sources)
    assert report["verification"]["ok"] is True
    assert report["verification"]["result_json_sha256_mismatches"] == 0
    assert report["tables"]["analysis_runs"]["inserted"] == 2
    assert report["tables"]["run_case_review_events"]["inserted"] == 3
    assert report["skipped"] == {"auth_sessions": "sessions are not migrated; users sign in again"}
    assert {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sources.items()} == digests_before

    from app.main import create_app
    app = create_app(tmp_path / "ignored-review.sqlite3", tmp_path / "ignored-auth.sqlite3", cookie_secure=False,
                     batch_db_path=tmp_path / "ignored-batch.sqlite3")
    verifier = login(app, users["verifier"]["username"], PASSWORDS["verifier"])  # sessions were not copied
    for migrated_run in (run_id, legacy_run):
        actual = _views(app, verifier, migrated_run)
        assert _comparable(actual) == _comparable(expected[migrated_run]), migrated_run
    assert not (tmp_path / "ignored-batch.sqlite3").exists()  # PostgreSQL is the only operational database
    from app.services.reviews import ReviewStore
    assert ReviewStore(tmp_path / "ignored-review.sqlite3").get_review("syn-claim-000001") == expected["legacy_review"]
    assert report["tables"]["review_history"]["inserted"] == 2

    # Running again inserts nothing and still verifies; a verify-only pass agrees.
    again = migrate(sources)
    assert all(table.get("inserted", 0) == 0 for table in again["tables"].values())
    assert migrate(sources, verify_only=True)["verification"]["ok"] is True
    with db_connection(tmp_path / "x") as connection:
        assert connection.execute("SELECT COUNT(*) FROM data_migration_runs").fetchone()[0] == 2
        job = connection.execute("SELECT status, error_code, fingerprint, owner FROM fkrtl_validation_jobs "
                                 "WHERE job_id='vjob_left_running'").fetchone()
        assert tuple(job) == ("failed", "FKRTL_VALIDATION_INTERRUPTED", None, None)
        assert connection.execute("SELECT COUNT(*) FROM fkrtl_source_validations WHERE fingerprint IS NOT NULL").fetchone()[0] == 0
        # None of the source sessions exist in the target (the only session is the login above).
        migrated_sessions = {row[0] for row in connection.execute("SELECT session_id FROM auth_sessions")}
    with sqlite3.connect(sources["auth"]) as source:
        source_sessions = {row[0] for row in source.execute("SELECT session_id FROM auth_sessions")}
    assert source_sessions and not (source_sessions & migrated_sessions)
    with db_connection(tmp_path / "x") as connection:
        assert connection.execute("SELECT COUNT(*) FROM auth_users").fetchone()[0] == len(users) + 1

    # The run without per-case rows is backfilled on PostgreSQL without changing its result.
    from scripts.backfill_run_case_rows import backfill
    with db_connection(tmp_path / "x") as connection:
        before = connection.execute("SELECT result_json FROM analysis_run_results WHERE run_id=?", (legacy_run,)).fetchone()[0]
    assert backfill(tmp_path / "x")["backfilled"] == 1
    with db_connection(tmp_path / "x") as connection:
        assert connection.execute("SELECT result_json FROM analysis_run_results WHERE run_id=?", (legacy_run,)).fetchone()[0] == before
    assert _comparable(_views(app, verifier, legacy_run)) == _comparable(expected[legacy_run])


def test_conflicting_target_rows_abort_without_writing_anything(tmp_path, monkeypatch):
    with sqlite_mode():
        _app, _users, sources, _runs, _views_ = _build_sqlite_source(tmp_path, monkeypatch)
    migrate(sources)
    with db_connection(tmp_path / "x") as connection:
        connection.execute("UPDATE run_case_reviews SET note='changed after cutover'")
        logged = connection.execute("SELECT COUNT(*) FROM data_migration_runs").fetchone()[0]
    with pytest.raises(MigrationError, match="run_case_reviews"):
        migrate(sources)
    with db_connection(tmp_path / "x") as connection:
        assert connection.execute("SELECT COUNT(*) FROM data_migration_runs").fetchone()[0] == logged


def test_dry_run_writes_nothing_and_unmigrated_schema_is_refused(tmp_path, monkeypatch):
    with sqlite_mode():
        _app, _users, sources, _runs, _views_ = _build_sqlite_source(tmp_path, monkeypatch)
    report = migrate(sources, dry_run=True)
    assert report["verification"]["ok"] is True and report["tables"]["analysis_runs"]["inserted"] == 2
    with db_connection(tmp_path / "x") as connection:
        assert connection.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM data_migration_runs").fetchone()[0] == 0
        connection.execute("DELETE FROM schema_migrations WHERE version='0003_data_migration_log'")
    with pytest.raises(MigrationError, match="db_migrate"):
        migrate(sources)


def test_fkrtl_batch_records_are_refused_as_raw_data(tmp_path):
    source = tmp_path / "with-raw.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.executescript("""
            CREATE TABLE data_batches (batch_id TEXT PRIMARY KEY, source_type TEXT, status TEXT);
            CREATE TABLE data_batch_records (batch_id TEXT, claim_id TEXT, case_id TEXT, record_json TEXT);
            INSERT INTO data_batches VALUES ('bat_fkrtl', 'bpjs_fkrtl_local', 'ready');
            INSERT INTO data_batch_records VALUES ('bat_fkrtl', 'x', 'case_x', '{}');
        """)
    with pytest.raises(MigrationError, match="FKRTL"):
        migrate({"batch": source, "auth": None, "review": None})
