from copy import deepcopy

import pytest

import app.analytics.evaluation as evaluation
from app.analytics.near_duplicate_claims import NearDuplicateConfig, detect_near_duplicate_claims
from app.analytics.risk_scoring import DETECTOR_ORDER
from app.data_sources.synthetic_benchmark_generator import (
    SyntheticBenchmarkProfile,
    generate_synthetic_benchmark_dataset,
)
from app.data_sources.synthetic_generator import SyntheticGeneratorConfig, generate_synthetic_dataset


def _dataset(seed=2026):
    config = SyntheticGeneratorConfig(seed=seed, claim_count=250, facility_count=12, target_anomaly_rate=0.04)
    return generate_synthetic_dataset(config)


def test_confusion_metrics_and_undefined_denominators_are_explicit():
    metrics = evaluation.confusion_metrics({"a", "b"}, {"a", "c"}, {"a", "b", "c", "d"})
    assert (metrics["tp"], metrics["fp"], metrics["tn"], metrics["fn"]) == (1, 1, 1, 1)
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["f1_score"] == 0.5
    assert metrics["false_positive_rate"] == 0.5

    no_predictions = evaluation.confusion_metrics({"a"}, set(), {"a", "b"})
    assert no_predictions["precision"] is None
    assert no_predictions["recall"] == 0.0
    assert no_predictions["f1_score"] is None
    no_positive_truth = evaluation.confusion_metrics(set(), {"b"}, {"a", "b"})
    assert no_positive_truth["recall"] is None
    assert no_positive_truth["f1_score"] is None
    no_negative_truth = evaluation.confusion_metrics({"a"}, {"a"}, {"a"})
    assert no_negative_truth["false_positive_rate"] is None


def test_actual_synthetic_suite_reports_all_detectors_and_facility_ranking():
    data = _dataset(321)
    original_records = deepcopy(data.records)
    original_truth = deepcopy(data.ground_truth.claim_labels)
    report = evaluation.evaluate_synthetic_dataset(
        data.records, data.facilities, data.ground_truth,
        seed=321, generator_version=data.metadata["generator_version"],
        target_anomaly_rate=0.04, audit_budget_fraction=0.25, random_seed_count=7,
    )
    repeated = evaluation.evaluate_synthetic_dataset(
        data.records, data.facilities, data.ground_truth,
        seed=321, generator_version=data.metadata["generator_version"],
        target_anomaly_rate=0.04, audit_budget_fraction=0.25, random_seed_count=7,
    )

    assert report == repeated
    assert report["data_source"] == "synthetic_experiment_only"
    assert report["metadata"]["generator_version"] == "3"
    assert report["metadata"]["synthetic_anomaly_claim_count"] == 10
    assert set(report["detectors"]) == set(DETECTOR_ORDER)
    assert report["combined"]["metrics"]["evaluated_count"] <= len(data.records)
    ranking = report["priority_ranking"]
    budget = ranking["budgets"]["0.2500"]
    assert budget["shared_budget_k"] == 3
    assert budget["approaches"]["random_baseline"]["seed_count"] == 7
    assert budget["approaches"]["simple_rule_flagged_claim_count"]["k"] == 3
    assert budget["approaches"]["claim_integrity_radar_priority"]["k"] == 3
    assert report["detectors"]["supporting_evidence_completeness_candidate"]["supported_scenarios"] == [
        "phantom_physiotherapy", "action_without_support", "mixed_light_severe",
    ]
    repeat = report["detectors"]["repeat_billing_candidate"]
    assert repeat["coverage"]["applicable_count"] == 2 + 240
    assert repeat["coverage"]["not_applicable_anomaly_count"] == 8
    assert repeat["metrics_target_scenarios_vs_normal"]["positive_label_count"] == 2
    assert "fraud_probability" not in str(report)
    assert any("not a fraud probability" in item for item in report["limitations"])
    assert "participant_token" not in str(report)
    assert "syn-claim-" not in str(report)
    assert data.records == original_records
    assert data.ground_truth.claim_labels == original_truth


