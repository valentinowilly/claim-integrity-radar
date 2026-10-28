"""Opt-in local .dta chunk reader; do not invoke without approved data use."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import date
from pathlib import Path
import hashlib
import sqlite3
import tempfile
from typing import Any

import numpy as np
import pandas as pd

from app.data_sources.bpjs_fkrtl_adapter import (
    FKRTL_REQUIRED_COLUMNS,
    FKRTL_SOURCE_COLUMNS,
    FkrtlMappingError,
    _clean,
    adapt_fkrtl_rows,
)


class FkrtlWindowExceedsCap(FkrtlMappingError):
    """The selected rows exceed the configured cap; nothing is truncated."""

    def __init__(self, eligible_rows: int, max_rows: int):
        super().__init__(
            f"The selected window contains {eligible_rows} rows, above the configured cap of {max_rows}."
        )
        self.eligible_rows = eligible_rows
        self.max_rows = max_rows


def iter_fkrtl_dta(
    input_path: str | Path,
    *,
    case_reference_secret: bytes,
    chunk_size: int = 50_000,
    scratch_directory: str | Path | None = None,
    date_window: tuple[date, date] | None = None,
    max_rows: int | None = None,
    secondary_lookup: Mapping[str, Sequence[str]] | None = None,
) -> Iterator[tuple[list[dict[str, Any]], dict[str, Any]]]:
    """Yield canonicalized chunks; source identifiers are not returned.

    Only allow-listed fields are read. FKL47/48 are intentionally excluded.
    Errors avoid echoing input paths or row values.

    ``date_window`` keeps rows whose admission date (FKL03) lies within the
    inclusive bounds; selection depends only on that date, so it is the same
    for any chunk size or file order. Rows outside the window or with an
    invalid admission date are counted, never mapped. ``max_rows`` is a cap on
    selected rows: exceeding it raises ``FkrtlWindowExceedsCap`` after counting
    the full selection, never a silent first-N truncation.
    """
    path = Path(input_path)
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    if max_rows is not None and max_rows < 1:
        raise ValueError("max_rows must be positive")
    if date_window is not None and date_window[0] > date_window[1]:
        raise ValueError("date window start must not be after its end")
    if not path.is_file():
        raise FkrtlMappingError("Input file is unavailable.")
    try:
        # Header only: decide which allow-listed columns exist before reading rows.
        with pd.read_stata(path, iterator=True, convert_categoricals=False) as header:
            available = set(header.variable_labels())
    except Exception as exc:
        raise FkrtlMappingError("The selected FKRTL input could not be opened safely.") from exc
    missing_required = [column for column in FKRTL_REQUIRED_COLUMNS if column not in available]
    if missing_required:
        # Column names only; no values are echoed.
        raise FkrtlMappingError(f"Required FKRTL columns are missing: {', '.join(missing_required)}.")
    # Optional columns that are absent stay None and are reported as missing.
    columns = [column for column in FKRTL_SOURCE_COLUMNS if column in available]
    try:
        # The context manager releases the source file handle promptly (Windows
        # otherwise keeps it locked until garbage collection).
        with pd.read_stata(
            path,
            iterator=True,
            chunksize=chunk_size,
            columns=columns,
            convert_categoricals=False,
        ) as reader:
            yield from _iter_mapped(reader, case_reference_secret, scratch_directory, date_window, max_rows,
                                    secondary_lookup)
    except FkrtlMappingError:
        raise
    except Exception as exc:
        raise FkrtlMappingError("The selected FKRTL input could not be mapped safely.") from exc


def _missing_mask(series: pd.Series) -> np.ndarray:
    """Vectorized form of the adapter's ``_clean(value) is None`` for one column."""
    from app.analytics.normalization import MISSING_TEXT_VALUES

    mask = series.isna().to_numpy(copy=True)
    if series.dtype == object:
        present = ~mask
        text = series[present].astype(str).str.strip().str.casefold()
        mask[present] = text.isin(MISSING_TEXT_VALUES).to_numpy()
    return mask


