from datetime import date
import json
import hashlib
import json as json_module

import pytest

from app.analytics.fkrtl_signatures import SIGNATURES, SIGNATURE_SPECS, summarize_signature
from app.data_sources.bpjs_fkrtl_adapter import (
    adapt_fkrtl_rows,
    pseudonymous_case_id,
)
from scripts.fkrtl_dta_reader import iter_fkrtl_dta
from scripts.fkrtl_dta_provider import LocalFkrtlDtaProvider
from scripts.fkrtl_signature_sensitivity import compare_synthetic_signature_sensitivity
from app.data_sources.providers import (
    CanonicalFeatureError,
    FeatureDataset,
    canonicalize_feature_dataset,
)
from app.services.provider_orchestrator import run_provider_analysis


def _row(**overrides):
    row = {
        "PSTV01": "synthetic-member-a", "FKL02": "synthetic-visit-a",
        "FKL03": "2024-03-01", "FKL04": "2024-03-03",
        "FKL05": "SYN-PROV", "FKL06": "SYN-CITY", "FKL07": "public",
        "FKL08": "general", "FKL09": "class-a", "FKL16": "SYN-DX1",
        "FKL18": "SYN-DX2", "FKL19": "SYN-GROUP", "FKL30": "SYN-PROC",
        "FKL47": "1000.00",
    }
    return {**row, **overrides}


def test_signature_profiles_are_explicit_and_measure_distinct_counts():
    a, b, c, d = _row(), _row(FKL02="synthetic-visit-b"), _row(
        PSTV01="synthetic-member-b", FKL02="synthetic-visit-c"
    ), _row(FKL02="synthetic-visit-d")
    b["FKL47"] = "2000"
    rows = [a, b, c, d, _row(FKL18=None)]

    service = summarize_signature(rows, "repeat_service_v1")
    same_amount = summarize_signature(rows, "repeat_service_same_amount_v1", allow_unverified_amount=True)
    legacy = summarize_signature(rows, "legacy_audit_signature_v1", allow_unverified_amount=True)
    cross_person = summarize_signature(rows, "cross_participant_exact_v1", allow_unverified_amount=True)

    assert service["repeated_group_count"] == 1
    assert service["rows_in_repeated_groups"] == 3
    assert service["excess_rows"] == 2
    assert same_amount["repeated_group_count"] == 1
    assert same_amount["rows_in_repeated_groups"] == 2
    assert same_amount["excess_rows"] == 1
    assert legacy["rows_in_repeated_groups"] == 2
    assert cross_person["repeated_group_count"] == 1
    assert cross_person["ineligible_rows"] == 1
    assert set(SIGNATURES["repeat_service_v1"]) == {
        "PSTV01", "FKL03", "FKL18", "FKL19", "FKL30"
    }
    for name, fields in SIGNATURES.items():
        assert SIGNATURE_SPECS[name]["version"] == name
        assert tuple(SIGNATURE_SPECS[name]["signature_fields"]) == fields
        assert set(fields).issubset(SIGNATURE_SPECS[name]["required_fields"])
        assert "PSTV01" in SIGNATURE_SPECS[name]["required_fields"]
        assert SIGNATURE_SPECS[name]["normalization"]
    assert "PSTV01" not in SIGNATURES["cross_participant_exact_v1"]
    assert summarize_signature(
        [a, d], "cross_participant_exact_v1", allow_unverified_amount=True
    )["repeated_group_count"] == 0


def test_signature_sensitivity_harness_uses_same_synthetic_population():
    rows = [
        _row(FKL02="synthetic-visit-a"),
        _row(FKL02="synthetic-visit-b"),
        _row(FKL02="synthetic-visit-c"),
        _row(PSTV01="synthetic-member-b", FKL02="synthetic-visit-d"),
    ]
    report = compare_synthetic_signature_sensitivity(rows)
    baseline = report["baseline"]
    assert baseline["repeat_service_v1"]["rows_in_repeated_groups"] == 3
    assert report["fkl04_changed"]["repeat_service_v1"]["rows_in_repeated_groups"] == 3
    assert report["fkl04_changed"]["legacy_audit_signature_v1"]["rows_in_repeated_groups"] == 2
    assert report["fkl47_changed"]["repeat_service_v1"]["rows_in_repeated_groups"] == 3
    assert report["fkl47_changed"]["repeat_service_same_amount_v1"]["rows_in_repeated_groups"] == 2
    assert report["normalization_variants"]["repeat_service_v1"]["rows_in_repeated_groups"] == 3
    assert report["required_value_missing"]["repeat_service_v1"]["ineligible_rows"] == 1
    assert "synthetic-member" not in json.dumps(report)
    assert "SYN-DX" not in json.dumps(report)


