"""Background FKRTL validation jobs: states, progress, run gate, failures and restarts (synthetic fixtures)."""

import sqlite3
import threading

import pytest

from app.api.routes import sources as sources_routes
from app.services.validation_jobs import wait_for_validation_jobs
from tests.test_analysis_runs import call, operator_session
from tests.test_fkrtl_validation import URL, create_fkrtl_run, env, full_row, validate, write  # noqa: F401


def _post(app, operator):
    return call(app, "POST", URL, cookies=operator, headers={"X-CSRF-Token": operator["cir_csrf"]})


def _held_validation(monkeypatch):
    """Replace the scan with one that reports progress and waits until released."""
    real = sources_routes.validate_fkrtl_local_source
    started, release = threading.Event(), threading.Event()

    def held(progress=None):
        progress(1, 2)
        started.set()
        release.wait(30)
        return real(progress=progress)
    monkeypatch.setattr(sources_routes, "validate_fkrtl_local_source", held)
    return started, release


def test_post_returns_at_once_and_the_job_reports_progress_then_the_outcome(tmp_path, env, monkeypatch):
    app, users, use = env
    use(write(tmp_path, [full_row(), full_row(FKL02="synvisit-a2")]))
    operator = operator_session(app, users)
    started, release = _held_validation(monkeypatch)
    import app.services.validation_jobs as jobs
    monkeypatch.setattr(jobs, "_PROGRESS_INTERVAL_ROWS", 1)  # store every progress report
    response = _post(app, operator)
    assert response.status_code == 202
    assert response.json()["job"]["status"] in ("pending", "running") and response.json()["state"] == "not_validated"
    assert started.wait(10)
    running = call(app, "GET", URL, cookies=operator).json()
    assert running["phase"] == "running" and running["job"]["status"] == "running"
    assert (running["job"]["rows_scanned"], running["job"]["rows_total"]) == (1, 2)
    # A second request while the job runs returns the same job instead of starting another scan.
    again = _post(app, operator).json()
    assert again["job"]["job_id"] == running["job"]["job_id"]
    blocked = create_fkrtl_run(app, operator)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "FKRTL_SOURCE_VALIDATION_IN_PROGRESS"
    release.set()
    wait_for_validation_jobs()
    done = call(app, "GET", URL, cookies=operator).json()
    assert done["job"]["status"] == "completed" and done["job"]["rows_scanned"] == 2
    assert done["phase"] == "passed" and done["current"] is True
    assert create_fkrtl_run(app, operator).status_code == 201


def test_a_failed_newer_job_blocks_runs_even_after_an_earlier_pass(tmp_path, env, monkeypatch):
    app, users, use = env
    use(write(tmp_path, [full_row(), full_row(FKL02="synvisit-a2")]))
    _state, operator = validate(app, users)

    def broken(progress=None):
        raise RuntimeError("unexpected failure /private/location secret-value")
    real = sources_routes.validate_fkrtl_local_source
    monkeypatch.setattr(sources_routes, "validate_fkrtl_local_source", broken)
    assert _post(app, operator).status_code == 202
    wait_for_validation_jobs()
    state = call(app, "GET", URL, cookies=operator)
    body = state.json()
    assert body["job"]["status"] == "failed" and body["job"]["error_code"] == "FKRTL_VALIDATION_JOB_FAILED"
    assert body["phase"] == "failed" and body["report"]["status"] == "passed"  # the earlier report is still shown
    assert "private" not in state.text and "secret-value" not in state.text
    blocked = create_fkrtl_run(app, operator)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "FKRTL_SOURCE_VALIDATION_FAILED"
    # Validating again (successfully) unblocks the run.
    monkeypatch.setattr(sources_routes, "validate_fkrtl_local_source", real)
    _state, operator = validate(app, users)
    assert create_fkrtl_run(app, operator).status_code == 201


def _insert_job(database, job_id, heartbeat_at, owner="other-host:4242:abcd"):
    """A job row written by another worker process (through the configured backend)."""
    from app.services.validation_jobs import _connect

    connection = _connect(database)
    try:
        with connection:
            connection.execute(
                "INSERT INTO fkrtl_validation_jobs(job_id,fingerprint,status,requested_at,started_at,owner,heartbeat_at) "
                "VALUES (?,?,?,?,?,?,?)", (job_id, None, "running", heartbeat_at, heartbeat_at, owner, heartbeat_at))
    finally:
        connection.close()


