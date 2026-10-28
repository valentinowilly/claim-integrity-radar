"""P0: one explicit repeat-pattern definition, and why 81 and 20 groups differ (synthetic only)."""

import json
import random

import pytest

from app.analytics.repeat_billing import AMOUNT_WITHHELD_SIGNATURE_FIELDS, detect_repeat_billing_candidates
from app.analytics.repeat_definitions import (
    LEGACY_SCRIPT_REPEAT_SERVICE, REPEAT_SERVICE_V1, RepeatDefinition, group_repeat_patterns,
    summarize_repeat_patterns,
)


def _row(index, *, participant="p1", day="2024-03-04", dx="A01", cbg="G1", proc="P1", amount="100", **extra):
    return {"case_id": f"case_{index:04d}", "participant_token": participant, "service_date": day,
            "primary_diagnosis": dx, "claim_group": cbg, "procedure_code": proc,
            "provider_billed_amount_unverified": amount, **extra}


def test_identical_repeat_forms_one_group():
    summary = summarize_repeat_patterns([_row(1), _row(2)], REPEAT_SERVICE_V1)
    assert (summary["groups"], summary["rows_in_groups"], summary["extra_rows"]) == (1, 2, 1)
    assert summary["same_amount_subset"]["groups"] == 1


def test_different_amounts_stay_a_pattern_but_leave_the_same_amount_subset():
    summary = summarize_repeat_patterns([_row(1, amount="100"), _row(2, amount="250")], REPEAT_SERVICE_V1)
    assert summary["groups"] == 1
    subset = summary["same_amount_subset"]
    assert subset["groups"] == 0 and subset["key_groups_with_differing_amounts"] == 1


def test_missing_key_field_is_ineligible_not_a_matching_value():
    records = [_row(1, proc=None), _row(2, proc=None)]
    core = summarize_repeat_patterns(records, REPEAT_SERVICE_V1)
    assert core["groups"] == 0 and core["ineligible_rows"] == 2
    assert core["ineligible_rows_by_missing_field"] == {"procedure_code": 2}
    # The exploratory script matched "<MISSING>" as a value: the same rows form a group there.
    legacy = summarize_repeat_patterns(records, LEGACY_SCRIPT_REPEAT_SERVICE)
    assert legacy["groups"] == 1 and legacy["ineligible_rows"] == 0


def test_different_participants_never_form_a_repeat_group():
    summary = summarize_repeat_patterns([_row(1, participant="p1"), _row(2, participant="p2")], REPEAT_SERVICE_V1)
    assert summary["groups"] == 0


def test_similar_looking_normal_visits_do_not_match():
    records = [_row(1), _row(2, proc="P2"), _row(3, day="2024-03-05"), _row(4, cbg="G2"), _row(5, dx="A02")]
    assert summarize_repeat_patterns(records, REPEAT_SERVICE_V1)["groups"] == 0


def test_missing_amount_is_excluded_from_the_subset_but_was_zero_in_the_legacy_script():
    records = [_row(1, amount=None), _row(2, amount="")]
    core = summarize_repeat_patterns(records, REPEAT_SERVICE_V1)["same_amount_subset"]
    legacy = summarize_repeat_patterns(records, LEGACY_SCRIPT_REPEAT_SERVICE)["same_amount_subset"]
    assert core["groups"] == 0 and core["rows_in_key_groups_without_valid_amount"] == 2
    assert legacy["groups"] == 1  # missing amounts coerced to 0 compare equal


def test_reconstructs_the_81_versus_20_relationship_on_synthetic_pairs():
    """81 pattern groups were all pairs; 61 had differing FKL47, so 81 - 61 = 20 equal-amount groups."""
    records, index = [], 0
    for pair in range(81):
        amounts = ("100", "100") if pair < 20 else ("100", "200")
        for amount in amounts:
            records.append(_row(index, participant=f"p{pair}", amount=amount))
            index += 1
    summary = summarize_repeat_patterns(records, LEGACY_SCRIPT_REPEAT_SERVICE)
    assert (summary["groups"], summary["rows_in_groups"], summary["extra_rows"]) == (81, 162, 81)
    subset = summary["same_amount_subset"]
    assert (subset["groups"], subset["rows_in_groups"], subset["extra_rows"]) == (20, 40, 20)
    assert subset["key_groups_with_differing_amounts"] == 61


def test_results_do_not_depend_on_row_order():
    records = [_row(i, participant=f"p{i % 7}", proc=None if i % 5 == 0 else "P1", amount=str(i % 3)) for i in range(60)]
    shuffled = records[:]
    random.Random(4).shuffle(shuffled)
    for definition in (REPEAT_SERVICE_V1, LEGACY_SCRIPT_REPEAT_SERVICE):
        assert summarize_repeat_patterns(records, definition) == summarize_repeat_patterns(shuffled, definition)


def test_summary_contains_no_identifiers_or_key_values():
    records = [_row(1, participant="participant_secret"), _row(2, participant="participant_secret")]
    text = json.dumps(summarize_repeat_patterns(records, REPEAT_SERVICE_V1))
    for value in ("case_0001", "participant_secret", "A01", "G1", "P1", "2024-03-04"):
        assert value not in text


def test_definition_requires_the_same_participant_and_valid_policies():
    with pytest.raises(ValueError):
        RepeatDefinition("bad", ("service_date",))
    with pytest.raises(ValueError):
        RepeatDefinition("bad", ("participant_token",), missing_policy="guess")


def test_detector_and_core_definition_agree():
    records = [
        {**_row(1), "province_code": "11", "municipality_code": "1101", "facility_ownership": "1",
         "facility_type": "2", "facility_class": "3", "admission_diagnosis": "A01"},
    ]
    records.append({**records[0], "case_id": "case_0002"})
    records.append({**records[0], "case_id": "case_0003", "procedure_code": None})
    detector = detect_repeat_billing_candidates(records, AMOUNT_WITHHELD_SIGNATURE_FIELDS)
    core = group_repeat_patterns(records, RepeatDefinition("profile", AMOUNT_WITHHELD_SIGNATURE_FIELDS))
    assert [group["case_ids"] for group in detector["candidate_groups"]] == core.groups == [["case_0001", "case_0002"]]
    assert [item["case_id"] for item in detector["ineligible_cases"]] == ["case_0003"]
