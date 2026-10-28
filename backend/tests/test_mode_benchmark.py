"""Four-mode synthetic benchmark: shared contract, label isolation, count reconciliation and per-mode behaviour."""

from datetime import datetime
import json
import re

import pytest

from app.data_sources.bpjs_fkrtl_adapter import adapt_fkrtl_rows
from app.data_sources.providers import CANONICAL_FEATURE_FIELDS
from scripts.mode_benchmark import (
    AGGREGATE_BASIS, BASELINE_FOR_MODE, COUNT_KEYS, DETECTORS, MODES, SCENARIOS, SYNTHETIC_ONLY_FIELDS,
    CountReconciliationError, confusion, evaluate_mode_benchmark, generate_mode_benchmark, metrics, reconcile,
    run_detectors, run_mode_seeds,
)

SMALL = {"background": 400, "planted": 4}


@pytest.fixture(scope="module")
def generated():
    return generate_mode_benchmark(3, **SMALL)


@pytest.fixture(scope="module")
def report(generated):
    return evaluate_mode_benchmark(*generated)


@pytest.fixture(scope="module")
def multi_seed():
    return run_mode_seeds((1, 2, 3), **SMALL)


def _method(report, mode, name):
    return report["modes"][mode]["methods"][name]


def test_records_follow_the_canonical_contract_and_carry_no_labels(generated):
    records, sidecar, truth = generated
    assert all(set(row) == set(CANONICAL_FEATURE_FIELDS) for row in records)
    assert set(truth["labels"]) == {row["case_id"] for row in records}
    scenario_names = set(SCENARIOS) | set(MODES) | {"positive", "control"}
    for row in records:
        values = {str(value) for value in row.values() if not isinstance(value, list)}
        assert not values & scenario_names
    assert "positive" not in json.dumps(sidecar) and "scenario" not in json.dumps(sidecar)
    assert all(row["billed_amount"] is None and row["provider_billed_amount_unverified"] is None for row in records)


def test_synthetic_only_fields_are_exactly_what_the_fkrtl_adapter_cannot_provide():
    assert {"facility_id", "service_type", "supporting_evidence_types",
            "supporting_evidence_recording_status"} <= set(SYNTHETIC_ONLY_FIELDS)
    row = {"PSTV01": 1, "FKL02": "v", "FKL03": datetime(2024, 3, 4), "FKL18": "A", "FKL19": "G", "FKL30": "P"}
    [mapped], _ = adapt_fkrtl_rows([row], case_reference_secret=b"k" * 32)
    assert all(mapped.get(field) is None for field in SYNTHETIC_ONLY_FIELDS)


def test_detectors_never_receive_truth_and_results_do_not_depend_on_it(generated):
    records, _sidecar, _truth = generated
    first = run_detectors(records)
    second = run_detectors(list(reversed(records)))
    for name in ("repeat_service_v1", "repeat_eleven_field", "evidence_scenario_rules"):
        assert first[name]["flagged"] == second[name]["flagged"]
    with pytest.raises(ValueError):
        evaluate_mode_benchmark([{**records[0], "scenario": "x"}], {}, {"labels": {}, "role": {}, "mode": {}})


def test_generation_is_deterministic_per_seed(generated):
    again = generate_mode_benchmark(3, **SMALL)
    assert again[0] == generated[0] and again[2] == generated[2]
    assert generate_mode_benchmark(4, **SMALL)[0] != generated[0]


def test_missingness_is_not_concentrated_in_one_class(multi_seed):
    for mode in MODES:
        balance = multi_seed["aggregate"][mode]["balance"]
        gap = balance["procedure_blank_rate_positives"]["mean"] - balance["procedure_blank_rate_negatives"]["mean"]
        assert abs(gap) < 0.2, mode
    assert 0.4 < AGGREGATE_BASIS["procedure_code_blank_rate"] < 0.43


# --- Count reconciliation and metric denominators ---

