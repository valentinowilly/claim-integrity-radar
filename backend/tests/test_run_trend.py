"""Headline numbers per run for the overview comparisons (counts only; synthetic data)."""

from app.data_sources.synthetic_csv import SYNTHETIC_CSV_MAPPING_VERSION, SYNTHETIC_CSV_SCHEMA_VERSION, export_synthetic_csv
from app.data_sources.synthetic_generator import SyntheticGeneratorConfig, generate_synthetic_dataset
from tests.test_analysis_runs import call, create_run, operator_session, setup, verifier_session


def _import(app, cookies, seed: int, key: str) -> str:
    """A batch of its own (a second run of the same batch would supersede the first)."""
    raw = export_synthetic_csv(generate_synthetic_dataset(SyntheticGeneratorConfig(seed=seed, claim_count=200, facility_count=10)).records)
    response = call(app, "POST", "/api/v1/batches/import", cookies=cookies, content=raw, headers={
        "Content-Type": "text/csv; charset=utf-8", "X-CSRF-Token": cookies["cir_csrf"], "X-Batch-Key": key,
        "X-Synthetic-Schema-Version": SYNTHETIC_CSV_SCHEMA_VERSION, "X-Synthetic-Mapping-Version": SYNTHETIC_CSV_MAPPING_VERSION,
        "X-Data-Classification": "synthetic_only"})
    assert response.status_code == 201, response.text
    return response.json()["batch"]["batch_id"]


def test_the_trend_lists_the_latest_runs_oldest_first_with_counts_only(tmp_path):
    app, _batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    first = create_run(app, operator, _import(app, operator, 11, "synthetic-trend-a")).json()["run"]["run_id"]
    second = create_run(app, operator, _import(app, operator, 12, "synthetic-trend-b")).json()["run"]["run_id"]
    verifier = verifier_session(app, users)

    detail = call(app, "GET", f"/api/v1/runs/{second}?view=summary", cookies=verifier).json()["result"]
    response = call(app, "GET", "/api/v1/runs/trend", cookies=verifier)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["run_id"] for item in items] == [first, second]
    latest = items[-1]
    assert latest["lane_counts"] == {lane: detail["action_policy"]["lane_counts"].get(lane, 0) for lane in ("red", "yellow", "green")}
    assert latest["records_considered"] == detail["records_considered"]
    # New runs also keep the per-day counts for the trend page (summary view included).
    daily = detail["daily_activity"]
    assert daily["status"] == "available" and sum(day["claims"] for day in daily["days"]) + daily["undated_claims"] == detail["records_considered"]
    # Numbers only: no claims, cases or participant data.
    assert set(latest) == {"run_id", "created_at", "source_type", "records_considered", "lane_counts", "billed_high_or_medium"}

    archived = call(app, "POST", f"/api/v1/runs/{first}/archive", cookies=operator,
                    headers={"X-CSRF-Token": operator["cir_csrf"]})
    assert archived.status_code == 204, archived.text
    assert [item["run_id"] for item in call(app, "GET", "/api/v1/runs/trend", cookies=verifier).json()["items"]] == [second]


def test_the_trend_needs_result_access_and_a_sane_limit(tmp_path):
    app, _batch_db, users = setup(tmp_path)
    assert call(app, "GET", "/api/v1/runs/trend").status_code == 401
    verifier = verifier_session(app, users)
    assert call(app, "GET", "/api/v1/runs/trend?limit=1", cookies=verifier).status_code == 400
    assert call(app, "GET", "/api/v1/runs/trend?limit=31", cookies=verifier).status_code == 400
    empty = call(app, "GET", "/api/v1/runs/trend", cookies=verifier)
    assert empty.status_code == 200 and empty.json()["items"] == []


def test_review_accuracy_reads_the_full_run_schema(tmp_path):
    app, _batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    create_run(app, operator, _import(app, operator, 21, "synthetic-accuracy-a"))
    create_run(app, operator, _import(app, operator, 22, "synthetic-accuracy-b"))
    response = call(app, "GET", "/api/v1/runs/review-accuracy?weeks=8", cookies=verifier_session(app, users))
    assert response.status_code == 200, response.text
    body = response.json()
    # Both analyses use the same rules version: no change marker; no decisions yet.
    assert len(body["weeks"]) == 8 and body["policy_changes"] == [] and body["totals"]["decided"] == 0
