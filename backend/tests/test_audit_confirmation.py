"""Authorized audit results: separate from reviewer outcomes, reference required, append-only."""

import sqlite3

import pytest

from app.security.auth import AuthStore
from tests.db_helpers import assert_rejected, db_connection, on_postgres, seed_reviewable_runs  # noqa: F401
from tests.test_run_scoped_reviews import call, review_env, review_url  # noqa: F401 (fixture)

URL = review_url() + "/audit-confirmation"
VALID = {"audit_result": "confirmed_issue", "audit_reference": "AUD-2026/014", "note": "Hasil audit lapangan sintetis."}


def test_audit_result_requires_manage_permission_csrf_and_an_existing_review(review_env):
    app, _db, _auth, users = review_env
    operator, lead = users["operator"][1], users["lead"][1]
    assert call(app, "POST", URL, cookies=operator, payload=VALID).status_code == 403
    assert call(app, "POST", URL, cookies=lead, payload=VALID, csrf=False).status_code == 403
    no_review = call(app, "POST", URL, cookies=lead, payload=VALID)
    assert no_review.status_code == 409
    assert no_review.json()["error"]["code"] == "RUN_AUDIT_CONFIRMATION_REQUIRES_REVIEW"
    assert call(app, "POST", review_url("run-a", "case-unknown") + "/audit-confirmation", cookies=lead, payload=VALID).status_code == 404


def test_reviewer_outcome_never_becomes_an_audit_result_and_confirmation_is_recorded_separately(review_env):
    app, db, _auth, users = review_env
    verifier, lead = users["verifier"][1], users["lead"][1]
    assert call(app, "PATCH", review_url(), cookies=verifier, payload={"review_status": "escalated", "note": None}).status_code == 200
    supported = call(app, "POST", review_url() + "/outcome", cookies=lead, payload={"review_outcome": "signal_supported", "note": None}).json()
    assert supported["review_outcome"] == "signal_supported" and supported["audit_result"] is None
    assert supported["audit_confirmations"] == []

    recorded = call(app, "POST", URL, cookies=lead, payload=VALID)
    assert recorded.status_code == 200, recorded.text
    body = recorded.json()
    assert body["audit_result"] == "confirmed_issue" and body["audit_result_label"]
    assert body["review_status"] == "escalated" and body["review_outcome"] == "signal_supported"
    [entry] = body["audit_confirmations"]
    assert entry["audit_reference"] == "AUD-2026/014" and entry["recorded_by_user_id"] == users["lead"][0]["user_id"]

    later = call(app, "POST", URL, cookies=lead, payload={**VALID, "audit_result": "confirmed_no_issue", "audit_reference": "AUD-2026/015"}).json()
    assert later["audit_result"] == "confirmed_no_issue" and len(later["audit_confirmations"]) == 2
    listed = call(app, "GET", "/api/v1/runs/run-a/reviews", cookies=verifier).json()["items"]
    assert listed[0]["audit_result"] == "confirmed_no_issue"
    with db_connection(db) as connection:
        assert_rejected(connection, "UPDATE run_case_audit_confirmations SET audit_result='confirmed_issue'")
        assert_rejected(connection, "DELETE FROM run_case_audit_confirmations")


@pytest.mark.parametrize("reference", ["", "x", "1234567890123", "AUD 2026", "a" * 70, "<script>"])
def test_audit_reference_must_be_a_short_reference_code(review_env, reference):
    app, _db, _auth, users = review_env
    lead = users["lead"][1]
    call(app, "PATCH", review_url(), cookies=lead, payload={"review_status": "in_review", "note": None})
    response = call(app, "POST", URL, cookies=lead, payload={**VALID, "audit_reference": reference})
    assert response.status_code == 422


def test_audit_note_rejects_identifiers_and_unknown_results(review_env):
    app, _db, _auth, users = review_env
    lead = users["lead"][1]
    call(app, "PATCH", review_url(), cookies=lead, payload={"review_status": "in_review", "note": None})
    assert call(app, "POST", URL, cookies=lead, payload={**VALID, "note": "Peserta 1234567890123 terbukti."}).status_code == 422
    assert call(app, "POST", URL, cookies=lead, payload={**VALID, "audit_result": "fraud"}).status_code == 422
    assert call(app, "POST", URL, cookies=lead, payload={**VALID, "extra": 1}).status_code == 422


