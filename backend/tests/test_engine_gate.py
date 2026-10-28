"""Detection engine capability gate: labelled synthetic fixtures with exact expected outputs.

Similar-claim screening is checked against a brute-force ground truth of its own rule (same
admission date, different participants, >= 9 comparable attributes, similarity >= 0.8); this
measures search completeness and coverage honesty, not fraud detection.
"""

from datetime import date, timedelta
from itertools import combinations
import json
import random

import pytest

from app.analytics.length_of_stay import detect_length_of_stay_outliers
from app.analytics.near_duplicate_claims import (
    NEAR_FIELDS, NearDuplicateConfig, _field_value, _max_bad_attributes, blocking_fields,
    detect_near_duplicate_claims, prerequisite_reason,
)
from app.analytics.repeat_billing import REPEAT_SERVICE_PROFILE, SIGNATURE_PROFILES, detect_repeat_billing_candidates
from app.analytics.risk_scoring import DETECTOR_ORDER, run_detector_suite, score_claims

GROUPED = [field for field in NEAR_FIELDS if field not in ("service_date", "billed_amount")]


def claim(case, participant, **overrides):
    row = {"case_id": f"syn-{case}", "participant_token": f"syn-participant-{participant}", "service_date": "2024-03-04",
           "province_code": "11", "municipality_code": "1101", "facility_ownership": "1", "facility_type": "2",
           "facility_class": "3", "admission_diagnosis": "A01", "primary_diagnosis": "B01", "claim_group": "G1",
           "procedure_code": "P1", "billed_amount": None}
    return {**row, **overrides}


def qualifying_pairs(records, config=NearDuplicateConfig()):
    """Brute-force ground truth of the screen's own rule over every pair."""
    values = {row["case_id"]: (row, tuple(_field_value(field, row.get(field)) for field in NEAR_FIELDS)) for row in records}
    truth = set()
    for (left, (left_row, a)), (right, (right_row, b)) in combinations(values.items(), 2):
        if left_row["participant_token"] == right_row["participant_token"] or a[0] is None or a[0] != b[0]:
            continue
        compared = [(x, y, field) for x, y, field in zip(a, b, NEAR_FIELDS) if x is not None and y is not None]
        if len(compared) < config.min_compared_attributes:
            continue
        matched = sum(abs(x - y) <= config.amount_tolerance if field == "billed_amount" else x == y for x, y, field in compared)
        if matched / len(compared) >= config.min_similarity:
            truth.add(tuple(sorted((left, right))))
    return truth


def found_pairs(result):
    """Every pair meeting the rule: informative candidates plus pairs explained by common attributes."""
    return {tuple(sorted(candidate["case_ids"]))
            for candidate in result["candidates"] + result.get("common_attribute_candidates", [])}


# ---- Similar-claim screening -------------------------------------------------------------

def difference_cases(amount):
    """Every allowed pattern of differing/missing attributes, one planted pair per pattern."""
    limit = _max_bad_attributes(NearDuplicateConfig(), amount_available=amount)
    rows, index = [], 0
    for size in range(0, limit + 1):
        for bad in combinations(GROUPED, size):
            for missing_count in range(0, size + 1):
                missing = set(bad[:missing_count])
                base = claim(f"p{index}a", f"{index}a", billed_amount="100" if amount else None,
                             service_date=(date(2024, 1, 1) + timedelta(days=index)).isoformat())
                other = {**base, "case_id": f"syn-p{index}b", "participant_token": f"syn-participant-{index}b"}
                for field in bad:
                    other[field] = None if field in missing else f"X{index}"
                rows += [base, other]
                index += 1
    return rows


@pytest.mark.parametrize("amount", [False, True])
def test_every_pair_the_rule_accepts_is_found_with_a_complete_search(amount):
    # Before: with the previous three blocking keys, pairs differing only in {primary, admission
    # diagnosis}, {municipality, admission diagnosis} or {province, municipality} were never
    # compared, yet both records were reported as assessed and not flagged.
    records = difference_cases(amount)
    result = detect_near_duplicate_claims(records, NearDuplicateConfig(max_pair_comparisons=10**6, max_candidates=10**6))
    truth = qualifying_pairs(records)
    assert truth and found_pairs(result) == truth
    assert result["unassessed_case_ids"] == [] and result["search_truncated"] is False
    assert result["search_diagnostics"]["blocking_complete_for_threshold"] is True


