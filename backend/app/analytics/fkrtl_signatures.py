"""Versioned, aggregate-only FKRTL signature definitions for local review.

These profiles reproduce distinct exploratory script definitions. They are not
production detector policies and return aggregate counts only.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from app.analytics.normalization import normalize_amount, normalize_date, normalize_text


SIGNATURES = {
    # From the early exploratory script run_fkrtl_real_detection.py (archived outside the repo): participant/date/diagnosis/group/procedure.
    "repeat_service_v1": ("PSTV01", "FKL03", "FKL18", "FKL19", "FKL30"),
    # A strict subset of repeat_service_v1 requiring equal claimed amount.
    "repeat_service_same_amount_v1": (
        "PSTV01", "FKL03", "FKL18", "FKL19", "FKL30", "FKL47",
    ),
    # From the early exploratory script audit_fkrtl_patterns.py (archived outside the repo): includes discharge date and claimed amount.
    "legacy_audit_signature_v1": (
        "PSTV01", "FKL03", "FKL04", "FKL18", "FKL19", "FKL30", "FKL47",
    ),
    # Exact pattern across distinct participants; FKL05 is the guide field.
    "cross_participant_exact_v1": (
        "FKL03", "FKL05", "FKL06", "FKL07", "FKL08", "FKL09",
        "FKL16", "FKL18", "FKL19", "FKL30", "FKL47",
    ),
}

SIGNATURE_SPECS = {
    name: {
        "version": name,
        "signature_fields": fields,
        "required_fields": tuple(dict.fromkeys((*fields, "PSTV01"))),
        "participant_rule": (
            "PSTV01 required internally and excluded from pattern key"
            if name == "cross_participant_exact_v1"
            else "PSTV01 required and part of same-participant key"
        ),
        "normalization": "FKL03/FKL04=date-only ISO; FKL47=finite non-negative Decimal; other fields=trimmed text",
        "eligibility_status": (
            "blocked_pending_FKL47_confirmation"
            if "FKL47" in fields else "exploratory_candidate_only"
        ),
    }
    for name, fields in SIGNATURES.items()
}

_DATE_FIELDS = {"FKL03", "FKL04"}
_AMOUNT_FIELDS = {"FKL47"}


def _normalize(field: str, value: Any) -> str | Any | None:
    if field in _DATE_FIELDS:
        return normalize_date(value)
    if field in _AMOUNT_FIELDS:
        return normalize_amount(value)
    return normalize_text(value)


def summarize_signature(
    rows: Iterable[Mapping[str, Any]], signature_name: str, *,
    allow_unverified_amount: bool = False,
) -> dict[str, int | str]:
    """Count repeated groups, rows, excess rows and ineligible rows safely.

    No source identifier, signature, or group key is returned. Cross-participant
    exact patterns require two distinct PSTV01 values, used in memory only.
    """
    if signature_name not in SIGNATURES:
        raise ValueError("Unknown signature profile.")
    fields = SIGNATURES[signature_name]
    if "FKL47" in fields and not allow_unverified_amount:
        raise ValueError(
            "This signature requires explicit synthetic-fixture opt-in or prior FKL47 validation."
        )
    groups: dict[tuple[Any, ...], list[str | None]] = defaultdict(list)
    ineligible = 0
    total = 0
    for row in rows:
        total += 1
        values = tuple(_normalize(field, row.get(field)) for field in fields)
        participant = _normalize("PSTV01", row.get("PSTV01"))
        if any(value is None for value in values) or participant is None:
            ineligible += 1
            continue
        groups[values].append(participant if isinstance(participant, str) else None)

    repeated = []
    for members in groups.values():
        if len(members) < 2:
            continue
        if signature_name == "cross_participant_exact_v1":
            participants = {value for value in members if value is not None}
            if len(participants) < 2:
                continue
        repeated.append(len(members))
    return {
        "signature_version": signature_name,
        "eligibility_status": SIGNATURE_SPECS[signature_name]["eligibility_status"],
        "signature_field_count": len(fields),
        "required_field_count": len(SIGNATURE_SPECS[signature_name]["required_fields"]),
        "input_rows": total,
        "repeated_group_count": len(repeated),
        "rows_in_repeated_groups": sum(repeated),
        "excess_rows": sum(size - 1 for size in repeated),
        "ineligible_rows": ineligible,
    }
