"""In-app notifications: role filtering, own actions excluded, cursor semantics, no sensitive content."""

from datetime import datetime, timedelta, timezone
import json
from urllib.parse import quote

from app.services.source_validations import record_validation
from app.services.validation_jobs import _connect as jobs_connect
from tests.test_analysis_runs import call, create_run, import_batch, login, operator_session, setup, verifier_session

URL = "/api/v1/notifications"


def _since(minutes: int = 5) -> str:
    """URL-encoded cursor ("+00:00" would otherwise be read as a space)."""
    return quote((datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat())


def _kinds(response) -> list[str]:
    return [item["kind"] for item in response.json()["items"]]


def _scenario(tmp_path):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    since = _since()
    batch, _ = import_batch(app, batch_db, operator)
    run_id = create_run(app, operator, batch["batch_id"]).json()["run"]["run_id"]
    verifier, lead = verifier_session(app, users), verifier_session(app, users, "lead")
    case_id = call(app, "GET", f"/api/v1/runs/{run_id}/cases?limit=1", cookies=verifier).json()["items"][0]["case"]["case_id"]
    review = f"/api/v1/runs/{run_id}/cases/{case_id}/review"
    assert call(app, "PATCH", review, cookies=verifier, json_body={"review_status": "escalated", "note": "Synthetic private remark"},
                headers={"X-CSRF-Token": verifier["cir_csrf"]}).status_code == 200
    assert call(app, "POST", review + "/outcome", cookies=lead, json_body={"review_outcome": "inconclusive", "note": None},
                headers={"X-CSRF-Token": lead["cir_csrf"]}).status_code == 200
    assert call(app, "POST", review + "/audit-confirmation", cookies=lead,
                json_body={"audit_result": "confirmed_no_issue", "audit_reference": "AUD-PRIVATE-77", "note": None},
                headers={"X-CSRF-Token": lead["cir_csrf"]}).status_code == 200
    return app, users, batch_db, run_id, case_id, since, operator, verifier, lead


def test_each_role_sees_only_what_it_may_read_and_not_its_own_actions(tmp_path):
    app, users, _db, run_id, case_id, since, operator, verifier, lead = _scenario(tmp_path)
    as_operator = call(app, "GET", f"{URL}?since={since}", cookies=operator)
    assert as_operator.status_code == 200
    assert _kinds(as_operator) == ["run_finished"]  # operators cannot read reviews
    as_verifier = call(app, "GET", f"{URL}?since={since}", cookies=verifier).json()["items"]
    assert {item["kind"] for item in as_verifier} == {"run_finished", "outcome_recorded", "audit_result_recorded"}
    as_lead = call(app, "GET", f"{URL}?since={since}", cookies=lead).json()["items"]
    assert {item["kind"] for item in as_lead} == {"run_finished", "case_escalated"}  # its own outcome/audit excluded
    escalation = next(item for item in as_lead if item["kind"] == "case_escalated")
    assert (escalation["run_id"], escalation["case_id"], escalation["status"]) == (run_id, case_id, "escalated")
    for body in (as_operator.text, json.dumps(as_verifier), json.dumps(as_lead)):
        assert "Synthetic private remark" not in body and "AUD-PRIVATE-77" not in body and "participant" not in body


def test_cursor_returns_only_newer_events_and_a_missing_cursor_starts_now(tmp_path):
    app, _users, _db, _run, _case, since, _operator, verifier, _lead = _scenario(tmp_path)
    first = call(app, "GET", f"{URL}?since={since}", cookies=verifier).json()
    assert first["items"] and first["next_since"] < first["server_time"]  # overlapping window
    assert call(app, "GET", URL, cookies=verifier).json()["items"] == []  # no cursor: nothing old
    later = quote((datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat())
    assert call(app, "GET", f"{URL}?since={later}", cookies=verifier).json()["items"] == []
    for bad in ("since=yesterday", "limit=0", "limit=51"):
        assert call(app, "GET", f"{URL}?{bad}", cookies=verifier).status_code == 400
    assert call(app, "GET", URL).status_code == 401


def test_validation_jobs_notify_operators_with_the_report_outcome(tmp_path):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    since = _since()
    entry = record_validation(batch_db, None, {"status": "passed_with_warnings", "errors": [], "warnings": [],
                                               "scan": None, "checks": []})
    now = datetime.now(timezone.utc).isoformat()
    connection = jobs_connect(batch_db)
    with connection:
        connection.execute("INSERT INTO fkrtl_validation_jobs(job_id,status,requested_at,finished_at,validation_id) "
                           "VALUES ('vjob_done','completed',?,?,?)", (now, now, entry["validation_id"]))
        connection.execute("INSERT INTO fkrtl_validation_jobs(job_id,status,requested_at,finished_at,error_code) "
                           "VALUES ('vjob_broken','failed',?,?,'FKRTL_VALIDATION_JOB_FAILED')", (now, now))
    connection.close()
    items = call(app, "GET", f"{URL}?since={since}", cookies=operator).json()["items"]
    statuses = {item["id"]: item["status"] for item in items if item["kind"] == "validation_finished"}
    assert statuses == {"validation:vjob_done": "passed_with_warnings", "validation:vjob_broken": "job_failed"}
    verifier = login(app, users["verifier"]["username"], "Synthetic-verifier-password-2026!")
    assert "validation_finished" not in _kinds(call(app, "GET", f"{URL}?since={since}", cookies=verifier))