def test_every_seed_mode_and_method_partitions_records_exactly(multi_seed):
    for seed, seed_report in multi_seed["per_seed"].items():
        dataset = seed_report["record_count"]
        for mode in MODES:
            methods = seed_report["modes"][mode]["methods"]
            assert set(methods) == {*DETECTORS, BASELINE_FOR_MODE[mode]}
            cohorts = set()
            for name, entry in methods.items():
                c = entry["counts"]
                assert c["tp"] + c["fn"] == c["assessed_positives"], (seed, mode, name)
                assert c["fp"] + c["tn"] == c["assessed_negatives"], (seed, mode, name)
                for label in ("positives", "negatives"):
                    assert c[label] == c[f"assessed_{label}"] + c[f"unassessed_{label}"] + c[f"not_applicable_{label}"]
                assert c["positives"] + c["negatives"] == c["cohort_records"]
                assert c["cohort_records"] + c["excluded_other_mode_records"] == c["dataset_records"] == dataset
                assert c["tp"] + c["fp"] == c["flagged_records_in_cohort"] <= c["flagged_records_in_dataset"]
                cohorts.add((c["positives"], c["negatives"]))
                # Per-scenario counts add up to the method's positives and mode controls.
                pos = entry["positives_by_scenario"].values()
                assert sum(item["records"] for item in pos) == c["positives"]
                assert sum(item["assessed"] for item in pos) == c["assessed_positives"]
                assert sum(item["flagged"] for item in pos) == c["tp"]
                assert sum(item["unassessed"] + item["not_applicable"] for item in pos) == (
                    c["unassessed_positives"] + c["not_applicable_positives"])
            assert len(cohorts) == 1, (seed, mode)  # same labelled cohort for every method of a mode


def test_metrics_use_the_declared_denominators(multi_seed):
    for mode in MODES:
        for name, entry in multi_seed["aggregate"][mode]["methods"].items():
            c, m = entry["pooled_counts"], entry["pooled_metrics"]
            assessed = c["assessed_positives"] + c["assessed_negatives"]
            assert m == metrics(c)
            if c["tp"] + c["fp"]:
                assert m["precision"] == round(c["tp"] / (c["tp"] + c["fp"]), 4)
            else:
                assert m["precision"] is None
            assert m["recall_on_assessed"] == (round(c["tp"] / c["assessed_positives"], 4) if c["assessed_positives"] else None)
            assert m["false_positive_rate"] == (round(c["fp"] / c["assessed_negatives"], 4) if c["assessed_negatives"] else None)
            assert m["flagged_per_1000_cohort_records"] == round(1000 * c["flagged_records_in_cohort"] / c["cohort_records"], 2)
            if assessed:
                assert m["flagged_per_1000_assessed_records"] == round(1000 * c["flagged_records_in_cohort"] / assessed, 2)
                assert m["assessed_prevalence"] == round(c["assessed_positives"] / assessed, 4)
            assert m["cohort_prevalence"] == round(c["positives"] / c["cohort_records"], 4)


def test_coverage_states_follow_each_detector_implementation(report):
    # Evidence check: no rule -> not applicable, not synchronised -> unassessed.
    drug_default = _method(report, "drug_device_fictitious", "evidence_default_rules")["counts"]
    assert drug_default["positives"] == drug_default["not_applicable_positives"] > 0
    assert drug_default["assessed_positives"] == 0
    drug_rules = _method(report, "drug_device_fictitious", "evidence_scenario_rules")["counts"]
    assert drug_rules["not_applicable_positives"] == 0 and drug_rules["unassessed_positives"] >= 0
    # Repeat key with blank FKL30 -> unassessed (missing data), never not applicable.
    repeat = _method(report, "repeat_billing", "repeat_service_v1")["counts"]
    assert repeat["unassessed_positives"] > 0 and repeat["not_applicable_positives"] == 0
    # Naive phantom/drug baselines apply only to their service types.
    naive = _method(report, "phantom_billing", "naive_execution_record_linkage")["counts"]
    assert naive["not_applicable_negatives"] > 0 and naive["unassessed_negatives"] == 0
    # Candidate units are named per method.
    assert _method(report, "cloning", "near_duplicate")["candidate_unit"] == "pair"
    assert _method(report, "repeat_billing", "repeat_service_v1")["candidate_unit"] == "group"
    assert _method(report, "phantom_billing", "evidence_default_rules")["candidate_unit"] == "record"


