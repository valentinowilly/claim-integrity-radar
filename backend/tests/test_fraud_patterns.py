"""Proposal fraud patterns named by a claim's rule findings (synthetic cases only)."""

from app.analytics.fraud_patterns import fraud_patterns


def _evidence(service_type):
    return {"indicator": "supporting_evidence_completeness_candidate", "supporting_values": {"rule": {"service_type": service_type}}}


def test_each_proposal_pattern_comes_from_its_checks():
    assert fraud_patterns({"indicators": ["synthetic_capacity_candidate"]}) == ["phantom_billing"]
    assert fraud_patterns({"indicators": ["cloned_clinical_note_candidate"]}) == ["cloning"]
    assert fraud_patterns({"indicators": ["repeat_billing_candidate"]}) == ["repeat_billing"]
    assert fraud_patterns({"indicators": ["unusual_special_topup_candidate"]}) == ["fictitious_claim"]
    assert fraud_patterns({"indicators": ["severity_without_secondary_candidate"]}) == ["upcoding_stay"]
    # The similar-claim screen alone names no pattern.
    assert fraud_patterns({"indicators": ["near_duplicate_claim_candidate"]}) == []


def test_missing_evidence_follows_the_service_type():
    indicators = ["supporting_evidence_completeness_candidate"]
    assert fraud_patterns({"indicators": indicators, "reasons": [_evidence("physiotherapy")]}) == ["phantom_billing"]
    assert fraud_patterns({"indicators": indicators, "reasons": [_evidence("special_drug")]}) == ["fictitious_claim"]
    assert fraud_patterns({"indicators": indicators, "reasons": [_evidence("special_device")]}) == ["fictitious_claim"]


def test_a_claim_can_carry_several_patterns_strongest_first():
    case = {"indicators": ["repeat_billing_candidate", "synthetic_capacity_candidate", "temporal_pattern_candidate",
                           "supporting_evidence_completeness_candidate"], "reasons": [_evidence("physiotherapy")]}
    assert fraud_patterns(case) == ["phantom_billing", "repeat_billing"]
