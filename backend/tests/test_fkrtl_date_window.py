"""Phase 2: admission-date window, pseudonym-key independence, FKL30 blanks, budget counts.

Every `.dta` file is a generated synthetic fixture in tmp_path. Expected outcomes
are kept in the tests (or explicit maps), never as input feature columns.
"""

from datetime import date, datetime
import random

import pytest

from app.analytics.near_duplicate_claims import NearDuplicateConfig, detect_near_duplicate_claims
from app.analytics.repeat_billing import AMOUNT_WITHHELD_SIGNATURE_FIELDS, detect_repeat_billing_candidates
from app.analytics.risk_scoring import score_claims
from tests.test_analysis_runs import call, operator_session, setup, verifier_session
from tests.test_fkrtl_local_source import _create_fkrtl_run, _row, configured  # noqa: F401

pd = pytest.importorskip("pandas")

from scripts.fkrtl_dta_provider import LocalFkrtlDtaProvider  # noqa: E402

KEY_A = bytes.fromhex("ab" * 32)
KEY_B = bytes.fromhex("5e" * 32)
WINDOW = (date(2024, 3, 4), date(2024, 3, 10))


def _write(tmp_path, rows, name="fixture.dta"):
    path = tmp_path / name
    pd.DataFrame(rows).to_stata(path, write_index=False)
    return path


def _load(path, key=KEY_A, window=WINDOW, chunk_size=50_000, max_rows=None):
    return LocalFkrtlDtaProvider(
        path, case_reference_secret=key, source_classification="synthetic_fixture",
        chunk_size=chunk_size, date_window=window, max_rows=max_rows,
    ).load()


def _visit_rows():
    """Inside-window rows, with a repeat pair split far apart in file order."""
    rows = [_row(PSTV01=7000001, FKL02="v-dup-a", FKL03=datetime(2024, 3, 6))]
    rows += [_row(PSTV01=7100000 + i, FKL02=f"v-out-{i}", FKL03=datetime(2024, 2, 1 + i % 20)) for i in range(30)]
    rows += [
        _row(PSTV01=7000002, FKL02="v-first", FKL03=datetime(2024, 3, 4)),   # boundary: first day
        _row(PSTV01=7000003, FKL02="v-last", FKL03=datetime(2024, 3, 10)),   # boundary: last day
        _row(PSTV01=7000004, FKL02="v-before", FKL03=datetime(2024, 3, 3)),  # one day before
        _row(PSTV01=7000005, FKL02="v-after", FKL03=datetime(2024, 3, 11)),  # one day after
    ]
    rows.append(_row(PSTV01=7000001, FKL02="v-dup-b", FKL03=datetime(2024, 3, 6)))
    return rows


def _positions(dataset):
    """Key-independent reference: case ID -> input position (file order)."""
    return {row["case_id"]: index for index, row in enumerate(dataset.records)}


# 1-3. Window boundaries, separated duplicates, file-order and chunk invariance

def test_window_bounds_are_inclusive_and_exclusions_are_counted(tmp_path):
    dataset = _load(_write(tmp_path, _visit_rows()))
    selection = dataset.source_metadata["selection"]
    assert len(dataset.records) == 4  # dup-a, first, last, dup-b
    assert {row["service_date"] for row in dataset.records} == {"2024-03-04", "2024-03-06", "2024-03-10"}
    assert selection == {
        "strategy": "admission_date_window", "date_from": "2024-03-04", "date_to": "2024-03-10",
        "bounds_inclusive": True, "date_field": "FKL03", "rows_scanned": 36, "eligible_rows": 4,
        "processed_rows": 4, "excluded_outside_window": 32, "excluded_invalid_date": 0, "row_cap": None,
    }


def test_duplicate_pair_far_apart_in_file_order_is_detected_inside_window(tmp_path):
    dataset = _load(_write(tmp_path, _visit_rows()), chunk_size=5)
    result = detect_repeat_billing_candidates(dataset.records, AMOUNT_WITHHELD_SIGNATURE_FIELDS)
    positions = _positions(dataset)
    groups = [sorted(positions[case_id] for case_id in group["case_ids"]) for group in result["candidate_groups"]]
    assert groups == [[0, 3]]  # first and last selected rows: the split pair


