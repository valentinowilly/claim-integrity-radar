"""Local FKRTL source validation: counts-only report, actionable errors, run gate (synthetic .dta fixtures)."""

from datetime import datetime
import json

import pytest

from app.services.validation_jobs import wait_for_validation_jobs
from tests.test_analysis_runs import call, operator_session, setup, verifier_session
from tests.test_fkrtl_local_source import KEY, PARTICIPANT_A, PARTICIPANT_B, POST_VERIFICATION_MARKER, _row

pd = pytest.importorskip("pandas")
URL = "/api/v1/sources/fkrtl-local/validation"
FORBIDDEN = (str(PARTICIPANT_A), str(PARTICIPANT_B), "synvisit", KEY, str(POST_VERIFICATION_MARKER))


def full_row(**overrides):
    return _row(FKL31="SYN-REGION", FKL32="SYN-TARIFF", **overrides)


def write(tmp_path, rows, name="fixture.dta"):
    path = tmp_path / name
    pd.DataFrame(rows).to_stata(path, write_index=False)
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CIR_FKRTL_PSEUDONYM_KEY", KEY)
    monkeypatch.setenv("BPJS_FKRTL_DATE_FROM", "2024-03-01")
    monkeypatch.setenv("BPJS_FKRTL_DATE_TO", "2024-03-31")
    monkeypatch.delenv("BPJS_FKRTL_MAX_ROWS", raising=False)

    def use(path):
        monkeypatch.setenv("BPJS_FKRTL_SAMPLE_PATH", str(path))
        return path

    app, _batch_db, users = setup(tmp_path)
    return app, users, use


def validate(app, users):
    operator = operator_session(app, users)
    response = call(app, "POST", URL, cookies=operator, headers={"X-CSRF-Token": operator["cir_csrf"]})
    # The scan runs as a background job: the POST returns at once, the state is read after it finished.
    assert response.status_code == 202, response.text
    assert response.json()["job"]["status"] in ("pending", "running", "completed")
    wait_for_validation_jobs()
    finished = call(app, "GET", URL, cookies=operator)
    for value in FORBIDDEN:
        assert value not in response.text and value not in finished.text
    assert finished.json()["job"]["status"] == "completed"
    return finished.json(), operator


def create_fkrtl_run(app, cookies):
    return call(app, "POST", "/api/v1/runs", cookies=cookies, json_body={"source_type": "bpjs_fkrtl_local"},
                headers={"X-CSRF-Token": cookies["cir_csrf"]})


def test_valid_source_reports_counts_and_check_readiness(tmp_path, env):
    app, users, use = env
    path = use(write(tmp_path, [
        full_row(), full_row(FKL02="synvisit-a2"),
        full_row(PSTV01=PARTICIPANT_B, FKL02="synvisit-b1", FKL03=datetime(2024, 4, 2), FKL04=datetime(2024, 4, 3)),
    ]))
    state, _ = validate(app, users)
    assert state["state"] == "validated" and state["current"] is True
    report = state["report"]
    assert report["status"] == "passed" and report["errors"] == [] and report["warnings"] == []
    scan = report["scan"]
    assert scan["rows_total"] == 3 and scan["rows_in_window"] == 2 and scan["duplicate_visit_rows"] == 0
    assert scan["admission_date_range"] == {"from": "2024-03-04", "to": "2024-04-02"}
    assert "FKL48" not in scan["columns_present"] and "FKL48" not in json.dumps(scan["missing_value_counts"])
    checks = {item["check"]: item for item in report["checks"]}
    assert checks["repeat_billing_candidate"]["rows_meeting_prerequisites"] == 2
    assert checks["near_duplicate_claim_candidate"]["rows_meeting_prerequisites"] == 2
    assert checks["length_of_stay"]["rows_meeting_prerequisites"] == 2
    for code in ("similar_claim_pattern_candidate", "synthetic_capacity_candidate",
                 "temporal_pattern_candidate", "supporting_evidence_completeness_candidate"):
        assert checks[code]["status"] == "not_applicable" and checks[code]["rows_meeting_prerequisites"] == 0
    assert str(path) not in json.dumps(state) and path.name not in json.dumps(state)
    # A passed validation does not block the existing run path.
    assert create_fkrtl_run(app, operator_session(app, users)).status_code == 201


