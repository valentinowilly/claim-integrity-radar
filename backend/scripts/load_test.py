"""Measured load test: how long one analysis of N claims takes on this machine, and how much memory it needs.

The demo-3 claims (29,628 synthetic claims of one month, 40 hospitals) are repeated in copies until N claims are
reached. Each copy gets new participants, visit numbers and a later period, and its notes are marked with the copy
number so that copies are not mistaken for cloned notes. The patterns per copy stay the same as demo-3, so the
risk lanes scale with the copies; that is checked, not assumed.

Stages are timed separately: building the file, the validated import (checks every row and stores the batch), and
the analysis (12 checks, the claim-pattern AI, lanes, facility groups). Peak memory is the process working set,
sampled every 0.2 s. Everything runs on a temporary SQLite database that is deleted afterwards.

    python -m scripts.load_test --claims 120000 --claims 450000 --out report.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import platform
import tempfile
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import psutil

from app.data_sources.bpjs_csv import BPJS_CSV_MAPPING_VERSION, BPJS_CSV_SCHEMA_VERSION
from app.services.batches import BatchStore
from app.services.runs import create_analysis_run

SOURCE = Path(__file__).resolve().parents[2] / "demo-data" / "demo-3-operasional.csv"
DATE_COLUMNS = ("FKL03", "FKL04")


class PeakMemory:
    def __init__(self) -> None:
        self.process = psutil.Process()
        self.peak = self.process.memory_info().rss
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, self.process.memory_info().rss)
            time.sleep(0.2)

    def __enter__(self) -> "PeakMemory":
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join()


def build_csv(target: int) -> tuple[bytes, int]:
    rows = list(csv.DictReader(SOURCE.open(encoding="utf-8")))
    header = list(rows[0].keys())
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=header, lineterminator="\n")
    writer.writeheader()
    written = 0
    copy = 0
    while written < target:
        shift = timedelta(days=35 * copy)
        for row in rows:
            if written >= target:
                break
            new = dict(row)
            if copy:
                new["PSTV01"] = f"SYNC{copy:02d}{row['PSTV01'][3:]}"
                new["FKL02"] = f"SYNC{copy:02d}{row['FKL02'][3:]}"
                for column in DATE_COLUMNS:
                    if row.get(column):
                        new[column] = (date.fromisoformat(row[column]) + shift).isoformat()
                if row.get("CATATAN_KLINIS"):
                    new["CATATAN_KLINIS"] = f"{row['CATATAN_KLINIS']} Kunjungan periode {copy + 1}."
                if row.get("ID_FASKES"):
                    new["ID_FASKES"] = f"{row['ID_FASKES']}P{copy:02d}"
            writer.writerow(new)
            written += 1
        copy += 1
    return out.getvalue().encode("utf-8"), copy


def measure(claims: int, folder: Path) -> dict[str, object]:
    db = folder / f"load-{claims}.sqlite3"
    started = time.monotonic()
    raw, copies = build_csv(claims)
    built = time.monotonic()
    with PeakMemory() as memory:
        batch, _ = BatchStore(db).import_csv(raw, batch_key=f"synthetic-load-{claims}", creator_user_id="usr_load",
                                             schema_version=BPJS_CSV_SCHEMA_VERSION,
                                             mapping_version=BPJS_CSV_MAPPING_VERSION, max_rows=claims + 10)
        imported = time.monotonic()
        if batch["status"] == "rejected":
            return {"claims": claims, "status": "rejected", "validation": batch.get("validation")}
        run = create_analysis_run(db, batch["batch_id"], "usr_load")
        analysed = time.monotonic()
    import sqlite3

    connection = sqlite3.connect(db)
    summary = json.loads(connection.execute("SELECT summary_json FROM analysis_run_result_views WHERE run_id=?",
                                            (run["run_id"],)).fetchone()[0])
    connection.close()
    lanes = summary["action_policy"]["lane_counts"]
    return {
        "claims": claims, "copies_of_demo3": copies, "status": run["execution_status"],
        "seconds": {"build_file": round(built - started, 1), "validated_import": round(imported - built, 1),
                    "analysis": round(analysed - imported, 1), "import_and_analysis": round(analysed - built, 1)},
        "claims_per_second": round(claims / (analysed - built), 1),
        "peak_memory_gb": round(memory.peak / 1024 ** 3, 2),
        "database_mb": round(db.stat().st_size / 1024 ** 2, 1),
        "lanes": {key: lanes.get(key, 0) for key in ("red", "yellow", "green")},
        "ml_status": (summary.get("ml_anomaly") or {}).get("status"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--claims", type=int, action="append", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    machine = {"cpu": platform.processor() or platform.machine(), "logical_cpus": os.cpu_count(),
               "memory_gb": round(psutil.virtual_memory().total / 1024 ** 3, 1), "python": platform.python_version(),
               "database": "SQLite (file sementara)"}
    results = []
    with tempfile.TemporaryDirectory(prefix="cir-load-") as folder:
        for claims in args.claims:
            result = measure(claims, Path(folder))
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    report = {"machine": machine, "results": results}
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