def test_detector_and_scoring_boundary_never_receives_ground_truth(monkeypatch):
    data = _dataset(412)
    observed = {}
    original_score_claims = evaluation.score_claims

    def detector_spy(records, facilities):
        observed["feature_keys"] = set().union(*(set(row) for row in records))
        observed["facility_count"] = len(facilities)
        return {
            indicator: {
                "indicator": indicator,
                "input_record_count": len(records),
                **({"candidate_groups": []} if indicator in {"repeat_billing_candidate", "similar_claim_pattern_candidate"} else {"candidates": []}),
                "ineligible_cases": [],
            }
            for indicator in DETECTOR_ORDER
        }

    def scoring_spy(records, detector_results):
        observed["scoring_feature_keys"] = set().union(*(set(row) for row in records))
        observed["scoring_detector_count"] = len(detector_results)
        return original_score_claims(records, detector_results)

    monkeypatch.setattr(evaluation, "run_detector_suite", detector_spy)
    monkeypatch.setattr(evaluation, "score_claims", scoring_spy)
    report = evaluation.evaluate_synthetic_dataset(
        data.records, data.facilities, data.ground_truth,
        seed=412, generator_version="3", target_anomaly_rate=0.04,
        random_seed_count=2,
    )
    assert not (observed["feature_keys"] & evaluation._FORBIDDEN_FEATURE_KEYS)
    assert not (observed["scoring_feature_keys"] & evaluation._FORBIDDEN_FEATURE_KEYS)
    assert observed["facility_count"] == len(data.facilities)
    assert observed["scoring_detector_count"] == len(DETECTOR_ORDER)
    assert report["combined"]["metrics"]["predicted_positive_count"] == 0


def test_truncated_detector_search_does_not_count_unseen_claims_as_true_negatives(monkeypatch):
    data = _dataset(509)

    def detector_spy(records, facilities):
        output = {}
        for indicator in DETECTOR_ORDER:
            result = {
                "indicator": indicator,
                "input_record_count": len(records),
                **({"candidate_groups": []} if indicator in {"repeat_billing_candidate", "similar_claim_pattern_candidate"} else {"candidates": []}),
                "ineligible_cases": [],
            }
            if indicator == "near_duplicate_claim_candidate":
                result["search_truncated"] = True
                result["pair_comparisons"] = 5000
            output[indicator] = result
        return output

    monkeypatch.setattr(evaluation, "run_detector_suite", detector_spy)
    report = evaluation.evaluate_synthetic_dataset(
        data.records, data.facilities, data.ground_truth,
        seed=509, generator_version="3", target_anomaly_rate=0.04,
        random_seed_count=2,
    )
    near = report["detectors"]["near_duplicate_claim_candidate"]
    assert near["coverage"]["search_truncated"] is True
    assert near["coverage"]["eligible_count"] == 0
    assert near["coverage"]["unassessed_count"] == near["coverage"]["applicable_count"]
    assert near["metrics_target_scenarios_vs_normal"]["tn"] == 0
    assert near["metrics_target_scenarios_vs_normal"]["evaluated_count"] == 0
    assert report["combined"]["coverage"]["status"] == "partial"


