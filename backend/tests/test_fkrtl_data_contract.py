"""P0: FKRTL adapter data contract on generated synthetic `.dta` fixtures (no BPJS data)."""

from datetime import datetime
import json
import random

import pytest

pd = pytest.importorskip("pandas")

from app.analytics.ml_anomaly import feature_catalog  # noqa: E402
from app.analytics.repeat_definitions import REPEAT_SERVICE_V1, summarize_repeat_patterns  # noqa: E402
from app.data_sources.bpjs_fkrtl_adapter import (  # noqa: E402
    FIELD_CONTRACT, FKRTL_REQUIRED_COLUMNS, FKRTL_SOURCE_COLUMNS, FkrtlMappingError,
)
from app.data_sources.providers import CANONICAL_FEATURE_FIELDS  # noqa: E402
from scripts.fkrtl_dta_provider import LocalFkrtlDtaProvider  # noqa: E402
from scripts.fkrtl_repeat_reconciliation import (  # noqa: E402
    SensitiveOutputError, assert_aggregate_only, build_repeat_reconciliation,
)

KEY = bytes.fromhex("7a" * 32)


def _source_row(index, **overrides):
    row = {
        "PSTV01": 5100000 + index, "FKL02": f"rawvisit-{index:04d}",
        "FKL03": datetime(2024, 3, 4), "FKL04": datetime(2024, 3, 6),
        "FKL05": 11, "FKL06": 1101, "FKL07": 1, "FKL08": 2, "FKL09": 3, "FKL13": 3,
        "FKL16": "SYN01", "FKL18": "SYN02", "FKL19": "SYN-CBG-1", "FKL30": "SYNPROC",
        "FKL31": 2, "FKL32": 40, "FKL47": 1500000,
        "FKL48": 987654321,  # present in the file, never read
    }
    row.update(overrides)
    return row


def _write(tmp_path, rows, name="contract.dta", drop=()):
    frame = pd.DataFrame(rows).drop(columns=list(drop))
    path = tmp_path / name
    frame.to_stata(path, write_index=False)
    return path


def _load(path, chunk_size=50_000):
    return LocalFkrtlDtaProvider(path, case_reference_secret=KEY, source_classification="synthetic_fixture",
                                 chunk_size=chunk_size).load()


def test_columns_map_to_the_documented_record_contract(tmp_path):
    record = _load(_write(tmp_path, [_source_row(1)])).records[0]
    assert (record["care_class"], record["tariff_region"], record["tariff_group"]) == ("3", "2", "40")
    assert (record["service_date"], record["discharge_date"]) == ("2024-03-04", "2024-03-06")
    assert (record["primary_diagnosis"], record["claim_group"], record["procedure_code"]) == ("SYN02", "SYN-CBG-1", "SYNPROC")
    assert record["provider_billed_amount_unverified"] == "1500000"  # plain decimal string, never 0 for missing
    assert record["billed_amount"] is None and record["facility_id"] is None
    assert set(FIELD_CONTRACT) <= set(CANONICAL_FEATURE_FIELDS) | {"case_id"}


@pytest.mark.parametrize("column", FKRTL_REQUIRED_COLUMNS)
def test_missing_required_column_fails_with_its_name(tmp_path, column):
    path = _write(tmp_path, [_source_row(1)], drop=(column,))
    with pytest.raises(FkrtlMappingError, match=column):
        _load(path)


def test_missing_optional_columns_stay_unknown_and_are_reported(tmp_path):
    dataset = _load(_write(tmp_path, [_source_row(1), _source_row(2)], drop=("FKL31", "FKL47", "FKL30")))
    record = dataset.records[0]
    assert record["tariff_region"] is None and record["provider_billed_amount_unverified"] is None
    assert record["procedure_code"] is None  # unknown, not "no procedure"
    coverage = dataset.source_metadata["adapter_coverage"]
    assert {"FKL30", "FKL31", "FKL47"} <= set(coverage["missing_source_columns"])
    assert coverage["field_non_missing_counts"]["provider_billed_amount_unverified"] == 0


