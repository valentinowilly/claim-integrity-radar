"""Per-case result rows: same pages as the snapshot, no full-result parse, immutable, legacy fallback."""

import hashlib
import itertools
import sqlite3

import pytest

from app.services import run_results, run_reviews, runs as runs_service
from app.db import connect_operational
from tests.db_helpers import assert_rejected, db_connection, on_postgres, seed_reviewable_runs  # noqa: F401
from tests.test_analysis_runs import call, create_run, import_batch, operator_session, setup, verifier_session


def _run(tmp_path, monkeypatch=None, legacy=False):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _ = import_batch(app, batch_db, operator)
    if legacy:
        # A run stored before per-case rows and the newer sections existed: no rows, and its
        # snapshot lacks ml_anomaly, length_of_stay and result_contract.
        monkeypatch.setattr(runs_service, "write_case_rows", lambda *_args: False)
        monkeypatch.setattr(runs_service, "_compact_snapshot", lambda snapshot: snapshot)
        real_pipeline = runs_service.execute_provider_snapshot

        def without_new_sections(*args, **kwargs):
            outcome, snapshot = real_pipeline(*args, **kwargs)
            for key in ("ml_anomaly", "length_of_stay", "result_contract"):
                snapshot.pop(key, None)
            for case in snapshot["cases"].values():
                case.pop("ml_anomaly", None)
                case.pop("length_of_stay", None)
            return outcome, snapshot
        monkeypatch.setattr(runs_service, "execute_provider_snapshot", without_new_sections)
    created = create_run(app, operator, batch["batch_id"])
    assert created.status_code == 201, created.text
    if legacy:
        monkeypatch.undo()
    return app, users, batch_db, created.json()["run"]["run_id"]


def _forbid_full_parse(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("the full stored result must not be parsed")
    for module in (run_results, runs_service, run_reviews):
        monkeypatch.setattr(module, "stored_result", fail)


def test_new_runs_store_one_row_per_flagged_claim_and_the_summary(tmp_path):
    app, users, batch_db, run_id = _run(tmp_path)
    verifier = verifier_session(app, users)
    full = call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier).json()["result"]
    connection = connect_operational(batch_db, timeout=20)
    rows = connection.execute("SELECT case_id FROM analysis_run_cases WHERE run_id=? ORDER BY position", (run_id,)).fetchall()
    summary = connection.execute("SELECT summary_json, view_version FROM analysis_run_result_views WHERE run_id=?",
                                 (run_id,)).fetchone()
    connection.close()
    assert [row[0] for row in rows] == list(full["cases"])
    assert summary[1] == run_results.VIEW_VERSION
    import json
    assert json.loads(summary[0]) == run_results.summary_view(full)


def test_sql_pages_equal_the_snapshot_reference_for_every_sort_and_filter(tmp_path, monkeypatch):
    app, users, batch_db, run_id = _run(tmp_path)
    verifier = verifier_session(app, users)
    full = call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier).json()["result"]
    case_ids = list(full["cases"])
    for case_id, status in zip(case_ids[:3], ("awaiting_evidence", "in_review", "escalated")):
        assert call(app, "PATCH", f"/api/v1/runs/{run_id}/cases/{case_id}/review", cookies=verifier,
                    json_body={"review_status": status}, headers={"X-CSRF-Token": verifier["cir_csrf"]}).status_code == 200
    lead = verifier_session(app, users, "lead")
    assert call(app, "POST", f"/api/v1/runs/{run_id}/cases/{case_ids[1]}/review/outcome", cookies=lead,
                json_body={"review_outcome": "inconclusive"}, headers={"X-CSRF-Token": lead["cir_csrf"]}).status_code == 200
    reviews = {item["case_id"]: item for item in run_reviews.RunReviewStore(batch_db).list_reviews(run_id)}
    indicators = sorted({code for case in full["cases"].values() for code in case["indicators"]})
    connection = connect_operational(batch_db, timeout=20)
    try:
        for sort, indicator, search, review_filter in itertools.product(
                run_results.SORT_KEYS, [None, *indicators], [None, case_ids[0][-5:].upper()],
                [None, "not_started", "has_outcome", "awaiting_evidence", "pending_review"]):
            for offset in (0, 7):
                query = dict(sort=sort, offset=offset, limit=9, indicator=indicator, search=search,
                             review_filter=review_filter)
                expected = run_results.case_page(full, reviews=reviews, **query)
                actual = run_results.stored_case_page(connection, run_id, reviews_visible=True, **query)
                assert actual == expected, query
    finally:
        connection.close()


def test_reads_of_a_run_with_rows_never_parse_the_full_result(tmp_path, monkeypatch):
    app, users, _batch_db, run_id = _run(tmp_path)
    verifier = verifier_session(app, users)
    first = call(app, "GET", f"/api/v1/runs/{run_id}/cases?limit=1", cookies=verifier).json()["items"][0]["case"]["case_id"]
    run_results._cache.clear()
    _forbid_full_parse(monkeypatch)
    for path in (f"/api/v1/runs/{run_id}?view=summary", f"/api/v1/runs/{run_id}/cases?sort=review_updated",
                 f"/api/v1/runs/{run_id}/cases/{first}", f"/api/v1/runs/{run_id}/cases/{first}/review",
                 f"/api/v1/runs/{run_id}/reviews"):
        assert call(app, "GET", path, cookies=verifier).status_code == 200, path
    saved = call(app, "PATCH", f"/api/v1/runs/{run_id}/cases/{first}/review", cookies=verifier,
                 json_body={"review_status": "in_review"}, headers={"X-CSRF-Token": verifier["cir_csrf"]})
    assert saved.status_code == 200
    assert call(app, "GET", f"/api/v1/runs/{run_id}/cases/case_not_in_run/review", cookies=verifier).status_code == 404
    assert call(app, "GET", f"/api/v1/runs/{run_id}/cases/case_not_in_run", cookies=verifier).status_code == 404
    assert run_results._cache == {}