def test_missing_and_unreadable_files_fail_with_actionable_messages(tmp_path, env):
    app, users, use = env
    use(tmp_path / "absent.dta")
    report = validate(app, users)[0]["report"]
    assert report["status"] == "failed" and report["errors"][0]["code"] == "FKRTL_SOURCE_FILE_UNAVAILABLE"
    assert "absent" not in json.dumps(report)
    broken = tmp_path / "broken.dta"
    broken.write_bytes(b"not a stata file")
    use(broken)
    report = validate(app, users)[0]["report"]
    assert report["status"] == "failed" and report["errors"][0]["code"] == "FKRTL_SOURCE_READ_FAILED"
    assert "Traceback" not in json.dumps(report) and "broken" not in json.dumps(report)


def test_missing_required_column_is_named_without_values(tmp_path, env):
    app, users, use = env
    rows = [full_row(), full_row(FKL02="synvisit-a2")]
    use(write(tmp_path, [{key: value for key, value in row.items() if key != "FKL02"} for row in rows]))
    report = validate(app, users)[0]["report"]
    assert report["status"] == "failed"
    assert report["errors"][0]["code"] == "FKRTL_REQUIRED_COLUMNS_MISSING" and "FKL02" in report["errors"][0]["message"]
    assert "FKL02" in report["scan"]["columns_missing"]


def test_malformed_dates_and_sentinels_are_counted_as_missing_not_values(tmp_path, env):
    app, users, use = env
    rows = [full_row(FKL03="2024-03-04", FKL04="2024-03-06"),
            full_row(FKL02="synvisit-a2", FKL03="2024-03-011", FKL04="2024-03-06"),   # malformed, not truncated
            full_row(FKL02="synvisit-a3", FKL03="2024-03-05", FKL04="NA", FKL30="NA"),
            full_row(FKL02="synvisit-a4", FKL03="2024-03-05", FKL04="2024-03-07", FKL30="", FKL18="null")]
    use(write(tmp_path, rows))
    report = validate(app, users)[0]["report"]
    scan = report["scan"]
    assert report["status"] == "passed_with_warnings"
    assert scan["admission_date_invalid"] == 1 and scan["rows_in_window"] == 3
    assert scan["missing_value_counts"]["FKL30"] == 2 and scan["missing_value_counts"]["FKL18"] == 1
    assert scan["missing_value_counts"]["FKL04"] == 1 and scan["discharge_date_invalid"] == 0
    checks = {item["check"]: item for item in report["checks"]}
    assert checks["repeat_billing_candidate"]["rows_meeting_prerequisites"] == 1
    assert checks["repeat_billing_candidate"]["rows_excluded"] == {
        "missing:primary_diagnosis+procedure_code": 1, "missing:procedure_code": 1}
    assert checks["length_of_stay"]["rows_meeting_prerequisites"] == 2
    assert checks["length_of_stay"]["rows_excluded"] == {"missing_date": 1}
    # One blank attribute (FKL30) still leaves 9 of 10; FKL30 plus FKL18 leaves 8.
    assert checks["near_duplicate_claim_candidate"]["rows_meeting_prerequisites"] == 2
    assert checks["near_duplicate_claim_candidate"]["rows_excluded"] == {"too_few_attributes": 1}
    assert {item["code"] for item in report["warnings"]} == {"FKRTL_INVALID_DATES", "FKRTL_PROCEDURE_BLANK"}


def test_duplicate_visits_fail_validation_and_block_the_run_until_the_source_changes(tmp_path, env):
    app, users, use = env
    use(write(tmp_path, [full_row(), full_row(), full_row(FKL02="synvisit-a2")]))
    state, operator = validate(app, users)
    report = state["report"]
    assert report["status"] == "failed" and report["scan"]["duplicate_visit_rows"] == 1
    assert report["errors"][0]["code"] == "FKRTL_DUPLICATE_VISITS"
    blocked = create_fkrtl_run(app, operator)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "FKRTL_SOURCE_VALIDATION_FAILED"
    listed = call(app, "GET", "/api/v1/runs", cookies=verifier_session(app, users)).json()
    assert listed["total_items"] == 0
    # A different file: the old validation is outdated and blocks too, until the new file is validated.
    use(write(tmp_path, [full_row(), full_row(FKL02="synvisit-a2")], name="fixed.dta"))
    assert call(app, "GET", URL, cookies=operator).json()["current"] is False
    stale = create_fkrtl_run(app, operator)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "FKRTL_SOURCE_VALIDATION_STALE"
    assert validate(app, users)[0]["report"]["status"] == "passed"
    assert create_fkrtl_run(app, operator).status_code == 201


