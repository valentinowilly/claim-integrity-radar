"""Run-scoped review API tests with isolated persisted synthetic run snapshots."""

import asyncio
import json
import sqlite3

import httpx
import pytest

from app.main import create_app
from app.security.auth import AuthStore
from app.services.reviews import ReviewStore


def call(app, method, path, *, cookies=None, payload=None, csrf=True):
    async def send():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        headers = {}
        if method not in {"GET", "HEAD"} and csrf and cookies:
            headers["X-CSRF-Token"] = cookies["cir_csrf"]
        return await httpx.AsyncClient(transport=transport, base_url="http://test").request(
            method, path, cookies=cookies, json=payload, headers=headers,
        )
    return asyncio.run(send())


@pytest.fixture
def review_env(tmp_path):
    run_db = tmp_path / "batch-runs.sqlite3"
    auth_db = tmp_path / "auth.sqlite3"
    result = {
        "data_source": {"kind": "synthetic", "label": "synthetic_data_batch"},
        "cases": {"case-shared": {"case_id": "case-shared", "risk_score": None}},
    }
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
        for run_id, status, available in (
            ("run-a", "completed", 1), ("run-b", "partial", 1), ("run-failed", "failed", 0),
        ):
            connection.execute("INSERT INTO analysis_runs VALUES (?,?,?)", (run_id, status, available))
            if available:
                connection.execute("INSERT INTO analysis_run_results VALUES (?,?)",
                                   (run_id, json.dumps(result, sort_keys=True)))
    app = create_app(review_db_path=tmp_path / "legacy-review.sqlite3", auth_db_path=auth_db,
                     cookie_secure=False, batch_db_path=run_db)
    store = AuthStore(auth_db)
    users = {}
    for key, username, role in (
        ("verifier", "synthetic-verifier", "verifikator"),
        ("lead", "synthetic-audit-lead", "audit_lead"),
        ("verifier2", "synthetic-verifier-two", "verifikator"),
    ):
        user = store.create_user(username, "Synthetic-review-password-2026!", role, "test-setup")
        session, token = store.authenticate(username, "Synthetic-review-password-2026!")
        users[key] = (user, {"cir_session": token, "cir_csrf": session["csrf_token"]})
    return app, run_db, auth_db, users


def review_url(run_id="run-a", case_id="case-shared"):
    return f"/api/v1/runs/{run_id}/cases/{case_id}/review"


def test_get_is_read_only_and_returns_pending_for_valid_run_case(review_env):
    app, db, _, users = review_env
    cookies = users["verifier"][1]
    first = call(app, "GET", review_url(), cookies=cookies)
    second = call(app, "GET", review_url(), cookies=cookies)
    assert first.status_code == second.status_code == 200
    assert first.json()["review_status"] == "pending_review"
    assert first.json()["review_outcome"] is None
    assert first.json()["review_id"] is None
    assert first.json()["history"] == []
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM run_case_reviews").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM run_case_review_events").fetchone()[0] == 0


def test_status_updates_append_events_and_persist_across_app_reinitialization(review_env, tmp_path):
    app, db, auth_db, users = review_env
    cookies = users["verifier"][1]
    path = review_url()
    first = call(app, "PATCH", path, cookies=cookies,
                 payload={"review_status": "in_review", "note": "Tinjau pola sintetik."})
    second = call(app, "PATCH", path, cookies=cookies,
                  payload={"review_status": "awaiting_evidence", "note": "Minta bukti sintetis."})
    assert first.status_code == second.status_code == 200
    assert second.json()["review_status"] == "awaiting_evidence"
    assert second.json()["review_outcome"] is None
    history = second.json()["history"]
    assert len(history) == 2
    assert history[0]["previous_status"] == "pending_review"
    assert history[1]["previous_status"] == "in_review"
    assert all(event["actor_user_id"] == users["verifier"][0]["user_id"] for event in history)
    reopened = create_app(review_db_path=tmp_path / "legacy-review.sqlite3", auth_db_path=auth_db,
                          cookie_secure=False, batch_db_path=db)
    loaded = call(reopened, "GET", path, cookies=cookies)
    assert loaded.status_code == 200
    assert loaded.json()["history"] == history


