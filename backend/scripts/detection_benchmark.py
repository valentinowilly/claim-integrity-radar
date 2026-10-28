"""Reproducible synthetic benchmark for rule checks and the ML ranking, evaluated independently.

Run from ``backend/``::

    python -m scripts.detection_benchmark --seeds 1-10
    python -m scripts.detection_benchmark --seeds 1-10 --duration

Everything here is generated synthetic data in the FKRTL canonical feature
shape (no amount, no facility ID). Ground truth (per-record expected states and
labelled planted pairs) lives only in the separate ``truth`` structure returned
by ``generate_benchmark``; it never enters the records given to the detectors
or the model. Results are synthetic-benchmark behaviour of the current,
untuned configuration, not validated real-world fraud detection.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
import hashlib
import json
import random
from statistics import mean, median
from typing import Any, Mapping, Sequence

from app.analytics.ml_anomaly import build_ml_anomaly_ranking
from app.analytics.near_duplicate_claims import NearDuplicateConfig, detect_near_duplicate_claims
from app.analytics.repeat_billing import AMOUNT_WITHHELD_SIGNATURE_FIELDS, detect_repeat_billing_candidates

BENCHMARK_VERSION = "cir-synthetic-detection-benchmark-v2"
WINDOW_START = date(2024, 3, 4)
WINDOW_DAYS = 7
K_VALUES = (10, 25, 50)
DEFAULT_SEEDS = tuple(range(1, 11))

# Per-scenario expected state for each method. "repeat" is the record-level
# expectation of the same-participant repeat rule; "near" says whether the
# record belongs to a labelled near-duplicate target or hard-negative pair;
# "ml" says whether the record is an ML target or a labelled benign rare record.
SCENARIOS: dict[str, dict[str, str]] = {
    "normal": {"repeat": "no_flag", "near": "background", "ml": "background",
               "meaning": "Routine claim from the common code distribution."},
    "benign_rare": {"repeat": "no_flag", "near": "background", "ml": "benign_rare",
                    "meaning": "Valid claim with rare but internally consistent codes and a normal stay."},
    "exact_repeat": {"repeat": "flag", "near": "background", "ml": "background",
                     "meaning": "Same participant, same admission date, identical codes."},
    "repeat_hard_negative": {"repeat": "no_flag", "near": "background", "ml": "background",
                             "meaning": "Same participant and date, different procedure: a separate service."},
    "incomplete_repeat": {"repeat": "unassessed", "near": "background", "ml": "background",
                          "meaning": "Would-be repeat with a blank procedure."},
    "next_day_repeat": {"repeat": "no_flag", "near": "background", "ml": "background",
                        "meaning": "Identical codes on consecutive days: outside the same-day repeat rule."},
    "clone_rare_template": {"repeat": "no_flag", "near": "target", "ml": "background",
                            "meaning": "Different participants, identical except admission diagnosis, unique procedure code."},
    "clone_common_template": {"repeat": "no_flag", "near": "target", "ml": "background",
                              "meaning": "Different participants, identical except admission diagnosis, routine codes."},
    "routine_same_day": {"repeat": "no_flag", "near": "hard_negative", "ml": "background",
                         "meaning": "Legitimate same-day claims of different participants with a common code combination."},
    "different_service_same_day": {"repeat": "no_flag", "near": "hard_negative", "ml": "background",
                                   "meaning": "Same date/district/diagnosis, different INA-CBG and procedure (2 differences)."},
    "three_differences": {"repeat": "no_flag", "near": "hard_negative", "ml": "background",
                          "meaning": "Same date/district/diagnosis, three differing attributes with common codes."},
    "ml_code_mismatch": {"repeat": "no_flag", "near": "background", "ml": "target",
                         "meaning": "Common diagnosis with another family's INA-CBG/procedure, normal stay."},
    "ml_long_stay": {"repeat": "no_flag", "near": "background", "ml": "target",
                     "meaning": "Consistent common codes with a 20-30 day stay."},
    "ml_frequent_visitor": {"repeat": "no_flag", "near": "background", "ml": "target",
                            "meaning": "One participant with five visits in the window, common codes, different days."},
    "both_repeat_and_ml": {"repeat": "flag", "near": "background", "ml": "target",
                           "meaning": "Exact repeat pair with mismatched codes and a long stay."},
}
NEAR_TARGET_KINDS = ("clone_rare_template", "clone_common_template")
NEAR_NEGATIVE_KINDS = ("routine_same_day", "different_service_same_day", "three_differences")
REPEAT_PAIR_KINDS = ("exact_repeat", "repeat_hard_negative", "incomplete_repeat", "next_day_repeat", "both_repeat_and_ml")
ML_TARGET_KINDS = ("ml_code_mismatch", "ml_long_stay", "ml_frequent_visitor", "both_repeat_and_ml")


def _opaque(seed: int, kind: str, index: int) -> str:
    return hashlib.sha256(f"{seed}|{kind}|{index}".encode()).hexdigest()[:20]


def _code_tables(rng: random.Random) -> dict[str, Any]:
    diagnoses = [f"D{index:02d}" for index in range(30)]
    weights = [1 / (rank + 1) for rank in range(30)]  # Zipf-like frequency
    cbg_for = {dx: f"G{index % 10}" for index, dx in enumerate(diagnoses)}
    procedures = {f"G{index}": [f"G{index}P{p}" for p in range(3)] for index in range(10)}
    municipalities = [f"M{index}" for index in range(6)]
    return {"diagnoses": diagnoses, "weights": weights, "cbg_for": cbg_for, "procedures": procedures,
            "municipalities": municipalities, "rng": rng}


def _claim(tables: Mapping[str, Any], case: str, participant: str, *, day: int, dx: str | None = None,
           cbg: str | None = None, procedure: str | None = "auto", stay: int | None = None,
           municipality: str | None = None, admission: str | None = None) -> dict[str, Any]:
    rng = tables["rng"]
    dx = dx or rng.choices(tables["diagnoses"], tables["weights"])[0]
    cbg = cbg or tables["cbg_for"][dx]
    if procedure == "auto":
        procedure = rng.choice(tables["procedures"][cbg]) if rng.random() > 0.2 else None
    municipality = municipality or rng.choice(tables["municipalities"])
    stay = rng.randint(0, 3) if stay is None else stay
    admitted = WINDOW_START + timedelta(days=day)
    return {
        "case_id": f"case_{case}", "participant_token": f"participant_{participant}",
        "service_date": admitted.isoformat(), "discharge_date": (admitted + timedelta(days=stay)).isoformat(),
        "province_code": "P1" if municipality in tables["municipalities"][:3] else "P2",
        "municipality_code": municipality, "facility_ownership": rng.choice(["1", "2"]),
        "facility_type": "2", "facility_class": rng.choice(["A", "B", "C"]),
        "admission_diagnosis": admission or (dx if rng.random() < 0.85 else rng.choice(tables["diagnoses"])),
        "primary_diagnosis": dx, "claim_group": cbg, "procedure_code": procedure, "billed_amount": None,
    }


def _common_service(tables: Mapping[str, Any]) -> tuple[str, str, str]:
    """A frequent, internally consistent diagnosis/INA-CBG/procedure combination."""
    rng = tables["rng"]
    dx = rng.choice(tables["diagnoses"][:5])
    cbg = tables["cbg_for"][dx]
    return dx, cbg, rng.choice(tables["procedures"][cbg])


def generate_benchmark(seed: int = 7, normal_count: int = 600, planted: int = 12) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return (records, truth).

    ``truth`` has ``labels`` (case_id -> scenario), ``expected`` (case_id -> expected
    state per method) and ``pairs`` (every planted pair with its own label). None of
    it is ever part of a record.
    """
    rng = random.Random(seed)
    tables = _code_tables(rng)
    records: list[dict[str, Any]] = []
    labels: dict[str, str] = {}
    pairs: list[dict[str, Any]] = []
    counter = iter(range(10**9))

    def new_ids(kind: str) -> tuple[str, str]:
        index = next(counter)
        return _opaque(seed, f"case-{kind}", index), _opaque(seed, f"person-{kind}", index)

    def add(row: dict[str, Any], scenario: str) -> dict[str, Any]:
        records.append(row)
        labels[row["case_id"]] = scenario
        return row

    def twin(base: dict[str, Any], scenario: str, *, new_participant: bool, **changes: Any) -> None:
        case, person = new_ids(scenario)
        row = {**base, "case_id": f"case_{case}", **changes}
        if new_participant:
            row["participant_token"] = f"participant_{person}"
        add(row, scenario)
        pairs.append({"pair_id": f"pair_{len(pairs):04d}", "kind": scenario,
                      "case_ids": sorted((base["case_id"], row["case_id"]))})

    def day() -> int:
        return rng.randrange(WINDOW_DAYS)

    for _ in range(normal_count):
        case, person = new_ids("normal")
        add(_claim(tables, case, person, day=day()), "normal")
    for index in range(planted):
        case, person = new_ids("rare")
        add(_claim(tables, case, person, day=day(), dx=f"R{index % 3}", cbg="GR", procedure="GRP0",
                   admission=f"R{index % 3}"), "benign_rare")

        case, person = new_ids("repeat")
        dx, cbg, proc = _common_service(tables)
        first = add(_claim(tables, case, person, day=day(), dx=dx, cbg=cbg, procedure=proc), "exact_repeat")
        twin(first, "exact_repeat", new_participant=False)

        case, person = new_ids("repeat-neg")
        dx, cbg, proc = _common_service(tables)
        base = add(_claim(tables, case, person, day=day(), dx=dx, cbg=cbg, procedure=proc), "repeat_hard_negative")
        other = next(p for p in tables["procedures"][cbg] if p != proc)
        twin(base, "repeat_hard_negative", new_participant=False, procedure_code=other)

        case, person = new_ids("incomplete")
        blank = add(_claim(tables, case, person, day=day(), procedure=None), "incomplete_repeat")
        twin(blank, "incomplete_repeat", new_participant=False)

        case, person = new_ids("clone-rare")
        rare_clone = add(_claim(tables, case, person, day=day(), procedure=f"PC{index}"), "clone_rare_template")
        twin(rare_clone, "clone_rare_template", new_participant=True, admission_diagnosis="DX-VARIANT")

        case, person = new_ids("clone-common")
        dx, cbg, proc = _common_service(tables)
        common_clone = add(_claim(tables, case, person, day=day(), dx=dx, cbg=cbg, procedure=proc, admission=dx),
                           "clone_common_template")
        twin(common_clone, "clone_common_template", new_participant=True,
             admission_diagnosis=tables["diagnoses"][(tables["diagnoses"].index(dx) + 1) % 5])

        case, person = new_ids("routine")
        dx, cbg, proc = _common_service(tables)
        routine = add(_claim(tables, case, person, day=day(), dx=dx, cbg=cbg, procedure=proc), "routine_same_day")
        case2, person2 = new_ids("routine")
        second = _claim(tables, case2, person2, day=0, dx=dx, cbg=cbg, procedure=proc,
                        municipality=routine["municipality_code"])
        second["service_date"] = routine["service_date"]
        add(second, "routine_same_day")
        pairs.append({"pair_id": f"pair_{len(pairs):04d}", "kind": "routine_same_day",
                      "case_ids": sorted((routine["case_id"], second["case_id"]))})

        case, person = new_ids("diff-service")
        dx, cbg, proc = _common_service(tables)
        service = add(_claim(tables, case, person, day=day(), dx=dx, cbg=cbg, procedure=proc, admission=dx),
                      "different_service_same_day")
        other_cbg = f"G{(int(cbg[1:]) + 1) % 10}"
        twin(service, "different_service_same_day", new_participant=True, claim_group=other_cbg,
             procedure_code=tables["procedures"][other_cbg][0])

        case, person = new_ids("three-diff")
        dx, cbg, proc = _common_service(tables)
        three = add(_claim(tables, case, person, day=day(), dx=dx, cbg=cbg, procedure=proc, admission=dx),
                    "three_differences")
        other_cbg = f"G{(int(cbg[1:]) + 2) % 10}"
        twin(three, "three_differences", new_participant=True, claim_group=other_cbg,
             procedure_code=tables["procedures"][other_cbg][1],
             facility_class=next(c for c in ("A", "B", "C") if c != three["facility_class"]))

        case, person = new_ids("ml-mismatch")
        dx = tables["diagnoses"][index % 5]
        wrong_cbg = f"G{(int(tables['cbg_for'][dx][1:]) + 5) % 10}"
        add(_claim(tables, case, person, day=day(), dx=dx, cbg=wrong_cbg,
                   procedure=tables["procedures"][wrong_cbg][0], admission=dx, stay=2), "ml_code_mismatch")

        case, person = new_ids("ml-stay")
        dx, cbg, proc = _common_service(tables)
        add(_claim(tables, case, person, day=day(), dx=dx, cbg=cbg, procedure=proc, admission=dx,
                   stay=rng.randint(20, 30)), "ml_long_stay")

        if index % 3 == 0:
            case, person = new_ids("both")
            both = add(_claim(tables, case, person, day=day(), dx=dx, cbg=wrong_cbg,
                              procedure=tables["procedures"][wrong_cbg][1], stay=30, admission=dx),
                       "both_repeat_and_ml")
            twin(both, "both_repeat_and_ml", new_participant=False)

            case, person = new_ids("next-day")
            start = rng.randrange(WINDOW_DAYS - 1)
            dx, cbg, proc = _common_service(tables)
            nd = add(_claim(tables, case, person, day=start, dx=dx, cbg=cbg, procedure=proc), "next_day_repeat")
            twin(nd, "next_day_repeat", new_participant=False,
                 service_date=(date.fromisoformat(nd["service_date"]) + timedelta(days=1)).isoformat())

            # Frequent visitor: five visits by one participant on different days.
            _case, visitor = new_ids("visitor")
            for visit_day in rng.sample(range(WINDOW_DAYS), 5):
                case, _ = new_ids("visit")
                dx, cbg, proc = _common_service(tables)
                add(_claim(tables, case, visitor, day=visit_day, dx=dx, cbg=cbg, procedure=proc), "ml_frequent_visitor")

    expected = {}
    for row in records:
        state = dict(SCENARIOS[labels[row["case_id"]]])
        state.pop("meaning")
        if state["repeat"] != "flag" and row["procedure_code"] is None:
            state["repeat"] = "unassessed"  # blank FKL30: the repeat rule cannot assess the record
        expected[row["case_id"]] = state
    return records, {"labels": labels, "expected": expected, "pairs": pairs}


