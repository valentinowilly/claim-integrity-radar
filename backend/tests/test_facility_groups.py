from app.analytics.action_policy import ActionPolicyConfig, evaluate_action_policy, get_action_policy_config
from app.analytics.facility_groups import build_facility_groups


def _record(case_id, municipality="1"):
    return {"case_id": case_id, "province_code": "33", "municipality_code": municipality,
            "facility_ownership": "9", "facility_type": "1", "facility_class": "7"}


def _case(percentile):
    return {"indicators": ["near_duplicate_claim_candidate"], "risk_score": None,
            "score_status": "insufficient_assessed_indicators", "indicator_coverage": [],
            "ml_anomaly": {"reference_percentile": percentile}}


def _specific(percentile):
    """A high-risk claim backed by a specific rule finding (repeat service) and the AI."""
    return {**_case(percentile), "indicators": ["repeat_billing_candidate", "near_duplicate_claim_candidate"]}


def test_evidence_lanes_and_v1_unchanged():
    snapshot = {"execution_status": "completed", "indicator_coverage": [],
                "cases": {"a": _case(0.97), "b": _case(0.92), "c": _case(0.5)}}
    lanes = evaluate_action_policy(snapshot, get_action_policy_config())["cases"]
    assert [lanes[key]["lane"] for key in "abc"] == ["red", "yellow", "green"]
    v1 = evaluate_action_policy(snapshot, ActionPolicyConfig())["cases"]
    assert {item["lane"] for item in v1.values()} == {"cannot_recommend"}
    # A specific rule finding is never low risk; two findings are high.
    specific = {"execution_status": "completed", "indicator_coverage": [], "cases": {
        "d": {**_case(0.5), "indicators": ["supporting_evidence_completeness_candidate"]},
        "e": {**_case(0.5), "indicators": ["repeat_billing_candidate", "similar_claim_pattern_candidate"]}}}
    lanes = evaluate_action_policy(specific, get_action_policy_config())["cases"]
    assert lanes["d"]["lane"] == "yellow" and lanes["e"]["lane"] == "red"


def test_groups_rank_hide_small_groups_and_use_official_labels():
    records = ([_record(f"x{i}") for i in range(40)] + [_record(f"y{i}", municipality="2") for i in range(5)]
               + [_record(f"z{i}", municipality="3") for i in range(100)])  # an ordinary group sets the average
    cases = {f"x{i}": _specific(0.99) for i in range(4)} | {"y0": _specific(0.99)}
    lanes = {case_id: {"lane": "red"} for case_id in cases}
    labels = {"facility_class": {"7": "RS Swasta Setara Type C"}, "facility_ownership": {"9": "Swasta"}}
    result = build_facility_groups(records, cases, lanes, labels, min_claims=30)
    assert result["group_count"] == 2 and result["hidden_group_count"] == 1 and result["hidden_claim_count"] == 5
    group = result["groups"][0]
    assert result["groups"][1]["level"] == "low"
    assert group["title"] == "RS Swasta Setara Type C · Swasta"
    assert group["level"] == "high" and group["lane_counts"]["red"] == 4
    assert group["records_to_request"] == 4 and len(group["sample_case_ids"]) == 4
    assert all(group["sample_findings"][case_id] == ["repeat_billing_candidate", "near_duplicate_claim_candidate"]
               for case_id in group["sample_case_ids"])
    assert group["verdict"].startswith("RISIKO TINGGI. Alasan: (1) 4 klaim")
    assert "y0" not in group["sample_case_ids"]


def test_fairness_compares_each_region_with_the_overall_share():
    records = [_record(f"a{i}") for i in range(40)] + [{**_record(f"b{i}"), "province_code": "11"} for i in range(40)]
    lanes = {"a0": {"lane": "red"}, "a1": {"lane": "yellow"}, "b0": {"lane": "green"}}
    fairness = build_facility_groups(records, {}, lanes, {"province_code": {"33": "Jawa Tengah", "11": "Aceh"}})["fairness"]
    assert fairness["overall_share"] == round(2 / 80, 5)
    province = next(item for item in fairness["dimensions"] if item["field"] == "province_code")
    assert [row["label"] for row in province["rows"]] == ["Jawa Tengah", "Aceh"]
    assert province["rows"][0]["ratio_to_overall"] == 2.0 and province["rows"][1]["ratio_to_overall"] == 0.0


