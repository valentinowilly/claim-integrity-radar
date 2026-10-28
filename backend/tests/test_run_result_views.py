"""Summary, paged candidates and case views over a stored run (read-only; synthetic data only)."""

from copy import deepcopy
from datetime import datetime
import json

import pytest

from app.analytics import ml_model
from app.services import analytics as analytics_service
from app.services import runs as runs_service
from app.services.run_results import case_page, case_view, summary_view
from tests.test_analysis_runs import call, create_run, import_batch, operator_session, setup, verifier_session
from tests.test_fkrtl_local_source import POST_VERIFICATION_MARKER, _create_fkrtl_run, _row


def _synthetic_run(tmp_path):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _generated = import_batch(app, batch_db, operator)
    created = create_run(app, operator, batch["batch_id"])
    assert created.status_code == 201, created.text
    return app, users, created.json()["run"]["run_id"]


def _fkrtl_run(tmp_path, monkeypatch):
    pd = pytest.importorskip("pandas")
    rows = [
        _row(PSTV01=8000000 + index, FKL02=f"synvisit-{index}", FKL03=datetime(2024, 3, 1 + index % 20),
             FKL04=datetime(2024, 3, 3 + index % 20), FKL19="SYN-CBG-1" if index % 2 else "SYN-CBG-2")
        for index in range(70)
    ]
    rows.append(_row(PSTV01=8999999, FKL02="synvisit-rare", FKL18="SYN99", FKL19="SYN-CBG-RARE",
                     FKL30="SYNPROC9", FKL04=datetime(2024, 4, 30)))
    # One repeated-service pair (same participant, day and codes, two visits) so rule cases exist.
    rows += [_row(PSTV01=8888888, FKL02=f"synvisit-repeat-{n}", FKL03=datetime(2024, 3, 25),
                  FKL04=datetime(2024, 3, 27), FKL19="SYN-CBG-1") for n in range(2)]
    path = tmp_path / "synthetic-view-fixture.dta"
    pd.DataFrame(rows).to_stata(path, write_index=False)
    monkeypatch.setenv("BPJS_FKRTL_SAMPLE_PATH", str(path))
    monkeypatch.setenv("CIR_FKRTL_PSEUDONYM_KEY", "cd" * 32)
    monkeypatch.setenv("BPJS_FKRTL_DATE_FROM", "2024-03-01")
    monkeypatch.setenv("BPJS_FKRTL_DATE_TO", "2024-03-31")
    monkeypatch.delenv("BPJS_FKRTL_MAX_ROWS", raising=False)
    app, _, users = setup(tmp_path)
    created = _create_fkrtl_run(app, operator_session(app, users))
    assert created.status_code == 201, created.text
    return app, users, created.json()["run"]["run_id"]


def _forbid_rerun(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("a read view must not run detection or ML inference")
    monkeypatch.setattr(runs_service, "execute_provider_snapshot", fail)
    monkeypatch.setattr(analytics_service, "score_pretrained_records", fail)
    monkeypatch.setattr(analytics_service, "build_ml_anomaly_ranking", fail)
    monkeypatch.setattr(ml_model, "score_records", fail)


def _reference_order(cases: dict, sort: str) -> list[str]:
    """The review queue's documented order: missing values last, ties by case reference."""
    def value(case):
        if sort == "rule_index":
            return None if case["risk_score"] is None else -case["risk_score"]
        if sort == "checks":
            return -len(case["indicators"])
        if sort == "ml_rank":
            return (case.get("ml_anomaly") or {}).get("rank")
        return None
    present = sorted((case_id for case_id in cases if value(cases[case_id]) is not None),
                     key=lambda case_id: (value(cases[case_id]), case_id))
    return present + sorted(case_id for case_id in cases if value(cases[case_id]) is None)


def test_summary_view_drops_case_objects_but_keeps_counts_coverage_and_ml(tmp_path, monkeypatch):
    app, users, run_id = _synthetic_run(tmp_path)
    verifier = verifier_session(app, users)
    full_response = call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier)
    full = full_response.json()["result"]
    _forbid_rerun(monkeypatch)
    summary_response = call(app, "GET", f"/api/v1/runs/{run_id}?view=summary", cookies=verifier)
    assert summary_response.status_code == 200
    summary = summary_response.json()["result"]

    assert full["cases"], "the synthetic fixture flags claims"
    assert summary["cases"] == {} and summary["action_policy"]["cases"] == {}
    view = summary["result_view"]
    assert view["kind"] == "summary" and view["case_count"] == len(full["cases"])
    assert [case["case_id"] for case in view["case_preview"]] == list(full["cases"])[:5]
    assert view["case_preview"] == [full["cases"][case_id] for case_id in list(full["cases"])[:5]]
    for key in ("indicators", "indicator_coverage", "ml_anomaly", "risk_scoring", "audit_priority",
                "records_considered", "execution_status", "data_source"):
        assert summary[key] == full[key], key
    listed = {item["case_id"] for item in full["ml_anomaly"]["items"]} | {
        item["case_id"] for item in full["length_of_stay"]["candidates"]}
    assert set(view["rule_flagged_listed_case_ids"]) == listed & set(full["cases"])
    for code, texts in view["indicator_reason_summaries"].items():
        expected = list(dict.fromkeys(reason["summary"] for case in full["cases"].values()
                                      for reason in case["reasons"] if reason["indicator"] == code))[:5]
        assert texts == expected
    assert len(summary_response.content) < len(full_response.content)
    # The default view is unchanged for API compatibility.
    assert call(app, "GET", f"/api/v1/runs/{run_id}?view=full", cookies=verifier).json()["result"] == full
    assert call(app, "GET", f"/api/v1/runs/{run_id}?view=other", cookies=verifier).status_code == 400


