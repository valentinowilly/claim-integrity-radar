"""Uploads in the BPJS FKRTL column format: example data only, same checks and trained AI as the FKRTL source."""

import csv
from datetime import date, timedelta
import io
import json

import pytest

from app.analytics.ml_model import MODEL_DIR_VARIABLE, TrainingConfig, save_artifact, train_model
from app.data_sources.bpjs_csv import BPJS_CSV_MAPPING_VERSION, BPJS_CSV_SCHEMA_VERSION, is_bpjs_csv, parse_bpjs_csv
from app.data_sources.synthetic_csv import CsvImportError
from tests.test_analysis_runs import call, create_run, operator_session, setup, verifier_session
from tests.test_ml_model import _records

COLUMNS = ("PSTV01", "FKL02", "FKL03", "FKL04", "FKL05", "FKL06", "FKL07", "FKL08", "FKL09", "FKL13",
           "FKL16", "FKL18", "FKL19", "FKL30", "FKL31", "FKL32", "FKL47")


def _rows(count=240, seed=8):
    """Canonical example records written back in BPJS column names."""
    rows = []
    for index, record in enumerate(_records(count, seed=seed, start=date(2024, 3, 4), prefix="x")):
        rows.append({
            "PSTV01": f"SYN{int(record['participant_token'][-5:]):07d}", "FKL02": f"SYNV{index:07d}",
            "FKL03": record["service_date"], "FKL04": record["discharge_date"],
            "FKL05": "31", "FKL06": "3171", "FKL07": "9", "FKL08": "1", "FKL09": "2" if index % 2 else "3",
            "FKL13": "3", "FKL16": record["admission_diagnosis"], "FKL18": record["primary_diagnosis"],
            "FKL19": record["claim_group"], "FKL30": record["procedure_code"] or "", "FKL31": "1", "FKL32": "1",
            "FKL47": "250000",
        })
    # The same participant, day and codes twice: a repeat-service candidate.
    rows.append(dict(rows[0], FKL02="SYNV9999999"))
    return rows


def _csv(rows, columns=COLUMNS):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(columns), extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode()


def _upload(app, cookies, raw, key="synthetic-bpjs-format"):
    return call(app, "POST", "/api/v1/batches/import", cookies=cookies, content=raw, headers={
        "Content-Type": "text/csv; charset=utf-8", "X-CSRF-Token": cookies["cir_csrf"], "X-Batch-Key": key,
        "X-Synthetic-Schema-Version": BPJS_CSV_SCHEMA_VERSION, "X-Synthetic-Mapping-Version": BPJS_CSV_MAPPING_VERSION,
        "X-Data-Classification": "synthetic_only",
    })


@pytest.fixture(scope="module")
def artifact_dir(tmp_path_factory):
    directory = tmp_path_factory.mktemp("bpjs-upload-artifact")
    save_artifact(train_model(_records(3000, seed=1), TrainingConfig(n_estimators=100, max_samples=256)), directory,
                  {"source_classification": "synthetic_fixture", "date_from": "2024-02-05", "date_to": "2024-02-18"})
    (directory / "category_labels.json").write_text(json.dumps({
        "province_code": {"31": "Provinsi Contoh"}, "municipality_code": {"3171": "Kota Contoh"},
        "facility_ownership": {"9": "Swasta"}, "facility_type": {"1": "Rumah sakit"},
        "facility_class": {"2": "RS Kelas B", "3": "RS Kelas C"}}), encoding="utf-8")
    return directory


def test_the_parser_maps_rows_and_never_keeps_participant_or_visit_numbers():
    raw = _csv(_rows())
    assert is_bpjs_csv(raw) and not is_bpjs_csv(b"claim_id,case_id\n")
    records, summary = parse_bpjs_csv(raw)
    assert summary["error_count"] == 0 and summary["row_count"] == len(records) == 241
    stored = json.dumps(records)
    assert "SYN0" not in stored and "SYNV" not in stored
    assert all(record["claim_id"] == record["case_id"] and record["case_id"].startswith("case_") for record in records)
    # The same file maps to the same references (stable across daily uploads).
    assert [r["case_id"] for r in parse_bpjs_csv(raw)[0]] == [r["case_id"] for r in records]


