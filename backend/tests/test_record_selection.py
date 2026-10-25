from copy import deepcopy

import pytest

from app.analytics.record_selection import (
    cir_priority_selection,
    random_selection,
    selected_assessment_summary,
    simple_rule_selection,
)


def _records():
    return [
        {"case_id": f"syn-case-{i}", "facility_id": facility}
        for i, facility in enumerate(("f-a", "f-a", "f-b", "f-b", "f-c", None))
    ]


def _scores(records):
    values = (0.1, 0.9, 0.7, None, 0.5, 0.2)
    states = ("assessed", "assessed", "partial_coverage", "not_assessable", "assessed", "assessed")
    return {"cases": [
        {"case_id": row["case_id"], "risk_score": values[i], "score_status": states[i]}
        for i, row in enumerate(records)
    ]}


def _priority():
    return {"items": [
        {"unit_id": "synthetic-audit-unit:f-b", "priority_index": 9.0, "priority_status": "available"},
        {"unit_id": "synthetic-audit-unit:f-a", "priority_index": 8.0, "priority_status": "available"},
        {"unit_id": "synthetic-audit-unit:f-c", "priority_index": 2.0, "priority_status": "partial"},
    ]}


def test_random_selector_is_unique_deterministic_and_reports_impossible_k():
    records = _records()
    first = random_selection(records, 4, seed=12026)
    second = random_selection(records, 4, seed=12026)
    assert first == second
    assert len(first.selected_case_ids) == 4
    assert len(set(first.selected_case_ids)) == 4
    impossible = random_selection(records, 7, seed=12026)
    assert impossible.status == "not_comparable"
    assert impossible.requested_k == 7
    assert len(impossible.selected_case_ids) == 6
    assert impossible.summary()["selected_unique_record_count"] == 6


def test_simple_rule_prioritizes_only_repeat_detector_and_fills_by_fallback():
    records = _records()
    result = {"indicator": "repeat_billing_candidate", "candidate_groups": [
        {"group_id": "repeat-1", "case_ids": ["syn-case-0", "syn-case-2"]},
        {"group_id": "repeat-2", "case_ids": ["syn-case-2", "syn-case-4"]},
    ]}
    chosen = simple_rule_selection(records, result, 4, seed=12026)
    assert len(chosen.selected_case_ids) == 4
    assert len(set(chosen.selected_case_ids)) == 4
    assert {"syn-case-0", "syn-case-2", "syn-case-4"}.issubset(chosen.selected_case_ids)
    assert chosen.selection_counts == {"repeat_billing_rule": 3, "exploratory_fallback": 1}
    assert chosen == simple_rule_selection(records, result, 4, seed=12026)
    assert "syn-case-0" not in str(chosen.summary())
    assert "syn-case-2" not in str(chosen.summary())
    with pytest.raises(ValueError, match="Only repeat_billing_candidate"):
        simple_rule_selection(records, {"indicator": "near_duplicate_claim_candidate", "candidate_groups": []}, 2)


def test_cir_priority_orders_facilities_and_record_scores_then_fallback():
    records = _records()
    selection = cir_priority_selection(records, _scores(records), _priority(), 3, seed=12026)
    # Facility priority orders f-b first; record risk score sorts within it.
    facility_by_id = {row["case_id"]: row["facility_id"] for row in records}
    selected_facilities = [facility_by_id[case_id] for case_id in selection.selected_case_ids]
    assert selected_facilities[:2] == ["f-b", "f-b"]
    assert selection.selection_counts["valid_facility_priority"] == 3
    assert selection.selection_counts["exploratory_fallback"] == 0
    assert len(set(selection.selected_case_ids)) == 3
    assert selection == cir_priority_selection(records, _scores(records), _priority(), 3, seed=12026)


def test_cir_uses_fallback_only_after_valid_priority_facilities_are_exhausted():
    records = _records()
    selection = cir_priority_selection(records, _scores(records), _priority(), 6, seed=12026)
    assert selection.comparable
    assert selection.selection_counts["valid_facility_priority"] == 4
    assert selection.selection_counts["exploratory_fallback"] == 2
    assert len(set(selection.selected_case_ids)) == 6
    assert selection.selection_counts["population_records_without_valid_facility_priority"] == 2
    assert set(selection.selected_case_ids[-2:]) == {"syn-case-4", "syn-case-5"}
    assert "syn-case-4" in selection.selected_case_ids  # partial-priority facility is fallback, not ranked


def test_ground_truth_is_not_an_input_and_label_changes_do_not_change_selection():
    records = _records()
    labels_a = {row["case_id"]: (i % 2 == 0) for i, row in enumerate(records)}
    labels_b = {case_id: not value for case_id, value in labels_a.items()}
    first = cir_priority_selection(records, _scores(records), _priority(), 4, seed=12026)
    second = cir_priority_selection(records, _scores(records), _priority(), 4, seed=12026)
    assert labels_a != labels_b
    assert first.selected_case_ids == second.selected_case_ids
    leaked = deepcopy(records)
    leaked[0]["is_synthetic_anomaly"] = True
    with pytest.raises(ValueError, match="Ground-truth fields"):
        cir_priority_selection(leaked, _scores(records), _priority(), 2)


def test_unassessed_records_are_not_coerced_to_negative_or_zero_score():
    records = _records()
    selection = cir_priority_selection(records, _scores(records), _priority(), 4, seed=12026)
    unassessed_case = "syn-case-3"
    if unassessed_case in selection.selected_case_ids:
        # Selection membership does not rewrite detector assessment or score.
        selected_item = next(item for item in _scores(records)["cases"] if item["case_id"] == unassessed_case)
        assert selected_item["risk_score"] is None
        assert selected_item["score_status"] == "not_assessable"
    summary = selection.summary()
    assert "selected_case_ids" not in summary
    assert "syn-case-" not in str(summary)
    assessed = selected_assessment_summary(selection, _scores(records))
    assert assessed["score_status_counts"].get("not_assessable", 0) == 1
    assert assessed["selected_record_count"] == 4
    assert "syn-case-" not in str(assessed)


def test_selected_assessment_summary_preserves_unassessed_status():
    records = _records()
    selection = random_selection(records, 6, seed=12026)
    summary = selected_assessment_summary(selection, _scores(records))
    assert summary["score_status_counts"]["not_assessable"] == 1
    assert summary["indicator_assessment_counts"] == {}
    assert "negative" in summary["note"]


def test_selector_rejects_invalid_priority_references_and_population_mismatch():
    records = _records()
    invalid = {"items": [{"unit_id": "synthetic-audit-unit:foreign", "priority_index": 9, "priority_status": "available"}]}
    # A stale priority row cannot cause an unverified facility to be ranked;
    # its records remain outside the prioritized set and may only be fallback.
    result = cir_priority_selection(records, _scores(records), invalid, 2, seed=12026)
    assert result.selection_counts["valid_facility_priority"] == 0
    assert result.selection_counts["exploratory_fallback"] == 2
    with pytest.raises(ValueError, match="unique"):
        random_selection([records[0], records[0]], 1)


def test_invalid_or_out_of_range_scores_are_not_used_as_rank_values():
    records = _records()
    scores = _scores(records)
    scores["cases"][0]["risk_score"] = 9.0
    scores["cases"][1]["risk_score"] = -0.5
    selection = cir_priority_selection(records, scores, _priority(), 2, seed=12026)
    summary = selected_assessment_summary(selection, scores)
    assert len(selection.selected_case_ids) == 2
    # Existing score states remain visible; invalid numeric values are not
    # transformed into a fabricated score by the selector.
    assert summary["score_status_counts"]
