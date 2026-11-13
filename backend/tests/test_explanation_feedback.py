"""Verifiers rate the reasons of a claim; one answer per person, claim and check; summed per check."""

from tests.test_analysis_runs import call, create_run, import_batch, operator_session, setup, verifier_session


def test_reasons_are_rated_once_per_person_and_summed_per_check(tmp_path):
    app, batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    batch, _ = import_batch(app, batch_db, operator)
    run_id = create_run(app, operator, batch["batch_id"]).json()["run"]["run_id"]
    verifier = verifier_session(app, users)
    csrf = {"X-CSRF-Token": verifier["cir_csrf"]}
    item = call(app, "GET", f"/api/v1/runs/{run_id}/cases?limit=1", cookies=verifier).json()["items"][0]["case"]
    case_id, indicator = item["case_id"], item["indicators"][0]
    url = f"/api/v1/runs/{run_id}/cases/{case_id}/explanation-feedback"

    assert call(app, "POST", url, cookies=verifier, json_body={"indicator": indicator, "helpful": False, "reason": "unclear"},
                headers=csrf).status_code == 200
    # A second answer replaces the first; a check that did not flag this claim is refused; no CSRF, no write.
    assert call(app, "POST", url, cookies=verifier, json_body={"indicator": indicator, "helpful": True}, headers=csrf).status_code == 200
    assert call(app, "POST", url, cookies=verifier, json_body={"indicator": "not_on_claim", "helpful": True}, headers=csrf).status_code == 422
    assert call(app, "POST", url, cookies=verifier, json_body={"indicator": indicator, "helpful": True}).status_code == 403

    assert call(app, "GET", url, cookies=verifier).json()["items"] == {indicator: {"helpful": True, "reason": None}}
    summary = call(app, "GET", "/api/v1/explanation-feedback/summary", cookies=verifier).json()
    assert summary["total"] == 1 and summary["share_helpful"] == 1.0
    assert summary["items"][0]["indicator"] == indicator
    assert call(app, "GET", "/api/v1/explanation-feedback/summary").status_code == 401
