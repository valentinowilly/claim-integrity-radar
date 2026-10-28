"""Regression tests: unassessed vs not-applicable vs negative findings, and rule-index meaning.

All records are small synthetic fixtures; no BPJS data is used.
"""

import pytest

from app.analytics.near_duplicate_claims import detect_near_duplicate_claims
from app.analytics.risk_scoring import DETECTOR_ORDER, RiskScoringConfig, score_claims
from app.analytics.temporal_patterns import detect_temporal_patterns
from app.data_sources.providers import FeatureDataset
from app.services.analytics import build_analytics_snapshot_from_dataset
from app.services.provider_orchestrator import execute_provider_snapshot
from tests.test_fkrtl_local_source import configured  # noqa: F401  (pytest fixture)


FKRTL_NOT_APPLICABLE = {
    "similar_claim_pattern_candidate": "needs a verified pre-verification amount",
    "synthetic_capacity_candidate": "needs facility identity, service units and capacity",
    "temporal_pattern_candidate": "needs facility identity, service type and timestamps",
    "supporting_evidence_completeness_candidate": "needs an evidence inventory",
}


def _row(index, **overrides):
    row = {
        "case_id": f"case_{index:04d}", "participant_token": f"p{index}", "service_date": "2024-03-04",
        "discharge_date": "2024-03-06", "province_code": "11", "municipality_code": "1101",
        "facility_ownership": "1", "facility_type": "2", "facility_class": "3",
        "admission_diagnosis": "A01", "primary_diagnosis": "A01", "claim_group": "G1", "procedure_code": "P1",
        "billed_amount": None, "facility_id": None, "service_type": None, "service_units": None,
        "service_timestamp": None,
    }
    row.update(overrides)
    return row


def _state(scored, case_id, indicator):
    case = next(item for item in scored["cases"] if item["case_id"] == case_id)
    return next(item["status"] for item in case["indicator_coverage"] if item["indicator"] == indicator)


def _fkrtl_snapshot(records):
    return build_analytics_snapshot_from_dataset(FeatureDataset(records=records, facilities=(), source_metadata={
        "kind": "local", "label": "fixture", "repeat_signature_profile": "repeat-visit-exact-no-amount-v1",
        "not_applicable_detectors": FKRTL_NOT_APPLICABLE,
    }))


# --- temporal ---------------------------------------------------------------

def test_temporal_record_missing_facility_or_service_type_is_unassessed_not_negative():
    records = [
        _row(1, participant_token="p1", service_timestamp="2024-03-04T08:00:00"),
        _row(2, participant_token="p1", service_date="2024-03-05", service_timestamp="2024-03-05T08:00:00",
             facility_id="F1"),
    ]
    result = detect_temporal_patterns(records)
    unassessed = {item["case_id"] for item in result["unassessed_cases"]}
    assert unassessed == {"case_0001", "case_0002"}
    scored = score_claims(records, {"temporal_pattern_candidate": result})
    assert _state(scored, "case_0001", "temporal_pattern_candidate") == "not_assessed"
    coverage = next(item for item in scored["detector_coverage"] if item["indicator"] == "temporal_pattern_candidate")
    assert coverage["assessed_case_count"] == 0 and coverage["not_assessed_case_count"] == 2


def test_temporal_record_with_all_prerequisites_remains_an_assessed_negative():
    records = [_row(1, participant_token="p1", facility_id="F1", service_type="S",
                    service_timestamp="2024-03-04T08:00:00")]
    result = detect_temporal_patterns(records)
    assert result["unassessed_cases"] == [] and result["unassessed_time_cases"] == []
    scored = score_claims(records, {"temporal_pattern_candidate": result})
    assert _state(scored, "case_0001", "temporal_pattern_candidate") == "not_triggered"


# --- near-duplicate ---------------------------------------------------------

def test_near_duplicate_record_without_any_complete_blocking_key_is_unassessed():
    records = [_row(1), _row(2), _row(3, service_date=None)]
    result = detect_near_duplicate_claims(records)
    assert "case_0003" in result["unassessed_case_ids"]
    scored = score_claims(records, {"near_duplicate_claim_candidate": result})
    assert _state(scored, "case_0003", "near_duplicate_claim_candidate") == "not_assessed"
    assert _state(scored, "case_0001", "near_duplicate_claim_candidate") == "triggered"


def test_near_duplicate_record_with_too_few_comparable_attributes_is_ineligible():
    # 10 comparable fields without an amount; two missing leaves 8 < min 9.
    records = [_row(1), _row(2), _row(3, procedure_code=None, admission_diagnosis=None)]
    result = detect_near_duplicate_claims(records)
    assert "case_0003" in {item["case_id"] for item in result["ineligible_cases"]}
    scored = score_claims(records, {"near_duplicate_claim_candidate": result})
    assert _state(scored, "case_0003", "near_duplicate_claim_candidate") == "not_assessed"


def test_near_duplicate_complete_singleton_remains_an_assessed_negative():
    records = [_row(1), _row(2, municipality_code="9999", primary_diagnosis="Z99", claim_group="G9",
                                admission_diagnosis="Z98", province_code="99")]
    result = detect_near_duplicate_claims(records)
    assert result["unassessed_case_ids"] == [] and result["ineligible_cases"] == []
    scored = score_claims(records, {"near_duplicate_claim_candidate": result})
    assert _state(scored, "case_0001", "near_duplicate_claim_candidate") == "not_triggered"


# --- source-level applicability and run-level reconciliation ----------------

