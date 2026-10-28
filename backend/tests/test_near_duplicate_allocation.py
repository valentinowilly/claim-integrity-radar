"""Phase 3: deterministic near-duplicate budget allocation and coverage accounting.

Records are small synthetic canonical fixtures; no BPJS data is used.
"""

import hashlib
import random

import pytest

from app.analytics.near_duplicate_claims import NearDuplicateConfig, detect_near_duplicate_claims
from app.analytics.risk_scoring import score_claims


def _record(index, *, participant=None, day=4, **overrides):
    row = {
        "case_id": f"case_{index:04d}", "participant_token": participant or f"p{index}",
        "service_date": f"2024-03-{day:02d}", "province_code": "11", "municipality_code": "1101",
        "facility_ownership": "1", "facility_type": "2", "facility_class": "3",
        "admission_diagnosis": "A01", "primary_diagnosis": "A01", "claim_group": "G1",
        "procedure_code": "P1", "billed_amount": None,
    }
    row.update(overrides)
    return row


def _coverage(records, result):
    scored = score_claims(records, {"near_duplicate_claim_candidate": result})
    item = next(i for i in scored["detector_coverage"] if i["indicator"] == "near_duplicate_claim_candidate")
    return item["assessed_case_count"], item["not_assessed_case_count"]


def _small_blocks(count=5, size=3):
    """Separate admission dates make independent blocks; members are identical across participants."""
    return [_record(block * 10 + member, day=block + 1) for block in range(count) for member in range(size)]


# 1. Small blocks that fit within the budget

def test_small_blocks_that_fit_are_processed_completely():
    records = _small_blocks()  # 5 blocks x 3 pairs = 15 valid pairs
    result = detect_near_duplicate_claims(records, NearDuplicateConfig(max_pair_comparisons=15))
    diagnostics = result["search_diagnostics"]
    # Members are identical, so each pair shares its combination with a third claim: all 15 meet
    # the rule and are classified as common-attribute pairs rather than flagged.
    assert result["pair_comparisons"] == 15 and diagnostics["qualifying_pair_count"] == 15
    assert (result["candidate_count"], diagnostics["common_attribute_pair_count"]) == (0, 15)
    assert result["unassessed_case_ids"] == [] and result["search_truncated"] is False
    assert diagnostics["sampled_unit_count"] == 0 and diagnostics["comparison_limit_hit"] is False
    assert _coverage(records, result) == (15, 0)


# 2. Mixed small and large blocks with leftover budget

