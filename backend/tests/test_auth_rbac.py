"""Authentication, session, role, CSRF, and security-event tests."""

import asyncio
import hashlib
import json
import sqlite3
from http.cookies import SimpleCookie
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.main import create_app
from app.services.analytics import build_analytics_snapshot
from app.security.auth import (
    AuthStore, AuthenticationError, PASSWORD_MIN_LENGTH, ROLES,
    hash_password, validate_password, verify_password,
)


def call(app, method, path, *, json_body=None, cookies=None, csrf=False):
    async def send():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"X-CSRF-Token": cookies["cir_csrf"]} if csrf and cookies else None
            return await client.request(method, path, json=json_body, cookies=cookies, headers=headers)
    return asyncio.run(send())


def setup_app(tmp_path):
    db_path = tmp_path / "isolated-auth-review.sqlite3"
    app = create_app(db_path, db_path, cookie_secure=False)
    app.state.test_db_path = db_path
    return app, AuthStore(db_path)


def bootstrap(store, username="root-admin"):
    return store.create_bootstrap_admin(
        username, "Synthetic-admin-password-2026!", "bootstrap-test-secret",
        "bootstrap-test-secret",
    )


def login(app, username, password):
    response = call(app, "POST", "/api/v1/auth/login", json_body={"username": username, "password": password})
    return response, dict(response.cookies.items())


def test_password_hash_is_salted_and_policy_is_enforced():
    password = "Synthetic-password-2026!"
    encoded_a = hash_password(password)
    encoded_b = hash_password(password)
    assert encoded_a != encoded_b
    assert encoded_a.startswith("scrypt$16384$8$1$")
    assert verify_password(password, encoded_a)
    assert not verify_password("wrong-password-value", encoded_a)
    with pytest.raises(ValueError):
        validate_password("short")
    with pytest.raises(ValueError):
        validate_password("x" * (1025))
    with pytest.raises(ValueError):
        validate_password("valid-length-but\x00invalid")
    assert PASSWORD_MIN_LENGTH == 12


def test_bootstrap_requires_secret_and_is_one_time(tmp_path):
    _, store = setup_app(tmp_path)
    with pytest.raises(AuthenticationError):
        store.create_bootstrap_admin("first-admin", "Synthetic-admin-password-2026!", "", None)
    with pytest.raises(AuthenticationError):
        store.create_bootstrap_admin("first-admin", "Synthetic-admin-password-2026!", "wrong", "configured")
    admin = bootstrap(store)
    assert admin["role"] == "platform_admin"
    with pytest.raises(AuthenticationError, match="satu kali"):
        bootstrap(store, "second-admin")


def test_local_demo_password_requires_explicit_development_mode(tmp_path, monkeypatch):
    _, store = setup_app(tmp_path)
    monkeypatch.delenv("CIR_ENV", raising=False)
    with pytest.raises(ValueError, match="CIR_ENV=development"):
        store.create_bootstrap_admin(
            "admin", "admin123", "bootstrap-test-secret", "bootstrap-test-secret",
            allow_local_demo_password=True,
        )

    monkeypatch.setenv("CIR_ENV", "development")
    admin = store.create_bootstrap_admin(
        "admin", "admin123", "bootstrap-test-secret", "bootstrap-test-secret",
        allow_local_demo_password=True,
    )
    assert admin["username"] == "admin"
    assert admin["role"] == "platform_admin"
    with sqlite3.connect(store.path) as connection:
        password_hash = connection.execute(
            "SELECT password_hash FROM auth_users WHERE username = 'admin'"
        ).fetchone()[0]
    assert password_hash.startswith("scrypt$")
    assert verify_password("admin123", password_hash)


