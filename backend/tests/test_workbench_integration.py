"""Workbench gaps: run-level review state for the queue and per-check unassessed reasons.

Everything here is synthetic: persisted fixture runs, the synthetic demo source and
generated `.dta` fixtures. No BPJS dataset is opened.
"""

from datetime import datetime
import json
import re
import sqlite3

from app.services.analytics import build_analytics_snapshot
from tests.db_helpers import assert_rejected, db_connection, on_postgres, seed_reviewable_runs  # noqa: F401
from tests.test_analysis_runs import call as run_call, operator_session, setup, verifier_session
from tests.test_fkrtl_local_source import KEY, _create_fkrtl_run, _row, _write_fixture
from tests.test_run_scoped_reviews import call, review_env, review_url  # noqa: F401 (fixture)


def test_run_review_list_reports_human_state_only_and_is_run_scoped(review_env):
    app, db, _, users = review_env
    verifier, lead = users["verifier"][1], users["lead"][1]
    empty = call(app, "GET", "/api/v1/runs/run-a/reviews", cookies=verifier)
    assert empty.status_code == 200
    assert empty.json()["items"] == [] and empty.json()["initial_status"] == "pending_review"
    with db_connection(db) as connection:
        before = connection.execute("SELECT result_json FROM analysis_run_results WHERE run_id='run-a'").fetchone()

    assert call(app, "PATCH", review_url(), cookies=verifier,
                payload={"review_status": "in_review", "note": "Tinjau pola sintetik."}).status_code == 200
    assert call(app, "POST", review_url() + "/outcome", cookies=lead,
                payload={"review_outcome": "inconclusive", "note": None}).status_code == 200
    listed = call(app, "GET", "/api/v1/runs/run-a/reviews", cookies=verifier).json()
    [item] = listed["items"]
    assert (item["case_id"], item["review_status"], item["review_outcome"]) == ("case-shared", "in_review", "inconclusive")
    # No notes or actors; audit_result is the latest authorized audit result (None until recorded).
    assert set(item) == {"case_id", "review_status", "review_outcome", "updated_at", "audit_result"}
    assert item["audit_result"] is None
    assert "bukan hasil algoritma" in listed["notice"]
    # Another run of the same case is independent, and the stored result is unchanged.
    assert call(app, "GET", "/api/v1/runs/run-b/reviews", cookies=verifier).json()["items"] == []
    with db_connection(db) as connection:
        after = connection.execute("SELECT result_json FROM analysis_run_results WHERE run_id='run-a'").fetchone()
    assert before == after


def test_run_review_list_requires_auth_and_a_reviewable_run(review_env):
    app, _, _, users = review_env
    assert call(app, "GET", "/api/v1/runs/run-a/reviews").status_code == 401
    verifier = users["verifier"][1]
    assert call(app, "GET", "/api/v1/runs/missing/reviews", cookies=verifier).status_code == 404
    assert call(app, "GET", "/api/v1/runs/run-failed/reviews", cookies=verifier).status_code == 409


def test_unassessed_reasons_account_for_every_unassessed_record_without_values():
    snapshot = build_analytics_snapshot()
    for coverage in snapshot["indicator_coverage"]:
        reasons = coverage["unassessed_reason_counts"]
        assert sum(reasons.values()) == coverage["records_unassessed"], coverage["indicator"]
        assert all(re.fullmatch(r"missing:[a-z_+]+|reason:.+|not_reached_by_search|unspecified", code) for code in reasons)
    repeat = next(item for item in snapshot["indicator_coverage"] if item["indicator"] == "repeat_billing_candidate")
    assert set(repeat["unassessed_reason_counts"]) <= {"missing:procedure_code", "missing:service_date",
                                                        "missing:billed_amount", "missing:participant_token"}


def test_fkrtl_run_reports_blank_procedure_as_the_unassessed_reason(tmp_path, monkeypatch):
    rows = [
        _row(),
        _row(FKL02="synvisit-a2", FKL09=1),                      # core repeat with different context
        _row(FKL02="synvisit-a3", FKL30=""), _row(FKL02="synvisit-a4", FKL30=""),  # blank FKL30 pair
        _row(PSTV01=7777772, FKL02="synvisit-b1", FKL18="SYN09", FKL03=datetime(2024, 3, 5)),
    ]
    monkeypatch.setenv("BPJS_FKRTL_SAMPLE_PATH", str(_write_fixture(tmp_path, rows)))
    monkeypatch.setenv("CIR_FKRTL_PSEUDONYM_KEY", KEY)
    monkeypatch.setenv("BPJS_FKRTL_DATE_FROM", "2024-03-01")
    monkeypatch.setenv("BPJS_FKRTL_DATE_TO", "2024-03-31")
    monkeypatch.delenv("BPJS_FKRTL_MAX_ROWS", raising=False)
    app, _batch_db, users = setup(tmp_path)
    created = _create_fkrtl_run(app, operator_session(app, users))
    assert created.status_code == 201, created.text
    run_id = created.json()["run"]["run_id"]
    verifier = verifier_session(app, users)
    detail = run_call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier)
    result = detail.json()["result"]
    coverage = {item["indicator"]: item for item in result["indicator_coverage"]}
    repeat = coverage["repeat_billing_candidate"]
    assert repeat["records_unassessed"] == 2
    assert repeat["unassessed_reason_counts"] == {"missing:procedure_code": 2}
    # Checks this source cannot support are not applicable, never unassessed.
    for code in ("supporting_evidence_completeness_candidate", "synthetic_capacity_candidate",
                 "temporal_pattern_candidate", "similar_claim_pattern_candidate"):
        assert coverage[code]["status"] == "not_applicable"
        assert coverage[code]["records_unassessed"] == 0 and coverage[code]["unassessed_reason_counts"] == {}
    # Blank-procedure records are not candidates; only the core-key pair is.
    repeat_cases = [case for case in result["cases"].values() if "repeat_billing_candidate" in case["indicators"]]
    assert len(repeat_cases) == 2
    assert result["audit_priority"]["status"] != "available"
    reviews = run_call(app, "GET", f"/api/v1/runs/{run_id}/reviews", cookies=verifier)
    assert reviews.status_code == 200 and reviews.json()["items"] == []
    text = json.dumps(detail.json()) + reviews.text
    for forbidden in ("7777771", "7777772", "synvisit"):
        assert forbidden not in text