def test_empty_window_fails_and_permissions_are_enforced(tmp_path, env, monkeypatch):
    app, users, use = env
    use(write(tmp_path, [full_row()]))
    monkeypatch.setenv("BPJS_FKRTL_DATE_FROM", "2023-01-01")
    monkeypatch.setenv("BPJS_FKRTL_DATE_TO", "2023-01-31")
    report = validate(app, users)[0]["report"]
    assert report["status"] == "failed" and report["errors"][0]["code"] == "FKRTL_WINDOW_EMPTY"
    verifier = verifier_session(app, users)
    assert call(app, "GET", URL, cookies=verifier).status_code == 200
    assert call(app, "POST", URL, cookies=verifier, headers={"X-CSRF-Token": verifier["cir_csrf"]}).status_code == 403
    operator = operator_session(app, users)
    assert call(app, "POST", URL, cookies=operator).status_code == 403  # CSRF required


def test_not_validated_state_before_any_validation(env):
    app, users, _use = env
    assert call(app, "GET", URL, cookies=verifier_session(app, users)).json() == {
        "state": "not_validated", "current": None, "validated_at": None, "report": None,
        "job": None, "phase": "not_validated"}


@pytest.mark.parametrize("sentinel", ["N/A", "na", " NA ", "null", "nan", ""])
def test_adapter_maps_every_missing_sentinel_to_none(sentinel):
    # Before: "N/A" and "na" passed through the adapter as procedure codes.
    from app.data_sources.bpjs_fkrtl_adapter import adapt_fkrtl_rows

    [record], _ = adapt_fkrtl_rows([_row(FKL30=sentinel)], case_reference_secret=bytes.fromhex(KEY))
    assert record["procedure_code"] is None


def test_validation_eligibility_matches_what_the_run_reports(tmp_path, env):
    # The validation counts come from the detectors' own prerequisite functions, so a run of
    # the same source reports the same eligible and unassessed numbers per row-level reason.
    app, users, use = env
    rows = [full_row(FKL02=f"synvisit-{index}", FKL18=f"SYN{index % 3}") for index in range(6)]
    rows += [full_row(FKL02="synvisit-blank", FKL30=""), full_row(FKL02="synvisit-two", FKL30="", FKL18=""),
             full_row(FKL02="synvisit-nodis", FKL04=None)]
    use(write(tmp_path, rows))
    report, operator = validate(app, users)
    checks = {item["check"]: item for item in report["report"]["checks"]}
    created = create_fkrtl_run(app, operator)
    assert created.status_code == 201, created.text
    result = call(app, "GET", f"/api/v1/runs/{created.json()['run']['run_id']}",
                  cookies=verifier_session(app, users)).json()["result"]
    summaries = {item["code"]: item for item in result["indicators"]}
    coverage = {item["indicator"]: item for item in result["indicator_coverage"]}

    repeat = checks["repeat_billing_candidate"]
    assert summaries["repeat_billing_candidate"]["eligible_count"] == repeat["rows_meeting_prerequisites"] == 7
    assert coverage["repeat_billing_candidate"]["unassessed_reason_counts"] == repeat["rows_excluded"]

    similar = checks["near_duplicate_claim_candidate"]
    assert similar["rows_excluded"] == {"too_few_attributes": 1}
    too_few = sum(count for code, count in coverage["near_duplicate_claim_candidate"]["unassessed_reason_counts"].items()
                  if code.startswith("reason:Atribut yang dapat dibandingkan kurang"))
    assert too_few == 1  # the blank-FKL30-only row is not excluded: one blank attribute is allowed

    duration = checks["length_of_stay"]
    run_reasons = {code: count for code, count in result["length_of_stay"]["unassessed_reason_counts"].items()
                   if count and code != "insufficient_peer_support"}
    assert run_reasons == duration["rows_excluded"] == {"missing_date": 1}
    for code in ("similar_claim_pattern_candidate", "synthetic_capacity_candidate", "temporal_pattern_candidate",
                 "supporting_evidence_completeness_candidate"):
        assert checks[code]["status"] == "not_applicable" and summaries[code]["status"] == "not_applicable"


