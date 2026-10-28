"""Integration checks for the synthetic analytics API."""

import asyncio
import os
import ast
import json
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

import httpx

from app.analytics.audit_priority import build_audit_priority_queue
from app.analytics.risk_scoring import DETECTOR_ORDER, run_detector_suite, score_claims
from app.data_sources.synthetic import get_synthetic_records
from app.main import create_app
from app.services.analytics import build_analytics_snapshot
from app.security.auth import AuthStore
import app.services.analytics as analytics_service


TEST_DB = Path(gettempdir()) / f"cir-api-tests-{uuid4().hex}.sqlite3"
TEST_APP = create_app(review_db_path=TEST_DB, auth_db_path=TEST_DB, cookie_secure=False)
_sessions: dict[str, dict] = {}


def _cookies() -> dict:
    """A verifier session in the active operational database (per-test schema on PostgreSQL)."""
    key = os.environ.get("CIR_DATABASE_SCHEMA") or "sqlite"
    if key not in _sessions:
        store = AuthStore(TEST_DB)
        store.create_user("api-verifikator", "Test-only-password-2026!", "verifikator", "test-bootstrap")
        session, token = store.authenticate("api-verifikator", "Test-only-password-2026!")
        _sessions[key] = {"cir_session": token, "cir_csrf": session["csrf_token"]}
    return _sessions[key]


def request(method: str, path: str):
    cookies = _cookies()

    async def send():
        transport = httpx.ASGITransport(app=TEST_APP, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"X-CSRF-Token": cookies["cir_csrf"]} if method not in {"GET", "HEAD"} else None
            return await client.request(method, path, cookies=cookies, headers=headers)

    return asyncio.run(send())


def test_all_contract_endpoints_return_expected_shapes_and_synthetic_label():
    responses = {
        "summary": request("GET", "/api/v1/dashboard/summary"),
        "analysis": request("GET", "/api/v1/analysis"),
        "cases": request("GET", "/api/v1/cases"),
        "evaluation": request("GET", "/api/v1/evaluation"),
    }
    detail_id = responses["cases"].json()["items"][0]["case_id"]
    responses["detail"] = request("GET", f"/api/v1/cases/{detail_id}")

    assert all(response.status_code == 200 for response in responses.values())
    assert set(responses["summary"].json()) == {
        "availability", "execution_status", "data_source", "generated_at", "period", "summary", "notice"
    }
    assert set(responses["analysis"].json()) == {
        "availability", "execution_status", "data_source", "generated_at", "filters", "coverage",
        "indicators", "planned_indicators", "indicator_coverage", "risk_scoring",
        "audit_priority", "limitations",
    }
    assert set(responses["cases"].json()) == {
        "availability", "execution_status", "data_source", "items", "pagination", "applied_filters", "notice"
    }
    assert set(responses["detail"].json()) == {"availability", "execution_status", "data_source", "case", "notice"}
    assert set(responses["evaluation"].json()) == {
        "availability", "data_source", "generated_at", "evaluation",
        "requirements_missing", "notice",
    }
    for response in responses.values():
        assert response.json()["data_source"] == {"kind": "synthetic", "label": "synthetic_demo"}
    assert responses["analysis"].json()["execution_status"] in {"completed", "partial", "failed"}


def test_health_contract_is_unchanged():
    response = request("GET", "/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok", "service": "claim-integrity-radar-api", "version": "0.1.0"
    }


def test_dashboard_and_analysis_counts_are_calculated_by_all_six_detectors():
    records = get_synthetic_records()
    detector_results = run_detector_suite(records, [])
    scored = score_claims(records, detector_results)
    priority = build_audit_priority_queue(records, scored)
    snapshot = build_analytics_snapshot()
    summary = request("GET", "/api/v1/dashboard/summary").json()
    analysis_result = request("GET", "/api/v1/analysis").json()

    assert summary["summary"]["claims_reviewed"] == len(records)
    assert summary["summary"]["cases_in_queue"] == len(snapshot["cases"])
    assert summary["summary"]["risk_level_counts"] == {"high": None, "medium": None, "low": None}
    assert set(detector_results) == set(DETECTOR_ORDER)
    expected = {item["code"]: item for item in snapshot["indicators"]}
    assert set(expected) == set(DETECTOR_ORDER)
    for item in analysis_result["indicators"]:
        result = expected[item["code"]]
        assert item["candidate_count"] == result["candidate_count"]
        assert item["candidate_group_count"] == result["candidate_group_count"]
        assert item["eligible_count"] == result["eligible_count"]
    assert analysis_result["risk_scoring"]["version"] == scored["scoring_version"]
    assert analysis_result["audit_priority"]["priority_version"] == priority["priority_version"]
    assert analysis_result["audit_priority"]["unit_count"] == len(priority["items"])
    assert analysis_result["audit_priority"]["unassigned_triggered_case_count"] == priority["unassigned_triggered_case_count"]
    assert analysis_result["indicator_coverage"] == snapshot["indicator_coverage"]


