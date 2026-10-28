"""Isolated integration tests for the auditor review workflow."""

import asyncio
import json

import httpx
import pytest

from app.data_sources.synthetic import get_synthetic_records
from app.main import create_app
from app.services.analytics import build_analytics_snapshot
from app.security.auth import AuthStore


def request(app, method: str, path: str, payload: dict | None = None):
    async def send():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            cookies = getattr(app.state, "test_auth_cookies", {})
            headers = {"X-CSRF-Token": cookies["cir_csrf"]} if method not in {"GET", "HEAD"} and cookies else None
            return await client.request(method, path, json=payload, cookies=cookies, headers=headers)

    return asyncio.run(send())


@pytest.fixture
def review_app(tmp_path):
    db_path = tmp_path / "isolated" / "reviews.sqlite3"
    app = create_app(review_db_path=db_path, auth_db_path=db_path, cookie_secure=False)
    store = AuthStore(db_path)
    user = store.create_user("review-verifikator", "Review-only-password-2026!", "verifikator", "test-bootstrap")
    session, token = store.authenticate("review-verifikator", "Review-only-password-2026!")
    app.state.test_auth_cookies = {"cir_session": token, "cir_csrf": session["csrf_token"]}
    app.state.test_user_id = user["user_id"]
    return app, db_path


def candidate_id() -> str:
    return sorted(build_analytics_snapshot()["cases"])[0]


@pytest.mark.sqlite_storage  # asserts the SQLite review file is created
def test_unreviewed_case_has_pending_review_and_empty_history(review_app):
    app, db_path = review_app
    case_id = candidate_id()
    response = request(app, "GET", f"/api/v1/cases/{case_id}/review")

    assert response.status_code == 200
    assert response.json()["status"] == "pending_review"
    assert response.json()["status_label"] == "Menunggu Tinjauan"
    assert response.json()["history"] == []
    assert response.json()["note"] is None
    assert db_path.exists()


def test_queue_includes_review_status_and_filter_works(review_app):
    app, _ = review_app
    case_id = candidate_id()
    before = request(app, "GET", "/api/v1/cases?review_status=pending_review").json()
    assert all(item["review_status"] == "pending_review" for item in before["items"])

    changed = request(
        app, "POST", f"/api/v1/cases/{case_id}/review",
        {"status": "needs_more_evidence", "note": "Perlu dokumen pendukung."},
    )
    assert changed.status_code == 200
    queue = request(app, "GET", "/api/v1/cases?review_status=needs_more_evidence").json()
    assert case_id in {item["case_id"] for item in queue["items"]}
    assert queue["applied_filters"]["review_status"] == "needs_more_evidence"


def test_status_update_appends_history_with_previous_and_new_status(review_app):
    app, _ = review_app
    case_id = candidate_id()
    first = request(app, "POST", f"/api/v1/cases/{case_id}/review", {
        "status": "needs_more_evidence", "note": "Minta dokumen pendukung.",
    })
    second = request(app, "POST", f"/api/v1/cases/{case_id}/review", {
        "status": "escalated", "note": "Perlu tinjauan lanjutan.",
    })

    assert first.status_code == second.status_code == 200
    current = second.json()
    assert current["status"] == "escalated"
    assert len(current["history"]) == 2
    assert current["history"][0]["previous_status"] == "pending_review"
    assert current["history"][0]["status"] == "needs_more_evidence"
    assert current["history"][1]["previous_status"] == "needs_more_evidence"
    assert current["history"][1]["status"] == current["status"]
    assert current["history"][-1]["changed_at"] == current["updated_at"]
    assert current["history"][-1]["note"] == current["note"]
    assert current["reviewer_label"] == "review-verifikator"
    assert current["history"][-1]["actor_id"] == app.state.test_user_id