def precision_recall(predicted: set[str], targets: set[str], assessed: set[str]) -> dict[str, Any]:
    """Record-level metrics over assessed records only; unassessed targets are reported separately."""
    evaluated_predicted = predicted & assessed
    tp = len(evaluated_predicted & targets)
    fp = len(evaluated_predicted - targets)
    fn = len((targets & assessed) - predicted)
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "recall_on_assessed_targets": round(tp / (tp + fn), 4) if tp + fn else None,
        "targets_unassessed": len(targets - assessed),
        "recall_including_unassessed": round(tp / len(targets), 4) if targets else None,
    }


def ranking_at_k(ranks: Mapping[str, Mapping[str, Any]], targets: set[str], k: int) -> dict[str, Any]:
    """Top-K by competition rank (records tied at the boundary are all included)."""
    top = {case_id for case_id, item in ranks.items() if item["rank"] <= k}
    hits = len(top & targets)
    return {
        "k": k, "top_k_size_with_ties": len(top), "hits": hits,
        "precision_at_k": round(hits / len(top), 4) if top else None,
        "recall_at_k": round(hits / len(targets), 4) if targets else None,
    }


def random_baseline_at_k(population: int, targets: int, k: int) -> dict[str, Any]:
    """Exact expectation for a uniformly random ranking (hypergeometric mean)."""
    return {"k": k, "expected_precision_at_k": round(targets / population, 4),
            "expected_recall_at_k": round(min(k, population) / population, 4)}


