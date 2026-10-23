"""Persistent AnalysisRun API tests using isolated synthetic-only stores."""

import asyncio
import copy
import json
import sqlite3

import httpx
import pytest

from app.analytics.risk_scoring import DETECTOR_ORDER
from app.analytics.action_policy import ActionPolicyConfig, ACTION_POLICY_CONFIGURATIONS, ACTION_POLICY_VERSION
from app.analytics.batch_adapter import BatchAdapterError, adapt_batch_features
from app.data_sources.synthetic_csv import (
    SYNTHETIC_CSV_MAPPING_VERSION, SYNTHETIC_CSV_SCHEMA_VERSION, export_synthetic_csv,
)
from app.data_sources.synthetic_generator import SyntheticGeneratorConfig, generate_synthetic_dataset
from app.main import create_app
from app.security.auth import AuthStore
from app.services.batches import BatchStore
from app.services import runs as runs_service


def call(app, method, path, *, cookies=None, json_body=None, content=None, headers=None):
    async def send():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, cookies=cookies, json=json_body,
                                        content=content, headers=headers)
    return asyncio.run(send())


def setup(tmp_path):
    auth_db = tmp_path / "auth.sqlite3"
    review_db = tmp_path / "review.sqlite3"
    batch_db = tmp_path / "batch-and-runs.sqlite3"
    app = create_app(review_db, auth_db, cookie_secure=False, batch_db_path=batch_db)
    store = AuthStore(auth_db)
    admin = store.create_bootstrap_admin(
        "root-admin", "Synthetic-admin-password-2026!", "bootstrap-test-secret", "bootstrap-test-secret",
    )
    users = {
        "operator": store.create_user("synthetic-operator", "Synthetic-operator-password-2026!",
                                      "data_operator", admin["user_id"]),
        "verifier": store.create_user("synthetic-verifier", "Synthetic-verifier-password-2026!",
                                      "verifikator", admin["user_id"]),
        "lead": store.create_user("synthetic-lead", "Synthetic-lead-password-2026!",
                                  "audit_lead", admin["user_id"]),
    }
    return app, batch_db, users


def login(app, username, password):
    response = call(app, "POST", "/api/v1/auth/login", json_body={"username": username, "password": password})
    assert response.status_code == 200
    return dict(response.cookies.items())


def operator_session(app, users):
    user = users["operator"]
    return login(app, user["username"], "Synthetic-operator-password-2026!")


def verifier_session(app, users, user_key="verifier"):
    user = users[user_key]
    password = "Synthetic-verifier-password-2026!" if user_key == "verifier" else "Synthetic-lead-password-2026!"
    return login(app, user["username"], password)


def import_batch(app, batch_db, cookies, *, malformed=False):
    generated = generate_synthetic_dataset(SyntheticGeneratorConfig(seed=712, claim_count=250, facility_count=12))
    raw = export_synthetic_csv(generated.records)
    if malformed:
        raw = b"not,the,synthetic,schema\n1,2,3,4\n"
    response = call(
        app, "POST", "/api/v1/batches/import", cookies=cookies, content=raw,
        headers={
            "Content-Type": "text/csv; charset=utf-8", "X-CSRF-Token": cookies["cir_csrf"],
            "X-Batch-Key": "synthetic-run-fixture", "X-Synthetic-Schema-Version": SYNTHETIC_CSV_SCHEMA_VERSION,
            "X-Synthetic-Mapping-Version": SYNTHETIC_CSV_MAPPING_VERSION,
            "X-Data-Classification": "synthetic_only",
        },
    )
    assert response.status_code == 201, response.text
    batch = response.json()["batch"]
    return batch, generated


def create_run(app, cookies, batch_id=None, retry_of_run_id=None, extra=None):
    body = {"batch_id": batch_id, "retry_of_run_id": retry_of_run_id}
    if batch_id is None:
        body.pop("batch_id")
    if retry_of_run_id is None:
        body.pop("retry_of_run_id")
    if extra:
        body.update(extra)
    return call(app, "POST", "/api/v1/runs", cookies=cookies, json_body=body,
                headers={"X-CSRF-Token": cookies["cir_csrf"]})


