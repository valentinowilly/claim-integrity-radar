"""Server-configured local BPJS FKRTL sample source for persisted AnalysisRuns.

The file path, pseudonym key, admission-date window, and row cap come only
from the backend process environment; request input never selects a path.
Status and errors never include the path, row values, or identifiers. The
pandas-based reader in ``scripts/`` is imported lazily so the API and health
path do not load it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
import hashlib
import hmac
import importlib.util
import os
from pathlib import Path
from typing import Any

from app.data_sources.bpjs_fkrtl_adapter import (
    FKRTL_MAPPING_VERSION,
    SPECIAL_CODE_COLUMNS,
    FkrtlMappingError,
    pseudonym_secret_from_environment,
)
from app.data_sources.providers import FeatureDataset


FKRTL_SOURCE_TYPE = "bpjs_fkrtl_local"
FKRTL_SOURCE_CLASSIFICATION = "bpjs_sample_local"
FKRTL_SCHEMA_PROFILE = "bpjs-fkrtl-sample-compatible-v1"
FKRTL_BATCH_KEY = "bpjs-fkrtl-local-sample"
PATH_VARIABLE = "BPJS_FKRTL_SAMPLE_PATH"
# Optional: the sample's secondary-diagnosis file (e.g. 202405_diagnosissekunder.dta), joined by visit number.
SECONDARY_PATH_VARIABLE = "BPJS_FKRTL_SECONDARY_PATH"
KEY_VARIABLE = "CIR_FKRTL_PSEUDONYM_KEY"
DATE_FROM_VARIABLE = "BPJS_FKRTL_DATE_FROM"
DATE_TO_VARIABLE = "BPJS_FKRTL_DATE_TO"
MAX_ROWS_VARIABLE = "BPJS_FKRTL_MAX_ROWS"
DEFAULT_MAX_ROWS = 50_000
MAX_ROWS_LIMIT = 2_000_000
# Measured on the 202403 sample: any 7-day window holds at most ~38k rows.
RECOMMENDED_WINDOW = ("2024-03-04", "2024-03-10")


class FkrtlSourceUnavailable(Exception):
    """Safe, actionable configuration or read error; never echoes paths or values."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LoadedFkrtlSource:
    dataset: FeatureDataset
    content_fingerprint: str
    row_count: int
    max_rows: int
    date_window: tuple[date, date]
    selection: dict[str, Any]
    invalid_service_date_count: int


def configured_max_rows() -> int:
    raw = os.environ.get(MAX_ROWS_VARIABLE, str(DEFAULT_MAX_ROWS)).strip()
    try:
        value = int(raw)
    except ValueError:
        raise FkrtlSourceUnavailable(
            "FKRTL_CONFIGURATION_INVALID", f"{MAX_ROWS_VARIABLE} harus berupa bilangan bulat.",
        ) from None
    if not 1 <= value <= MAX_ROWS_LIMIT:
        raise FkrtlSourceUnavailable(
            "FKRTL_CONFIGURATION_INVALID", f"{MAX_ROWS_VARIABLE} harus 1-{MAX_ROWS_LIMIT}.",
        )
    return value


def configured_date_window() -> tuple[date, date]:
    """Inclusive admission-date (FKL03) bounds; both are required."""
    raw_from = os.environ.get(DATE_FROM_VARIABLE, "").strip()
    raw_to = os.environ.get(DATE_TO_VARIABLE, "").strip()
    if not raw_from or not raw_to:
        raise FkrtlSourceUnavailable(
            "FKRTL_DATE_WINDOW_NOT_CONFIGURED",
            f"Set {DATE_FROM_VARIABLE} dan {DATE_TO_VARIABLE} (YYYY-MM-DD, inklusif), "
            f"mis. {RECOMMENDED_WINDOW[0]} s.d. {RECOMMENDED_WINDOW[1]}.",
        )
    try:
        window = (date.fromisoformat(raw_from), date.fromisoformat(raw_to))
    except ValueError:
        raise FkrtlSourceUnavailable(
            "FKRTL_CONFIGURATION_INVALID", f"{DATE_FROM_VARIABLE}/{DATE_TO_VARIABLE} harus berformat YYYY-MM-DD.",
        ) from None
    if window[0] > window[1]:
        raise FkrtlSourceUnavailable(
            "FKRTL_CONFIGURATION_INVALID", f"{DATE_FROM_VARIABLE} tidak boleh setelah {DATE_TO_VARIABLE}.",
        )
    return window


