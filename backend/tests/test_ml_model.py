"""Offline-trained anomaly model: shared features, artifact round trip and run integration (synthetic only)."""

from datetime import date, timedelta
import json
import random

import pytest

from app.analytics import ml_model
from app.analytics.ml_model import (
    FEATURE_NAMES, MIN_REFERENCE_COUNT, MODEL_DIR_VARIABLE, ModelArtifactError, TrainingConfig,
    build_features, fit_reference, load_artifact, save_artifact, score_records, train_model,
)
from app.data_sources.fkrtl_local_source import FKRTL_SCHEMA_PROFILE
from app.services.analytics import build_analytics_snapshot

GROUPS = [("SYN-DX-A", "SYN-CBG-A", "SYN-PR-A"), ("SYN-DX-B", "SYN-CBG-B", "SYN-PR-B"),
          ("SYN-DX-C", "SYN-CBG-C", None), ("SYN-DX-D", "SYN-CBG-D", "SYN-PR-D")]


def _records(count: int, seed: int, start: date = date(2024, 2, 5), prefix: str = "syn-train") -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for index in range(count):
        diagnosis, group, procedure = GROUPS[rng.randrange(len(GROUPS))]
        # Background variation: Isolation Forest cannot split on a feature that is constant in
        # training, so a few uncommon combinations and long stays exist, as in real claims.
        if rng.random() < 0.03:
            group = GROUPS[rng.randrange(len(GROUPS))][1]
        stay = rng.choice((2, 3, 3, 4)) if rng.random() >= 0.03 else rng.randrange(6, 15)
        day = start + timedelta(days=rng.randrange(14))
        rows.append({
            "case_id": f"{prefix}-{index:05d}", "participant_token": f"syn-person-{rng.randrange(count):05d}",
            "service_date": day.isoformat(), "discharge_date": (day + timedelta(days=stay)).isoformat(),
            "province_code": "SYN-P1", "municipality_code": f"SYN-M{rng.randrange(3)}",
            "facility_ownership": "SYN-O1", "facility_type": "SYN-T1", "facility_class": rng.choice(("SYN-K1", "SYN-K2")),
            "care_class": "SYN-C1", "admission_diagnosis": diagnosis, "primary_diagnosis": diagnosis,
            "claim_group": group, "procedure_code": procedure, "billed_amount": str(rng.randrange(1, 9) * 100000),
        })
    return rows


@pytest.fixture(scope="module")
def artifact_dir(tmp_path_factory):
    directory = tmp_path_factory.mktemp("ml-artifact")
    trained = train_model(_records(3000, seed=1), TrainingConfig(n_estimators=100, max_samples=256))
    save_artifact(trained, directory, {"source_classification": "synthetic_fixture",
                                       "date_from": "2024-02-05", "date_to": "2024-02-18"})
    return directory


def test_feature_pipeline_is_deterministic_and_row_local_except_visit_counts():
    rows = _records(500, seed=2)
    reference = fit_reference(rows)
    first = build_features(rows, reference)
    assert first == build_features(rows, reference)
    assert len(first[0]) == len(FEATURE_NAMES)
    # Reversing the batch only reorders rows: features do not depend on position.
    assert build_features(list(reversed(rows)), reference) == list(reversed(first))


def test_amounts_and_identifiers_do_not_change_features():
    rows = _records(300, seed=3)
    reference = fit_reference(rows)
    changed = [{**row, "billed_amount": "1", "case_id": f"other-{index}"} for index, row in enumerate(rows)]
    assert build_features(changed, reference) == build_features(rows, reference)
    # Renaming every participant consistently keeps visit counts, so features stay the same.
    renamed = [{**row, "participant_token": "x" + row["participant_token"]} for row in rows]
    assert build_features(renamed, reference) == build_features(rows, reference)


def test_reference_suppresses_small_counts_and_holds_no_row_identifiers(artifact_dir):
    reference_text = (artifact_dir / "reference.json").read_text(encoding="utf-8")
    reference = json.loads(reference_text)
    counts = [count for table in reference["categorical_counts"].values() for count in table.values()]
    counts += [count for table in reference["pair_counts"].values() for count in table.values()]
    assert counts and min(counts) >= MIN_REFERENCE_COUNT
    assert "syn-person" not in reference_text and "syn-train" not in reference_text
    assert "billed_amount" not in reference_text
    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    assert "billed_amount" not in [item["name"] for item in manifest["features"]]
    assert set(manifest["files"]) == {"model.joblib", "reference.json"}