def test_a_job_whose_worker_stopped_is_marked_interrupted_at_startup(tmp_path, env):
    from app.main import create_app

    app, users, use = env
    use(write(tmp_path, [full_row(), full_row(FKL02="synvisit-a2")]))
    database = tmp_path / "batch-and-runs.sqlite3"
    _insert_job(database, "vjob_orphan", "2000-01-01T00:00:00+00:00")  # heartbeat stopped long ago
    restarted = create_app(tmp_path / "review.sqlite3", tmp_path / "auth.sqlite3", cookie_secure=False,
                           batch_db_path=database)
    operator = operator_session(restarted, users)
    state = call(restarted, "GET", URL, cookies=operator).json()
    assert state["job"]["status"] == "failed" and state["job"]["error_code"] == "FKRTL_VALIDATION_INTERRUPTED"
    assert create_fkrtl_run(restarted, operator).json()["error"]["code"] == "FKRTL_SOURCE_VALIDATION_FAILED"


def test_a_live_job_of_another_worker_survives_startup_and_blocks_a_second_job(tmp_path, env):
    from datetime import datetime, timezone

    from app.main import create_app

    app, users, use = env
    use(write(tmp_path, [full_row(), full_row(FKL02="synvisit-a2")]))
    database = tmp_path / "batch-and-runs.sqlite3"
    _insert_job(database, "vjob_live_elsewhere", datetime.now(timezone.utc).isoformat())
    restarted = create_app(tmp_path / "review.sqlite3", tmp_path / "auth.sqlite3", cookie_secure=False,
                           batch_db_path=database)
    operator = operator_session(restarted, users)
    state = call(restarted, "GET", URL, cookies=operator).json()
    assert state["job"]["job_id"] == "vjob_live_elsewhere" and state["job"]["status"] == "running"
    again = _post(restarted, operator).json()
    assert again["job"]["job_id"] == "vjob_live_elsewhere"  # no second scan started here
    blocked = create_fkrtl_run(restarted, operator)
    assert blocked.json()["error"]["code"] == "FKRTL_SOURCE_VALIDATION_IN_PROGRESS"


def test_the_report_stays_bound_to_the_fingerprint_taken_when_the_job_was_requested(tmp_path, env, monkeypatch):
    app, users, use = env
    use(write(tmp_path, [full_row(), full_row(FKL02="synvisit-a2")]))
    operator = operator_session(app, users)
    started, release = _held_validation(monkeypatch)
    assert _post(app, operator).status_code == 202
    assert started.wait(10)
    monkeypatch.setenv("BPJS_FKRTL_DATE_TO", "2024-03-30")  # configuration changes during the scan
    release.set()
    wait_for_validation_jobs()
    state = call(app, "GET", URL, cookies=operator).json()
    assert state["job"]["status"] == "completed" and state["current"] is False and state["phase"] == "stale"
    blocked = create_fkrtl_run(app, operator)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "FKRTL_SOURCE_VALIDATION_STALE"


def test_failed_report_is_a_completed_job_with_a_failed_phase(tmp_path, env):
    app, users, use = env
    use(write(tmp_path, [full_row(), full_row()]))  # duplicate visit reference
    state, operator = validate(app, users)
    assert state["job"]["status"] == "completed" and state["phase"] == "failed"
    assert create_fkrtl_run(app, operator).json()["error"]["code"] == "FKRTL_SOURCE_VALIDATION_FAILED"


@pytest.mark.parametrize("phase_source", ["passed_with_warnings"])
def test_warning_phase_allows_the_run(tmp_path, env, phase_source):
    app, users, use = env
    use(write(tmp_path, [full_row(FKL30=""), full_row(FKL02="synvisit-a2")]))  # blank procedure warns
    state, operator = validate(app, users)
    assert state["phase"] == phase_source
    assert create_fkrtl_run(app, operator).status_code == 201