def test_same_case_in_different_runs_has_independent_review(review_env):
    app, _, _, users = review_env
    cookies = users["verifier"][1]
    changed = call(app, "PATCH", review_url("run-a"), cookies=cookies,
                   payload={"review_status": "closed", "note": None})
    other = call(app, "GET", review_url("run-b"), cookies=cookies)
    assert changed.status_code == other.status_code == 200
    assert changed.json()["review_status"] == "closed"
    assert other.json()["review_status"] == "pending_review"
    assert other.json()["history"] == []


def test_outcome_is_separate_and_audit_lead_only(review_env):
    app, _, _, users = review_env
    verifier = users["verifier"][1]
    lead = users["lead"][1]
    denied = call(app, "POST", review_url() + "/outcome", cookies=verifier,
                  payload={"review_outcome": "signal_supported", "note": "Sintetis."})
    assert denied.status_code == 403
    assert call(app, "GET", review_url(), cookies=verifier).json()["review_outcome"] is None
    recorded = call(app, "POST", review_url() + "/outcome", cookies=lead,
                    payload={"review_outcome": "signal_not_supported", "note": "Fixture sintetis."})
    assert recorded.status_code == 200
    body = recorded.json()
    assert body["review_status"] == "pending_review"
    assert body["review_outcome"] == "signal_not_supported"
    assert body["history"][0]["event_type"] == "outcome_recorded"
    assert body["history"][0]["previous_outcome"] is None
    assert body["history"][0]["new_outcome"] == "signal_not_supported"
    assert body["history"][0]["actor_user_id"] == users["lead"][0]["user_id"]
    changed = call(app, "POST", review_url() + "/outcome", cookies=lead,
                   payload={"review_outcome": "inconclusive", "note": "Masih belum cukup."})
    assert changed.status_code == 200
    assert changed.json()["review_status"] == "pending_review"
    assert changed.json()["review_outcome"] == "inconclusive"
    assert len(changed.json()["history"]) == 2
    assert changed.json()["history"][1]["event_type"] == "outcome_changed"
    assert changed.json()["history"][1]["previous_outcome"] == "signal_not_supported"


def test_platform_admin_can_manage_synthetic_run_scoped_review(review_env):
    app, _, _, users = review_env
    admin_store = AuthStore(app.state.auth_db_path)
    admin = admin_store.create_bootstrap_admin(
        "synthetic-full-admin", "Synthetic-admin-password-2026!", "stage23-secret", "stage23-secret",
    )
    session, token = admin_store.authenticate(admin["username"], "Synthetic-admin-password-2026!")
    cookies = {"cir_session": token, "cir_csrf": session["csrf_token"]}
    path = review_url()

    assert call(app, "GET", path).status_code == 401
    assert call(app, "PATCH", path, cookies=cookies, csrf=False,
                payload={"review_status": "in_review"}).status_code == 403
    assert call(app, "POST", path + "/outcome", cookies=cookies, csrf=False,
                payload={"review_outcome": "signal_supported"}).status_code == 403
    assert call(app, "GET", path, cookies=cookies).status_code == 200
    status = call(app, "PATCH", path, cookies=cookies,
                  payload={"review_status": "in_review", "note": "Synthetic admin workflow."})
    assert status.status_code == 200
    outcome = call(app, "POST", path + "/outcome", cookies=cookies,
                   payload={"review_outcome": "signal_supported", "note": "Synthetic review only."})
    assert outcome.status_code == 200
    assert outcome.json()["review_status"] == "in_review"
    assert outcome.json()["review_outcome"] == "signal_supported"
    assert len(outcome.json()["history"]) == 2
    assert all(event["actor_user_id"] == admin["user_id"] for event in outcome.json()["history"])


@pytest.mark.parametrize("method,path,payload", [
    ("PATCH", review_url(), {"review_status": "closed", "actor_user_id": "forged"}),
    ("PATCH", review_url(), {"review_status": "closed", "review_outcome": "signal_supported"}),
    ("POST", review_url() + "/outcome", {"review_outcome": "fraud_confirmed"}),
    ("POST", review_url() + "/outcome", {"review_outcome": "inconclusive", "role": "audit_lead"}),
])
def test_unknown_or_forged_fields_are_rejected(review_env, method, path, payload):
    app, _, _, users = review_env
    cookies = users["lead"][1] if path.endswith("outcome") else users["verifier"][1]
    response = call(app, method, path, cookies=cookies, payload=payload)
    assert response.status_code == 422
    assert "forged" not in response.text
    assert "fraud_confirmed" not in response.text


