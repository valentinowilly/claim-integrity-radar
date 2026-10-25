"""Label-blind record selectors for synthetic audit-budget experiments.

Selected case IDs are transient evaluator inputs. Persist/export only the
aggregate returned by :meth:`RecordSelection.summary`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import math
import random
from typing import Any


SELECTION_SEED = 12026
RECORD_SELECTION_POLICY_VERSION = "record-selection-v1"
FORBIDDEN_LABEL_KEYS = frozenset({
    "is_anomaly", "is_anomalous", "is_synthetic_anomaly", "scenario", "scenario_label",
    "scenario_labels", "primary_scenario", "scenario_group_id", "scenario_code",
    "intensity_level", "injected_signals", "label_scope", "ground_truth",
    "claim_labels", "group_labels", "facility_labels",
})


@dataclass(frozen=True)
class RecordSelection:
    method: str
    requested_k: int
    selected_case_ids: tuple[str, ...]
    status: str
    selection_counts: Mapping[str, int]
    limitations: tuple[str, ...] = ()
    selected_by_path: Mapping[str, tuple[str, ...]] = field(default_factory=dict, repr=False)

    @property
    def comparable(self) -> bool:
        return self.status == "comparable"

    def summary(self) -> dict[str, Any]:
        """Return safe aggregate metadata; never includes record identifiers."""
        return {
            "method": self.method,
            "status": self.status,
            "comparable": self.comparable,
            "requested_k": self.requested_k,
            "selected_unique_record_count": len(self.selected_case_ids),
            "selection_counts": dict(self.selection_counts),
            "limitations": list(self.limitations),
        }


def _validate(records: Sequence[Mapping[str, Any]], k: int) -> tuple[dict[str, Mapping[str, Any]], list[str]]:
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("K must be a positive integer")
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in records:
        if not isinstance(row, Mapping):
            raise ValueError("Each feature record must be a mapping")
        if FORBIDDEN_LABEL_KEYS & set(row):
            raise ValueError("Ground-truth fields are forbidden in selector features")
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("Each feature record must have a non-empty case_id")
        if case_id in by_id:
            raise ValueError("Feature case_id values must be unique")
        by_id[case_id] = row
    if not by_id:
        raise ValueError("Feature population must not be empty")
    return by_id, sorted(by_id)


def _tie_key(seed: int, namespace: str, value: str) -> str:
    payload = f"{RECORD_SELECTION_POLICY_VERSION}\0{seed}\0{namespace}\0{value}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def random_selection(
    records: Sequence[Mapping[str, Any]], k: int, *, seed: int = SELECTION_SEED,
) -> RecordSelection:
    by_id, ids = _validate(records, k)
    rng = random.Random(seed)
    chosen = tuple(rng.sample(ids, min(k, len(ids))))
    return RecordSelection(
        "random_uniform_without_replacement", k, chosen,
        "comparable" if len(chosen) == k else "not_comparable",
        {"uniform_random": len(chosen)},
        () if len(chosen) == k else ("Populasi tidak memiliki cukup record unik untuk memenuhi K.",),
        {"uniform_random": chosen},
    )


def _repeat_candidate_ids(repeat_result: Mapping[str, Any], population: set[str]) -> set[str]:
    if repeat_result.get("indicator") != "repeat_billing_candidate":
        raise ValueError("Only repeat_billing_candidate may drive the single-rule baseline")
    groups = repeat_result.get("candidate_groups")
    if not isinstance(groups, (list, tuple)):
        raise ValueError("repeat_billing candidate_groups must be present")
    candidate_ids: set[str] = set()
    for group in groups:
        if not isinstance(group, Mapping) or not isinstance(group.get("case_ids"), (list, tuple)):
            raise ValueError("Malformed repeat_billing candidate group")
        ids = group["case_ids"]
        if any(not isinstance(case_id, str) for case_id in ids):
            raise ValueError("Malformed repeat_billing case identifier")
        unknown = set(ids) - population
        if unknown:
            raise ValueError("repeat_billing output references records outside the feature population")
        candidate_ids.update(ids)
    return candidate_ids


def simple_rule_selection(
    records: Sequence[Mapping[str, Any]],
    repeat_billing_result: Mapping[str, Any],
    k: int,
    *, seed: int = SELECTION_SEED,
) -> RecordSelection:
    """Rank only repeat-billing members; fill remaining audit budget randomly.

    The detector has no rule-specific score. Seeded hash ordering is used for
    ties among candidates and in the fallback pool; no score is fabricated.
    """
    by_id, ids = _validate(records, k)
    population = set(by_id)
    candidates = _repeat_candidate_ids(repeat_billing_result, population)
    ordered_candidates = sorted(candidates, key=lambda case_id: _tie_key(seed, "repeat", case_id))
    primary = ordered_candidates[:k]
    remaining = [case_id for case_id in ids if case_id not in candidates]
    ordered_fallback = sorted(remaining, key=lambda case_id: _tie_key(seed, "simple-fallback", case_id))
    needed = max(0, k - len(primary))
    fallback = ordered_fallback[:needed]
    chosen = tuple(primary + fallback)
    enough = len(chosen) == k
    return RecordSelection(
        "repeat_billing_single_rule", k, chosen,
        "comparable" if enough else "not_comparable",
        {"repeat_billing_rule": len(primary), "exploratory_fallback": len(fallback)},
        () if enough else ("Populasi tidak memiliki cukup record unik untuk memenuhi K.",),
        {"repeat_billing_rule": tuple(primary), "exploratory_fallback": tuple(fallback)},
    )


def _valid_priority(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def cir_priority_selection(
    records: Sequence[Mapping[str, Any]],
    scoring_result: Mapping[str, Any],
    facility_priority: Mapping[str, Any],
    k: int,
    *, seed: int = SELECTION_SEED,
) -> RecordSelection:
    """Select within valid facility-priority units, then explore the remainder.

    Existing per-case ``risk_score`` is used only when finite and its status
    is not ``not_assessable``. Unknown scores are not replaced with zero; they
    follow scored records via a deterministic seeded tie order.
    """
    by_id, ids = _validate(records, k)
    case_items = scoring_result.get("cases")
    if not isinstance(case_items, (list, tuple)):
        raise ValueError("scoring_result.cases must be present")
    scores: dict[str, tuple[float | None, str | None]] = {}
    for item in case_items:
        if not isinstance(item, Mapping) or not isinstance(item.get("case_id"), str):
            raise ValueError("Malformed scored case")
        case_id = item["case_id"]
        if case_id not in by_id or case_id in scores:
            raise ValueError("Scored case IDs must be unique members of the population")
        score = _valid_priority(item.get("risk_score"))
        if score is not None and score > 1:
            score = None
        if item.get("score_status") == "not_assessable":
            score = None
        scores[case_id] = (score, item.get("score_status") if isinstance(item.get("score_status"), str) else None)

    facility_items = facility_priority.get("items")
    if not isinstance(facility_items, (list, tuple)):
        raise ValueError("facility_priority.items must be present")
    facility_order: list[tuple[str, float]] = []
    seen_facilities: set[str] = set()
    records_by_facility: dict[str, list[str]] = {}
    for case_id, row in by_id.items():
        facility_id = row.get("facility_id")
        if isinstance(facility_id, str) and facility_id:
            records_by_facility.setdefault(facility_id, []).append(case_id)
    for item in facility_items:
        if not isinstance(item, Mapping):
            continue
        facility_id = item.get("unit_id")
        # Queue unit IDs use `synthetic-audit-unit:<facility_id>`; accept only
        # explicitly available, finite indices from that established schema.
        prefix = "synthetic-audit-unit:"
        if not isinstance(facility_id, str) or not facility_id.startswith(prefix):
            continue
        facility_id = facility_id[len(prefix):]
        if facility_id not in records_by_facility:
            continue
        priority = _valid_priority(item.get("priority_index"))
        if item.get("priority_status") != "available" or priority is None:
            continue
        if facility_id in seen_facilities:
            raise ValueError("Duplicate facility priority unit")
        seen_facilities.add(facility_id)
        facility_order.append((facility_id, priority))

    # Higher facility priority first; seeded tie-break avoids using IDs or any
    # ground-truth-dependent ordering for equal scores.
    facility_order.sort(key=lambda pair: (-pair[1], _tie_key(seed, "facility", pair[0])))
    selected: list[str] = []
    prioritized_count = 0
    fallback_count = 0
    selected_set: set[str] = set()

    def record_order(case_id: str) -> tuple[int, float, str]:
        score, _ = scores.get(case_id, (None, None))
        # Rank valid observed scores before unavailable scores; do not coerce
        # missing assessment into numeric zero.
        return (0 if score is not None else 1, -(score or 0.0) if score is not None else 0.0,
                _tie_key(seed, "record", case_id))

    for facility_id, _ in facility_order:
        facility_records = sorted(records_by_facility[facility_id], key=record_order)
        for case_id in facility_records:
            if len(selected) == k:
                break
            if case_id not in selected_set:
                selected.append(case_id)
                selected_set.add(case_id)
                prioritized_count += 1
        if len(selected) == k:
            break

    # Exploratory fallback is restricted to records outside facilities with
    # a valid facility-priority row. No signal/priority is not a negative.
    valid_facility_ids = {facility_id for facility_id, _ in facility_order}
    fallback_pool = [
        case_id for case_id in ids
        if case_id not in selected_set and by_id[case_id].get("facility_id") not in valid_facility_ids
    ]
    fallback_pool.sort(key=lambda case_id: _tie_key(seed, "cir-fallback", case_id))
    for case_id in fallback_pool[:max(0, k - len(selected))]:
        selected.append(case_id)
        selected_set.add(case_id)
        fallback_count += 1

    enough = len(selected) == k
    limitations: list[str] = []
    valid_population_count = sum(row.get("facility_id") in valid_facility_ids for row in by_id.values())
    if valid_population_count < len(by_id):
        limitations.append("Sebagian populasi tidak memiliki facility priority valid; record tersebut hanya dapat masuk melalui fallback eksploratori.")
    if not enough:
        limitations.append("K tidak dapat dipenuhi dari record unik yang tersedia dalam jalur prioritas dan fallback yang memenuhi syarat.")
    return RecordSelection(
        "cir_facility_priority", k, tuple(selected),
        "comparable" if enough else "not_comparable",
        {
            "valid_facility_priority": prioritized_count,
            "exploratory_fallback": fallback_count,
            "population_records_with_valid_facility_priority": valid_population_count,
            "population_records_without_valid_facility_priority": len(by_id) - valid_population_count,
        },
        tuple(limitations),
        {
            "valid_facility_priority": tuple(selected[:prioritized_count]),
            "exploratory_fallback": tuple(selected[prioritized_count:]),
        },
    )


def selected_assessment_summary(
    selection: RecordSelection,
    scoring_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Aggregate saved score/coverage states for selected records only.

    This does not infer a negative result from absent findings and emits no
    case/facility identifiers.
    """
    raw_cases = scoring_result.get("cases")
    if not isinstance(raw_cases, (list, tuple)):
        raise ValueError("scoring_result.cases must be present")
    by_id: dict[str, Mapping[str, Any]] = {}
    for case in raw_cases:
        if not isinstance(case, Mapping) or not isinstance(case.get("case_id"), str):
            raise ValueError("Malformed scored case")
        if case["case_id"] in by_id:
            raise ValueError("Scored case IDs must be unique")
        by_id[case["case_id"]] = case
    missing = set(selection.selected_case_ids) - set(by_id)
    if missing:
        raise ValueError("Selected records are missing from scoring output")
    def summarize(case_ids: Sequence[str]) -> dict[str, Any]:
        status_counts: dict[str, int] = {}
        indicator_counts: dict[str, dict[str, int]] = {}
        for case_id in case_ids:
            case = by_id[case_id]
            status = case.get("score_status")
            if not isinstance(status, str):
                status = "unavailable"
            status_counts[status] = status_counts.get(status, 0) + 1
            states = case.get("indicator_coverage", [])
            if isinstance(states, (list, tuple)):
                for item in states:
                    if not isinstance(item, Mapping) or not isinstance(item.get("indicator"), str):
                        continue
                    name = item["indicator"]
                    state = item.get("status")
                    if not isinstance(state, str):
                        state = "unavailable"
                    per_state = indicator_counts.setdefault(name, {})
                    per_state[state] = per_state.get(state, 0) + 1
        return {
            "selected_record_count": len(case_ids),
            "score_status_counts": status_counts,
            "indicator_assessment_counts": indicator_counts,
        }

    return {
        **summarize(selection.selected_case_ids),
        "selection_path_assessment": {
            path: summarize(case_ids)
            for path, case_ids in selection.selected_by_path.items()
        },
        "note": "Coverage status is reported as supplied; unassessed and unavailable records are not treated as negative.",
    }
