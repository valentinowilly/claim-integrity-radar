"""Coverage/result contract tests using isolated synthetic-only records."""

from app.analytics.risk_scoring import DETECTOR_ORDER, score_claims
from app.services.analytics import build_analytics_snapshot


def _records(count=1):
    return [
        {
            "case_id": f"syn-contract-{number:03d}",
            "participant_token": f"syn-person-{number:03d}",
            "service_date": "2024-04-12",
            "facility_id": "syn-facility-01",
            "service_type": "synthetic_service",
            "billed_amount": "100.00",
        }
        for number in range(count)
    ]


def _results(records):
    return {
        indicator: {
            "indicator": indicator,
            "input_record_count": len(records),
            "candidate_groups" if indicator in {"repeat_billing_candidate", "similar_claim_pattern_candidate"} else "candidates": [],
            "ineligible_cases": [],
        }
        for indicator in DETECTOR_ORDER
    }


def _state(scored, case_id, indicator):
    case = next(item for item in scored["cases"] if item["case_id"] == case_id)
    return next(item["status"] for item in case["indicator_coverage"] if item["indicator"] == indicator)


def test_complete_assessment_has_explicit_positive_or_negative_result():
    records = _records()
    results = _results(records)
    indicator = DETECTOR_ORDER[0]
    results[indicator]["candidate_groups"] = [{
        "group_id": "syn-group-1", "case_ids": [records[0]["case_id"]], "reason": "Synthetic trigger.",
    }]
    scored = score_claims(records, results)

    assert _state(scored, records[0]["case_id"], indicator) == "triggered"
    assert _state(scored, records[0]["case_id"], DETECTOR_ORDER[1]) == "not_triggered"
    assert scored["cases"][0]["risk_score"] is not None


def test_prerequisite_gap_is_unassessed_and_never_a_negative():
    records = _records()
    results = _results(records)
    indicator = DETECTOR_ORDER[0]
    results[indicator]["ineligible_cases"] = [{
        "case_id": records[0]["case_id"], "reason": "A required synthetic attribute is missing.",
    }]
    scored = score_claims(records, results)

    assert _state(scored, records[0]["case_id"], indicator) == "not_assessed"
    assert indicator in scored["cases"][0]["not_assessed_indicators"]


def test_explicit_not_applicable_is_separate_from_unassessed_and_score_denominator():
    records = _records()
    results = _results(records)
    indicator = DETECTOR_ORDER[0]
    results[indicator]["not_applicable_cases"] = [{
        "case_id": records[0]["case_id"], "reason": "No rule applies to this synthetic service.",
    }]
    scored = score_claims(records, results)

    assert _state(scored, records[0]["case_id"], indicator) == "not_applicable"
    assert indicator in scored["cases"][0]["not_applicable_indicators"]
    assert indicator not in scored["cases"][0]["assessed_indicators"]
    assert indicator not in scored["cases"][0]["not_assessed_indicators"]


def test_partial_unavailable_and_truncated_results_do_not_create_false_negatives():
    records = _records(2)
    results = _results(records)
    partial_indicator, unavailable_indicator, truncated_indicator = DETECTOR_ORDER[:3]
    results[partial_indicator]["status"] = "partial"
    results[unavailable_indicator]["status"] = "unavailable"
    results[truncated_indicator]["search_truncated"] = True
    results[truncated_indicator]["candidates"] = [{
        "candidate_id": "syn-pair", "case_ids": [records[0]["case_id"]], "reason": "Synthetic bounded result.",
    }]
    scored = score_claims(records, results)

    assert _state(scored, records[0]["case_id"], partial_indicator) == "not_assessed"
    assert _state(scored, records[0]["case_id"], unavailable_indicator) == "not_assessed"
    assert _state(scored, records[0]["case_id"], truncated_indicator) == "triggered"
    assert _state(scored, records[1]["case_id"], truncated_indicator) == "not_assessed"
    assert scored["cases"][1]["risk_score"] is not None
    assert scored["cases"][1]["score_status"] == "partial_coverage"


def test_no_assessable_indicators_preserves_null_score():
    records = _records()
    results = _results(records)
    for result in results.values():
        result["not_applicable_cases"] = [{"case_id": records[0]["case_id"], "reason": "Out of scope."}]
    scored = score_claims(records, results)

    assert scored["cases"][0]["risk_score"] is None
    assert scored["cases"][0]["score_status"] == "not_assessable"


def test_runtime_snapshot_exposes_independent_execution_and_coverage_dimensions():
    snapshot = build_analytics_snapshot()
    assert snapshot["execution_status"] == "partial"
    by_indicator = {item["indicator"]: item for item in snapshot["indicator_coverage"]}
    capacity = by_indicator["synthetic_capacity_candidate"]
    assert capacity["status"] == "partial"
    assert capacity["records_assessed"] == 0
    assert capacity["records_unassessed"] > 0