def test_missing_invalid_and_cross_session_csrf_are_denied(review_env):
    app, _, _, users = review_env
    own = users["verifier"][1]
    other = users["verifier2"][1]
    path = review_url()
    missing = call(app, "PATCH", path, cookies={"cir_session": own["cir_session"]},
                   payload={"review_status": "in_review"}, csrf=False)
    invalid = call(app, "PATCH", path, cookies={**own, "cir_csrf": "wrong-token"},
                   payload={"review_status": "in_review"})
    crossed = call(app, "PATCH", path, cookies={"cir_session": own["cir_session"],
                   "cir_csrf": other["cir_csrf"]}, payload={"review_status": "in_review"})
    assert [missing.status_code, invalid.status_code, crossed.status_code] == [403, 403, 403]


def test_unknown_run_case_and_unreviewable_run_are_rejected(review_env):
    app, _, _, users = review_env
    cookies = users["verifier"][1]
    for path in (review_url("missing-run"), review_url("run-a", "other-case")):
        response = call(app, "GET", path, cookies=cookies)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RUN_CASE_REVIEW_NOT_FOUND"
    failed = call(app, "GET", review_url("run-failed"), cookies=cookies)
    assert failed.status_code == 409
    assert failed.json()["error"]["code"] == "RUN_NOT_REVIEWABLE"


def test_run_result_is_unchanged_and_security_events_are_separate(review_env):
    app, db, _, users = review_env
    cookies = users["lead"][1]
    with sqlite3.connect(db) as connection:
        before = connection.execute("SELECT result_json FROM analysis_run_results WHERE run_id='run-a'").fetchone()[0]
    call(app, "PATCH", review_url(), cookies=cookies, payload={"review_status": "escalated", "note": "Synthetic"})
    call(app, "POST", review_url() + "/outcome", cookies=cookies,
         payload={"review_outcome": "inconclusive", "note": "Synthetic review"})
    with sqlite3.connect(db) as connection:
        after = connection.execute("SELECT result_json FROM analysis_run_results WHERE run_id='run-a'").fetchone()[0]
        history_count = connection.execute("SELECT COUNT(*) FROM run_case_review_events").fetchone()[0]
        security = connection.execute("SELECT event_type FROM run_review_security_audit_events ORDER BY rowid").fetchall()
    assert before == after
    assert history_count == 2
    assert [row[0] for row in security] == ["run_review_status_changed", "run_review_outcome_changed"]
    assert "participant_token" not in json.loads(after)
    with sqlite3.connect(db) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE run_case_review_events SET note='rewritten' WHERE event_type='status_changed'")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM run_case_review_events WHERE event_type='status_changed'")


def test_legacy_not_substantiated_status_is_not_migrated_into_run_outcome(review_env):
    app, _, _, users = review_env
    legacy_db = app.state.review_db_path
    ReviewStore(legacy_db).update_review(
        "case-shared", "not_substantiated", "Legacy-only synthetic note.",
        users["verifier"][0]["user_id"], "synthetic-verifier",
    )
    legacy = ReviewStore(legacy_db).get_review("case-shared")
    run_scoped = call(app, "GET", review_url(), cookies=users["verifier"][1])
    assert legacy["status"] == "not_substantiated"
    assert len(legacy["history"]) == 1
    assert run_scoped.status_code == 200
    assert run_scoped.json()["review_status"] == "pending_review"
    assert run_scoped.json()["review_outcome"] is None
    assert run_scoped.json()["history"] == []


def test_note_limit_and_response_minimization(review_env):
    app, _, _, users = review_env
    cookies = users["verifier"][1]
    too_long = call(app, "PATCH", review_url(), cookies=cookies,
                    payload={"review_status": "in_review", "note": "x" * 1001})
    assert too_long.status_code == 422
    unsafe = call(app, "PATCH", review_url(), cookies=cookies,
                  payload={"review_status": "in_review", "note": "participant_token: demo-secret"})
    assert unsafe.status_code == 422
    assert "demo-secret" not in unsafe.text
    saved = call(app, "PATCH", review_url(), cookies=cookies,
                 payload={"review_status": "in_review", "note": "Synthetic note only."})
    body = saved.text.lower()
    assert saved.status_code == 200
    for forbidden in ("participant_token", "pstV01", "signature", "ground_truth", "password_hash"):
        assert forbidden.lower() not in body