def test_hard_negatives_are_not_paired():
    base = claim("n0", "a")
    records = [
        base,
        claim("three-diff", "b", primary_diagnosis="Z", admission_diagnosis="Z", claim_group="Z"),  # 7 of 10
        claim("other-day", "c", service_date="2024-03-05"),                                         # out of scope
        claim("same-person", "a"),                                                                  # same participant
    ]
    result = detect_near_duplicate_claims(records)
    assert found_pairs(result) == set()
    assert qualifying_pairs(records) == set()


def test_records_with_too_few_attributes_are_ineligible_not_negative():
    records = [claim("full", "a"), claim("sparse", "b", procedure_code=None, admission_diagnosis=None)]
    result = detect_near_duplicate_claims(records)
    assert [item["case_id"] for item in result["ineligible_cases"]] == ["syn-sparse"]
    assert prerequisite_reason(records[1]) == "too_few_attributes"
    scored = score_claims(records, run_detector_suite(records, []))
    state = {case["case_id"]: next(row["status"] for row in case["indicator_coverage"]
                                   if row["indicator"] == "near_duplicate_claim_candidate") for case in scored["cases"]}
    assert state["syn-sparse"] == "not_assessed"


def background(size, seed):
    rng = random.Random(seed)
    rows = []
    for index in range(size):
        rows.append(claim(f"bg{index}", f"bg{index % (size // 2)}", service_date=f"2024-03-0{1 + rng.randrange(3)}",
                          municipality_code=rng.choice(["1101", "1102"]), province_code="11",
                          primary_diagnosis=rng.choice(["B01", "B02", "B03"]), admission_diagnosis=rng.choice(["A01", "A02"]),
                          claim_group=rng.choice(["G1", "G2"]), procedure_code=rng.choice(["P1", "P2", None]),
                          facility_class=rng.choice(["1", "2", "3"])))
    return rows


@pytest.mark.parametrize("budget", [50, 400, 10**6])
def test_assessed_means_every_qualifying_partner_was_compared(budget):
    # Dense synthetic blocks force a bounded search; whatever the budget, a record reported as
    # assessed and not flagged must have no qualifying partner left uncompared.
    records = background(240, seed=3)
    result = detect_near_duplicate_claims(records, NearDuplicateConfig(max_pair_comparisons=budget, max_candidates=10**6))
    truth, found = qualifying_pairs(records), found_pairs(result)
    assert found <= truth
    unassessed = set(result["unassessed_case_ids"])
    flagged = {case_id for pair in found for case_id in pair}
    for left, right in truth - found:
        assert left in unassessed or left in flagged
        assert right in unassessed or right in flagged
        assert not ({left, right} <= (set(row["case_id"] for row in records) - unassessed - flagged))
    if budget == 10**6:
        assert found == truth and not unassessed


def test_oversized_blocks_are_assessed_through_their_refinement_buckets():
    # 150 same-day claims share the first blocking key but differ from each other in four
    # attributes (no qualifying pairs); one planted copy differs from its source in two. The
    # block exceeds max_block_size, yet the copy is found and every member is assessed.
    records = [claim(f"big{index}", f"big{index}", procedure_code=f"P{index}", facility_class=f"C{index}",
                     admission_diagnosis=f"A{index}", claim_group=f"G{index}") for index in range(150)]
    records.append({**records[0], "case_id": "syn-copy", "participant_token": "syn-participant-copy",
                    "claim_group": "G-copy", "facility_class": "C-copy"})
    config = NearDuplicateConfig(max_pair_comparisons=10**6, max_candidates=10**6)
    result = detect_near_duplicate_claims(records, config)
    assert result["search_diagnostics"]["oversized_primary_block_count"] >= 1
    assert found_pairs(result) == qualifying_pairs(records)
    assert ("syn-big0", "syn-copy") in found_pairs(result) and result["unassessed_case_ids"] == []


def test_input_order_and_position_do_not_change_results():
    records = difference_cases(False) + background(120, seed=5)
    config = NearDuplicateConfig(max_pair_comparisons=2000, max_candidates=10**6)
    reference = detect_near_duplicate_claims(records, config)
    for seed in (1, 2, 3):
        shuffled = records[:]
        random.Random(seed).shuffle(shuffled)
        again = detect_near_duplicate_claims(shuffled, config)
        assert found_pairs(again) == found_pairs(reference)
        assert again["unassessed_case_ids"] == reference["unassessed_case_ids"]