def rule_flag_baseline_at_k(flagged: set[str], targets: set[str], population: int, k: int) -> dict[str, Any]:
    """Expected Precision/Recall@K when rule-flagged records are ranked first, in random order."""
    flagged_hits = len(flagged & targets)
    if k <= len(flagged):
        hits = k * flagged_hits / len(flagged) if flagged else 0.0
    else:
        rest = population - len(flagged)
        hits = flagged_hits + (k - len(flagged)) * (len(targets) - flagged_hits) / rest if rest else flagged_hits
    return {"k": k, "expected_precision_at_k": round(hits / k, 4),
            "expected_recall_at_k": round(hits / len(targets), 4) if targets else None}


def _ids(truth: Mapping[str, Any], method: str, state: str) -> set[str]:
    return {case_id for case_id, expected in truth["expected"].items() if expected[method] == state}


def _scenario_ids(truth: Mapping[str, Any], scenario: str) -> set[str]:
    return {case_id for case_id, name in truth["labels"].items() if name == scenario}


def _pairs(truth: Mapping[str, Any], kinds: Sequence[str]) -> dict[str, set[tuple[str, ...]]]:
    return {kind: {tuple(pair["case_ids"]) for pair in truth["pairs"] if pair["kind"] == kind} for kind in kinds}


