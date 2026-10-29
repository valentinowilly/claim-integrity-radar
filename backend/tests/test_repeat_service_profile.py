"""Primary FKRTL repeat profile ``repeat-service-v1``: core key gates, context only informs.

All records and `.dta` files here are generated synthetic fixtures.
"""

from datetime import datetime
import json

import pytest

from app.analytics.ml_anomaly import build_ml_anomaly_ranking
from app.analytics.repeat_billing import (
    REPEAT_CONTEXT_FIELDS, REPEAT_SERVICE_PROFILE, SIGNATURE_FIELDS, SIGNATURE_PROFILES,
    detect_repeat_billing_candidates,
)
from app.analytics.repeat_definitions import REPEAT_SERVICE_KEY
from app.data_sources.bpjs_fkrtl_adapter import FKRTL_SOURCE_COLUMNS, adapt_fkrtl_rows
from app.data_sources.providers import CANONICAL_FEATURE_FIELDS
from app.services.analytics import build_analytics_snapshot
from scripts.fkrtl_dta_provider import FKRTL_REPEAT_SIGNATURE_PROFILE
from tests.test_analysis_runs import call, operator_session, setup, verifier_session
from tests.test_fkrtl_local_source import KEY, POST_VERIFICATION_MARKER, _create_fkrtl_run, _row, _write_fixture

CORE = SIGNATURE_PROFILES[REPEAT_SERVICE_PROFILE]


def _record(case, **overrides):
    record = {
        "case_id": case, "participant_token": "p1", "service_date": "2024-03-04",
        "province_code": "11", "municipality_code": "1101", "facility_ownership": "1", "facility_type": "2",
        "facility_class": "3", "admission_diagnosis": "SYN01", "primary_diagnosis": "SYN02",
        "claim_group": "SYN-CBG-1", "procedure_code": "SYNPROC", "billed_amount": None,
    }
    record.update(overrides)
    return record


def test_profile_key_is_the_core_definition_and_context_is_the_remaining_eleven_field_attributes():
    assert CORE == REPEAT_SERVICE_KEY
    assert FKRTL_REPEAT_SIGNATURE_PROFILE == REPEAT_SERVICE_PROFILE
    assert set(REPEAT_CONTEXT_FIELDS) == {
        "province_code", "municipality_code", "facility_ownership", "facility_type", "facility_class",
        "admission_diagnosis",
    }
    assert not set(REPEAT_CONTEXT_FIELDS) & set(CORE)


def test_same_core_key_stays_a_candidate_when_context_fields_differ():
    records = [
        _record("case_1"),
        _record("case_2", facility_class="1", municipality_code="9999", admission_diagnosis="SYN77"),
    ]
    result = detect_repeat_billing_candidates(records, CORE)
    assert result["signature_profile"] == REPEAT_SERVICE_PROFILE
    [group] = result["candidate_groups"]
    assert group["case_ids"] == ["case_1", "case_2"]
    assert group["differing_attributes"] == ["municipality_code", "facility_class", "admission_diagnosis"]
    assert group["context_unavailable_attributes"] == []
    assert set(group["matched_attributes"]) == {*CORE, "province_code", "facility_ownership", "facility_type"}
    assert "bukan alasan menyingkirkan kandidat" in group["reason"]
    # The former 11-field profile hides the same pair.
    assert detect_repeat_billing_candidates(records, SIGNATURE_PROFILES["repeat-visit-exact-no-amount-v1"])[
        "candidate_groups"] == []
    # Field names only: no context or key values are returned.
    text = json.dumps(group)
    assert "9999" not in text and "SYN77" not in text and "p1" not in text


def test_blank_procedure_is_unassessed_and_never_forms_a_partial_match_candidate():
    records = [_record("case_1", procedure_code=None), _record("case_2", procedure_code=" "),
               _record("case_3"), _record("case_4", procedure_code="OTHER")]
    result = detect_repeat_billing_candidates(records, CORE)
    assert result["candidate_groups"] == []
    assert {item["case_id"]: item["missing_attributes"] for item in result["ineligible_cases"]} == {
        "case_1": ["procedure_code"], "case_2": ["procedure_code"],
    }


def test_optional_context_fields_do_not_change_eligibility():
    base = [_record("case_1"), _record("case_2"), _record("case_3", participant_token="p2", procedure_code=None)]
    variants = [
        base,
        [{**row, "facility_class": None, "municipality_code": None} for row in base],
        [{**row, "admission_diagnosis": f"X{index}", "province_code": None} for index, row in enumerate(base)],
    ]
    outcomes = []
    for records in variants:
        result = detect_repeat_billing_candidates(records, CORE)
        outcomes.append((
            [group["case_ids"] for group in result["candidate_groups"]],
            [item["case_id"] for item in result["ineligible_cases"]],
        ))
    assert outcomes == [([["case_1", "case_2"]], ["case_3"])] * 3
    missing_context = detect_repeat_billing_candidates(variants[1], CORE)["candidate_groups"][0]
    assert missing_context["context_unavailable_attributes"] == ["municipality_code", "facility_class"]


