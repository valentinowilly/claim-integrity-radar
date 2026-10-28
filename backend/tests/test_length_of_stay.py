"""Phase 5: exploratory peer-relative duration screen (synthetic fixtures only)."""

from datetime import date, datetime, timedelta
import random

import pytest

from app.analytics.length_of_stay import (
    LengthOfStayConfig, detect_length_of_stay_outliers, nearest_rank_threshold,
)
from app.data_sources.providers import FeatureDataset
from app.services import analytics as analytics_service

START = date(2024, 3, 4)


def _row(index, span, *, cbg="G1", care="3", participant=None, start=START, **overrides):
    row = {
        "case_id": f"case_{index:05d}", "participant_token": participant or f"p{index}",
        "service_date": start.isoformat(), "discharge_date": (start + timedelta(days=span)).isoformat(),
        "claim_group": cbg, "care_class": care,
    }
    row.update(overrides)
    return row


def _ordinary(count=100, offset=0, **kwargs):
    return [_row(offset + i, i % 5, **kwargs) for i in range(count)]  # spans 0..4


def _flagged(result):
    return {item["case_id"] for item in result["candidates"]}


def test_nearest_rank_threshold_definition():
    spans = list(range(1, 101))
    assert nearest_rank_threshold(spans, 0.99) == 99  # position ceil(99.0) = 99
    assert nearest_rank_threshold(list(range(1, 102)), 0.99) == 100  # ceil(99.99) = 100


def test_planted_upper_tail_is_flagged_and_explained():
    records = _ordinary() + [_row(900, 20)]
    result = detect_length_of_stay_outliers(records)
    assert _flagged(result) == {"case_00900"}
    candidate = result["candidates"][0]
    assert candidate["span_days"] == 20 and candidate["peer_support"] == 101
    assert candidate["peer_threshold_days"] == 4 and candidate["peer_median_days"] == 2
    assert candidate["share_of_peers_with_shorter_span"] == 0.9901  # 100 of 101 peers (itself excluded)
    assert "INA-CBG dan kelas rawat" in candidate["explanation"] and "bukan bukti fraud" in candidate["explanation"]


def test_ordinary_durations_are_negative_controls():
    result = detect_length_of_stay_outliers(_ordinary(300))
    assert result["candidate_count"] == 0 and result["assessed_count"] == 300


def test_legitimate_long_stay_is_flagged_statistically_but_framed_as_not_evidence():
    # A clinically justified long stay looks identical to the screen: it is a statistical
    # signal for review, so being flagged is expected and is not a fraud finding.
    records = _ordinary() + [_row(901, 25)]
    result = detect_length_of_stay_outliers(records)
    assert _flagged(result) == {"case_00901"}
    assert any("bukan bukti fraud" in text for text in result["limitations"])


def test_missing_invalid_reversed_and_same_day_dates():
    records = _ordinary() + [
        _row(950, 3, discharge_date=None),
        _row(951, 3, discharge_date="2024-13-40"),
        _row(952, 0, discharge_date=(START - timedelta(days=2)).isoformat()),
        _row(953, 0),  # same day
        _row(954, 3, claim_group=None),
    ]
    result = detect_length_of_stay_outliers(records)
    counts = result["unassessed_reason_counts"]
    assert (counts["missing_date"], counts["invalid_date"], counts["reversed_dates"], counts["missing_peer_key"]) == (1, 1, 1, 1)
    assert "case_00953" not in _flagged(result)
    assert result["assessed_count"] == 101  # 100 ordinary + the same-day record


def test_same_day_spans_are_never_candidates_even_with_a_zero_threshold():
    records = [_row(i, 0) for i in range(120)] + [_row(990, 1)]
    result = detect_length_of_stay_outliers(records)
    assert _flagged(result) == {"case_00990"}  # threshold 0: only a span of at least 1 day qualifies


def test_insufficient_peer_support_is_unassessed_with_reason():
    records = _ordinary(98) + [_row(960, 30)]  # 99 < minimum 100
    result = detect_length_of_stay_outliers(records)
    assert result["candidate_count"] == 0 and result["assessed_count"] == 0
    assert result["unassessed_reason_counts"]["insufficient_peer_support"] == 99
    assert result["peer_groups_below_support"] == 1 and result["status"] == "insufficient_data"


def test_values_tied_at_the_threshold_are_not_flagged():
    records = _ordinary(95) + [_row(970 + i, 10) for i in range(5)]  # top 5 tie at 10
    result = detect_length_of_stay_outliers(records)
    assert result["candidates"] == [] and result["assessed_count"] == 100


def test_peer_groups_are_independent():
    long_group = [_row(2000 + i, 7 + i % 6, cbg="G9", care="1") for i in range(120)]  # typical 7..12
    records = _ordinary() + long_group + [_row(980, 12)]  # 12 days: extreme for G1/3
    result = detect_length_of_stay_outliers(records)
    assert _flagged(result) == {"case_00980"}  # the same span is ordinary in the G9/1 group
    assert result["peer_groups_assessed"] == 2


def test_exact_copies_count_once_in_the_reference():
    target = _row(990, 20, participant="same-person")
    copies = [{**target, "case_id": f"case_0099{i}"} for i in range(1, 4)]
    result = detect_length_of_stay_outliers(_ordinary() + [target] + copies)
    assert {item["peer_support"] for item in result["candidates"]} == {101}
    assert len(result["candidates"]) == 4  # every copy is still evaluated and reported