def test_declared_unsupported_detectors_are_not_applicable_not_incomplete():
    records = [_row(1, participant_token="p1"), _row(2, participant_token="p1")] + [
        _row(index, primary_diagnosis=f"D{index}", claim_group=f"G{index}", municipality_code=f"M{index}")
        for index in range(3, 12)
    ]
    snapshot = _fkrtl_snapshot(records)
    coverage = {item["indicator"]: item for item in snapshot["indicator_coverage"]}
    for indicator in FKRTL_NOT_APPLICABLE:
        item = coverage[indicator]
        assert item["status"] == "not_applicable"
        assert (item["records_assessed"], item["records_unassessed"], item["records_not_applicable"]) == (0, 0, 11)
        assert any(FKRTL_NOT_APPLICABLE[indicator] in text for text in item["limitations"])
    assert coverage["repeat_billing_candidate"]["status"] == "complete"
    assert snapshot["execution_status"] == "completed"


def test_unknown_not_applicable_declaration_is_rejected():
    with pytest.raises(ValueError):
        build_analytics_snapshot_from_dataset(FeatureDataset(records=[_row(1)], facilities=(), source_metadata={
            "kind": "local", "label": "fixture", "not_applicable_detectors": {"made_up_detector": "x"},
        }))


def test_coverage_counts_reconcile_with_run_status():
    records = [_row(1), _row(2), _row(3, service_date=None)]
    snapshot = _fkrtl_snapshot(records)
    statuses = {item["status"] for item in snapshot["indicator_coverage"]}
    for item in snapshot["indicator_coverage"]:
        assert item["records_assessed"] + item["records_unassessed"] + item["records_not_applicable"] == 3
        assert (item["status"] == "complete") == (item["records_unassessed"] == 0 and item["records_assessed"] > 0
                                                 and not item["search_truncated"])
    assert statuses & {"partial"}
    assert snapshot["execution_status"] == "partial"


def test_run_with_every_detector_not_applicable_is_not_reported_completed():
    every = {indicator: "unsupported in fixture" for indicator in DETECTOR_ORDER}
    snapshot = build_analytics_snapshot_from_dataset(FeatureDataset(records=[_row(1)], facilities=(), source_metadata={
        "kind": "local", "label": "fixture", "not_applicable_detectors": every,
    }))
    assert all(item["status"] == "not_applicable" for item in snapshot["indicator_coverage"])
    assert snapshot["execution_status"] != "completed"


# --- rule risk index meaning -----------------------------------------------

def test_rule_index_with_too_few_assessed_checks_is_not_reported_as_a_number():
    records = [_row(1, participant_token="p1"), _row(2, participant_token="p1")] + [
        _row(index, primary_diagnosis=f"D{index}", claim_group=f"G{index}", municipality_code=f"M{index}")
        for index in range(3, 12)
    ]

    class _Provider:
        def load(self):
            return FeatureDataset(records=records, facilities=(), source_metadata={
                "kind": "local", "label": "fixture",
                "repeat_signature_profile": "repeat-visit-exact-no-amount-v1",
                "not_applicable_detectors": FKRTL_NOT_APPLICABLE,
            })

    _, snapshot = execute_provider_snapshot(_Provider())
    case = snapshot["cases"]["case_0001"]
    assert case["indicators"] == ["repeat_billing_candidate"]
    assert case["risk_score"] is None
    assert case["score_status"] == "insufficient_assessed_indicators"
    assert case["score_basis"] == {"assessed_indicator_count": 2, "minimum_assessed_indicators": 3}
    # Policy v3: the withheld index does not hide the finding; one specific rule finding is medium risk.
    assert snapshot["action_policy"]["cases"]["case_0001"]["lane"] == "yellow"
    assert snapshot["risk_scoring"]["insufficient_indicator_case_count"] >= 2
    assert snapshot["records_eligible"] == 0


def test_configured_fkrtl_run_reports_unsupported_checks_as_not_applicable(tmp_path, configured):
    from tests.test_analysis_runs import call, operator_session, setup, verifier_session
    from tests.test_fkrtl_local_source import _create_fkrtl_run

    app, _, users = setup(tmp_path)
    run = _create_fkrtl_run(app, operator_session(app, users)).json()["run"]
    result = call(app, "GET", f"/api/v1/runs/{run['run_id']}", cookies=verifier_session(app, users)).json()["result"]
    coverage = {item["indicator"]: item for item in result["indicator_coverage"]}
    for indicator in FKRTL_NOT_APPLICABLE:
        assert coverage[indicator]["status"] == "not_applicable"
        assert coverage[indicator]["records_unassessed"] == 0
    for item in result["indicator_coverage"]:
        assert item["records_assessed"] + item["records_unassessed"] + item["records_not_applicable"] == 4
    for case in result["cases"].values():
        # Five checks apply to FKRTL (repeat, near-duplicate and the three clinical checks), so the index
        # is derived once at least three of them assessed the claim.
        assessed = len(case["assessed_indicators"])
        if assessed >= 3:
            assert case["risk_score"] == round(len(case["indicators"]) / assessed, 6)
        else:
            assert case["risk_score"] is None and case["score_status"] == "insufficient_assessed_indicators"
    assert result["risk_scoring"]["minimum_assessed_indicators"] == 3


def test_rule_index_minimum_is_explicit_configuration_and_validated():
    assert RiskScoringConfig().min_assessed_indicators == 3
    with pytest.raises(ValueError):
        RiskScoringConfig(min_assessed_indicators=0)
