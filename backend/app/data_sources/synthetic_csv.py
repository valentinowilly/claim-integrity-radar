"""Versioned CSV interchange for wholly synthetic feature records.

This is not a parser or mapping for BPJS source files. Ground-truth fields are
intentionally absent from the allow-listed schema.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Any, Iterable


SYNTHETIC_CSV_SCHEMA_VERSION = "synthetic-claims-v1"
SYNTHETIC_CSV_MAPPING_VERSION = "synthetic-canonical-v1"

# CSV headers and Python field names match the feature records produced by
# synthetic_generator.py. Array fields use a semicolon-delimited representation.
REQUIRED_COLUMNS = (
    "claim_id", "case_id", "facility_id", "participant_token", "service_date",
    "province_code", "municipality_code", "facility_ownership", "facility_type",
    "facility_class", "admission_diagnosis", "primary_diagnosis", "claim_group",
    "procedure_code", "billed_amount", "service_type", "service_units",
    "facility_daily_capacity", "supporting_evidence_required",
    "supporting_evidence_types", "supporting_evidence_present",
)
OPTIONAL_COLUMNS = (
    "service_timestamp", "supporting_evidence_recording_status",
    "facility_daily_claim_count",
)
CSV_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS
MAX_SAFE_ERRORS = 20
GROUND_TRUTH_COLUMNS = frozenset({
    "is_anomaly", "is_synthetic_anomaly", "scenario", "scenario_label", "scenario_labels",
    "scenario_group_id", "scenario_code", "primary_scenario", "ground_truth", "intensity_level",
    "injected_signals", "label_scope", "claim_labels", "group_labels",
})


class CsvImportError(ValueError):
    """A safe, aggregated CSV schema or validation failure."""

    def __init__(self, summary: dict[str, Any]):
        super().__init__("CSV sintetis tidak lolos validasi.")
        self.summary = summary


def _error_summary(counts: dict[str, int], errors: list[dict[str, Any]], row_count: int | None,
                   warnings: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error_count": sum(counts.values()),
        "error_counts": dict(sorted(counts.items())),
        "errors": errors[:MAX_SAFE_ERRORS],
        "errors_truncated": len(errors) > MAX_SAFE_ERRORS,
        "row_count": row_count,
        "warning_counts": warnings or {},
    }


def _cell(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    return value if value else None


def _parse_row(row: dict[str, str | None], row_number: int,
               add_error: Any) -> dict[str, Any] | None:
    result: dict[str, Any] = {}
    valid = True

    def fail(column: str, code: str) -> None:
        nonlocal valid
        valid = False
        add_error(row_number, column, code)

    for key in CSV_COLUMNS:
        value = _cell(row.get(key))
        if key in {"claim_id", "case_id", "facility_id", "participant_token",
                   "province_code", "municipality_code", "facility_ownership", "facility_type",
                   "facility_class", "admission_diagnosis", "primary_diagnosis", "claim_group",
                   "procedure_code", "service_type"}:
            if key in REQUIRED_COLUMNS and value is None:
                fail(key, "required_value_missing")
            if value is not None and len(value) > 256:
                fail(key, "text_value_too_long")
            result[key] = value
        elif key == "billed_amount":
            try:
                amount = Decimal(value) if value is not None else None
                if amount is None or not amount.is_finite() or amount < 0:
                    raise InvalidOperation
                result[key] = format(amount, "f")
            except (InvalidOperation, ValueError):
                fail(key, "invalid_amount")
                result[key] = None
        elif key in {"service_units", "facility_daily_capacity", "facility_daily_claim_count"}:
            if value is None and key in OPTIONAL_COLUMNS:
                result[key] = None
                continue
            try:
                number = int(value) if value is not None else 0
                if (str(number) != value or number < 0
                        or key in {"service_units", "facility_daily_capacity"} and number < 1):
                    raise ValueError
                result[key] = number
            except ValueError:
                fail(key, "invalid_non_negative_integer")
                result[key] = None
        elif key in {"supporting_evidence_required", "supporting_evidence_types"}:
            # Empty is a valid empty list, used by synthetic missing-evidence fixtures.
            result[key] = [] if value is None else [part.strip() for part in value.split(";") if part.strip()]
        elif key == "supporting_evidence_present":
            lowered = (value or "").casefold()
            if lowered not in {"true", "false"}:
                fail(key, "invalid_boolean")
                result[key] = None
            else:
                result[key] = lowered == "true"
        elif key == "service_date":
            try:
                result[key] = date.fromisoformat(value).isoformat() if value else None
                if result[key] is None:
                    raise ValueError
            except ValueError:
                fail(key, "invalid_iso_date")
        elif key == "service_timestamp":
            if value is None:
                result[key] = None
            else:
                try:
                    if "T" not in value:
                        raise ValueError
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    result[key] = parsed.isoformat()
                except ValueError:
                    fail(key, "invalid_iso_datetime")
                    result[key] = None
        elif key == "supporting_evidence_recording_status":
            allowed = {"recorded", "not_recorded", "unknown"}
            if value is not None and value not in allowed:
                fail(key, "unsupported_enum_value")
                result[key] = None
            else:
                result[key] = value

    # Application IDs are opaque synthetic IDs; reject whitespace and unsafe length.
    for key, prefix in (("claim_id", "syn-claim-"), ("case_id", "syn-claim-"),
                        ("facility_id", "syn-facility-"), ("participant_token", "syn-participant-")):
        value = result.get(key)
        if value is not None and (len(value) > 100 or any(ch.isspace() for ch in value)
                                  or not value.startswith(prefix)):
            fail(key, "invalid_identifier")

    return result if valid else None


def parse_synthetic_csv(raw: bytes, *, max_rows: int = 120_000) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Decode, validate, and normalize all rows or reject the entire import."""
    if not raw:
        raise CsvImportError(_error_summary({"empty_input": 1}, [], 0))
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise CsvImportError(_error_summary({"invalid_encoding": 1}, [], None)) from None

    counts: dict[str, int] = {}
    safe_errors: list[dict[str, Any]] = []

    def add_error(row: int | None, column: str | None, code: str) -> None:
        counts[code] = counts.get(code, 0) + 1
        if len(safe_errors) < MAX_SAFE_ERRORS + 1:
            item: dict[str, Any] = {"code": code}
            if row is not None:
                item["row"] = row
            if column is not None:
                item["column"] = column
            safe_errors.append(item)

    stream = StringIO(text, newline="")
    try:
        reader = csv.DictReader(stream, strict=True)
        headers = reader.fieldnames
        if not headers or not any((header or "").strip() for header in headers):
            raise CsvImportError(_error_summary({"empty_file": 1}, [], 0))
        normalized_headers = [header.strip() for header in headers]
        if len(set(normalized_headers)) != len(normalized_headers):
            raise CsvImportError(_error_summary({"duplicate_header": 1}, [], None))
        headers = normalized_headers
        missing = sorted(set(REQUIRED_COLUMNS) - set(headers))
        unexpected = sorted(set(headers) - set(CSV_COLUMNS))
        for column in missing:
            add_error(None, column, "missing_required_column")
        for column in unexpected:
            add_error(None, None,
                      "ground_truth_column_forbidden" if column.casefold() in GROUND_TRUTH_COLUMNS
                      else "unexpected_column")
        if missing or unexpected:
            raise CsvImportError(_error_summary(counts, safe_errors, None))

        # DictReader retains header names; stripped names are checked above. Reject excess cells.
        records: list[dict[str, Any]] = []
        seen_claims: set[str] = set()
        seen_cases: set[str] = set()
        row_count = 1
        for row_count, raw_row in enumerate(reader, start=2):
            if row_count - 1 > max_rows:
                add_error(None, None, "row_limit_exceeded")
                break
            if None in raw_row:
                add_error(row_count, None, "malformed_row_width")
                continue
            normalized_row = {str(key).strip(): value for key, value in raw_row.items()}
            record = _parse_row(normalized_row, row_count, add_error)
            if record is None:
                continue
            claim_id = record["claim_id"]
            case_id = record["case_id"]
            if claim_id in seen_claims:
                add_error(row_count, "claim_id", "duplicate_identifier")
                continue
            if case_id in seen_cases:
                add_error(row_count, "case_id", "duplicate_identifier")
                continue
            seen_claims.add(claim_id)
            seen_cases.add(case_id)
            records.append(record)
    except csv.Error:
        raise CsvImportError(_error_summary({"malformed_csv": 1}, [], None)) from None

    parsed_rows = max(0, row_count - 1) if text else 0
    if parsed_rows == 0 and not counts:
        add_error(None, None, "empty_file")
    if counts:
        raise CsvImportError(_error_summary(counts, safe_errors, parsed_rows))
    if not records:
        raise CsvImportError(_error_summary({"empty_file": 1}, [], parsed_rows))

    missing_optional = sorted(set(OPTIONAL_COLUMNS) - set(headers))
    warnings = {"optional_columns_missing": len(missing_optional)} if missing_optional else {}
    return records, _error_summary({}, [], parsed_rows, warnings)


def export_synthetic_csv(records: Iterable[dict[str, Any]]) -> bytes:
    """Serialize feature-only generator records using the explicit v1 schema."""
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for record in records:
        unknown = set(record) - set(CSV_COLUMNS) - GROUND_TRUTH_COLUMNS
        if unknown:
            raise ValueError("Record memiliki field di luar skema CSV sintetis v1.")
        row: dict[str, Any] = {}
        for column in CSV_COLUMNS:
            value = record.get(column)
            if isinstance(value, list):
                row[column] = ";".join(str(item) for item in value)
            elif value is None:
                row[column] = ""
            elif isinstance(value, bool):
                row[column] = "true" if value else "false"
            else:
                row[column] = str(value)
        writer.writerow(row)
    return output.getvalue().encode("utf-8")