@pytest.mark.parametrize("payload", [
    {"status": "fraud_confirmed", "note": "x"},
    {"status": "escalated", "note": "x", "reviewer_label": "verified user"},
    {"status": "escalated", "unexpected": "value"},
    {"note": "missing status"},
])
def test_invalid_payload_is_rejected_without_echoing_input(review_app, payload):
    app, _ = review_app
    response = request(app, "POST", f"/api/v1/cases/{candidate_id()}/review", payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INVALID_PAYLOAD"
    assert "details" in body["error"]
    assert payload.get("reviewer_label", "verified user") not in json.dumps(body)


def test_note_length_is_bounded(review_app):
    app, _ = review_app
    response = request(app, "POST", f"/api/v1/cases/{candidate_id()}/review", {
        "status": "not_substantiated", "note": "x" * 1001,
    })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PAYLOAD"


def test_unknown_case_returns_contract_404_for_both_review_routes(review_app):
    app, _ = review_app
    for method in ("GET", "POST"):
        response = request(app, method, "/api/v1/cases/unknown-case/review", {
            "status": "escalated", "note": "Tidak digunakan.",
        } if method == "POST" else None)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "CASE_NOT_FOUND"


def test_state_persists_after_database_connection_and_app_are_recreated(review_app):
    app, db_path = review_app
    case_id = candidate_id()
    updated = request(app, "POST", f"/api/v1/cases/{case_id}/review", {
        "status": "not_substantiated", "note": "Indikasi tidak cukup setelah peninjauan.",
    })
    reopened_app = create_app(review_db_path=db_path, auth_db_path=db_path, cookie_secure=False)
    reopened_app.state.test_auth_cookies = app.state.test_auth_cookies
    reopened_app.state.test_user_id = app.state.test_user_id
    reopened = request(reopened_app, "GET", f"/api/v1/cases/{case_id}/review")

    assert updated.status_code == reopened.status_code == 200
    assert reopened.json()["status"] == "not_substantiated"
    assert reopened.json()["history"] == updated.json()["history"]


def test_health_does_not_initialize_review_database(review_app):
    _, db_path = review_app
    app = create_app(review_db_path=db_path, auth_db_path=db_path, cookie_secure=False)
    response = request(app, "GET", "/health")
    fresh_path = db_path.parent / "health-only.sqlite3"
    health_app = create_app(review_db_path=fresh_path, auth_db_path=fresh_path, cookie_secure=False)
    health_response = request(health_app, "GET", "/health")
    assert response.status_code == health_response.status_code == 200
    assert not fresh_path.exists()


@pytest.mark.sqlite_storage  # an unwritable SQLite path; PostgreSQL failures: test_postgres_storage.py
def test_storage_failure_returns_controlled_503_without_database_details(tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("fixture", encoding="utf-8")
    auth_path = tmp_path / "auth.sqlite3"
    app = create_app(review_db_path=blocker / "reviews.sqlite3", auth_db_path=auth_path, cookie_secure=False)
    store = AuthStore(auth_path)
    store.create_user("storage-verifikator", "Storage-test-password-2026!", "verifikator", "test-bootstrap")
    session, token = store.authenticate("storage-verifikator", "Storage-test-password-2026!")
    app.state.test_auth_cookies = {"cir_session": token, "cir_csrf": session["csrf_token"]}
    response = request(app, "GET", f"/api/v1/cases/{candidate_id()}/review")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "REVIEW_STORAGE_UNAVAILABLE"
    assert str(tmp_path) not in json.dumps(response.json())


def test_review_response_contains_no_source_tokens_or_signature_values(review_app):
    app, _ = review_app
    case_id = candidate_id()
    response = request(app, "POST", f"/api/v1/cases/{case_id}/review", {
        "status": "needs_more_evidence", "note": "Periksa dokumen pendukung.",
    })
    serialized = json.dumps(response.json(), sort_keys=True)
    assert response.status_code == 200
    source_record = next(
        item for item in get_synthetic_records() if item["case_id"] == case_id
    )
    for field, raw_value in source_record.items():
        if field not in {"case_id", "participant_token"} and raw_value and str(raw_value).strip():
            assert str(raw_value) not in serialized
    assert "demo-person-" not in serialized
    assert "signature" not in serialized.lower()