def test_results_are_stable_under_row_permutations():
    records = _ordinary(200) + [_row(900, 20), _row(901, 15, cbg="G2")] + _ordinary(100, offset=500, cbg="G2")
    shuffled = records[:]
    random.Random(3).shuffle(shuffled)
    first, second = detect_length_of_stay_outliers(records), detect_length_of_stay_outliers(shuffled)
    assert _flagged(first) == _flagged(second) == {"case_00900", "case_00901"}
    assert {k: v for k, v in first.items() if k != "candidates"} == {k: v for k, v in second.items() if k != "candidates"}


def test_counts_reconcile():
    records = _ordinary() + [_row(900, 20), _row(950, 3, discharge_date=None)] + _ordinary(10, offset=300, cbg="SMALL")
    result = detect_length_of_stay_outliers(records)
    assert result["assessed_count"] + result["unassessed_count"] == result["input_record_count"] == len(records)
    assert result["candidate_count"] == len(result["candidates"]) == 1
    assert result["candidates_per_1000_assessed"] == round(1 / 101 * 1000, 2)


def test_config_is_validated():
    with pytest.raises(ValueError):
        LengthOfStayConfig(upper_percentile=1.0)


def test_duration_screen_does_not_change_rule_risk_or_priority(monkeypatch):
    records = [{**row, "province_code": "11", "municipality_code": "1101", "facility_ownership": "1",
                "facility_type": "2", "facility_class": "3", "admission_diagnosis": "A01",
                "primary_diagnosis": f"D{row['case_id'][-1]}", "procedure_code": "P1", "billed_amount": None}
               for row in _ordinary() + [_row(900, 20)]]
    dataset = FeatureDataset(records=records, facilities=(), source_metadata={"kind": "synthetic", "label": "fixture"})
    with_los = analytics_service.build_analytics_snapshot_from_dataset(dataset)
    assert with_los["length_of_stay"]["candidate_count"] == 1
    monkeypatch.setattr(analytics_service, "detect_length_of_stay_outliers",
                        lambda source_records: {"indicator": "length_of_stay_outlier", "candidates": []})
    without_los = analytics_service.build_analytics_snapshot_from_dataset(dataset)
    view = lambda snap: {cid: (c["risk_score"], c["score_status"], c["indicators"]) for cid, c in snap["cases"].items()}  # noqa: E731
    assert view(with_los) == view(without_los)
    assert with_los["audit_priority"] == without_los["audit_priority"]
    assert with_los["risk_scoring"] == without_los["risk_scoring"]
    assert with_los["execution_status"] == without_los["execution_status"]


def test_duration_only_candidate_is_reviewable_through_the_api(tmp_path, monkeypatch):
    pd = pytest.importorskip("pandas")
    from tests.test_analysis_runs import call, operator_session, setup, verifier_session
    from tests.test_fkrtl_local_source import _create_fkrtl_run, _row as fkrtl_row

    rows = [fkrtl_row(PSTV01=6000000 + i, FKL02=f"los-{i}", FKL03=datetime(2024, 3, 4),
                      FKL04=datetime(2024, 3, 4 + i % 4), FKL18=f"SYN{i % 7}", FKL30="")
            for i in range(110)]
    # Three attributes differ from every other claim, so the long stay has no similar-claim match
    # (a single different diagnosis would match 8 of 9 attributes under the complete blocking);
    # INA-CBG and class of care stay equal so its duration peer group is unchanged.
    rows.append(fkrtl_row(PSTV01=6999999, FKL02="los-long", FKL03=datetime(2024, 3, 4),
                          FKL04=datetime(2024, 3, 30), FKL30="", FKL18="SYN99", FKL16="SYN98", FKL07=9))
    path = tmp_path / "synthetic-los.dta"
    pd.DataFrame(rows).to_stata(path, write_index=False)
    for name, value in (("BPJS_FKRTL_SAMPLE_PATH", str(path)), ("CIR_FKRTL_PSEUDONYM_KEY", "ef" * 32),
                        ("BPJS_FKRTL_DATE_FROM", "2024-03-01"), ("BPJS_FKRTL_DATE_TO", "2024-03-31")):
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("BPJS_FKRTL_MAX_ROWS", raising=False)
    app, _, users = setup(tmp_path)
    run = _create_fkrtl_run(app, operator_session(app, users)).json()["run"]
    verifier = verifier_session(app, users)
    result = call(app, "GET", f"/api/v1/runs/{run['run_id']}", cookies=verifier).json()["result"]
    los = result["length_of_stay"]
    assert los["candidate_count"] == 1 and los["assessed_count"] == 111
    case_id = los["candidates"][0]["case_id"]
    assert case_id not in result["cases"]  # no rule signal: reviewable only via the duration screen
    review = call(app, "PATCH", f"/api/v1/runs/{run['run_id']}/cases/{case_id}/review", cookies=verifier,
                  json_body={"review_status": "in_review"}, headers={"X-CSRF-Token": verifier["cir_csrf"]})
    assert review.status_code == 200
    assert run["configuration"]["length_of_stay"]["version"] == "los-peer-p99-v1"