def test_invalid_dates_and_amounts_become_unknown_and_are_counted(tmp_path):
    rows = [
        _source_row(1, FKL03="2024-02-30"),             # impossible date
        _source_row(2, FKL04="1899-01-01"),             # implausible discharge date
        _source_row(3, FKL47=-5),                       # negative amount
        _source_row(4, FKL30="", FKL13=None),           # blank procedure, missing class
    ]
    frame_rows = [{**row, "FKL03": str(row["FKL03"])[:10], "FKL04": str(row["FKL04"])[:10]} for row in rows]
    dataset = _load(_write(tmp_path, frame_rows))
    by_visit = {index: record for index, record in enumerate(dataset.records)}
    coverage = dataset.source_metadata["adapter_coverage"]
    assert by_visit[0]["service_date"] is None and coverage["invalid_service_date_count"] == 1
    assert by_visit[1]["discharge_date"] is None and coverage["invalid_discharge_date_count"] == 1
    assert by_visit[2]["provider_billed_amount_unverified"] is None and coverage["invalid_provider_amount_count"] == 1
    assert by_visit[3]["procedure_code"] is None and by_visit[3]["care_class"] is None


def test_fkl48_never_reaches_records_or_features(tmp_path):
    assert "FKL48" not in FKRTL_SOURCE_COLUMNS
    record = _load(_write(tmp_path, [_source_row(1)])).records[0]
    assert "987654321" not in json.dumps(record)
    feature_names = {item["name"] for item in feature_catalog()}
    assert not any("amount" in name or "FKL48" in name or "FKL47" in name for name in feature_names)


def _reconciliation(dataset):
    return build_repeat_reconciliation(dataset.records, adapter_coverage=dataset.source_metadata["adapter_coverage"])


def _repeat_rows():
    rows = [_source_row(i) for i in range(6)]
    rows[1].update(PSTV01=rows[0]["PSTV01"])                       # repeat pair, same amount
    rows[3].update(PSTV01=rows[2]["PSTV01"], FKL47=999)             # repeat pair, differing amount
    rows[5].update(PSTV01=rows[4]["PSTV01"]); rows[4]["FKL30"] = ""; rows[5]["FKL30"] = ""  # blank procedure
    return rows


def test_repeat_counts_are_consistent_across_chunks_and_row_order(tmp_path):
    rows = _repeat_rows()
    shuffled = rows[:]
    random.Random(2).shuffle(shuffled)
    reports = [
        _reconciliation(_load(_write(tmp_path, rows, "a.dta"), chunk_size=size))["repeat_definitions"]
        for size in (1, 4, 50_000)
    ]
    reports.append(_reconciliation(_load(_write(tmp_path, shuffled, "b.dta")))["repeat_definitions"])
    assert all(report == reports[0] for report in reports)
    core, legacy = reports[0]["repeat_service_v1"], reports[0]["legacy_script_repeat_service"]
    assert (core["groups"], core["same_amount_subset"]["groups"], core["ineligible_rows"]) == (2, 1, 2)
    assert legacy["groups"] == 3  # also matches the blank-procedure pair


def test_aggregate_report_is_deterministic_and_leaks_no_identifiers(tmp_path, capsys):
    dataset = _load(_write(tmp_path, _repeat_rows()))
    first, second = _reconciliation(dataset), _reconciliation(dataset)
    first.pop("repeat_seconds"); second.pop("repeat_seconds")
    assert first == second
    raw_values = [str(5100000 + i) for i in range(6)] + [f"rawvisit-{i:04d}" for i in range(6)]
    assert_aggregate_only(first, raw_values)
    text = json.dumps(first, default=str)
    assert all(value not in text for value in raw_values) and "case_" not in text
    assert capsys.readouterr().out == ""  # building the report logs nothing


def test_identifier_guard_rejects_leaks():
    with pytest.raises(SensitiveOutputError):
        assert_aggregate_only({"x": "case_0123456789abcdef"})
    with pytest.raises(SensitiveOutputError):
        assert_aggregate_only({"x": "visit 5100001"}, ["5100001"])


def test_repeat_service_definition_matches_the_record_contract():
    assert set(REPEAT_SERVICE_V1.key_fields) <= set(CANONICAL_FEATURE_FIELDS)
    assert summarize_repeat_patterns([], REPEAT_SERVICE_V1)["groups"] == 0
