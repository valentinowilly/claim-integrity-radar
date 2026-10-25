"""Comparative, record-level audit-budget evaluation on synthetic fixtures.

The pipeline and all three selection methods run before ground-truth labels are
read. Returned output contains aggregates only; selected IDs are transient.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from itertools import combinations
import statistics
import math
import platform
from typing import Any

from app.analytics.audit_priority import build_audit_priority_queue
from app.analytics.record_selection import (
    RECORD_SELECTION_POLICY_VERSION,
    SELECTION_SEED,
    RecordSelection,
    cir_priority_selection,
    random_selection,
    selected_assessment_summary,
    simple_rule_selection,
)
from app.analytics.risk_scoring import (
    DETECTOR_ORDER,
    DETECTOR_SUITE_VERSION,
    run_detector_suite,
    score_claims,
)


RECORD_EVALUATION_VERSION = "synthetic-record-selection-evaluation-v1"
RANDOM_SEEDS = tuple(range(12026, 12056))
DEFAULT_RECORD_K = (6000, 12000, 24000)
_LABEL_KEYS = frozenset({
    "is_anomaly", "is_anomalous", "is_synthetic_anomaly", "scenario", "scenario_label",
    "scenario_labels", "primary_scenario", "scenario_group_id", "scenario_code",
    "intensity_level", "injected_signals", "label_scope", "ground_truth",
    "claim_labels", "group_labels", "facility_labels",
})
NEAR_DUPLICATE_TARGET_SCENARIOS = frozenset({"cloning", "mixed_light_severe"})


def _labels_from(ground_truth: Any, feature_ids: set[str]) -> dict[str, Mapping[str, Any]]:
    raw = getattr(ground_truth, "claim_labels", None)
    if raw is None and isinstance(ground_truth, Mapping):
        raw = ground_truth.get("claim_labels")
    if not isinstance(raw, (list, tuple)):
        raise ValueError("ground_truth.claim_labels is required")
    labels: dict[str, Mapping[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping) or not isinstance(item.get("case_id"), str):
            raise ValueError("Each ground-truth label must reference a case_id")
        case_id = item["case_id"]
        if case_id in labels:
            raise ValueError("Ground-truth case IDs must be unique")
        if not isinstance(item.get("is_synthetic_anomaly"), bool):
            raise ValueError("is_synthetic_anomaly must be boolean")
        labels[case_id] = item
    if set(labels) != feature_ids:
        raise ValueError("Ground-truth labels must match the feature population")
    return labels


def _selection_metrics(
    selection: RecordSelection,
    labels: Mapping[str, Mapping[str, Any]],
    positive_count: int,
    scenarios: Sequence[str],
) -> dict[str, Any]:
    selected = set(selection.selected_case_ids)
    hits = sum(labels[case_id]["is_synthetic_anomaly"] is True for case_id in selected)
    scenario_hits = Counter(
        str(labels[case_id].get("primary_scenario"))
        for case_id in selected
        if labels[case_id]["is_synthetic_anomaly"] is True
    )
    k = selection.requested_k
    metrics = {
        "selected_positive_record_count": hits,
        "precision_at_k": round(hits / k, 6) if selection.comparable else None,
        "recall_at_k": round(hits / positive_count, 6) if positive_count and selection.comparable else None,
        "positive_records_per_100_selected_records": round(100 * hits / k, 6) if selection.comparable else None,
        "selected_positive_record_count_by_scenario": {
            scenario: scenario_hits.get(scenario, 0) for scenario in scenarios
        },
        "selected_positive_record_count_by_selection_path": {
            path: sum(labels[case_id]["is_synthetic_anomaly"] is True for case_id in case_ids)
            for path, case_ids in selection.selected_by_path.items()
        },
    }
    return metrics


def _mean_std(items: Sequence[float | None]) -> tuple[float | None, float | None]:
    values = [item for item in items if item is not None]
    if not values:
        return None, None
    return round(statistics.fmean(values), 6), round(statistics.pstdev(values), 6)


def _facility_priority_diagnostics(
    priority: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    facilities: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return facility-priority eligibility counts without emitting IDs."""
    population_facility_ids = {
        row.get("facility_id") for row in records
        if isinstance(row.get("facility_id"), str) and row.get("facility_id")
    }
    facility_metadata_ids = {
        row.get("facility_id") for row in facilities
        if isinstance(row.get("facility_id"), str) and row.get("facility_id")
    }
    raw_items = priority.get("items", [])
    items = list(raw_items) if isinstance(raw_items, (list, tuple)) else []
    status_counts: Counter[str] = Counter()
    index_counts: Counter[str] = Counter()
    matched_unit_facilities: set[str] = set()
    unmatched_unit_count = 0
    usable_facilities: set[str] = set()
    valid_index_nonavailable_status_count = 0
    prefix = "synthetic-audit-unit:"

    for item in items:
        if not isinstance(item, Mapping):
            status_counts["malformed_unit"] += 1
            index_counts["unusable_type"] += 1
            unmatched_unit_count += 1
            continue
        status = item.get("priority_status")
        status_counts[status if isinstance(status, str) else "missing_status"] += 1

        unit_id = item.get("unit_id")
        facility_id = unit_id[len(prefix):] if isinstance(unit_id, str) and unit_id.startswith(prefix) else None
        if facility_id is None or facility_id not in population_facility_ids:
            unmatched_unit_count += 1
        else:
            matched_unit_facilities.add(facility_id)

        value = item.get("priority_index")
        if value is None:
            index_counts["missing"] += 1
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            index_counts["unusable_type"] += 1
            continue
        if not math.isfinite(value):
            index_counts["non_finite"] += 1
            continue
        if value < 0:
            index_counts["negative"] += 1
            continue
        index_counts["finite_nonnegative"] += 1
        if status == "available" and facility_id in population_facility_ids:
            usable_facilities.add(facility_id)
        else:
            valid_index_nonavailable_status_count += 1

    return {
        "population_facility_count": len(population_facility_ids),
        "facility_metadata_id_count": len(facility_metadata_ids),
        "priority_unit_count": len(items),
        "priority_status_histogram": dict(sorted(status_counts.items())),
        "priority_index_category_counts": dict(sorted(index_counts.items())),
        "finite_nonnegative_index_not_usable_due_to_status_or_unit_mismatch_count": valid_index_nonavailable_status_count,
        "matched_priority_facility_id_count": len(matched_unit_facilities),
        "unmatched_or_unparseable_priority_unit_count": unmatched_unit_count,
        "distinct_facility_metadata_ids_missing_from_record_population_count": len(facility_metadata_ids - population_facility_ids),
        "population_record_count_with_available_facility_priority": sum(
            row.get("facility_id") in usable_facilities for row in records
        ),
        "population_record_count_without_available_facility_priority": sum(
            row.get("facility_id") not in usable_facilities for row in records
        ),
        "note": "Counts describe pipeline priority units; absent units mean no queue item, not a zero score or a normal facility.",
    }