def later_occurrence_flags(digests: bytes) -> np.ndarray:
    """True for every occurrence of a 32-byte digest after its first one, in input order.

    Exact (digests are compared as four 64-bit integers) and order-preserving: lexsort is
    stable, so among equal digests the first in input order stays unflagged.
    """
    words = np.frombuffer(digests, dtype=">u8").reshape(-1, 4)
    if len(words) == 0:
        return np.zeros(0, dtype=bool)
    order = np.lexsort(words.T[::-1])
    ordered = words[order]
    flags = np.zeros(len(words), dtype=bool)
    flags[order[1:]] = (ordered[1:] == ordered[:-1]).all(axis=1)
    return flags


def _duplicate_flags(connection: sqlite3.Connection, digests: list[str]) -> list[bool]:
    """Flag every occurrence of a visit digest after its first one, across all chunks."""
    seen_before: set[str] = set()
    for start in range(0, len(digests), 900):
        batch = digests[start:start + 900]
        placeholders = ",".join("?" * len(batch))
        seen_before.update(row[0] for row in connection.execute(
            f"SELECT digest FROM seen WHERE digest IN ({placeholders})", batch))
    flags, current = [], set()
    for digest in digests:
        flags.append(digest in seen_before or digest in current)
        current.add(digest)
    connection.executemany("INSERT OR IGNORE INTO seen(digest) VALUES (?)", ((digest,) for digest in current))
    return flags