def _issues() -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    configured = os.environ.get(PATH_VARIABLE, "").strip()
    if not configured:
        issues.append({"code": "FKRTL_SOURCE_NOT_CONFIGURED",
                       "message": f"Set {PATH_VARIABLE} pada environment backend ke file 202403_fkrtl.dta lokal."})
    else:
        path = Path(configured).expanduser()
        if path.suffix.lower() != ".dta" or not path.is_file():
            issues.append({"code": "FKRTL_SOURCE_FILE_UNAVAILABLE",
                           "message": f"File pada {PATH_VARIABLE} tidak ditemukan atau bukan berkas .dta."})
    secondary = os.environ.get(SECONDARY_PATH_VARIABLE, "").strip()
    if secondary and (Path(secondary).expanduser().suffix.lower() != ".dta" or not Path(secondary).expanduser().is_file()):
        issues.append({"code": "FKRTL_SECONDARY_FILE_UNAVAILABLE",
                       "message": f"File pada {SECONDARY_PATH_VARIABLE} tidak ditemukan atau bukan berkas .dta. "
                                  "Kosongkan variabel ini bila diagnosis sekunder tidak dipakai."})
    if importlib.util.find_spec("pandas") is None:
        issues.append({"code": "FKRTL_READER_UNAVAILABLE",
                       "message": "Pembaca .dta membutuhkan pandas; jalankan pip install -r requirements.txt."})
    try:
        pseudonym_secret_from_environment(KEY_VARIABLE)
    except FkrtlMappingError:
        issues.append({"code": "FKRTL_PSEUDONYM_KEY_INVALID",
                       "message": f"Set {KEY_VARIABLE} ke kunci hex lokal minimal 32 byte (64 karakter hex)."})
    for check in (configured_date_window, configured_max_rows):
        try:
            check()
        except FkrtlSourceUnavailable as exc:
            issues.append({"code": exc.code, "message": exc.message})
    return issues


def fkrtl_source_status() -> dict[str, Any]:
    """Return configuration readiness only; the file is not opened here."""
    issues = _issues()
    try:
        max_rows: int | None = configured_max_rows()
    except FkrtlSourceUnavailable:
        max_rows = None
    try:
        window: tuple[date, date] | None = configured_date_window()
    except FkrtlSourceUnavailable:
        window = None
    return {
        "source_type": FKRTL_SOURCE_TYPE,
        "label": "Sampel FKRTL BPJS (lokal, server-side)",
        "classification": FKRTL_SOURCE_CLASSIFICATION,
        "schema_profile": FKRTL_SCHEMA_PROFILE,
        "mapping_version": FKRTL_MAPPING_VERSION,
        "configured": bool(os.environ.get(PATH_VARIABLE, "").strip()),
        "secondary_diagnoses": "linked" if configured_secondary_path() else "not_configured",
        "available": not issues,
        "max_rows": max_rows,
        "date_from": window[0].isoformat() if window else None,
        "date_to": window[1].isoformat() if window else None,
        "issues": issues,
    }


def configured_secondary_path() -> Path | None:
    raw = os.environ.get(SECONDARY_PATH_VARIABLE, "").strip()
    path = Path(raw).expanduser() if raw else None
    return path if path is not None and path.is_file() else None


