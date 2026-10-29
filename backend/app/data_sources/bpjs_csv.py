"""Uploaded CSV files in the BPJS FKRTL claim column format (example data only).

Petugas upload the daily claim export in the same columns as the BPJS FKRTL
data (PSTV01, FKL02, FKL03 ... FKL32, optional FKL47). Rows go through the same
adapter as the server-side FKRTL source, so the analysis, the repeat definition
and the AI trained on the BPJS sample apply unchanged.

Uploads are for example data only: every participant number (PSTV01) must start
with ``SYN``, so a real BPJS export is rejected before any row is stored. The
post-verification amount (FKL48) is refused outright. Validation errors carry row
numbers and codes, never cell values.
"""

from __future__ import annotations

import csv
import hashlib
import re
from io import StringIO
from typing import Any

from app.data_sources.bpjs_fkrtl_adapter import (
    FKRTL_MAPPING_VERSION, FKRTL_REQUIRED_COLUMNS, FKRTL_SOURCE_COLUMNS, SPECIAL_CODE_COLUMNS, FkrtlMappingError,
    adapt_fkrtl_rows,
)
from app.data_sources.synthetic_csv import GROUND_TRUTH_COLUMNS, MAX_SAFE_ERRORS, CsvImportError, _error_summary

BPJS_CSV_SCHEMA_VERSION = "bpjs-fkrtl-csv-v1"
BPJS_CSV_MAPPING_VERSION = FKRTL_MAPPING_VERSION
SYNTHETIC_PARTICIPANT_PREFIX = "SYN"
FORBIDDEN_COLUMNS = frozenset({"FKL48"})
# Optional, not a BPJS column: a short clinical note (resume medis) of example data, read by the clone
# check and shown to verifiers; kept out of analysis results.
NOTE_COLUMN = "CATATAN_KLINIS"
MAX_NOTE_LENGTH = 4000
# Optional: secondary diagnoses of the visit (the BPJS sample keeps them in a separate file, column FKL24);
# in an upload, ICD-10 codes separated by ";".
SECONDARY_COLUMN = "FKL24"
MAX_SECONDARY_CODES = 30
_SECONDARY_SPLIT = re.compile(r"[;|,\s]+")
# Optional operational columns, not in the BPJS sample: facility capacity, service type and time, and the
# supporting-evidence inventory. In production they come from the facility register and the electronic
# medical record; in the example files they are synthetic. They feed the capacity, service-time and
# evidence checks, which stay "not applicable" for files without them.
OPERATIONAL_COLUMNS = {
    "ID_FASKES": "facility_id", "KAPASITAS_HARIAN": "facility_daily_capacity", "JENIS_LAYANAN": "service_type",
    "JUMLAH_LAYANAN": "service_units", "JAM_LAYANAN": "service_timestamp", "BUKTI_WAJIB": "supporting_evidence_required",
    "BUKTI_TERCATAT": "supporting_evidence_types", "STATUS_BUKTI": "supporting_evidence_recording_status",
}
_LIST_SPLIT = re.compile(r"[;|,]+")
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
EVIDENCE_STATUSES = {"tercatat": "recorded", "recorded": "recorded", "belum_tercatat": "not_recorded",
                     "not_recorded": "not_recorded"}
# Example data has no secret identities; a fixed key keeps case references stable across
# uploads (the same claim in two daily files gets the same reference).
UPLOAD_PSEUDONYM_SECRET = hashlib.sha256(b"cir-example-upload-pseudonym-v1").digest()


def is_bpjs_csv(raw: bytes) -> bool:
    """True when the header row uses the BPJS column names."""
    header = raw[:4096].decode("utf-8-sig", errors="ignore").splitlines()[:1]
    return bool(header) and "PSTV01" in {cell.strip() for cell in header[0].split(",")}