def test_explicit_unassessed_positive_and_negative_are_excluded_from_detector_metrics():
    base = {
        "service_date": "2024-04-12", "province_code": "SYN-PROV-01",
        "municipality_code": "SYN-MUNI-001", "facility_ownership": "synthetic-public",
        "facility_type": "synthetic-general", "facility_class": "synthetic-class-a",
        "admission_diagnosis": "SYN-AD-001", "primary_diagnosis": "SYN-DX-001",
        "claim_group": "SYN-GROUP-001", "procedure_code": "SYN-PROC-001",
        "billed_amount": "125000",
    }
    records = []
    for index in range(4):
        records.append({
            **base,
            "case_id": f"syn-pair-{chr(ord('a') + index)}",
            "participant_token": f"syn-participant-{index}",
        })
    scope = {row["case_id"] for row in records}
    # A low-budget, four-record synthetic block reproduces stratified
    # sampling: the detector explicitly reports the block as unassessed even
    # though the hard comparison-cap flag is false.
    result = detect_near_duplicate_claims(
        records, NearDuplicateConfig(max_pair_comparisons=1, max_candidates=10),
    )

    predicted, eligible, coverage = evaluation._detector_coverage(
        "near_duplicate_claim_candidate", result, scope,
    )
    missed = sorted(scope - predicted)
    assert len(missed) == 2
    actual_positive = {next(iter(predicted)), missed[0]}
    metrics = evaluation.confusion_metrics(
        actual_positive, predicted, eligible, scope,
    )

    assert len(predicted) == 2
    assert eligible == predicted
    assert result["search_diagnostics"]["stratified_block_sampling"] is True
    assert len(result["unassessed_case_ids"]) == 4
    assert result["search_truncated"] is False
    assert coverage["status"] == "partial"
    assert coverage["search_truncated"] is False
    assert coverage["unassessed_count"] == 2
    assert metrics["tp"] == 1
    assert metrics["fp"] == 1
    assert metrics["fn"] == 0
    assert metrics["tn"] == 0
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 1.0
    assert metrics["evaluated_count"] == 2
    assert metrics["unassessed_positive_label_count"] == 1
    assert metrics["unassessed_negative_label_count"] == 1


def test_label_and_feature_ids_must_match_and_labels_cannot_be_feature_fields():
    data = _dataset(611)
    corrupted = deepcopy(data.records)
    corrupted[0]["is_synthetic_anomaly"] = True
    with pytest.raises(ValueError, match="Ground-truth field"):
        evaluation.evaluate_synthetic_dataset(
            corrupted, data.facilities, data.ground_truth,
            seed=611, generator_version="3", target_anomaly_rate=0.04,
        )

    labels = deepcopy(data.ground_truth.claim_labels)
    labels.pop()
    with pytest.raises(ValueError, match="ID label dan fitur"):
        evaluation.evaluate_synthetic_dataset(
            data.records, data.facilities, {"claim_labels": labels},
            seed=611, generator_version="3", target_anomaly_rate=0.04,
        )


def test_evaluation_parameters_reject_invalid_budget_and_random_seed_count():
    data = _dataset(712)
    with pytest.raises(ValueError, match="audit budget"):
        evaluation.evaluate_synthetic_dataset(
            data.records, data.facilities, data.ground_truth,
            seed=712, generator_version="3", target_anomaly_rate=0.04,
            audit_budget_fraction=0,
        )


def test_detector_scenario_mapping_keeps_other_anomalies_out_of_negative_population():
    expected = {
        "repeat_billing_candidate": ("repeat_billing",),
        "similar_claim_pattern_candidate": ("mixed_light_severe",),
        "near_duplicate_claim_candidate": ("cloning", "mixed_light_severe"),
        "synthetic_capacity_candidate": ("mixed_light_severe",),
        "temporal_pattern_candidate": ("repeat_billing", "cloning", "mixed_light_severe"),
        "supporting_evidence_completeness_candidate": (
            "phantom_physiotherapy", "action_without_support", "mixed_light_severe",
        ),
    }
    assert evaluation.SUPPORTED_SCENARIOS == expected

    data = _dataset(321)
    report = evaluation.evaluate_synthetic_dataset(
        data.records, data.facilities, data.ground_truth,
        seed=321, generator_version="3", target_anomaly_rate=0.04,
        random_seed_count=2,
    )
    for indicator, scenarios in expected.items():
        result = report["detectors"][indicator]
        labels = data.ground_truth.claim_labels
        expected_positive = sum(
            label["is_synthetic_anomaly"] and label["primary_scenario"] in scenarios
            for label in labels
        )
        assert result["metrics_target_scenarios_vs_normal"]["positive_label_count"] <= expected_positive
        assert result["coverage"]["not_applicable_anomaly_count"] == 10 - expected_positive