def test_login_me_logout_cookie_flags_revocation_and_audit_redaction(tmp_path):
    app, store = setup_app(tmp_path)
    admin = bootstrap(store)
    response, cookies = login(app, admin["username"], "Synthetic-admin-password-2026!")
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "platform_admin"
    assert "csrf_token" in response.json()
    set_cookie = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        set_cookie.load(header)
    session_cookie = set_cookie.get("cir_session")
    csrf_cookie = set_cookie.get("cir_csrf")
    assert session_cookie is not None and session_cookie["httponly"]
    assert session_cookie["samesite"] == "lax" and session_cookie["path"] == "/api/v1"
    assert csrf_cookie is not None and not csrf_cookie["httponly"]
    assert "session_token" not in json.dumps(response.json())
    assert "Synthetic-admin-password-2026!" not in json.dumps(response.json())
    with sqlite3.connect(store.path) as connection:
        password_hash, token_hash, csrf_hash = connection.execute(
            "SELECT u.password_hash, s.token_hash, s.csrf_hash FROM auth_users u "
            "JOIN auth_sessions s ON s.user_id = u.user_id WHERE u.user_id = ?",
            (admin["user_id"],),
        ).fetchone()
    assert password_hash != "Synthetic-admin-password-2026!" and password_hash.startswith("scrypt$")
    assert token_hash == hashlib.sha256(cookies["cir_session"].encode()).hexdigest()
    assert csrf_hash == hashlib.sha256(cookies["cir_csrf"].encode()).hexdigest()
    assert cookies["cir_session"] != token_hash and cookies["cir_csrf"] != csrf_hash

    me = call(app, "GET", "/api/v1/auth/me", cookies=cookies)
    assert me.status_code == 200
    assert me.json()["user"]["user_id"] == admin["user_id"]
    logged_out = call(app, "POST", "/api/v1/auth/logout", cookies=cookies, csrf=True)
    assert logged_out.status_code == 204
    assert call(app, "GET", "/api/v1/auth/me", cookies=cookies).status_code == 401

    events = store.list_audit_events()
    event_types = {item["event_type"] for item in events}
    assert {"admin_bootstrap_completed", "login_succeeded", "logout_session_revoked"}.issubset(event_types)
    serialized = json.dumps(events)
    assert "Synthetic-admin-password-2026!" not in serialized
    assert cookies["cir_session"] not in serialized
    assert cookies["cir_csrf"] not in serialized


def test_failed_login_is_generic_and_audited_without_credentials(tmp_path):
    app, store = setup_app(tmp_path)
    bootstrap(store)
    response = call(app, "POST", "/api/v1/auth/login", json_body={
        "username": "root-admin", "password": "incorrect-synthetic-password",
    })
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    events = store.list_audit_events()
    assert events[0]["event_type"] == "login_failed"
    assert "incorrect-synthetic-password" not in json.dumps(events)
    assert "root-admin" not in json.dumps(events)


@pytest.mark.parametrize("role", ROLES)
def test_backend_permission_matrix_enforced_for_all_roles(tmp_path, role):
    app, store = setup_app(tmp_path)
    admin = bootstrap(store)
    user = store.create_user(f"user-{role}", "Synthetic-role-password-2026!", role, admin["user_id"])
    _, cookies = login(app, user["username"], "Synthetic-role-password-2026!")
    assert call(app, "GET", "/api/v1/dashboard/summary", cookies=cookies).status_code == 200

    analysis = call(app, "GET", "/api/v1/analysis", cookies=cookies)
    assert analysis.status_code == 200
    cases = call(app, "GET", "/api/v1/cases", cookies=cookies)
    assert cases.status_code == (200 if role in {"platform_admin", "verifikator", "audit_lead"} else 403)
    case_id = sorted(build_analytics_snapshot()["cases"])[0]
    review = call(app, "GET", f"/api/v1/cases/{case_id}/review", cookies=cookies)
    assert review.status_code == (200 if role in {"platform_admin", "verifikator", "audit_lead"} else 403)
    review_update = call(app, "POST", f"/api/v1/cases/{case_id}/review",
                         json_body={"status": "needs_more_evidence"}, cookies=cookies, csrf=True)
    assert review_update.status_code == (200 if role in {"platform_admin", "verifikator", "audit_lead"} else 403)
    permissions = call(app, "GET", "/api/v1/auth/me", cookies=cookies).json()["permissions"]
    assert ("runs:results:read" in permissions) == (role in {"platform_admin", "verifikator", "audit_lead"})
    assert ("batches:write" in permissions) == (role in {"platform_admin", "data_operator"})
    assert ("review:manage" in permissions) == (role in {"platform_admin", "audit_lead"})
    create_user = call(app, "POST", "/api/v1/auth/users", json_body={
        "username": f"created-{role}", "password": "Synthetic-created-password-2026!", "role": "data_operator",
    }, cookies=cookies, csrf=True)
    assert create_user.status_code == (201 if role == "platform_admin" else 403)