def _group_labels_from(ground_truth: Any) -> list[Mapping[str, Any]]:
    raw = getattr(ground_truth, "group_labels", None)
    if raw is None and isinstance(ground_truth, Mapping):
        raw = ground_truth.get("group_labels")
    if not isinstance(raw, (list, tuple)):
        raise ValueError("ground_truth.group_labels is required for near-duplicate diagnostics")
    return [item for item in raw if isinstance(item, Mapping)]


def _pair(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left < right else (right, left)


def _near_duplicate_diagnostics(
    result: Mapping[str, Any],
    group_labels: Sequence[Mapping[str, Any]],
    generated_pairs: set[tuple[str, str]],
    compared_pairs: set[tuple[str, str]],
    comparison_passed_pairs: set[tuple[str, str]],
) -> dict[str, Any]:
    """Join synthetic group truth only after all selectors have frozen choices.

    Pair IDs are used transiently for the join and only aggregate counts leave
    this function.
    """
    target_groups: list[set[str]] = []
    for group in group_labels:
        if (group.get("is_synthetic_anomaly") is True
                and group.get("scenario_code") in NEAR_DUPLICATE_TARGET_SCENARIOS):
            members = group.get("case_ids")
            if isinstance(members, (list, tuple)) and len(members) >= 2 and all(isinstance(x, str) for x in members):
                target_groups.append(set(members))

    target_pairs: set[tuple[str, str]] = set()
    for members in target_groups:
        target_pairs.update(combinations(sorted(members), 2))
    accepted_pairs: set[tuple[str, str]] = set()
    candidates = result.get("candidates", [])
    if isinstance(candidates, (list, tuple)):
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            pair_ids = candidate.get("case_ids")
            if isinstance(pair_ids, (list, tuple)) and len(pair_ids) == 2 and all(isinstance(x, str) for x in pair_ids):
                accepted_pairs.add(_pair(pair_ids[0], pair_ids[1]))

    positive_claim_ids = set().union(*target_groups) if target_groups else set()
    accepted_positive_pairs = target_pairs & accepted_pairs
    detected_claim_ids = {case_id for pair_ids in accepted_positive_pairs for case_id in pair_ids}
    groups_with_detection = sum(
        any(pair_ids in accepted_pairs for pair_ids in combinations(sorted(group), 2))
        for group in target_groups
    )
    groups_fully_detected = sum(
        all(pair_ids in accepted_pairs for pair_ids in combinations(sorted(group), 2))
        for group in target_groups
    )
    unassessed_ids = result.get("unassessed_case_ids", [])
    ineligible = result.get("ineligible_cases", [])
    return {
        "target_scenarios": sorted(NEAR_DUPLICATE_TARGET_SCENARIOS),
        "pair_unit": {
            "planted_positive_pair_count": len(target_pairs),
            "blocking_generated_positive_pair_count": len(target_pairs & generated_pairs),
            "positive_pair_count_not_generated_by_blocking": len(target_pairs - generated_pairs),
            "positive_pair_count_generated_but_not_compared": len((target_pairs & generated_pairs) - compared_pairs),
            "positive_pair_count_compared_below_threshold": len((target_pairs & compared_pairs) - comparison_passed_pairs),
            "positive_pair_count_passed_but_not_returned": len((target_pairs & comparison_passed_pairs) - accepted_pairs),
            "positive_pair_count_accepted": len(accepted_positive_pairs),
            "all_reported_candidate_pair_count": len(candidates) if isinstance(candidates, (list, tuple)) else 0,
        },
        "scenario_group_unit": {
            "planted_positive_group_count": len(target_groups),
            "groups_with_at_least_one_accepted_positive_pair": groups_with_detection,
            "groups_with_all_member_pairs_accepted": groups_fully_detected,
        },
        "claim_unit": {
            "planted_positive_claim_count_in_target_groups": len(positive_claim_ids),
            "claims_in_at_least_one_accepted_positive_pair": len(detected_claim_ids),
            "target_group_claims_without_accepted_positive_pair": len(positive_claim_ids - detected_claim_ids),
            "explicitly_unassessed_claim_count": len(unassessed_ids) if isinstance(unassessed_ids, (list, tuple)) else None,
            "ineligible_claim_count": len(ineligible) if isinstance(ineligible, (list, tuple)) else None,
        },
        "search_truncated": result.get("search_truncated") is True,
        "pair_comparisons_reported_by_detector": result.get("pair_comparisons"),
        "search_diagnostics": {
            key: value
            for key, value in (result.get("search_diagnostics", {}).items()
                               if isinstance(result.get("search_diagnostics"), Mapping) else ())
            if key in {
                "primary_block_count", "eligible_primary_block_count", "selected_primary_block_count",
                "oversized_primary_block_count", "refinement_bucket_count",
                "oversized_refinement_bucket_count", "dense_bucket_sample_count",
                "maximum_primary_block_size", "maximum_refinement_bucket_size",
                "estimated_primary_pair_work", "blocks_skipped_by_pair_budget",
                "comparison_limit_hit", "candidate_limit_hit", "hard_search_limit_hit",
                "ineligible_pair_count", "stratified_block_sampling",
                "stratified_sampled_primary_block_count", "stratified_sampling_left_unassessed",
                "stratified_sampling_unassessed_case_count", "comparison_budget_unassessed_case_count",
                "candidate_limit_unassessed_case_count", "bounded_block_unassessed_case_count",
                "unassessed_case_count", "assessment_incomplete", "unassessed_cause_counts_are_nonexclusive",
            }
        },
        "limitation": (
            "Known synthetic scenario pairs diagnose candidate-generation stages; they do not establish real-world "
            "performance. The detector's coverage status describes declared search bounds, not completeness against "
            "unseen planted positives."
        ),
    }


def evaluate_record_level_comparison(
    records: Sequence[Mapping[str, Any]],
    facilities: Sequence[Mapping[str, Any]],
    ground_truth: Any,
    *,
    k_values: Sequence[int] = DEFAULT_RECORD_K,
    random_seeds: Sequence[int] = RANDOM_SEEDS,
    selection_seed: int = SELECTION_SEED,
    generator_version: str,
    generator_seed: int,
    target_anomaly_rate: float,
    generator_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute shared detectors/scoring/priority then compare record selection.

    Label data is intentionally not accepted by any detector or selector. The
    complete selection set for every method/K/seed is frozen before labels are
    parsed for aggregate metrics.
    """
    if not k_values or any(isinstance(k, bool) or not isinstance(k, int) or k < 1 for k in k_values):
        raise ValueError("k_values must contain positive integers")
    if len(set(k_values)) != len(k_values):
        raise ValueError("k_values must be unique")
    if not random_seeds or len(set(random_seeds)) != len(random_seeds):
        raise ValueError("random_seeds must be non-empty and unique")

    # Selector validation is also the explicit feature/ground-truth boundary.
    random_selection(records, 1, seed=selection_seed)
    feature_ids = {row["case_id"] for row in records}
    facility_keys = set().union(*(set(row) for row in facilities)) if facilities else set()
    if _LABEL_KEYS & facility_keys:
        raise ValueError("Ground-truth fields are forbidden in facility features")

    blocking_pairs: set[tuple[str, str]] = set()
    compared_pairs: set[tuple[str, str]] = set()
    comparison_passed_pairs: set[tuple[str, str]] = set()

    def observe_similarity(left: str, right: str, passed: bool) -> None:
        pair_ids = _pair(left, right)
        compared_pairs.add(pair_ids)
        if passed:
            comparison_passed_pairs.add(pair_ids)

    detector_results = run_detector_suite(
        records,
        facilities,
        near_duplicate_candidate_pair_observer=lambda left, right: blocking_pairs.add(_pair(left, right)),
        near_duplicate_similarity_observer=observe_similarity,
    )
    scoring = score_claims(records, detector_results)
    priority = build_audit_priority_queue(records, scoring)
    priority_diagnostics = _facility_priority_diagnostics(priority, records, facilities)
    repeat_result = detector_results.get("repeat_billing_candidate")
    if not isinstance(repeat_result, Mapping):
        raise ValueError("repeat_billing detector result is unavailable")

    # Build every selection before loading/reading any ground-truth label.
    frozen: dict[str, dict[str, Any]] = {}
    for k in k_values:
        random_rows = [
            (seed, random_selection(records, k, seed=seed))
            for seed in random_seeds
        ]
        simple = simple_rule_selection(records, repeat_result, k, seed=selection_seed)
        cir = cir_priority_selection(records, scoring, priority, k, seed=selection_seed)
        frozen[str(k)] = {"random": random_rows, "simple_rule": simple, "cir": cir}

    # Ground truth is first read below the frozen-selection boundary.
    labels_by_id = _labels_from(ground_truth, feature_ids)
    near_result = detector_results.get("near_duplicate_claim_candidate", {})
    if not isinstance(near_result, Mapping):
        near_result = {}
    near_diagnostics = _near_duplicate_diagnostics(
        near_result, _group_labels_from(ground_truth), blocking_pairs,
        compared_pairs, comparison_passed_pairs,
    )
    positive_count = sum(item["is_synthetic_anomaly"] is True for item in labels_by_id.values())
    scenario_counts = Counter(
        str(item.get("primary_scenario"))
        for item in labels_by_id.values()
        if item["is_synthetic_anomaly"] is True
    )

    budgets: dict[str, Any] = {}
    for k_text, selection_set in frozen.items():
        random_rows = []
        for seed, selection in selection_set["random"]:
            random_rows.append({
                "seed": seed,
                **selection.summary(),
                "metrics": _selection_metrics(selection, labels_by_id, positive_count, sorted(scenario_counts)),
                "selected_assessment": selected_assessment_summary(selection, scoring),
            })
        random_precision_mean, random_precision_std = _mean_std([
            row["metrics"]["precision_at_k"] for row in random_rows
        ])
        random_recall_mean, random_recall_std = _mean_std([
            row["metrics"]["recall_at_k"] for row in random_rows
        ])
        random_p100_mean, random_p100_std = _mean_std([
            row["metrics"]["positive_records_per_100_selected_records"] for row in random_rows
        ])

        method_reports: dict[str, Any] = {
            "random_baseline": {
                "seed_count": len(random_rows),
                "seeds": list(random_seeds),
                "per_seed": random_rows,
                "precision_at_k_mean": random_precision_mean,
                "precision_at_k_population_stddev": random_precision_std,
                "recall_at_k_mean": random_recall_mean,
                "recall_at_k_population_stddev": random_recall_std,
                "positive_records_per_100_mean": random_p100_mean,
                "positive_records_per_100_population_stddev": random_p100_std,
                "selected_positive_record_count_by_scenario_mean": {
                    scenario: _mean_std([
                        float(row["metrics"]["selected_positive_record_count_by_scenario"].get(scenario, 0))
                        for row in random_rows
                    ])[0]
                    for scenario in sorted(scenario_counts)
                },
                "selected_positive_record_count_by_scenario_population_stddev": {
                    scenario: _mean_std([
                        float(row["metrics"]["selected_positive_record_count_by_scenario"].get(scenario, 0))
                        for row in random_rows
                    ])[1]
                    for scenario in sorted(scenario_counts)
                },
            }
        }
        for key, name in (("simple_rule", "simple_rule_repeat_billing"), ("cir", "cir_facility_priority")):
            selection = selection_set[key]
            method_reports[name] = {
                **selection.summary(),
                "selection_seed": selection_seed,
                "metrics": _selection_metrics(selection, labels_by_id, positive_count, sorted(scenario_counts)),
                "selected_assessment": selected_assessment_summary(selection, scoring),
            }
        budgets[k_text] = {
            "requested_k": int(k_text),
            "methods": method_reports,
        }

    coverage = [
        {key: value for key, value in item.items() if key in {
            "indicator", "status", "assessed_case_count", "triggered_case_count",
            "not_applicable_case_count", "not_assessed_case_count", "search_truncated",
        }}
        for item in scoring.get("detector_coverage", [])
        if isinstance(item, Mapping)
    ]
    return {
        "evaluation_version": RECORD_EVALUATION_VERSION,
        "data_source": "synthetic_experiment_only",
        "metadata": {
            "generator_version": str(generator_version),
            "generator_seed": generator_seed,
            "selection_seed": selection_seed,
            "claim_record_count": len(records),
            "facility_count": len(facilities),
            "target_anomaly_rate": target_anomaly_rate,
            "generator_configuration": {
                key: value for key, value in (generator_metadata or {}).items()
                if isinstance(value, (str, int, float, bool, type(None)))
            },
            "positive_synthetic_claim_record_count": positive_count,
            "positive_synthetic_claim_record_count_by_scenario": dict(sorted(scenario_counts.items())),
            "random_seed_count": len(random_seeds),
            "detector_suite_version": DETECTOR_SUITE_VERSION,
            "scoring_version": scoring.get("scoring_version"),
            "priority_version": priority.get("priority_version"),
            "selection_policy_version": RECORD_SELECTION_POLICY_VERSION,
            "selection_frozen_before_ground_truth": True,
            "python_version": platform.python_version(),
        },
        "unit": "unique synthetic claim record",
        "metric_definitions": {
            "precision_at_k": "selected positive unique synthetic claim records / requested K; null if K cannot be met",
            "recall_at_k": "selected positive unique synthetic claim records / all positive unique synthetic claim records in population; null if denominator is zero or K cannot be met",
            "positive_records_per_100_selected_records": "100 * selected positive unique synthetic claim records / K; null if K cannot be met",
            "detector_coverage": "reported independently from audit selection; unassessed, partial, and unavailable are not negative labels",
        },
        "budgets": budgets,
        "detector_coverage": coverage,
        "facility_priority_diagnostics": priority_diagnostics,
        "near_duplicate_diagnostics": near_diagnostics,
        "limitations": [
            "Selection metrics compare synthetic scenario labels only; they do not measure real-world fraud detection performance.",
            "A record selected by fallback is an exploratory audit selection, not a detector positive.",
            "No green/yellow/red lane metrics are calculated because an equivalent population-wide policy for all methods is not defined.",
            "CIR inherits facility-priority assumptions and the available/partial coverage constraints of the underlying pipeline.",
        ],
    }