def test_prerequisite_functions_match_the_detectors_on_synthetic_records():
    from app.analytics.length_of_stay import detect_length_of_stay_outliers, row_prerequisite_reason
    from app.analytics.near_duplicate_claims import detect_near_duplicate_claims, prerequisite_reason
    from app.analytics.repeat_billing import REPEAT_SERVICE_PROFILE, SIGNATURE_PROFILES, detect_repeat_billing_candidates
    from app.analytics.repeat_definitions import REPEAT_SERVICE_KEY, RepeatDefinition, missing_key_fields
    from app.data_sources.synthetic_generator import SyntheticGeneratorConfig, generate_synthetic_dataset

    records = generate_synthetic_dataset(SyntheticGeneratorConfig(seed=9, claim_count=400, facility_count=8)).records
    # Blank some attributes so every exclusion path is exercised.
    records = [{**row, "procedure_code": None} if index % 5 == 0 else
               {**row, "primary_diagnosis": None, "procedure_code": None} if index % 7 == 0 else row
               for index, row in enumerate(records)]
    near = detect_near_duplicate_claims(records)
    too_few = {item["case_id"] for item in near["ineligible_cases"] if "kurang dari batas" in item["reason"]}
    assert too_few == {row["case_id"] for row in records if prerequisite_reason(row) == "too_few_attributes"}
    unblockable = {row["case_id"] for row in records if prerequisite_reason(row) == "no_complete_blocking_key"}
    assert unblockable <= set(near["unassessed_case_ids"])

    definition = RepeatDefinition(name=REPEAT_SERVICE_PROFILE, key_fields=REPEAT_SERVICE_KEY)
    repeat = detect_repeat_billing_candidates(records, SIGNATURE_PROFILES[REPEAT_SERVICE_PROFILE])
    assert {item["case_id"]: item["missing_attributes"] for item in repeat["ineligible_cases"]} == {
        row["case_id"]: missing_key_fields(row, definition) for row in records if missing_key_fields(row, definition)}

    duration = detect_length_of_stay_outliers(records)
    expected = {}
    for row in records:
        reason = row_prerequisite_reason(row)
        if reason:
            expected[reason] = expected.get(reason, 0) + 1
    assert {code: count for code, count in duration["unassessed_reason_counts"].items()
            if count and code != "insufficient_peer_support"} == expected


def test_a_blank_stata_date_is_missing_and_does_not_fail_the_batch():
    # Before: pandas NaT (a datetime subclass) reached date comparison and raised, so one blank
    # discharge date made the whole validation or run fail with FKRTL_SOURCE_READ_FAILED.
    from app.data_sources.bpjs_fkrtl_adapter import _date_only, adapt_fkrtl_rows

    assert _date_only(pd.NaT) is None
    [record], coverage = adapt_fkrtl_rows([_row(FKL04=pd.NaT)], case_reference_secret=bytes.fromhex(KEY))
    assert record["discharge_date"] is None and coverage["invalid_discharge_date_count"] == 0


def test_fkrtl_workflow_from_validation_to_outcome_and_history_without_rerunning(tmp_path, env, monkeypatch):
    from app.services import runs as runs_service

    app, users, use = env
    use(write(tmp_path, [full_row(), full_row(FKL02="synvisit-a2"), full_row(FKL02="synvisit-a3", FKL30=""),
                         full_row(PSTV01=PARTICIPANT_B, FKL02="synvisit-b1", FKL18="SYN09")]))
    state, operator = validate(app, users)
    assert state["report"]["status"] == "passed_with_warnings"
    created = create_fkrtl_run(app, operator)
    assert created.status_code == 201
    run_id = created.json()["run"]["run_id"]

    def no_rerun(*_args, **_kwargs):
        raise AssertionError("reading a saved run must not execute detection again")
    monkeypatch.setattr(runs_service, "execute_provider_snapshot", no_rerun)
    monkeypatch.setattr(runs_service, "load_fkrtl_local_source", no_rerun)

    verifier, lead = verifier_session(app, users), verifier_session(app, users, "lead")
    first = call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier)
    result = first.json()["result"]
    assert result["data_source"]["label"] != "synthetic_data_batch"
    [case_id] = [case_id for case_id, case in result["cases"].items() if "repeat_billing_candidate" in case["indicators"]][:1]
    review_url = f"/api/v1/runs/{run_id}/cases/{case_id}/review"
    assert call(app, "PATCH", review_url, cookies=verifier, json_body={"review_status": "in_review", "note": None},
                headers={"X-CSRF-Token": verifier["cir_csrf"]}).status_code == 200
    outcome = call(app, "POST", review_url + "/outcome", cookies=lead,
                   json_body={"review_outcome": "inconclusive", "note": None}, headers={"X-CSRF-Token": lead["cir_csrf"]})
    assert outcome.status_code == 200 and outcome.json()["data_source"] == "bpjs_fkrtl_local_sample"

    history = call(app, "GET", "/api/v1/runs", cookies=verifier).json()["items"]
    assert [(item["run_id"], item["source_type"]) for item in history] == [(run_id, "bpjs_fkrtl_local")]
    reopened = call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier)
    assert reopened.json()["result"] == result  # review state never changes the stored snapshot
    reviews = call(app, "GET", f"/api/v1/runs/{run_id}/reviews", cookies=verifier).json()["items"]
    assert [(item["case_id"], item["review_status"], item["review_outcome"]) for item in reviews] == [
        (case_id, "in_review", "inconclusive")]
    for text in (first.text, reopened.text, outcome.text):
        for value in FORBIDDEN:
            assert value not in text