@pytest.mark.parametrize("chunk_size", [1, 3, 50_000])
def test_selection_is_invariant_to_file_order_and_chunk_size(tmp_path, chunk_size):
    rows = _visit_rows()
    shuffled = rows[:]
    random.Random(7).shuffle(shuffled)
    base = _load(_write(tmp_path, rows, "ordered.dta"))
    other = _load(_write(tmp_path, shuffled, "shuffled.dta"), chunk_size=chunk_size)
    assert {row["case_id"] for row in base.records} == {row["case_id"] for row in other.records}
    assert base.source_metadata["selection"] == other.source_metadata["selection"]


# 4. Cap exceeded fails visibly

def test_window_above_cap_raises_with_full_count_instead_of_truncating(tmp_path):
    from scripts.fkrtl_dta_reader import FkrtlWindowExceedsCap

    with pytest.raises(FkrtlWindowExceedsCap) as error:
        _load(_write(tmp_path, _visit_rows()), chunk_size=2, max_rows=3)
    assert (error.value.eligible_rows, error.value.max_rows) == (4, 3)


def test_missing_date_window_configuration_is_actionable(tmp_path, configured, monkeypatch):
    monkeypatch.delenv("BPJS_FKRTL_DATE_TO")
    app, _, users = setup(tmp_path)
    operator = operator_session(app, users)
    status = call(app, "GET", "/api/v1/sources/fkrtl-local", cookies=operator).json()
    assert status["available"] is False
    assert "FKRTL_DATE_WINDOW_NOT_CONFIGURED" in {item["code"] for item in status["issues"]}
    response = _create_fkrtl_run(app, operator)
    assert response.status_code == 503 and response.json()["error"]["code"] == "FKRTL_DATE_WINDOW_NOT_CONFIGURED"


# 5. Run metadata describes the window and coverage

def test_run_metadata_records_window_bounds_and_counts(tmp_path, configured, monkeypatch):
    monkeypatch.setenv("BPJS_FKRTL_DATE_FROM", "2024-03-04")
    monkeypatch.setenv("BPJS_FKRTL_DATE_TO", "2024-03-04")
    app, batch_db, users = setup(tmp_path)
    run = _create_fkrtl_run(app, operator_session(app, users)).json()["run"]
    selection = run["configuration"]["source"]["selection"]
    assert (selection["date_from"], selection["date_to"], selection["bounds_inclusive"]) == ("2024-03-04", "2024-03-04", True)
    assert (selection["rows_scanned"], selection["processed_rows"], selection["excluded_outside_window"]) == (4, 3, 1)
    result = call(app, "GET", f"/api/v1/runs/{run['run_id']}", cookies=verifier_session(app, users)).json()["result"]
    assert result["records_considered"] == selection["processed_rows"]
    assert any("2024-03-04 to 2024-03-04" in text for text in result["data_source"]["limitations"])


# 6. Pseudonymization key independence

def _dense_rows():
    """One dense admission date (block > budget) plus a sparse date with one cross-participant pair."""
    rows = [
        _row(PSTV01=8100000 + i, FKL02=f"d-{i}", FKL03=datetime(2024, 3, 5),
             FKL18="SYN02" if i % 3 else "SYN05", FKL30="SYNPROC" if i % 4 else "SYNPROC2")
        for i in range(40)
    ]
    rows += [_row(PSTV01=8200001, FKL02="s-1", FKL03=datetime(2024, 3, 9), FKL18="SYN77", FKL19="SYN-CBG-7"),
             _row(PSTV01=8200002, FKL02="s-2", FKL03=datetime(2024, 3, 9), FKL18="SYN77", FKL19="SYN-CBG-7")]
    return rows


def _near_summary(dataset, config):
    result = detect_near_duplicate_claims(dataset.records, config)
    positions = _positions(dataset)
    scored = score_claims(dataset.records, {"near_duplicate_claim_candidate": result})
    coverage = next(item for item in scored["detector_coverage"] if item["indicator"] == "near_duplicate_claim_candidate")
    return {
        "pairs": sorted(tuple(sorted(positions[c] for c in cand["case_ids"])) for cand in result["candidates"]),
        "unassessed": sorted(positions[c] for c in result["unassessed_case_ids"]),
        "comparisons": result["pair_comparisons"],
        "truncated": result["search_truncated"],
        "coverage": (coverage["assessed_case_count"], coverage["not_assessed_case_count"]),
    }


