from copy import deepcopy

from app.analytics.action_policy import ActionPolicyConfig, evaluate_action_policy
from app.analytics.risk_scoring import DETECTOR_ORDER


def _snapshot(score=0.2, *, score_status="assessed", states=None, execution_status="completed", truncated=()):
    states = states or {indicator: "not_triggered" for indicator in DETECTOR_ORDER}
    return {
        "execution_status": execution_status,
        "indicator_coverage": [
            {"indicator": indicator, "status": "partial" if indicator in truncated else "complete",
             "search_truncated": indicator in truncated}
            for indicator in DETECTOR_ORDER
        ],
        "cases": {
            "syn-case-001": {
                "case_id": "syn-case-001", "risk_score": score, "score_status": score_status,
                "assessed_indicators": [name for name, state in states.items() if state in {"triggered", "not_triggered"}],
                "indicator_coverage": [{"indicator": name, "status": state} for name, state in states.items()],
                "limitations": [],
            }
        },
    }


def test_demo_policy_has_each_lane_and_keeps_risk_level_separate():
    config = ActionPolicyConfig()
    assert evaluate_action_policy(_snapshot(0.2), config)["cases"]["syn-case-001"]["lane"] == "green"
    assert evaluate_action_policy(_snapshot(0.5), config)["cases"]["syn-case-001"]["lane"] == "yellow"
    assert evaluate_action_policy(_snapshot(0.9), config)["cases"]["syn-case-001"]["lane"] == "red"
    result = evaluate_action_policy(_snapshot(None, score_status="not_assessable"), config)
    assert result["cases"]["syn-case-001"]["lane"] == "cannot_recommend"
    assert "risk_level" not in result["cases"]["syn-case-001"]
    assert result["policy_version"] == config.version


def test_not_applicable_is_ignored_but_unassessed_unavailable_and_truncated_block():
    states = {indicator: "not_triggered" for indicator in DETECTOR_ORDER}
    states[DETECTOR_ORDER[0]] = "not_applicable"
    assert evaluate_action_policy(_snapshot(states=states))["cases"]["syn-case-001"]["lane"] == "green"

    states[DETECTOR_ORDER[1]] = "not_assessed"
    assert evaluate_action_policy(_snapshot(states=states))["cases"]["syn-case-001"]["lane"] == "cannot_recommend"

    states = {indicator: "not_triggered" for indicator in DETECTOR_ORDER}
    truncated = _snapshot(states=states, truncated=(DETECTOR_ORDER[2],))
    assert evaluate_action_policy(truncated)["cases"]["syn-case-001"]["lane"] == "cannot_recommend"

    unavailable = _snapshot(states=states)
    unavailable["indicator_coverage"][0]["status"] = "unavailable"
    assert evaluate_action_policy(unavailable)["cases"]["syn-case-001"]["lane"] == "cannot_recommend"


def test_partial_score_and_empty_result_do_not_become_green_or_zero():
    result = evaluate_action_policy(_snapshot(0.0, score_status="partial_coverage"))
    assert result["cases"]["syn-case-001"]["lane"] == "cannot_recommend"
    assert evaluate_action_policy({"cases": {}, "indicator_coverage": []})["status"] == "not_assessable"


def test_policy_configuration_is_validated_and_inputs_are_unchanged():
    try:
        ActionPolicyConfig(version="bad", green_upper=0.8, yellow_upper=0.4)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid policy config accepted")
    source = _snapshot()
    original = deepcopy(source)
    evaluate_action_policy(source)
    assert source == original