def _mixed():
    small = [_record(100 + i, day=1 + i // 2, primary_diagnosis=f"S{i // 2}") for i in range(6)]  # 3 blocks of 2
    large = [_record(200 + i, day=20, procedure_code=f"P{i}") for i in range(8)]  # 1 block, 28 pairs, all distinct
    return small + large


def test_leftover_budget_is_spent_on_larger_blocks_after_small_blocks_complete():
    records = _mixed()
    result = detect_near_duplicate_claims(records, NearDuplicateConfig(max_pair_comparisons=10))
    diagnostics = result["search_diagnostics"]
    small_ids = {f"case_{100 + i:04d}" for i in range(6)}
    large_ids = {f"case_{200 + i:04d}" for i in range(8)}
    assert diagnostics["planned_pair_count"] == 10  # 3 small pairs + 7 sampled large pairs: no idle budget
    assert diagnostics["comparison_limit_hit"] is True and result["search_truncated"] is True
    assert set(result["unassessed_case_ids"]) == large_ids  # only the partially searched block
    assert not small_ids & set(result["unassessed_case_ids"])
    assert diagnostics["fully_processed_unit_count"] >= 3 and diagnostics["sampled_unit_count"] >= 1


# 3. Dense block where the budget is exhausted

def test_dense_block_with_exhausted_budget_leaves_its_records_unassessed():
    records = [_record(i, procedure_code=f"P{i % 4}") for i in range(20)]
    result = detect_near_duplicate_claims(records, NearDuplicateConfig(max_pair_comparisons=5))
    assert result["pair_comparisons"] == 5
    assert result["search_diagnostics"]["comparison_limit_hit"] is True
    assert set(result["unassessed_case_ids"]) == {row["case_id"] for row in records}
    triggered = {case_id for candidate in result["candidates"] for case_id in candidate["case_ids"]}
    assessed, unassessed = _coverage(records, result)
    assert (assessed, unassessed) == (len(triggered), 20 - len(triggered))  # never a negative finding


# 4. Candidate-cap exhaustion

def test_candidate_cap_stops_comparisons_and_marks_uncompared_pairs_unassessed():
    records = [_record(i) for i in range(6)]  # 15 identical cross-participant pairs
    result = detect_near_duplicate_claims(records, NearDuplicateConfig(max_candidates=2))
    diagnostics = result["search_diagnostics"]
    # The cap applies to pairs meeting the rule, whatever their evidence class.
    assert diagnostics["qualifying_pair_count"] == 2 and result["pair_comparisons"] == 2
    assert diagnostics["candidate_limit_hit"] is True and diagnostics["comparison_limit_hit"] is False
    assert diagnostics["planned_pair_count"] == 15 and result["search_truncated"] is True
    assert diagnostics["candidate_limit_unassessed_case_count"] > 0


# 5. Same-participant exclusion

def test_same_participant_pairs_never_consume_the_budget():
    records = [_record(i, participant="same") for i in range(5)] + [_record(9, participant="other")]
    result = detect_near_duplicate_claims(records, NearDuplicateConfig(max_pair_comparisons=5))
    diagnostics = result["search_diagnostics"]
    assert diagnostics["same_participant_pair_count"] == 10  # C(5, 2), checked once each
    assert result["pair_comparisons"] == 5 and diagnostics["comparison_limit_hit"] is False
    assert all("case_0009" in candidate["case_ids"] for candidate in result["candidates"])
    assert result["unassessed_case_ids"] == []


# 6. Missing or insufficient comparable attributes

def test_pairs_below_the_comparable_minimum_are_excluded_before_budgeting():
    records = [_record(1, procedure_code=None), _record(2, facility_class=None)]  # each 9 present, 8 shared
    result = detect_near_duplicate_claims(records, NearDuplicateConfig(max_pair_comparisons=1))
    diagnostics = result["search_diagnostics"]
    assert diagnostics["insufficient_comparable_pair_count"] == 1
    assert result["pair_comparisons"] == 0 and diagnostics["comparison_limit_hit"] is False
    # The only possible pair can never be a candidate, so both are genuine negatives.
    assert _coverage(records, result) == (2, 0)


def test_record_below_the_minimum_is_ineligible_and_kept_out_of_blocks():
    records = [_record(1), _record(2), _record(3, procedure_code=None, facility_class=None)]
    result = detect_near_duplicate_claims(records, NearDuplicateConfig(max_pair_comparisons=1))
    assert {item["case_id"] for item in result["ineligible_cases"]} == {"case_0003"}
    assert result["pair_comparisons"] == 1 and result["search_diagnostics"]["comparison_limit_hit"] is False


# 7. Pseudonymization-key invariance

def _relabel(records, key):
    """Simulate a different pseudonym key: every case ID and participant token changes."""
    def digest(value):
        return hashlib.sha256(f"{key}|{value}".encode()).hexdigest()[:24]
    relabelled = [
        {**row, "case_id": f"case_{digest(row['case_id'])}", "participant_token": f"participant_{digest(row['participant_token'])}"}
        for row in records
    ]
    back = {new["case_id"]: old["case_id"] for new, old in zip(relabelled, records)}
    return relabelled, back


def _outcome(result, back=None):
    back = back or {}
    name = lambda case_id: back.get(case_id, case_id)  # noqa: E731
    diagnostics = result["search_diagnostics"]
    return {
        "pairs": sorted(tuple(sorted(name(c) for c in candidate["case_ids"])) for candidate in result["candidates"]),
        "unassessed": sorted(name(c) for c in result["unassessed_case_ids"]),
        "counts": (result["pair_comparisons"], result["candidate_count"], result["search_truncated"],
                   diagnostics["planned_pair_count"], diagnostics["sampled_unit_count"]),
    }


@pytest.mark.parametrize("budget", [4, 10, 1000])
def test_outcomes_do_not_depend_on_the_pseudonym_key(budget):
    records = _mixed()
    config = NearDuplicateConfig(max_pair_comparisons=budget)
    outcomes = []
    for key in ("key-one", "key-two"):
        relabelled, back = _relabel(records, key)
        outcomes.append(_outcome(detect_near_duplicate_claims(relabelled, config), back))
    assert outcomes[0] == outcomes[1] == _outcome(detect_near_duplicate_claims(records, config))


# 8. Input-order invariance

@pytest.mark.parametrize("seed", [1, 2, 3])
def test_permuted_input_rows_give_identical_results_for_distinguishable_records(seed):
    records = _mixed()
    shuffled = records[:]
    random.Random(seed).shuffle(shuffled)
    config = NearDuplicateConfig(max_pair_comparisons=10)
    assert _outcome(detect_near_duplicate_claims(shuffled, config)) == _outcome(detect_near_duplicate_claims(records, config))


def test_permuted_indistinguishable_records_keep_counts_but_may_swap_identities():
    """Identical features across participants: which twin is sampled is not meaningful."""
    records = [_record(i) for i in range(12)]
    shuffled = records[:]
    random.Random(4).shuffle(shuffled)
    config = NearDuplicateConfig(max_pair_comparisons=7)
    first = _outcome(detect_near_duplicate_claims(records, config))
    second = _outcome(detect_near_duplicate_claims(shuffled, config))
    assert first["counts"] == second["counts"] and len(first["unassessed"]) == len(second["unassessed"])


# 9. Chunk-size invariance (through the FKRTL reader and provider)

def test_reader_chunk_size_does_not_change_near_duplicate_results(tmp_path):
    pytest.importorskip("pandas")
    from tests.test_fkrtl_date_window import _dense_rows, _load, _positions, _write

    path = _write(tmp_path, _dense_rows())
    outcomes = []
    for chunk_size in (1, 7, 50_000):
        dataset = _load(path, chunk_size=chunk_size)
        positions = _positions(dataset)
        outcome = _outcome(detect_near_duplicate_claims(dataset.records, NearDuplicateConfig(max_pair_comparisons=25)))
        outcomes.append({**outcome, "pairs": [tuple(sorted(positions[c] for c in pair)) for pair in outcome["pairs"]],
                         "unassessed": sorted(positions[c] for c in outcome["unassessed"])})
    assert outcomes[0] == outcomes[1] == outcomes[2]


# 10. Accurate assessed, unassessed, candidate and truncation counts

def test_counts_reconcile_for_the_mixed_scenario():
    records = _mixed()
    result = detect_near_duplicate_claims(records, NearDuplicateConfig(max_pair_comparisons=10))
    assert result["candidate_count"] == len(result["candidates"])
    assert result["pair_comparisons"] <= 10
    assert result["search_diagnostics"]["unassessed_case_count"] == len(result["unassessed_case_ids"]) == 8
    triggered = {case_id for candidate in result["candidates"] for case_id in candidate["case_ids"]}
    triggered_large = {case_id for case_id in triggered if case_id.startswith("case_02")}
    assessed, unassessed = _coverage(records, result)
    assert assessed + unassessed == len(records)
    assert unassessed == 8 - len(triggered_large)
