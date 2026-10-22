"""Deterministic, wholly artificial runtime records for the demo API."""

from copy import deepcopy


def _claim(case_id: str, participant: str, **overrides: str) -> dict[str, str]:
    record = {
        "case_id": case_id,
        "participant_token": participant,
        "service_date": "2025-01-14",
        "province_code": "DEMO-PROVINCE-01",
        "municipality_code": "DEMO-CITY-01",
        "facility_ownership": "public-demo",
        "facility_type": "general-demo",
        "facility_class": "class-demo-a",
        "admission_diagnosis": "DEMO-DX-10",
        "primary_diagnosis": "DEMO-DX-20",
        "claim_group": "DEMO-GROUP-01",
        "procedure_code": "DEMO-PROC-01",
        "billed_amount": "125000.00",
    }
    record.update(overrides)
    return record


# These values are invented for software behavior checks and do not originate
# from, or represent a sample of, any BPJS data.
_SYNTHETIC_CLAIMS = [
    _claim("syn-normal-001", "demo-person-normal", primary_diagnosis="DEMO-DX-NORMAL"),
    _claim("syn-repeat-001", "demo-person-repeat", service_date="2025-01-15"),
    _claim("syn-repeat-002", "demo-person-repeat", service_date="2025-01-15"),
    _claim("syn-pattern-001", "demo-person-pattern-a"),
    _claim("syn-pattern-002", "demo-person-pattern-b"),
    _claim("syn-pattern-003", "demo-person-pattern-c"),
    _claim("syn-near-001", "demo-person-near-a", primary_diagnosis="DEMO-DX-NEAR"),
    _claim(
        "syn-near-002", "demo-person-near-b",
        primary_diagnosis="DEMO-DX-NEAR", procedure_code="DEMO-PROC-02",
    ),
    _claim("syn-invalid-001", "demo-person-invalid", service_date="2025-99-99"),
    _claim("syn-missing-procedure-001", "demo-person-no-procedure", procedure_code=" "),
    _claim(
        "syn-routine-001", "demo-person-routine",
        primary_diagnosis="DEMO-DX-ROUTINE",
    ),
    _claim(
        "syn-routine-002", "demo-person-routine",
        primary_diagnosis="DEMO-DX-ROUTINE",
    ),
]


def get_synthetic_records() -> list[dict[str, str]]:
    """Return a fresh copy; callers cannot mutate the module's source records."""
    return deepcopy(_SYNTHETIC_CLAIMS)
