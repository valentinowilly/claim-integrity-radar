"""Synthetic-only CSV validation, immutable DataBatch, and API tests."""

import asyncio
import csv
import io
import json
import sqlite3

import httpx
import pytest

from app.data_sources.synthetic_csv import (
    CSV_COLUMNS, REQUIRED_COLUMNS, CsvImportError, SYNTHETIC_CSV_MAPPING_VERSION,
    SYNTHETIC_CSV_SCHEMA_VERSION, export_synthetic_csv, parse_synthetic_csv,
)
from app.data_sources.synthetic_generator import SyntheticGeneratorConfig, generate_synthetic_dataset
from app.main import create_app
from app.security.auth import AuthStore
from app.services.batches import BatchStore
from app.services.reviews import ReviewStore


def synthetic_record(index: int = 1) -> dict:
    return {
        "claim_id": f"syn-claim-{index:06d}", "case_id": f"syn-claim-{index:06d}",
        "facility_id": "syn-facility-0001", "participant_token": f"syn-participant-{index:06d}",
        "service_date": "2024-06-15", "service_timestamp": "2024-06-15T10:30:00",
        "province_code": "SYN-PROV-01", "municipality_code": "SYN-CITY-001",
        "facility_ownership": "synthetic_public", "facility_type": "synthetic_general",
        "facility_class": "synthetic-class-1", "admission_diagnosis": "SYN-ADM-0001",
        "primary_diagnosis": "SYN-DX-0001", "claim_group": "SYN-GROUP-01",
        "procedure_code": "SYN-PROC-001", "billed_amount": "125000.00",
        "service_type": "outpatient", "service_units": 1, "facility_daily_capacity": 40,
        "facility_daily_claim_count": 2, "supporting_evidence_required": ["clinical_note"],
        "supporting_evidence_types": ["clinical_note"], "supporting_evidence_present": True,
        "supporting_evidence_recording_status": "recorded",
    }


def payload(records: list[dict], columns=CSV_COLUMNS) -> bytes:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for record in records:
        row = {}
        for name in columns:
            value = record.get(name)
            if isinstance(value, list):
                value = ";".join(value)
            elif isinstance(value, bool):
                value = str(value).lower()
            row[name] = "" if value is None else value
        writer.writerow(row)
    return out.getvalue().encode()


def call(app, method, path, *, content=None, headers=None, cookies=None, json_body=None):
    async def send():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, content=content, headers=headers,
                                        cookies=cookies, json=json_body)
    return asyncio.run(send())


def setup_authenticated(tmp_path):
    auth_db = tmp_path / "auth.sqlite3"
    review_db = tmp_path / "review.sqlite3"
    batch_db = tmp_path / "batches.sqlite3"
    app = create_app(review_db, auth_db, cookie_secure=False, batch_db_path=batch_db)
    store = AuthStore(auth_db)
    admin = store.create_bootstrap_admin(
        "root-admin", "Synthetic-admin-password-2026!", "bootstrap-test-secret", "bootstrap-test-secret",
    )
    operator = store.create_user("synthetic-operator", "Synthetic-operator-password-2026!",
                                 "data_operator", admin["user_id"])
    verifier = store.create_user("synthetic-verifier", "Synthetic-verifier-password-2026!",
                                 "verifikator", admin["user_id"])
    def login(user, password):
        response = call(app, "POST", "/api/v1/auth/login", json_body={"username": user, "password": password})
        return dict(response.cookies.items())
    return app, login(operator["username"], "Synthetic-operator-password-2026!"), \
        login(verifier["username"], "Synthetic-verifier-password-2026!"), operator, batch_db


def import_request(app, cookies, body, *, csrf=True, extra_headers=None):
    headers = {
        "Content-Type": "text/csv; charset=utf-8",
        "X-Batch-Key": "synthetic-fixture",
        "X-Synthetic-Schema-Version": SYNTHETIC_CSV_SCHEMA_VERSION,
        "X-Synthetic-Mapping-Version": SYNTHETIC_CSV_MAPPING_VERSION,
        "X-Data-Classification": "synthetic_only",
    }
    headers.update(extra_headers or {})
    if csrf:
        headers["X-CSRF-Token"] = cookies["cir_csrf"]
    return call(app, "POST", "/api/v1/batches/import", content=body, headers=headers, cookies=cookies)