def test_artifact_round_trip_gives_identical_scores_and_rejects_tampering(artifact_dir, tmp_path):
    holdout = _records(400, seed=4, start=date(2024, 3, 4), prefix="syn-hold")
    first, results = score_records(holdout, load_artifact(artifact_dir))
    second, again = score_records(holdout, load_artifact(artifact_dir))
    assert first == second and results == again
    assert first["status"] == "available" and first["mode"] == "pretrained_artifact"
    assert first["records_scored"] == 400

    tampered = tmp_path / "tampered"
    tampered.mkdir()
    for name in ("manifest.json", "reference.json", "model.joblib"):
        (tampered / name).write_bytes((artifact_dir / name).read_bytes())
    (tampered / "reference.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ModelArtifactError) as error:
        load_artifact(tampered)
    assert error.value.code == "ML_MODEL_CHECKSUM_MISMATCH"


def test_missing_artifact_is_reported_unavailable_not_scored(tmp_path, monkeypatch):
    monkeypatch.setenv(MODEL_DIR_VARIABLE, str(tmp_path / "missing"))
    summary, results = score_records(_records(50, seed=5))
    assert summary["status"] == "unavailable"
    assert summary["error_code"] == "ML_MODEL_ARTIFACT_MISSING"
    assert summary["records_scored"] == 0 and results == {}
    assert str(tmp_path) not in json.dumps(summary)


def test_missing_prerequisites_are_not_assessed_with_reason(artifact_dir):
    rows = _records(60, seed=6, start=date(2024, 3, 4), prefix="syn-hold")
    rows[0]["claim_group"] = None
    rows[1]["service_date"] = "not-a-date"
    summary, results = score_records(rows, load_artifact(artifact_dir))
    assert results[rows[0]["case_id"]] == {"inference_status": "not_assessed", "reason": "missing:claim_group",
                                           "model_version": ml_model.MODEL_VERSION}
    assert results[rows[1]["case_id"]]["reason"] == "missing:service_date"
    assert summary["records_scored"] == 58 and summary["records_not_assessed"] == 2
    assert summary["not_assessed_reason_counts"] == {"missing:claim_group": 1, "missing:service_date": 1}


def test_injected_compound_anomaly_scores_above_unchanged_records(artifact_dir):
    rows = _records(400, seed=7, start=date(2024, 3, 4), prefix="syn-hold")
    injected = dict(rows[0], case_id="syn-injected", claim_group="SYN-CBG-D", procedure_code="SYN-PR-A",
                    discharge_date=(date.fromisoformat(rows[0]["service_date"]) + timedelta(days=40)).isoformat())
    _, results = score_records(rows + [injected], load_artifact(artifact_dir))
    unchanged = sorted(item["anomaly_score"] for key, item in results.items() if key != "syn-injected")
    assert results["syn-injected"]["anomaly_score"] > unchanged[-1]
    assert results["syn-injected"]["reference_percentile"] >= 0.99
    signals = {item["feature"] for item in results["syn-injected"]["supporting_signals"]}
    assert "length_of_stay_deviation" in signals


def test_fkrtl_run_uses_the_artifact_and_keeps_rules_separate(artifact_dir, monkeypatch):
    monkeypatch.setenv(MODEL_DIR_VARIABLE, str(artifact_dir))
    rows = _records(200, seed=8, start=date(2024, 3, 4), prefix="syn-hold")
    rows.append(dict(rows[0], case_id="syn-hold-repeat"))  # same participant, day and codes: a repeat candidate
    rows[5]["claim_group"] = None
    source = {"source_schema_profile": FKRTL_SCHEMA_PROFILE, "repeat_signature_profile": "repeat-service-v1"}

    def fail_fit(*_args, **_kwargs):
        raise AssertionError("an FKRTL run must not refit the per-run ranking")
    monkeypatch.setattr("app.services.analytics.build_ml_anomaly_ranking", fail_fit)
    snapshot = build_analytics_snapshot(records=rows, facilities=[], data_source=source)
    ml = snapshot["ml_anomaly"]
    assert ml["mode"] == "pretrained_artifact" and ml["status"] == "available"
    assert ml["records_scored"] == 200 and ml["records_not_assessed"] == 1
    assert ml["training_reference"]["date_to"] == "2024-02-18"
    assert "participant_token" not in json.dumps(ml) and "syn-person" not in json.dumps(ml)
    assert "FKL47" not in json.dumps(snapshot) and "FKL48" not in json.dumps(snapshot)
    flagged = snapshot["cases"]
    assert flagged, "the repeat rule still flags its pair"
    for case in flagged.values():
        assert case["ml_anomaly"] is None or case["ml_anomaly"]["inference_status"] == "scored"
        assert "anomaly" not in json.dumps(case["reasons"])  # rule reasons never include the ML score


def test_synthetic_csv_runs_keep_the_per_run_ranking(monkeypatch):
    called = []
    monkeypatch.setattr("app.services.analytics.score_pretrained_records",
                        lambda *args, **kwargs: called.append(1) or ({}, {}))
    snapshot = build_analytics_snapshot()
    assert not called
    assert snapshot["ml_anomaly"].get("mode") is None
