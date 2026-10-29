"""Result consistency from detectors to the run API (synthetic fixtures only).

Invariants: per-case states, reasons, scores and lanes agree with each other and with the
indicator summaries; not-assessed is never a negative; a check the source declares
unsupported is not applicable everywhere; persisted results read back unchanged; internal
detector keys and participant tokens never appear in responses.
"""

import json

from app.analytics.clinical_rules import INDICATORS as CLINICAL_INDICATORS
from app.analytics.note_similarity import INDICATOR as NOTE_INDICATOR
from app.analytics.claim_detail_rules import INDICATORS as DETAIL_INDICATORS
from app.analytics.detector_utils import MEMBER_CASE_IDS
from app.services import runs as runs_service
from app.services.analytics import build_analytics_snapshot
from tests.test_analysis_runs import call, create_run, import_batch, operator_session, setup, verifier_session
from tests.test_fkrtl_local_source import KEY, _create_fkrtl_run, _row, _write_fixture
from tests.test_repeat_service_profile import _record
from scripts.fkrtl_dta_provider import FKRTL_NOT_APPLICABLE_DETECTORS

ASSESSED = {"triggered", "not_triggered"}


def assert_consistent(result):
    summaries = {item["code"]: item for item in result["indicators"]}
    coverage = {item["indicator"]: item for item in result["indicator_coverage"]}
    for code, summary in summaries.items():
        assert summary["eligible_count"] + summary["unassessed_count"] + summary["not_applicable_count"] \
            == result["records_considered"], code
        flagged = [case for case in result["cases"].values() if code in case["indicators"]]
        if summary["candidate_count"] is not None:
            assert summary["candidate_count"] == len(flagged), code
        assert summary["search_truncated"] == coverage[code]["search_truncated"], code
        assert sum(coverage[code].get("unassessed_reason_counts", {}).values()) == summary["unassessed_count"], code
    for case_id, case in result["cases"].items():
        rows = {row["indicator"]: row["status"] for row in case["indicator_coverage"]}
        assert set(case["indicators"]) == {code for code, state in rows.items() if state == "triggered"}
        assert set(case["assessed_indicators"]) == {code for code, state in rows.items() if state in ASSESSED}
        assert set(case["not_assessed_indicators"]) == {code for code, state in rows.items() if state == "not_assessed"}
        assert set(case["not_applicable_indicators"]) == {code for code, state in rows.items() if state == "not_applicable"}
        for code, state in rows.items():
            if summaries[code]["status"] == "not_applicable":
                assert state == "not_applicable", (case_id, code)
        assert {reason["indicator"] for reason in case["reasons"]} == set(case["indicators"])
        assessed = len(case["assessed_indicators"])
        if case["risk_score"] is None:
            assert case["score_status"] in {"insufficient_assessed_indicators", "not_assessable"}
        else:
            # Equal default weights: unassessed and not-applicable checks are outside the denominator.
            assert assessed >= 3 and case["risk_score"] == round(len(case["indicators"]) / assessed, 6)
            assert case["score_status"] == ("partial_coverage" if case["not_assessed_indicators"] else "assessed")
        lane = result["action_policy"]["cases"][case_id]["lane"]
        if lane != "cannot_recommend" and case["risk_score"] is None:
            # Evidence lane (policy v3): a rule-flagged claim whose index was withheld.
            assert case["indicators"] and case["score_status"] == "insufficient_assessed_indicators"
            assert isinstance(case.get("ml_anomaly"), dict)
        elif lane != "cannot_recommend":
            # A derived index may still have per-claim gaps (e.g. no reference stay for a rare INA-CBG);
            # the status above then says partial_coverage.
            assert case["risk_score"] is not None
            assert not any(coverage[code]["search_truncated"] for code in rows if rows[code] != "not_applicable")


def assert_sanitized(text, *forbidden):
    # Before: evidence lines still named "participant_token" while supporting_values did not.
    assert MEMBER_CASE_IDS not in text and "participant_token" not in text
    for value in forbidden:
        assert value not in text
    for case in json.loads(text)["result"]["cases"].values():
        for reason in case["reasons"]:
            listed = {line.split(": ", 1)[0]: line.split(": ", 1)[1].split(", ") for line in reason["evidence"]
                      if line.split(": ", 1)[0].endswith("_attributes")}
            for key, names in listed.items():
                assert names == reason["supporting_values"][key], (key, names)