def test_synthetic_export_round_trip_and_ground_truth_is_not_exported():
    feature = synthetic_record()
    feature["is_synthetic_anomaly"] = True
    feature["scenario_group_id"] = "must-not-be-exported"
    feature["scenario_code"] = "must-not-be-exported-either"
    encoded = export_synthetic_csv([feature])
    assert b"is_synthetic_anomaly" not in encoded
    parsed, summary = parse_synthetic_csv(encoded)
    assert parsed[0]["claim_id"] == "syn-claim-000001"
    assert parsed[0]["supporting_evidence_required"] == ["clinical_note"]
    assert parsed[0]["supporting_evidence_present"] is True
    assert summary["row_count"] == 1


def test_generator_feature_records_fit_csv_schema_without_ground_truth():
    dataset = generate_synthetic_dataset(SyntheticGeneratorConfig(
        seed=991, claim_count=200, facility_count=12, target_anomaly_rate=0.04,
    ))
    encoded = export_synthetic_csv(dataset.records)
    parsed, summary = parse_synthetic_csv(encoded)
    assert len(parsed) == 200 and summary["error_count"] == 0
    assert not any(set(row) & {"is_synthetic_anomaly", "scenario_group_id", "primary_scenario"}
                   for row in parsed)


@pytest.mark.parametrize("raw,code", [
    (b"", "empty_input"), (b"\xff", "invalid_encoding"),
    (b'"unterminated', "malformed_csv"),
])
def test_import_rejects_empty_encoding_and_malformed_input(raw, code):
    with pytest.raises(CsvImportError) as error:
        parse_synthetic_csv(raw)
    assert error.value.summary["error_counts"] == {code: 1}


def test_header_only_csv_is_rejected_as_empty_file():
    with pytest.raises(CsvImportError) as error:
        parse_synthetic_csv((",".join(CSV_COLUMNS) + "\n").encode())
    assert error.value.summary["error_counts"] == {"empty_file": 1}


def test_missing_unexpected_and_ground_truth_columns_are_rejected_safely():
    data = synthetic_record()
    raw = payload([data], columns=tuple(name for name in REQUIRED_COLUMNS if name != "billed_amount") + ("is_anomaly",))
    with pytest.raises(CsvImportError) as error:
        parse_synthetic_csv(raw)
    summary = error.value.summary
    assert summary["error_counts"]["missing_required_column"] == 1
    assert summary["error_counts"]["ground_truth_column_forbidden"] == 1
    assert "125000.00" not in json.dumps(summary)
    assert "syn-participant" not in json.dumps(summary)
    unknown_column_body = payload([synthetic_record()], columns=CSV_COLUMNS + ("local_private_field",))
    with pytest.raises(CsvImportError) as unknown_error:
        parse_synthetic_csv(unknown_column_body)
    assert unknown_error.value.summary["error_counts"] == {"unexpected_column": 1}


def test_optional_columns_may_be_absent_and_are_normalized_to_none():
    data = synthetic_record()
    columns = tuple(name for name in CSV_COLUMNS if name not in {
        "service_timestamp", "facility_daily_claim_count", "supporting_evidence_recording_status",
    })
    parsed, summary = parse_synthetic_csv(payload([data], columns))
    assert parsed[0]["service_timestamp"] is None
    assert parsed[0]["facility_daily_claim_count"] is None
    assert summary["warning_counts"]["optional_columns_missing"] == 3


def test_row_limit_is_aggregated_as_rejection():
    with pytest.raises(CsvImportError) as error:
        parse_synthetic_csv(payload([synthetic_record(1), synthetic_record(2)]), max_rows=1)
    assert error.value.summary["error_counts"] == {"row_limit_exceeded": 1}


def test_invalid_values_duplicate_identifiers_and_error_aggregation_are_safe():
    first = synthetic_record(1)
    second = synthetic_record(1)
    invalid = synthetic_record(2)
    invalid["service_date"] = "not-a-date"
    invalid["billed_amount"] = "sensitive-value"
    with pytest.raises(CsvImportError) as error:
        parse_synthetic_csv(payload([first, second, invalid]))
    summary = error.value.summary
    assert summary["error_counts"]["duplicate_identifier"] >= 1
    assert summary["error_counts"]["invalid_iso_date"] == 1
    assert summary["error_counts"]["invalid_amount"] == 1
    assert "sensitive-value" not in json.dumps(summary)
    assert "syn-participant" not in json.dumps(summary)


