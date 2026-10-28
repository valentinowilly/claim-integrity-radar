"""Configured local FKRTL source → persisted AnalysisRun → run-scoped review.

Every `.dta` file here is a generated synthetic fixture written to tmp_path;
no BPJS dataset is opened.
"""

from datetime import datetime
import json
import re
import sqlite3

import pytest

from app.analytics.repeat_billing import (
    AMOUNT_WITHHELD_SIGNATURE_FIELDS, detect_repeat_billing_candidates,
)
from app.data_sources.bpjs_fkrtl_adapter import adapt_fkrtl_rows
from app.services.batches import BatchStore
from tests.db_helpers import assert_rejected, db_connection, on_postgres, seed_reviewable_runs  # noqa: F401
from tests.test_analysis_runs import call, create_run, operator_session, setup, verifier_session


KEY = "ab" * 32
PARTICIPANT_A = 7777771
PARTICIPANT_B = 7777772
POST_VERIFICATION_MARKER = 987654321


def _row(**overrides):
    row = {
        "PSTV01": PARTICIPANT_A, "FKL02": "synvisit-a1",
        "FKL03": datetime(2024, 3, 4), "FKL04": datetime(2024, 3, 6),
        "FKL05": 11, "FKL06": 1101, "FKL07": 1, "FKL08": 2, "FKL09": 3, "FKL13": 3,
        "FKL16": "SYN01", "FKL18": "SYN02", "FKL19": "SYN-CBG-1", "FKL30": "SYNPROC",
        # Present in the file but outside the reader allow-list.
        "FKL47": 123456.0, "FKL48": float(POST_VERIFICATION_MARKER),
    }
    row.update(overrides)
    return row


def _write_fixture(tmp_path, rows=None):
    pd = pytest.importorskip("pandas")
    rows = rows or [
        _row(),
        _row(FKL02="synvisit-a2", FKL04=datetime(2024, 3, 5)),  # repeat visit candidate
        _row(FKL02="synvisit-a3", FKL03=datetime(2024, 3, 20), FKL04=datetime(2024, 3, 21)),
        _row(PSTV01=PARTICIPANT_B, FKL02="synvisit-b1", FKL18="SYN09"),
    ]
    path = tmp_path / "synthetic-fkrtl-fixture.dta"
    pd.DataFrame(rows).to_stata(path, write_index=False)
    return path


@pytest.fixture
def configured(tmp_path, monkeypatch):
    path = _write_fixture(tmp_path)
    monkeypatch.setenv("BPJS_FKRTL_SAMPLE_PATH", str(path))
    monkeypatch.setenv("CIR_FKRTL_PSEUDONYM_KEY", KEY)
    monkeypatch.setenv("BPJS_FKRTL_DATE_FROM", "2024-03-01")
    monkeypatch.setenv("BPJS_FKRTL_DATE_TO", "2024-03-31")
    monkeypatch.delenv("BPJS_FKRTL_MAX_ROWS", raising=False)
    return path


def _validate_fkrtl_source(app, cookies):
    """Start the background validation and wait for it (the POST returns before the scan ends)."""
    from app.services.validation_jobs import wait_for_validation_jobs

    started = call(app, "POST", "/api/v1/sources/fkrtl-local/validation", cookies=cookies,
                   headers={"X-CSRF-Token": cookies["cir_csrf"]})
    assert started.status_code == 202, started.text
    wait_for_validation_jobs()
    return call(app, "GET", "/api/v1/sources/fkrtl-local/validation", cookies=cookies)


def _create_fkrtl_run(app, cookies, *, validate=True, **extra):
    """Follow the supported workflow: validate the configured source, then create the run."""
    if validate:
        _validate_fkrtl_source(app, cookies)
    return create_run(app, cookies, extra={"source_type": "bpjs_fkrtl_local", **extra})


def test_status_reports_actionable_issues_without_paths(tmp_path, monkeypatch):
    app, _, users = setup(tmp_path)
    operator = operator_session(app, users)
    secret_dir = tmp_path / "private-location"
    monkeypatch.setenv("BPJS_FKRTL_SAMPLE_PATH", str(secret_dir / "missing.dta"))
    monkeypatch.delenv("CIR_FKRTL_PSEUDONYM_KEY", raising=False)
    response = call(app, "GET", "/api/v1/sources/fkrtl-local", cookies=operator)
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False and body["configured"] is True
    codes = {item["code"] for item in body["issues"]}
    assert {"FKRTL_SOURCE_FILE_UNAVAILABLE", "FKRTL_PSEUDONYM_KEY_INVALID"} <= codes
    assert "private-location" not in response.text

    run = _create_fkrtl_run(app, operator)
    assert run.status_code == 503
    assert run.json()["error"]["code"] == "FKRTL_SOURCE_FILE_UNAVAILABLE"
    assert call(app, "GET", "/api/v1/runs", cookies=operator).json()["total_items"] == 0