def test_bounded_search_discloses_its_selection_and_output_has_no_tokens():
    records = background(240, seed=3)
    bounded = detect_near_duplicate_claims(records, NearDuplicateConfig(max_pair_comparisons=50))
    assert bounded["search_diagnostics"]["assessment_selection"] == "bounded_small_neighbourhoods_first"
    assert any("tidak mewakili seluruh jendela" in text for text in bounded["limitations"])
    complete = detect_near_duplicate_claims(records, NearDuplicateConfig(max_pair_comparisons=10**6, max_candidates=10**6))
    assert complete["search_diagnostics"]["assessment_selection"] == "complete"
    assert "syn-participant" not in json.dumps(bounded) and "syn-participant" not in json.dumps(complete)


def test_blocking_keys_cover_every_bad_attribute_set_the_threshold_allows():
    for amount, groups in ((False, 3), (True, 4)):
        limit = _max_bad_attributes(NearDuplicateConfig(), amount_available=amount)
        keys = blocking_fields(groups)
        assert limit < groups
        for size in range(1, limit + 1):
            for bad in combinations(GROUPED, size):
                assert any(not set(bad) & set(key) for key in keys), bad


# ---- Repeated-service pattern ------------------------------------------------------------

CORE = SIGNATURE_PROFILES[REPEAT_SERVICE_PROFILE]


def test_repeat_positive_negative_and_unassessed_cases_are_exact():
    records = [
        claim("r1", "p"), claim("r2", "p"),                                   # same key: one pattern
        claim("r3", "p", procedure_code="P9"),                                # different procedure: negative
        claim("r4", "q"), claim("r5", "q", procedure_code=" n/a "),           # sentinel procedure: unassessed
        claim("r6", "s", procedure_code=None), claim("r7", "s", procedure_code=None),  # blank pair: never a pattern
    ]
    result = detect_repeat_billing_candidates(records, CORE)
    assert [group["case_ids"] for group in result["candidate_groups"]] == [["syn-r1", "syn-r2"]]
    assert sorted(item["case_id"] for item in result["ineligible_cases"]) == ["syn-r5", "syn-r6", "syn-r7"]
    scored = score_claims(records, run_detector_suite(records, [], repeat_signature_fields=CORE))
    states = {case["case_id"]: next(row["status"] for row in case["indicator_coverage"]
                                    if row["indicator"] == "repeat_billing_candidate") for case in scored["cases"]}
    assert states == {"syn-r1": "triggered", "syn-r2": "triggered", "syn-r3": "not_triggered", "syn-r4": "not_triggered",
                      "syn-r5": "not_assessed", "syn-r6": "not_assessed", "syn-r7": "not_assessed"}
    coverage = next(item for item in scored["detector_coverage"] if item["indicator"] == "repeat_billing_candidate")
    assert (coverage["triggered_case_count"], coverage["assessed_case_count"], coverage["not_assessed_case_count"]) == (2, 4, 3)
    assert "syn-participant" not in json.dumps(result)
    for seed in (1, 2):
        shuffled = records[:]
        random.Random(seed).shuffle(shuffled)
        assert detect_repeat_billing_candidates(shuffled, CORE)["candidate_groups"] == result["candidate_groups"]


# ---- Length of stay ----------------------------------------------------------------------

def stays(prefix, count, span, start=0, **overrides):
    return [{"case_id": f"syn-{prefix}{index}", "participant_token": f"syn-participant-{prefix}{index}",
             "service_date": "2024-03-01", "discharge_date": (date(2024, 3, 1) + timedelta(days=span)).isoformat(),
             "claim_group": "G1", "care_class": "3", **overrides} for index in range(start, start + count)]


