"""Daily continuity: a new file is compared with claims of earlier files (repeat and readmission only)."""

from app.data_sources.bpjs_csv import UPLOAD_PSEUDONYM_SECRET
from app.data_sources.bpjs_fkrtl_adapter import pseudonymous_case_id
from tests.test_analysis_runs import call, create_run, operator_session, setup, verifier_session
from tests.test_bpjs_csv_upload import _csv, _upload

BASE = {"FKL05": "31", "FKL06": "3171", "FKL07": "9", "FKL08": "1", "FKL09": "2", "FKL13": "3", "FKL31": "1",
        "FKL32": "1", "FKL47": "250000"}


def row(participant, visit, admitted, discharged, diagnosis="K35", group="K-1-13-I", procedure="4701"):
    return {**BASE, "PSTV01": participant, "FKL02": visit, "FKL03": admitted, "FKL04": discharged,
            "FKL16": diagnosis, "FKL18": diagnosis, "FKL19": group, "FKL30": procedure}


def case(item):
    return pseudonymous_case_id(item["PSTV01"], item["FKL02"], secret=UPLOAD_PSEUDONYM_SECRET)


def filler(prefix, day, count=40):
    return [row(f"SYN9{prefix}{index:05d}", f"SYNV9{prefix}{index:05d}", day, day, diagnosis="J06", group="Q-5-44-0",
                procedure="8907") for index in range(count)]


def _run(app, operator, rows, key):
    uploaded = _upload(app, operator, _csv(rows), key=key)
    assert uploaded.status_code in (200, 201), uploaded.text
    created = create_run(app, operator, uploaded.json()["batch"]["batch_id"])
    assert created.status_code == 201, created.text
    return uploaded.json()["batch"], created.json()["run"]["run_id"]


def test_the_next_days_file_is_compared_with_the_earlier_file(tmp_path):
    app, _db, users = setup(tmp_path)
    operator, verifier = operator_session(app, users), verifier_session(app, users)
    first_stay = row("SYN10000001", "SYNV100000001", "2024-09-02", "2024-09-05")
    billed_once = row("SYN10000002", "SYNV100000002", "2024-09-02", "2024-09-04")
    _batch, first_run = _run(app, operator, [first_stay, billed_once] + filler("1", "2024-09-02"), "synthetic-hari-1")

    readmitted = row("SYN10000001", "SYNV100000003", "2024-09-06", "2024-09-08")       # 1 day after discharge
    billed_again = {**billed_once, "FKL02": "SYNV100000004"}                             # same visit, new number
    _batch, second_run = _run(app, operator, [readmitted, billed_again] + filler("2", "2024-09-06"), "synthetic-hari-2")

    result = call(app, "GET", f"/api/v1/runs/{second_run}", cookies=verifier).json()["result"]
    cases = result["cases"]
    assert case(readmitted) in cases and "rapid_readmission_candidate" in cases[case(readmitted)]["indicators"]
    assert "repeat_billing_candidate" in cases[case(billed_again)]["indicators"]
    reasons = [item for item in cases[case(billed_again)]["reasons"] if item["indicator"] == "repeat_billing_candidate"]
    assert "data sebelumnya" in reasons[0]["summary"] and reasons[0]["supporting_values"]["earlier_claim_count"] == 1
    # Claims of the earlier file are compared, never re-queued in this analysis.
    assert case(first_stay) not in cases and case(billed_once) not in cases
    assert result["records_considered"] == 42
    assert result["data_source"]["selection"]["earlier_claims_compared"] == 42
    # The earlier analysis is a stored snapshot: the later file does not change it.
    first = call(app, "GET", f"/api/v1/runs/{first_run}", cookies=verifier).json()["result"]
    assert "repeat_billing_candidate" not in (first["cases"].get(case(billed_once)) or {}).get("indicators", [])


def test_the_same_file_twice_and_removed_files_never_count_as_earlier_claims(tmp_path):
    app, _db, users = setup(tmp_path)
    operator, verifier = operator_session(app, users), verifier_session(app, users)
    claims = [row("SYN20000001", "SYNV200000001", "2024-09-02", "2024-09-04")] + filler("3", "2024-09-02")
    batch, _first = _run(app, operator, claims, "synthetic-sama-a")
    # The same claims under another file name are the same claims, not repeats.
    _other, again = _run(app, operator, claims, "synthetic-sama-b")
    assert call(app, "GET", f"/api/v1/runs/{again}", cookies=verifier).json()["result"]["cases"] == {}

    # A re-billed visit is not compared with a file removed from the list.
    for removed in (batch["batch_id"], _other["batch_id"]):
        assert call(app, "DELETE", f"/api/v1/batches/{removed}", cookies=operator,
                    headers={"X-CSRF-Token": operator["cir_csrf"]}).status_code == 204
    rebilled = {**claims[0], "FKL02": "SYNV200000009"}
    _batch, run = _run(app, operator, [rebilled] + filler("4", "2024-09-03"), "synthetic-sesudah-hapus")
    result = call(app, "GET", f"/api/v1/runs/{run}", cookies=verifier).json()["result"]
    assert case(rebilled) not in result["cases"]
    assert result["data_source"]["selection"]["earlier_claims_compared"] == 0


def test_a_reviewed_claim_keeps_its_decision_in_the_next_analysis(tmp_path):
    app, _db, users = setup(tmp_path)
    operator, verifier = operator_session(app, users), verifier_session(app, users)
    stay = row("SYN30000001", "SYNV300000001", "2024-09-02", "2024-09-05")
    again = row("SYN30000001", "SYNV300000002", "2024-09-06", "2024-09-07")      # rapid readmission pair
    batch, first = _run(app, operator, [stay, again] + filler("5", "2024-09-02"), "synthetic-tinjau-1")
    flagged = case(again)
    url = f"/api/v1/runs/{first}/cases/{flagged}/review"
    csrf = {"X-CSRF-Token": verifier["cir_csrf"]}
    assert call(app, "PATCH", url, cookies=verifier, headers=csrf,
                json_body={"review_status": "escalated", "note": "Sintetis."}).status_code == 200
    assert call(app, "POST", url + "/outcome", cookies=verifier, headers=csrf,
                json_body={"review_outcome": "signal_supported", "note": None}).status_code == 200
    assert call(app, "POST", url + "/audit-confirmation", cookies=verifier, headers=csrf, json_body={
        "audit_result": "confirmed_issue", "audit_reference": "AUD-2026/031", "note": None}).status_code == 200

    # The same claims analysed again (e.g. the next day's analysis that still lists them).
    second = create_run(app, operator, batch["batch_id"]).json()["run"]["run_id"]
    carried = call(app, "GET", f"/api/v1/runs/{second}/cases/{flagged}/review", cookies=verifier).json()
    assert carried["review_status"] == "escalated" and carried["review_outcome"] == "signal_supported"
    assert carried["audit_result"] == "confirmed_issue"
    assert {event["actor_user_id"] for event in carried["history"]} == {"system-continuity"}
    assert all("Dibawa dari analisis sebelumnya" in event["note"] for event in carried["history"])
    assert carried["audit_confirmations"][0]["audit_reference"] == "AUD-2026/031"
    # Claims that were never reviewed are not given a review, and the earlier analysis is unchanged.
    untouched = call(app, "GET", f"/api/v1/runs/{second}/cases/{case(stay)}/review", cookies=verifier).json()
    assert untouched["review_status"] == "pending_review" and untouched["history"] == []
    original = call(app, "GET", url, cookies=verifier).json()
    assert {event["actor_user_id"] for event in original["history"]} == {users["verifier"]["user_id"]}