def test_store_versions_idempotency_record_persistence_and_immutability(tmp_path):
    store = BatchStore(tmp_path / "batches.sqlite3")
    first_body = export_synthetic_csv([synthetic_record(1), synthetic_record(2)])
    first, reused = store.import_csv(
        first_body, batch_key="synthetic-alpha", creator_user_id="usr_synthetic",
        schema_version=SYNTHETIC_CSV_SCHEMA_VERSION, mapping_version=SYNTHETIC_CSV_MAPPING_VERSION,
    )
    assert first["status"] == "ready"
    assert first["batch_version"] == 1 and not reused
    assert store.get_record_count(first["batch_id"]) == 2
    # Model the planned many-runs-to-one-batch FK without adding AnalysisRun runtime code.
    with sqlite3.connect(store.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "CREATE TABLE future_run_refs(run_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL "
            "REFERENCES data_batches(batch_id))"
        )
        connection.executemany("INSERT INTO future_run_refs VALUES (?, ?)", [
            ("run_synthetic_001", first["batch_id"]), ("run_synthetic_002", first["batch_id"]),
        ])
        assert connection.execute(
            "SELECT COUNT(*) FROM future_run_refs WHERE batch_id=?", (first["batch_id"],)
        ).fetchone()[0] == 2
    same, reused = store.import_csv(
        first_body, batch_key="synthetic-alpha", creator_user_id="usr_synthetic",
        schema_version=SYNTHETIC_CSV_SCHEMA_VERSION, mapping_version=SYNTHETIC_CSV_MAPPING_VERSION,
    )
    assert reused and same["batch_id"] == first["batch_id"]
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM batch_security_audit_events WHERE event_type='batch_import_reused'"
        ).fetchone()[0] == 1

    second, reused = store.import_csv(
        export_synthetic_csv([synthetic_record(1), synthetic_record(3)]), batch_key="synthetic-alpha",
        creator_user_id="usr_synthetic", schema_version=SYNTHETIC_CSV_SCHEMA_VERSION,
        mapping_version=SYNTHETIC_CSV_MAPPING_VERSION,
    )
    assert second["batch_version"] == 2 and second["batch_id"] != first["batch_id"] and not reused
    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE data_batches SET status='rejected' WHERE batch_id=?", (first["batch_id"],))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM data_batch_records WHERE batch_id=?", (first["batch_id"],))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "INSERT INTO data_batch_records VALUES (?, ?, ?, ?)",
                (first["batch_id"], "syn-claim-extra", "syn-claim-extra", "{}"),
            )


def test_rejected_import_is_persisted_without_partial_records_and_next_version_is_distinct(tmp_path):
    store = BatchStore(tmp_path / "batches.sqlite3")
    rejected, _ = store.import_csv(
        b"claim_id,scenario_label\nsyn-claim-000001,hidden\n", batch_key="synthetic-alpha",
        creator_user_id="usr_synthetic", schema_version=SYNTHETIC_CSV_SCHEMA_VERSION,
        mapping_version=SYNTHETIC_CSV_MAPPING_VERSION,
    )
    assert rejected["status"] == "rejected"
    assert store.get_record_count(rejected["batch_id"]) == 0
    ready, _ = store.import_csv(
        export_synthetic_csv([synthetic_record()]), batch_key="synthetic-alpha", creator_user_id="usr_synthetic",
        schema_version=SYNTHETIC_CSV_SCHEMA_VERSION, mapping_version=SYNTHETIC_CSV_MAPPING_VERSION,
    )
    assert ready["batch_version"] == rejected["batch_version"] + 1


def test_schema_and_mapping_changes_create_distinct_rejected_versions(tmp_path):
    store = BatchStore(tmp_path / "batches.sqlite3")
    raw = export_synthetic_csv([synthetic_record()])
    first, _ = store.import_csv(
        raw, batch_key="synthetic-alpha", creator_user_id="usr_synthetic",
        schema_version=SYNTHETIC_CSV_SCHEMA_VERSION, mapping_version=SYNTHETIC_CSV_MAPPING_VERSION,
    )
    unsupported_schema, _ = store.import_csv(
        raw, batch_key="synthetic-alpha", creator_user_id="usr_synthetic",
        schema_version="synthetic-claims-v2", mapping_version=SYNTHETIC_CSV_MAPPING_VERSION,
    )
    unsupported_mapping, _ = store.import_csv(
        raw, batch_key="synthetic-alpha", creator_user_id="usr_synthetic",
        schema_version=SYNTHETIC_CSV_SCHEMA_VERSION, mapping_version="synthetic-canonical-v2",
    )
    assert first["status"] == "ready"
    assert unsupported_schema["status"] == unsupported_mapping["status"] == "rejected"
    assert len({first["batch_id"], unsupported_schema["batch_id"], unsupported_mapping["batch_id"]}) == 3
    assert [first["batch_version"], unsupported_schema["batch_version"],
            unsupported_mapping["batch_version"]] == [1, 2, 3]
    assert store.get_record_count(unsupported_schema["batch_id"]) == 0


