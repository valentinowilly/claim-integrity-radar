"""Train the FKRTL anomaly model offline and write the versioned artifact.

Run from ``backend/`` with BPJS_FKRTL_SAMPLE_PATH and CIR_FKRTL_PSEUDONYM_KEY set
in the environment (the same configuration an AnalysisRun uses):

    python -m scripts.train_ml_model --date-from 2024-02-05 --date-to 2024-03-03

The training window is read through the same reader and adapter as a run. The
window must end before any window the model is evaluated or demonstrated on.
Prints counts only: no rows, identifiers, codes or paths.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import os
from pathlib import Path
import time
import tracemalloc

from app.analytics.ml_model import DEFAULT_MODEL_DIR, TrainingConfig, save_artifact, train_model
from app.data_sources.fkrtl_local_source import (
    DATE_FROM_VARIABLE, DATE_TO_VARIABLE, MAX_ROWS_VARIABLE, FkrtlSourceUnavailable, load_fkrtl_local_source,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date-from", required=True, type=date.fromisoformat)
    parser.add_argument("--date-to", required=True, type=date.fromisoformat)
    parser.add_argument("--max-rows", type=int, default=200_000)
    parser.add_argument("--output", type=Path, default=DEFAULT_MODEL_DIR)
    args = parser.parse_args()
    os.environ[DATE_FROM_VARIABLE] = args.date_from.isoformat()
    os.environ[DATE_TO_VARIABLE] = args.date_to.isoformat()
    os.environ[MAX_ROWS_VARIABLE] = str(args.max_rows)

    tracemalloc.start()
    started = time.perf_counter()
    try:
        loaded = load_fkrtl_local_source()
    except FkrtlSourceUnavailable as exc:
        print(f"error {exc.code}")
        return 1
    read_seconds = time.perf_counter() - started
    classification = loaded.dataset.source_metadata.get("classification")
    trained = train_model(loaded.dataset.records, TrainingConfig())
    fit_seconds = time.perf_counter() - started - read_seconds
    manifest = save_artifact(trained, args.output, {
        "source_classification": classification,
        "date_from": args.date_from.isoformat(),
        "date_to": args.date_to.isoformat(),
        "trained_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "command": "python -m scripts.train_ml_model --date-from "
                   f"{args.date_from.isoformat()} --date-to {args.date_to.isoformat()} --max-rows {args.max_rows}",
    })
    peak_mb = tracemalloc.get_traced_memory()[1] / 1e6
    print(f"classification={classification} rows_seen={trained['rows_seen']} rows_eligible={trained['rows_eligible']}")
    print(f"not_eligible={trained['not_eligible_reasons']}")
    print(f"read_seconds={read_seconds:.1f} fit_seconds={fit_seconds:.1f} peak_traced_mb={peak_mb:.0f}")
    print(f"model_version={manifest['model_version']} checksum={manifest['files']['model.joblib'][:12]}")
    sizes = {path.name: path.stat().st_size for path in args.output.iterdir()}
    print(f"artifact_bytes={sizes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
