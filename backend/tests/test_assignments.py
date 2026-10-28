"""Light work sharing: one reviewer takes a claim; others see who holds it and cannot take it over."""

from app.security.auth import AuthStore
from tests.db_helpers import db_connection
from tests.test_analysis_runs import call, create_run, import_batch, operator_session, setup, verifier_session

PASSWORD = "Synthetic-second-reviewer-2026!"


def _second_reviewer(app, tmp_path, users):
    store = AuthStore(tmp_path / "auth.sqlite3")
    store.create_user("synthetic-reviewer-two", PASSWORD, "verifikator", users["verifier"]["user_id"])
    response = call(app, "POST", "/api/v1/auth/login", json_body={"username": "synthetic-reviewer-two", "password": PASSWORD})
    return dict(response.cookies.items())


def _assign(app, cookies, run_id, case_id, action):
    return call(app, "POST", f"/api/v1/runs/{run_id}/cases/{case_id}/assignment", cookies=cookies,
                json_body={"action": action}, headers={"X-CSRF-Token": cookies["cir_csrf"]})


def _queue(app, cookies, run_id, assigned):
    response = call(app, "GET", f"/api/v1/runs/{run_id}/cases?limit=100&assigned={assigned}", cookies=cookies)
    assert response.status_code == 200, response.text
    return {item["case"]["case_id"] for item in response.json()["items"]}


def test_a_taken_claim_is_mine_and_others_cannot_take_or_release_it(tmp_path):
    app, batch_db, users = setup(tmp_path)
    operator, verifier = operator_session(app, users), verifier_session(app, users)
    other = _second_reviewer(app, tmp_path, users)
    batch, _generated = import_batch(app, batch_db, operator)
    run_id = create_run(app, operator, batch["batch_id"]).json()["run"]["run_id"]
    every = _queue(app, verifier, run_id, "none")
    case_id = sorted(every)[0]

    taken = _assign(app, verifier, run_id, case_id, "take")
    assert taken.status_code == 200 and taken.json()["assignment"]["is_me"] is True
    assert _queue(app, verifier, run_id, "me") == {case_id}
    assert case_id not in _queue(app, verifier, run_id, "none") and len(_queue(app, verifier, run_id, "none")) == len(every) - 1
    seen = call(app, "GET", f"/api/v1/runs/{run_id}/assignments", cookies=other).json()["items"][case_id]
    assert seen["username"] == "synthetic-verifier" and seen["is_me"] is False

    refused = _assign(app, other, run_id, case_id, "take")
    assert refused.status_code == 409 and "synthetic-verifier" in refused.json()["error"]["message"]
    assert _assign(app, other, run_id, case_id, "release").status_code == 409
    assert _assign(app, operator, run_id, case_id, "take").status_code == 403         # data operators do not review
    assert _assign(app, verifier, run_id, "case-unknown", "take").status_code == 404
    assert call(app, "POST", f"/api/v1/runs/{run_id}/cases/{case_id}/assignment", cookies=verifier,
                json_body={"action": "take"}).status_code == 403                       # no CSRF token

    # The claim stays with its reviewer in the next analysis of the same data.
    next_run = create_run(app, operator, batch["batch_id"]).json()["run"]["run_id"]
    assert _queue(app, verifier, next_run, "me") == {case_id}

    assert _assign(app, verifier, next_run, case_id, "release").json()["assignment"] is None
    assert _assign(app, other, next_run, case_id, "take").json()["assignment"]["username"] == "synthetic-reviewer-two"
    with db_connection(batch_db) as connection:
        events = [row[0] for row in connection.execute(
            "SELECT event_type FROM run_review_security_audit_events WHERE case_id=? ORDER BY occurred_at", (case_id,))]
    assert events == ["case_taken", "case_released", "case_taken"]


def test_assignment_filters_need_review_access(tmp_path):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _generated = import_batch(app, batch_db, operator)
    run_id = create_run(app, operator, batch["batch_id"]).json()["run"]["run_id"]
    verifier = verifier_session(app, users)
    assert call(app, "GET", f"/api/v1/runs/{run_id}/cases?assigned=everyone", cookies=verifier).status_code == 400
    assert call(app, "GET", f"/api/v1/runs/{run_id}/assignments", cookies=operator).status_code == 403