def test_missing_values_are_ineligible_and_no_identifiers_or_signatures_escape():
    with pytest.raises(ValueError, match="explicit synthetic-fixture opt-in"):
        summarize_signature([_row()], "legacy_audit_signature_v1")
    result = summarize_signature(
        [_row(FKL03=" "), _row()], "legacy_audit_signature_v1",
        allow_unverified_amount=True,
    )
    assert result["ineligible_rows"] == 1
    assert "synthetic-member" not in str(result)
    assert "SYN-DX" not in str(result)


def test_fkrtl_mapping_uses_fkl05_dates_and_withholds_unsupported_features():
    rows, coverage = adapt_fkrtl_rows(
        [_row(FKL03=date(2024, 3, 1), FKL05_NEW="wrong-version-name")],
        case_reference_secret=b"synthetic-fixture-secret-32-bytes!",
    )
    record = rows[0]
    assert record["province_code"] == "SYN-PROV"
    assert record["service_date"] == "2024-03-01"
    assert record["facility_id"] is None
    assert record["billed_amount"] is None
    assert record["participant_token"].startswith("participant_")
    assert "synthetic-member-a" not in json.dumps(record)
    assert "FKL02" not in record and "FKL48" not in record
    assert record["case_id"] == pseudonymous_case_id(
        "synthetic-member-a", "synthetic-visit-a", secret=b"synthetic-fixture-secret-32-bytes!"
    )
    assert coverage["billed_amount"] == "withheld_pending_FKL47_semantics_confirmation"
    assert coverage["facility_identity"] == "unavailable"
    assert coverage["ground_truth"] == "not_present"


def test_fkrtl_adapter_marks_invalid_dates_and_does_not_infer_timestamp():
    rows, coverage = adapt_fkrtl_rows(
        [_row(FKL03="not-a-date")],
        case_reference_secret=b"synthetic-fixture-secret-32-bytes!",
    )
    assert rows[0]["service_date"] is None
    assert rows[0]["service_timestamp"] is None
    assert coverage["invalid_service_date_count"] == 1


def test_pseudonymous_case_reference_is_deterministic_and_secret_scoped():
    key = b"synthetic-fixture-secret-32-bytes!"
    first = pseudonymous_case_id("synthetic-person-a", "synthetic-visit-a", secret=key)
    assert first == pseudonymous_case_id("synthetic-person-a", "synthetic-visit-a", secret=key)
    assert first != pseudonymous_case_id("synthetic-person-b", "synthetic-visit-a", secret=key)
    assert first != pseudonymous_case_id("synthetic-person-a", "synthetic-visit-a", secret=b"other-synthetic-secret-32-bytes!")
    assert "synthetic-visit-a" not in first
    with pytest.raises(ValueError):
        pseudonymous_case_id("synthetic-person-a", "synthetic-visit-a", secret=b"short")


def test_adapter_output_and_signature_aggregate_do_not_expose_source_ids_or_signature():
    records, _ = adapt_fkrtl_rows(
        [_row()], case_reference_secret=b"synthetic-fixture-secret-32-bytes!",
    )
    serialized = json.dumps(records)
    assert "synthetic-visit-a" not in serialized
    assert "participant_" in serialized  # keyed internal comparison token, not the source identifier
    assert "synthetic-member-a" not in serialized
    assert "1000.00" not in serialized
    aggregate = summarize_signature([_row(), _row(FKL02="synthetic-visit-b")], "repeat_service_v1")
    assert "synthetic-member" not in json.dumps(aggregate)
    assert "SYN-DX" not in json.dumps(aggregate)