def scan_fkrtl_dta(
    input_path: str | Path,
    *,
    case_reference_secret: bytes,
    date_window: tuple[date, date],
    chunk_size: int = 100_000,
    scratch_directory: str | Path | None = None,
    progress: Callable[[int, int | None], None] | None = None,
) -> dict[str, Any]:
    """Aggregate validation scan of the whole file; returns counts only, never values.

    ``progress(rows_scanned, rows_total)`` is called after each chunk; ``rows_total`` comes
    from the file header when pandas exposes it, else None. It never changes the counts.

    Each row is mapped by the same adapter as a run (allow-listed columns; FKL48 is never
    read), and window eligibility uses the detectors' own prerequisite functions, so the
    counts follow the rules a run applies. Duplicate visit references are detected with
    digests of the HMAC case reference (``later_occurrence_flags``); ``scratch_directory``
    is accepted for compatibility and no longer used by the scan.
    """
    from collections import Counter

    from app.analytics.length_of_stay import row_prerequisite_reason
    from app.analytics.near_duplicate_claims import prerequisite_reason
    from app.analytics.repeat_billing import REPEAT_SERVICE_PROFILE
    from app.analytics.repeat_definitions import REPEAT_SERVICE_KEY, RepeatDefinition, missing_key_fields

    repeat_definition = RepeatDefinition(name=REPEAT_SERVICE_PROFILE, key_fields=REPEAT_SERVICE_KEY)
    path = Path(input_path)
    if not path.is_file():
        raise FkrtlMappingError("Input file is unavailable.")
    try:
        with pd.read_stata(path, iterator=True, convert_categoricals=False) as header:
            available = set(header.variable_labels())
            # Row count from the header (private in pandas 2.x; best effort for progress only).
            header_rows = getattr(header, "_nobs", None)
            rows_expected = header_rows if isinstance(header_rows, int) and header_rows >= 0 else None
    except Exception as exc:
        raise FkrtlMappingError("The selected FKRTL input could not be opened safely.") from exc
    columns = [column for column in FKRTL_SOURCE_COLUMNS if column in available]
    report: dict[str, Any] = {
        "columns_present": columns,
        "columns_missing": [column for column in FKRTL_SOURCE_COLUMNS if column not in available],
        "required_columns_missing": [column for column in FKRTL_REQUIRED_COLUMNS if column not in available],
    }
    if report["required_columns_missing"]:
        return report
    missing = {column: 0 for column in columns}
    totals = {
        "rows_total": 0, "admission_date_invalid": 0, "discharge_date_invalid": 0,
        "discharge_before_admission": 0, "duplicate_visit_rows": 0, "rows_in_window": 0,
        "duplicate_visit_rows_in_window": 0,
    }
    excluded = {check: Counter() for check in ("repeat_billing_candidate", "near_duplicate_claim_candidate",
                                               "length_of_stay")}
    admission_range: list[str] = []
    window_from, window_to = date_window[0].isoformat(), date_window[1].isoformat()
    # Duplicate visit references are found once at the end over the 32-byte digests of the HMAC
    # case references (about 32 bytes per row in memory), flagging every occurrence after the first
    # in file order. This replaced a scratch SQLite set that took most of the scan time.
    digests = bytearray()
    in_window: list[bool] = []
    try:
        with pd.read_stata(path, iterator=True, chunksize=chunk_size, columns=columns,
                           convert_categoricals=False) as reader:
            for frame in reader:
                # Same missing-value rule as the adapter's _clean, evaluated per column.
                masks = {column: _missing_mask(frame[column]) for column in columns}
                for column, mask in masks.items():
                    missing[column] += int(mask.sum())
                admission_present = ~masks["FKL03"]
                discharge_present = ~masks["FKL04"] if "FKL04" in masks else np.zeros(len(frame), dtype=bool)
                # One adapter call per chunk; repeated visits are mapped and counted, not rejected.
                mapped, _coverage = adapt_fkrtl_rows(
                    frame.to_dict(orient="records"), case_reference_secret=case_reference_secret,
                    reject_duplicate_visits=False,
                )
                for index, record in enumerate(mapped):
                    totals["rows_total"] += 1
                    digests += hashlib.sha256(record["case_id"].encode("utf-8")).digest()
                    admitted, discharged = record["service_date"], record["discharge_date"]
                    totals["admission_date_invalid"] += int(admitted is None and bool(admission_present[index]))
                    totals["discharge_date_invalid"] += int(discharged is None and bool(discharge_present[index]))
                    totals["discharge_before_admission"] += int(bool(admitted and discharged and discharged < admitted))
                    if admitted:
                        admission_range = [min(admission_range[0], admitted), max(admission_range[1], admitted)]                             if admission_range else [admitted, admitted]
                    window_row = bool(admitted and window_from <= admitted <= window_to)
                    in_window.append(window_row)
                    if not window_row:
                        continue
                    totals["rows_in_window"] += 1
                    absent = missing_key_fields(record, repeat_definition)
                    excluded["repeat_billing_candidate"]["missing:" + "+".join(absent) if absent else "eligible"] += 1
                    excluded["near_duplicate_claim_candidate"][prerequisite_reason(record) or "eligible"] += 1
                    excluded["length_of_stay"][row_prerequisite_reason(record) or "eligible"] += 1
                if progress is not None:
                    progress(totals["rows_total"], rows_expected)
        duplicates = later_occurrence_flags(bytes(digests))
        totals["duplicate_visit_rows"] = int(duplicates.sum())
        totals["duplicate_visit_rows_in_window"] = int((duplicates & np.array(in_window, dtype=bool)).sum())
    except FkrtlMappingError:
        raise
    except Exception as exc:
        raise FkrtlMappingError("The selected FKRTL input could not be scanned safely.") from exc
    return {
        **report, **totals,
        "missing_value_counts": missing,
        "admission_date_range": {"from": admission_range[0], "to": admission_range[1]} if admission_range else None,
        "window_eligibility": {
            check: {"eligible": counts.pop("eligible", 0), "excluded": dict(sorted(counts.items()))}
            for check, counts in excluded.items()
        },
    }


