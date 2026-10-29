"""Repeated-service pattern is reported as a pattern, never as established Repeat Billing.

All records and `.dta` files here are generated synthetic fixtures.
"""

import json

import pytest

from app.analytics.repeat_billing import SIGNATURE_PROFILES, detect_repeat_billing_candidates
from app.analytics.risk_scoring import run_detector_suite, score_claims
from app.data_sources.bpjs_fkrtl_adapter import FkrtlMappingError, adapt_fkrtl_rows
from tests.test_analysis_runs import call, operator_session, setup, verifier_session
from tests.test_fkrtl_local_source import KEY, _create_fkrtl_run, _row, _write_fixture
from tests.test_repeat_service_profile import CORE, _record

REPEAT = "repeat_billing_candidate"
BILLING_LIMITATION = "Sumber tidak memuat status penagihan atau pembayaran per kunjungan"


def _coverage(records, case_id):
    scored = score_claims(records, run_detector_suite(records, [], repeat_signature_fields=CORE))
    case = next(item for item in scored["cases"] if item["case_id"] == case_id)
    return next(item["status"] for item in case["indicator_coverage"] if item["indicator"] == REPEAT), case


@pytest.mark.parametrize("profile", sorted(SIGNATURE_PROFILES))
def test_every_profile_reports_a_pattern_and_never_established_repeat_billing(profile):
    records = [_record("case_1", billed_amount="10"), _record("case_2", billed_amount="10")]
    result = detect_repeat_billing_candidates(records, SIGNATURE_PROFILES[profile])
    assert result["interpretation"] == {
        "signal_type": "repeated_service_pattern", "repeat_billing": "not_established",
        "billing_status_evidence": "not_available",
    }
    [group] = result["candidate_groups"]
    assert group["interpretation"] == "repeated_service_pattern"
    assert group["billing_status_evidence"] == "not_available"
    assert any(BILLING_LIMITATION in text for text in group["limitations"])
    assert "bukan bukti tagihan ganda" in group["reason"]


def test_blank_procedure_is_unassessed_not_a_matching_value_or_a_negative():
    # Two visits that differ only by a blank procedure must not form a pattern, and
    # neither may be reported as assessed and not flagged.
    records = [_record("case_1", procedure_code=""), _record("case_2", procedure_code="")]
    result = detect_repeat_billing_candidates(records, CORE)
    assert result["candidate_groups"] == []
    assert [item["missing_attributes"] for item in result["ineligible_cases"]] == [["procedure_code"]] * 2
    state, case = _coverage(records, "case_1")
    assert state == "not_assessed" and REPEAT in case["not_assessed_indicators"]


def test_insufficient_key_data_is_unassessed_while_a_complete_pair_is_flagged():
    records = [_record("case_1"), _record("case_2"), _record("case_3", claim_group=None)]
    assert _coverage(records, "case_1")[0] == "triggered"
    assert _coverage(records, "case_3")[0] == "not_assessed"
    single = [_record("case_1"), _record("case_4", service_date="2024-03-05")]
    assert _coverage(single, "case_1")[0] == "not_triggered"


def test_a_visit_repeated_by_a_one_to_many_join_is_rejected_not_counted_twice():
    # A secondary-diagnosis join repeats the visit row; the adapter must refuse the batch
    # instead of turning one visit into a two-record repeated-service pattern.
    joined = [_row(), _row()]
    with pytest.raises(FkrtlMappingError, match="Duplicate visit references"):
        adapt_fkrtl_rows(joined, case_reference_secret=bytes.fromhex(KEY))
    records, _ = adapt_fkrtl_rows([_row(), _row(FKL02="synvisit-a2")], case_reference_secret=bytes.fromhex(KEY))
    assert len({record["case_id"] for record in records}) == 2


def test_fkrtl_run_api_carries_the_interpretation_and_withholds_scores(tmp_path, monkeypatch):
    rows = [_row(), _row(FKL02="synvisit-a2"), _row(FKL02="synvisit-a3", FKL30="")]
    path = _write_fixture(tmp_path, rows)
    monkeypatch.setenv("BPJS_FKRTL_SAMPLE_PATH", str(path))
    monkeypatch.setenv("CIR_FKRTL_PSEUDONYM_KEY", KEY)
    monkeypatch.setenv("BPJS_FKRTL_DATE_FROM", "2024-03-01")
    monkeypatch.setenv("BPJS_FKRTL_DATE_TO", "2024-03-31")
    monkeypatch.delenv("BPJS_FKRTL_MAX_ROWS", raising=False)
    app, _batch_db, users = setup(tmp_path)
    created = _create_fkrtl_run(app, operator_session(app, users))
    assert created.status_code == 201, created.text
    run_id = created.json()["run"]["run_id"]
    result = call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier_session(app, users)).json()["result"]

    summary = next(item for item in result["indicators"] if item["code"] == REPEAT)
    assert summary["name"] == "Repeated-service pattern (Repeat Billing screening)"
    assert summary["interpretation"]["repeat_billing"] == "not_established"
    assert summary["eligible_count"] == 2 and summary["unassessed_count"] == 1
    assert any(BILLING_LIMITATION in text for text in summary["limitations"])

    flagged = [case for case in result["cases"].values() if REPEAT in case["indicators"]]
    assert len(flagged) == 2
    for case in flagged:
        reason = next(item for item in case["reasons"] if item["indicator"] == REPEAT)
        assert reason["supporting_values"]["interpretation"] == "repeated_service_pattern"
        assert reason["supporting_values"]["billing_status_evidence"] == "not_available"
        # The rule index covers only the checks that assessed this claim.
        assessed = len(case["assessed_indicators"])
        assert case["risk_score"] == (round(len(case["indicators"]) / assessed, 6) if assessed >= 3 else None)
        # Too few checks apply for a rule index; v4 lanes the flagged claim by its evidence: specific
        # rule findings only; the similar-claim screen alone stays green.
        lane = result["action_policy"]["cases"][case["case_id"]]
        assert lane["policy_version"] == "action-policy-evidence-v4-provisional"
        specific = [code for code in case["indicators"] if code != "near_duplicate_claim_candidate"]
        percentile = case["ml_anomaly"].get("reference_percentile", case["ml_anomaly"].get("anomaly_percentile"))
        expected = ("red" if len(specific) >= 2 or (percentile >= 0.95 and specific)
                    else "yellow" if specific else "green")
        assert lane["lane"] == expected
    assert "confirmed" not in json.dumps(summary).lower()