def evaluate_benchmark(records: Sequence[Mapping[str, Any]], truth: Mapping[str, Any],
                       permutation_seeds: Sequence[int] = (1,)) -> dict[str, Any]:
    """Evaluate the repeat rule, near-duplicate rule and ML ranking independently."""
    if any(set(row) & {"scenario", "label", "is_anomaly", "ground_truth", "expected"} for row in records):
        raise ValueError("Labels must not be part of the evaluated records.")
    labels = truth["labels"]
    population = len(records)
    all_ids = {row["case_id"] for row in records}

    # Same-participant repeat rule (FKRTL profile).
    repeat = detect_repeat_billing_candidates(records, AMOUNT_WITHHELD_SIGNATURE_FIELDS)
    repeat_groups = [frozenset(group["case_ids"]) for group in repeat["candidate_groups"]]
    repeat_flagged = set().union(*repeat_groups) if repeat_groups else set()
    repeat_unassessed = {item["case_id"] for item in repeat["ineligible_cases"]}
    repeat_pairs = _pairs(truth, REPEAT_PAIR_KINDS)

    def pair_matched(pair: tuple[str, ...]) -> bool:
        return any(set(pair) <= group for group in repeat_groups)

    # Cross-participant near-duplicate rule (existing default settings).
    near = detect_near_duplicate_claims(records, NearDuplicateConfig())
    candidates = {tuple(sorted(candidate["case_ids"])) for candidate in near["candidates"]}
    near_flagged = {case_id for pair in candidates for case_id in pair}
    near_unassessed = set(near["unassessed_case_ids"]) | {item["case_id"] for item in near["ineligible_cases"]}
    targets = _pairs(truth, NEAR_TARGET_KINDS)
    negatives = _pairs(truth, NEAR_NEGATIVE_KINDS)
    all_targets = set().union(*targets.values())
    labelled = all_targets | set().union(*negatives.values())
    background = _ids(truth, "near", "background")

    # ML ranking (unchanged model) and baselines.
    summary, ranks = build_ml_anomaly_ranking(records)
    ml_targets = _ids(truth, "ml", "target")
    benign_rare = _ids(truth, "ml", "benign_rare")
    rule_flagged = repeat_flagged | near_flagged
    stable = []
    for perm_seed in permutation_seeds:
        shuffled = list(records)
        random.Random(perm_seed).shuffle(shuffled)
        stable.append(build_ml_anomaly_ranking(shuffled)[1] == ranks)
    per_k = []
    for k in K_VALUES:
        top = {case_id for case_id, item in ranks.items() if item["rank"] <= k}
        per_k.append({
            **ranking_at_k(ranks, ml_targets, k),
            "recall_by_target_kind": {
                kind: round(len(top & _scenario_ids(truth, kind)) / len(_scenario_ids(truth, kind)), 4)
                for kind in ML_TARGET_KINDS if _scenario_ids(truth, kind)
            },
            "benign_rare_in_top_k": len(top & benign_rare),
            "rule_flagged_in_top_k": len(top & rule_flagged),
            "random_baseline": random_baseline_at_k(population, len(ml_targets), len(top)),
            "rule_flag_baseline": rule_flag_baseline_at_k(rule_flagged, ml_targets, population, len(top)),
        })

    return {
        "benchmark_version": BENCHMARK_VERSION,
        "label": "SYNTHETIC BENCHMARK - not validated real-world fraud detection",
        "record_count": population,
        "scenario_counts": dict(sorted(Counter(labels.values()).items())),
        "repeat_rule": {
            **precision_recall(repeat_flagged, _ids(truth, "repeat", "flag"), all_ids - repeat_unassessed),
            "unassessed_records": len(repeat_unassessed),
            "expected_unassessed_records": len(_ids(truth, "repeat", "unassessed")),
            "unassessed_matches_expected": repeat_unassessed == _ids(truth, "repeat", "unassessed"),
            "pairs_matched_by_kind": {kind: sum(map(pair_matched, found)) for kind, found in repeat_pairs.items()},
            "pairs_by_kind": {kind: len(found) for kind, found in repeat_pairs.items()},
        },
        "near_duplicate_rule": {
            # Unit: candidate pair. A true positive is a returned pair that is exactly a
            # labelled target pair; precision divides by every returned candidate pair.
            "candidate_pairs": len(candidates),
            "candidates_per_1000_records": round(len(candidates) / population * 1000, 2),
            "target_pairs": len(all_targets),
            "target_pairs_found": len(candidates & all_targets),
            "recall_by_target_kind": {kind: round(len(candidates & found) / len(found), 4) for kind, found in targets.items()},
            "recall": round(len(candidates & all_targets) / len(all_targets), 4) if all_targets else None,
            "precision": round(len(candidates & all_targets) / len(candidates), 4) if candidates else None,
            "hard_negative_pairs_matched_by_kind": {kind: len(candidates & found) for kind, found in negatives.items()},
            "hard_negative_pairs_by_kind": {kind: len(found) for kind, found in negatives.items()},
            "unlabelled_similarity_pairs": len(candidates - labelled),
            "unlabelled_pairs_within_background": sum(1 for pair in candidates - labelled if set(pair) <= background),
            "assessed_records": population - len(near_unassessed),
            "unassessed_records": len(near_unassessed),
            "search_truncated": near["search_truncated"],
            "pair_comparisons": near["pair_comparisons"],
        },
        "ml_ranking": {
            "status": summary["status"],
            "records_scored": summary["records_scored"],
            "targets": len(ml_targets),
            "benign_rare_records": len(benign_rare),
            "rule_flagged_records": len(rule_flagged),
            "ml_targets_rule_flagged": len(ml_targets & rule_flagged),
            "at_k": per_k,
            # Where each group sits in the ranking (1 = most unusual); shows what the model rewards.
            "median_rank_by_kind": {
                kind: median(ranks[case_id]["rank"] for case_id in _scenario_ids(truth, kind))
                for kind in (*ML_TARGET_KINDS, "benign_rare", "clone_rare_template", "normal")
                if _scenario_ids(truth, kind)
            },
            "max_tie_count": max((item["tie_count"] for item in ranks.values()), default=0),
            "stable_under_row_permutations": all(stable),
        },
    }