def _select_window(frame: pd.DataFrame, date_window: tuple[date, date] | None) -> tuple[pd.DataFrame, dict[str, int]]:
    if date_window is None:
        return frame, {"rows_scanned": len(frame), "excluded_outside_window": 0, "excluded_invalid_date": 0}
    admitted = pd.to_datetime(frame["FKL03"], errors="coerce").dt.normalize()
    start, end = pd.Timestamp(date_window[0]), pd.Timestamp(date_window[1])
    invalid = admitted.isna()
    inside = ~invalid & (admitted >= start) & (admitted <= end)
    return frame[inside], {
        "rows_scanned": len(frame),
        "excluded_outside_window": int((~invalid & ~inside).sum()),
        "excluded_invalid_date": int(invalid.sum()),
    }


def _iter_mapped(
    reader: Any,
    case_reference_secret: bytes,
    scratch_directory: str | Path | None,
    date_window: tuple[date, date] | None,
    max_rows: int | None,
    secondary_lookup: Mapping[str, Sequence[str]] | None = None,
) -> Iterator[tuple[list[dict[str, Any]], dict[str, Any]]]:
    # Keep only a second digest of the already-pseudonymous case reference
    # in scratch SQLite. Memory use is bounded by the current chunk, while
    # no source participant/visit identifiers enter temporary storage.
    with tempfile.TemporaryDirectory(
        prefix="cir_fkrtl_seen_",
        dir=str(scratch_directory) if scratch_directory is not None else None,
    ) as scratch:
        connection = sqlite3.connect(Path(scratch) / "case-digests.sqlite3")
        try:
            connection.execute(
                "CREATE TABLE seen_case_digest (digest TEXT PRIMARY KEY) WITHOUT ROWID"
            )
            selected_total = 0
            for frame in reader:
                frame, selection = _select_window(frame, date_window)
                selected_total += len(frame)
                if max_rows is not None and selected_total > max_rows:
                    # Keep counting so the error reports the full selection size.
                    continue
                mapped, coverage = adapt_fkrtl_rows(
                    frame.to_dict(orient="records"),
                    case_reference_secret=case_reference_secret,
                    secondary_lookup=secondary_lookup,
                )
                digests = [
                    hashlib.sha256(row["case_id"].encode("utf-8")).hexdigest()
                    for row in mapped
                ]
                try:
                    connection.executemany(
                        "INSERT INTO seen_case_digest(digest) VALUES (?)",
                        ((digest,) for digest in digests),
                    )
                except sqlite3.IntegrityError:
                    raise FkrtlMappingError(
                        "Duplicate visit references occur across input chunks."
                    ) from None
                connection.commit()
                yield mapped, {**coverage, **selection}
            if max_rows is not None and selected_total > max_rows:
                raise FkrtlWindowExceedsCap(selected_total, max_rows)
        finally:
            connection.close()


def load_secondary_lookup(
    fkrtl_path: str | Path,
    secondary_path: str | Path,
    date_window: tuple[date, date] | None,
    chunk_size: int = 200_000,
) -> dict[str, list[str]]:
    """Secondary diagnoses (FKL24) per visit number for the visits admitted in the window (memory only).

    First the visit numbers of the window are read (FKL02 and FKL03 only), then the secondary-diagnosis file
    is streamed and only those visits are kept. Visits without any secondary diagnosis are absent (an empty
    list for the caller). Visit numbers never leave this process.
    """
    visits: set[str] = set()
    try:
        with pd.read_stata(fkrtl_path, iterator=True, chunksize=chunk_size, columns=["FKL02", "FKL03"],
                           convert_categoricals=False) as reader:
            for frame in reader:
                frame, _selection = _select_window(frame, date_window)
                visits.update(value for value in map(_clean, frame["FKL02"]) if value)
        lookup: dict[str, list[str]] = {}
        with pd.read_stata(secondary_path, iterator=True, chunksize=chunk_size, columns=["FKL02", "FKL24"],
                           convert_categoricals=False) as reader:
            for frame in reader:
                for visit, code in zip(map(_clean, frame["FKL02"]), map(_clean, frame["FKL24"])):
                    if visit in visits and code:
                        lookup.setdefault(visit, []).append(code.upper())
    except Exception as exc:
        raise FkrtlMappingError("The secondary-diagnosis file could not be read safely.") from exc
    return lookup
