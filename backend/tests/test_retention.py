"""Superseded and old analyses leave the lists (archived, never deleted); deletes stay refused."""

from datetime import timedelta

import pytest

from app.services import retention
from tests.db_helpers import assert_rejected, db_connection  # noqa: F401
from tests.test_analysis_runs import call, create_run, import_batch, operator_session, setup, verifier_session


def _run(app, operator, batch_id):
    created = create_run(app, operator, batch_id)
    assert created.status_code == 201, created.text
    return created.json()["run"]["run_id"]


def _ids(app, cookies, archived=False):
    url = "/api/v1/runs?archived=true" if archived else "/api/v1/runs"
    return {item["run_id"]: item.get("archive_reason") for item in call(app, "GET", url, cookies=cookies).json()["items"]}


def test_a_new_analysis_of_the_same_file_supersedes_the_earlier_one(tmp_path):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _generated = import_batch(app, batch_db, operator)
    first = _run(app, operator, batch["batch_id"])
    second = _run(app, operator, batch["batch_id"])
    assert set(_ids(app, operator)) == {second}
    assert _ids(app, operator, archived=True) == {first: "superseded"}


def test_old_analyses_are_archived_once_and_a_restored_one_stays(tmp_path):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _generated = import_batch(app, batch_db, operator)
    run_id = _run(app, operator, batch["batch_id"])
    later = retention.utc_now() + timedelta(days=retention.active_days() + 1)
    assert retention.sweep(batch_db, now=later)["archived"] == 1
    assert _ids(app, operator, archived=True) == {run_id: "older"}
    assert call(app, "DELETE", f"/api/v1/runs/{run_id}/archive", cookies=operator,
                headers={"X-CSRF-Token": operator["cir_csrf"]}).status_code == 204
    assert retention.sweep(batch_db, now=later)["archived"] == 0
    assert run_id in _ids(app, operator)


def test_stored_results_and_ready_files_can_never_be_deleted(tmp_path):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _generated = import_batch(app, batch_db, operator)
    run_id = _run(app, operator, batch["batch_id"])
    retention.sweep(batch_db, now=retention.utc_now() + timedelta(days=400))   # archived, not deleted
    for statement, value in (("DELETE FROM analysis_run_cases WHERE run_id=?", run_id),
                             ("DELETE FROM analysis_run_results WHERE run_id=?", run_id),
                             ("DELETE FROM analysis_runs WHERE run_id=?", run_id),
                             ("DELETE FROM data_batch_records WHERE batch_id=?", batch["batch_id"])):
        with db_connection(batch_db) as connection:
            with pytest.raises(Exception):
                connection.execute(statement, (value,))
    assert call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier_session(app, users)).status_code == 200
