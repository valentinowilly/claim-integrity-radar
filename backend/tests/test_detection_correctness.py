"""Regression tests for detector correctness fixes (Sprint 1)."""

from datetime import date

import pytest

from app.analytics.detector_utils import date_value, text_value
from app.analytics.length_of_stay import detect_length_of_stay_outliers
from app.analytics.normalization import MISSING_TEXT_VALUES, normalize_date, normalize_text
from app.analytics.risk_scoring import run_detector_suite, score_claims
from app.analytics.temporal_patterns import detect_temporal_patterns

TEMPORAL = "temporal_pattern_candidate"


def visit(case, day, **overrides):
    # A timestamp lets both temporal rules assess the record (without one it is unassessed).
    row = {"case_id": f"syn-{case}", "participant_token": "syn-participant-1", "facility_id": "syn-facility-1",
           "service_type": "physiotherapy", "service_date": day, "service_timestamp": f"{day}T09:00:00"}
    return {**row, **overrides}


def flagged_groups(rows):
    return [sorted(c["case_ids"]) for c in detect_temporal_patterns(rows)["candidates"]
            if c["pattern_type"] == "short_window_repeat"]


def coverage_state(rows, case_id):
    scored = score_claims(rows, run_detector_suite(rows, []))
    case = next(item for item in scored["cases"] if item["case_id"] == case_id)
    return next(item["status"] for item in case["indicator_coverage"] if item["indicator"] == TEMPORAL)


def test_a_later_visit_within_the_window_of_the_previous_one_is_flagged():
    # Before: the window was anchored on the first visit, so day 4 (one day after day 3)
    # was left out and reported as assessed and not flagged.
    rows = [visit("d0", "2024-01-01"), visit("d3", "2024-01-04"), visit("d4", "2024-01-05")]
    assert flagged_groups(rows) == [["syn-d0", "syn-d3", "syn-d4"]]
    assert coverage_state(rows, "syn-d4") == "triggered"


def test_a_run_of_visits_is_one_group_and_a_distant_visit_stays_unflagged():
    # Before: four visits one to three days apart were split into two groups.
    rows = [visit("a", "2024-01-01"), visit("b", "2024-01-04"), visit("c", "2024-01-05"),
            visit("d", "2024-01-06"), visit("far", "2024-02-01")]
    assert flagged_groups(rows) == [["syn-a", "syn-b", "syn-c", "syn-d"]]
    assert coverage_state(rows, "syn-far") == "not_triggered"


def test_visits_further_apart_than_the_window_are_not_chained():
    rows = [visit("a", "2024-01-01"), visit("b", "2024-01-05"), visit("c", "2024-01-09")]
    assert flagged_groups(rows) == []


@pytest.mark.parametrize("sentinel", sorted(MISSING_TEXT_VALUES - {""}) + ["  NA  ", "NULL", "None"])
def test_detector_text_values_treat_missing_sentinels_like_the_repeat_detector(sentinel):
    assert text_value(sentinel) is None
    assert normalize_text(sentinel) is None


def test_missing_service_type_sentinels_no_longer_match_each_other():
    # Before: two visits with service_type "NA" formed a short-window repeat as if
    # "NA" were the same service; now the prerequisite is missing and both are unassessed.
    rows = [visit("x", "2024-01-01", service_type="NA"), visit("y", "2024-01-02", service_type="NA")]
    result = detect_temporal_patterns(rows)
    assert result["candidates"] == []
    assert sorted(item["case_id"] for item in result["unassessed_cases"]) == ["syn-x", "syn-y"]
    assert coverage_state(rows, "syn-x") == "not_assessed"


@pytest.mark.parametrize("raw", ["2024-01-011", "2024-01-01xyz", "2024-13-01", "NA"])
def test_malformed_dates_are_missing_not_truncated(raw):
    # Before: the first ten characters were parsed, so "2024-01-011" became 2024-01-01.
    assert date_value(raw) is None and normalize_date(raw) is None


def test_valid_dates_and_timestamps_are_still_accepted():
    assert date_value("2024-01-05") == date(2024, 1, 5)
    assert date_value("2024-01-05T10:30:00") == date(2024, 1, 5)
    assert date_value("2024-01-05T10:30:00Z") == date(2024, 1, 5)


def test_malformed_or_sentinel_discharge_dates_make_duration_unassessed_with_the_right_reason():
    base = {"participant_token": "syn-participant-1", "service_date": "2024-01-01", "claim_group": "G1", "care_class": "3"}
    rows = [{**base, "case_id": "syn-bad", "discharge_date": "2024-01-011"},
            {**base, "case_id": "syn-na", "discharge_date": "NA"}]
    result = detect_length_of_stay_outliers(rows)
    assert result["candidates"] == [] and result["assessed_count"] == 0
    # Before: "2024-01-011" was read as 2024-01-01 (a 0-day stay) and "NA" was an invalid date.
    assert result["unassessed_reason_counts"]["invalid_date"] == 1
    assert result["unassessed_reason_counts"]["missing_date"] == 1
