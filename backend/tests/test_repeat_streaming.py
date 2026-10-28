"""Whole-file streaming reconciliation matches the in-memory definitions (synthetic only)."""

import json
import random

import pytest

from app.analytics.repeat_definitions import LEGACY_SCRIPT_REPEAT_SERVICE, REPEAT_SERVICE_V1, summarize_repeat_patterns
from scripts.fkrtl_repeat_streaming import APP_DETECTOR, PARTIAL_WITHOUT_PROCEDURE, run_streaming_reconciliation


def _row(index, participant, *, day="2024-03-04", proc="P1", amount="100", municipality="1101", month_day=None):
    return {
        "case_id": f"case_{index:04d}", "participant_token": participant,
        "service_date": month_day or day, "primary_diagnosis": "A01", "claim_group": "G1", "procedure_code": proc,
        "province_code": "11", "municipality_code": municipality, "facility_ownership": "1", "facility_type": "2",
        "facility_class": "3", "admission_diagnosis": "A01", "provider_billed_amount_unverified": amount,
    }


def _records():
    rows = [
        _row(1, "p1"), _row(2, "p1"),                                         # identical: core + app
        _row(3, "p2"), _row(4, "p2", municipality="9999"),                    # core only: differs on FKL06
        _row(5, "p3", amount="100"), _row(6, "p3", amount="300"),             # core + app, differing FKL47
        _row(7, "p4", proc=None), _row(8, "p4", proc=None),                   # blank FKL30: partial/legacy only
        _row(9, "p5", proc="P1"), _row(10, "p5", proc="P2"),                  # partial only, FKL30 present but differs
        _row(11, "p6", month_day="2024-07-01"), _row(12, "p6", month_day="2024-07-01"),  # another month
        _row(13, "p7"),                                                       # singleton
    ]
    return rows


def _chunked(records, size):
    return lambda: (records[start:start + size] for start in range(0, len(records), size))


@pytest.mark.parametrize("size", [1, 4, 100])
def test_streaming_counts_match_in_memory_definitions(size):
    records = _records()
    report = run_streaming_reconciliation(_chunked(records, size))
    for definition in (REPEAT_SERVICE_V1, LEGACY_SCRIPT_REPEAT_SERVICE):
        expected = summarize_repeat_patterns(records, definition)
        got = report["definitions"][definition.name]
        assert (got["groups"], got["rows_in_groups"], got["extra_rows"]) == (
            expected["groups"], expected["rows_in_groups"], expected["extra_rows"])
        assert got["rows_not_assessable"] == expected["ineligible_rows"]
    core_subset = report["definitions"][REPEAT_SERVICE_V1.name]["same_fkl47_subset_exploratory"]
    expected_subset = summarize_repeat_patterns(records, REPEAT_SERVICE_V1)["same_amount_subset"]
    assert (core_subset["groups"], core_subset["key_groups_with_differing_amounts"]) == (
        expected_subset["groups"], expected_subset["key_groups_with_differing_amounts"])


def test_definitions_and_overlap_on_a_known_fixture():
    report = run_streaming_reconciliation(_chunked(_records(), 3))
    core = report["definitions"][REPEAT_SERVICE_V1.name]
    app = report["definitions"][APP_DETECTOR.name]
    partial = report["definitions"][PARTIAL_WITHOUT_PROCEDURE.name]
    assert (core["groups"], app["groups"], partial["groups"]) == (4, 3, 6)
    assert core["groups_involving_blank_fkl30"] == 0 and partial["groups_involving_blank_fkl30"] == 1
    assert core["by_admission_month"]["2024-07"] == {"groups": 1, "rows_in_groups": 2, "extra_rows": 1}
    overlap = report["overlap"]["core_vs_app_detector"]
    assert overlap["app_groups_inside_a_core_group"] == 3  # by construction: app key extends the core key
    assert overlap["core_groups_without_any_app_group"] == 1
    assert overlap["core_groups_not_reproduced_by_reason"] == {"differs_on_municipality_code": 1}
    partial_overlap = report["overlap"]["partial_without_fkl30_vs_core"]
    assert partial_overlap["partial_groups_involving_blank_fkl30"] == 1
    assert partial_overlap["partial_groups_with_all_fkl30_present_but_differing"] == 1


def test_streaming_report_is_deterministic_and_identifier_free():
    records = _records()
    shuffled = records[:]
    random.Random(5).shuffle(shuffled)
    first = run_streaming_reconciliation(_chunked(records, 4))
    second = run_streaming_reconciliation(_chunked(shuffled, 2))
    first.pop("timing_seconds"); second.pop("timing_seconds")
    assert first == second
    text = json.dumps(first)
    assert "case_" not in text and "p1" not in text and "A01" not in text
