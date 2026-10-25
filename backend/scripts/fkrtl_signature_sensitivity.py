"""Synthetic-only, same-population sensitivity harness for signature versions."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from app.analytics.fkrtl_signatures import summarize_signature


def compare_synthetic_signature_sensitivity(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare profiles on one fixture population and controlled field edits.

    This helper accepts fixture rows only. It reports group/row/excess and
    ineligible aggregates; it never returns keys, identifiers, or signatures.
    Amount-based definitions are enabled here solely for artificial fixtures.
    """
    scenarios: dict[str, list[dict[str, Any]]] = {"baseline": deepcopy(rows)}
    for name, field, replacement, index_from_end in (
        ("fkl04_changed", "FKL04", "2024-03-09", 2),
        ("fkl47_changed", "FKL47", "987654.32", 2),
        ("normalization_variants", "FKL03", " 2024-03-08T09:30:00 ", 1),
        ("required_value_missing", "FKL18", None, 1),
    ):
        changed = deepcopy(rows)
        if changed:
            changed[max(0, len(changed) - index_from_end)][field] = replacement
        scenarios[name] = changed

    profiles = (
        "repeat_service_v1",
        "repeat_service_same_amount_v1",
        "legacy_audit_signature_v1",
        "cross_participant_exact_v1",
    )
    return {
        scenario: {
            profile: summarize_signature(
                population,
                profile,
                allow_unverified_amount=True,
            )
            for profile in profiles
        }
        for scenario, population in scenarios.items()
    }


def main() -> None:
    rows = [
        {
            "PSTV01": "synthetic-person-a", "FKL02": f"synthetic-visit-{index}",
            "FKL03": "2024-03-08", "FKL04": "2024-03-10", "FKL05": "SYN-PROV",
            "FKL06": "SYN-CITY", "FKL07": "synthetic-owner", "FKL08": "synthetic-type",
            "FKL09": "synthetic-class", "FKL16": "SYN-AD", "FKL18": "SYN-DX",
            "FKL19": "SYN-GROUP", "FKL30": "SYN-PROC", "FKL47": "1000.00",
        }
        for index in range(3)
    ]
    rows.append({**rows[0], "PSTV01": "synthetic-person-b", "FKL02": "synthetic-visit-cross-person"})
    print(json.dumps(compare_synthetic_signature_sensitivity(rows), sort_keys=True))


if __name__ == "__main__":
    main()
