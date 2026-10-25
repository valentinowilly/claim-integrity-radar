"""Opt-in local .dta chunk reader; do not invoke without approved data use."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import hashlib
import sqlite3
import tempfile
from typing import Any

import pandas as pd

from app.data_sources.bpjs_fkrtl_adapter import (
    FKRTL_SOURCE_COLUMNS,
    FkrtlMappingError,
    adapt_fkrtl_rows,
)


def iter_fkrtl_dta(
    input_path: str | Path,
    *,
    case_reference_secret: bytes,
    chunk_size: int = 50_000,
    scratch_directory: str | Path | None = None,
) -> Iterator[tuple[list[dict[str, Any]], dict[str, Any]]]:
    """Yield canonicalized chunks; source identifiers are not returned.

    Only allow-listed fields are read. FKL47/48 are intentionally excluded.
    Errors avoid echoing input paths or row values.
    """
    path = Path(input_path)
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    if not path.is_file():
        raise FkrtlMappingError("Input file is unavailable.")
    try:
        reader = pd.read_stata(
            path,
            iterator=True,
            chunksize=chunk_size,
            columns=list(FKRTL_SOURCE_COLUMNS),
            convert_categoricals=False,
        )
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
                for frame in reader:
                    mapped, coverage = adapt_fkrtl_rows(
                        frame.to_dict(orient="records"),
                        case_reference_secret=case_reference_secret,
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
                    yield mapped, coverage
            finally:
                connection.close()
    except FkrtlMappingError:
        raise
    except Exception as exc:
        raise FkrtlMappingError("The selected FKRTL input could not be mapped safely.") from exc