def test_create_pins_batch_persists_actual_pipeline_and_get_does_not_rerun(tmp_path, monkeypatch):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, generated = import_batch(app, batch_db, operator)
    pinned = BatchStore(batch_db).get_execution_input(batch["batch_id"])["batch"]

    original_pipeline = runs_service.build_analytics_snapshot
    pipeline_calls = []
    def check_feature_boundary(**kwargs):
        pipeline_calls.append(1)
        assert len(kwargs["records"]) == len(generated.records)
        assert all(not {"is_anomaly", "scenario", "ground_truth", "scenario_group_id"}.intersection(row)
                   for row in kwargs["records"])
        return original_pipeline(**kwargs)
    monkeypatch.setattr(runs_service, "build_analytics_snapshot", check_feature_boundary)
    response = create_run(app, operator, batch["batch_id"])
    assert response.status_code == 201, response.text
    manifest = response.json()["run"]
    assert manifest["batch_id"] == batch["batch_id"]
    assert manifest["batch_version"] == batch["batch_version"]
    assert manifest["content_checksum"] == pinned["content_checksum"]
    assert manifest["source_schema_version"] == SYNTHETIC_CSV_SCHEMA_VERSION
    assert manifest["source_mapping_version"] == SYNTHETIC_CSV_MAPPING_VERSION
    assert manifest["creator_user_id"] == users["operator"]["user_id"]
    assert manifest["execution_status"] in {"completed", "partial"}
    assert manifest["completed_at"] is not None and manifest["result_available"] is True
    assert manifest["scoring_version"] == "rule-risk-index-v1-provisional"
    assert manifest["priority_version"] == "audit-priority-v1-synthetic-assumption"
    assert manifest["detector_suite_version"] == "detector-suite-v1-manual"
    assert manifest["action_policy_version"] == ACTION_POLICY_VERSION
    assert manifest["configuration"]["action_policy"]["green_upper"] == 1 / 3
    assert manifest["configuration"]["detector_order"] == list(DETECTOR_ORDER)
    assert len(pipeline_calls) == 1

    verifier = verifier_session(app, users)
    def fail_if_called(*args, **kwargs):
        raise AssertionError("GET must not execute analytics")
    monkeypatch.setattr(runs_service, "build_analytics_snapshot", fail_if_called)
    detail = call(app, "GET", f"/api/v1/runs/{manifest['run_id']}", cookies=verifier)
    assert detail.status_code == 200
    result = detail.json()["result"]
    assert result["action_policy"]["policy_version"] == ACTION_POLICY_VERSION
    assert result["action_policy"]["configuration"] == manifest["configuration"]["action_policy"]
    assert result["data_source"] == {"kind": "synthetic", "label": "synthetic_data_batch"}
    assert result["records_considered"] == len(generated.records)
    assert len(result["indicator_coverage"]) == 6
    assert all(item["indicator"] in DETECTOR_ORDER for item in result["indicator_coverage"])
    serialized = json.dumps(detail.json())
    for record in generated.records:
        assert record["participant_token"] not in serialized
    for forbidden in ("ground_truth", "scenario_group_id", "is_synthetic_anomaly"):
        assert forbidden not in serialized


def test_batches_can_have_independent_runs_and_run_history_survives_reinitialization(tmp_path):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _ = import_batch(app, batch_db, operator)
    run1 = create_run(app, operator, batch["batch_id"])
    run2 = create_run(app, operator, batch["batch_id"])
    assert run1.status_code == run2.status_code == 201
    first, second = run1.json()["run"], run2.json()["run"]
    assert first["run_id"] != second["run_id"]
    assert first["batch_id"] == second["batch_id"] == batch["batch_id"]

    verifier = verifier_session(app, users)
    listed = call(app, "GET", f"/api/v1/runs?batch_id={batch['batch_id']}&limit=10&offset=0", cookies=verifier)
    assert listed.status_code == 200 and listed.json()["total_items"] == 2
    reinitialized = create_app(tmp_path / "review.sqlite3", tmp_path / "auth.sqlite3",
                               cookie_secure=False, batch_db_path=batch_db)
    detail = call(reinitialized, "GET", f"/api/v1/runs/{first['run_id']}", cookies=verifier)
    assert detail.status_code == 200
    assert detail.json()["run"]["execution_status"] == first["execution_status"]
    assert detail.json()["result"]["records_considered"] == 250


def test_policy_versions_are_pinned_per_run_and_old_result_is_immutable(tmp_path, monkeypatch):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _ = import_batch(app, batch_db, operator)
    first_response = create_run(app, operator, batch["batch_id"])
    assert first_response.status_code == 201
    first_id = first_response.json()["run"]["run_id"]
    verifier = verifier_session(app, users)
    before = call(app, "GET", f"/api/v1/runs/{first_id}", cookies=verifier).json()

    alternate = ActionPolicyConfig("action-policy-demo-v2-provisional", 0.25, 0.75)
    monkeypatch.setitem(ACTION_POLICY_CONFIGURATIONS, alternate.version, alternate)
    second = create_run(app, operator, batch["batch_id"], extra={"action_policy_version": alternate.version})
    assert second.status_code == 201, second.text
    assert second.json()["run"]["action_policy_version"] == alternate.version
    assert second.json()["run"]["configuration"]["action_policy"] == alternate.as_dict()
    after = call(app, "GET", f"/api/v1/runs/{first_id}", cookies=verifier).json()
    assert after == before

    altered_same_version = ActionPolicyConfig(ACTION_POLICY_VERSION, 0.25, 0.75)
    monkeypatch.setitem(ACTION_POLICY_CONFIGURATIONS, ACTION_POLICY_VERSION, altered_same_version)
    conflict = create_run(app, operator, batch["batch_id"])
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "ACTION_POLICY_VERSION_CONFLICT"