def test_fkl47_and_fkl48_values_do_not_change_any_finding_or_score(tmp_path, env):
    app, users, use = env
    results = []
    for name, amounts in (("low.dta", (1.0, 2.0)), ("high.dta", (999999.0, 888888.0))):
        use(write(tmp_path, [full_row(FKL47=amounts[0], FKL48=amounts[1]),
                             full_row(FKL02="synvisit-a2", FKL47=amounts[1], FKL48=amounts[0])], name=name))
        _state, operator = validate(app, users)
        run_id = create_fkrtl_run(app, operator).json()["run"]["run_id"]
        result = call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier_session(app, users)).json()["result"]
        results.append(({case: (item["indicators"], item["risk_score"], item["score_status"])
                         for case, item in result["cases"].items()}, result["audit_priority"]["status"]))
        assert "999999" not in json.dumps(result) and "888888" not in json.dumps(result)
    assert results[0] == results[1]
    assert results[0][1] == "not_assessable"


def _reference_scan(path, window):
    """Row-by-row reference of the validation scan (the pre-optimization algorithm)."""
    from collections import Counter

    from app.analytics.length_of_stay import row_prerequisite_reason
    from app.analytics.near_duplicate_claims import prerequisite_reason
    from app.analytics.repeat_definitions import REPEAT_SERVICE_KEY, RepeatDefinition, missing_key_fields
    from app.data_sources.bpjs_fkrtl_adapter import FKRTL_SOURCE_COLUMNS, _clean, adapt_fkrtl_rows

    frame = pd.read_stata(path, convert_categoricals=False)
    columns = [column for column in FKRTL_SOURCE_COLUMNS if column in frame.columns]
    missing = {column: 0 for column in columns}
    totals = Counter()
    excluded = {check: Counter() for check in ("repeat_billing_candidate", "near_duplicate_claim_candidate", "length_of_stay")}
    seen, low, high = set(), None, None
    definition = RepeatDefinition("repeat-service-v1", REPEAT_SERVICE_KEY)
    for row in frame[columns].to_dict(orient="records"):
        totals["rows_total"] += 1
        for column in columns:
            missing[column] += int(_clean(row.get(column)) is None)
        [record], _ = adapt_fkrtl_rows([row], case_reference_secret=bytes.fromhex(KEY))
        admitted, discharged = record["service_date"], record["discharge_date"]
        totals["admission_date_invalid"] += int(admitted is None and _clean(row.get("FKL03")) is not None)
        totals["discharge_date_invalid"] += int(discharged is None and _clean(row.get("FKL04")) is not None)
        totals["discharge_before_admission"] += int(bool(admitted and discharged and discharged < admitted))
        if admitted:
            low, high = min(low or admitted, admitted), max(high or admitted, admitted)
        duplicate = record["case_id"] in seen
        seen.add(record["case_id"])
        totals["duplicate_visit_rows"] += int(duplicate)
        if not admitted or not window[0] <= admitted <= window[1]:
            continue
        totals["rows_in_window"] += 1
        totals["duplicate_visit_rows_in_window"] += int(duplicate)
        absent = missing_key_fields(record, definition)
        excluded["repeat_billing_candidate"]["missing:" + "+".join(absent) if absent else "eligible"] += 1
        excluded["near_duplicate_claim_candidate"][prerequisite_reason(record) or "eligible"] += 1
        excluded["length_of_stay"][row_prerequisite_reason(record) or "eligible"] += 1
    return {**totals, "missing_value_counts": missing, "admission_date_range": {"from": low, "to": high},
            "window_eligibility": {check: {"eligible": counts.pop("eligible", 0), "excluded": dict(sorted(counts.items()))}
                                   for check, counts in excluded.items()}}


