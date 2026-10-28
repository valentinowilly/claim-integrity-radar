"""Small shared helpers for isolated, deterministic rule detectors."""

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.analytics.normalization import is_missing, normalize_date
from app.analytics.records import validate_case_records


def valid_records(records: Sequence[Mapping[str, Any]]) -> list[tuple[str, Mapping[str, Any]]]:
    return validate_case_records(records)


# Internal key for the complete member list of a candidate whose public ``case_ids``
# are cut to a display limit. It is read by scoring/coverage within one analysis
# execution and is never copied into API reasons (not in any safe-field list).
MEMBER_CASE_IDS = "_member_case_ids"


def candidate_members(candidate: Mapping[str, Any]) -> list[str] | None:
    """All member case IDs: the internal complete list when present, else the public list."""
    members = candidate.get(MEMBER_CASE_IDS)
    if members is None:
        members = candidate.get("case_ids")
    if isinstance(members, (list, tuple)) and all(isinstance(case_id, str) for case_id in members):
        return list(members)
    return None


def membership_incomplete(candidate: Mapping[str, Any]) -> bool:
    """True only when the display cut also lost members (no complete internal list)."""
    return candidate.get("case_ids_truncated") is True and candidate.get(MEMBER_CASE_IDS) is None


def text_value(value: Any) -> str | None:
    # Missing sentinels ("NA", "null", ...) follow normalization.is_missing, as in the
    # repeat and exact-pattern detectors, so two missing codes never match each other.
    if not isinstance(value, str) or is_missing(value):
        return None
    value = value.strip()
    return value if value else None


def date_value(value: Any) -> date | None:
    # Same strict ISO rule as normalization.normalize_date; a malformed string is
    # missing rather than truncated to a plausible date.
    normalized = normalize_date(value)
    return date.fromisoformat(normalized) if normalized else None


def timestamp_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def nonnegative_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None
    return number if number.is_finite() and number >= 0 else None
