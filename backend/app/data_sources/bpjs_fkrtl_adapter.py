"""Explicit, opt-in FKRTL sample adapter; never used by runtime analytics.

This is a schema mapping utility, not an authorization to process BPJS files.
PSTV01 is passed through only as an internal participant comparison key.
FKL02 is intentionally not used as a facility ID or exposed as a case ID.
FKL47 is withheld from billed_amount until its units/timing/formula are cleared;
it is carried only as ``provider_billed_amount_unverified`` for aggregate
reconciliation (never a detector or ML feature). FKL48 is never selected or mapped.

Record contract (``bpjs-fkrtl-sample-map-v2``): see ``FIELD_CONTRACT``. Missing or
invalid source values become ``None`` (unknown), never 0 or "absent service".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import os
from typing import Any

from app.analytics.normalization import is_missing


FKRTL_MAPPING_VERSION = "bpjs-fkrtl-sample-map-v2"
# Without these the record has no stable reference or admission date.
FKRTL_REQUIRED_COLUMNS = ("PSTV01", "FKL02", "FKL03")
# Special top-up codes (dictionary p. 24): sub-acute, procedure, prosthesis, investigation, drug.
SPECIAL_CODE_COLUMNS = ("FKL33", "FKL35", "FKL38", "FKL41", "FKL44")
FKRTL_SOURCE_COLUMNS = (
    "PSTV01", "FKL02", "FKL03", "FKL04", "FKL05", "FKL06", "FKL07",
    "FKL08", "FKL09", "FKL13", "FKL16", "FKL18", "FKL19", "FKL30",
    "FKL31", "FKL32", "FKL47", *SPECIAL_CODE_COLUMNS,
)
if "FKL48" in FKRTL_SOURCE_COLUMNS:  # post-verification amount: never read
    raise RuntimeError("FKL48 must never be read by the FKRTL adapter.")
# Dates outside this range are treated as invalid (unknown), not as real dates.
PLAUSIBLE_DATE_RANGE = (date(2000, 1, 1), date(2099, 12, 31))
CANONICAL_MAPPING = {
    "service_date": "FKL03",
    "discharge_date": "FKL04",
    "province_code": "FKL05",
    "municipality_code": "FKL06",
    "facility_ownership": "FKL07",
    "facility_type": "FKL08",
    "facility_class": "FKL09",
    # Class of care at access (dictionary p. 20); peer key for the duration screen.
    "care_class": "FKL13",
    "admission_diagnosis": "FKL16",
    "primary_diagnosis": "FKL18",
    "claim_group": "FKL19",
    "procedure_code": "FKL30",
    # Tariff region and tariff group (dictionary p. 23); context only.
    "tariff_region": "FKL31",
    "tariff_group": "FKL32",
}
# Which detector needs which field (unlisted fields are optional context).
FIELD_CONTRACT = {
    "case_id": {"source": "PSTV01 + FKL02 (HMAC, in memory)", "required": True},
    "participant_token": {"source": "PSTV01 (HMAC, in memory)", "required": True,
                          "use": "same/different-participant checks only; never a similarity attribute"},
    "service_date": {"source": "FKL03", "required": True, "use": "date window, repeat key, duration"},
    "discharge_date": {"source": "FKL04", "use": "duration screen"},
    "primary_diagnosis": {"source": "FKL18", "use": "repeat key, similarity, ML"},
    "claim_group": {"source": "FKL19", "use": "repeat key, similarity, ML, duration peer group"},
    "procedure_code": {"source": "FKL30", "use": "repeat key, similarity, ML",
                       "missing": "blank meaning unconfirmed: unknown, record ineligible for repeat keys"},
    "care_class": {"source": "FKL13", "use": "duration peer group; class of care, not a facility identity"},
    "tariff_region": {"source": "FKL31", "use": "context only"},
    "tariff_group": {"source": "FKL32", "use": "context only"},
    "provider_billed_amount_unverified": {"source": "FKL47", "use": "same-amount reconciliation subset only",
                                          "missing": "None; never coerced to 0"},
    "billed_amount": {"source": "none", "use": "always None for FKRTL (pre-verification amount unverified)"},
    "special_codes": {"source": "FKL33/35/38/41/44", "use": "unusual special top-up check",
                      "missing": "None when the source has none of these columns; [] when none is billed"},
    "secondary_diagnoses": {"source": "secondary-diagnosis file FKL24 (joined by visit) or upload column FKL24",
                            "use": "severity-without-secondary check, note reading",
                            "missing": "None when the source provides no secondary diagnoses"},
    "facility_id": {"source": "none", "use": "always None: no verified facility identifier"},
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
    if isinstance(value, float):
        # Stata numeric codes are read as float in any chunk containing a
        # missing value; keep "12" and "12.0" equal across chunks.
        if value != value:
            return None
        if value.is_integer():
            return str(int(value))
    text = str(value).strip()
    # One missing-value definition for adapter and detectors (blank, NA, N/A, nan, NaT, null, none, <NA>).
    return None if is_missing(text) else text


def _date_only(value: Any) -> str | None:
    # pandas reads a blank Stata date as NaT, a datetime subclass that is not equal to
    # itself; it is a missing date, not a parse failure of the whole batch.
    if value is None or value != value:
        return None
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        text = _clean(value)
        if text is None:
            return None
        try:
            # FKL03/FKL04 are documented as dates; do not infer a timestamp.
            parsed = date.fromisoformat(text)
        except ValueError:
            return None
    if not PLAUSIBLE_DATE_RANGE[0] <= parsed <= PLAUSIBLE_DATE_RANGE[1]:
        return None
    return parsed.isoformat()


def _amount(value: Any) -> Decimal | None:
    """Finite, non-negative amount or None; missing is never coerced to 0."""
    if isinstance(value, bool):
        return None
    text = _clean(value)
    if text is None:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return amount.normalize() if amount.is_finite() and amount >= 0 else None


def adapt_fkrtl_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    case_reference_secret: bytes,
    reject_duplicate_visits: bool = True,
    secondary_lookup: Mapping[str, Sequence[str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Map rows already read by an explicitly authorized local caller.

    FKL02 is HMAC-pseudonymized into a stable case reference and never returned.
    PSTV01 remains only in the internal ``participant_token`` feature for
    same/different-participant checks; callers must not serialize it.
    ``secondary_lookup`` maps a visit number (FKL02) to its secondary diagnoses (in memory only); without it
    ``secondary_diagnoses`` stays None (not provided by the source).
    """
    output: list[dict[str, Any]] = []
    missing_columns: set[str] = set()
    invalid_dates = invalid_discharge_dates = invalid_amounts = 0
    seen_case_ids: set[str] = set()
    for row in rows:
        missing_columns.update(set(FKRTL_SOURCE_COLUMNS) - set(row))
        case_id = pseudonymous_case_id(
            row.get("PSTV01"), row.get("FKL02"), secret=case_reference_secret
        )
        # Runs always reject repeats; the validation scan maps them and counts them instead.
        if case_id in seen_case_ids and reject_duplicate_visits:
            raise FkrtlMappingError("Duplicate visit references occur in the input batch.")
        seen_case_ids.add(case_id)
        service_date = _date_only(row.get("FKL03"))
        discharge_date = _date_only(row.get("FKL04"))
        invalid_dates += int(_clean(row.get("FKL03")) is not None and service_date is None)
        invalid_discharge_dates += int(_clean(row.get("FKL04")) is not None and discharge_date is None)
        provider_amount = _amount(row.get("FKL47"))
        invalid_amounts += int(_clean(row.get("FKL47")) is not None and provider_amount is None)
        feature: dict[str, Any] = {
            "case_id": case_id,
            "participant_token": pseudonymous_participant_token(
                row.get("PSTV01"), secret=case_reference_secret
            ),
            **{target: _clean(row.get(source)) for target, source in CANONICAL_MAPPING.items()
               if target not in {"service_date", "discharge_date"}},
            "service_date": service_date,
            "discharge_date": discharge_date,
            # Exact decimal string (JSON-safe); None when missing or invalid.
            "provider_billed_amount_unverified": format(provider_amount, "f") if provider_amount is not None else None,
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
            # None when the source has no special-code column; otherwise the billed codes ([] when none).
            "special_codes": ([code for code in (_clean(row.get(column)) for column in SPECIAL_CODE_COLUMNS) if code]
                              if any(column in row for column in SPECIAL_CODE_COLUMNS) else None),
            "secondary_diagnoses": (sorted(set(secondary_lookup.get(_clean(row.get("FKL02")) or "", ())))
                                    if secondary_lookup is not None else None),
        }
        output.append(feature)
    return output, {
        "mapping_version": FKRTL_MAPPING_VERSION,
        "row_count": len(output),
        "missing_source_columns": sorted(missing_columns),
        "invalid_service_date_count": invalid_dates,
        "invalid_discharge_date_count": invalid_discharge_dates,
        "invalid_provider_amount_count": invalid_amounts,
        # Aggregate non-missing count per mapped field (no values).
        "field_non_missing_counts": {
            field: sum(1 for record in output if record.get(field) is not None)
            for field in (*CANONICAL_MAPPING, "provider_billed_amount_unverified")
        },
        "facility_identity": "unavailable",
        "billed_amount": "withheld_pending_FKL47_semantics_confirmation",
        "capacity": "unavailable",
        "evidence_inventory": "unavailable",
        "minute_level_time": "unavailable",
        "ground_truth": "not_present",
    }
