"""User feedback on claim explanations, questions from the help page, and the administrators' activity history."""

from datetime import datetime, timedelta, timezone

from app.services.feedback import FeedbackStore
from tests.db_helpers import db_connection
from tests.test_analysis_runs import call, create_run, import_batch, login, operator_session, setup, verifier_session

ADMIN = ("root-admin", "Synthetic-admin-password-2026!")


def _post(app, cookies, path, body):
    return call(app, "POST", path, cookies=cookies, json_body=body, headers={"X-CSRF-Token": cookies["cir_csrf"]})


def _run_with_claim(app, batch_db, users):
    operator = operator_session(app, users)
    batch, _generated = import_batch(app, batch_db, operator)
    run_id = create_run(app, operator, batch["batch_id"]).json()["run"]["run_id"]
    verifier = verifier_session(app, users)
    cases = call(app, "GET", f"/api/v1/runs/{run_id}/cases?limit=5", cookies=verifier).json()["items"]
    return operator, verifier, run_id, cases[0]["case"]["case_id"]


def test_one_vote_per_person_per_claim_and_voting_again_replaces_it(tmp_path):
    app, batch_db, users = setup(tmp_path)
    _operator, verifier, run_id, case_id = _run_with_claim(app, batch_db, users)
    path = f"/api/v1/runs/{run_id}/cases/{case_id}/feedback"

    assert call(app, "GET", path, cookies=verifier).json()["mine"] is None
    first = _post(app, verifier, path, {"helpful": True})
    assert first.status_code == 200, first.text
    assert first.json()["mine"]["helpful"] is True and first.json()["mine"]["message"] is None
    again = _post(app, verifier, path, {"helpful": False, "message": "  Alasan   kurang jelas  "})
    assert again.json()["mine"]["helpful"] is False and again.json()["mine"]["message"] == "Alasan kurang jelas"
    assert again.json()["mine"]["feedback_id"] == first.json()["mine"]["feedback_id"]
    assert call(app, "GET", path, cookies=verifier).json()["mine"]["helpful"] is False
    with db_connection(batch_db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM user_feedback").fetchone()[0] == 1
    # The vote belongs to its author; another reviewer starts without a vote.
    lead = verifier_session(app, users, "lead")
    assert call(app, "GET", path, cookies=lead).json()["mine"] is None


def test_claim_votes_are_validated(tmp_path):
    app, batch_db, users = setup(tmp_path)
    _operator, verifier, run_id, case_id = _run_with_claim(app, batch_db, users)
    path = f"/api/v1/runs/{run_id}/cases/{case_id}/feedback"
    assert _post(app, verifier, f"/api/v1/runs/{run_id}/cases/case-unknown/feedback", {"helpful": True}).status_code == 404
    assert _post(app, verifier, path, {"helpful": True, "message": "x" * 501}).status_code == 422
    assert _post(app, verifier, path, {"helpful": True, "rating": 5}).status_code == 422       # unknown field
    assert _post(app, verifier, path, {}).status_code == 422
    assert call(app, "POST", path, cookies=verifier, json_body={"helpful": True}).status_code == 403  # no CSRF token
    assert call(app, "POST", path, json_body={"helpful": True}).status_code == 401


def test_help_questions_and_suggestions(tmp_path):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    sent = _post(app, operator, "/api/v1/feedback", {"context": "help_question", "message": "Bagaimana cara unggah ulang?"})
    assert sent.status_code == 201 and sent.json()["item"]["context"] == "help_question"
    assert _post(app, operator, "/api/v1/feedback", {"context": "general", "message": "   "}).status_code == 422
    assert _post(app, operator, "/api/v1/feedback", {"context": "claim_explanation", "message": "x"}).status_code == 422
    assert _post(app, operator, "/api/v1/feedback", {"context": "general", "message": ""}).status_code == 422


def test_summary_counts_votes_per_role_and_is_limited_to_readers(tmp_path):
    app, batch_db, users = setup(tmp_path)
    operator, verifier, run_id, case_id = _run_with_claim(app, batch_db, users)
    lead = verifier_session(app, users, "lead")
    _post(app, verifier, f"/api/v1/runs/{run_id}/cases/{case_id}/feedback", {"helpful": True})
    _post(app, lead, f"/api/v1/runs/{run_id}/cases/{case_id}/feedback", {"helpful": False, "message": "Tambahkan contoh"})
    _post(app, operator, "/api/v1/feedback", {"context": "general", "message": "Tombol unggah mudah ditemukan"})

    assert call(app, "GET", "/api/v1/feedback/summary", cookies=verifier).status_code == 403
    assert call(app, "GET", "/api/v1/feedback/summary", cookies=operator).status_code == 403
    summary = call(app, "GET", "/api/v1/feedback/summary", cookies=lead)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert (body["votes"], body["helpful"], body["not_helpful"], body["helpful_share"]) == (2, 1, 1, 0.5)
    assert (body["people"], body["questions"], body["suggestions"]) == (3, 0, 1)
    assert {row["role"]: (row["votes"], row["helpful"]) for row in body["by_role"]} == {
        "verifikator": (1, 1), "audit_lead": (1, 0)}
    authors = {item["author"]: item["message"] for item in body["recent_messages"]}
    assert authors == {"synthetic-lead": "Tambahkan contoh", "synthetic-operator": "Tombol unggah mudah ditemukan"}
    assert "user_id" not in body["recent_messages"][0]
    admin = login(app, *ADMIN)
    assert call(app, "GET", "/api/v1/feedback/summary", cookies=admin).status_code == 200


def test_summary_period_leaves_out_older_entries(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.sqlite3")
    store.add_message("general", "user-1", "verifikator", "Masukan lama")
    later = datetime.now(timezone.utc) + timedelta(days=40)
    assert store.summary(days=30, now=later)["suggestions"] == 0
    assert store.summary(days=60, now=later)["suggestions"] == 1
    assert store.summary(days=30)["helpful_share"] is None  # no votes yet


def test_activity_history_merges_the_logs_for_administrators_only(tmp_path):
    app, batch_db, users = setup(tmp_path)
    _operator, verifier, run_id, case_id = _run_with_claim(app, batch_db, users)
    _post(app, verifier, f"/api/v1/runs/{run_id}/cases/{case_id}/assignment", {"action": "take"})
    call(app, "POST", "/api/v1/auth/login", json_body={"username": "synthetic-verifier", "password": "wrong-password-2026!"})

    assert call(app, "GET", "/api/v1/activity", cookies=verifier).status_code == 403
    lead = verifier_session(app, users, "lead")
    assert call(app, "GET", "/api/v1/activity", cookies=lead).status_code == 403
    admin = login(app, *ADMIN)
    response = call(app, "GET", "/api/v1/activity", cookies=admin)
    assert response.status_code == 200, response.text
    body = response.json()
    events = {item["event_type"] for item in body["items"]}
    assert {"login_succeeded", "login_failed", "batch_imported", "analysis_run_created", "analysis_run_completed",
            "case_taken"} <= events
    taken = next(item for item in body["items"] if item["event_type"] == "case_taken")
    assert (taken["actor_name"], taken["actor_kind"], taken["category"]) == ("synthetic-verifier", "user", "tinjauan")
    assert (taken["target_type"], taken["target_id"]) == ("claim", case_id)
    failed = next(item for item in body["items"] if item["event_type"] == "login_failed")
    assert failed["actor_kind"] == "unknown"
    times = [item["occurred_at"] for item in body["items"]]
    assert times == sorted(times, reverse=True)
    assert all("metadata" not in item and "metadata_json" not in item for item in body["items"])
    assert sum(body["counts"].values()) == len(body["items"])

    only_reviews = call(app, "GET", "/api/v1/activity?category=tinjauan", cookies=admin).json()
    assert only_reviews["items"] and {item["category"] for item in only_reviews["items"]} == {"tinjauan"}
    assert only_reviews["counts"] == body["counts"]
    assert len(call(app, "GET", "/api/v1/activity?limit=2", cookies=admin).json()["items"]) == 2
    assert call(app, "GET", "/api/v1/activity?category=semua", cookies=admin).status_code == 422
    assert call(app, "GET", "/api/v1/activity?limit=0", cookies=admin).status_code == 422