def _stats(values: Sequence[float | None]) -> dict[str, float | None]:
    present = [value for value in values if value is not None]
    if not present:
        return {"mean": None, "min": None, "max": None}
    return {"mean": round(mean(present), 4), "min": round(min(present), 4), "max": round(max(present), 4)}


def run_seeds(seeds: Sequence[int] = DEFAULT_SEEDS) -> dict[str, Any]:
    """Run the benchmark on independent generation seeds and summarise across them."""
    per_seed = {}
    for seed in seeds:
        records, truth = generate_benchmark(seed=seed)
        per_seed[seed] = evaluate_benchmark(records, truth)
    reports = list(per_seed.values())
    near = [report["near_duplicate_rule"] for report in reports]
    ml = [report["ml_ranking"] for report in reports]
    aggregate: dict[str, Any] = {
        "seeds": list(seeds),
        "near_duplicate": {
            "precision": _stats([item["precision"] for item in near]),
            "recall": _stats([item["recall"] for item in near]),
            **{f"recall_{kind}": _stats([item["recall_by_target_kind"][kind] for item in near]) for kind in NEAR_TARGET_KINDS},
            "candidates_per_1000_records": _stats([item["candidates_per_1000_records"] for item in near]),
            "unassessed_records": _stats([item["unassessed_records"] for item in near]),
            "truncated_runs": sum(item["search_truncated"] for item in near),
            **{f"hard_negative_matched_{kind}": _stats([item["hard_negative_pairs_matched_by_kind"][kind] for item in near])
               for kind in NEAR_NEGATIVE_KINDS},
        },
        "repeat_rule": {
            "precision": _stats([report["repeat_rule"]["precision"] for report in reports]),
            "recall": _stats([report["repeat_rule"]["recall_on_assessed_targets"] for report in reports]),
            "hard_negative_pairs_matched": _stats([report["repeat_rule"]["pairs_matched_by_kind"]["repeat_hard_negative"] for report in reports]),
            "unassessed_matches_expected_all_seeds": all(report["repeat_rule"]["unassessed_matches_expected"] for report in reports),
        },
        "ml_ranking": {
            "stable_under_row_permutations_all_seeds": all(item["stable_under_row_permutations"] for item in ml),
            "median_rank_by_kind": {
                kind: _stats([item["median_rank_by_kind"].get(kind) for item in ml])
                for kind in (*ML_TARGET_KINDS, "benign_rare", "clone_rare_template", "normal")
            },
        },
    }
    for index, k in enumerate(K_VALUES):
        rows = [item["at_k"][index] for item in ml]
        aggregate["ml_ranking"][f"at_{k}"] = {
            "precision": _stats([row["precision_at_k"] for row in rows]),
            "recall": _stats([row["recall_at_k"] for row in rows]),
            "random_precision": _stats([row["random_baseline"]["expected_precision_at_k"] for row in rows]),
            "rule_flag_precision": _stats([row["rule_flag_baseline"]["expected_precision_at_k"] for row in rows]),
            "benign_rare_in_top_k": _stats([row["benign_rare_in_top_k"] for row in rows]),
            "rule_flagged_in_top_k": _stats([row["rule_flagged_in_top_k"] for row in rows]),
            **{f"recall_{kind}": _stats([row["recall_by_target_kind"].get(kind) for row in rows]) for kind in ML_TARGET_KINDS},
        }
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "label": "SYNTHETIC BENCHMARK - not validated real-world fraud detection",
        "aggregate": aggregate,
        "per_seed": per_seed,
        "limitations": [
            "Scenario labels define this benchmark's target contracts only; they are not fraud labels.",
            "The common-template target is indistinguishable from routine same-day claims on the available fields by construction.",
            "Model settings and thresholds were not tuned on these seeds; no combined or hybrid score is computed.",
            "Results do not transfer to real FKRTL data, which has no ground truth.",
        ],
    }