def test_declared_unsupported_checks_are_not_applicable_per_case_not_unassessed():
    # Before: the indicator summary said not applicable, but each flagged case listed the
    # same checks as "not assessed" ("no assessment produced") with a coverage limitation.
    records = [_record("case_1"), _record("case_2")]
    source = {"repeat_signature_profile": "repeat-service-v1", "not_applicable_detectors": FKRTL_NOT_APPLICABLE_DETECTORS}
    snapshot = build_analytics_snapshot(records, data_source=source)
    case = snapshot["cases"]["case_1"]
    rows = {row["indicator"]: row for row in case["indicator_coverage"]}
    for code, reason in FKRTL_NOT_APPLICABLE_DETECTORS.items():
        assert rows[code]["status"] == "not_applicable"
        assert rows[code]["reason"] == f"Tidak berlaku untuk sumber data ini: {reason}"
    assert case["not_assessed_indicators"] == []
    # No BPJS schema profile is declared here, so the clinical and clinical-note checks are not applicable too.
    assert sorted(case["not_applicable_indicators"]) == sorted([*FKRTL_NOT_APPLICABLE_DETECTORS, *CLINICAL_INDICATORS, NOTE_INDICATOR, *DETAIL_INDICATORS])
    assert not any("belum tuntas" in text for text in case["limitations"])


def test_synthetic_run_is_consistent_and_reads_back_exactly(tmp_path, monkeypatch):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _generated = import_batch(app, batch_db, operator)
    captured = {}
    original = runs_service.execute_provider_snapshot

    def capture(provider, action_policy=None):
        dataset, snapshot = original(provider, action_policy)
        captured["snapshot"], captured["records"] = snapshot, list(dataset.records)
        return dataset, snapshot

    monkeypatch.setattr(runs_service, "execute_provider_snapshot", capture)
    created = create_run(app, operator, batch["batch_id"])
    assert created.status_code == 201, created.text
    run_id = created.json()["run"]["run_id"]
    verifier = verifier_session(app, users)
    first = call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier)
    second = call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier)
    result = first.json()["result"]
    assert result == second.json()["result"]
    # Persisted and read back: every computed section equals the sanitized in-memory result
    # (sanitizing only drops identity field names such as participant_token from attribute lists).
    sanitized = json.loads(json.dumps(runs_service._compact_snapshot(
        runs_service._safe_snapshot(captured["snapshot"], captured["records"]))))
    assert {key: result[key] for key in sanitized} == sanitized
    assert result["cases"], "the synthetic fixture must flag claims"
    assert_consistent(result)
    assert_sanitized(first.text, "syn-participant-")