def test_anonymous_access_denied_and_review_actor_comes_only_from_session(tmp_path):
    app, store = setup_app(tmp_path)
    assert call(app, "GET", "/api/v1/analysis").status_code == 401
    admin = bootstrap(store)
    reviewer = store.create_user("synthetic-reviewer", "Synthetic-review-password-2026!", "verifikator", admin["user_id"])
    _, cookies = login(app, reviewer["username"], "Synthetic-review-password-2026!")
    case_id = sorted(build_analytics_snapshot()["cases"])[0]

    denied_csrf = call(app, "POST", f"/api/v1/cases/{case_id}/review", json_body={"status": "escalated"}, cookies=cookies)
    assert denied_csrf.status_code == 403
    spoof = call(app, "POST", f"/api/v1/cases/{case_id}/review", json_body={
        "status": "escalated", "actor_id": "spoofed", "reviewer_label": "spoofed",
    }, cookies=cookies, csrf=True)
    assert spoof.status_code == 422
    saved = call(app, "POST", f"/api/v1/cases/{case_id}/review", json_body={
        "status": "needs_more_evidence", "note": "Synthetic review note only.",
    }, cookies=cookies, csrf=True)
    assert saved.status_code == 200
    assert saved.json()["history"][-1]["actor_id"] == reviewer["user_id"]
    assert saved.json()["reviewer_label"] == reviewer["username"]
    event = next(item for item in store.list_audit_events() if item["event_type"] == "review_updated")
    assert event["actor_user_id"] == reviewer["user_id"]
    assert event["target_id"] == case_id
    assert "Synthetic-review-password-2026!" not in json.dumps(store.list_audit_events())
    assert cookies["cir_session"] not in json.dumps(store.list_audit_events())


def test_session_expiry_and_disabled_account_revoke_access(tmp_path):
    app, store = setup_app(tmp_path)
    admin = bootstrap(store)
    operator = store.create_user("synthetic-operator", "Synthetic-operator-password-2026!", "data_operator", admin["user_id"])
    _, cookies = login(app, operator["username"], "Synthetic-operator-password-2026!")
    with store._connection() as connection:
        connection.execute(
            "UPDATE auth_sessions SET expires_at = ? WHERE token_hash = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
             hashlib.sha256(cookies["cir_session"].encode()).hexdigest()),
        )
    assert call(app, "GET", "/api/v1/auth/me", cookies=cookies).status_code == 401
    assert any(item["event_type"] == "session_expired" for item in store.list_audit_events())

    _, admin_cookies = login(app, admin["username"], "Synthetic-admin-password-2026!")
    disabled_login, operator_cookies = login(app, operator["username"], "Synthetic-operator-password-2026!")
    assert disabled_login.status_code == 200
    disable = call(app, "PATCH", f"/api/v1/auth/users/{operator['user_id']}",
                   json_body={"is_active": False}, cookies=admin_cookies, csrf=True)
    assert disable.status_code == 200
    assert call(app, "GET", "/api/v1/auth/me", cookies=operator_cookies).status_code == 401
    assert any(item["event_type"] == "session_revoked_inactive_account" for item in store.list_audit_events())


def test_role_update_and_last_admin_protection(tmp_path):
    app, store = setup_app(tmp_path)
    admin = bootstrap(store)
    _, cookies = login(app, admin["username"], "Synthetic-admin-password-2026!")
    denied = call(app, "POST", "/api/v1/auth/users", json_body={
        "username": "synthetic-new", "password": "Synthetic-new-password-2026!", "role": "audit_lead",
    }, cookies=cookies, csrf=True)
    assert denied.status_code == 201
    created = denied.json()["user"]
    changed = call(app, "PATCH", f"/api/v1/auth/users/{admin['user_id']}",
                   json_body={"is_active": False}, cookies=cookies, csrf=True)
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "ADMIN_INVARIANT"


def test_health_does_not_create_auth_or_review_database(tmp_path):
    db_path = tmp_path / "health-only.sqlite3"
    app = create_app(db_path, db_path, cookie_secure=False)
    response = call(app, "GET", "/health")
    assert response.status_code == 200
    assert not db_path.exists()


def test_session_cookie_is_secure_by_default(tmp_path):
    db_path = tmp_path / "secure-cookie.sqlite3"
    app = create_app(db_path, db_path)
    store = AuthStore(db_path)
    admin = bootstrap(store)
    response = call(app, "POST", "/api/v1/auth/login", json_body={
        "username": admin["username"], "password": "Synthetic-admin-password-2026!",
    })
    set_cookie = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        set_cookie.load(header)
    assert response.status_code == 200
    assert set_cookie["cir_session"]["secure"]