def test_case_rows_and_summary_are_immutable(tmp_path):
    _app, _users, batch_db, run_id = _run(tmp_path)
    connection = connect_operational(batch_db, timeout=20)
    try:
        for statement in ("UPDATE analysis_run_cases SET case_json='{}' WHERE run_id=?",
                          "DELETE FROM analysis_run_cases WHERE run_id=?",
                          "UPDATE analysis_run_result_views SET summary_json='{}' WHERE run_id=?",
                          "DELETE FROM analysis_run_result_views WHERE run_id=?",
                          "INSERT INTO analysis_run_cases(run_id,position,case_id,case_json,indicators,sort_checks) "
                          "VALUES (?, 99999, 'case_extra', '{}', '||', 0)"):
            assert_rejected(connection, statement, (run_id,))
    finally:
        connection.close()


def test_a_stored_legacy_snapshot_opens_through_every_view_without_change_or_rerun(tmp_path, monkeypatch):
    app, users, batch_db, run_id = _run(tmp_path, monkeypatch, legacy=True)
    connection = connect_operational(batch_db, timeout=20)
    stored_text = connection.execute("SELECT result_json FROM analysis_run_results WHERE run_id=?", (run_id,)).fetchone()[0]
    assert connection.execute("SELECT COUNT(*) FROM analysis_run_cases WHERE run_id=?", (run_id,)).fetchone()[0] == 0
    connection.close()
    for key in ('"ml_anomaly"', '"length_of_stay"', '"result_contract"'):
        assert key not in stored_text

    def fail(*_args, **_kwargs):
        raise AssertionError("opening history must not rerun detection or inference")
    monkeypatch.setattr(runs_service, "execute_provider_snapshot", fail)
    verifier = verifier_session(app, users)
    full = call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier).json()["result"]
    summary = call(app, "GET", f"/api/v1/runs/{run_id}?view=summary", cookies=verifier).json()["result"]
    assert summary["cases"] == {} and summary["result_view"]["case_count"] == len(full["cases"])
    assert "ml_anomaly" not in summary and "length_of_stay" not in summary
    page = call(app, "GET", f"/api/v1/runs/{run_id}/cases?limit=100&sort=ml_rank", cookies=verifier).json()
    assert [item["case"]["case_id"] for item in page["items"]] == sorted(full["cases"])[:100]  # no ranks: by reference
    first = next(iter(full["cases"]))
    scoped = call(app, "GET", f"/api/v1/runs/{run_id}/cases/{first}", cookies=verifier).json()["result"]
    assert scoped["cases"] == {first: full["cases"][first]}
    assert call(app, "GET", f"/api/v1/runs/{run_id}/cases/{first}/review", cookies=verifier).status_code == 200
    connection = connect_operational(batch_db, timeout=20)
    after = connection.execute("SELECT result_json FROM analysis_run_results WHERE run_id=?", (run_id,)).fetchone()[0]
    connection.close()
    assert hashlib.sha256(after.encode()).digest() == hashlib.sha256(stored_text.encode()).digest()


def test_backfill_adds_identical_rows_to_a_legacy_run_once(tmp_path, monkeypatch):
    from scripts.backfill_run_case_rows import backfill

    app, users, batch_db, run_id = _run(tmp_path, monkeypatch, legacy=True)
    verifier = verifier_session(app, users)
    before = {sort: call(app, "GET", f"/api/v1/runs/{run_id}/cases?limit=50&sort={sort}", cookies=verifier).json()
              for sort in run_results.SORT_KEYS}
    summary_before = call(app, "GET", f"/api/v1/runs/{run_id}?view=summary", cookies=verifier).json()["result"]
    connection = connect_operational(batch_db, timeout=20)
    stored_text = connection.execute("SELECT result_json FROM analysis_run_results WHERE run_id=?", (run_id,)).fetchone()[0]
    connection.close()
    assert backfill(batch_db, dry_run=True) == {"runs_with_result": 1, "already_had_rows": 0, "backfilled": 1,
                                                 "without_case_map": 0}
    assert backfill(batch_db) == {"runs_with_result": 1, "already_had_rows": 0, "backfilled": 1, "without_case_map": 0}
    assert backfill(batch_db)["already_had_rows"] == 1  # idempotent
    _forbid_full_parse(monkeypatch)
    run_results._cache.clear()
    for sort, page in before.items():
        assert call(app, "GET", f"/api/v1/runs/{run_id}/cases?limit=50&sort={sort}", cookies=verifier).json() == page
    assert call(app, "GET", f"/api/v1/runs/{run_id}?view=summary", cookies=verifier).json()["result"] == summary_before
    connection = connect_operational(batch_db, timeout=20)
    assert connection.execute("SELECT result_json FROM analysis_run_results WHERE run_id=?", (run_id,)).fetchone()[0] == stored_text
    connection.close()
