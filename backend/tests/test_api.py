"""Integration checks for the synthetic analytics API."""

import asyncio
import ast
import json
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

import httpx

from app.analytics.repeat_billing import detect_repeat_billing_candidates
from app.analytics.similar_claim_pattern import detect_similar_claim_patterns
from app.data_sources.synthetic import get_synthetic_records
from app.main import create_app
from app.services.analytics import build_analytics_snapshot


TEST_APP = create_app(Path(gettempdir()) / f"cir-api-tests-{uuid4().hex}.sqlite3")


def request(method: str, path: str):
    async def send():
        transport = httpx.ASGITransport(app=TEST_APP, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path)

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
        "availability", "data_source", "generated_at", "period", "summary", "notice"
    }
    assert set(responses["analysis"].json()) == {
        "availability", "data_source", "generated_at", "filters", "coverage",
        "indicators", "planned_indicators", "limitations",
    }
    assert set(responses["cases"].json()) == {
        "availability", "data_source", "items", "pagination", "applied_filters", "notice"
    }
    assert set(responses["detail"].json()) == {"availability", "data_source", "case", "notice"}
    assert set(responses["evaluation"].json()) == {
        "availability", "data_source", "generated_at", "evaluation",
        "requirements_missing", "notice",
    }
    for response in responses.values():
        assert response.json()["data_source"] == {"kind": "synthetic", "label": "synthetic_demo"}


def test_health_contract_is_unchanged():
    response = request("GET", "/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok", "service": "claim-integrity-radar-api", "version": "0.1.0"
    }


def test_dashboard_and_analysis_counts_are_calculated_by_both_detectors():
    records = get_synthetic_records()
    repeat = detect_repeat_billing_candidates(records)
    similar = detect_similar_claim_patterns(records)
    snapshot = build_analytics_snapshot()
    summary = request("GET", "/api/v1/dashboard/summary").json()
    analysis_result = request("GET", "/api/v1/analysis").json()

    assert summary["summary"]["claims_reviewed"] == len(records)
    assert summary["summary"]["cases_in_queue"] == len(snapshot["cases"])
    assert summary["summary"]["risk_level_counts"] == {"high": None, "medium": None, "low": None}
    expected = {
        "repeat_billing_candidate": repeat,
        "similar_claim_pattern_candidate": similar,
    }
    for item in analysis_result["indicators"]:
        result = expected[item["code"]]
        candidate_ids = {
            case_id for group in result["candidate_groups"] for case_id in group["case_ids"]
        }
        assert item["candidate_count"] == len(candidate_ids)
        assert item["candidate_group_count"] == len(result["candidate_groups"])
        assert item["eligible_count"] == result["input_record_count"] - len(result["ineligible_cases"])


def test_pagination_filters_and_sorting_are_deterministic():
    first = request("GET", "/api/v1/cases?page=1&page_size=2&sort_by=risk_score&sort_order=desc").json()
    second = request("GET", "/api/v1/cases?page=2&page_size=2&sort_by=risk_score&sort_order=desc").json()
    all_items = request("GET", "/api/v1/cases?page_size=100").json()["items"]
    first_ids = [item["case_id"] for item in first["items"]]
    second_ids = [item["case_id"] for item in second["items"]]
    assert not set(first_ids) & set(second_ids)
    assert first_ids + second_ids == sorted(item["case_id"] for item in all_items[:4])
    assert [item["case_id"] for item in all_items] == sorted(item["case_id"] for item in all_items)

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
    assert case["risk_level"] is None and case["risk_score"] is None
    missing = request("GET", "/api/v1/cases/case_unknown")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "CASE_NOT_FOUND"


def test_evaluation_is_unavailable_without_ground_truth_and_has_no_metrics():
    result = request("GET", "/api/v1/evaluation").json()
    assert result["availability"] == "insufficient_data"
    assert result["evaluation"] is None
    assert any("Label acuan" in item for item in result["requirements_missing"])


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
