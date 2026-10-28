"""Rate limits for login and sensitive review writes, and audit-reference visibility."""

import sqlite3

import pytest

from app.security.auth import AuthStore
from app.security.rate_limit import DEFAULT_RULES, RateLimiter, Rule, configured_rules
from tests.db_helpers import assert_rejected, db_connection, on_postgres, seed_reviewable_runs  # noqa: F401
from tests.test_run_scoped_reviews import call, review_env, review_url  # noqa: F401 (fixture)

AUDIT_URL = review_url() + "/audit-confirmation"
VALID = {"audit_result": "confirmed_issue", "audit_reference": "AUD-2026/014", "note": None}
PASSWORD = "Synthetic-review-password-2026!"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def limited(app, clock, **overrides):
    app.state.rate_limiter = RateLimiter({**DEFAULT_RULES, **overrides}, clock=clock)


def login(app, username, password):
    return call(app, "POST", "/api/v1/auth/login", payload={"username": username, "password": password})


def test_limiter_allows_up_to_the_limit_rejects_excess_and_recovers_after_the_window():
    clock = Clock()
    limiter = RateLimiter({"r": Rule(2, 60)}, clock=clock)
    assert limiter.hit("r", "k") is None and limiter.hit("r", "k") is None
    assert limiter.hit("r", "k") == 60
    assert limiter.hit("r", "other") is None
    clock.now += 30
    assert limiter.hit("r", "k") == 30
    clock.now += 30
    assert limiter.hit("r", "k") is None


def test_limiter_disabled_and_key_count_is_bounded():
    disabled = RateLimiter(None)
    assert all(disabled.hit("r", "k") is None for _ in range(100))
    bounded = RateLimiter({"r": Rule(1, 60)}, max_keys=3)
    for key in "abcde":
        bounded.hit("r", key)
    assert len(bounded._hits) == 3


def test_rules_are_configurable_and_invalid_values_are_rejected(monkeypatch):
    monkeypatch.setenv("CIR_RATE_LIMIT_AUDIT_CONFIRMATION", "3/120")
    assert configured_rules()["audit_confirmation"] == Rule(3, 120)
    monkeypatch.setenv("CIR_RATE_LIMIT_ENABLED", "false")
    assert configured_rules() is None
    monkeypatch.setenv("CIR_RATE_LIMIT_ENABLED", "true")
    for raw in ("3", "0/60", "3/0", "x/60"):
        monkeypatch.setenv("CIR_RATE_LIMIT_AUDIT_CONFIRMATION", raw)
        with pytest.raises(ValueError):
            configured_rules()


def test_failed_logins_for_one_username_are_limited_before_the_password_check(review_env):
    app, _db, _auth, _users = review_env
    clock = Clock()
    limited(app, clock, login_failures=Rule(3, 900))
    for _ in range(3):
        assert login(app, "synthetic-audit-lead", "wrong-password-123").status_code == 401
    blocked = login(app, "synthetic-audit-lead", PASSWORD)
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "900"
    assert blocked.json()["error"]["code"] == "RATE_LIMITED" and PASSWORD not in blocked.text
    assert login(app, "synthetic-verifier", PASSWORD).status_code == 200
    clock.now += 900
    assert login(app, "synthetic-audit-lead", PASSWORD).status_code == 200


def test_successful_login_resets_failures_and_client_address_limit_applies(review_env):
    app, _db, _auth, _users = review_env
    # Four attempts per client address: the fifth is rejected even with a correct password.
    limited(app, Clock(), login_failures=Rule(2, 900), login_ip=Rule(4, 300))
    assert login(app, "synthetic-verifier", "wrong-password-123").status_code == 401
    assert login(app, "synthetic-verifier", PASSWORD).status_code == 200
    assert login(app, "synthetic-verifier", "wrong-password-123").status_code == 401
    assert login(app, "synthetic-verifier", PASSWORD).status_code == 200
    assert login(app, "synthetic-verifier", PASSWORD).status_code == 429