def test_batch_api_rbac_csrf_metadata_and_health_isolation(tmp_path):
    app, operator, verifier, operator_user, batch_db = setup_authenticated(tmp_path)
    assert call(app, "GET", "/health").status_code == 200
    assert not batch_db.exists()
    assert call(app, "GET", "/api/v1/batches").status_code == 401

    denied_write = import_request(app, verifier, export_synthetic_csv([synthetic_record()]))
    assert denied_write.status_code == 403
    denied_no_csrf = import_request(app, operator, export_synthetic_csv([synthetic_record()]), csrf=False)
    assert denied_no_csrf.status_code == 403
    invalid_csrf = import_request(app, operator, export_synthetic_csv([synthetic_record()]), csrf=False,
                                  extra_headers={"X-CSRF-Token": "wrong-token"})
    assert invalid_csrf.status_code == 403

    wrong_classification = import_request(
        app, operator, export_synthetic_csv([synthetic_record()]),
        extra_headers={"X-Data-Classification": "bpjs_sample"},
    )
    assert wrong_classification.status_code == 422

    created = import_request(app, operator, export_synthetic_csv([synthetic_record()]))
    assert created.status_code == 201
    batch = created.json()["batch"]
    assert batch["creator_user_id"] == operator_user["user_id"]
    assert "participant_token" not in json.dumps(created.json())
    assert "125000.00" not in json.dumps(created.json())
    assert "content_checksum" not in created.json()["batch"]
    with sqlite3.connect(batch_db) as connection:
        audit_rows = connection.execute(
            "SELECT actor_user_id,event_type,metadata_json FROM batch_security_audit_events"
        ).fetchall()
    assert audit_rows[0][0] == operator_user["user_id"]
    assert audit_rows[0][1] == "batch_imported"
    assert "syn-participant" not in json.dumps(audit_rows)
    assert "125000.00" not in json.dumps(audit_rows)

    listing = call(app, "GET", "/api/v1/batches?limit=5", cookies=verifier)
    assert listing.status_code == 200
    assert listing.json()["total_items"] == 1
    admin = AuthStore(app.state.auth_db_path).create_user(
        "synthetic-admin-reader", "Synthetic-admin-reader-password-2026!", "platform_admin", operator_user["user_id"]
    )
    admin_login = call(app, "POST", "/api/v1/auth/login", json_body={
        "username": admin["username"], "password": "Synthetic-admin-reader-password-2026!",
    })
    admin_cookies = dict(admin_login.cookies.items())
    assert call(app, "GET", "/api/v1/batches", cookies=admin_cookies).status_code == 200
    assert import_request(app, admin_cookies, export_synthetic_csv([synthetic_record(30)]), csrf=False).status_code == 403
    assert import_request(app, admin_cookies, export_synthetic_csv([synthetic_record(3)])).status_code == 201
    lead = AuthStore(app.state.auth_db_path).create_user(
        "synthetic-audit-lead", "Synthetic-audit-lead-password-2026!", "audit_lead", operator_user["user_id"]
    )
    lead_login = call(app, "POST", "/api/v1/auth/login", json_body={
        "username": lead["username"], "password": "Synthetic-audit-lead-password-2026!",
    })
    lead_cookies = dict(lead_login.cookies.items())
    assert call(app, "GET", "/api/v1/batches", cookies=lead_cookies).status_code == 200
    assert import_request(app, lead_cookies, export_synthetic_csv([synthetic_record(4)])).status_code == 403
    detail = call(app, "GET", f"/api/v1/batches/{batch['batch_id']}", cookies=verifier)
    assert detail.status_code == 200
    missing = call(app, "GET", "/api/v1/batches/bat_unknown", cookies=operator)
    assert missing.status_code == 404
    assert "participant_token" not in json.dumps(detail.json())

    # Batch creation is additive and leaves existing auth and review records intact.
    assert call(app, "GET", "/api/v1/auth/me", cookies=operator).status_code == 200
    review_store = ReviewStore(app.state.review_db_path)
    review_store.update_review("syn-normal-001", "needs_more_evidence", "Synthetic only.",
                               "usr_existing", "existing-reviewer")
    another = import_request(app, operator, export_synthetic_csv([synthetic_record(2)]),
                             extra_headers={"X-Batch-Key": "synthetic-second"})
    assert another.status_code == 201
    assert review_store.get_review("syn-normal-001")["status"] == "needs_more_evidence"


def test_upload_byte_limit_is_configurable_and_rejected_before_storage(tmp_path, monkeypatch):
    app, operator, _, _, batch_db = setup_authenticated(tmp_path)
    monkeypatch.setenv("CIR_BATCH_MAX_BYTES", "1024")
    too_large = import_request(app, operator, b"x" * 1025)
    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "UPLOAD_TOO_LARGE"
    assert not batch_db.exists()