def test_dta_reader_uses_synthetic_fixture_and_explicit_column_allowlist(tmp_path):
    pd = pytest.importorskip("pandas")
    path = tmp_path / "synthetic-only.dta"
    pd.DataFrame([_row()]).to_stata(path, write_index=False)
    chunks = list(iter_fkrtl_dta(
        path, case_reference_secret=b"synthetic-fixture-secret-32-bytes!", chunk_size=1,
    ))
    assert len(chunks) == 1
    records, coverage = chunks[0]
    assert len(records) == 1
    assert records[0]["province_code"] == "SYN-PROV"
    assert records[0]["billed_amount"] is None
    assert coverage["facility_identity"] == "unavailable"


def test_dta_reader_rejects_duplicate_pseudonymous_case_ids_across_chunks(tmp_path):
    pd = pytest.importorskip("pandas")
    path = tmp_path / "synthetic-duplicate-visit.dta"
    # Same participant+visit in separate chunks must not create ambiguous review IDs.
    duplicate = pd.DataFrame([_row(), _row()])
    duplicate.to_stata(path, write_index=False)
    reader = iter_fkrtl_dta(
        path, case_reference_secret=b"synthetic-fixture-secret-32-bytes!", chunk_size=1,
    )
    next(reader)
    with pytest.raises(ValueError, match="Duplicate visit references"):
        next(reader)
    reader.close()


def test_dta_reader_rejects_duplicate_references_within_a_chunk(tmp_path):
    pd = pytest.importorskip("pandas")
    path = tmp_path / "synthetic-duplicate-in-chunk.dta"
    pd.DataFrame([_row(), _row()]).to_stata(path, write_index=False)
    with pytest.raises(ValueError, match="Duplicate visit references"):
        list(iter_fkrtl_dta(
            path, case_reference_secret=b"synthetic-fixture-secret-32-bytes!", chunk_size=5,
        ))


@pytest.mark.parametrize("chunk_size", [1, 2, 50])
def test_dta_reader_output_is_deterministic_across_chunk_sizes(tmp_path, chunk_size):
    pd = pytest.importorskip("pandas")
    path = tmp_path / "synthetic-stable.dta"
    rows = [_row(FKL02=f"synthetic-visit-{index}") for index in range(7)]
    pd.DataFrame(rows).to_stata(path, write_index=False)
    chunks = list(iter_fkrtl_dta(
        path, case_reference_secret=b"synthetic-fixture-secret-32-bytes!", chunk_size=chunk_size,
    ))
    flattened = [record for records, _ in chunks for record in records]
    assert [row["case_id"] for row in flattened] == [
        pseudonymous_case_id(row["PSTV01"], row["FKL02"],
                             secret=b"synthetic-fixture-secret-32-bytes!")
        for row in rows
    ]


def test_reader_rejects_missing_required_references_without_echoing_values():
    with pytest.raises(ValueError, match="Participant and visit references are required") as error:
        adapt_fkrtl_rows(
            [_row(PSTV01=None)], case_reference_secret=b"synthetic-fixture-secret-32-bytes!",
        )
    assert "synthetic-visit-a" not in str(error.value)
    with pytest.raises(ValueError, match="Participant and visit references are required"):
        adapt_fkrtl_rows(
            [_row(FKL02=" ")], case_reference_secret=b"synthetic-fixture-secret-32-bytes!",
        )


def test_reader_scratch_contains_only_digest_and_is_removed_after_exception(tmp_path, monkeypatch):
    pd = pytest.importorskip("pandas")
    import scripts.fkrtl_dta_reader as reader_module

    path = tmp_path / "synthetic-cleanup.dta"
    pd.DataFrame([_row()]).to_stata(path, write_index=False)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    reader = iter_fkrtl_dta(
        path, case_reference_secret=b"synthetic-fixture-secret-32-bytes!",
        chunk_size=1, scratch_directory=scratch,
    )
    next(reader)
    children = list(scratch.iterdir())
    assert len(children) == 1
    db_path = children[0] / "case-digests.sqlite3"
    import sqlite3
    connection = sqlite3.connect(db_path)
    try:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(seen_case_digest)")]
        value = connection.execute("SELECT digest FROM seen_case_digest").fetchone()[0]
    finally:
        connection.close()
    assert columns == ["digest"]
    expected_case_id = pseudonymous_case_id(
        "synthetic-member-a", "synthetic-visit-a",
        secret=b"synthetic-fixture-secret-32-bytes!",
    )
    assert value == hashlib.sha256(expected_case_id.encode()).hexdigest()
    reader.close()
    assert list(scratch.iterdir()) == []