def test_confusion_partitions_and_rejects_inconsistent_states():
    dataset = {"a", "b", "c", "x", "y", "z", "o"}
    states = {"assessed": {"a", "b", "x", "y", "o"}, "unassessed": {"c"}, "not_applicable": {"z"}}
    counts = confusion({"a", "x"}, states, {"a", "b", "c"}, {"x", "y", "z"}, dataset,
                       [frozenset({"a", "x"}), frozenset({"x", "o"})])
    assert (counts["tp"], counts["fp"], counts["fn"], counts["tn"]) == (1, 1, 1, 1)
    assert (counts["unassessed_positives"], counts["not_applicable_negatives"]) == (1, 1)
    assert (counts["cohort_records"], counts["excluded_other_mode_records"]) == (6, 1)
    assert (counts["candidate_units_in_dataset"], counts["candidate_units_within_cohort"]) == (2, 1)
    m = metrics(counts)
    assert m["precision"] == 0.5 and m["recall_on_all_positives"] == round(1 / 3, 4)
    assert m["flagged_per_1000_cohort_records"] == round(2000 / 6, 2)
    assert m["flagged_per_1000_assessed_records"] == 500.0
    with pytest.raises(CountReconciliationError):
        confusion({"c"}, states, {"a", "b", "c"}, {"x", "y", "z"}, dataset)  # flagged but unassessed
    with pytest.raises(CountReconciliationError):
        confusion(set(), {**states, "not_applicable": {"z", "c"}}, {"a"}, {"x"}, dataset)  # overlapping states
    with pytest.raises(CountReconciliationError):
        reconcile({**counts, "tn": counts["tn"] + 1})


def test_counts_keys_are_complete(report):
    entry = _method(report, "cloning", "near_duplicate")
    assert tuple(entry["counts"]) == COUNT_KEYS


# --- Per-mode behaviour (unchanged contracts) ---

def test_repeat_mode_core_definition_and_blank_procedure(report):
    core = _method(report, "repeat_billing", "repeat_service_v1")
    eleven = _method(report, "repeat_billing", "repeat_eleven_field")
    assert core["counts"]["fn"] == 0 and core["metrics"]["recall_on_assessed"] == 1.0
    assert eleven["positives_by_scenario"]["repeat_context_variation"]["rate_on_assessed"] in (0.0, None)
    assert core["counts"]["unassessed_positives"] == eleven["counts"]["unassessed_positives"] > 0
    assert core["metrics"]["recall_on_all_positives"] < 1.0
    controls = core["controls_by_scenario"]
    assert controls["repeat_control_different_procedure"]["rate_on_assessed"] in (0.0, None)
    assert controls["repeat_control_next_day"]["rate_on_assessed"] in (0.0, None)


def test_evidence_modes_distinguish_absent_unsynchronised_and_not_assessed(report):
    phantom = _method(report, "phantom_billing", "evidence_default_rules")
    pending = phantom["controls_by_scenario"]["phantom_control_sync_pending"]
    assert pending["assessed"] == 0 and pending["unassessed"] == pending["records"] > 0
    assert phantom["positives_by_scenario"]["phantom_log_not_matching"]["rate_on_assessed"] in (0.0, None)
    states = report["evidence_states"]["evidence_default_rules"]
    assert states["no_rule_not_applicable"] > 0 and states["inventory_not_synchronised_unassessed"] > 0
    drug = _method(report, "drug_device_fictitious", "evidence_scenario_rules")
    assert drug["counts"]["fp"] == 0
    assert drug["positives_by_scenario"]["drug_one_item_undispensed"]["rate_on_assessed"] in (0.0, None)
    naive = _method(report, "drug_device_fictitious", "naive_item_exact_dispensing")
    assert naive["metrics"]["recall_on_assessed"] == 1.0
    assert naive["controls_by_scenario"]["drug_control_unit_difference"]["rate_on_assessed"] == 1.0


def test_report_is_aggregate_only(multi_seed):
    text = json.dumps(multi_seed)
    assert not re.search(r"(case|participant)_[0-9a-f]{20}|synfac-\d", text)