def test_paged_cases_cover_every_flagged_claim_once_in_queue_order(tmp_path, monkeypatch):
    app, users, run_id = _synthetic_run(tmp_path)
    verifier = verifier_session(app, users)
    full = call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier).json()["result"]
    _forbid_rerun(monkeypatch)
    for sort in ("rule_index", "checks", "ml_rank", "case_ref", "stored"):
        seen, offset = [], 0
        while True:
            page = call(app, "GET", f"/api/v1/runs/{run_id}/cases?sort={sort}&offset={offset}&limit=7",
                        cookies=verifier).json()
            assert page["total_matching"] == page["total_cases"] == len(full["cases"])
            for item in page["items"]:
                assert item["case"] == full["cases"][item["case"]["case_id"]]
                assert item["lane"] == full["action_policy"]["cases"].get(item["case"]["case_id"])
            seen += [item["case"]["case_id"] for item in page["items"]]
            offset += 7
            if offset >= page["total_matching"]:
                break
        expected = list(full["cases"]) if sort == "stored" else _reference_order(full["cases"], sort)
        assert seen == expected, sort

    code = next(iter(full["cases"].values()))["indicators"][0]
    filtered = call(app, "GET", f"/api/v1/runs/{run_id}/cases?indicator={code}&limit=100", cookies=verifier).json()
    assert filtered["total_matching"] == sum(code in case["indicators"] for case in full["cases"].values())
    some_id = next(iter(full["cases"]))
    searched = call(app, "GET", f"/api/v1/runs/{run_id}/cases?search={some_id[-8:].upper()}", cookies=verifier).json()
    assert some_id in [item["case"]["case_id"] for item in searched["items"]]
    for bad in ("limit=0", "limit=101", "offset=-1", "sort=unknown", "review_filter=unknown"):
        assert call(app, "GET", f"/api/v1/runs/{run_id}/cases?{bad}", cookies=verifier).status_code == 400
    assert call(app, "GET", "/api/v1/runs/run_missing/cases", cookies=verifier).status_code == 404


def test_review_filter_and_counts_follow_saved_reviews(tmp_path):
    app, users, run_id = _synthetic_run(tmp_path)
    verifier = verifier_session(app, users)
    first = call(app, "GET", f"/api/v1/runs/{run_id}/cases?limit=1&sort=stored", cookies=verifier).json()
    case_id = first["items"][0]["case"]["case_id"]
    assert first["reviewed_case_count"] == 0
    saved = call(app, "PATCH", f"/api/v1/runs/{run_id}/cases/{case_id}/review", cookies=verifier,
                 json_body={"review_status": "awaiting_evidence"}, headers={"X-CSRF-Token": verifier["cir_csrf"]})
    assert saved.status_code == 200
    awaiting = call(app, "GET", f"/api/v1/runs/{run_id}/cases?review_filter=awaiting_evidence", cookies=verifier).json()
    assert [item["case"]["case_id"] for item in awaiting["items"]] == [case_id]
    assert awaiting["reviewed_case_count"] == 1
    not_started = call(app, "GET", f"/api/v1/runs/{run_id}/cases?review_filter=not_started&limit=100", cookies=verifier).json()
    assert not_started["total_matching"] == first["total_cases"] - 1
    recent = call(app, "GET", f"/api/v1/runs/{run_id}/cases?sort=review_updated&limit=1", cookies=verifier).json()
    assert recent["items"][0]["case"]["case_id"] == case_id


