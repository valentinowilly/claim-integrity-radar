"""Labelled synthetic benchmark for similar-claim screening (search completeness, not fraud accuracy).

Planted pairs are copies of a background claim given to another participant with 0-2 changed
attributes or one blank attribute, placed at random positions; hard negatives change three
attributes or the admission date. Metrics are reported against the planted labels and against a
brute-force ground truth of the screen's own rule. Prints aggregates only; no real data is used.

Usage (from backend/): python -m scripts.similar_claim_engine_benchmark --records 6000 --seeds 1-3
"""

from __future__ import annotations

import argparse
from itertools import combinations
import json
import random
import time

from app.analytics.near_duplicate_claims import NEAR_FIELDS, NearDuplicateConfig, _field_value, detect_near_duplicate_claims

MUTABLE = ["province_code", "municipality_code", "facility_ownership", "facility_type", "facility_class",
           "admission_diagnosis", "primary_diagnosis", "claim_group", "procedure_code"]


def generate(size: int, seed: int) -> tuple[list[dict], set[tuple[str, str]], set[tuple[str, str]]]:
    rng = random.Random(seed)
    rows = []
    for index in range(size):
        municipality = rng.randrange(40)
        rows.append({
            "case_id": f"syn-bg{index}", "participant_token": f"syn-participant-{index}",
            "service_date": f"2024-03-{1 + rng.randrange(7):02d}", "province_code": str(municipality // 8),
            "municipality_code": str(1000 + municipality), "facility_ownership": str(rng.randrange(3)),
            "facility_type": str(rng.randrange(4)), "facility_class": str(rng.randrange(3)),
            "admission_diagnosis": f"A{int(rng.paretovariate(1.2)) % 120}", "primary_diagnosis": f"B{int(rng.paretovariate(1.2)) % 150}",
            "claim_group": f"G{int(rng.paretovariate(1.3)) % 80}",
            "procedure_code": None if rng.random() < 0.42 else f"P{int(rng.paretovariate(1.2)) % 90}", "billed_amount": None,
        })
    planted, negatives = set(), set()
    background = list(rows)  # sources are background claims only, never another planted copy
    for number in range(size // 50):
        source = background[rng.randrange(size)]
        copy = {**source, "case_id": f"syn-copy{number}", "participant_token": f"syn-participant-copy{number}"}
        kind = rng.choice(["identical", "one", "two", "blank", "three", "date"])
        changes = {"identical": 0, "one": 1, "two": 2, "blank": 0, "three": 3, "date": 0}[kind]
        present = [field for field in MUTABLE if source[field] is not None]
        for field in rng.sample(present, changes):
            copy[field] = f"X{number}{field}"
        if kind == "blank":
            copy[rng.choice(present)] = None
        if kind == "date":
            copy["service_date"] = "2024-03-20"
        rows.insert(rng.randrange(len(rows) + 1), copy)
        (negatives if kind in ("three", "date") else planted).add(tuple(sorted((source["case_id"], copy["case_id"]))))
    return rows, planted, negatives


def rule_truth(rows: list[dict], config: NearDuplicateConfig) -> set[tuple[str, str]]:
    """Brute force within each admission date (the screen's scope)."""
    by_date: dict = {}
    for row in rows:
        by_date.setdefault(row["service_date"], []).append(row)
    truth = set()
    for group in by_date.values():
        values = [(row, tuple(_field_value(field, row.get(field)) for field in NEAR_FIELDS)) for row in group]
        for (left, a), (right, b) in combinations(values, 2):
            if left["participant_token"] == right["participant_token"]:
                continue
            compared = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
            if len(compared) >= config.min_compared_attributes and \
                    sum(x == y for x, y in compared) / len(compared) >= config.min_similarity:
                truth.add(tuple(sorted((left["case_id"], right["case_id"]))))
    return truth


def evaluate(rows, planted, negatives, budget: int) -> dict:
    config = NearDuplicateConfig(max_pair_comparisons=budget, max_candidates=10**7)
    started = time.perf_counter()
    result = detect_near_duplicate_claims(rows, config)
    seconds = time.perf_counter() - started
    # Search completeness is measured on every qualifying pair, whichever evidence class it received.
    qualifying = result["candidates"] + result["common_attribute_candidates"]
    found = {tuple(sorted(candidate["case_ids"])) for candidate in qualifying}
    truth = rule_truth(rows, config)
    by_id = {row["case_id"]: row for row in rows}

    def semantic(candidates) -> list:
        # Feature-level pair signatures: records with identical features are interchangeable.
        return sorted(tuple(sorted(tuple(str(by_id[case_id].get(field)) for field in NEAR_FIELDS) for case_id in item["case_ids"]))
                      for item in candidates)
    unassessed = set(result["unassessed_case_ids"])
    reachable = {pair for pair in planted if not set(pair) & unassessed}
    shuffled = rows[:]
    random.Random(99).shuffle(shuffled)
    reordered = detect_near_duplicate_claims(shuffled, config)
    reordered_qualifying = reordered["candidates"] + reordered["common_attribute_candidates"]
    return {
        "budget": budget, "records": len(rows), "seconds": round(seconds, 2),
        "planted_pairs": len(planted), "planted_found": len(found & planted),
        "planted_recall": round(len(found & planted) / len(planted), 3) if planted else None,
        "planted_recall_on_assessed": round(len(found & reachable) / len(reachable), 3) if reachable else None,
        "planted_meeting_rule": len(planted & truth),
        "planted_meeting_rule_recall": round(len(found & planted & truth) / len(planted & truth), 3) if planted & truth else None,
        "hard_negatives_found": len(found & negatives),
        "candidate_pairs": len(found),
        "precision_vs_planted_labels": round(len(found & planted) / len(found), 3) if found else None,
        "rule_truth_pairs": len(truth), "rule_recall": round(len(found & truth) / len(truth), 3) if truth else None,
        "found_outside_rule": len(found - truth),
        "records_assessed_share": round(1 - len(unassessed) / len(rows), 3),
        "search_truncated": result["search_truncated"],
        "identical_ids_under_shuffle": {tuple(sorted(c["case_ids"])) for c in reordered_qualifying} == found,
        "semantically_stable_under_shuffle": semantic(reordered_qualifying) == semantic(qualifying)
        and reordered["unassessed_case_ids"] == result["unassessed_case_ids"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=6000)
    parser.add_argument("--seeds", default="1-3")
    parser.add_argument("--budgets", default="5000,50000,10000000")
    args = parser.parse_args()
    first, last = (int(part) for part in args.seeds.split("-"))
    for seed in range(first, last + 1):
        rows, planted, negatives = generate(args.records, seed)
        for budget in (int(value) for value in args.budgets.split(",")):
            print(json.dumps({"seed": seed, **evaluate(rows, planted, negatives, budget)}))


if __name__ == "__main__":
    main()
