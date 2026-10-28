"""Add per-case rows to runs stored before they existed (derived data; the stored result is unchanged).

    python -m scripts.backfill_run_case_rows [--database PATH] [--dry-run]

With CIR_DATABASE_URL set it works on that PostgreSQL database (``--database`` is ignored).

Reads each terminal run's stored ``result_json`` once and writes the same rows and summary a
new run gets, in one transaction per run. Runs that already have rows, or whose result has no
case map, are skipped. Without the migration those runs stay readable through the snapshot
fallback. Prints counts only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.db import connect_operational, sqlite_script
from app.services.batches import configured_batch_db_path
from app.services.run_results import CASE_ROWS_SCHEMA, has_case_rows, write_case_rows


def backfill(database: Path, dry_run: bool = False) -> dict[str, int]:
    counts = {"runs_with_result": 0, "already_had_rows": 0, "backfilled": 0, "without_case_map": 0}
    connection = connect_operational(database, timeout=20)
    try:
        sqlite_script(connection, CASE_ROWS_SCHEMA)
        connection.commit()
        run_ids = [row[0] for row in connection.execute(
            "SELECT r.run_id FROM analysis_run_results r JOIN analysis_runs a ON a.run_id=r.run_id "
            "WHERE a.execution_status IN ('completed','partial','failed') ORDER BY a.created_at")]
        for run_id in run_ids:
            counts["runs_with_result"] += 1
            if has_case_rows(connection, run_id):
                counts["already_had_rows"] += 1
                continue
            text = connection.execute("SELECT result_json FROM analysis_run_results WHERE run_id=?", (run_id,)).fetchone()[0]
            stored = json.loads(text) if text is not None else None
            connection.commit()
            if dry_run:
                counts["backfilled" if isinstance(stored, dict) and isinstance(stored.get("cases"), dict)
                       else "without_case_map"] += 1
                continue
            with connection:
                written = write_case_rows(connection, run_id, stored)
            counts["backfilled" if written else "without_case_map"] += 1
    finally:
        connection.close()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(backfill(args.database or configured_batch_db_path(), args.dry_run)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
