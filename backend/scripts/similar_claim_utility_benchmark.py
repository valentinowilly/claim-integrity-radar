"""Utility benchmark v2 for similar-claim screening (synthetic, labelled; not a fraud accuracy measure).

Compared with v1 (``similar_claim_engine_benchmark``) the generator adds what makes the task hard:
* correlated codes (INA-CBG mostly follows the primary diagnosis);
* labelled routine clusters: several different patients with the same common codes in the same
  district on the same day (hard negatives the screen should not surface);
* planted copies whose source is drawn half from routine clusters (realistically hard) and half
  from other background claims; plus three-change and other-date hard negatives.

Every variant is scored on the same complete-search candidates, so differences come from the
selection rule only. Seeds 1-5 are the development set used to choose a variant; seeds 101-105 are
the holdout. K for precision@K is fixed at 50 before running. Prints aggregates only.

Usage (from backend/): python -m scripts.similar_claim_utility_benchmark --seeds 1-5
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import random
import statistics
import time
import tracemalloc

from app.analytics.near_duplicate_claims import NEAR_FIELDS, NearDuplicateConfig, _field_value, detect_near_duplicate_claims

K = 50
MUTABLE = ["province_code", "municipality_code", "facility_ownership", "facility_type", "facility_class",
           "admission_diagnosis", "primary_diagnosis", "claim_group", "procedure_code"]


def _claim(rng: random.Random, case_id: str, participant: str, day: int, municipality: int, primary: int) -> dict:
    return {
        "case_id": case_id, "participant_token": participant, "service_date": f"2024-03-{day:02d}",
        "province_code": str(municipality // 8), "municipality_code": str(1000 + municipality),
        "facility_ownership": str(rng.randrange(3)), "facility_type": str(rng.randrange(4)),
        "facility_class": str(rng.randrange(3)),
        "admission_diagnosis": f"A{primary if rng.random() < 0.6 else int(rng.paretovariate(1.2)) % 150}",
        "primary_diagnosis": f"B{primary}",
        "claim_group": f"G{primary % 60 if rng.random() < 0.8 else int(rng.paretovariate(1.3)) % 80}",
        "procedure_code": None if rng.random() < 0.42 else f"P{int(rng.paretovariate(1.2)) % 90}",
        "billed_amount": None,
    }


def generate(size: int, seed: int) -> dict:
    rng = random.Random(seed)
    rows: list[dict] = []
    for index in range(size):
        rows.append(_claim(rng, f"syn-bg{index}", f"syn-participant-bg{index}", 1 + rng.randrange(7),
                           rng.randrange(40), int(rng.paretovariate(1.2)) % 150))
    routine_pairs: set = set()
    clusters = []
    for number in range(size // 60):
        template = _claim(rng, "", "", 1 + rng.randrange(7), rng.randrange(40), int(rng.paretovariate(2.5)) % 8)
        members = []
        for member in range(rng.randrange(3, 9)):
            row = {**template, "case_id": f"syn-rt{number}-{member}", "participant_token": f"syn-participant-rt{number}-{member}"}
            # Routine variation: categories and procedure vary a little between patients.
            for field in rng.sample(["facility_ownership", "facility_type", "facility_class", "procedure_code"], rng.randrange(0, 2)):
                row[field] = None if field == "procedure_code" and rng.random() < 0.5 else f"{row[field]}v{member}"
            members.append(row)
        clusters.append(members)
        rows += members
        routine_pairs |= {tuple(sorted((a["case_id"], b["case_id"]))) for i, a in enumerate(members) for b in members[i + 1:]}
    background = list(rows)
    routine_members = [row for members in clusters for row in members]
    planted, negatives, planted_from_routine = set(), set(), set()
    for number in range(size // 50):
        from_routine = rng.random() < 0.5
        source = rng.choice(routine_members if from_routine else background[:size])
        copy = {**source, "case_id": f"syn-copy{number}", "participant_token": f"syn-participant-copy{number}"}
        kind = rng.choice(["identical", "one", "two", "blank", "three", "date"])
        present = [field for field in MUTABLE if source[field] is not None]
        for field in rng.sample(present, {"one": 1, "two": 2, "three": 3}.get(kind, 0)):
            copy[field] = f"X{number}{field}"
        if kind == "blank":
            copy[rng.choice(present)] = None
        if kind == "date":
            copy["service_date"] = "2024-03-20"
        rows.insert(rng.randrange(len(rows) + 1), copy)
        pair = tuple(sorted((source["case_id"], copy["case_id"])))
        if kind in ("three", "date"):
            negatives.add(pair)
        else:
            planted.add(pair)
            if from_routine:
                planted_from_routine.add(pair)
    return {"rows": rows, "planted": planted, "planted_from_routine": planted_from_routine,
            "negatives": negatives, "routine": routine_pairs}


def combination_support(rows: list[dict], candidates: list[dict]) -> list[int]:
    """Records on the candidate's admission date that share every matched attribute value (>= 2)."""
    by_id = {row["case_id"]: row for row in rows}
    normalized = {row["case_id"]: {field: _field_value(field, row.get(field)) for field in NEAR_FIELDS} for row in rows}
    indexes: dict = {}
    supports = []
    for candidate in candidates:
        fields = tuple(sorted(set(candidate["matched_attributes"]) | {"service_date"}))
        if fields not in indexes:
            indexes[fields] = Counter(tuple(values[field] for field in fields) for values in normalized.values()
                                      if all(values[field] is not None for field in fields))
        left = normalized[by_id[candidate["case_ids"][0]]["case_id"]]
        supports.append(indexes[fields][tuple(left[field] for field in fields)])
    return supports