def test_case_view_is_the_stored_case_and_unknown_claims_are_404(tmp_path, monkeypatch):
    app, users, run_id = _fkrtl_run(tmp_path, monkeypatch)
    verifier = verifier_session(app, users)
    full = call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier).json()["result"]
    _forbid_rerun(monkeypatch)
    assert full["ml_anomaly"]["mode"] == "pretrained_artifact"
    assert full["cases"], "the fixture's repeated-service pair is rule-flagged"
    for case_id in list(full["cases"])[:3]:
        scoped = call(app, "GET", f"/api/v1/runs/{run_id}/cases/{case_id}", cookies=verifier).json()["result"]
        assert scoped["cases"] == {case_id: full["cases"][case_id]}
        assert scoped["action_policy"]["cases"] == {
            key: value for key, value in full["action_policy"]["cases"].items() if key == case_id}
        assert scoped["ml_anomaly"]["items"] == [item for item in full["ml_anomaly"]["items"] if item["case_id"] == case_id]
        assert scoped["result_view"] == {"kind": "case", "case_id": case_id, "case_count": len(full["cases"])}
        assert scoped["cases"][case_id]["ml_anomaly"]["model_version"] == ml_model.MODEL_VERSION
    ml_only = next(item for item in full["ml_anomaly"]["items"] if item["case_id"] not in full["cases"])
    scoped = call(app, "GET", f"/api/v1/runs/{run_id}/cases/{ml_only['case_id']}", cookies=verifier).json()["result"]
    assert scoped["cases"] == {} and scoped["ml_anomaly"]["items"] == [ml_only]
    assert ml_only["supporting_signals"] == scoped["ml_anomaly"]["items"][0]["supporting_signals"]
    missing = call(app, "GET", f"/api/v1/runs/{run_id}/cases/case_not_in_run", cookies=verifier)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "RUN_CASE_NOT_FOUND"
    # Reviews on the reopened run use the same stored result, still without rerunning anything.
    review = call(app, "GET", f"/api/v1/runs/{run_id}/cases/{ml_only['case_id']}/review", cookies=verifier)
    assert review.status_code == 200


def test_views_do_not_leak_identifiers_or_fkl47_fkl48(tmp_path, monkeypatch):
    app, users, run_id = _fkrtl_run(tmp_path, monkeypatch)
    verifier = verifier_session(app, users)
    first_case = next(iter(call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier).json()["result"]["cases"]))
    bodies = [call(app, "GET", path, cookies=verifier).text for path in (
        f"/api/v1/runs/{run_id}?view=summary", f"/api/v1/runs/{run_id}/cases?limit=100",
        f"/api/v1/runs/{run_id}/cases/{first_case}")]
    for body in bodies:
        # FKL47 is named only in the documented "withheld" status label; no amount value may appear.
        for forbidden in ("8999999", "8888888", "synvisit", "participant_token", "FKL48", "123456",
                          str(POST_VERIFICATION_MARKER), str(tmp_path)):
            assert forbidden not in body


def test_views_read_legacy_snapshots_without_ml_or_duration_sections():
    legacy = {
        "availability": "available", "execution_status": "completed", "indicators": [], "indicator_coverage": [],
        "cases": {"case_a": {"case_id": "case_a", "indicators": ["repeat_billing_candidate"], "risk_score": 0.4,
                             "reasons": [{"indicator": "repeat_billing_candidate", "summary": "Pola berulang."}]},
                  "case_b": {"case_id": "case_b", "indicators": [], "risk_score": None, "reasons": []}},
        "action_policy": {"cases": {"case_a": {"lane": "yellow"}}},
    }
    frozen = deepcopy(legacy)
    summary = summary_view(legacy)
    assert summary["cases"] == {} and summary["result_view"]["case_count"] == 2
    assert "ml_anomaly" not in summary and "length_of_stay" not in summary
    assert summary["result_view"]["rule_flagged_listed_case_ids"] == []
    page = case_page(legacy, sort="ml_rank", limit=10)
    assert [item["case"]["case_id"] for item in page["items"]] == ["case_a", "case_b"]  # no ranks: by reference
    assert page["reviewed_case_count"] is None
    assert case_view(legacy, "case_a")["cases"] == {"case_a": legacy["cases"]["case_a"]}
    assert case_view(legacy, "case_missing") is None
    assert legacy == frozen, "views must never mutate the shared stored result"
    # Results without a case map (failed runs) pass through unchanged and have no case views.
    assert summary_view(None) is None and summary_view({"availability": "unavailable"}) == {"availability": "unavailable"}
    assert case_page(None) is None and case_view({"cases": None}, "x") is None