@pytest.mark.parametrize("budget", [3, 25, 5000])
def test_near_duplicate_outcomes_do_not_depend_on_the_pseudonym_key(tmp_path, budget):
    path = _write(tmp_path, _dense_rows())
    config = NearDuplicateConfig(max_pair_comparisons=budget)
    summary_a = _near_summary(_load(path, key=KEY_A), config)
    summary_b = _near_summary(_load(path, key=KEY_B), config)
    assert summary_a == summary_b
    if budget == 3:
        assert summary_a["truncated"] or summary_a["unassessed"]


def test_repeat_outcomes_do_not_depend_on_the_pseudonym_key(tmp_path):
    path = _write(tmp_path, _visit_rows())
    groups = []
    for key in (KEY_A, KEY_B):
        dataset = _load(path, key=key)
        positions = _positions(dataset)
        result = detect_repeat_billing_candidates(dataset.records, AMOUNT_WITHHELD_SIGNATURE_FIELDS)
        groups.append(sorted(tuple(sorted(positions[c] for c in g["case_ids"])) for g in result["candidate_groups"]))
    assert groups[0] == groups[1] == [(0, 3)]


# 7. FKL30 blank: meaning unverified, so the record stays unassessed

@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_fkl30_is_missing_and_unassessed_not_a_procedure_value(tmp_path, blank):
    rows = [_row(PSTV01=7300001, FKL02="b-1", FKL03=datetime(2024, 3, 6), FKL30=blank),
            _row(PSTV01=7300001, FKL02="b-2", FKL03=datetime(2024, 3, 6), FKL30=blank)]
    dataset = _load(_write(tmp_path, rows))
    assert all(row["procedure_code"] is None for row in dataset.records)
    result = detect_repeat_billing_candidates(dataset.records, AMOUNT_WITHHELD_SIGNATURE_FIELDS)
    assert result["candidate_groups"] == []  # two identical blank-procedure visits are NOT matched
    assert {tuple(item["missing_attributes"]) for item in result["ineligible_cases"]} == {("procedure_code",)}
    scored = score_claims(dataset.records, {"repeat_billing_candidate": result})
    coverage = next(item for item in scored["detector_coverage"] if item["indicator"] == "repeat_billing_candidate")
    assert (coverage["assessed_case_count"], coverage["not_assessed_case_count"]) == (0, 2)


# 8. Candidate, assessed, unassessed and truncation counts

def test_dense_and_sparse_dates_report_consistent_counts(tmp_path):
    dataset = _load(_write(tmp_path, _dense_rows()))
    total = len(dataset.records)
    tight = _near_summary(dataset, NearDuplicateConfig(max_pair_comparisons=3))
    roomy = _near_summary(dataset, NearDuplicateConfig(max_pair_comparisons=5000, max_block_size=100))
    for summary in (tight, roomy):
        assessed, unassessed = summary["coverage"]
        assert assessed + unassessed == total
        assert summary["comparisons"] <= (3 if summary is tight else 5000)
    assert tight["unassessed"]  # the dense date cannot be finished within 3 comparisons
    assert not roomy["truncated"] and roomy["unassessed"] == []
    assert (40, 41) in roomy["pairs"]  # the sparse-date cross-participant pair


def test_records_that_can_never_match_do_not_consume_the_comparison_budget(tmp_path):
    rows = _dense_rows()[:6]
    base = _near_summary(_load(_write(tmp_path, rows, "base.dta")), NearDuplicateConfig())
    impossible = [_row(PSTV01=8900000 + i, FKL02=f"x-{i}", FKL03=datetime(2024, 3, 5), FKL30="", FKL16="")
                  for i in range(5)]
    extended = _near_summary(_load(_write(tmp_path, rows + impossible, "extended.dta")), NearDuplicateConfig())
    assert extended["comparisons"] == base["comparisons"]
    assert extended["pairs"] == base["pairs"]
