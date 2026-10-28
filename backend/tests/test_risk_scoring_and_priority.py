from copy import deepcopy

import pytest

from app.analytics.audit_priority import AuditEffortConfig, build_audit_priority_queue
from app.analytics.risk_scoring import (
    DETECTOR_ORDER,
    RiskScoringConfig,
    run_detector_suite,
    score_claims,
)
from app.data_sources.synthetic_generator import SyntheticGeneratorConfig, generate_synthetic_dataset


def _rows():
    return [
        {
            "case_id": "syn-case-a", "participant_token": "syn-person-a", "facility_id": "syn-fac-2",
            "service_date": "2024-02-01", "service_type": "synthetic", "billed_amount": "100.00",
        },
        {
            "case_id": "syn-case-b", "participant_token": "syn-person-b", "facility_id": "syn-fac-2",
            "service_date": "2024-02-01", "service_type": "synthetic", "billed_amount": "200.00",
        },
        {
            "case_id": "syn-case-c", "participant_token": "syn-person-c", "facility_id": "syn-fac-2",
            "service_date": "2024-02-01", "service_type": "synthetic", "billed_amount": "300.00",
        },
    ]


def _empty_results(records):
    results = {}
    for indicator in DETECTOR_ORDER:
        results[indicator] = {
            "indicator": indicator,
            "input_record_count": len(records),
            "candidate_groups": [] if indicator in {"repeat_billing_candidate", "similar_claim_pattern_candidate"} else None,
            "candidates": [] if indicator not in {"repeat_billing_candidate", "similar_claim_pattern_candidate"} else None,
            "ineligible_cases": [],
        }
        if indicator in {"repeat_billing_candidate", "similar_claim_pattern_candidate"}:
            results[indicator].pop("candidates")
        else:
            results[indicator].pop("candidate_groups")
    return results


def test_one_indicator_and_custom_weight_follow_normalized_weighted_formula():
    rows = _rows()
    results = _empty_results(rows)
    results["repeat_billing_candidate"]["candidate_groups"] = [{
        "group_id": "repeat-billing-0001",
        "case_ids": ["syn-case-a"],
        "reason": "Synthetic repeat signal.",
        "matched_attributes": ["service_date"],
    }]
    weights = {indicator: 1 for indicator in DETECTOR_ORDER}
    weights["repeat_billing_candidate"] = 3
    scored = score_claims(rows, results, RiskScoringConfig(weights=weights))
    first = next(item for item in scored["cases"] if item["case_id"] == "syn-case-a")

    assert first["risk_score"] == round(3 / (3 + len(DETECTOR_ORDER) - 1), 6)  # 3 / (3 + the other checks at 1)
    assert first["triggered_indicators"] == ["repeat_billing_candidate"]
    assert first["indicator_reasons"][0]["reason"] == "Synthetic repeat signal."
    assert first["score_version"] == "rule-risk-index-v2-provisional"


def test_many_near_pairs_contribute_once_and_claim_value_is_deduplicated():
    rows = _rows()
    original_rows = deepcopy(rows)
    results = _empty_results(rows)
    results["repeat_billing_candidate"]["candidate_groups"] = [{
        "group_id": "repeat-1", "case_ids": ["syn-case-a"], "reason": "Repeat candidate.",
    }]
    results["near_duplicate_claim_candidate"]["candidates"] = [
        {"candidate_id": "pair-a-b", "case_ids": ["syn-case-a", "syn-case-b"], "reason": "Near pair 1."},
        {"candidate_id": "pair-a-c", "case_ids": ["syn-case-a", "syn-case-c"], "reason": "Near pair 2."},
    ]
    scores = score_claims(rows, results)
    case_a = next(item for item in scores["cases"] if item["case_id"] == "syn-case-a")
    queue = build_audit_priority_queue(rows, scores)
    unit = queue["items"][0]

    assert case_a["risk_score"] == round(2 / len(DETECTOR_ORDER), 6)
    assert case_a["triggered_indicators"] == ["repeat_billing_candidate", "near_duplicate_claim_candidate"]
    assert unit["claim_value"]["amount"] == "600.00"  # a is counted once despite two near pairs and repeat
    assert unit["claim_value"]["unique_claim_count"] == 3
    assert unit["audit_effort"]["recommended_record_files"] == 3
    assert unit["risk_score"] == round(2 / len(DETECTOR_ORDER), 6)
    assert unit["priority_index"] == round(round(2 / len(DETECTOR_ORDER), 6) * 600 / 3, 8)
    assert rows == original_rows


