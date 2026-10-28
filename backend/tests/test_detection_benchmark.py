"""Phase 4: the synthetic detection benchmark is reproducible, label-separated and correctly computed."""

import pytest

pytest.importorskip("sklearn")

from app.data_sources.providers import CANONICAL_FEATURE_FIELDS  # noqa: E402
from scripts.detection_benchmark import (  # noqa: E402
    NEAR_NEGATIVE_KINDS, NEAR_TARGET_KINDS, SCENARIOS, evaluate_benchmark, generate_benchmark,
    precision_recall, random_baseline_at_k, ranking_at_k, rule_flag_baseline_at_k, run_seeds,
)


@pytest.fixture(scope="module")
def benchmark():
    records, truth = generate_benchmark(seed=7)
    return records, truth, evaluate_benchmark(records, truth)


def test_generation_and_evaluation_are_reproducible(benchmark):
    records, truth, report = benchmark
    again_records, again_truth = generate_benchmark(seed=7)
    assert (again_records, again_truth) == (records, truth)
    assert evaluate_benchmark(again_records, again_truth) == report
    assert generate_benchmark(seed=8)[0] != records


def test_every_record_has_an_expected_state_and_every_pair_its_own_label(benchmark):
    records, truth, _report = benchmark
    ids = {row["case_id"] for row in records}
    assert set(truth["labels"]) == set(truth["expected"]) == ids
    for expected in truth["expected"].values():
        assert expected["repeat"] in {"flag", "no_flag", "unassessed"}
        assert expected["near"] in {"target", "hard_negative", "background"}
        assert expected["ml"] in {"target", "benign_rare", "background"}
    assert len({pair["pair_id"] for pair in truth["pairs"]}) == len(truth["pairs"])
    for pair in truth["pairs"]:
        assert len(pair["case_ids"]) == 2 and set(pair["case_ids"]) <= ids
        assert {truth["labels"][case_id] for case_id in pair["case_ids"]} == {pair["kind"]}
    kinds = {pair["kind"] for pair in truth["pairs"]}
    assert set(NEAR_TARGET_KINDS) | set(NEAR_NEGATIVE_KINDS) <= kinds


def test_labels_stay_separate_from_model_and_rule_inputs(benchmark):
    records, truth, _report = benchmark
    allowed = set(CANONICAL_FEATURE_FIELDS)
    assert all(set(row) <= allowed for row in records)
    assert set(truth["labels"].values()) <= set(SCENARIOS)
    words = {"repeat", "clone", "routine", "rare", "incomplete", "ml", "both", "visitor", "service"}
    assert not any(word in row["case_id"] or word in row["participant_token"] for row in records for word in words)
    with pytest.raises(ValueError):
        evaluate_benchmark([{**records[0], "scenario": "normal"}] + records[1:], truth)


def test_record_metrics_on_a_known_fixture():
    metrics = precision_recall({"a", "b", "c"}, {"a", "b", "d"}, {"a", "b", "c", "d"})
    assert (metrics["tp"], metrics["fp"], metrics["fn"]) == (2, 1, 1)
    assert metrics["precision"] == 0.6667 and metrics["recall_on_assessed_targets"] == 0.6667
    unassessed = precision_recall({"a", "b", "c"}, {"a", "b", "d"}, {"a", "b", "c"})
    assert unassessed["fn"] == 0 and unassessed["targets_unassessed"] == 1


def test_ranking_and_baseline_metrics_on_known_fixtures():
    ranks = {"a": {"rank": 1}, "b": {"rank": 2}, "c": {"rank": 2}, "d": {"rank": 4}}
    assert ranking_at_k(ranks, {"b", "d"}, 2) == {
        "k": 2, "top_k_size_with_ties": 3, "hits": 1, "precision_at_k": 0.3333, "recall_at_k": 0.5}
    assert random_baseline_at_k(100, 10, 20) == {"k": 20, "expected_precision_at_k": 0.1, "expected_recall_at_k": 0.2}
    # 4 flagged records, 2 of them targets; K=2 inside the flagged block -> 1 expected hit.
    flagged, targets = {"a", "b", "c", "d"}, {"a", "b", "x"}
    assert rule_flag_baseline_at_k(flagged, targets, 10, 2) == {
        "k": 2, "expected_precision_at_k": 0.5, "expected_recall_at_k": 0.3333}
    # K=7: all 4 flagged (2 hits) + 3 of the 6 others holding 1 target -> 2.5 expected hits.
    assert rule_flag_baseline_at_k(flagged, targets, 10, 7)["expected_precision_at_k"] == round(2.5 / 7, 4)


