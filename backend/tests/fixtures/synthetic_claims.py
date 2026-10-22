"""Deterministic, wholly artificial claims for indicator tests."""

from copy import deepcopy


def _claim(case_id: str, participant: str, **overrides):
    record = {
        "case_id": case_id,
        "participant_token": participant,
        "service_date": "2025-01-14",
        "province_code": "SYN-P1",
        "municipality_code": "SYN-C1",
        "facility_ownership": "public",
        "facility_type": "general",
        "facility_class": "class-a",
        "admission_diagnosis": "SYN-DX-10",
        "primary_diagnosis": "SYN-DX-20",
        "claim_group": "SYN-CBG-01",
        "procedure_code": "SYN-PR-01",
        "billed_amount": "125000.00",
        # An intentionally irrelevant post-verification field. Detectors must
        # not read it or use it as a risk predictor.
        "FKL48": "synthetic-only-post-verification-value",
    }
    record.update(overrides)
    return record


SYNTHETIC_CLAIMS = [
    # 1. A normal claim without a matching pair.
    _claim(
        "syn-normal-001",
        "synthetic-person-normal",
        primary_diagnosis="SYN-DX-NORMAL",
    ),

    # 2. Exact repeat signature for the same synthetic participant.
    _claim("syn-repeat-001", "synthetic-person-repeat", service_date="2025-01-15"),
    _claim("syn-repeat-002", "synthetic-person-repeat", service_date="2025-01-15"),

    # 3. Same complete service pattern across three different participants.
    _claim("syn-pattern-001", "synthetic-person-pattern-a"),
    _claim("syn-pattern-002", "synthetic-person-pattern-b"),
    _claim("syn-pattern-003", "synthetic-person-pattern-c"),

    # 4. Near-match: procedure differs, so it must not join a complete match.
    _claim(
        "syn-near-001",
        "synthetic-person-near-a",
        primary_diagnosis="SYN-DX-NEAR",
    ),
    _claim(
        "syn-near-002",
        "synthetic-person-near-b",
        primary_diagnosis="SYN-DX-NEAR",
        procedure_code="SYN-PR-02",
    ),

    # 5. Invalid date/amount is ineligible; blank procedure is partial-only.
    _claim("syn-invalid-001", "synthetic-person-invalid", service_date="2025-99-99"),
    _claim("syn-missing-procedure-001", "synthetic-person-no-procedure", procedure_code=" "),

    # 6. Illustrative legitimate repeat: a planned recurring service can have
    # identical attributes. It remains a candidate requiring human context.
    _claim(
        "syn-routine-001",
        "synthetic-person-routine",
        primary_diagnosis="SYN-DX-ROUTINE",
    ),
    _claim(
        "syn-routine-002",
        "synthetic-person-routine",
        primary_diagnosis="SYN-DX-ROUTINE",
    ),
]


def synthetic_claims_copy():
    """Return a fresh deep copy so tests can assert detector immutability."""
    return deepcopy(SYNTHETIC_CLAIMS)