def _fingerprint(path: Path, window: tuple[date, date], max_rows: int) -> str:
    """Identify the configured file version and selection without hashing contents."""
    stat = path.stat()
    basis = (
        f"size={stat.st_size};mtime_ns={stat.st_mtime_ns};date_from={window[0].isoformat()};"
        f"date_to={window[1].isoformat()};max_rows={max_rows};mapping={FKRTL_MAPPING_VERSION}"
    )
    secondary = configured_secondary_path()
    if secondary is not None:  # a linked secondary-diagnosis file is part of the analysed input
        secondary_stat = secondary.stat()
        basis += f";secondary_size={secondary_stat.st_size};secondary_mtime_ns={secondary_stat.st_mtime_ns}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def current_source_fingerprint() -> str | None:
    """Fingerprint of the configured file and selection, or None when not configured/readable."""
    if _issues():
        return None
    try:
        path = Path(os.environ[PATH_VARIABLE].strip()).expanduser()
        content = _fingerprint(path, configured_date_window(), configured_max_rows())
        secret = pseudonym_secret_from_environment(KEY_VARIABLE)
    except (OSError, FkrtlSourceUnavailable, FkrtlMappingError):
        return None
    # The validated file location and pseudonym key also define the source: a different file
    # with the same size and timestamp, or another key, must need a new validation. Both enter
    # one-way digests only; neither the path nor the key is stored.
    location = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()
    key_digest = hmac.new(secret, b"cir-fkrtl-validation-fingerprint", hashlib.sha256).hexdigest()
    return hashlib.sha256(f"{content};{location};{key_digest}".encode("utf-8")).hexdigest()


# Row-level eligibility rules as applied by each detector (see the prerequisite functions in
# repeat_definitions, near_duplicate_claims and length_of_stay). Counts come from those functions.
_CHECK_RULES = {
    "repeat_billing_candidate": {
        "required_columns": ["PSTV01", "FKL03", "FKL18", "FKL19", "FKL30"],
        "optional_columns": ["FKL05", "FKL06", "FKL07", "FKL08", "FKL09", "FKL16"],
        "rule": "Every key column must be present; a blank FKL30 leaves the visit unassessed (its meaning is "
                "unconfirmed). Optional columns are reviewer context only.",
    },
    "near_duplicate_claim_candidate": {
        "required_columns": ["PSTV01"],
        "optional_columns": ["FKL03", "FKL05", "FKL06", "FKL07", "FKL08", "FKL09", "FKL16", "FKL18", "FKL19", "FKL30"],
        "rule": "No single attribute is required: at least 9 of these 10 attributes must be present (one may be "
                "blank, e.g. FKL30) and one blocking group must be complete together with the admission date "
                "(district + primary diagnosis + ownership; province + INA-CBG + facility type; or admission "
                "diagnosis + procedure + facility class). Only claims with the same admission date are compared. "
                "Meeting this does not guarantee assessment: the bounded search may not reach a record.",
    },
    "length_of_stay": {
        "required_columns": ["FKL03", "FKL04", "FKL19", "FKL13"],
        "optional_columns": [],
        "rule": "Valid admission and discharge dates (discharge not before admission), INA-CBG and class of care. "
                "Peer groups below the minimum support are unassessed when the analysis runs.",
    },
}


