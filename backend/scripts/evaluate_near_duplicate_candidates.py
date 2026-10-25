"""Evaluate bounded near-duplicate candidate generation on synthetic labeled pairs.

Ground-truth labels are held in a separate fixture structure and never passed
to the detector. This measures only the constructed synthetic pair universe.
"""

from __future__ import annotations

import argparse
import json
import random
from copy import deepcopy
from datetime import date, timedelta

from app.analytics.near_duplicate_claims import NearDuplicateConfig, detect_near_duplicate_claims


def build_fixture(record_count: int, seed: int = 731) -> tuple[list[dict], dict[str, set[tuple[str, str]]]]:
    if record_count < 4:
        raise ValueError("record_count minimal 4")
    base = {
        "service_date": "2024-04-12", "province_code": f"SYN-PROV-{seed % 97:02d}",
        "municipality_code": f"SYN-MUNI-{seed % 997:03d}", "facility_ownership": "synthetic-public",
        "facility_type": "synthetic-general", "facility_class": "synthetic-class-a",
        "admission_diagnosis": "SYN-AD-001", "primary_diagnosis": "SYN-DX-001",
        "claim_group": "SYN-GROUP-001", "procedure_code": "SYN-PROC-001",
        "billed_amount": "125000", "service_type": "synthetic-therapy",
    }
    records: list[dict] = []
    positive_pairs: set[tuple[str, str]] = set()
    negative_pairs: set[tuple[str, str]] = set()
    pair_count = record_count // 2
    rng = random.Random(seed)
    positive_indexes = set(rng.sample(range(pair_count), pair_count // 2))
    for index in range(pair_count):
        positive = index in positive_indexes
        # IDs and row order carry no label text; labels remain in the separate
        # fixture structure below.
        left_id, right_id = f"syn-eval-{index:07d}-a", f"syn-eval-{index:07d}-b"
        left, right = deepcopy(base), deepcopy(base)
        day_offset = rng.randrange(365)
        shared_block = {
            "service_date": (date(2024, 1, 1) + timedelta(days=day_offset)).isoformat(),
            "municipality_code": f"fixture-municipality-{rng.randrange(10**9):09d}",
            "primary_diagnosis": f"fixture-diagnosis-{rng.randrange(10**9):09d}",
            "admission_diagnosis": f"fixture-admission-{rng.randrange(10**9):09d}",
        }
        for row, case_id, participant in (
            (left, left_id, f"fixture-participant-{index:07d}-a"),
            (right, right_id, f"fixture-participant-{index:07d}-b"),
        ):
            row["case_id"] = case_id
            row["claim_id"] = case_id
            row["participant_token"] = participant
            # Each pair gets a distinct, deterministic block so the benchmark
            # controls pair density and does not derive labels from row order.
            row.update(shared_block)
        if positive:
            right["procedure_code"] = f"{left['procedure_code']}-variant"
            positive_pairs.add(tuple(sorted((left_id, right_id))))
        else:
            # Plausible look-alike control below the configured similarity
            # threshold; remains a negative example in this fixture.
            right["procedure_code"] = f"{left['procedure_code']}-variant"
            right["claim_group"] = f"{left['claim_group']}-variant"
            right["facility_class"] = f"{left['facility_class']}-variant"
            negative_pairs.add(tuple(sorted((left_id, right_id))))
        records.extend((left, right))
    if record_count % 2:
        row = deepcopy(base)
        row["case_id"] = f"syn-eval-singleton-{record_count:07d}"
        row["claim_id"] = row["case_id"]
        row["participant_token"] = f"fixture-participant-singleton-{record_count:07d}"
        row["municipality_code"] = f"fixture-singleton-municipality-{record_count:07d}"
        row["primary_diagnosis"] = f"fixture-singleton-diagnosis-{record_count:07d}"
        records.append(row)
    return records, {"positive_pairs": positive_pairs, "negative_pairs": negative_pairs}


def evaluate(
    record_count: int,
    comparison_limit: int,
    seed: int = 731,
    reverse_input: bool = False,
) -> dict:
    records, ground_truth = build_fixture(record_count, seed)
    if reverse_input:
        records.reverse()
    generated_pairs: set[tuple[str, str]] = set()
    similarity_checked: set[tuple[str, str]] = set()
    similarity_passed: set[tuple[str, str]] = set()

    def observe_generated(left: str, right: str) -> None:
        generated_pairs.add(tuple(sorted((left, right))))

    def observe_similarity(left: str, right: str, passed: bool) -> None:
        pair = tuple(sorted((left, right)))
        similarity_checked.add(pair)
        if passed:
            similarity_passed.add(pair)

    result = detect_near_duplicate_claims(records, NearDuplicateConfig(
        max_pair_comparisons=comparison_limit,
        max_candidates=comparison_limit,
    ), candidate_pair_observer=observe_generated,
        similarity_observer=observe_similarity)
    predicted = {tuple(sorted(item["case_ids"])) for item in result["candidates"]}
    positives = ground_truth["positive_pairs"]
    negatives = ground_truth["negative_pairs"]
    positive_generated = positives & generated_pairs
    positive_checked = positives & similarity_checked
    positive_passed = positives & similarity_passed
    positive_uncovered_by_search = positives - generated_pairs
    positive_generated_but_unchecked = positive_generated - similarity_checked
    positive_checked_but_failed = positive_checked - similarity_passed
    negative_checked = negatives & similarity_checked
    false_positive = negatives & similarity_passed
    labeled_pairs = positives | negatives
    unlabeled_predicted = predicted - labeled_pairs
    return {
        "data_source": "synthetic_fixture_only",
        "seed": seed,
        "input_order": "reversed" if reverse_input else "forward",
        "record_count": len(records),
        "comparison_limit": comparison_limit,
        "ground_truth_positive_pair_count": len(positives),
        "ground_truth_negative_pair_count": len(negatives),
        "positive_pairs_discovered_by_candidate_generation": len(positive_generated),
        "positive_pairs_actually_similarity_checked": len(positive_checked),
        "positive_pairs_checked_and_passed_threshold": len(positive_passed),
        "positive_pairs_checked_but_failed_threshold": len(positive_checked_but_failed),
        "positive_pairs_generated_but_not_similarity_checked": len(positive_generated_but_unchecked),
        "positive_pairs_not_generated_by_bounded_block_search": len(positive_uncovered_by_search),
        "positive_pair_discovery_rate": (
            len(positive_generated) / len(positives) if positives else None
        ),
        "positive_pair_similarity_pass_rate_of_planted": (
            len(positive_passed) / len(positives) if positives else None
        ),
        "negative_control_pairs_actually_similarity_checked": len(negative_checked),
        "negative_control_pairs_predicted": len(false_positive),
        "predicted_pairs_outside_labeled_fixture_universe": len(unlabeled_predicted),
        "unique_triggered_case_count": len({case_id for pair in predicted for case_id in pair}),
        "unassessed_case_count": len(result["unassessed_case_ids"]),
        "pair_comparisons": result["pair_comparisons"],
        "generated_pair_count": len(generated_pairs),
        "similarity_checked_pair_count": len(similarity_checked),
        "search_truncated": result["search_truncated"],
        "diagnostics": result["search_diagnostics"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 1000, 10000])
    parser.add_argument("--limits", nargs="+", type=int, default=[100, 1000, 5000])
    parser.add_argument("--seed", type=int, default=731)
    args = parser.parse_args()
    print(json.dumps([
        evaluate(size, limit, args.seed)
        for size in args.sizes
        for limit in args.limits
    ], sort_keys=True))


if __name__ == "__main__":
    main()
