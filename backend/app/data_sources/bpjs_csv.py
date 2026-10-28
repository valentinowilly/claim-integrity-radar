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
        unknown = sorted(set(headers) - set(FKRTL_SOURCE_COLUMNS) - {NOTE_COLUMN, SECONDARY_COLUMN})
        has_secondary = SECONDARY_COLUMN in headers
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
    for record, note, secondary in zip(records, notes, secondaries):
        record["claim_id"] = record["case_id"]
        record["clinical_note"] = note
        record["secondary_diagnoses"] = secondary
    warnings = {key: value for key, value in (
        ("unknown_columns_ignored", len(unknown)),
        # Special top-up columns are rarely present in a file; their absence is not worth a warning.
        ("optional_columns_missing", len(set(coverage["missing_source_columns"]) - set(SPECIAL_CODE_COLUMNS))),
        ("invalid_discharge_date", coverage["invalid_discharge_date_count"]),
        ("invalid_provider_amount", coverage["invalid_provider_amount_count"]),
    ) if value}
    return records, _error_summary({}, [], parsed_rows, warnings)