def test_reader_cleans_scratch_storage_when_mapping_raises(tmp_path, monkeypatch):
    pd = pytest.importorskip("pandas")
    import scripts.fkrtl_dta_reader as reader_module

    path = tmp_path / "synthetic-failure.dta"
    pd.DataFrame([_row()]).to_stata(path, write_index=False)
    scratch = tmp_path / "scratch-failure"
    scratch.mkdir()

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic fixture failure")

    monkeypatch.setattr(reader_module, "adapt_fkrtl_rows", fail)
    with pytest.raises(ValueError, match="could not be mapped safely"):
        list(iter_fkrtl_dta(
            path, case_reference_secret=b"synthetic-fixture-secret-32-bytes!",
            scratch_directory=scratch,
        ))
    assert list(scratch.iterdir()) == []


def test_local_dta_provider_runs_analytics_with_source_metadata_and_safe_output(tmp_path):
    pd = pytest.importorskip("pandas")
    path = tmp_path / "synthetic-provider.dta"
    pd.DataFrame([_row(), _row(PSTV01="synthetic-member-b", FKL02="synthetic-visit-b")]).to_stata(
        path, write_index=False,
    )
    provider = LocalFkrtlDtaProvider(
        path, case_reference_secret=b"synthetic-fixture-secret-32-bytes!",
        source_classification="synthetic_fixture", chunk_size=1,
    )
    result = run_provider_analysis(provider)
    serialized = json_module.dumps(result)
    assert result["feature_contract_version"] == "canonical-analytic-features-v1"
    assert result["data_source"]["label"] == "synthetic_fkrtl_fixture"
    assert result["data_source"]["classification"] == "synthetic_fixture"
    assert result["data_source"]["mapping_version"] == "bpjs-fkrtl-sample-map-v1"
    assert result["execution_status"] in {"completed", "partial"}
    assert len(result["coverage"]) == 6
    assert result["score_type"] == "provisional_rule_based_index_not_fraud_probability"
    assert result["audit_priority"]["status"] != "available"
    assert "synthetic-member" not in serialized
    assert "synthetic-visit" not in serialized
    assert "synthetic-fixture-secret" not in serialized
    assert "participant_token" not in serialized
    assert "FKL48" not in serialized
    assert str(path) not in serialized


def test_provider_pipeline_is_deterministic_across_chunk_sizes(tmp_path):
    pd = pytest.importorskip("pandas")
    path = tmp_path / "synthetic-chunk-stability.dta"
    pd.DataFrame([
        _row(),
        _row(PSTV01="synthetic-member-b", FKL02="synthetic-visit-b"),
        _row(PSTV01="synthetic-member-c", FKL02="synthetic-visit-c", FKL30="SYN-PROC-OTHER"),
    ]).to_stata(path, write_index=False)
    key = b"synthetic-fixture-secret-32-bytes!"

    one = run_provider_analysis(LocalFkrtlDtaProvider(
        path, case_reference_secret=key, source_classification="synthetic_fixture", chunk_size=1,
    ))
    many = run_provider_analysis(LocalFkrtlDtaProvider(
        path, case_reference_secret=key, source_classification="synthetic_fixture", chunk_size=50,
    ))

    assert one == many


def test_canonical_contract_rejects_source_columns_and_ground_truth():
    common = {"case_id": "case_synthetic_1", "participant_token": "token_internal"}
    with pytest.raises(CanonicalFeatureError, match="outside the canonical"):
        canonicalize_feature_dataset(FeatureDataset(
            records=[{**common, "PSTV01": "synthetic-member"}], facilities=(),
            source_metadata={"kind": "synthetic", "label": "fixture"},
        ))
    with pytest.raises(CanonicalFeatureError, match="Ground-truth"):
        canonicalize_feature_dataset(FeatureDataset(
            records=[{**common, "is_anomaly": True}], facilities=(),
            source_metadata={"kind": "synthetic", "label": "fixture"},
        ))
    projected = canonicalize_feature_dataset(FeatureDataset(
        records=[{**common, "claim_id": "synthetic-claim-1", "province_code": "SYN"}],
        facilities=(), source_metadata={"kind": "synthetic", "label": "fixture"},
    ))
    assert projected.records[0]["province_code"] == "SYN"
    assert "claim_id" not in projected.records[0]
    assert projected.records[0]["billed_amount"] is None