def test_policy_selection_rejects_unknown_versions_and_client_thresholds(tmp_path):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _ = import_batch(app, batch_db, operator)
    unknown = create_run(app, operator, batch["batch_id"], extra={
        "action_policy_version": "action-policy-unknown-provisional",
    })
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "ACTION_POLICY_VERSION_UNKNOWN"
    arbitrary_thresholds = create_run(app, operator, batch["batch_id"], extra={
        "action_policy": {"green_upper": 0.9, "yellow_upper": 0.95},
    })
    assert arbitrary_thresholds.status_code == 422


def test_missing_rejected_and_invalid_batches_are_rejected(tmp_path):
    app, _, users = setup(tmp_path)
    operator = operator_session(app, users)
    assert create_run(app, operator, "bat_unknown").status_code == 404
    rejected, _ = import_batch(app, tmp_path / "batch-and-runs.sqlite3", operator, malformed=True)
    assert rejected["status"] == "rejected"
    response = create_run(app, operator, rejected["batch_id"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BATCH_NOT_RUNNABLE"
    assert create_run(app, operator).status_code == 422


def test_batch_adapter_is_versioned_typed_feature_only_and_returns_detached_copies(tmp_path):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _ = import_batch(app, batch_db, operator)
    execution = BatchStore(batch_db).get_execution_input(batch["batch_id"])
    original = copy.deepcopy(execution["records"])
    features, facilities = adapt_batch_features(execution["batch"], execution["records"])
    assert len(features) == len(original)
    assert facilities and facilities[0]["facility_id"].startswith("syn-facility-")
    features[0]["service_units"] = 99
    assert execution["records"] == original
    contaminated = copy.deepcopy(original)
    contaminated[0]["scenario"] = "synthetic_label"
    with pytest.raises(BatchAdapterError):
        adapt_batch_features(execution["batch"], contaminated)
    invalid = copy.deepcopy(original)
    invalid[0]["service_units"] = "not-an-integer"
    with pytest.raises(BatchAdapterError):
        adapt_batch_features(execution["batch"], invalid)


def test_auth_csrf_role_and_creator_are_enforced(tmp_path):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _ = import_batch(app, batch_db, operator)
    verifier = verifier_session(app, users)
    assert create_run(app, verifier, batch["batch_id"]).status_code == 403
    no_csrf = call(app, "POST", "/api/v1/runs", cookies=operator,
                   json_body={"batch_id": batch["batch_id"]})
    assert no_csrf.status_code == 403
    bad_csrf = call(app, "POST", "/api/v1/runs", cookies=operator,
                    json_body={"batch_id": batch["batch_id"]}, headers={"X-CSRF-Token": "incorrect"})
    assert bad_csrf.status_code == 403
    forged = create_run(app, operator, batch["batch_id"], extra={"creator_user_id": users["verifier"]["user_id"],
                                                                  "role": "audit_lead"})
    assert forged.status_code == 422
    created = create_run(app, operator, batch["batch_id"])
    assert created.status_code == 201
    assert created.json()["run"]["creator_user_id"] == users["operator"]["user_id"]
    run_id = created.json()["run"]["run_id"]
    assert call(app, "GET", f"/api/v1/runs/{run_id}", cookies=operator).status_code == 403
    assert call(app, "GET", "/api/v1/runs", cookies=operator).status_code == 200
    assert call(app, "GET", "/api/v1/runs", cookies=verifier).status_code == 200
    lead = verifier_session(app, users, "lead")
    assert call(app, "GET", f"/api/v1/runs/{run_id}", cookies=lead).status_code == 200
    admin = login(app, "root-admin", "Synthetic-admin-password-2026!")
    assert call(app, "GET", "/api/v1/runs", cookies=admin).status_code == 403
    assert call(app, "GET", f"/api/v1/runs/{run_id}", cookies=admin).status_code == 403
    assert call(app, "GET", f"/api/v1/runs/{run_id}").status_code == 401


def test_pipeline_failure_is_safe_terminal_and_retry_creates_new_run(tmp_path, monkeypatch):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _ = import_batch(app, batch_db, operator)
    def broken(*args, **kwargs):
        raise RuntimeError("sensitive participant-token failure detail")
    monkeypatch.setattr(runs_service, "build_analytics_snapshot", broken)
    failed = create_run(app, operator, batch["batch_id"])
    assert failed.status_code == 500
    assert "sensitive participant-token" not in failed.text
    failed_id = failed.json()["error"]["details"]["run_id"]
    store = runs_service.AnalysisRunStore(batch_db)
    original = store.get_run(failed_id)
    assert original["execution_status"] == "failed"
    assert original["failure_category"] == "PIPELINE_EXECUTION_FAILED"
    assert original["result"] is None

    monkeypatch.undo()
    retry = create_run(app, operator, retry_of_run_id=failed_id)
    assert retry.status_code == 201, retry.text
    new_run = retry.json()["run"]
    assert new_run["run_id"] != failed_id
    assert new_run["retry_of_run_id"] == failed_id
    assert store.get_run(failed_id)["execution_status"] == "failed"
    assert store.get_run(new_run["run_id"])["execution_status"] in {"completed", "partial"}
    wrong_batch = create_run(app, operator, "bat_another_version", retry_of_run_id=failed_id)
    assert wrong_batch.status_code == 409
    assert wrong_batch.json()["error"]["code"] == "RETRY_BATCH_MISMATCH"


def test_partial_status_null_scores_and_not_applicable_are_persisted_without_reinterpretation(tmp_path, monkeypatch):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _ = import_batch(app, batch_db, operator)
    synthetic_snapshot = {
        "availability": "available", "execution_status": "partial",
        "data_source": {"kind": "synthetic", "label": "synthetic_data_batch"},
        "records_considered": 250, "records_eligible": 0, "indicators": [],
        "indicator_coverage": [
            {"indicator": DETECTOR_ORDER[0], "status": "not_applicable", "records_assessed": 0,
             "records_not_applicable": 250, "records_unassessed": 0, "search_truncated": False,
             "candidate_group_count": 0, "limitations": []},
            {"indicator": DETECTOR_ORDER[1], "status": "partial", "records_assessed": 100,
             "records_not_applicable": 0, "records_unassessed": 150, "search_truncated": True,
             "candidate_group_count": None, "limitations": ["truncated"]},
        ],
        "risk_scoring": {"version": "rule-risk-index-v1-provisional", "weights": {}, "weight_basis": "test",
                         "unassessable_case_count": 1, "limitations": []},
        "audit_priority": {"priority_version": "audit-priority-v1-synthetic-assumption",
                           "status": "not_assessable", "formula": "rule", "unit": "synthetic facility"},
        "cases": {"syn-claim-000001": {"risk_score": None, "risk_level": None,
                                       "score_status": "not_assessable"}},
    }
    monkeypatch.setattr(runs_service, "build_analytics_snapshot", lambda **kwargs: synthetic_snapshot)
    created = create_run(app, operator, batch["batch_id"])
    assert created.status_code == 201
    run_id = created.json()["run"]["run_id"]
    verifier = verifier_session(app, users)
    detail = call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier).json()
    assert detail["run"]["execution_status"] == "partial"
    assert detail["result"]["cases"]["syn-claim-000001"]["risk_score"] is None
    assert detail["result"]["audit_priority"]["status"] == "not_assessable"
    assert detail["result"]["indicator_coverage"][0]["status"] == "not_applicable"
    assert detail["run"]["coverage"][1]["search_truncated"] is True


def test_terminal_run_cannot_be_overwritten_or_deleted_and_health_is_database_independent(tmp_path):
    app, batch_db, users = setup(tmp_path)
    # Health remains a process-only check and does not initialize batch/run stores.
    untouched = tmp_path / "untouched.sqlite3"
    isolated = create_app(tmp_path / "review-unused.sqlite3", tmp_path / "auth-unused.sqlite3",
                          cookie_secure=False, batch_db_path=untouched)
    assert call(isolated, "GET", "/health").status_code == 200
    assert not untouched.exists()

    operator = operator_session(app, users)
    batch, _ = import_batch(app, batch_db, operator)
    created = create_run(app, operator, batch["batch_id"])
    assert created.status_code == 201
    run_id = created.json()["run"]["run_id"]
    with sqlite3.connect(batch_db) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE analysis_runs SET execution_status='failed' WHERE run_id=?", (run_id,))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM analysis_run_results WHERE run_id=?", (run_id,))
        events = connection.execute(
            "SELECT event_type FROM analysis_run_audit_events WHERE target_run_id=? ORDER BY occurred_at,event_id",
            (run_id,),
        ).fetchall()
    assert [row[0] for row in events] == ["analysis_run_created", "analysis_run_" + created.json()["run"]["execution_status"]]