def test_coordinated_pipeline_calls_detectors_scoring_and_priority_once(monkeypatch):
    calls = {"detectors": 0, "scoring": 0, "priority": 0}
    original_detectors = analytics_service.run_detector_suite
    original_scoring = analytics_service.score_claims
    original_priority = analytics_service.build_audit_priority_queue

    def detectors(*args, **kwargs):
        calls["detectors"] += 1
        result = original_detectors(*args, **kwargs)
        assert set(result) == set(DETECTOR_ORDER)
        return result

    def scoring(*args, **kwargs):
        calls["scoring"] += 1
        return original_scoring(*args, **kwargs)

    def priority(*args, **kwargs):
        calls["priority"] += 1
        return original_priority(*args, **kwargs)

    monkeypatch.setattr(analytics_service, "run_detector_suite", detectors)
    monkeypatch.setattr(analytics_service, "score_claims", scoring)
    monkeypatch.setattr(analytics_service, "build_audit_priority_queue", priority)
    snapshot = build_analytics_snapshot()

    assert calls == {"detectors": 1, "scoring": 1, "priority": 1}
    assert len(snapshot["indicator_coverage"]) == len(DETECTOR_ORDER)
    by_code = {item["indicator"]: item for item in snapshot["indicator_coverage"]}
    assert by_code["synthetic_capacity_candidate"]["records_not_applicable"] == 0
    assert by_code["synthetic_capacity_candidate"]["records_unassessed"] == len(get_synthetic_records())
    assert by_code["synthetic_capacity_candidate"]["status"] == "partial"
    assert by_code["temporal_pattern_candidate"]["status"] == "partial"
    assert snapshot["audit_priority"]["status"] == "not_assessable"
    assert snapshot["audit_priority"]["unassigned_triggered_case_count"] > 0
    assert snapshot["execution_status"] == "partial"
    serialized = json.dumps(snapshot["cases"], sort_keys=True)
    assert "demo-person-" not in serialized
    assert "is_synthetic_anomaly" not in serialized
    assert "primary_scenario" not in serialized
    assert "scenario_group_id" not in serialized


def test_empty_source_is_insufficient_data_with_a_valid_empty_queue():
    snapshot = build_analytics_snapshot(records=[])
    assert snapshot["availability"] == "insufficient_data"
    assert snapshot["records_considered"] == 0
    assert snapshot["cases"] == {}
    assert snapshot["risk_scoring"]["unassessable_case_count"] == 0
    assert all(item["candidate_count"] == 0 for item in snapshot["indicators"])


def test_unavailable_detectors_report_null_candidate_counts_not_false_zero(monkeypatch):
    monkeypatch.setattr(analytics_service, "run_detector_suite", lambda records, facilities, **_options: {
        indicator: {"indicator": indicator, "status": "unavailable", "error_type": "SyntheticTestFailure"}
        for indicator in DETECTOR_ORDER
    })
    snapshot = build_analytics_snapshot()
    assert snapshot["availability"] == "unavailable"
    assert all(item["candidate_count"] is None for item in snapshot["indicators"])
    assert all(item["candidate_group_count"] is None for item in snapshot["indicators"])
    assert all(item["status"] == "unavailable" for item in snapshot["indicator_coverage"])
    assert snapshot["execution_status"] == "failed"
    assert snapshot["risk_scoring"]["unassessable_case_count"] == len(get_synthetic_records())
    assert snapshot["audit_priority"]["status"] == "not_assessable"
    analysis_response = request("GET", "/api/v1/analysis")
    assert analysis_response.status_code == 200
    assert analysis_response.json()["availability"] == "unavailable"
    assert analysis_response.json()["execution_status"] == "failed"
    assert all(item["candidate_count"] is None for item in analysis_response.json()["indicators"])
    summary_response = request("GET", "/api/v1/dashboard/summary")
    assert summary_response.status_code == 200
    assert all(item["candidate_records"] is None for item in summary_response.json()["summary"]["indicator_counts"])


