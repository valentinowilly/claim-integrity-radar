"""Three rule checks on the BPJS columns: extreme stay, rapid readmission, unusual severity (synthetic records)."""

from datetime import date, timedelta

from app.analytics.clinical_rules import (
    LONG_STAY, READMISSION, SEVERITY, detect_extreme_stay, detect_rapid_readmission, detect_unusual_severity,
)
from app.analytics.risk_scoring import run_detector_suite

SEP = "\x1f"
REFERENCE = {
    "stay_peer_fine": {"K-4-17-I|3": [3.0, 1.0]},
    "stay_peer_coarse": {"K-4-17-I": [3.0, 1.0], "K-4-17-III": [4.0, 1.0]},
    "pair_counts": {"primary_diagnosis__claim_group": {
        f"K35{SEP}K-4-17-I": 380, f"K35{SEP}K-4-17-II": 15, f"K35{SEP}K-4-17-III": 5,  # III is 1.25% of K35
        f"J18{SEP}K-4-17-I": 40, f"J18{SEP}K-4-17-III": 30,                            # III is common for J18
        f"A09{SEP}K-4-17-III": 10,                                                       # too few references
    }},
}


def claim(case_id, *, participant="p1", start=date(2024, 3, 4), stay=3, group="K-4-17-I", diagnosis="K35", care="3"):
    return {"case_id": f"syn-{case_id}", "participant_token": participant, "service_date": start.isoformat(),
            "discharge_date": (start + timedelta(days=stay)).isoformat(), "claim_group": group,
            "primary_diagnosis": diagnosis, "care_class": care}


def flagged(result):
    return {case.removeprefix("syn-") for item in result["candidates"] for case in (item.get("case_ids") or [item["case_id"]])}


def ids(items):
    return {(item["case_id"] if isinstance(item, dict) else item).removeprefix("syn-") for item in items}


def test_extreme_stay_needs_both_a_week_and_five_robust_deviations_above_the_reference():
    records = [claim("typical", stay=4), claim("long", stay=11), claim("very-long", stay=12), claim("day-case", stay=0),
               claim("no-reference", stay=30, group="Z-4-99-I"), {**claim("no-dates"), "discharge_date": None}]
    result = detect_extreme_stay(records, REFERENCE)
    # Limit = max(3 + 7, 3 + 5 * 1.4826 * 1) = 10.4 days; the stay must exceed it.
    assert flagged(result) == {"long", "very-long"}
    assert ids(result["not_applicable_cases"]) == {"day-case"}
    assert ids(result["unassessed_case_ids"]) == {"no-reference", "no-dates"}
    assert result["assessed_count"] == 3 and "fraud" not in result["candidates"][0]["reason"].lower()
    assert detect_extreme_stay(records, None)["status"] == "unavailable"


def test_rapid_readmission_pairs_the_same_patient_and_diagnosis_within_three_days():
    first = claim("first", start=date(2024, 3, 1), stay=3)                          # discharged 4 March
    records = [first, claim("again", start=date(2024, 3, 6), stay=2),             # 2 days later: flagged
               claim("later", start=date(2024, 3, 20), stay=2),                    # weeks later: not flagged
               claim("other-diagnosis", start=date(2024, 3, 9), stay=1, diagnosis="J18"),
               claim("other-patient", participant="p2", start=date(2024, 3, 5), stay=2),
               claim("outpatient", start=date(2024, 3, 7), stay=0)]
    result = detect_rapid_readmission(records)
    assert flagged(result) == {"first", "again"}
    assert result["candidates"][0]["supporting_values"]["days_between"] == 2
    assert ids(result["not_applicable_cases"]) == {"outpatient"}


def test_unusual_severity_flags_a_severity_rarely_used_for_the_diagnosis():
    records = [claim("upcoded", group="K-4-17-III"), claim("usual", group="K-4-17-I"),
               claim("common-severe", group="K-4-17-III", diagnosis="J18"),
               claim("thin-reference", group="K-4-17-III", diagnosis="A09"), claim("outpatient-code", group="Q-5-44-0")]
    result = detect_unusual_severity(records, REFERENCE)
    assert flagged(result) == {"upcoded"}
    assert result["candidates"][0]["supporting_values"]["reference_support"] == 400
    assert ids(result["not_applicable_cases"]) == {"usual", "outpatient-code"}
    assert ids(result["unassessed_case_ids"]) == {"thin-reference"}


def test_the_clinical_checks_run_only_for_sources_in_the_bpjs_format():
    records = [claim("a"), claim("b", stay=12)]
    other = run_detector_suite(records, [])
    assert {other[code]["status"] for code in (LONG_STAY, READMISSION, SEVERITY)} == {"not_applicable"}
    bpjs = run_detector_suite(records, [], clinical_rules=True, clinical_reference=REFERENCE)
    assert flagged(bpjs[LONG_STAY]) == {"b"} and bpjs[READMISSION]["status"] == "complete"
    without_model = run_detector_suite(records, [], clinical_rules=True)
    assert without_model[LONG_STAY]["status"] == without_model[SEVERITY]["status"] == "unavailable"
    assert without_model[READMISSION]["status"] == "complete"
