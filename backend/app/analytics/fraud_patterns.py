"""Fraud patterns of the proposal, read from a flagged claim's rule findings (labels, not verdicts).

The proposal names four patterns: phantom billing, cloning, repeat billing and fictitious drug/device claims.
Each maps to the rule checks that look for it. The supporting-evidence check serves two of them, so its
service type decides: physiotherapy evidence belongs to phantom billing, drug or device evidence to a
fictitious claim. Checks outside the four (stay and severity) form one more label, so no finding goes
unlabelled. A claim can carry several patterns; the one backed by more findings comes first. The exploratory
similar-claim screen alone names no pattern.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PATTERNS = ("phantom_billing", "cloning", "repeat_billing", "fictitious_claim", "upcoding_stay")
_BY_INDICATOR = {
    "synthetic_capacity_candidate": "phantom_billing",
    "temporal_pattern_candidate": "phantom_billing",
    "cloned_clinical_note_candidate": "cloning",
    "repeat_billing_candidate": "repeat_billing",
    "rapid_readmission_candidate": "repeat_billing",
    "unusual_special_topup_candidate": "fictitious_claim",
    "length_of_stay_extreme_candidate": "upcoding_stay",
    "unusual_severity_candidate": "upcoding_stay",
    "severity_without_secondary_candidate": "upcoding_stay",
}
_EVIDENCE = "supporting_evidence_completeness_candidate"
_FICTITIOUS_SERVICES = {"special_drug", "special_device"}


def fraud_patterns(case: Mapping[str, Any]) -> list[str]:
    """Pattern codes of one claim, strongest first (most findings, then the proposal's order)."""
    counts: dict[str, int] = {}
    for indicator in case.get("indicators") or []:
        pattern = _BY_INDICATOR.get(indicator)
        if indicator == _EVIDENCE:
            pattern = "fictitious_claim" if _evidence_service(case) in _FICTITIOUS_SERVICES else "phantom_billing"
        if pattern:
            counts[pattern] = counts.get(pattern, 0) + 1
    return sorted(counts, key=lambda pattern: (-counts[pattern], PATTERNS.index(pattern)))


def _evidence_service(case: Mapping[str, Any]) -> str | None:
    for reason in case.get("reasons") or []:
        if isinstance(reason, Mapping) and reason.get("indicator") == _EVIDENCE:
            rule = (reason.get("supporting_values") or {}).get("rule")
            if isinstance(rule, Mapping) and isinstance(rule.get("service_type"), str):
                return rule["service_type"]
    return None