def test_pagination_filters_and_sorting_are_deterministic():
    first = request("GET", "/api/v1/cases?page=1&page_size=2&sort_by=risk_score&sort_order=desc").json()
    second = request("GET", "/api/v1/cases?page=2&page_size=2&sort_by=risk_score&sort_order=desc").json()
    all_items = request("GET", "/api/v1/cases?page_size=100").json()["items"]
    first_ids = [item["case_id"] for item in first["items"]]
    second_ids = [item["case_id"] for item in second["items"]]
    assert not set(first_ids) & set(second_ids)
    assert first_ids + second_ids == [item["case_id"] for item in all_items[:4]]
    # A withheld index (too few assessed checks) is null, never a fabricated number,
    # and sorts after every numeric index.
    scores = [item["risk_score"] for item in all_items]
    numeric = [score for score in scores if score is not None]
    assert numeric and scores == numeric + [None] * (len(scores) - len(numeric))
    assert numeric == sorted(numeric, reverse=True)
    assert all(item["score_status"] in {"insufficient_assessed_indicators", "not_assessable"}
               for item in all_items if item["risk_score"] is None)

    repeat = request("GET", "/api/v1/cases?indicator=repeat_billing_candidate").json()
    assert all("repeat_billing_candidate" in item["indicators"] for item in repeat["items"])
    assert request("GET", "/api/v1/cases?status=in_review").json()["pagination"]["total_items"] == 0
    assert request("GET", "/api/v1/cases?risk_level=high").json()["pagination"]["total_items"] == 0
    invalid = request("GET", "/api/v1/cases?page_size=101")
    assert invalid.status_code == 400
    assert set(invalid.json()["error"]) == {"code", "message", "request_id", "details"}


def test_case_details_are_explainable_minimized_and_unknown_ids_are_404():
    listing = request("GET", "/api/v1/cases").json()["items"]
    case = request("GET", f"/api/v1/cases/{listing[0]['case_id']}").json()["case"]
    serialized = json.dumps(case, sort_keys=True)
    assert case["reasons"]
    assert all(reason["summary"] and reason["evidence"] for reason in case["reasons"])
    assert all(reason["limitations"] for reason in case["reasons"])
    assert "demo-person-" not in serialized
    assert "125000" not in serialized
    assert "DEMO-PROVINCE-01" not in serialized
    source_record = next(row for row in get_synthetic_records() if row["case_id"] == case["case_id"])
    for field, raw_value in source_record.items():
        if field != "case_id" and raw_value:
            assert str(raw_value) not in serialized
    assert case["risk_level"] is None and case["risk_score"] is not None
    assert case["score_status"] in {"assessed", "partial_coverage"}
    missing = request("GET", "/api/v1/cases/case_unknown")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "CASE_NOT_FOUND"


def test_evaluation_is_unavailable_without_a_report_and_has_no_metrics(monkeypatch, tmp_path):
    monkeypatch.setenv("CIR_EVALUATION_REPORT_DIR", str(tmp_path))
    result = request("GET", "/api/v1/evaluation").json()
    assert result["availability"] == "insufficient_data"
    assert result["evaluation"] is None
    assert any("Label acuan" in item for item in result["requirements_missing"])


def test_evaluation_serves_the_latest_synthetic_pipeline_report(monkeypatch, tmp_path):
    import json
    monkeypatch.setenv("CIR_EVALUATION_REPORT_DIR", str(tmp_path))
    (tmp_path / "current-pipeline-10-seed1.json").write_text(json.dumps(
        {"report": "cir-current-pipeline-synthetic-v1", "data_source": "synthetic_experiment_only", "precision": {"high": 1.0}}))
    (tmp_path / "current-pipeline-bad.json").write_text("{not json")
    result = request("GET", "/api/v1/evaluation").json()
    assert result["availability"] == "available"
    assert result["evaluation"]["precision"]["high"] == 1.0
    assert "sintetis" in result["notice"]


def test_results_repeat_consistently_and_period_filter_validation_is_explicit():
    first = request("GET", "/api/v1/dashboard/summary").json()
    second = request("GET", "/api/v1/dashboard/summary").json()
    first.pop("generated_at")
    second.pop("generated_at")
    assert first == second
    filtered = request(
        "GET", "/api/v1/dashboard/summary?period_from=2026-01-01&period_to=2026-12-31"
    ).json()
    assert filtered["summary"]["claims_reviewed"] == 0
    assert filtered["summary"]["cases_in_queue"] == 0
    assert request(
        "GET", "/api/v1/dashboard/summary?period_from=2026-02-01&period_to=2026-01-01"
    ).status_code == 400


def test_application_code_does_not_import_dataset_io_or_legacy_analysis_scripts():
    app_root = Path(__file__).parents[1] / "app"
    forbidden = {
        "pandas", "numpy", "pyreadstat", "subprocess",
        "inspect_metadata", "profile_fkrtl", "detect_repeat_candidates",
        "detect_cloning_candidates", "detect_cloning_v2",
    }
    for source_path in app_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = {alias.name.split(".")[0] for alias in node.names}
                assert not imported & forbidden
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    assert node.func.id not in {
                        "open", "read_csv", "read_parquet", "read_excel", "read_pickle"
                    }
                elif isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in {
                        "read_csv", "read_parquet", "read_excel", "read_pickle"
                    }