def test_fkrtl_run_keeps_unsupported_checks_not_applicable_and_lanes_by_two_signals(tmp_path, monkeypatch):
    rows = [_row(), _row(FKL02="synvisit-a2"), _row(FKL02="synvisit-a3", FKL30=""),
            _row(PSTV01=7777772, FKL02="synvisit-b1", FKL18="SYN09")]
    path = _write_fixture(tmp_path, rows)
    monkeypatch.setenv("BPJS_FKRTL_SAMPLE_PATH", str(path))
    monkeypatch.setenv("CIR_FKRTL_PSEUDONYM_KEY", KEY)
    monkeypatch.setenv("BPJS_FKRTL_DATE_FROM", "2024-03-01")
    monkeypatch.setenv("BPJS_FKRTL_DATE_TO", "2024-03-31")
    monkeypatch.delenv("BPJS_FKRTL_MAX_ROWS", raising=False)
    app, _batch_db, users = setup(tmp_path)
    created = _create_fkrtl_run(app, operator_session(app, users))
    assert created.status_code == 201, created.text
    detail = call(app, "GET", f"/api/v1/runs/{created.json()['run']['run_id']}", cookies=verifier_session(app, users))
    result = detail.json()["result"]
    assert_consistent(result)
    assert result["cases"]
    for case in result["cases"].values():
        # The four unsupported checks never apply; a clinical check may also not apply to this claim
        # (e.g. a same-day visit has no stay to compare), and the sample has no clinical notes.
        extra = set(case["not_applicable_indicators"]) - set(FKRTL_NOT_APPLICABLE_DETECTORS)
        assert set(FKRTL_NOT_APPLICABLE_DETECTORS) <= set(case["not_applicable_indicators"])
        # This fixture has no secondary-diagnosis file and no special top-up columns: both checks do not apply.
        assert NOTE_INDICATOR in extra and set(DETAIL_INDICATORS) <= extra
        assert extra <= {*CLINICAL_INDICATORS, NOTE_INDICATOR, *DETAIL_INDICATORS}
        assessed = len(case["assessed_indicators"])
        assert case["risk_score"] == (round(len(case["indicators"]) / assessed, 6) if assessed >= 3 else None)
        # v4 lanes the flagged claim by its evidence, not by the index: specific rule findings; the
        # similar-claim screen alone (even with the AI agreeing) stays green.
        lane = result["action_policy"]["cases"][case["case_id"]]
        assert lane["policy_version"] == "action-policy-evidence-v4-provisional"
        specific = [code for code in case["indicators"] if code != "near_duplicate_claim_candidate"]
        percentile = case["ml_anomaly"].get("reference_percentile", case["ml_anomaly"].get("anomaly_percentile"))
        expected = ("red" if len(specific) >= 2 or (percentile >= 0.95 and specific)
                    else "yellow" if specific else "green")
        assert lane["lane"] == expected
    blank = next(item for item in result["indicators"] if item["code"] == "repeat_billing_candidate")
    assert blank["unassessed_count"] == 1
    assert_sanitized(detail.text, "7777771", "7777772", "synvisit")


def test_error_responses_do_not_echo_submitted_values(tmp_path):
    app, _batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    secret_like = "PSTV01-7777771-synvisit"
    invalid = create_run(app, operator, extra={"source_type": secret_like, "participant_token": secret_like})
    assert invalid.status_code in {400, 404, 409, 422}
    assert secret_like not in invalid.text
    missing = call(app, "GET", f"/api/v1/runs/run_{secret_like}", cookies=verifier_session(app, users))
    assert missing.status_code in {404, 422} and secret_like not in missing.text


def test_stored_shared_text_compaction_is_lossless(tmp_path, monkeypatch):
    import copy

    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _generated = import_batch(app, batch_db, operator)
    captured = {}
    original = runs_service.execute_provider_snapshot

    def capture(provider, action_policy=None):
        dataset, snapshot = original(provider, action_policy)
        captured["full"] = runs_service._safe_snapshot(copy.deepcopy(snapshot), list(dataset.records))
        return dataset, snapshot

    monkeypatch.setattr(runs_service, "execute_provider_snapshot", capture)
    run_id = create_run(app, operator, batch["batch_id"]).json()["run"]["run_id"]
    stored = call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier_session(app, users)).json()["result"]
    full = json.loads(json.dumps(captured["full"]))
    assert stored["result_contract"]["version"] == runs_service.RESULT_CONTRACT
    summaries = {item["code"]: set(item["limitations"]) for item in stored["indicators"]}
    scoring = set(stored["risk_scoring"]["limitations"])
    assert stored["cases"].keys() == full["cases"].keys()
    for case_id, case in stored["cases"].items():
        before = full["cases"][case_id]
        for key in ("indicators", "risk_score", "score_status", "assessed_indicators", "not_assessed_indicators",
                    "not_applicable_indicators"):
            assert case[key] == before[key], key
        assert [row["status"] for row in case["indicator_coverage"]] == [row["status"] for row in before["indicator_coverage"]]
        for kept, original_reason in zip(case["reasons"], before["reasons"]):
            assert {k: v for k, v in kept.items() if k != "limitations"} == \
                {k: v for k, v in original_reason.items() if k != "limitations"}
            assert set(original_reason["limitations"]) <= set(kept["limitations"]) | summaries[kept["indicator"]]
        assert set(before["limitations"]) <= set(case["limitations"]) | scoring