@pytest.mark.parametrize("reference", ["1234-5678-9012-3", "0001.2345.6789", "password:hunter2", "secret-token-x",
                                       "bearer-abc", "a3f9c1d2e4b5a6c7d8e9f0a1b2c3d4e5f6a7b8c9"])
def test_audit_reference_rejects_separated_identifiers_secrets_and_tokens(review_env, reference):
    # Found in the closeout security review: these shapes were accepted before the validator was hardened.
    app, _db, _auth, users = review_env
    lead = users["lead"][1]
    call(app, "PATCH", review_url(), cookies=lead, payload={"review_status": "in_review", "note": None})
    assert call(app, "POST", URL, cookies=lead, payload={**VALID, "audit_reference": reference}).status_code == 422


@pytest.mark.parametrize("reference", ["AUD-2026/014", "INSP.2026.07", "BPK:LHP-12/2026"])
def test_audit_reference_accepts_short_reference_codes(review_env, reference):
    app, _db, _auth, users = review_env
    lead = users["lead"][1]
    call(app, "PATCH", review_url(), cookies=lead, payload={"review_status": "in_review", "note": None})
    response = call(app, "POST", URL, cookies=lead, payload={**VALID, "audit_reference": reference})
    assert response.status_code == 200 and response.json()["audit_confirmations"][-1]["audit_reference"] == reference


def test_recorder_cannot_be_impersonated_and_data_operator_cannot_record(review_env):
    app, _db, _auth, users = review_env
    lead, verifier = users["lead"], users["verifier"]
    call(app, "PATCH", review_url(), cookies=lead[1], payload={"review_status": "in_review", "note": None})
    forged = {**VALID, "recorded_by_user_id": verifier[0]["user_id"]}
    assert call(app, "POST", URL, cookies=lead[1], payload=forged).status_code == 422
    assert call(app, "POST", URL, cookies=users["operator"][1], payload=VALID).status_code == 403
    body = call(app, "POST", URL, cookies=lead[1], payload=VALID).json()
    assert {entry["recorded_by_user_id"] for entry in body["audit_confirmations"]} == {lead[0]["user_id"]}


def test_audit_confirmation_rejects_missing_session_crossed_csrf_and_deactivated_account(review_env):
    # Closeout security review: session-identity paths of the audit endpoint were not covered.
    app, _db, auth_db, users = review_env
    lead, verifier = users["lead"], users["verifier"]
    call(app, "PATCH", review_url(), cookies=lead[1], payload={"review_status": "in_review", "note": None})
    assert call(app, "POST", URL, payload=VALID, csrf=False).status_code == 401
    crossed = {"cir_session": lead[1]["cir_session"], "cir_csrf": verifier[1]["cir_csrf"]}
    assert call(app, "POST", URL, cookies=crossed, payload=VALID).status_code == 403
    AuthStore(auth_db).update_user(lead[0]["user_id"], "test-setup", is_active=False)
    assert call(app, "POST", URL, cookies=lead[1], payload=VALID).status_code == 401
    with db_connection(_db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM run_case_audit_confirmations").fetchone()[0] == 0


def test_audit_reference_is_not_readable_without_review_read(review_env):
    # Visibility rationale: audit references are shown only to review:read roles, never to data operators.
    app, _db, auth_db, users = review_env
    lead = users["lead"][1]
    call(app, "PATCH", review_url(), cookies=lead, payload={"review_status": "in_review", "note": None})
    assert call(app, "POST", URL, cookies=lead, payload=VALID).status_code == 200
    store = AuthStore(auth_db)
    store.create_user("synthetic-operator", "Synthetic-review-password-2026!", "data_operator", "test-setup")
    session, token = store.authenticate("synthetic-operator", "Synthetic-review-password-2026!")
    operator = {"cir_session": token, "cir_csrf": session["csrf_token"]}
    for path in (review_url(), "/api/v1/runs/run-a/reviews"):
        response = call(app, "GET", path, cookies=operator)
        assert response.status_code == 403 and "AUD-2026/014" not in response.text
