"""Synthetic-only unit tests for the first rule-based indicators."""

from copy import deepcopy
from datetime import date
from decimal import Decimal
import json

import pytest

from app.analytics.repeat_billing import (
    SIGNATURE_FIELDS as REPEAT_SIGNATURE_FIELDS,
    detect_repeat_billing_candidates,
)
from app.analytics.similar_claim_pattern import (
    BASE_SIGNATURE_FIELDS,
    COMPLETE_SIGNATURE_FIELDS,
    detect_similar_claim_patterns,
)
from fixtures.synthetic_claims import synthetic_claims_copy


def _group_by_cases(result):
    return {tuple(group["case_ids"]): group for group in result["candidate_groups"]}


def test_repeat_finds_repeat_and_possible_legitimate_pair_only():
    result = detect_repeat_billing_candidates(synthetic_claims_copy())
    groups = _group_by_cases(result)

    assert result["indicator"] == "repeat_billing_candidate"
    assert tuple(["syn-repeat-001", "syn-repeat-002"]) in groups
    assert tuple(["syn-routine-001", "syn-routine-002"]) in groups
    assert ("syn-normal-001",) not in groups
    assert ("syn-near-001", "syn-near-002") not in groups
    assert groups[("syn-repeat-001", "syn-repeat-002")]["candidate_record_count"] == 2
    assert groups[("syn-repeat-001", "syn-repeat-002")]["matched_attributes"] == list(REPEAT_SIGNATURE_FIELDS)
    assert all("bukti" in group["reason"].lower() for group in groups.values())


def test_similar_patterns_require_distinct_participants_and_keep_modes_separate():
    result = detect_similar_claim_patterns(synthetic_claims_copy())

    assert result["indicator"] == "similar_claim_pattern_candidate"
    assert len(result["candidate_groups"]) == 1
    group = result["candidate_groups"][0]
    assert group["case_ids"] == ["syn-pattern-001", "syn-pattern-002", "syn-pattern-003"]
    assert group["candidate_record_count"] == 3
    assert group["distinct_participant_count"] == 3
    assert group["mode"] == "complete"
    assert group["matched_attributes"] == list(COMPLETE_SIGNATURE_FIELDS)
    assert "syn-normal-001" not in group["case_ids"]
    assert "syn-repeat-001" not in group["case_ids"]
    assert "syn-near-001" not in group["case_ids"]
    assert "syn-near-002" not in group["case_ids"]
    assert "syn-routine-001" not in group["case_ids"]


def test_required_missing_values_are_ineligible_and_not_a_shared_signature():
    records = [
        {
            "case_id": "syn-missing-a",
            "participant_token": "synthetic-person-a",
            "service_date": "2025-01-14",
            "province_code": "SYN-P1",
            "municipality_code": "SYN-C1",
            "facility_ownership": "public",
            "facility_type": "general",
            "facility_class": "class-a",
            "admission_diagnosis": "SYN-DX-10",
            "primary_diagnosis": " ",
            "claim_group": "SYN-CBG-01",
            "procedure_code": "",
            "billed_amount": "125000",
        },
        {
            "case_id": "syn-missing-b",
            "participant_token": "synthetic-person-b",
            "service_date": "2025-01-14",
            "province_code": "SYN-P1",
            "municipality_code": "SYN-C1",
            "facility_ownership": "public",
            "facility_type": "general",
            "facility_class": "class-a",
            "admission_diagnosis": "SYN-DX-10",
            "primary_diagnosis": None,
            "claim_group": "SYN-CBG-01",
            "procedure_code": None,
            "billed_amount": "125000.00",
        },
    ]

    repeat = detect_repeat_billing_candidates(records)
    similar = detect_similar_claim_patterns(records)
    assert repeat["candidate_groups"] == []
    assert all(
        {"procedure_code", "primary_diagnosis"}.issubset(row["missing_attributes"])
        for row in repeat["ineligible_cases"]
    )
    assert similar["candidate_groups"] == []
    assert all("primary_diagnosis" in row["missing_attributes"] for row in similar["ineligible_cases"])