def test_post_verification_amount_is_never_a_pre_verification_input():
    assert "FKL48" not in FKRTL_SOURCE_COLUMNS
    assert not {"FKL48", "verified_amount", "post_verification_amount"} & set(CANONICAL_FEATURE_FIELDS)
    secret = bytes.fromhex(KEY)
    rows = [_row(FKL02="v1"), _row(FKL02="v2"), _row(FKL02="v3", PSTV01=1234567, FKL18="SYN09")]
    low, _ = adapt_fkrtl_rows([{**row, "FKL48": 1.0} for row in rows], case_reference_secret=secret)
    high, _ = adapt_fkrtl_rows([{**row, "FKL48": 9e12} for row in rows], case_reference_secret=secret)
    assert low == high
    assert str(POST_VERIFICATION_MARKER) not in json.dumps(adapt_fkrtl_rows(rows, case_reference_secret=secret)[0])
    assert detect_repeat_billing_candidates(low, CORE) == detect_repeat_billing_candidates(high, CORE)
    assert build_ml_anomaly_ranking(low)[1] == build_ml_anomaly_ranking(high)[1]


def test_fkrtl_runtime_flags_core_repeat_with_context_and_leaves_blank_procedure_unassessed(tmp_path, monkeypatch):
    rows = [
        _row(),
        _row(FKL02="synvisit-a2", FKL09=1, FKL06=1199),          # same core key, different context
        _row(FKL02="synvisit-a3", FKL30=""), _row(FKL02="synvisit-a4", FKL30=""),  # blank FKL30 pair
        _row(PSTV01=7777772, FKL02="synvisit-b1", FKL18="SYN09"),
    ]
    path = _write_fixture(tmp_path, rows)
    monkeypatch.setenv("BPJS_FKRTL_SAMPLE_PATH", str(path))
    monkeypatch.setenv("CIR_FKRTL_PSEUDONYM_KEY", KEY)
    monkeypatch.setenv("BPJS_FKRTL_DATE_FROM", "2024-03-01")
    monkeypatch.setenv("BPJS_FKRTL_DATE_TO", "2024-03-31")
    monkeypatch.delenv("BPJS_FKRTL_MAX_ROWS", raising=False)
    app, _batch_db, users = setup(tmp_path)
    created = _create_fkrtl_run(app, operator_session(app, users))
    assert created.status_code == 201, created.text
    run = created.json()["run"]
    assert run["configuration"]["source"]["repeat_signature_profile"] == "repeat-service-v1"

    detail = call(app, "GET", f"/api/v1/runs/{run['run_id']}", cookies=verifier_session(app, users))
    assert detail.status_code == 200
    result = detail.json()["result"]
    repeat_cases = [case for case in result["cases"].values() if "repeat_billing_candidate" in case["indicators"]]
    assert len(repeat_cases) == 2
    reason = next(item for item in repeat_cases[0]["reasons"] if item["indicator"] == "repeat_billing_candidate")
    values = reason["supporting_values"]
    assert values["differing_attributes"] == ["municipality_code", "facility_class"]
    assert "participant_token" not in values["matched_attributes"]
    summary = next(item for item in result["indicators"] if item["code"] == "repeat_billing_candidate")
    assert summary["unassessed_count"] + summary["not_applicable_count"] + summary["eligible_count"] == 5
    assert summary["eligible_count"] == 3
    assert "repeat_service_v1" in summary["definition"]
    serialized = json.dumps(detail.json())
    for forbidden in ("7777771", "7777772", "synvisit", "1199", str(POST_VERIFICATION_MARKER)):
        assert forbidden not in serialized


def test_unrelated_synthetic_flow_keeps_the_amount_profile():
    snapshot = build_analytics_snapshot()
    repeat = next(item for item in snapshot["indicators"] if item["code"] == "repeat_billing_candidate")
    assert repeat["status"] in {"completed", "partial"} and repeat["candidate_count"] >= 2
    assert "billed_amount" in SIGNATURE_FIELDS
    result = detect_repeat_billing_candidates([_record("case_a", billed_amount="10"), _record("case_b", billed_amount="10")])
    assert result["signature_profile"] == "repeat-billing-exact-v1"
    assert "context_unavailable_attributes" not in result["candidate_groups"][0]


def test_uploaded_files_match_claims_that_both_carry_no_procedure():
    # Two same-day claims of one participant, same diagnosis and INA-CBG, no procedure on either.
    from app.analytics.repeat_billing import REPEAT_SERVICE_NO_PROCEDURE_PROFILE

    records = [_record("case_a", procedure_code=None), _record("case_b", procedure_code=None), _record("case_c")]
    v1 = detect_repeat_billing_candidates(records, CORE, REPEAT_SERVICE_PROFILE)
    assert v1["candidate_groups"] == [] and {item["case_id"] for item in v1["ineligible_cases"]} == {"case_a", "case_b"}
    v2 = detect_repeat_billing_candidates(records, CORE, REPEAT_SERVICE_NO_PROCEDURE_PROFILE)
    assert v2["signature_profile"] == REPEAT_SERVICE_NO_PROCEDURE_PROFILE and v2["ineligible_cases"] == []
    [group] = v2["candidate_groups"]
    assert group["case_ids"] == ["case_a", "case_b"] and group["no_procedure_recorded"] is True
    assert "tanpa kode tindakan" in group["reason"]
    # A blank procedure never matches a recorded one.
    assert "case_c" not in group["case_ids"]