def test_audit_confirmation_is_limited_per_user_and_rejected_requests_store_nothing(review_env):
    app, db, _auth, users = review_env
    clock = Clock()
    limited(app, clock, audit_confirmation=Rule(2, 60))
    lead = users["lead"][1]
    call(app, "PATCH", review_url(), cookies=lead, payload={"review_status": "in_review", "note": None})
    assert [call(app, "POST", AUDIT_URL, cookies=lead, payload=VALID).status_code for _ in range(2)] == [200, 200]
    rejected = call(app, "POST", AUDIT_URL, cookies=lead, payload=VALID)
    assert rejected.status_code == 429 and rejected.headers["retry-after"] == "60"
    assert "AUD-2026/014" not in rejected.text
    with db_connection(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM run_case_audit_confirmations").fetchone()[0] == 2
    # A data operator is refused by permission before the limit, so it never consumes or reaches the quota.
    assert call(app, "POST", AUDIT_URL, cookies=users["operator"][1], payload=VALID).status_code == 403
    clock.now += 60
    assert call(app, "POST", AUDIT_URL, cookies=lead, payload=VALID).status_code == 200


def test_review_writes_are_limited_per_user(review_env):
    app, _db, _auth, users = review_env
    limited(app, Clock(), review_write=Rule(2, 60))
    verifier, other = users["verifier"][1], users["verifier2"][1]
    status = {"review_status": "in_review", "note": None}
    assert [call(app, "PATCH", review_url(), cookies=verifier, payload=status).status_code
            for _ in range(3)] == [200, 200, 429]
    assert call(app, "PATCH", review_url(), cookies=other, payload=status).status_code == 200


def test_default_limits_allow_a_normal_review_workflow(review_env):
    app, _db, _auth, users = review_env
    lead = users["lead"][1]
    for status in ("in_review", "awaiting_evidence", "escalated"):
        assert call(app, "PATCH", review_url(), cookies=lead, payload={"review_status": status, "note": None}).status_code == 200
    assert call(app, "POST", review_url() + "/outcome", cookies=lead,
                payload={"review_outcome": "signal_supported", "note": None}).status_code == 200
    assert call(app, "POST", AUDIT_URL, cookies=lead, payload=VALID).status_code == 200


def test_only_audit_management_roles_receive_the_audit_reference(review_env, monkeypatch):
    app, _db, auth_db, users = review_env
    lead, verifier = users["lead"][1], users["verifier"][1]
    call(app, "PATCH", review_url(), cookies=lead, payload={"review_status": "in_review", "note": None})
    call(app, "POST", AUDIT_URL, cookies=lead, payload={**VALID, "note": "Catatan audit sintetis."})
    # The verifier role now holds review:manage and sees the full audit record.
    assert call(app, "GET", review_url(), cookies=verifier).json()["audit_details_visible"] is True

    # A read-only reviewer role (review:read/write without review:manage) still gets the redacted view.
    from app.security import auth
    monkeypatch.setitem(auth.ROLE_PERMISSIONS, "verifikator", auth.ROLE_PERMISSIONS["verifikator"] - {"review:manage"})
    seen = call(app, "GET", review_url(), cookies=verifier)
    assert seen.status_code == 200
    body = seen.json()
    assert body["audit_result"] == "confirmed_issue" and body["audit_result_label"]
    assert body["audit_confirmations"] == [] and body["audit_details_visible"] is False
    assert "AUD-2026/014" not in seen.text and "Catatan audit sintetis." not in seen.text
    written = call(app, "PATCH", review_url(), cookies=verifier, payload={"review_status": "escalated", "note": None})
    assert written.status_code == 200 and "AUD-2026/014" not in written.text
    queue = call(app, "GET", "/api/v1/runs/run-a/reviews", cookies=verifier)
    assert queue.json()["items"][0]["audit_result"] == "confirmed_issue" and "AUD-2026/014" not in queue.text

    full = call(app, "GET", review_url(), cookies=lead).json()
    assert full["audit_details_visible"] is True
    assert full["audit_confirmations"][0]["audit_reference"] == "AUD-2026/014"
    admin_store = AuthStore(auth_db)
    admin = admin_store.create_bootstrap_admin("synthetic-admin", PASSWORD, "s", "s")
    session, token = admin_store.authenticate(admin["username"], PASSWORD)
    admin_view = call(app, "GET", review_url(), cookies={"cir_session": token, "cir_csrf": session["csrf_token"]})
    assert admin_view.json()["audit_details_visible"] is True