def test_near_duplicate_metrics_use_candidate_pair_denominators(benchmark):
    records, _truth, report = benchmark
    near = report["near_duplicate_rule"]
    assert near["precision"] == round(near["target_pairs_found"] / near["candidate_pairs"], 4)
    assert near["recall"] == round(near["target_pairs_found"] / near["target_pairs"], 4)
    assert near["candidates_per_1000_records"] == round(near["candidate_pairs"] / len(records) * 1000, 2)
    assert near["assessed_records"] + near["unassessed_records"] == len(records)
    # Two differing attributes still pass the unchanged 0.8 threshold; three do not.
    assert near["hard_negative_pairs_matched_by_kind"]["three_differences"] == 0


def test_repeat_rule_contracts_hold(benchmark):
    _records, _truth, report = benchmark
    repeat = report["repeat_rule"]
    assert repeat["unassessed_matches_expected"] is True
    assert repeat["pairs_matched_by_kind"]["repeat_hard_negative"] == 0
    assert repeat["pairs_matched_by_kind"]["next_day_repeat"] == 0
    assert repeat["pairs_matched_by_kind"]["exact_repeat"] == repeat["pairs_by_kind"]["exact_repeat"]


def test_multi_seed_run_summarises_and_stays_stable():
    report = run_seeds((1, 2))
    assert set(report["per_seed"]) == {1, 2}
    assert report["aggregate"]["ml_ranking"]["stable_under_row_permutations_all_seeds"] is True
    assert "SYNTHETIC BENCHMARK" in report["label"]
    at_10 = report["aggregate"]["ml_ranking"]["at_10"]
    assert at_10["random_precision"]["mean"] is not None and at_10["rule_flag_precision"]["mean"] is not None


# --- Phase 5: duration screen benchmark ---

from scripts.detection_benchmark import LOS_SCENARIOS, evaluate_los_benchmark, generate_los_benchmark  # noqa: E402


@pytest.fixture(scope="module")
def los_benchmark():
    records, truth = generate_los_benchmark(seed=3)
    return records, truth, evaluate_los_benchmark(records, truth)


def test_duration_benchmark_is_reproducible_and_label_separated(los_benchmark):
    records, truth, report = los_benchmark
    assert generate_los_benchmark(seed=3) == (records, truth)
    assert evaluate_los_benchmark(records, truth) == report
    assert all(set(row) <= set(CANONICAL_FEATURE_FIELDS) for row in records)
    assert set(truth["labels"]) == set(truth["expected"]) == {row["case_id"] for row in records}
    assert set(truth["labels"].values()) == set(LOS_SCENARIOS)
    with pytest.raises(ValueError):
        evaluate_los_benchmark([{**records[0], "expected": "target"}] + records[1:], truth)


def test_duration_benchmark_contracts(los_benchmark):
    _records, _truth, report = los_benchmark
    screen = report["duration_screen"]
    assert screen["unassessed_matches_expected"] is True
    assert screen["ordinary_false_alerts"] == 0
    assert screen["stable_under_row_permutation"] is True
    assert screen["assessed"] + screen["unassessed"] == report["record_count"]
    assert screen["target_recall"] >= 0.8  # predeclared screen, not tuned on this seed
    # Legitimate long stays are statistically identical to targets: the screen flags them by design.
    assert screen["legitimate_long_flag_rate"] >= 0.5
    assert "not fraud detection" in report["label"]