def test_province_rows_carry_the_code_billed_value_and_group_count_for_the_map():
    records = ([{**_record(f"a{i}"), "provider_billed_amount_unverified": "1000"} for i in range(40)]
               + [{**_record(f"b{i}"), "province_code": "11", "facility_class": "8"} for i in range(40)])
    lanes = {"a0": {"lane": "red"}, "a1": {"lane": "yellow"}, "a2": {"lane": "green"}}
    fairness = build_facility_groups(records, {}, lanes, {})["fairness"]
    rows = {row["code"]: row for row in next(item for item in fairness["dimensions"] if item["field"] == "province_code")["rows"]}
    assert rows["33"]["billed_high_or_medium"] == 2000  # only the high and medium-risk claims
    assert rows["11"]["billed_high_or_medium"] is None  # no amounts in that province
    assert rows["33"]["facility_groups"] == 1 and rows["11"]["facility_groups"] == 1
    assert {group["province_code"] for group in build_facility_groups(records, {}, lanes, {}, min_claims=1)["groups"]} == {"33", "11"}



def test_exposure_sums_billed_value_per_risk_level_without_touching_lanes():
    records = [{**_record("a"), "provider_billed_amount_unverified": "1000000"},
               {**_record("b"), "provider_billed_amount_unverified": "250000"},
               {**_record("c"), "provider_billed_amount_unverified": "50000"}]
    lanes = {"a": {"lane": "red"}, "b": {"lane": "yellow"}, "c": {"lane": "green"}}
    exposure = build_facility_groups(records, {}, lanes, {}, min_claims=1)["exposure"]
    assert exposure["billed_total"] == 1_300_000 and exposure["billed_high"] == 1_000_000
    assert exposure["billed_high_or_medium"] == 1_250_000 and exposure["share_of_billed"] == round(1_250_000 / 1_300_000, 5)
    assert exposure["amount_source"].startswith("FKL47")
    assert lanes == {"a": {"lane": "red"}, "b": {"lane": "yellow"}, "c": {"lane": "green"}}


def test_the_billed_amount_never_drives_the_risk_level():
    from app.analytics.ml_model import FEATURE_NAMES
    assert not any("amount" in name or "billed" in name for name in FEATURE_NAMES)
    base = {"execution_status": "completed", "indicator_coverage": [], "cases": {
        "a": {**_case(0.5), "indicators": ["supporting_evidence_completeness_candidate"], "billed_amount": "1"}}}
    rich = {**base, "cases": {"a": {**base["cases"]["a"], "billed_amount": "999999999"}}}
    config = get_action_policy_config()
    assert evaluate_action_policy(base, config)["cases"] == evaluate_action_policy(rich, config)["cases"]



def test_a_run_relative_ai_score_cannot_confirm_the_exploratory_screen():
    relative = {**_case(0.99), "ml_anomaly": {"anomaly_percentile": 0.99}}
    absolute = _case(0.99)
    snapshot = {"execution_status": "completed", "indicator_coverage": [], "cases": {"r": relative, "a": absolute}}
    lanes = evaluate_action_policy(snapshot, get_action_policy_config())["cases"]
    assert lanes["r"]["lane"] == "green" and lanes["a"]["lane"] == "red"



def test_a_large_facility_is_not_high_risk_by_size_alone():
    # 4 high-risk claims among 400 is below twice the average share here; 4 among 40 is well above it.
    records = [_record(f"big{i}") for i in range(400)] + [_record(f"small{i}", municipality="2") for i in range(40)]
    cases = {f"big{i}": _specific(0.99) for i in range(4)} | {f"small{i}": _specific(0.99) for i in range(4)}
    lanes = {case_id: {"lane": "red"} for case_id in cases}
    levels = {g["region"].split(",")[0]: g["level"] for g in build_facility_groups(records, cases, lanes, {}, min_claims=30)["groups"]}
    assert levels == {"1": "medium", "2": "high"}


def test_similarity_alone_never_makes_a_facility_high_risk():
    # The same 4 high-risk claims among 40, but found only by the exploratory similar-claim screen
    # (the AI agreed): the group is medium, because similarity is not a rule finding.
    records = [_record(f"big{i}") for i in range(400)] + [_record(f"small{i}", municipality="2") for i in range(40)]
    cases = {f"small{i}": _case(0.99) for i in range(4)}
    lanes = {case_id: {"lane": "red"} for case_id in cases}
    group = next(g for g in build_facility_groups(records, cases, lanes, {}, min_claims=30)["groups"]
                 if g["region"].startswith("2"))
    assert group["level"] == "medium" and group["red_with_specific_finding"] == 0
