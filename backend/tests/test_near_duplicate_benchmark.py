from scripts.evaluate_near_duplicate_candidates import build_fixture, evaluate
from app.analytics.near_duplicate_claims import NearDuplicateConfig, detect_near_duplicate_claims
from app.analytics.risk_scoring import DETECTOR_ORDER, score_claims


def test_synthetic_pair_benchmark_has_known_positive_and_legitimate_negative_controls():
    records, labels = build_fixture(100, seed=19)
    result = detect_near_duplicate_claims(records, NearDuplicateConfig(max_pair_comparisons=5000))
    predicted = {tuple(sorted(item["case_ids"])) for item in result["candidates"]}

    assert all(not any(key in row for key in ("is_anomaly", "scenario", "ground_truth")) for row in records)
    assert all("positive" not in row["case_id"] and "negative" not in row["case_id"] for row in records)
    assert len(labels["positive_pairs"]) == 25
    assert len(labels["negative_pairs"]) == 25
    assert labels["positive_pairs"].issubset(predicted)
    assert not labels["negative_pairs"].intersection(predicted)
    assert result["search_truncated"] is False


def test_synthetic_pair_benchmark_reports_budgeted_pairs_as_unassessed_and_is_deterministic():
    first = evaluate(1000, 25, seed=23)
    second = evaluate(1000, 25, seed=23)

    assert first == second
    assert first["pair_comparisons"] <= 25
    assert first["search_truncated"] is True
    assert first["positive_pairs_not_generated_by_bounded_block_search"] > 0
    assert first["positive_pairs_checked_but_failed_threshold"] == 0
    assert first["positive_pair_discovery_rate"] < 1
    assert first["negative_control_pairs_actually_similarity_checked"] >= 0


def test_evaluator_separates_generation_similarity_and_uncovered_pairs():
    result = evaluate(100, 100, seed=29)

    assert result["ground_truth_positive_pair_count"] == 25
    assert result["positive_pairs_discovered_by_candidate_generation"] == 25
    assert result["positive_pairs_actually_similarity_checked"] == 25
    assert result["positive_pairs_checked_and_passed_threshold"] == 25
    assert result["positive_pairs_not_generated_by_bounded_block_search"] == 0
    assert result["negative_control_pairs_actually_similarity_checked"] == 25
    assert result["negative_control_pairs_predicted"] == 0
    assert result["positive_pair_discovery_rate"] == 1


def test_evaluator_keeps_budget_uncovered_separate_from_threshold_misses():
    result = evaluate(1000, 25, seed=31)

    assert result["positive_pairs_discovered_by_candidate_generation"] == (
        result["positive_pairs_actually_similarity_checked"]
        + result["positive_pairs_generated_but_not_similarity_checked"]
    )
    assert result["positive_pairs_actually_similarity_checked"] == (
        result["positive_pairs_checked_and_passed_threshold"]
        + result["positive_pairs_checked_but_failed_threshold"]
    )
    assert result["ground_truth_positive_pair_count"] == (
        result["positive_pairs_discovered_by_candidate_generation"]
        + result["positive_pairs_not_generated_by_bounded_block_search"]
    )


def test_candidate_quality_metrics_are_invariant_to_input_order():
    forward = evaluate(1000, 100, seed=37)
    reversed_result = evaluate(1000, 100, seed=37, reverse_input=True)

    metric_fields = (
        "ground_truth_positive_pair_count",
        "ground_truth_negative_pair_count",
        "positive_pairs_discovered_by_candidate_generation",
        "positive_pairs_actually_similarity_checked",
        "positive_pairs_checked_and_passed_threshold",
        "positive_pairs_not_generated_by_bounded_block_search",
        "negative_control_pairs_actually_similarity_checked",
        "negative_control_pairs_predicted",
    )
    assert {field: forward[field] for field in metric_fields} == {
        field: reversed_result[field] for field in metric_fields
    }


def test_near_duplicate_pair_results_do_not_depend_on_input_order():
    records, _labels = build_fixture(120, seed=41)
    config = NearDuplicateConfig(max_pair_comparisons=5000)

    assert detect_near_duplicate_claims(records, config) == detect_near_duplicate_claims(
        list(reversed(records)), config,
    )


def test_budget_exhausted_block_is_reported_as_truncated_and_unassessed():
    base = {
        "service_date": "2024-04-12", "province_code": "SYN-PROV-01",
        "municipality_code": "SYN-MUNI-001", "facility_ownership": "synthetic-public",
        "facility_type": "synthetic-general", "facility_class": "synthetic-class-a",
        "admission_diagnosis": "SYN-AD-001", "primary_diagnosis": "SYN-DX-001",
        "claim_group": "SYN-GROUP-001", "procedure_code": "SYN-PROC-001",
        "billed_amount": "125000",
    }
    records = [{
        **base,
        "case_id": f"syn-case-{index:03d}",
        "participant_token": f"syn-participant-{index:03d}",
        "facility_id": "syn-facility-01",
        "service_type": "synthetic-service",
    } for index in range(3)]
    detector_result = detect_near_duplicate_claims(
        records, NearDuplicateConfig(max_pair_comparisons=1, max_candidates=10),
    )

    diagnostics = detector_result["search_diagnostics"]
    # Three valid pairs cannot fit a budget of one: the block is sampled, and an
    # exhausted budget is a hard truncation (the former stratified mode hid this).
    assert diagnostics["hard_search_limit_hit"] is True
    assert diagnostics["sampled_unit_count"] >= 1  # one unit per blocking key
    assert diagnostics["stratified_sampling_left_unassessed"] is True
    assert diagnostics["stratified_sampling_unassessed_case_count"] == 3
    assert diagnostics["assessment_incomplete"] is True
    assert detector_result["search_truncated"] is True
    assert not any("syn-case-" in str(value) for value in diagnostics.values())

    detector_results = {
        indicator: {
            "indicator": indicator,
            "input_record_count": len(records),
            "candidate_groups" if indicator in {"repeat_billing_candidate", "similar_claim_pattern_candidate"} else "candidates": [],
            "ineligible_cases": [],
        }
        for indicator in DETECTOR_ORDER
    }
    detector_results["near_duplicate_claim_candidate"] = detector_result
    scored = score_claims(records, detector_results)
    coverage = next(
        item for item in scored["detector_coverage"]
        if item["indicator"] == "near_duplicate_claim_candidate"
    )
    assert coverage["status"] == "partial"
    assert coverage["search_truncated"] is True
    # The one compared pair is three identical claims' common combination, so it flags nobody and
    # all three records in the sampled unit stay unassessed (formerly the pair flagged two).
    assert coverage["not_assessed_case_count"] == 3
