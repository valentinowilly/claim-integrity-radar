"""Temporal groups above the display limit keep complete internal membership (synthetic fixtures)."""

from datetime import date, timedelta
import json
import random

import pytest

from app.analytics.detector_utils import MEMBER_CASE_IDS
from app.analytics.risk_scoring import run_detector_suite, score_claims
from app.analytics.temporal_patterns import TemporalConfig, detect_temporal_patterns
from app.services.analytics import build_analytics_snapshot

TEMPORAL = "temporal_pattern_candidate"
DISPLAY_LIMIT = TemporalConfig().max_case_ids
PARTICIPANT = "syn-participant-chain"


def visit(case, day_offset, participant=PARTICIPANT, **overrides):
    day = date(2024, 1, 1) + timedelta(days=day_offset)
    row = {"case_id": f"syn-{case}", "participant_token": participant, "facility_id": "syn-facility-1",
           "service_type": "physiotherapy", "service_date": day.isoformat(),
           "service_timestamp": f"{day.isoformat()}T09:{len(case) % 60:02d}:00"}
    return {**row, **overrides}


def chain(size):
    # One visit per day: every visit is within the 3-day window of the previous one.
    return [visit(f"chain-{index:03d}", index) for index in range(size)]


def bystanders():
    # Assessable single visits of other participants (assessed negatives) and one record
    # without a facility (prerequisite missing, must stay unassessed).
    rows = [visit(f"single-{index}", index * 10, participant=f"syn-participant-{index}") for index in range(3)]
    rows.append(visit("no-facility", 2, participant="syn-participant-x", facility_id=None))
    return rows


def states(records, detector_results=None):
    results = detector_results or run_detector_suite(records, [])
    scored = score_claims(records, results)
    by_case = {
        case["case_id"]: next(item["status"] for item in case["indicator_coverage"] if item["indicator"] == TEMPORAL)
        for case in scored["cases"]
    }
    coverage = next(item for item in scored["detector_coverage"] if item["indicator"] == TEMPORAL)
    return by_case, coverage, scored


@pytest.mark.parametrize("size", [DISPLAY_LIMIT, DISPLAY_LIMIT + 5])
def test_every_member_is_flagged_and_bystanders_keep_their_assessment(size):
    records = chain(size) + bystanders()
    [candidate] = detect_temporal_patterns(records)["candidates"]
    assert candidate["case_count"] == size
    assert len(candidate["case_ids"]) == min(size, DISPLAY_LIMIT)
    assert candidate["case_ids_truncated"] is (size > DISPLAY_LIMIT)
    assert sorted(candidate[MEMBER_CASE_IDS]) == sorted(row["case_id"] for row in chain(size))

    by_case, coverage, _ = states(records)
    assert all(by_case[row["case_id"]] == "triggered" for row in chain(size))
    # Before: a group above the limit made every record "not_assessed" for temporal.
    assert all(by_case[f"syn-single-{index}"] == "not_triggered" for index in range(3))
    assert by_case["syn-no-facility"] == "not_assessed"
    assert coverage["triggered_case_count"] == size
    assert coverage["assessed_case_count"] == size + 3 and coverage["not_assessed_case_count"] == 1
    assert coverage["search_truncated"] is False and coverage["status"] == "partial"


def test_the_display_limit_does_not_change_any_assessment_or_score():
    records = chain(DISPLAY_LIMIT + 5) + bystanders()
    default = run_detector_suite(records, [])
    wide = {**default, TEMPORAL: detect_temporal_patterns(records, TemporalConfig(max_case_ids=500))}
    assert wide[TEMPORAL]["candidates"][0]["case_ids_truncated"] is False
    narrow_states, narrow_coverage, narrow_scored = states(records, default)
    wide_states, wide_coverage, wide_scored = states(records, wide)
    assert narrow_states == wide_states and narrow_coverage == wide_coverage
    assert [(case["case_id"], case["risk_score"], case["score_status"]) for case in narrow_scored["cases"]] == \
        [(case["case_id"], case["risk_score"], case["score_status"]) for case in wide_scored["cases"]]
    assert narrow_scored["partial_group_membership"] == []


def test_input_order_does_not_drop_members_of_a_chain():
    records = chain(DISPLAY_LIMIT + 7) + bystanders()
    shuffled = records[:]
    random.Random(7).shuffle(shuffled)
    first = detect_temporal_patterns(records)["candidates"]
    second = detect_temporal_patterns(shuffled)["candidates"]
    assert [sorted(item[MEMBER_CASE_IDS]) for item in first] == [sorted(item[MEMBER_CASE_IDS]) for item in second]
    assert states(records)[0] == states(shuffled)[0]


def test_snapshot_counts_once_and_exposes_neither_membership_nor_participants():
    records = chain(DISPLAY_LIMIT + 5) + bystanders()
    snapshot = build_analytics_snapshot(records)
    summary = next(item for item in snapshot["indicators"] if item["code"] == TEMPORAL)
    assert summary["candidate_count"] == DISPLAY_LIMIT + 5 and summary["candidate_group_count"] == 1
    assert summary["search_truncated"] is False
    assert summary["eligible_count"] + summary["unassessed_count"] + summary["not_applicable_count"] == len(records)
    flagged = [case for case in snapshot["cases"].values() if TEMPORAL in case["indicators"]] \
        if isinstance(snapshot["cases"], dict) else [case for case in snapshot["cases"] if TEMPORAL in case["indicators"]]
    assert len(flagged) == DISPLAY_LIMIT + 5
    for case in flagged:
        reasons = [item for item in case["reasons"] if item["indicator"] == TEMPORAL]
        assert len(reasons) == 1 and reasons[0]["supporting_values"]["case_count"] == DISPLAY_LIMIT + 5
    serialized = json.dumps(snapshot)
    assert MEMBER_CASE_IDS not in serialized
    assert "syn-participant" not in serialized


def test_small_groups_are_unchanged():
    records = [visit("a", 0), visit("b", 2), visit("c", 3), visit("far", 30)]
    [candidate] = detect_temporal_patterns(records)["candidates"]
    assert candidate["case_ids"] == candidate[MEMBER_CASE_IDS] == ["syn-a", "syn-b", "syn-c"]
    assert candidate["case_ids_truncated"] is False
    by_case, _, _ = states(records)
    assert [by_case[f"syn-{name}"] for name in ("a", "b", "c", "far")] == ["triggered"] * 3 + ["not_triggered"]