def test_benchmark_generator_v4_has_seeded_sparse_positive_facilities_and_balanced_volume():
    config = SyntheticGeneratorConfig(seed=909, claim_count=2500, facility_count=20, target_anomaly_rate=0.04)
    profile = SyntheticBenchmarkProfile(positive_facility_fraction=0.20)
    first = generate_synthetic_benchmark_dataset(config, profile)
    second = generate_synthetic_benchmark_dataset(config, profile)

    assert first.records == second.records
    assert first.facilities == second.facilities
    assert first.ground_truth.claim_labels == second.ground_truth.claim_labels
    assert first.ground_truth.facility_labels == second.ground_truth.facility_labels
    assert first.metadata["generator_version"] == "4"
    assert first.metadata["base_generator_version"] == "3"
    labels = first.ground_truth.facility_labels
    assert labels is not None
    positives = [item for item in labels if item["is_synthetic_anomaly_facility"]]
    negatives = [item for item in labels if not item["is_synthetic_anomaly_facility"]]
    assert len(positives) == 4
    assert len(negatives) == 16
    assert all(item["anomaly_claim_count"] > 0 for item in positives)
    assert all(item["anomaly_claim_count"] == 0 for item in negatives)

    claims_per_facility = {}
    record_by_id = {row["case_id"]: row for row in first.records}
    for row in first.records:
        claims_per_facility[row["facility_id"]] = claims_per_facility.get(row["facility_id"], 0) + 1
    assert max(claims_per_facility.values()) - min(claims_per_facility.values()) <= 1
    assert len({item["facility_id"] for item in positives}) == 4
    assert len({item["facility_id"] for item in negatives}) == 16
    facility_type_by_id = {item["facility_id"]: item["facility_type"] for item in first.facilities}
    positive_type_counts = {}
    for item in positives:
        value = facility_type_by_id[item["facility_id"]]
        positive_type_counts[value] = positive_type_counts.get(value, 0) + 1
    assert max(positive_type_counts.values()) - min(positive_type_counts.values()) <= 1

    control = next(item for item in first.ground_truth.group_labels if item["scenario_code"] == "legitimate_repeat_control")
    control_facilities = {record_by_id[case_id]["facility_id"] for case_id in control["case_ids"]}
    assert len(control_facilities) == 1
    assert next(iter(control_facilities)) in {item["facility_id"] for item in negatives}
    forbidden = evaluation._FORBIDDEN_FEATURE_KEYS
    assert all(not (set(row) & forbidden) for row in first.records)


def test_v4_ranking_uses_claim_derived_facility_labels_and_multiple_shared_k_values():
    data = generate_synthetic_benchmark_dataset(
        SyntheticGeneratorConfig(seed=1010, claim_count=2500, facility_count=20),
        SyntheticBenchmarkProfile(positive_facility_fraction=0.20),
    )
    report = evaluation.evaluate_synthetic_dataset(
        data.records, data.facilities, data.ground_truth,
        seed=1010, generator_version=data.metadata["generator_version"],
        target_anomaly_rate=data.metadata["target_anomaly_rate"],
        generator_metadata=data.metadata,
        audit_budget_fractions=(0.10, 0.20, 0.30),
        random_seed_count=9,
    )
    ranking = report["priority_ranking"]
    assert ranking["anomaly_facility_count"] == 4
    assert ranking["negative_facility_count_from_claim_labels"] == 16
    assert ranking["anomaly_facility_prevalence"] == 0.2
    assert ranking["budgets"]["0.1000"]["shared_budget_k"] == 2
    assert ranking["budgets"]["0.2000"]["shared_budget_k"] == 4
    assert ranking["budgets"]["0.3000"]["shared_budget_k"] == 6
    for budget in ranking["budgets"].values():
        k_values = {item["k"] for method, item in budget["approaches"].items() if method != "random_baseline"}
        assert k_values == {budget["shared_budget_k"]}
        assert budget["approaches"]["random_baseline"]["seed_count"] == 9
    assert report["metadata"]["generator_configuration"]["benchmark_profile"] == "facility-stratified-sparse-positive-v1"
    with pytest.raises(ValueError, match="random_seed_count"):
        evaluation.evaluate_synthetic_dataset(
            data.records, data.facilities, data.ground_truth,
            seed=712, generator_version="3", target_anomaly_rate=0.04,
            random_seed_count=0,
        )