def test_priority_order_changes_with_claim_value_and_uses_case_id_for_ties():
    rows = _rows() + [{
        "case_id": "syn-case-d", "participant_token": "syn-person-d", "facility_id": "syn-fac-1",
        "service_date": "2024-02-01", "service_type": "synthetic", "billed_amount": "1000.00",
    }]
    results = _empty_results(rows)
    results["repeat_billing_candidate"]["candidate_groups"] = [{
        "group_id": "repeat", "case_ids": ["syn-case-a", "syn-case-b", "syn-case-c", "syn-case-d"],
        "reason": "Synthetic repeat signal.",
    }]
    scores = score_claims(rows, results)
    first = build_audit_priority_queue(rows, scores)
    assert first["items"][0]["unit_id"] == "synthetic-audit-unit:syn-fac-1"

    cheaper = deepcopy(rows)
    next(row for row in cheaper if row["case_id"] == "syn-case-d")["billed_amount"] = "100.00"
    second = build_audit_priority_queue(cheaper, scores)
    assert second["items"][0]["unit_id"] == "synthetic-audit-unit:syn-fac-2"

    tie_rows = [
        {"case_id": "syn-case-z", "participant_token": "syn-person-z", "facility_id": "syn-fac-1", "billed_amount": "100.00"},
        {"case_id": "syn-case-a", "participant_token": "syn-person-a", "facility_id": "syn-fac-9", "billed_amount": "100.00"},
    ]
    tie_results = _empty_results(tie_rows)
    tie_results["repeat_billing_candidate"]["candidate_groups"] = [{
        "group_id": "repeat-tie", "case_ids": ["syn-case-a", "syn-case-z"], "reason": "Repeat.",
    }]
    tie_scores = score_claims(tie_rows, tie_results)
    tied_queue = build_audit_priority_queue(tie_rows, tie_scores)
    assert [item["tie_break_case_id"] for item in tied_queue["items"]] == ["syn-case-a", "syn-case-z"]


def test_invalid_claim_value_does_not_become_zero_or_a_fabricated_priority():
    rows = _rows()
    rows[0]["billed_amount"] = "not-a-number"
    results = _empty_results(rows)
    results["repeat_billing_candidate"]["candidate_groups"] = [{
        "group_id": "repeat-invalid-value", "case_ids": ["syn-case-a"], "reason": "Repeat.",
    }]
    scores = score_claims(rows, results)
    queue = build_audit_priority_queue(rows, scores)
    unit = queue["items"][0]

    assert unit["claim_value"]["amount"] is None
    assert unit["claim_value"]["status"] == "unavailable"
    assert unit["priority_index"] is None
    assert unit["priority_status"] == "not_assessable"


def test_missing_detectors_and_truncated_near_search_are_not_reported_as_no_signal():
    rows = _rows()
    none_scored = score_claims(rows, {})
    assert all(item["risk_score"] is None and item["score_status"] == "not_assessable" for item in none_scored["cases"])

    results = _empty_results(rows)
    results["near_duplicate_claim_candidate"]["search_truncated"] = True
    results["supporting_evidence_completeness_candidate"]["candidates"] = [{
        "case_id": "syn-case-a", "candidate_id": "evidence-a", "reason": "Recorded evidence missing.",
    }]
    partial = score_claims(rows, results)
    case_a = next(item for item in partial["cases"] if item["case_id"] == "syn-case-a")
    assert case_a["risk_score"] == round(1 / (len(DETECTOR_ORDER) - 1), 6)  # near search truncated
    assert case_a["score_status"] == "partial_coverage"
    assert {item["indicator"] for item in case_a["indicator_coverage"] if item["status"] == "not_assessed"} == {"near_duplicate_claim_candidate"}
    queue = build_audit_priority_queue(rows, partial)
    assert queue["items"][0]["priority_status"] == "not_assessable"
    assert queue["items"][0]["priority_index"] is None
    assert queue["items"][0]["eligibility_reasons"]
    assert any("terpotong" in limitation for limitation in queue["items"][0]["limitations"])


