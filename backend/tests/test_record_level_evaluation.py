from copy import deepcopy

import pytest

import app.analytics.record_level_evaluation as record_eval
from app.data_sources.synthetic_benchmark_generator import (
    SyntheticBenchmarkProfile,
    generate_synthetic_benchmark_dataset,
)
from app.data_sources.synthetic_generator import SyntheticGeneratorConfig


def _smoke_data():
    return generate_synthetic_benchmark_dataset(
        SyntheticGeneratorConfig(seed=2026, claim_count=1200, facility_count=20, target_anomaly_rate=0.04),
        SyntheticBenchmarkProfile(positive_facility_fraction=0.20),
    )


def _run(data, ground_truth=None):
    return record_eval.evaluate_record_level_comparison(
        data.records, data.facilities, ground_truth or data.ground_truth,
        k_values=(60, 120, 240), generator_version="4", generator_seed=2026,
        target_anomaly_rate=0.04, generator_metadata=data.metadata,
    )


def test_small_synthetic_comparison_runs_all_methods_and_k_without_identifier_output():
    data = _smoke_data()
    report = _run(data)
    assert report["data_source"] == "synthetic_experiment_only"
    assert report["metadata"]["claim_record_count"] == 1200
    assert report["metadata"]["facility_count"] == 20
    assert report["metadata"]["positive_synthetic_claim_record_count"] == 48
    assert report["metadata"]["selection_frozen_before_ground_truth"] is True
    assert report["metadata"]["selection_policy_version"] == "record-selection-v1"
    assert report["metadata"]["scoring_version"]
    assert report["metadata"]["priority_version"]
    assert len(report["detector_coverage"]) == 6
    assert all("not_assessed_case_count" in row and "search_truncated" in row for row in report["detector_coverage"])
    assert set(report["budgets"]) == {"60", "120", "240"}
    for k_text, budget in report["budgets"].items():
        k = int(k_text)
        methods = budget["methods"]
        random = methods["random_baseline"]
        assert random["seed_count"] == 30
        assert random["seeds"] == list(range(12026, 12056))
        assert len(random["per_seed"]) == 30
        assert all("tp" not in result["metrics"] and "tn" not in result["metrics"] for result in random["per_seed"])
        for result in random["per_seed"]:
            assert result["comparable"] is True
            assert result["selected_unique_record_count"] == k
            assert sum(result["metrics"]["selected_positive_record_count_by_scenario"].values()) == result["metrics"]["selected_positive_record_count"]
            assert result["metrics"]["precision_at_k"] == pytest.approx(result["metrics"]["positive_records_per_100_selected_records"] / 100, abs=1e-6)
        for name in ("simple_rule_repeat_billing", "cir_facility_priority"):
            result = methods[name]
            assert result["comparable"] is True
            assert result["selected_unique_record_count"] == k
            assert result["metrics"]["precision_at_k"] == pytest.approx(result["metrics"]["positive_records_per_100_selected_records"] / 100, abs=1e-6)
            assert result["selected_assessment"]["selected_record_count"] == k
            assert sum(result["metrics"]["selected_positive_record_count_by_scenario"].values()) == result["metrics"]["selected_positive_record_count"]
            path_keys = ("repeat_billing_rule", "exploratory_fallback") if name == "simple_rule_repeat_billing" else ("valid_facility_priority", "exploratory_fallback")
            assert sum(result["selection_counts"][key] for key in path_keys) == k
            assert sum(result["metrics"]["selected_positive_record_count_by_selection_path"].values()) == result["metrics"]["selected_positive_record_count"]
    serialized = str(report)
    assert "syn-claim-" not in serialized
    assert "syn-case-" not in serialized
    assert "participant_token" not in serialized
    assert "selected_case_ids" not in serialized
    pair_metrics = report["near_duplicate_diagnostics"]["pair_unit"]
    assert pair_metrics["planted_positive_pair_count"] == (
        pair_metrics["blocking_generated_positive_pair_count"]
        + pair_metrics["positive_pair_count_not_generated_by_blocking"]
    )
    assert pair_metrics["blocking_generated_positive_pair_count"] >= (
        pair_metrics["positive_pair_count_generated_but_not_compared"]
    )
    assert pair_metrics["blocking_generated_positive_pair_count"] == sum(
        pair_metrics[key] for key in (
            "positive_pair_count_generated_but_not_compared",
            "positive_pair_count_compared_below_threshold",
            "positive_pair_count_passed_but_not_returned",
            "positive_pair_count_accepted",
        )
    )
    assert report["near_duplicate_diagnostics"]["scenario_group_unit"]["planted_positive_group_count"] > 0
    priority_diag = report["facility_priority_diagnostics"]
    assert priority_diag["population_facility_count"] == 20
    assert priority_diag["priority_unit_count"] >= 0
    assert "priority_status_histogram" in priority_diag
    assert "priority_index_category_counts" in priority_diag
    assert (
        priority_diag["matched_priority_facility_id_count"]
        + priority_diag["unmatched_or_unparseable_priority_unit_count"]
        == priority_diag["priority_unit_count"]
    )
    for method in (
        report["budgets"]["60"]["methods"]["simple_rule_repeat_billing"],
        report["budgets"]["60"]["methods"]["cir_facility_priority"],
    ):
        assert "selection_path_assessment" in method["selected_assessment"]
    assert "syn-facility-" not in str(priority_diag)
    assert "syn-case-" not in str(priority_diag)
    assert "syn-case-" not in serialized
    assert "syn-claim-" not in serialized
    assert "syn-group-" not in serialized


def test_labels_are_only_joined_after_frozen_selection(monkeypatch):
    data = _smoke_data()
    original_selectors = (
        record_eval.random_selection,
        record_eval.simple_rule_selection,
        record_eval.cir_priority_selection,
    )
    captured = []

    def capture(fn):
        def wrapped(*args, **kwargs):
            selection = fn(*args, **kwargs)
            captured.append((selection.method, selection.requested_k, selection.selected_case_ids))
            return selection
        return wrapped

    monkeypatch.setattr(record_eval, "random_selection", capture(original_selectors[0]))
    monkeypatch.setattr(record_eval, "simple_rule_selection", capture(original_selectors[1]))
    monkeypatch.setattr(record_eval, "cir_priority_selection", capture(original_selectors[2]))
    first = _run(data)
    first_selections = list(captured)

    altered_truth = deepcopy(data.ground_truth)
    for label in altered_truth.claim_labels:
        label["is_synthetic_anomaly"] = not label["is_synthetic_anomaly"]
    captured.clear()
    second = _run(data, altered_truth)
    assert first_selections == captured
    assert first["budgets"]["60"]["methods"]["cir_facility_priority"]["selection_counts"] == second["budgets"]["60"]["methods"]["cir_facility_priority"]["selection_counts"]
    assert first["budgets"]["60"]["methods"]["cir_facility_priority"]["metrics"] != second["budgets"]["60"]["methods"]["cir_facility_priority"]["metrics"]


def test_runner_rejects_ground_truth_leakage_in_features():
    data = _smoke_data()
    data.records[0]["primary_scenario"] = "phantom_physiotherapy"
    with pytest.raises(ValueError, match="Ground-truth fields"):
        _run(data)


def test_runner_rejects_alternate_anomaly_label_field_in_features():
    data = _smoke_data()
    data.records[0]["is_anomalous"] = True
    with pytest.raises(ValueError, match="Ground-truth fields"):
        _run(data)