def test_unassessed_reasons_exclude_flagged_records_of_a_truncated_search():
    # Found on the local FKRTL smoke run: a truncated near-duplicate search lists
    # flagged records as unassessed too; scoring keeps them assessed.
    from app.analytics.risk_scoring import run_detector_suite, score_claims
    from app.data_sources.synthetic import get_synthetic_records
    from app.services.analytics import _coverage_for_indicator

    records = get_synthetic_records()
    ids = [row["case_id"] for row in records]
    results = run_detector_suite(records, [])
    results["near_duplicate_claim_candidate"] = {
        "indicator": "near_duplicate_claim_candidate", "input_record_count": len(records),
        "candidates": [{"case_ids": ids[:2], "reason": "synthetic", "limitations": []}],
        "ineligible_cases": [{"case_id": ids[3], "reason": "Token peserta tidak tersedia untuk mensyaratkan peserta berbeda."}],
        "unassessed_case_ids": [ids[0], ids[2]], "search_truncated": True, "pair_comparisons": 1,
        "truncation_scope": "explicit_unassessed_cases",
    }
    scoring = score_claims(records, results, include_untriggered_cases=False)
    triggered = {item["case_id"] for item in scoring["cases"]
                 if "near_duplicate_claim_candidate" in item["triggered_indicators"]}
    coverage = _coverage_for_indicator("near_duplicate_claim_candidate", results["near_duplicate_claim_candidate"],
                                       scoring["detector_coverage"], triggered)
    assert coverage["records_unassessed"] == 2
    assert coverage["unassessed_reason_counts"] == {
        "not_reached_by_search": 1,
        "reason:Token peserta tidak tersedia untuk mensyaratkan peserta berbeda.": 1,
    }

    # A detector with only a global truncation flag withholds every unflagged record.
    del results["near_duplicate_claim_candidate"]["truncation_scope"]
    scoring = score_claims(records, results, include_untriggered_cases=False)
    coverage = _coverage_for_indicator("near_duplicate_claim_candidate", results["near_duplicate_claim_candidate"],
                                       scoring["detector_coverage"], triggered)
    reasons = coverage["unassessed_reason_counts"]
    assert sum(reasons.values()) == coverage["records_unassessed"] == len(records) - 2
    assert reasons["search_limited"] == len(records) - 4


def test_fkrtl_detail_notice_states_the_recorded_selection(tmp_path, monkeypatch):
    from app.api.routes.runs import _detail_notice

    monkeypatch.setenv("BPJS_FKRTL_SAMPLE_PATH", str(_write_fixture(tmp_path, [_row(), _row(FKL02="synvisit-a2")])))
    monkeypatch.setenv("CIR_FKRTL_PSEUDONYM_KEY", KEY)
    monkeypatch.setenv("BPJS_FKRTL_DATE_FROM", "2024-03-04")
    monkeypatch.setenv("BPJS_FKRTL_DATE_TO", "2024-03-10")
    monkeypatch.delenv("BPJS_FKRTL_MAX_ROWS", raising=False)
    app, _batch_db, users = setup(tmp_path)
    run_id = _create_fkrtl_run(app, operator_session(app, users)).json()["run"]["run_id"]
    notice = run_call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier_session(app, users)).json()["notice"]
    assert "2024-03-04 s.d. 2024-03-10 (inklusif)" in notice and "bukan seluruh sampel" in notice
    assert "ditolak, tidak dipotong" in notice and "jendela baris" not in notice
    assert "bergantung pada konfigurasi dan field yang tersedia" in notice
    # Runs saved before date windows (first rows in file order) are described as such.
    legacy = _detail_notice({"source_type": "bpjs_fkrtl_local", "configuration": {"source": {"row_window": {"max_rows": 10}}}})
    assert "seleksi baris awal pada run lama" in legacy and "tidak mewakili seluruh sampel" in legacy
    assert _detail_notice({"source_type": "synthetic_csv"}).startswith("Hasil analisis berkas unggahan")