def _detector_readiness(scan: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-check eligibility inside the configured window (counts only)."""
    from scripts.fkrtl_dta_provider import FKRTL_NOT_APPLICABLE_DETECTORS

    in_window = scan["rows_in_window"]
    rows = []
    for check, rule in _CHECK_RULES.items():
        eligibility = scan["window_eligibility"][check]
        rows.append({"check": check, "status": "applicable", **rule, "rows_in_window": in_window,
                     "rows_meeting_prerequisites": eligibility["eligible"],
                     "rows_excluded": eligibility["excluded"]})
    rows += [{"check": code, "status": "not_applicable", "required_columns": [], "optional_columns": [],
              "rule": reason, "rows_in_window": in_window, "rows_meeting_prerequisites": 0, "rows_excluded": {}}
             for code, reason in FKRTL_NOT_APPLICABLE_DETECTORS.items()]
    return rows


def validate_fkrtl_local_source(progress: Callable[[int, int | None], None] | None = None) -> dict[str, Any]:
    """Open the configured file and report data quality as counts; no paths, values or IDs.

    Status ``failed`` means a run would fail or be meaningless (configuration, unreadable
    file, required columns, duplicate visits, empty or oversized window); warnings mark
    data-quality issues that leave records unassessed but do not block a run.
    """
    base = {
        "source_type": FKRTL_SOURCE_TYPE, "classification": FKRTL_SOURCE_CLASSIFICATION,
        "schema_profile": FKRTL_SCHEMA_PROFILE, "mapping_version": FKRTL_MAPPING_VERSION,
    }
    issues = _issues()
    if issues:
        return {**base, "status": "failed", "errors": issues, "warnings": [], "scan": None, "checks": []}
    path = Path(os.environ[PATH_VARIABLE].strip()).expanduser()
    window, max_rows = configured_date_window(), configured_max_rows()
    try:
        from scripts.fkrtl_dta_reader import scan_fkrtl_dta

        scan = scan_fkrtl_dta(path, case_reference_secret=pseudonym_secret_from_environment(KEY_VARIABLE),
                              date_window=window, progress=progress)
    except FkrtlMappingError as exc:
        message = str(exc) if str(exc).startswith(("Input file", "The selected FKRTL")) else \
            "Sampel FKRTL tidak dapat dibaca dengan aman."
        return {**base, "status": "failed", "warnings": [], "scan": None, "checks": [],
                "errors": [{"code": "FKRTL_SOURCE_READ_FAILED",
                            "message": f"{message} Periksa bahwa {PATH_VARIABLE} menunjuk berkas .dta FKRTL yang utuh."}]}
    except Exception:
        return {**base, "status": "failed", "warnings": [], "scan": None, "checks": [],
                "errors": [{"code": "FKRTL_SOURCE_READ_FAILED",
                            "message": "Sampel FKRTL tidak dapat dibaca dengan aman."}]}
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if scan["required_columns_missing"]:
        errors.append({"code": "FKRTL_REQUIRED_COLUMNS_MISSING",
                       "message": "Kolom wajib tidak ada: " + ", ".join(scan["required_columns_missing"])
                                  + ". Gunakan berkas FKRTL pelayanan (bukan diagnosis sekunder atau dataset lain)."})
        return {**base, "status": "failed", "errors": errors, "warnings": [], "scan": {
            "columns_present": scan["columns_present"], "columns_missing": scan["columns_missing"]}, "checks": []}
    if scan["duplicate_visit_rows"]:
        errors.append({"code": "FKRTL_DUPLICATE_VISITS",
                       "message": f"{scan['duplicate_visit_rows']} baris mengulang referensi kunjungan (PSTV01+FKL02). "
                                  "Run memerlukan satu baris per kunjungan; jangan memakai hasil join satu-ke-banyak."})
    if not scan["rows_in_window"]:
        errors.append({"code": "FKRTL_WINDOW_EMPTY",
                       "message": f"Tidak ada kunjungan dengan FKL03 di {window[0].isoformat()} s.d. {window[1].isoformat()}. "
                                  f"Sesuaikan {DATE_FROM_VARIABLE}/{DATE_TO_VARIABLE} dengan rentang tanggal berkas."})
    elif scan["rows_in_window"] > max_rows:
        errors.append({"code": "FKRTL_WINDOW_EXCEEDS_CAP",
                       "message": f"Jendela berisi {scan['rows_in_window']} baris, melebihi batas {max_rows}. "
                                  f"Persempit jendela atau naikkan {MAX_ROWS_VARIABLE} setelah mengukur memori."})
    # Special top-up columns are often absent from a file; that only leaves their check not applicable.
    missing_optional = [column for column in scan["columns_missing"] if column not in SPECIAL_CODE_COLUMNS]
    if missing_optional:
        warnings.append({"code": "FKRTL_OPTIONAL_COLUMNS_MISSING",
                         "message": "Kolom opsional tidak ada (pemeriksaan terkait tidak dinilai): "
                                    + ", ".join(missing_optional) + "."})
    if scan["admission_date_invalid"] or scan["discharge_date_invalid"]:
        warnings.append({"code": "FKRTL_INVALID_DATES",
                         "message": f"{scan['admission_date_invalid']} FKL03 dan {scan['discharge_date_invalid']} FKL04 "
                                    "tidak valid; record tersebut tidak masuk jendela atau tidak dinilai durasinya."})
    if scan["missing_value_counts"].get("FKL30"):
        warnings.append({"code": "FKRTL_PROCEDURE_BLANK",
                         "message": f"{scan['missing_value_counts']['FKL30']} baris FKL30 kosong; makna kosong belum "
                                    "dikonfirmasi BPJS sehingga record tersebut tidak dinilai pola layanan berulang."})
    return {
        **base,
        "status": "failed" if errors else ("passed_with_warnings" if warnings else "passed"),
        "errors": errors,
        "warnings": warnings,
        "date_window": {"from": window[0].isoformat(), "to": window[1].isoformat()},
        "max_rows": max_rows,
        "scan": {key: scan[key] for key in (
            "rows_total", "rows_in_window", "columns_present", "columns_missing", "missing_value_counts",
            "admission_date_invalid", "discharge_date_invalid", "discharge_before_admission",
            "duplicate_visit_rows", "duplicate_visit_rows_in_window", "admission_date_range")},
        "checks": _detector_readiness(scan),
        "post_verification_amount": "FKL48 is never read",
    }


def load_fkrtl_local_source() -> LoadedFkrtlSource:
    """Read every row admitted inside the configured window (read-only, allow-listed columns)."""
    issues = _issues()
    if issues:
        raise FkrtlSourceUnavailable(issues[0]["code"], issues[0]["message"])
    path = Path(os.environ[PATH_VARIABLE].strip()).expanduser()
    max_rows = configured_max_rows()
    window = configured_date_window()
    secret = pseudonym_secret_from_environment(KEY_VARIABLE)
    try:
        fingerprint = _fingerprint(path, window, max_rows)
        from scripts.fkrtl_dta_provider import LocalFkrtlDtaProvider
        from scripts.fkrtl_dta_reader import FkrtlWindowExceedsCap

        try:
            dataset = LocalFkrtlDtaProvider(
                path, case_reference_secret=secret, source_classification="bpjs_sample",
                date_window=window, max_rows=max_rows, secondary_path=configured_secondary_path(),
            ).load()
        except FkrtlWindowExceedsCap as exc:
            raise FkrtlSourceUnavailable(
                "FKRTL_WINDOW_EXCEEDS_CAP",
                f"Jendela {window[0].isoformat()} s.d. {window[1].isoformat()} berisi {exc.eligible_rows} baris, "
                f"melebihi batas {exc.max_rows}. Persempit jendela tanggal atau naikkan {MAX_ROWS_VARIABLE} "
                "setelah mengukur memori; data tidak dipotong diam-diam.",
            ) from None
    except FkrtlSourceUnavailable:
        raise
    except FkrtlMappingError as exc:
        raise FkrtlSourceUnavailable("FKRTL_SOURCE_READ_FAILED", str(exc)) from None
    except Exception:
        raise FkrtlSourceUnavailable(
            "FKRTL_SOURCE_READ_FAILED", "Sampel FKRTL tidak dapat dibaca atau dipetakan dengan aman.",
        ) from None
    coverage = dataset.source_metadata.get("adapter_coverage", {})
    return LoadedFkrtlSource(
        dataset=dataset,
        content_fingerprint=fingerprint,
        row_count=len(dataset.records),
        max_rows=max_rows,
        date_window=window,
        selection=dict(dataset.source_metadata.get("selection", {})),
        invalid_service_date_count=int(coverage.get("invalid_service_date_count", 0)),
    )