@pytest.mark.parametrize("chunk_size", [1, 3, 7, 1000])
def test_optimized_scan_matches_the_row_by_row_reference(tmp_path, chunk_size):
    from datetime import date

    from scripts.fkrtl_dta_reader import scan_fkrtl_dta

    rows = [full_row(FKL02=f"synvisit-{index}", FKL03=f"2024-03-{1 + index % 12:02d}", FKL04=f"2024-03-{3 + index % 12:02d}",
                     FKL30=["", "NA", " n/a ", "SYNPROC", "null"][index % 5], FKL18=["SYN1", "", "nan", "SYN2"][index % 4],
                     FKL16=[" ", "SYN3"][index % 2])
            for index in range(20)]
    rows += [full_row(FKL02="synvisit-3", FKL03="2024-03-04", FKL04="2024-03-05"),     # duplicate across chunks
             full_row(FKL02="synvisit-bad", FKL03="2024-03-011", FKL04="2024-02-01"),  # malformed admission
             full_row(FKL02="synvisit-rev", FKL03="2024-03-05", FKL04="2024-03-01"),   # discharge before admission
             full_row(FKL02="synvisit-none", FKL03="2024-03-06", FKL04="NaT")]
    path = write(tmp_path, rows)
    window = (date(2024, 3, 4), date(2024, 3, 10))
    scanned = scan_fkrtl_dta(path, case_reference_secret=bytes.fromhex(KEY), date_window=window, chunk_size=chunk_size)
    reference = _reference_scan(path, (window[0].isoformat(), window[1].isoformat()))
    for key, value in reference.items():
        assert scanned[key] == value, key
    assert scanned["duplicate_visit_rows"] == 1 and scanned["admission_date_invalid"] == 1


def test_validation_survives_an_api_restart(tmp_path, env):
    from app.main import create_app

    app, users, use = env
    use(write(tmp_path, [full_row(), full_row(FKL02="synvisit-a2")]))
    validate(app, users)
    # A new application instance on the same databases stands in for a restarted server.
    restarted = create_app(tmp_path / "review.sqlite3", tmp_path / "auth.sqlite3", cookie_secure=False,
                           batch_db_path=tmp_path / "batch-and-runs.sqlite3")
    operator = operator_session(restarted, users)
    state = call(restarted, "GET", URL, cookies=operator).json()
    assert state["state"] == "validated" and state["current"] is True and state["report"]["status"] == "passed"
    assert create_fkrtl_run(restarted, operator).status_code == 201


@pytest.mark.parametrize("change", ["window", "max_rows", "key", "same_stat_other_path", "content"])
def test_any_source_change_makes_the_validation_stale_and_blocks_the_run(tmp_path, env, monkeypatch, change):
    import os
    import shutil

    app, users, use = env
    path = use(write(tmp_path, [full_row(), full_row(FKL02="synvisit-a2")]))
    _state, operator = validate(app, users)
    if change == "window":
        monkeypatch.setenv("BPJS_FKRTL_DATE_TO", "2024-03-30")
    elif change == "max_rows":
        monkeypatch.setenv("BPJS_FKRTL_MAX_ROWS", "40000")
    elif change == "key":
        monkeypatch.setenv("CIR_FKRTL_PSEUDONYM_KEY", "cd" * 32)
    elif change == "same_stat_other_path":
        other = tmp_path / "copy.dta"
        shutil.copyfile(path, other)
        stat = path.stat()
        os.utime(other, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert other.stat().st_size == stat.st_size and other.stat().st_mtime_ns == stat.st_mtime_ns
        use(other)
    else:
        stat = path.stat()
        write(tmp_path, [full_row(), full_row(FKL02="synvisit-a3")])
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert call(app, "GET", URL, cookies=operator).json()["current"] is False
    blocked = create_fkrtl_run(app, operator)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "FKRTL_SOURCE_VALIDATION_STALE"


def test_later_occurrence_flags_match_a_first_seen_set_in_input_order():
    import hashlib
    import random

    from scripts.fkrtl_dta_reader import later_occurrence_flags

    rng = random.Random(11)
    keys = [rng.randrange(300) for _ in range(2000)]
    seen, expected = set(), []
    for key in keys:
        expected.append(key in seen)
        seen.add(key)
    digests = b"".join(hashlib.sha256(str(key).encode()).digest() for key in keys)
    assert later_occurrence_flags(digests).tolist() == expected
    # Digests that differ only in trailing zero bytes stay distinct (compared as integers, not strings).
    assert later_occurrence_flags(b"a" * 31 + bytes(1) + b"a" * 32).tolist() == [False, False]
    assert later_occurrence_flags(b"").tolist() == []