def test_stored_result_cache_is_not_mutated_by_views(tmp_path):
    app, users, run_id = _synthetic_run(tmp_path)
    verifier = verifier_session(app, users)
    before = call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier).json()["result"]
    for path in (f"/api/v1/runs/{run_id}?view=summary", f"/api/v1/runs/{run_id}/cases?limit=3",
                 f"/api/v1/runs/{run_id}/cases/{next(iter(before['cases']))}"):
        assert call(app, "GET", path, cookies=verifier).status_code == 200
    assert call(app, "GET", f"/api/v1/runs/{run_id}", cookies=verifier).json()["result"] == before


def test_startup_reports_a_missing_or_tampered_model_without_paths(tmp_path, monkeypatch, caplog):
    from app.main import create_app

    monkeypatch.setenv(ml_model.MODEL_DIR_VARIABLE, str(tmp_path / "absent-model"))
    with caplog.at_level("WARNING", logger="cir.ml"):
        app = create_app(tmp_path / "r.sqlite3", tmp_path / "a.sqlite3", cookie_secure=False,
                         batch_db_path=tmp_path / "b.sqlite3")
    status = app.state.ml_model_status
    assert status == {"available": False, "model_version": ml_model.MODEL_VERSION, "error_code": "ML_MODEL_ARTIFACT_MISSING"}
    assert "ML_MODEL_ARTIFACT_MISSING" in caplog.text and str(tmp_path) not in caplog.text

    tampered = tmp_path / "tampered"
    tampered.mkdir()
    for name in ("manifest.json", "reference.json", "model.joblib"):
        (tampered / name).write_bytes((ml_model.DEFAULT_MODEL_DIR / name).read_bytes())
    (tampered / "model.joblib").write_bytes(b"not a model")
    assert ml_model.model_status(tampered)["error_code"] == "ML_MODEL_CHECKSUM_MISMATCH"
    (tampered / "model.joblib").write_bytes((ml_model.DEFAULT_MODEL_DIR / "model.joblib").read_bytes())
    manifest = json.loads((tampered / "manifest.json").read_text(encoding="utf-8"))
    shipped_sklearn = manifest["sklearn_version"]
    manifest["sklearn_version"] = "0.0.0"  # pickled by another scikit-learn: refused before unpickling
    (tampered / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert ml_model.model_status(tampered)["error_code"] == "ML_MODEL_RUNTIME_MISMATCH"
    manifest["sklearn_version"] = shipped_sklearn
    manifest["feature_pipeline_version"] = "cir-ml-features-v0"
    (tampered / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert ml_model.model_status(tampered)["error_code"] == "ML_MODEL_VERSION_MISMATCH"
    with pytest.raises(ml_model.ModelArtifactError):
        ml_model.load_artifact(tampered)
    shipped = ml_model.model_status()
    monkeypatch.delenv(ml_model.MODEL_DIR_VARIABLE)
    assert ml_model.model_status()["available"] is True and shipped["available"] is False


def test_shipped_artifact_matches_the_inference_feature_contract():
    artifact = ml_model.load_artifact(ml_model.DEFAULT_MODEL_DIR)
    manifest, reference, model = artifact["manifest"], artifact["reference"], artifact["model"]
    assert [item["name"] for item in manifest["features"]] == ml_model.FEATURE_NAMES
    assert model.n_features_in_ == len(ml_model.FEATURE_NAMES)
    assert set(reference["feature_quantiles"]) == set(ml_model.FEATURE_NAMES)  # looked up by name at inference
    assert manifest["training"]["source_classification"] == "bpjs_sample"
    assert manifest["training"]["date_to"] < "2024-03-04"  # ends before the held-out demonstration week
    text = json.dumps(reference)
    assert "case_" not in text and "participant_token" not in text and "syn" not in text.lower()
    assert min(count for table in reference["pair_counts"].values() for count in table.values()) >= ml_model.MIN_REFERENCE_COUNT


def test_calibration_returns_only_counts_of_the_risk_rule_inputs(tmp_path, monkeypatch):
    app, users, run_id = _fkrtl_run(tmp_path, monkeypatch)
    _forbid_rerun(monkeypatch)
    response = call(app, "GET", f"/api/v1/runs/{run_id}/calibration", cookies=verifier_session(app, users))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["flagged"] == sum(item["count"] for item in body["bins"]) > 0
    assert all(set(item) == {"specific", "ai_bin", "count"} for item in body["bins"])
    assert "synvisit" not in response.text and "case_" not in response.text
    missing = call(app, "GET", "/api/v1/runs/run_unknown/calibration", cookies=verifier_session(app, users))
    assert missing.status_code == 404
