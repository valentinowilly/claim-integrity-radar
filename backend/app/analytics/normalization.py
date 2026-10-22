"""Small, dependency-free canonicalization helpers for rule signatures."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import math
from typing import Any


MISSING_TEXT_VALUES = {"", "na", "n/a", "nan", "nat", "null", "none", "<na>"}


def is_missing(value: Any) -> bool:
    """Recognize nulls, whitespace, and common textual missing sentinels."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().casefold() in MISSING_TEXT_VALUES
    if isinstance(value, float):
        return math.isnan(value)
    if isinstance(value, Decimal):
        return value.is_nan()
    return False


def normalize_text(value: Any) -> str | None:
    """Trim text while preserving case; code case rules are not yet validated."""
    if is_missing(value):
        return None
    normalized = str(value).strip()
    return normalized or None


def normalize_date(value: Any) -> str | None:
    """Return a strict ISO calendar date; invalid values are treated as missing."""
    if is_missing(value):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return None

    raw = value.strip()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            return None


def normalize_amount(value: Any) -> Decimal | None:
    """Parse finite, non-negative amounts exactly; reject booleans and bad values."""
    if is_missing(value) or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return amount.normalize()