@pytest.mark.parametrize("change, code", [
    (lambda rows, cols: (rows, cols + ("FKL48",)), "post_verification_amount_forbidden"),
    (lambda rows, cols: (rows, tuple(c for c in cols if c != "FKL03")), "missing_required_column"),
    (lambda rows, cols: ([dict(rows[0], PSTV01="0001234567")] + rows[1:], cols), "real_participant_not_allowed"),
    (lambda rows, cols: ([rows[0], dict(rows[0])] + rows[2:], cols), "duplicate_visit"),
    (lambda rows, cols: (rows, cols + ("is_anomaly",)), "ground_truth_column_forbidden"),
])
def test_unsafe_or_real_files_are_rejected_whole_without_echoing_values(change, code):
    rows, columns = change(_rows(), COLUMNS)
    with pytest.raises(CsvImportError) as raised:
        parse_bpjs_csv(_csv(rows, columns))
    summary = raised.value.summary
    assert summary["error_counts"].get(code), summary
    assert "0001234567" not in json.dumps(summary)


def test_an_uploaded_bpjs_file_runs_with_the_trained_ai_and_named_facility_groups(tmp_path, monkeypatch, artifact_dir):
    monkeypatch.setenv(MODEL_DIR_VARIABLE, str(artifact_dir))
    from app.analytics.ml_model import _category_labels_from
    _category_labels_from.cache_clear()
    app, _batch_db, users = setup(tmp_path)
    operator, verifier = operator_session(app, users), verifier_session(app, users)
    uploaded = _upload(app, operator, _csv(_rows()))
    assert uploaded.status_code == 201, uploaded.text
    batch = uploaded.json()["batch"]
    assert batch["status"] == "ready" and batch["row_count"] == 241

    created = create_run(app, operator, batch["batch_id"])
    assert created.status_code == 201, created.text
    run_id = created.json()["run"]["run_id"]
    detail = call(app, "GET", f"/api/v1/runs/{run_id}?view=summary", cookies=verifier)
    assert detail.status_code == 200
    result = detail.json()["result"]
    assert result["ml_anomaly"]["mode"] == "pretrained_artifact"
    assert result["data_source"]["kind"] == "synthetic"
    summaries = {item["code"]: item for item in result["indicators"]}
    for code in ("similar_claim_pattern_candidate", "synthetic_capacity_candidate", "temporal_pattern_candidate",
                 "supporting_evidence_completeness_candidate"):
        assert summaries[code]["status"] == "not_applicable"
    assert summaries["repeat_billing_candidate"]["candidate_count"] >= 1
    groups = result["facility_groups"]["groups"]
    assert groups and groups[0]["region"] == "Kota Contoh, Provinsi Contoh"
    assert groups[0]["title"] in {"RS Kelas B · Swasta", "RS Kelas C · Swasta"}
    body = detail.text + call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier).text
    import re
    leaks = sorted({match for match in re.findall(r".{40}(?:SYN0|SYNV|participant_[0-9a-f]{32}).{20}", body)})
    assert not leaks, leaks[:3]


def test_a_real_export_is_refused_at_upload(tmp_path):
    app, _batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    rows = [dict(row, PSTV01=f"{index:010d}") for index, row in enumerate(_rows(40))]
    response = _upload(app, operator, _csv(rows), key="synthetic-real-attempt")
    assert response.status_code == 201
    batch = response.json()["batch"]
    assert batch["status"] == "rejected"
    assert batch["validation"]["error_counts"]["real_participant_not_allowed"] == 41
    assert "0000000001" not in response.text