def test_partial_similar_pattern_requires_two_distinct_people():
    records = synthetic_claims_copy()
    partial = [
        {**row, "procedure_code": " "}
        for row in records
        if row["case_id"] in {"syn-pattern-001", "syn-pattern-002"}
    ]
    group = detect_similar_claim_patterns(partial)["candidate_groups"][0]
    assert group["mode"] == "procedure_missing"
    assert group["matched_attributes"] == list(BASE_SIGNATURE_FIELDS)
    assert group["distinct_participant_count"] == 2
    assert "lebih rentan false positive" in " ".join(group["limitations"])


def test_results_explain_matches_without_exposing_tokens_or_fraud_conclusions():
    records = synthetic_claims_copy()
    result = {
        "repeat": detect_repeat_billing_candidates(records),
        "similar": detect_similar_claim_patterns(records),
    }
    serialized = json.dumps(result, sort_keys=True)

    assert "synthetic-person-" not in serialized
    assert "synthetic-only-post-verification-value" not in serialized
    assert "FKL48" not in serialized
    for detection in result.values():
        for group in detection["candidate_groups"]:
            explanation = (group["reason"] + " " + " ".join(group["limitations"])).lower()
            assert "bukan bukti" in explanation
            assert group["matched_attributes"]
            assert group["candidate_record_count"] >= 2


def test_input_is_not_mutated_and_results_are_deterministic_under_row_reordering():
    records = synthetic_claims_copy()
    before = deepcopy(records)
    reversed_records = list(reversed(records))

    repeat_first = detect_repeat_billing_candidates(records)
    repeat_second = detect_repeat_billing_candidates(reversed_records)
    similar_first = detect_similar_claim_patterns(records)
    similar_second = detect_similar_claim_patterns(reversed_records)

    assert records == before
    assert repeat_first == repeat_second
    assert similar_first == similar_second


def test_signature_normalization_is_consistent_for_dates_amounts_and_whitespace():
    first = synthetic_claims_copy()[0]
    second = deepcopy(first)
    first["case_id"] = "syn-normalized-a"
    second["case_id"] = "syn-normalized-b"
    first["service_date"] = date(2025, 1, 14)
    second["service_date"] = "2025-01-14T18:30:00"
    first["billed_amount"] = Decimal("125000.0")
    second["billed_amount"] = "125000.00"
    first["primary_diagnosis"] = " SYN-DX-NORMAL "

    result = detect_repeat_billing_candidates([first, second])
    assert result["candidate_groups"][0]["case_ids"] == [
        "syn-normalized-a",
        "syn-normalized-b",
    ]


def test_invalid_required_values_are_reported_without_echoing_input_values():
    records = synthetic_claims_copy()
    invalid = next(row for row in records if row["case_id"] == "syn-invalid-001")
    invalid["billed_amount"] = "definitely-not-an-amount"
    result = detect_repeat_billing_candidates(records)
    excluded = next(row for row in result["ineligible_cases"] if row["case_id"] == "syn-invalid-001")

    assert "service_date" in excluded["missing_attributes"]
    assert "billed_amount" in excluded["missing_attributes"]
    assert "definitely-not-an-amount" not in json.dumps(result)


def test_case_id_must_be_application_generated_and_separate_from_participant_token():
    record = synthetic_claims_copy()[0]
    record["case_id"] = "synthetic-person-normal"
    with pytest.raises(ValueError, match="ID aplikasi"):
        detect_repeat_billing_candidates([record])

    record["case_id"] = "case_synthetic_normal"
    record["participant_token"] = " case_synthetic_normal "
    with pytest.raises(ValueError, match="terpisah dari token peserta"):
        detect_similar_claim_patterns([record])