def test_priority_requires_facility_id_complete_coverage_and_all_valid_claim_values():
    rows = _rows()
    results = _empty_results(rows)
    results["repeat_billing_candidate"]["candidate_groups"] = [{
        "group_id": "repeat", "case_ids": ["syn-case-a", "syn-case-b"], "reason": "Repeat candidate.",
    }]
    scores = score_claims(rows, results)
    complete = build_audit_priority_queue(rows, scores)
    assert complete["status"] == "available"
    assert complete["eligible_unit_count"] == 1
    assert complete["items"][0]["priority_index"] is not None

    invalid_rows = deepcopy(rows)
    invalid_rows[1]["billed_amount"] = None
    invalid_scores = score_claims(invalid_rows, results)
    invalid = build_audit_priority_queue(invalid_rows, invalid_scores)
    assert invalid["items"][0]["priority_index"] is None
    assert any("billed_amount" in reason for reason in invalid["items"][0]["eligibility_reasons"])

    missing_facility = deepcopy(rows)
    for row in missing_facility:
        row.pop("facility_id")
    missing_scores = score_claims(missing_facility, results)
    unavailable = build_audit_priority_queue(missing_facility, missing_scores)
    assert unavailable["status"] == "not_assessable"
    assert unavailable["items"] == []
    assert unavailable["unassigned_triggered_case_count"] == 2
    assert unavailable["eligibility_reasons"]


def test_no_eligible_evidence_for_any_indicator_is_not_assessable():
    rows = _rows()
    results = _empty_results(rows)
    for indicator in DETECTOR_ORDER:
        results[indicator]["unassessed_cases"] = [{"case_id": row["case_id"], "reason": "Not assessed."} for row in rows]
    scored = score_claims(rows, results)
    assert all(item["risk_score"] is None for item in scored["cases"])


def test_effort_configuration_rejects_zero_or_negative_and_inputs_are_unchanged():
    with pytest.raises(ValueError):
        AuditEffortConfig(files_per_claim=0)
    with pytest.raises(ValueError):
        AuditEffortConfig(max_files_per_unit=0)
    rows = _rows()
    original = deepcopy(rows)
    results = _empty_results(rows)
    results["repeat_billing_candidate"]["candidate_groups"] = [{
        "group_id": "repeat", "case_ids": ["syn-case-a"], "reason": "Repeat.",
    }]
    scores = score_claims(rows, results)
    score_copy = deepcopy(scores)
    build_audit_priority_queue(rows, scores)
    assert rows == original
    assert scores == score_copy


def test_synthetic_detector_suite_and_scores_are_deterministic_and_do_not_leak_identifiers():
    dataset = generate_synthetic_dataset(SyntheticGeneratorConfig(seed=808, claim_count=250, facility_count=12))
    records_before = deepcopy(dataset.records)
    results = run_detector_suite(dataset.records, dataset.facilities)
    scores = score_claims(dataset.records, results)
    queue = build_audit_priority_queue(dataset.records, scores)
    repeat_scores = score_claims(dataset.records, run_detector_suite(dataset.records, dataset.facilities))

    assert tuple(results) == DETECTOR_ORDER
    assert scores == repeat_scores
    assert all(0 <= item["risk_score"] <= 1 for item in scores["cases"] if item["risk_score"] is not None)
    assert all("ground_truth" not in str(item) and "scenario_label" not in str(item) for item in scores["cases"])
    raw_tokens = {row["participant_token"] for row in dataset.records}
    assert not any(token in str(scores) for token in raw_tokens)
    assert not any(token in str(queue) for token in raw_tokens)
    assert dataset.records == records_before
    assert all(item["data_scope"] == "synthetic_experiment" for item in queue["items"])
