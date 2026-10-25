"""Synthetic-only detector and facility-priority evaluation.

Ground truth is consumed only after detector and risk-scoring calls complete.
This module reports aggregate metrics and never returns claim-level labels.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import math
import random
import statistics
from typing import Any

from app.analytics.audit_priority import build_audit_priority_queue
from app.data_sources.synthetic_generator import SCENARIO_CODES
from app.analytics.risk_scoring import DETECTOR_ORDER, run_detector_suite, score_claims


EVALUATION_VERSION = "synthetic-evaluation-v1"
SUPPORTED_SCENARIOS = {
    "repeat_billing_candidate": ("repeat_billing",),
    # The exact matcher is not expected to recover deliberate attribute
    # variations in the cloning scenario; near-duplicate is the target there.
    "similar_claim_pattern_candidate": ("mixed_light_severe",),
    "near_duplicate_claim_candidate": ("cloning", "mixed_light_severe"),
    "synthetic_capacity_candidate": ("mixed_light_severe",),
    "temporal_pattern_candidate": ("repeat_billing", "cloning", "mixed_light_severe"),
    "supporting_evidence_completeness_candidate": (
        "phantom_physiotherapy", "action_without_support", "mixed_light_severe",
    ),
}
_FORBIDDEN_FEATURE_KEYS = {
    "is_anomaly", "is_synthetic_anomaly", "scenario", "scenario_label",
    "scenario_labels", "primary_scenario", "scenario_group_id", "scenario_code",
    "intensity_level", "injected_signals", "label_scope", "claim_labels",
    "group_labels", "ground_truth",
}


def confusion_metrics(
    actual_positive_ids: set[str],
    predicted_positive_ids: set[str],
    eligible_ids: set[str],
    universe_ids: set[str] | None = None,
) -> dict[str, int | float | None]:
    """Compute confusion counts on explicitly assessable items only.

    Undefined ratios are ``None``: precision without predictions, recall with
    no positives, F1 when precision/recall is undefined, and FPR with no
    negatives. This prevents silently turning undefined metrics into zero.
    """
    positives = actual_positive_ids & eligible_ids
    predictions = predicted_positive_ids & eligible_ids
    negatives = eligible_ids - positives
    tp = len(positives & predictions)
    fp = len(negatives & predictions)
    fn = len(positives - predictions)
    tn = len(negatives - predictions)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    ) if precision is not None and recall is not None else None
    fpr = fp / (fp + tn) if fp + tn else None
    universe = universe_ids if universe_ids is not None else (actual_positive_ids | eligible_ids)
    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": _round_metric(precision),
        "recall": _round_metric(recall),
        "f1_score": _round_metric(f1),
        "false_positive_rate": _round_metric(fpr),
        "evaluated_count": len(eligible_ids),
        "positive_label_count": len(positives),
        "predicted_positive_count": len(predictions),
        "unassessed_positive_label_count": len((actual_positive_ids & universe) - eligible_ids),
        "unassessed_negative_label_count": len((universe - actual_positive_ids) - eligible_ids),
    }


def _round_metric(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _candidate_case_ids(result: Mapping[str, Any]) -> set[str]:
    candidates = result.get("candidate_groups", result.get("candidates", []))
    ids: set[str] = set()
    if not isinstance(candidates, (list, tuple)):
        return ids
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        case_id = item.get("case_id")
        if isinstance(case_id, str):
            ids.add(case_id)
        case_ids = item.get("case_ids")
        if isinstance(case_ids, (list, tuple)):
            ids.update(value for value in case_ids if isinstance(value, str))
    return ids


def _detector_coverage(
    indicator: str,
    result: Mapping[str, Any] | None,
    scope_ids: set[str],
) -> tuple[set[str], set[str], dict[str, Any]]:
    """Return known positives, eligible IDs, and honest coverage metadata."""
    if not isinstance(result, Mapping) or result.get("status") == "unavailable" or result.get("indicator") != indicator:
        return set(), set(), {
            "status": "unavailable", "eligible_count": 0,
            "unassessed_count": len(scope_ids), "coverage_fraction": 0.0,
            "search_truncated": False, "candidate_count": 0,
            "failure_type": result.get("error_type") if isinstance(result, Mapping) else None,
        }
    predicted = _candidate_case_ids(result) & scope_ids
    declared_unassessed: set[str] = set()
    for key in ("ineligible_cases", "unassessed_cases", "unassessed_time_cases"):
        values = result.get(key, [])
        if isinstance(values, (list, tuple)):
            declared_unassessed.update(
                item["case_id"] for item in values
                if isinstance(item, Mapping) and isinstance(item.get("case_id"), str)
            )
    # Some bounded pair detectors expose omitted records directly as IDs
    # rather than as {case_id, reason} objects. Respect that scoped contract
    # even when the global hard-cap flag is false: stratified sampling can
    # leave explicit records unassessed without exhausting the comparison cap.
    explicit_unassessed_ids = result.get("unassessed_case_ids", [])
    if isinstance(explicit_unassessed_ids, (list, tuple)) and all(
        isinstance(case_id, str) for case_id in explicit_unassessed_ids
    ):
        declared_unassessed.update(
            explicit_unassessed_ids
        )
    elif "unassessed_case_ids" in result:
        # Malformed coverage metadata must fail closed for negative findings.
        declared_unassessed.update(scope_ids - predicted)
    declared_unassessed &= scope_ids
    truncated_groups = any(
        isinstance(item, Mapping) and item.get("case_ids_truncated") is True
        for item in result.get("candidate_groups", result.get("candidates", []))
    )
    search_truncated = result.get("search_truncated") is True or truncated_groups
    if search_truncated:
        # Only explicit predictions are safely classifiable; absence from a
        # bounded search cannot be counted as a negative prediction.
        eligible = predicted
    else:
        eligible = scope_ids - declared_unassessed
    eligible |= predicted
    unassessed_ids = scope_ids - eligible
    unassessed_count = len(unassessed_ids)
    status = "unavailable" if not eligible else ("partial" if unassessed_count else "complete")
    raw_candidates = result.get("candidate_groups", result.get("candidates", []))
    return predicted, eligible, {
        "status": status,
        "eligible_count": len(eligible),
        "unassessed_count": unassessed_count,
        "coverage_fraction": _round_metric(len(eligible) / len(scope_ids)) if scope_ids else None,
        "search_truncated": search_truncated,
        "unassessed_declared_count": len(declared_unassessed - predicted),
        "unassessed_due_to_truncation_count": max(0, unassessed_count - len(declared_unassessed - predicted)) if search_truncated else 0,
        "candidate_count": len(raw_candidates) if isinstance(raw_candidates, (list, tuple)) else 0,
        "pair_comparisons": result.get("pair_comparisons"),
        "search_parameters": result.get("search_parameters"),
    }


def _metrics_for_scenario(
    labels_by_id: Mapping[str, Mapping[str, Any]],
    predicted: set[str],
    eligible: set[str],
    scenario: str,
    normal_ids: set[str],
) -> dict[str, Any]:
    actual = {case_id for case_id, label in labels_by_id.items() if label.get("primary_scenario") == scenario}
    scenario_scope = actual | normal_ids
    scenario_eligible = eligible & scenario_scope
    metrics = confusion_metrics(actual, predicted, scenario_eligible, scenario_scope)
    metrics["applicable_count"] = len(scenario_scope)
    metrics["not_applicable_anomaly_count"] = 0
    metrics["coverage_fraction"] = _round_metric(len(scenario_eligible) / len(scenario_scope)) if scenario_scope else None
    return metrics


def _ranking_metrics(selected: Sequence[str], positive_facilities: set[str], total_facilities: int) -> dict[str, Any]:
    k = len(selected)
    hits = sum(facility in positive_facilities for facility in selected)
    precision = hits / k if k else None
    recall = hits / len(positive_facilities) if positive_facilities else None
    prevalence = len(positive_facilities) / total_facilities if total_facilities else None
    return {
        "k": k,
        "anomaly_facilities_prioritized": hits,
        "precision_at_k": _round_metric(precision),
        "recall_at_k": _round_metric(recall),
        "facility_anomaly_prevalence": _round_metric(prevalence),
        "lift_vs_facility_prevalence": _round_metric(precision / prevalence) if precision is not None and prevalence else None,
    }


def _facility_ranking_evaluation(
    facilities: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
    labels_by_id: Mapping[str, Mapping[str, Any]],
    scored: Mapping[str, Any],
    priority_queue: Mapping[str, Any],
    budget_fractions: Sequence[float],
    random_seeds: Sequence[int],
) -> dict[str, Any]:
    facility_ids = sorted({item.get("facility_id") for item in facilities if isinstance(item.get("facility_id"), str)})
    if not facility_ids:
        return {"status": "not_available", "reason": "Tidak ada ID fasilitas sintetis yang dapat dievaluasi."}
    facility_set = set(facility_ids)
    facility_by_case = {
        row["case_id"]: row.get("facility_id")
        for row in records if isinstance(row.get("case_id"), str)
    }
    positive_facilities = {
        facility_by_case[case_id]
        for case_id, label in labels_by_id.items()
        if label.get("is_synthetic_anomaly") is True
        and facility_by_case.get(case_id) in facility_set
    }
    scored_cases = scored.get("cases", [])
    flagged_claim_counts: Counter[str] = Counter()
    for item in scored_cases:
        facility_id = item.get("facility_id")
        if facility_id in facility_set and item.get("triggered_indicators"):
            flagged_claim_counts[facility_id] += 1
    simple_order = sorted(facility_ids, key=lambda value: (-flagged_claim_counts[value], value))

    priority_items = [
        item for item in priority_queue.get("items", [])
        if item.get("unit_kind") == "synthetic_facility"
        and isinstance(item.get("unit_id"), str)
    ]
    facility_from_unit = {f"synthetic-audit-unit:{value}": value for value in facility_ids}
    priority_order = [facility_from_unit[item["unit_id"]] for item in priority_items if item["unit_id"] in facility_from_unit]
    priority_order += [value for value in facility_ids if value not in set(priority_order)]
    detector_coverage = scored.get("detector_coverage", [])
    truncated_indicators = sorted(
        item["indicator"] for item in detector_coverage
        if isinstance(item, Mapping) and item.get("search_truncated") is True
        and isinstance(item.get("indicator"), str)
    )
    partial_priority_unit_count = sum(
        item.get("priority_status") in {"partial", "not_assessable"}
        for item in priority_items
    )
    priority_unit_ids = {
        facility_from_unit[item["unit_id"]]
        for item in priority_items if item["unit_id"] in facility_from_unit
    }
    random_orders: list[tuple[int, list[str]]] = []
    for random_seed in random_seeds:
        shuffled = facility_ids.copy()
        random.Random(random_seed).shuffle(shuffled)
        random_orders.append((random_seed, shuffled))

    budget_reports: dict[str, Any] = {}
    for budget_fraction in budget_fractions:
        budget_k = min(len(facility_ids), max(1, math.ceil(len(facility_ids) * budget_fraction)))
        random_runs = [
            _ranking_metrics(order[:budget_k], positive_facilities, len(facility_ids))
            for _, order in random_orders
        ]
        random_precision_values = [row["precision_at_k"] for row in random_runs if row["precision_at_k"] is not None]
        random_mean_precision = statistics.fmean(random_precision_values) if random_precision_values else None
        random_mean_recall = statistics.fmean(
            row["recall_at_k"] for row in random_runs if row["recall_at_k"] is not None
        ) if positive_facilities else None
        random_mean_hits = statistics.fmean(row["anomaly_facilities_prioritized"] for row in random_runs)
        random_lift_values = [row["lift_vs_facility_prevalence"] for row in random_runs if row["lift_vs_facility_prevalence"] is not None]

        def approach(order: Sequence[str]) -> dict[str, Any]:
            metrics = _ranking_metrics(order[:budget_k], positive_facilities, len(facility_ids))
            precision = metrics["precision_at_k"]
            metrics["lift_vs_random_mean"] = (
                _round_metric(precision / random_mean_precision)
                if precision is not None and random_mean_precision not in {None, 0}
                else None
            )
            metrics["status"] = "not_discriminative" if not positive_facilities or len(positive_facilities) == len(facility_ids) else "measured_on_synthetic_labels"
            return metrics

        random_status = "not_discriminative" if not positive_facilities or len(positive_facilities) == len(facility_ids) else "measured_on_synthetic_labels"
        budget_reports[f"{budget_fraction:.4f}"] = {
            "budget_fraction": budget_fraction,
            "shared_budget_k": budget_k,
            "approaches": {
                "random_baseline": {
                    "status": random_status,
                    "seed_count": len(random_runs),
                    "seeds": list(random_seeds),
                    "anomaly_facilities_prioritized_mean": _round_metric(random_mean_hits),
                    "precision_at_k_mean": _round_metric(random_mean_precision),
                    "precision_at_k_stddev": _round_metric(statistics.pstdev(random_precision_values)) if len(random_precision_values) > 1 else (0.0 if random_precision_values else None),
                    "recall_at_k_mean": _round_metric(random_mean_recall),
                    "lift_vs_facility_prevalence_mean": _round_metric(statistics.fmean(random_lift_values)) if random_lift_values else None,
                },
                "simple_rule_flagged_claim_count": approach(simple_order),
                "claim_integrity_radar_priority": approach(priority_order),
            },
        }

    return {
        "status": "not_discriminative" if not positive_facilities or len(positive_facilities) == len(facility_ids) else "measured_on_synthetic_labels",
        "unit": "synthetic facility",
        "facility_count": len(facility_ids),
        "anomaly_facility_count": len(positive_facilities),
        "anomaly_facility_prevalence": _round_metric(len(positive_facilities) / len(facility_ids)) if facility_ids else None,
        "positive_facility_count_from_claim_labels": len(positive_facilities),
        "negative_facility_count_from_claim_labels": len(facility_ids) - len(positive_facilities),
        "priority_queue_facility_count": len(priority_unit_ids),
        "priority_queue_facilities_without_triggered_unit": len(facility_ids) - len(priority_unit_ids),
        "partial_priority_unit_count": partial_priority_unit_count,
        "truncated_indicators_affecting_priority": truncated_indicators,
        "budgets": budget_reports,
        "simple_rule_definition": "Count distinct claims with at least one triggered detector per facility; descending, then synthetic facility ID ascending.",
        "priority_definition": "Existing audit-priority queue order, completed with facilities without queue items at the end in synthetic facility ID order.",
        "limitations": [
            "Facility anomaly is aggregated from is_synthetic_anomaly claim labels after the detector/scoring/ranking pipeline; labels never enter features or ranking inputs.",
            "Facility ranking results depend on the benchmark generator's positive-facility prevalence and do not establish operational utility.",
            "A missing detector signal is not interpreted as a claim or facility proven normal.",
            "The priority order may change because detector searches are bounded or some claims are unassessed." if truncated_indicators or partial_priority_unit_count else "No detector search truncation or partial priority unit was reported for this run.",
        ],
    }


def evaluate_synthetic_dataset(
    records: Sequence[Mapping[str, Any]],
    facilities: Sequence[Mapping[str, Any]],
    ground_truth: Any,
    *,
    seed: int,
    generator_version: str,
    target_anomaly_rate: float,
    generator_metadata: Mapping[str, Any] | None = None,
    audit_budget_fractions: Sequence[float] | None = None,
    audit_budget_fraction: float | None = None,
    random_seed_count: int = 30,
) -> dict[str, Any]:
    """Run detectors/scoring on features, then compare aggregate output to truth."""
    if audit_budget_fraction is not None:
        budget_fractions = (audit_budget_fraction,)
    else:
        budget_fractions = tuple(audit_budget_fractions or (0.05, 0.10, 0.20))
    if not budget_fractions or any(not 0 < value <= 1 for value in budget_fractions):
        raise ValueError("setiap audit budget harus berada pada (0, 1]")
    if len(set(budget_fractions)) != len(budget_fractions):
        raise ValueError("audit budgets tidak boleh duplikat")
    if random_seed_count < 1:
        raise ValueError("random_seed_count minimal 1")
    feature_ids: set[str] = set()
    for row in records:
        if _FORBIDDEN_FEATURE_KEYS & set(row):
            raise ValueError("Ground-truth field terdeteksi pada fitur; evaluasi dibatalkan")
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or case_id in feature_ids:
            raise ValueError("case_id fitur harus valid dan unik")
        feature_ids.add(case_id)
    labels = getattr(ground_truth, "claim_labels", None)
    if labels is None and isinstance(ground_truth, Mapping):
        labels = ground_truth.get("claim_labels")
    if not isinstance(labels, (list, tuple)):
        raise ValueError("ground_truth.claim_labels tidak tersedia")
    labels_by_id: dict[str, Mapping[str, Any]] = {}
    for label in labels:
        if not isinstance(label, Mapping) or not isinstance(label.get("case_id"), str):
            raise ValueError("Label harus memiliki case_id sintetis")
        if label["case_id"] in labels_by_id:
            raise ValueError("Label case_id duplikat")
        labels_by_id[label["case_id"]] = label
    if set(labels_by_id) != feature_ids:
        raise ValueError("ID label dan fitur harus mencakup klaim yang sama")
    if any(not isinstance(label.get("is_synthetic_anomaly"), bool) for label in labels_by_id.values()):
        raise ValueError("is_synthetic_anomaly harus boolean")
    if any(
        label.get("is_synthetic_anomaly") is True
        and label.get("primary_scenario") not in SCENARIO_CODES
        for label in labels_by_id.values()
    ):
        raise ValueError("Setiap klaim anomali harus memiliki skenario target yang dikenal")
    facility_ids = {
        row.get("facility_id") for row in records
        if isinstance(row.get("facility_id"), str)
    }
    facility_labels = getattr(ground_truth, "facility_labels", None)
    if facility_labels:
        facility_label_map = {
            item.get("facility_id"): item
            for item in facility_labels if isinstance(item, Mapping)
        }
        if set(facility_label_map) != facility_ids:
            raise ValueError("ID label fasilitas dan fasilitas fitur harus sama")
        record_facility = {
            row["case_id"]: row.get("facility_id") for row in records
            if isinstance(row.get("case_id"), str)
        }
        derived_anomaly_counts: Counter[str] = Counter(
            record_facility[case_id]
            for case_id, label in labels_by_id.items()
            if label.get("is_synthetic_anomaly") is True
        )
        for facility_id, label in facility_label_map.items():
            expected_count = derived_anomaly_counts[facility_id]
            if label.get("anomaly_claim_count") != expected_count or label.get("is_synthetic_anomaly_facility") is not (expected_count > 0):
                raise ValueError("Label fasilitas tidak konsisten dengan agregasi label klaim")

    # Critical boundary: only feature records and facility metadata are passed
    # into detectors. Ground truth is first consulted below this boundary.
    detector_results = run_detector_suite(records, facilities)
    scored = score_claims(records, detector_results)
    priority_queue = build_audit_priority_queue(records, scored)
    universe = feature_ids
    all_positive_ids = {
        case_id for case_id, label in labels_by_id.items()
        if label.get("is_synthetic_anomaly") is True
    }
    normal_ids = {
        case_id for case_id, label in labels_by_id.items()
        if label.get("is_synthetic_anomaly") is False and label.get("primary_scenario") is None
    }
    non_normal_negative_count = len(labels_by_id) - len(all_positive_ids) - len(normal_ids)
    if non_normal_negative_count:
        raise ValueError("Label non-anomali dengan primary_scenario terisi belum memiliki protokol evaluasi")

    detector_reports: dict[str, Any] = {}
    for indicator in DETECTOR_ORDER:
        result = detector_results.get(indicator)
        target_scenarios = set(SUPPORTED_SCENARIOS[indicator])
        target_positive_ids = {
            case_id for case_id, label in labels_by_id.items()
            if label.get("is_synthetic_anomaly") is True
            and label.get("primary_scenario") in target_scenarios
        }
        scope_ids = target_positive_ids | normal_ids
        predicted, eligible, coverage = _detector_coverage(indicator, result, scope_ids)
        metrics = confusion_metrics(target_positive_ids, predicted, eligible, scope_ids)
        not_applicable_anomalies = all_positive_ids - target_positive_ids
        coverage.update({
            "applicable_count": len(scope_ids),
            "target_positive_label_count": len(target_positive_ids),
            "normal_negative_label_count": len(normal_ids),
            "not_applicable_anomaly_count": len(not_applicable_anomalies),
            "unassessed_positive_label_count": metrics["unassessed_positive_label_count"],
            "unassessed_negative_label_count": metrics["unassessed_negative_label_count"],
        })
        scenario_metrics = {
            scenario: _metrics_for_scenario(labels_by_id, predicted, eligible, scenario, normal_ids)
            for scenario in sorted(SUPPORTED_SCENARIOS[indicator])
        }
        detector_reports[indicator] = {
            "metrics_target_scenarios_vs_normal": metrics,
            "supported_scenarios": list(SUPPORTED_SCENARIOS[indicator]),
            "metrics_by_supported_scenario": scenario_metrics,
            "coverage": coverage,
        }

    scored_by_id = {
        item["case_id"]: item for item in scored.get("cases", [])
        if isinstance(item, Mapping) and isinstance(item.get("case_id"), str)
    }
    combined_predictions = {
        case_id for case_id, item in scored_by_id.items()
        if item.get("triggered_indicators")
    }
    combined_scope = all_positive_ids | normal_ids
    combined_eligible = {
        case_id for case_id, item in scored_by_id.items()
        if case_id in combined_scope
        and (item.get("triggered_indicators") or item.get("score_status") in {"assessed", "assessed_no_signal"})
    } & combined_scope
    combined_predictions &= combined_scope
    combined_metrics = confusion_metrics(all_positive_ids, combined_predictions, combined_eligible, combined_scope)
    unassessed_combined = len(combined_scope - combined_eligible)
    combined_report = {
        "definition": "A claim in any targeted synthetic anomaly scenario is positive; a normal claim is negative. A claim is predicted positive when at least one detector contributes a trigger to the existing rule score. Untriggered claims with partial/unavailable scoring coverage are unassessed.",
        "metrics": combined_metrics,
        "coverage": {
            "status": "partial" if unassessed_combined else "complete",
            "applicable_count": len(combined_scope),
            "eligible_count": len(combined_eligible),
            "unassessed_count": unassessed_combined,
            "not_applicable_anomaly_count": len(all_positive_ids - combined_scope),
            "coverage_fraction": _round_metric(len(combined_eligible) / len(combined_scope)) if combined_scope else None,
            "detector_coverage": scored.get("detector_coverage", []),
        },
    }

    random_seeds = [seed + 10_000 + index for index in range(random_seed_count)]
    ranking_report = _facility_ranking_evaluation(
        facilities, records, labels_by_id, scored, priority_queue,
        budget_fractions, random_seeds,
    )
    anomaly_scenario_counts = Counter(
        str(label.get("primary_scenario"))
        for label in labels_by_id.values() if label.get("is_synthetic_anomaly") is True
    )
    return {
        "evaluation_version": EVALUATION_VERSION,
        "data_source": "synthetic_experiment_only",
        "metadata": {
            "generator_version": str(generator_version),
            "seed": seed,
            "claim_count": len(records),
            "facility_count": len(facilities),
            "target_anomaly_rate": target_anomaly_rate,
            "synthetic_anomaly_claim_count": len(all_positive_ids),
            "synthetic_anomaly_claim_count_by_scenario": dict(sorted(anomaly_scenario_counts.items())),
            "negative_claim_count": len(universe - all_positive_ids),
            "normal_claim_count_in_scope": len(normal_ids),
            "generator_configuration": {
                key: value for key, value in (generator_metadata or {}).items()
                if isinstance(value, (str, int, float, bool, type(None)))
            },
        },
        "metric_definitions": {
            "unit": "claim within each detector's target-scenario plus normal-negative scope; synthetic facility for ranking metrics",
            "precision": "TP / (TP + FP); null when no positive predictions",
            "recall": "TP / (TP + FN); null when no positive ground truth in the evaluated subset",
            "f1_score": "harmonic mean of defined precision and recall; null if either is undefined",
            "false_positive_rate": "FP / (FP + TN); null when no evaluable negatives",
            "unassessed": "eligible-scope claims excluded from TP/FP/TN/FN when unqualified, unavailable, or hidden by truncation; no signal under incomplete coverage is not a negative",
            "not_applicable": "non-target anomaly scenarios are excluded from that detector's metric population, not treated as negatives",
            "facility_positive": "facility containing at least one synthetic anomaly-labeled claim",
        },
        "detectors": detector_reports,
        "combined": combined_report,
        "priority_ranking": ranking_report,
        "limitations": [
            "Labels are scenario-defined synthetic ground truth, not verified BPJS fraud labels.",
            "Results depend on generator construction/version, injection rate, thresholds, and selected seed.",
            "Scenario-specific results are reported only for scenarios each detector was designed to address; they do not imply every detector should detect every scenario.",
            "Near-duplicate and other bounded/truncated searches leave claims unassessed as documented; their absence from candidate output is not treated as a true negative.",
            "The provisional risk score is not a fraud probability; ranking quality on this synthetic benchmark is not real-world audit utility.",
        ],
    }
