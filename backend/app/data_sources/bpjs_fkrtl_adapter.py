"""Explicit, opt-in FKRTL sample adapter; never used by runtime analytics.

This is a schema mapping utility, not an authorization to process BPJS files.
PSTV01 is passed through only as an internal participant comparison key.
FKL02 is intentionally not used as a facility ID or exposed as a case ID.
FKL47 is withheld from billed_amount until its units/timing/formula are cleared;
FKL48 is never selected or mapped.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
import hashlib
import hmac
import os
from typing import Any


FKRTL_MAPPING_VERSION = "bpjs-fkrtl-sample-map-v1"
FKRTL_SOURCE_COLUMNS = (
    "PSTV01", "FKL02", "FKL03", "FKL04", "FKL05", "FKL06", "FKL07",
    "FKL08", "FKL09", "FKL16", "FKL18", "FKL19", "FKL30",
)
CANONICAL_MAPPING = {
    "service_date": "FKL03",
    "discharge_date": "FKL04",
    "province_code": "FKL05",
    "municipality_code": "FKL06",
    "facility_ownership": "FKL07",
    "facility_type": "FKL08",
    "facility_class": "FKL09",
    "admission_diagnosis": "FKL16",
    "primary_diagnosis": "FKL18",
    "claim_group": "FKL19",
    "procedure_code": "FKL30",
}


class FkrtlMappingError(ValueError):
    """Safe schema or value error without echoing source values."""


def pseudonym_secret_from_environment(
    variable: str = "CIR_FKRTL_PSEUDONYM_KEY",
) -> bytes:
    """Load a hex-encoded key from local process environment without logging it."""
    encoded = os.environ.get(variable)
    if not encoded:
        raise FkrtlMappingError("The local pseudonym key is not configured.")
    try:
        secret = bytes.fromhex(encoded)
    except ValueError:
        raise FkrtlMappingError("The local pseudonym key configuration is invalid.") from None
    if len(secret) < 32:
        raise FkrtlMappingError("The local pseudonym key of sufficient length is required.")
    return secret


def pseudonymous_case_id(participant_id: Any, visit_id: Any, *, secret: bytes) -> str:
    """Create a stable local review reference using keyed pseudonymization.

    Supply a locally protected key (at least 32 bytes); never commit or log it.
    FKL02 is documented as visit identity within a participant, so PSTV01 scopes
    it internally. Neither source value is returned. Replacing the key
    intentionally changes generated case references.
    """
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise FkrtlMappingError("A local pseudonym key of sufficient length is required.")
    participant = _clean(participant_id)
    visit = _clean(visit_id)
    if participant is None or visit is None:
        raise FkrtlMappingError("Participant and visit references are required to create a case reference.")
    message = b"case:" + f"{len(participant)}:{participant}{len(visit)}:{visit}".encode("utf-8")
    digest = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return f"case_{digest[:32]}"


def pseudonymous_participant_token(participant_id: Any, *, secret: bytes) -> str:
    """Return a keyed, internal-only stable participant comparison token."""
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise FkrtlMappingError("A local pseudonym key of sufficient length is required.")
    participant = _clean(participant_id)
    if participant is None:
        raise FkrtlMappingError("A participant reference is required for internal comparison.")
    digest = hmac.new(secret, b"participant:" + participant.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"participant_{digest[:32]}"


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if not text or text.casefold() in {"nan", "nat", "none", "null", "<na>"} else text


def _date_only(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = _clean(value)
    if text is None:
        return None
    try:
        # FKL03/FKL04 are documented as dates; do not infer a timestamp.
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def adapt_fkrtl_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    case_reference_secret: bytes,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Map rows already read by an explicitly authorized local caller.

    FKL02 is HMAC-pseudonymized into a stable case reference and never returned.
    PSTV01 remains only in the internal ``participant_token`` feature for
    same/different-participant checks; callers must not serialize it.
    """
    output: list[dict[str, Any]] = []
    missing_columns: set[str] = set()
    invalid_dates = 0
    seen_case_ids: set[str] = set()
    for row in rows:
        missing_columns.update(set(FKRTL_SOURCE_COLUMNS) - set(row))
        case_id = pseudonymous_case_id(
            row.get("PSTV01"), row.get("FKL02"), secret=case_reference_secret
        )
        if case_id in seen_case_ids:
            raise FkrtlMappingError("Duplicate visit references occur in the input batch.")
        seen_case_ids.add(case_id)
        service_date = _date_only(row.get("FKL03"))
        discharge_date = _date_only(row.get("FKL04"))
        invalid_dates += int(row.get("FKL03") is not None and service_date is None)
        feature: dict[str, Any] = {
            "case_id": case_id,
            "participant_token": pseudonymous_participant_token(
                row.get("PSTV01"), secret=case_reference_secret
            ),
            **{target: _clean(row.get(source)) for target, source in CANONICAL_MAPPING.items()
               if target not in {"service_date", "discharge_date"}},
            "service_date": service_date,
            "discharge_date": discharge_date,
            # These synthetic-only prerequisites are deliberately unavailable.
            "facility_id": None,
            "service_timestamp": None,
            "service_type": None,
            "service_units": None,
            "facility_daily_capacity": None,
            "supporting_evidence_required": None,
            "supporting_evidence_types": None,
            "supporting_evidence_present": None,
            "supporting_evidence_recording_status": None,
            "billed_amount": None,
        }
        output.append(feature)
    return output, {
        "mapping_version": FKRTL_MAPPING_VERSION,
        "row_count": len(output),
        "missing_source_columns": sorted(missing_columns),
        "invalid_service_date_count": invalid_dates,
        "facility_identity": "unavailable",
        "billed_amount": "withheld_pending_FKL47_semantics_confirmation",
        "capacity": "unavailable",
        "evidence_inventory": "unavailable",
        "minute_level_time": "unavailable",
        "ground_truth": "not_present",
    }