def test_status_requires_authentication(tmp_path):
    app, _, _ = setup(tmp_path)
    assert call(app, "GET", "/api/v1/sources/fkrtl-local").status_code == 401


def test_configured_fkrtl_source_persists_run_with_explainable_repeat_and_review(tmp_path, configured):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    status = call(app, "GET", "/api/v1/sources/fkrtl-local", cookies=operator).json()
    assert status["available"] is True and status["max_rows"] == 50_000

    created = _create_fkrtl_run(app, operator)
    assert created.status_code == 201, created.text
    run = created.json()["run"]
    assert run["source_type"] == "bpjs_fkrtl_local"
    assert run["source_classification"] == "bpjs_sample_local"
    assert run["execution_status"] in {"completed", "partial"}
    assert run["configuration"]["source"]["repeat_signature_profile"] == "repeat-service-v1"

    # Metadata-only batch: no source rows are copied into the application DB.
    batch = BatchStore(batch_db).get_batch(run["batch_id"])
    assert batch["source_type"] == "bpjs_fkrtl_local" and batch["row_count"] == 4
    assert BatchStore(batch_db).get_record_count(run["batch_id"]) == 0
    listed = call(app, "GET", "/api/v1/batches", cookies=operator)
    assert listed.status_code == 200 and listed.json()["items"][0]["source_type"] == "bpjs_fkrtl_local"

    verifier = verifier_session(app, users)
    detail = call(app, "GET", f"/api/v1/runs/{run['run_id']}", cookies=verifier)
    assert detail.status_code == 200
    result = detail.json()["result"]
    assert result["records_considered"] == 4
    repeat_cases = [case for case in result["cases"].values()
                    if "repeat_billing_candidate" in case["indicators"]]
    assert len(repeat_cases) == 2
    reason = next(item for item in repeat_cases[0]["reasons"] if item["indicator"] == "repeat_billing_candidate")
    assert "bukan bukti" in reason["summary"]
    assert "billed_amount" not in json.dumps(reason["supporting_values"])
    assert result["audit_priority"]["status"] != "available"  # no facility ranking

    serialized = json.dumps(detail.json())
    for forbidden in (str(PARTICIPANT_A), str(PARTICIPANT_B), "synvisit", str(POST_VERIFICATION_MARKER),
                      configured.stem):
        assert forbidden not in serialized
    assert not re.search(r"participant_[0-9a-f]{32}", serialized)  # attribute names only, never token values

    case_id = repeat_cases[0]["case_id"]
    review_url = f"/api/v1/runs/{run['run_id']}/cases/{case_id}/review"
    updated = call(app, "PATCH", review_url, cookies=verifier,
                   json_body={"review_status": "in_review", "note": "Cek resume medis."},
                   headers={"X-CSRF-Token": verifier["cir_csrf"]})
    assert updated.status_code == 200, updated.text
    assert updated.json()["data_source"] == "bpjs_fkrtl_local_sample"
    assert updated.json()["review_status"] == "in_review"

    # Re-running the unchanged configured file reuses the same metadata batch.
    second = _create_fkrtl_run(app, operator)
    assert second.status_code == 201
    assert second.json()["run"]["batch_id"] == run["batch_id"]


def test_row_cap_fails_visibly_instead_of_truncating(tmp_path, configured, monkeypatch):
    # Replaces the former first-N behaviour: a cap below the window size is an error.
    monkeypatch.setenv("BPJS_FKRTL_MAX_ROWS", "2")
    app, _, users = setup(tmp_path)
    operator = operator_session(app, users)
    # Validation reports the oversized window and blocks the run; nothing is truncated.
    validation = _validate_fkrtl_source(app, operator).json()["report"]
    assert validation["status"] == "failed"
    assert [item["code"] for item in validation["errors"]] == ["FKRTL_WINDOW_EXCEEDS_CAP"]
    response = _create_fkrtl_run(app, operator, validate=False)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FKRTL_SOURCE_VALIDATION_FAILED"
    assert call(app, "GET", "/api/v1/runs", cookies=operator).json()["total_items"] == 0
    # The run path enforces the cap itself as well (defence in depth).
    from app.data_sources.fkrtl_local_source import FkrtlSourceUnavailable, load_fkrtl_local_source
    with pytest.raises(FkrtlSourceUnavailable) as raised:
        load_fkrtl_local_source()
    assert raised.value.code == "FKRTL_WINDOW_EXCEEDS_CAP" and "4 baris" in raised.value.message


