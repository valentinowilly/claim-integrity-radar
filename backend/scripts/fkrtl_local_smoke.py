"""Aggregate-only smoke test of the configured local FKRTL source.

Run manually from ``backend/`` after setting BPJS_FKRTL_SAMPLE_PATH,
CIR_FKRTL_PSEUDONYM_KEY, BPJS_FKRTL_DATE_FROM/BPJS_FKRTL_DATE_TO (inclusive
admission dates) and optionally BPJS_FKRTL_MAX_ROWS (cap; never truncates). It executes the same
reader and analytics pipeline as an AnalysisRun but persists nothing and prints
counts only: no rows, identifiers, case references, codes, or paths.
"""

from __future__ import annotations

import time

from app.data_sources.fkrtl_local_source import FkrtlSourceUnavailable, fkrtl_source_status, load_fkrtl_local_source
from app.services.provider_orchestrator import execute_provider_snapshot


def main() -> int:
    status = fkrtl_source_status()
    print(f"available={status['available']} max_rows={status['max_rows']}")
    for issue in status["issues"]:
        print(f"issue {issue['code']}: {issue['message']}")
    if not status["available"]:
        return 1
    started = time.perf_counter()
    try:
        loaded = load_fkrtl_local_source()
    except FkrtlSourceUnavailable as exc:
        print(f"error {exc.code}: {exc.message}")
        return 1
    read_seconds = time.perf_counter() - started

    class _Loaded:
        def load(self):
            return loaded.dataset

    _, snapshot = execute_provider_snapshot(_Loaded())
    total_seconds = time.perf_counter() - started
    selection = loaded.selection
    print(
        f"window={selection.get('date_from')}..{selection.get('date_to')} (inclusive) "
        f"rows_scanned={selection.get('rows_scanned')} processed={selection.get('processed_rows')} "
        f"excluded_outside_window={selection.get('excluded_outside_window')} "
        f"excluded_invalid_date={selection.get('excluded_invalid_date')} row_cap={selection.get('row_cap')}"
    )
    print(f"rows_read={loaded.row_count} invalid_service_dates={loaded.invalid_service_date_count}")
    print(f"read_seconds={read_seconds:.1f} total_seconds={total_seconds:.1f}")
    print(f"execution_status={snapshot['execution_status']} signaled_cases={len(snapshot['cases'])}")
    for item in snapshot["indicators"]:
        print(
            f"{item['code']}: status={item['status']} candidates={item['candidate_count']} "
            f"groups={item['candidate_group_count']} assessed={item['eligible_count']} "
            f"not_applicable={item['not_applicable_count']} unassessed={item['unassessed_count']} "
            f"truncated={item['search_truncated']}"
        )
    print(f"audit_priority_status={snapshot['audit_priority']['status']}")
    ml = snapshot["ml_anomaly"]
    print(f"ml_anomaly_status={ml['status']} records_scored={ml['records_scored']} "
          f"ranked_items_stored={len(ml['items'])} explained_items="
          f"{sum(1 for item in ml['items'] if item.get('top_deviations'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
