"""Unsupervised anomaly ranking on small synthetic canonical fixtures only."""

from datetime import date, datetime, timedelta
import json

import pytest

pytest.importorskip("sklearn")

from app.analytics.ml_anomaly import MlAnomalyConfig, build_ml_anomaly_ranking, feature_catalog
from app.data_sources.providers import FeatureDataset
from app.services.analytics import build_analytics_snapshot_from_dataset
from tests.test_analysis_runs import call, operator_session, setup, verifier_session
from tests.test_fkrtl_local_source import _create_fkrtl_run, _row


def _records(count=120, unusual=("case_unusual_1", "case_unusual_2")):
    rows = []
    for index in range(count):
        start = date(2024, 3, 1) + timedelta(days=index % 20)
        rows.append({
            "case_id": f"case_{index:04d}", "participant_token": f"p{index}",
            "service_date": start.isoformat(), "discharge_date": (start + timedelta(days=2 + index % 2)).isoformat(),
            "province_code": "11", "municipality_code": "1101" if index % 3 else "1102",
            "facility_ownership": "1", "facility_type": "2", "facility_class": "3",
            "admission_diagnosis": "SYN01", "primary_diagnosis": "SYN01" if index % 4 else "SYN02",
            "claim_group": "CBG-A" if index % 2 else "CBG-B", "procedure_code": "P1",
            "billed_amount": "100",
        })
    for case_id in unusual:
        rows.append({
            **rows[0], "case_id": case_id, "participant_token": f"p-{case_id}",
            "discharge_date": "2024-04-20", "admission_diagnosis": "SYN77", "primary_diagnosis": "SYN88",
            "claim_group": "CBG-RARE", "procedure_code": "P9", "facility_class": "9",
        })
    return rows


def test_ranking_is_deterministic_relative_and_explained():
    summary, ranks = build_ml_anomaly_ranking(_records())
    again, _ = build_ml_anomaly_ranking(_records())
    assert summary == again
    assert summary["status"] == "available" and summary["records_scored"] == 122
    assert summary["score_type"] == "relative_unsupervised_anomaly_rank_not_fraud_probability"
    top_ids = [item["case_id"] for item in summary["items"][:2]]
    assert set(top_ids) == {"case_unusual_1", "case_unusual_2"}
    assert summary["items"][0]["top_deviations"]
    assert all("fraud" not in item["description"].lower() for item in summary["items"][0]["top_deviations"])
    # Competition ranks: a rank is 1 + the number of strictly higher scores; ties share it.
    for item in ranks.values():
        higher = sum(other["anomaly_score"] > item["anomaly_score"] for other in ranks.values())
        assert item["rank"] == higher + 1
        assert item["tie_count"] == sum(other["anomaly_score"] == item["anomaly_score"] for other in ranks.values())
    assert any("bukan probabilitas fraud" in text for text in summary["limitations"])


def test_identifiers_and_amounts_do_not_influence_scores():
    base, _ = build_ml_anomaly_ranking(_records())
    changed = _records()
    for index, row in enumerate(changed):
        row["billed_amount"] = str(index * 997)
        row["participant_token"] = f"relabelled-{index}"  # same per-participant counts
    other, _ = build_ml_anomaly_ranking(changed)
    assert [(item["case_id"], item["anomaly_score"]) for item in base["items"]] == [
        (item["case_id"], item["anomaly_score"]) for item in other["items"]
    ]
    names = " ".join(item["name"] for item in feature_catalog())
    assert "amount" not in names and "participant_token" not in names and "case_id" not in names


def test_small_population_is_reported_not_ranked():
    summary, ranks = build_ml_anomaly_ranking(_records(count=10, unusual=()), MlAnomalyConfig(min_records=50))
    assert summary["status"] == "insufficient_data" and summary["items"] == [] and ranks == {}


def test_snapshot_keeps_ml_separate_from_rule_coverage_and_priority():
    records = _records()
    dataset = FeatureDataset(records=records, facilities=(), source_metadata={"kind": "synthetic", "label": "fixture"})
    snapshot = build_analytics_snapshot_from_dataset(dataset)
    assert snapshot["ml_anomaly"]["status"] == "available"
    # Missing facility metadata keeps rule coverage partial and priority not assessable.
    assert snapshot["execution_status"] == "partial"
    assert snapshot["audit_priority"]["status"] != "available"
    assert "ml_anomaly" not in snapshot["risk_scoring"]["weights"]
    for case in snapshot["cases"].values():
        assert case["ml_anomaly"] is None or case["ml_anomaly"]["rank"] >= 1


def test_fkrtl_run_persists_ml_ranking_and_ml_only_case_is_reviewable(tmp_path, monkeypatch):
    pd = pytest.importorskip("pandas")
    rows = [
        _row(PSTV01=8000000 + index, FKL02=f"synvisit-{index}", FKL03=datetime(2024, 3, 1 + index % 20),
             FKL04=datetime(2024, 3, 3 + index % 20), FKL19="SYN-CBG-1" if index % 2 else "SYN-CBG-2")
        for index in range(70)
    ]
    rows.append(_row(PSTV01=8999999, FKL02="synvisit-rare", FKL18="SYN99", FKL19="SYN-CBG-RARE",
                     FKL30="SYNPROC9", FKL04=datetime(2024, 4, 30)))
    path = tmp_path / "synthetic-ml-fixture.dta"
    pd.DataFrame(rows).to_stata(path, write_index=False)
    monkeypatch.setenv("BPJS_FKRTL_SAMPLE_PATH", str(path))
    monkeypatch.setenv("CIR_FKRTL_PSEUDONYM_KEY", "cd" * 32)
    monkeypatch.setenv("BPJS_FKRTL_DATE_FROM", "2024-03-01")
    monkeypatch.setenv("BPJS_FKRTL_DATE_TO", "2024-03-31")
    monkeypatch.delenv("BPJS_FKRTL_MAX_ROWS", raising=False)

    app, _, users = setup(tmp_path)
    created = _create_fkrtl_run(app, operator_session(app, users))
    assert created.status_code == 201, created.text
    run = created.json()["run"]
    # FKRTL runs score with the offline-trained artifact shipped in backend/models (no per-run refit).
    assert run["configuration"]["ml_anomaly"]["model_version"] == "cir-iforest-fkrtl-v2"
    verifier = verifier_session(app, users)
    result = call(app, "GET", f"/api/v1/runs/{run['run_id']}", cookies=verifier).json()["result"]
    ml = result["ml_anomaly"]
    assert ml["status"] == "available" and ml["records_scored"] == 71
    assert ml["mode"] == "pretrained_artifact"
    serialized = json.dumps(ml)
    for forbidden in ("8999999", "synvisit", "SYN99", "SYN-CBG-RARE", "987654321"):
        assert forbidden not in serialized
    ml_only = next(item["case_id"] for item in ml["items"] if item["case_id"] not in result["cases"])
    review = call(app, "PATCH", f"/api/v1/runs/{run['run_id']}/cases/{ml_only}/review", cookies=verifier,
                  json_body={"review_status": "in_review"}, headers={"X-CSRF-Token": verifier["cir_csrf"]})
    assert review.status_code == 200, review.text
    missing = call(app, "GET", f"/api/v1/runs/{run['run_id']}/cases/case_not_ranked/review", cookies=verifier)
    assert missing.status_code == 404