def chance_expectation(rows: list[dict], candidates: list[dict]) -> list[float]:
    """Expected number of same-day pairs agreeing on the matched values if attributes were independent."""
    by_date: dict = {}
    for row in rows:
        by_date.setdefault(_field_value("service_date", row.get("service_date")), []).append(row)
    frequency = {date: {field: Counter(_field_value(field, row.get(field)) for row in group) for field in NEAR_FIELDS}
                 for date, group in by_date.items()}
    by_id = {row["case_id"]: row for row in rows}
    expectations = []
    for candidate in candidates:
        left = by_id[candidate["case_ids"][0]]
        date = _field_value("service_date", left.get("service_date"))
        size = len(by_date[date])
        probability = 1.0
        for field in candidate["matched_attributes"]:
            probability *= (frequency[date][field][_field_value(field, left.get(field))] / size) ** 2
        expectations.append(size * (size - 1) / 2 * probability)
    return expectations


def summarize(found: set, data: dict, label: str, ranked: list | None = None) -> dict:
    planted, routine = data["planted"], data["routine"]
    flagged = Counter(case_id for pair in found for case_id in pair)
    per_record = list(flagged.values()) or [0]
    result = {
        "variant": label, "candidate_pairs": len(found),
        "precision_vs_planted": round(len(found & planted) / len(found), 3) if found else None,
        "recall_planted": round(len(found & planted) / len(planted), 3),
        "recall_planted_from_routine": round(len(found & data["planted_from_routine"]) / len(data["planted_from_routine"]), 3)
        if data["planted_from_routine"] else None,
        "recall_planted_other": round(len(found & (planted - data["planted_from_routine"]))
                                      / len(planted - data["planted_from_routine"]), 3),
        "routine_pairs_surfaced_share": round(len(found & routine) / len(routine), 3),
        "hard_negatives_found": len(found & data["negatives"]),
        "flagged_records": len(flagged),
        "pairs_per_flagged_record": {"mean": round(statistics.mean(per_record), 2),
                                     "p95": sorted(per_record)[int(0.95 * (len(per_record) - 1))], "max": max(per_record)},
    }
    if ranked is not None:
        top = ranked[:K]
        result[f"precision_at_{K}"] = round(sum(pair in planted for pair in top) / K, 3)
    return result


def run_seed(size: int, seed: int) -> list[dict]:
    data = generate(size, seed)
    rows = data["rows"]
    config = NearDuplicateConfig(max_pair_comparisons=10**7, max_candidates=10**7)
    tracemalloc.start()
    started = time.perf_counter()
    result = detect_near_duplicate_claims(rows, config)
    search_seconds = time.perf_counter() - started
    # The rule baseline is every qualifying pair, whichever evidence class the engine assigned.
    candidates = result["candidates"] + result["common_attribute_candidates"]
    engine_pairs = [tuple(sorted(candidate["case_ids"])) for candidate in result["candidates"]]
    started = time.perf_counter()
    support = combination_support(rows, candidates)
    expected = chance_expectation(rows, candidates)
    scoring_seconds = time.perf_counter() - started
    peak_mb = tracemalloc.get_traced_memory()[1] / 1e6
    tracemalloc.stop()
    pairs = [tuple(sorted(candidate["case_ids"])) for candidate in candidates]
    similarity = [candidate["similarity_ratio"] for candidate in candidates]
    digest = {pair: hash(pair) for pair in pairs}
    by_similarity = sorted(range(len(pairs)), key=lambda i: (-similarity[i], pairs[i]))
    by_support = sorted(range(len(pairs)), key=lambda i: (support[i], -similarity[i], pairs[i]))
    by_expected = sorted(range(len(pairs)), key=lambda i: (expected[i], -similarity[i], pairs[i]))
    del digest
    rows_out = [
        summarize(set(pairs), data, "rule_all_candidates", [pairs[i] for i in by_similarity]),
        summarize({pairs[i] for i in range(len(pairs)) if support[i] <= 2}, data, "support_le_2", [pairs[i] for i in by_support]),
        summarize({pairs[i] for i in range(len(pairs)) if support[i] <= 3}, data, "support_le_3"),
        summarize({pairs[i] for i in range(len(pairs)) if expected[i] < 1}, data, "independence_expected_lt_1",
                  [pairs[i] for i in by_expected]),
        # What the engine actually flags, in the order it returns (expected chance pairs, then similarity).
        summarize(set(engine_pairs), data, "engine_informative_output", engine_pairs),
    ]
    rows_out[-1]["matches_support_le_2_reference"] = set(engine_pairs) == {
        pairs[i] for i in range(len(pairs)) if support[i] <= 2}
    for item in rows_out:
        item.update({"seed": seed, "records": len(rows), "search_seconds": round(search_seconds, 2),
                     "scoring_seconds": round(scoring_seconds, 2), "peak_mb": round(peak_mb, 1),
                     "planted_pairs": len(data["planted"]), "routine_pairs": len(data["routine"])})
    shuffled = rows[:]
    random.Random(seed + 7).shuffle(shuffled)
    shuffled_result = detect_near_duplicate_claims(shuffled, config)
    again = shuffled_result["candidates"] + shuffled_result["common_attribute_candidates"]
    again_support = combination_support(shuffled, again)
    stable = {tuple(sorted(c["case_ids"])) for c, s in zip(again, again_support) if s <= 2} == \
        {pairs[i] for i in range(len(pairs)) if support[i] <= 2}
    rows_out[1]["stable_under_shuffle"] = stable
    return rows_out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=6000)
    parser.add_argument("--seeds", default="1-5")
    args = parser.parse_args()
    first, last = (int(part) for part in args.seeds.split("-"))
    for seed in range(first, last + 1):
        for row in run_seed(args.records, seed):
            print(json.dumps(row))


if __name__ == "__main__":
    main()