def parse_bpjs_csv(raw: bytes, *, max_rows: int = 120_000) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate every row, then map them all, or reject the whole file."""
    if not raw:
        raise CsvImportError(_error_summary({"empty_input": 1}, [], 0))
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise CsvImportError(_error_summary({"invalid_encoding": 1}, [], None)) from None

    counts: dict[str, int] = {}
    errors: list[dict[str, Any]] = []

    def add_error(row: int | None, column: str | None, code: str) -> None:
        counts[code] = counts.get(code, 0) + 1
        if len(errors) < MAX_SAFE_ERRORS + 1:
            item: dict[str, Any] = {"code": code}
            if row is not None:
                item["row"] = row
            if column is not None:
                item["column"] = column
            errors.append(item)

    rows: list[dict[str, str | None]] = []
    row_count = 1
    try:
        reader = csv.DictReader(StringIO(text, newline=""), strict=True)
        headers = [header.strip() for header in (reader.fieldnames or [])]
        if not any(headers):
            raise CsvImportError(_error_summary({"empty_file": 1}, [], 0))
        if len(set(headers)) != len(headers):
            raise CsvImportError(_error_summary({"duplicate_header": 1}, [], None))
        for column in sorted(set(FKRTL_REQUIRED_COLUMNS) - set(headers)):
            add_error(None, column, "missing_required_column")
        for column in sorted(set(headers) & FORBIDDEN_COLUMNS):
            add_error(None, column, "post_verification_amount_forbidden")
        for column in sorted(header for header in headers if header.casefold() in GROUND_TRUTH_COLUMNS):
            add_error(None, None, "ground_truth_column_forbidden")
        if counts:
            raise CsvImportError(_error_summary(counts, errors, None))
        unknown = sorted(set(headers) - set(FKRTL_SOURCE_COLUMNS) - {NOTE_COLUMN, SECONDARY_COLUMN} - set(OPERATIONAL_COLUMNS))
        has_secondary = SECONDARY_COLUMN in headers
        operational_headers = [column for column in OPERATIONAL_COLUMNS if column in headers]
        operations: list[dict[str, Any]] = []
        notes: list[str | None] = []
        secondaries: list[list[str] | None] = []
        seen_visits: set[tuple[str, str]] = set()
        for row_count, raw_row in enumerate(reader, start=2):
            if row_count - 1 > max_rows:
                add_error(None, None, "row_limit_exceeded")
                break
            if None in raw_row:
                add_error(row_count, None, "malformed_row_width")
                continue
            row = {str(key).strip(): (value.strip() or None) if isinstance(value, str) else None
                   for key, value in raw_row.items() if str(key).strip() in FKRTL_SOURCE_COLUMNS}
            participant, visit = row.get("PSTV01"), row.get("FKL02")
            if participant is None or visit is None:
                add_error(row_count, "PSTV01" if participant is None else "FKL02", "missing_required_value")
                continue
            if not participant.upper().startswith(SYNTHETIC_PARTICIPANT_PREFIX):
                add_error(row_count, "PSTV01", "real_participant_not_allowed")
                continue
            if row.get("FKL03") is None:
                add_error(row_count, "FKL03", "missing_required_value")
                continue
            if (participant, visit) in seen_visits:
                add_error(row_count, "FKL02", "duplicate_visit")
                continue
            seen_visits.add((participant, visit))
            operational = _operational_values(raw_row, operational_headers, row.get("FKL03"))
            if isinstance(operational, str):
                add_error(row_count, operational, "invalid_operational_value")
                continue
            operations.append(operational)
            rows.append(row)
            note = raw_row.get(NOTE_COLUMN)
            note = note.strip()[:MAX_NOTE_LENGTH] if isinstance(note, str) else ""
            notes.append(note or None)
            if has_secondary:
                codes = [code.upper() for code in _SECONDARY_SPLIT.split(raw_row.get(SECONDARY_COLUMN) or "") if code]
                secondaries.append(sorted(set(codes))[:MAX_SECONDARY_CODES])
            else:
                secondaries.append(None)
    except csv.Error:
        raise CsvImportError(_error_summary({"malformed_csv": 1}, [], None)) from None

    parsed_rows = max(0, row_count - 1)
    if not counts and not rows:
        add_error(None, None, "empty_file")
    if counts:
        raise CsvImportError(_error_summary(counts, errors, parsed_rows))
    try:
        records, coverage = adapt_fkrtl_rows(rows, case_reference_secret=UPLOAD_PSEUDONYM_SECRET)
    except FkrtlMappingError:
        raise CsvImportError(_error_summary({"unmappable_rows": 1}, [], parsed_rows)) from None
    invalid_dates = coverage["invalid_service_date_count"]
    if invalid_dates:
        raise CsvImportError(_error_summary({"invalid_service_date": invalid_dates}, [], parsed_rows))
    for record, note, secondary, operational in zip(records, notes, secondaries, operations):
        record["claim_id"] = record["case_id"]
        record["clinical_note"] = note
        record["secondary_diagnoses"] = secondary
        record.update(operational)
        if operational_headers and not operational:
            # The file carries operational columns but this claim has none: it is not a recorded service session
            # (e.g. an ordinary inpatient claim), so the capacity and service-time checks do not apply to it.
            record["operational_scope"] = "none"
    conflict = _capacity_conflict(records)
    if conflict:
        raise CsvImportError(_error_summary({"facility_capacity_conflict": 1}, [{"code": "facility_capacity_conflict", "column": "KAPASITAS_HARIAN"}], parsed_rows))
    warnings = {key: value for key, value in (
        ("unknown_columns_ignored", len(unknown)),
        # Special top-up columns are rarely present in a file; their absence is not worth a warning.
        ("optional_columns_missing", len(set(coverage["missing_source_columns"]) - set(SPECIAL_CODE_COLUMNS))),
        ("invalid_discharge_date", coverage["invalid_discharge_date_count"]),
        ("invalid_provider_amount", coverage["invalid_provider_amount_count"]),
    ) if value}
    return records, _error_summary({}, [], parsed_rows, warnings)


def _operational_values(raw_row: dict[str, Any], columns: list[str], service_date: str | None) -> dict[str, Any] | str:
    """Values of the optional operational columns of one row, or the name of the first invalid column."""
    values: dict[str, Any] = {}
    for column in columns:
        text = raw_row.get(column)
        text = text.strip() if isinstance(text, str) else ""
        if not text:
            continue
        field = OPERATIONAL_COLUMNS[column]
        if field in ("facility_daily_capacity", "service_units"):
            if not text.isdigit() or int(text) < 1 or int(text) > 100_000:
                return column
            values[field] = int(text)
        elif field == "service_timestamp":
            match = _TIME.match(text)
            if not match or not service_date:
                return column
            values[field] = f"{service_date[:10]}T{int(match.group(1)):02d}:{match.group(2)}:00"
        elif field in ("supporting_evidence_required", "supporting_evidence_types"):
            if text == "-":
                values[field] = []
                continue
            items = [item.strip().lower() for item in _LIST_SPLIT.split(text) if item.strip()]
            if not items or any(len(item) > 60 for item in items):
                return column
            values[field] = sorted(set(items))
        elif field == "supporting_evidence_recording_status":
            status = EVIDENCE_STATUSES.get(text.lower())
            if status is None:
                return column
            values[field] = status
        else:
            if len(text) > 60:
                return column
            values[field] = text
    if "supporting_evidence_required" in values:
        # An inventory row: recorded unless the file says otherwise; presence follows the recorded list.
        values.setdefault("supporting_evidence_types", [])
        values.setdefault("supporting_evidence_recording_status", "recorded")
        values["supporting_evidence_present"] = bool(values["supporting_evidence_types"])
    return values


def _capacity_conflict(records: list[dict[str, Any]]) -> bool:
    """One facility must have one daily capacity within a file."""
    seen: dict[str, int] = {}
    for record in records:
        facility, capacity = record.get("facility_id"), record.get("facility_daily_capacity")
        if facility is None or capacity is None:
            continue
        if seen.setdefault(facility, capacity) != capacity:
            return True
    return False
