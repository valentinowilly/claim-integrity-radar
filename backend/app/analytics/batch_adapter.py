"""Explicit adapter from the versioned synthetic CSV batch to detector features."""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.data_sources.synthetic_csv import (
    CSV_COLUMNS,
    SYNTHETIC_CSV_MAPPING_VERSION,
    SYNTHETIC_CSV_SCHEMA_VERSION,
)


class BatchAdapterError(ValueError):
    """The batch metadata or normalized records do not match the supported contract."""


_FORBIDDEN_LABEL_FIELDS = frozenset({
    "is_anomaly", "is_synthetic_anomaly", "scenario", "scenario_label",
    "scenario_labels", "scenario_group_id", "scenario_code", "primary_scenario",
    "ground_truth", "intensity_level", "injected_signals", "label_scope",
    "claim_labels", "group_labels",
})


def adapt_batch_features(
    batch: Mapping[str, Any], records: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate supported batch versions and return feature rows plus facilities.

    This is a pass-through mapping for `synthetic-claims-v1` to
    `synthetic-canonical-v1`; it does not infer BPJS source mappings.
    """
    if batch.get("source_type") != "synthetic_csv":
        raise BatchAdapterError("Unsupported batch source.")
    if batch.get("schema_version") != SYNTHETIC_CSV_SCHEMA_VERSION:
        raise BatchAdapterError("Unsupported batch schema version.")
    if batch.get("mapping_version") != SYNTHETIC_CSV_MAPPING_VERSION:
        raise BatchAdapterError("Unsupported batch mapping version.")
    if batch.get("status") not in {"ready", "ready_with_warnings"}:
        raise BatchAdapterError("Batch is not ready for analysis.")
    if not isinstance(batch.get("batch_version"), int) or batch["batch_version"] < 1:
        raise BatchAdapterError("Batch version is invalid.")
    checksum = batch.get("content_checksum")
    if not isinstance(checksum, str) or len(checksum) != 64:
        raise BatchAdapterError("Batch checksum is invalid.")

    adapted: list[dict[str, Any]] = []
    facilities_by_id: dict[str, dict[str, Any]] = {}
    required = set(CSV_COLUMNS)
    text_fields = {
        "claim_id", "case_id", "facility_id", "participant_token", "service_date",
        "province_code", "municipality_code", "facility_ownership", "facility_type",
        "facility_class", "admission_diagnosis", "primary_diagnosis", "claim_group",
        "procedure_code", "service_type",
    }
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise BatchAdapterError(f"Normalized record {index} is invalid.")
        if _FORBIDDEN_LABEL_FIELDS.intersection(record):
            raise BatchAdapterError("Ground-truth fields are not valid detector features.")
        if set(record) != required:
            raise BatchAdapterError("Normalized record does not match the declared synthetic schema.")
        if not isinstance(record.get("claim_id"), str) or not isinstance(record.get("case_id"), str):
            raise BatchAdapterError("Normalized record identifiers are invalid.")
        if any(not isinstance(record.get(field), str) or not record[field].strip()
               for field in text_fields):
            raise BatchAdapterError("A required synthetic text field is invalid.")
        try:
            if date.fromisoformat(record["service_date"]).isoformat() != record["service_date"]:
                raise ValueError
        except (TypeError, ValueError):
            raise BatchAdapterError("A synthetic service date is invalid.") from None
        try:
            amount = Decimal(record["billed_amount"])
            if not amount.is_finite() or amount < 0:
                raise InvalidOperation
        except (TypeError, InvalidOperation, ValueError):
            raise BatchAdapterError("A synthetic billed amount is invalid.") from None
        for field, minimum in (("service_units", 1), ("facility_daily_capacity", 1)):
            if isinstance(record.get(field), bool) or not isinstance(record.get(field), int) or record[field] < minimum:
                raise BatchAdapterError("A synthetic numeric field is invalid.")
        daily_count = record.get("facility_daily_claim_count")
        if daily_count is not None and (isinstance(daily_count, bool)
                                        or not isinstance(daily_count, int) or daily_count < 0):
            raise BatchAdapterError("Optional synthetic daily count is invalid.")
        if not isinstance(record.get("supporting_evidence_present"), bool):
            raise BatchAdapterError("Synthetic evidence flag is invalid.")
        for field in ("supporting_evidence_required", "supporting_evidence_types"):
            value = record.get(field)
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise BatchAdapterError("Synthetic evidence inventory is invalid.")
        timestamp = record.get("service_timestamp")
        recording_status = record.get("supporting_evidence_recording_status")
        if timestamp is not None and not isinstance(timestamp, str):
            raise BatchAdapterError("Optional synthetic timestamp is invalid.")
        if recording_status is not None and not isinstance(recording_status, str):
            raise BatchAdapterError("Optional synthetic evidence status is invalid.")
        feature = deepcopy({field: record[field] for field in CSV_COLUMNS})
        facility_id = feature["facility_id"]
        capacity = feature["facility_daily_capacity"]
        existing = facilities_by_id.get(facility_id)
        if existing is not None and existing["daily_capacity_units"] != capacity:
            raise BatchAdapterError("Facility capacity metadata conflicts within the batch.")
        facilities_by_id[facility_id] = {
            "facility_id": facility_id,
            "daily_capacity_units": capacity,
        }
        adapted.append(feature)
    if not adapted:
        raise BatchAdapterError("A ready batch must contain normalized records.")
    return adapted, [facilities_by_id[key] for key in sorted(facilities_by_id)]


BPJS_RECORD_FIELDS = frozenset({
    "claim_id", "case_id", "participant_token", "service_date", "discharge_date",
    "province_code", "municipality_code", "facility_ownership", "facility_type", "facility_class",
    "care_class", "admission_diagnosis", "primary_diagnosis", "claim_group", "procedure_code",
    "tariff_region", "tariff_group", "provider_billed_amount_unverified", "facility_id", "service_timestamp",
    "service_type", "service_units", "facility_daily_capacity", "supporting_evidence_required",
    "supporting_evidence_types", "supporting_evidence_present", "supporting_evidence_recording_status",
    "billed_amount",
})


BPJS_OPTIONAL_FIELDS = frozenset({"clinical_note", "secondary_diagnoses", "special_codes", "operational_scope"})


def adapt_bpjs_batch_features(batch: Mapping[str, Any], records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Check stored records of an uploaded file in the BPJS column format before analysis."""
    from app.data_sources.bpjs_csv import BPJS_CSV_MAPPING_VERSION, BPJS_CSV_SCHEMA_VERSION

    if batch.get("source_type") != "synthetic_csv" or batch.get("schema_version") != BPJS_CSV_SCHEMA_VERSION \
            or batch.get("mapping_version") != BPJS_CSV_MAPPING_VERSION:
        raise BatchAdapterError("Unsupported batch schema version.")
    if batch.get("status") not in {"ready", "ready_with_warnings"}:
        raise BatchAdapterError("Batch is not ready for analysis.")
    adapted: list[dict[str, Any]] = []
    for record in records:
        # Files stored before the optional fields were added keep validating.
        if not isinstance(record, Mapping) or set(record) - BPJS_OPTIONAL_FIELDS != BPJS_RECORD_FIELDS:
            raise BatchAdapterError("Normalized record does not match the declared BPJS-format schema.")
        if _FORBIDDEN_LABEL_FIELDS.intersection(record):
            raise BatchAdapterError("Ground-truth fields are not valid detector features.")
        if not all(isinstance(record.get(field), str) for field in ("claim_id", "case_id", "participant_token")):
            raise BatchAdapterError("Normalized record identifiers are invalid.")
        try:
            if date.fromisoformat(record["service_date"]).isoformat() != record["service_date"]:
                raise ValueError
        except (TypeError, ValueError):
            raise BatchAdapterError("A service date is invalid.") from None
        note = record.get("clinical_note")
        if note is not None and not isinstance(note, str):
            raise BatchAdapterError("A clinical note is invalid.")
        if record.get("operational_scope") not in (None, "none"):
            raise BatchAdapterError("An operational scope marker is invalid.")
        for field in ("secondary_diagnoses", "special_codes"):
            value = record.get(field)
            if value is not None and not (isinstance(value, list) and all(isinstance(code, str) for code in value)):
                raise BatchAdapterError("A secondary diagnosis or special code list is invalid.")
        adapted.append({**deepcopy(dict(record)), "clinical_note": note,
                        "secondary_diagnoses": record.get("secondary_diagnoses"),
                        "special_codes": record.get("special_codes")})
    if not adapted:
        raise BatchAdapterError("A ready batch must contain normalized records.")
    return adapted