def test_fkrtl_source_rejects_client_selected_batch(tmp_path, configured):
    app, _, users = setup(tmp_path)
    operator = operator_session(app, users)
    response = _create_fkrtl_run(app, operator, batch_id="bat_client_selected")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUN_SOURCE_BATCH_MISMATCH"


@pytest.mark.sqlite_storage
def test_legacy_batch_schema_is_widened_in_place(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE data_batches (batch_id TEXT PRIMARY KEY, batch_key TEXT NOT NULL, "
            "batch_version INTEGER NOT NULL CHECK(batch_version > 0), created_at TEXT NOT NULL, "
            "creator_user_id TEXT NOT NULL, source_type TEXT NOT NULL CHECK(source_type = 'synthetic_csv'), "
            "schema_version TEXT NOT NULL, mapping_version TEXT NOT NULL, content_checksum TEXT NOT NULL, "
            "row_count INTEGER, validation_summary_json TEXT NOT NULL, status TEXT NOT NULL "
            "CHECK(status IN ('validating','ready','ready_with_warnings','rejected')), "
            "UNIQUE(batch_key, batch_version), UNIQUE(batch_key, content_checksum, schema_version, mapping_version))"
        )
        connection.execute(
            "INSERT INTO data_batches VALUES ('bat_old','synthetic-old',1,'2026-01-01T00:00:00+00:00','u',"
            "'synthetic_csv','s','m','c',0,?, 'ready')",
            (json.dumps({"error_count": 0, "error_counts": {}, "errors": [], "errors_truncated": False,
                         "row_count": 0, "warning_counts": {}}),),
        )
    store = BatchStore(path)
    batch, reused = store.register_local_source(
        source_type="bpjs_fkrtl_local", batch_key="bpjs-fkrtl-local-sample", schema_version="p",
        mapping_version="m", content_fingerprint="f" * 64, row_count=3,
        validation_summary={"error_count": 0, "error_counts": {}, "errors": [], "errors_truncated": False,
                            "row_count": 3, "warning_counts": {}},
        creator_user_id="u",
    )
    assert not reused and batch["source_type"] == "bpjs_fkrtl_local"
    assert {item["batch_id"] for item in store.list_batches()["items"]} == {"bat_old", batch["batch_id"]}
    with sqlite3.connect(path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE data_batches SET source_type='other' WHERE batch_id='bat_old'")


def test_amount_withheld_profile_matches_same_participant_visits_only():
    base = {
        "participant_token": "p1", "service_date": "2024-03-04", "province_code": "11",
        "municipality_code": "1101", "facility_ownership": "1", "facility_type": "2", "facility_class": "3",
        "admission_diagnosis": "SYN01", "primary_diagnosis": "SYN02", "claim_group": "SYN-CBG-1",
        "procedure_code": "SYNPROC", "billed_amount": None,
    }
    records = [
        {**base, "case_id": "case_1"}, {**base, "case_id": "case_2"},
        {**base, "case_id": "case_3", "participant_token": "p2"},
    ]
    assert detect_repeat_billing_candidates(records)["candidate_groups"] == []  # default needs amount
    result = detect_repeat_billing_candidates(records, AMOUNT_WITHHELD_SIGNATURE_FIELDS)
    assert [group["case_ids"] for group in result["candidate_groups"]] == [["case_1", "case_2"]]
    assert "billed_amount" not in result["candidate_groups"][0]["matched_attributes"]
    with pytest.raises(ValueError):
        detect_repeat_billing_candidates(records, ("participant_token",))


def test_adapter_treats_integral_float_codes_like_integers():
    secret = bytes.fromhex(KEY)
    as_int, _ = adapt_fkrtl_rows([_row()], case_reference_secret=secret)
    as_float, _ = adapt_fkrtl_rows(
        [_row(PSTV01=float(PARTICIPANT_A), FKL05=11.0, FKL06=1101.0)], case_reference_secret=secret,
    )
    assert as_int == as_float
    missing, _ = adapt_fkrtl_rows([_row(FKL05=float("nan"))], case_reference_secret=secret)
    assert missing[0]["province_code"] is None
