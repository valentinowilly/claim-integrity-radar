"""Validation shared by isolated detector functions."""

from collections.abc import Mapping, Sequence
import re
from typing import Any

from app.analytics.normalization import normalize_text


CASE_ID_PATTERN = re.compile(r"^(?:syn-|case_)[A-Za-z0-9][A-Za-z0-9_-]{0,57}$")


def validate_case_records(
    records: Sequence[Mapping[str, Any]],
) -> list[tuple[str, Mapping[str, Any]]]:
    """Require unique, opaque application case IDs without changing records."""
    if isinstance(records, (str, bytes)):
        raise TypeError("records harus berupa urutan objek record")

    validated: list[tuple[str, Mapping[str, Any]]] = []
    seen_case_ids: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise TypeError(f"record ke-{index} harus berupa mapping")
        case_id = record.get("case_id")
        if not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id):
            raise ValueError(
                f"case_id record ke-{index} harus berupa ID aplikasi 'case_' atau ID fixture 'syn-'"
            )
        if case_id in seen_case_ids:
            raise ValueError(f"case_id duplikat: {case_id}")
        if case_id == normalize_text(record.get("participant_token")):
            raise ValueError("case_id harus dibuat terpisah dari token peserta")
        seen_case_ids.add(case_id)
        validated.append((case_id, record))
    return validated