# --- Phase 5: duration screen benchmark (separate dataset; Phase 4 data unchanged) ---

# Expected duration-screen state per scenario. "target" = planted extreme upper tail;
# "legitimate_long" = clinically justified long stay that is statistically identical;
# the duration screen cannot and should not separate the two (that is a fraud question).
LOS_SCENARIOS: dict[str, dict[str, str]] = {
    "los_ordinary": {"los": "ordinary", "meaning": "Short stay (0-4 days) in a short-stay peer group."},
    "los_ordinary_long_group": {"los": "ordinary", "meaning": "7-12 day stay in a peer group where that is typical."},
    "los_rare_code_ordinary": {"los": "ordinary", "meaning": "Rare diagnosis code with an ordinary 1-3 day stay."},
    "los_natural_tail": {"los": "natural_tail", "meaning": "Legitimate moderately long stay (5-9 days) in a short-stay group."},
    "los_upper_tail_target": {"los": "target", "meaning": "Planted extreme span (18-35 days) in a short-stay group."},
    "los_legitimate_long": {"los": "legitimate_long", "meaning": "Clinically justified 18-35 day stay; statistically identical to a target."},
    "los_invalid_dates": {"los": "unassessed", "meaning": "Missing, invalid or reversed admission/discharge dates."},
    "los_small_peer_group": {"los": "unassessed", "meaning": "Peer group below the minimum support."},
}
LOS_GROUPS = (("G0", "3", 700), ("G1", "3", 500), ("G2", "2", 400))  # short-stay peer groups