def test_length_of_stay_flags_only_planted_extremes_and_fails_closed():
    ordinary = [row for span in (2, 3, 4) for row in stays(f"o{span}-", 60, span)]
    extreme = stays("x", 1, 40)
    small_group = stays("s", 20, 30, claim_group="G2")                 # below peer support
    broken = [*stays("m", 1, 3, discharge_date=None), *stays("i", 1, 3, discharge_date="2024-03-011"),
              *stays("v", 1, 3, discharge_date="2024-02-01")]
    records = ordinary + extreme + small_group + broken
    result = detect_length_of_stay_outliers(records)
    assert [item["case_id"] for item in result["candidates"]] == ["syn-x0"]
    reasons = result["unassessed_reason_counts"]
    assert (reasons["insufficient_peer_support"], reasons["missing_date"], reasons["invalid_date"],
            reasons["reversed_dates"]) == (20, 1, 1, 1)
    shuffled = records[:]
    random.Random(4).shuffle(shuffled)
    assert [item["case_id"] for item in detect_length_of_stay_outliers(shuffled)["candidates"]] == ["syn-x0"]
    assert "fraud" in " ".join(result["limitations"]).lower()


# ---- Risk index withholding --------------------------------------------------------------

def test_index_is_withheld_when_fewer_than_three_checks_apply():
    records = [claim("w1", "p"), claim("w2", "p")]
    unsupported = {code: "not in source" for code in ("similar_claim_pattern_candidate", "synthetic_capacity_candidate",
                                                      "temporal_pattern_candidate", "supporting_evidence_completeness_candidate")}
    scored = score_claims(records, run_detector_suite(records, [], repeat_signature_fields=CORE, not_applicable=unsupported))
    for case in scored["cases"]:
        assert case["risk_score"] is None and case["score_status"] == "insufficient_assessed_indicators"
        # Without the BPJS-format clinical checks only repeat and near-duplicate apply (4 + 3 not applicable).
        assert len(case["assessed_indicators"]) == 2
        assert len(case["not_applicable_indicators"]) == len(DETECTOR_ORDER) - 2


# ---- Similar-claim evidence classes (utility gate) ---------------------------------------

def test_routine_cluster_is_common_and_a_unique_copy_is_informative():
    # Six routine claims, two procedures: every matched combination is held by at least three claims.
    routine = [claim(f"rt{index}", f"rt{index}", procedure_code=f"P{index % 2}") for index in range(6)]
    source = claim("src", "src", primary_diagnosis="B77", admission_diagnosis="A77", claim_group="G77",
                   municipality_code="1199")
    copy = {**source, "case_id": "syn-copy", "participant_token": "syn-participant-copy", "facility_class": "9"}
    records = routine + [source, copy]
    result = detect_near_duplicate_claims(records, NearDuplicateConfig(max_pair_comparisons=10**6, max_candidates=10**6))
    assert [tuple(sorted(item["case_ids"])) for item in result["candidates"]] == [("syn-copy", "syn-src")]
    [candidate] = result["candidates"]
    assert candidate["evidence_class"] == "informative" and candidate["match_support"] == 2
    assert "kombinasi umum" in candidate["reason"]
    common = result["common_attribute_candidates"]
    assert common and all(item["evidence_class"] == "common_attributes" and item["match_support"] >= 3 for item in common)
    diagnostics = result["search_diagnostics"]
    assert diagnostics["qualifying_pair_count"] == len(common) + 1
    assert diagnostics["records_matched_only_on_common_attributes"] == 6
    # Records matched only on a common combination are assessed and not flagged.
    scored = score_claims(records, run_detector_suite(records, []))
    states = {case["case_id"]: next(row["status"] for row in case["indicator_coverage"]
                                    if row["indicator"] == "near_duplicate_claim_candidate") for case in scored["cases"]}
    assert states["syn-copy"] == states["syn-src"] == "triggered"
    assert all(states[f"syn-rt{index}"] == "not_triggered" for index in range(6))


def test_match_support_equals_the_benchmark_reference_and_ignores_budget():
    from scripts.similar_claim_utility_benchmark import combination_support, generate

    data = generate(800, seed=11)
    complete = detect_near_duplicate_claims(data["rows"], NearDuplicateConfig(max_pair_comparisons=10**6, max_candidates=10**6))
    pairs = complete["candidates"] + complete["common_attribute_candidates"]
    assert [item["match_support"] for item in pairs] == combination_support(data["rows"], pairs)
    bounded = detect_near_duplicate_claims(data["rows"], NearDuplicateConfig(max_pair_comparisons=300))
    reference = {tuple(item["case_ids"]): item["match_support"] for item in pairs}
    for item in bounded["candidates"] + bounded["common_attribute_candidates"]:
        assert item["match_support"] == reference[tuple(item["case_ids"])]
    order = [item["expected_chance_pairs"] for item in complete["candidates"]]
    assert order == sorted(order)