def generate_los_benchmark(seed: int = 7, planted: int = 8) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return (records, truth) for the duration screen; truth labels never enter the records."""
    rng = random.Random(seed)
    tables = _code_tables(rng)
    records: list[dict[str, Any]] = []
    labels: dict[str, str] = {}
    counter = iter(range(10**9))

    def add(scenario: str, *, cbg: str, care: str, stay: int, dx: str | None = None,
            participant: str | None = None) -> dict[str, Any]:
        index = next(counter)
        dx = dx or rng.choice([d for d in tables["diagnoses"] if tables["cbg_for"][d] == cbg] or tables["diagnoses"][:1])
        row = _claim(tables, _opaque(seed, "los-case", index), participant or _opaque(seed, "los-person", index),
                     day=rng.randrange(WINDOW_DAYS), dx=dx, cbg=cbg, stay=stay, admission=dx,
                     procedure=rng.choice(tables["procedures"].get(cbg, [f"{cbg}P0"])))
        row["care_class"] = care
        records.append(row)
        labels[row["case_id"]] = scenario
        return row

    for cbg, care, size in LOS_GROUPS:
        for _ in range(size):
            if rng.random() < 0.015:
                add("los_natural_tail", cbg=cbg, care=care, stay=rng.randint(5, 9))
            else:
                add("los_ordinary", cbg=cbg, care=care, stay=rng.choice([0, 0, 1, 1, 2, 2, 3, 4]))
    for _ in range(300):
        add("los_ordinary_long_group", cbg="G9", care="1", stay=rng.randint(7, 12))
    for index in range(planted):
        cbg, care, _size = LOS_GROUPS[index % len(LOS_GROUPS)]
        target = add("los_upper_tail_target", cbg=cbg, care=care, stay=rng.randint(18, 35))
        if index == 0:  # exact copies of one target must count once in the reference
            for _ in range(2):
                copy_index = next(counter)
                copy = {**target, "case_id": f"case_{_opaque(seed, 'los-case', copy_index)}"}
                records.append(copy)
                labels[copy["case_id"]] = "los_upper_tail_target"
        add("los_legitimate_long", cbg=cbg, care=care, stay=rng.randint(18, 35))
    for index in range(12):
        add("los_rare_code_ordinary", cbg="G0", care="3", stay=rng.randint(1, 3), dx=f"R{index % 3}")
    for kind in ("missing", "invalid", "reversed") * 4:
        row = add("los_invalid_dates", cbg="G0", care="3", stay=2)
        if kind == "missing":
            row["discharge_date"] = None
        elif kind == "invalid":
            row["discharge_date"] = "2024-02-31"
        else:
            row["discharge_date"] = (date.fromisoformat(row["service_date"]) - timedelta(days=3)).isoformat()
    for index in range(30):
        add("los_small_peer_group", cbg="GS", care="1", stay=30 if index == 0 else rng.randint(0, 4))
    expected = {case_id: LOS_SCENARIOS[scenario]["los"] for case_id, scenario in labels.items()}
    return records, {"labels": labels, "expected": expected}


def evaluate_los_benchmark(records: Sequence[Mapping[str, Any]], truth: Mapping[str, Any],
                           permutation_seed: int = 1) -> dict[str, Any]:
    """Duration screen vs the unchanged ML ranking on the same records."""
    from app.analytics.length_of_stay import detect_length_of_stay_outliers

    if any(set(row) & {"scenario", "label", "is_anomaly", "ground_truth", "expected"} for row in records):
        raise ValueError("Labels must not be part of the evaluated records.")
    expected = truth["expected"]

    def with_state(state: str) -> set[str]:
        return {case_id for case_id, value in expected.items() if value == state}

    def scenario(name: str) -> set[str]:
        return {case_id for case_id, value in truth["labels"].items() if value == name}

    result = detect_length_of_stay_outliers(records)
    flagged = {item["case_id"] for item in result["candidates"]}
    shuffled = list(records)
    random.Random(permutation_seed).shuffle(shuffled)
    permuted = detect_length_of_stay_outliers(shuffled)
    targets, legit, tail, ordinary = (with_state(s) for s in ("target", "legitimate_long", "natural_tail", "ordinary"))
    expected_unassessed = with_state("unassessed")
    flagged_unassessed = flagged & expected_unassessed

    summary, ranks = build_ml_anomaly_ranking(records)
    comparison = []
    for k in sorted({max(1, len(flagged)), 50}):
        top = {case_id for case_id, item in ranks.items() if item["rank"] <= k}
        comparison.append({
            "k": k, "top_k_size_with_ties": len(top),
            "ml_recall_of_targets": round(len(top & targets) / len(targets), 4) if targets else None,
            "ml_top_k_overlap_with_duration_candidates": len(top & flagged),
            "rare_code_ordinary_in_ml_top_k": len(top & scenario("los_rare_code_ordinary")),
            "legitimate_long_in_ml_top_k": len(top & legit),
        })
    return {
        "benchmark_version": f"{BENCHMARK_VERSION}+los-v1",
        "label": "SYNTHETIC BENCHMARK - statistical duration signal, not fraud detection",
        "record_count": len(records),
        "duration_screen": {
            "version": result["version"],
            "assessed": result["assessed_count"],
            "unassessed": result["unassessed_count"],
            "unassessed_reason_counts": result["unassessed_reason_counts"],
            "unassessed_matches_expected": result["unassessed_count"] == len(expected_unassessed) and not flagged_unassessed,
            "candidates": len(flagged),
            "candidates_per_1000_assessed": result["candidates_per_1000_assessed"],
            "target_recall": round(len(flagged & targets) / len(targets), 4) if targets else None,
            "ordinary_false_alerts": len(flagged & ordinary),
            "ordinary_records": len(ordinary),
            "natural_tail_flag_rate": round(len(flagged & tail) / len(tail), 4) if tail else None,
            # Expected to be high: statistically identical to targets. Not a fraud false positive.
            "legitimate_long_flag_rate": round(len(flagged & legit) / len(legit), 4) if legit else None,
            "stable_under_row_permutation": {item["case_id"] for item in permuted["candidates"]} == flagged,
        },
        "ml_comparison": {
            "status": summary["status"],
            "target_median_ml_rank": median(ranks[case_id]["rank"] for case_id in targets) if targets else None,
            "legitimate_long_median_ml_rank": median(ranks[case_id]["rank"] for case_id in legit) if legit else None,
            "rare_code_ordinary_median_ml_rank": median(ranks[case_id]["rank"] for case_id in scenario("los_rare_code_ordinary")),
            "at_k": comparison,
        },
    }


def run_los_seeds(seeds: Sequence[int] = DEFAULT_SEEDS) -> dict[str, Any]:
    per_seed = {seed: evaluate_los_benchmark(*generate_los_benchmark(seed=seed)) for seed in seeds}
    screens = [report["duration_screen"] for report in per_seed.values()]
    ml = [report["ml_comparison"] for report in per_seed.values()]
    return {
        "benchmark_version": f"{BENCHMARK_VERSION}+los-v1",
        "label": "SYNTHETIC BENCHMARK - statistical duration signal, not fraud detection",
        "aggregate": {
            "seeds": list(seeds),
            **{key: _stats([screen[key] for screen in screens]) for key in (
                "target_recall", "candidates_per_1000_assessed", "assessed", "unassessed", "candidates",
                "ordinary_false_alerts", "natural_tail_flag_rate", "legitimate_long_flag_rate")},
            "unassessed_matches_expected_all_seeds": all(screen["unassessed_matches_expected"] for screen in screens),
            "stable_under_row_permutation_all_seeds": all(screen["stable_under_row_permutation"] for screen in screens),
            "ml_target_median_rank": _stats([item["target_median_ml_rank"] for item in ml]),
            "ml_rare_code_ordinary_median_rank": _stats([item["rare_code_ordinary_median_ml_rank"] for item in ml]),
            "ml_recall_of_targets_at_k_equal_to_duration_candidates": _stats([item["at_k"][0]["ml_recall_of_targets"] for item in ml]),
            "ml_recall_of_targets_at_50": _stats([item["at_k"][-1]["ml_recall_of_targets"] for item in ml]),
            "rare_code_ordinary_in_ml_top_50": _stats([item["at_k"][-1]["rare_code_ordinary_in_ml_top_k"] for item in ml]),
        },
        "per_seed": per_seed,
        "limitations": [
            "Targets and legitimate long stays are statistically identical by construction; the duration screen answers a statistical question only.",
            "The 99th-percentile threshold and minimum support were declared before running this benchmark and not tuned on it.",
            "Results do not transfer to real FKRTL data, which has no ground truth.",
        ],
    }


def _parse_seeds(text: str) -> list[int]:
    if "-" in text:
        start, end = (int(part) for part in text.split("-", 1))
        return list(range(start, end + 1))
    return [int(part) for part in text.split(",")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", default="1-10", help="e.g. 1-10 or 3,5,8")
    parser.add_argument("--aggregate-only", action="store_true")
    parser.add_argument("--duration", action="store_true", help="run the Phase 5 duration-screen benchmark")
    args = parser.parse_args()
    report = (run_los_seeds if args.duration else run_seeds)(_parse_seeds(args.seeds))
    if args.aggregate_only:
        report.pop("per_seed")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
