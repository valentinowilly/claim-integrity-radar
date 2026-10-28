"""Aggregate-only FKRTL adapter check and repeat-pattern reconciliation.

Run locally from ``backend/`` with the same configuration as the app
(BPJS_FKRTL_SAMPLE_PATH, CIR_FKRTL_PSEUDONYM_KEY, BPJS_FKRTL_DATE_FROM/TO,
optional BPJS_FKRTL_MAX_ROWS)::

    python -m scripts.fkrtl_repeat_reconciliation

Output: counts only (no identifiers, case references, key values or rows),
printed and written to ``backend/outputs/fkrtl_aggregates/`` (ignored by Git).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import time
from typing import Any, Mapping, Sequence

from app.analytics.repeat_billing import AMOUNT_WITHHELD_SIGNATURE_FIELDS
from app.analytics.repeat_definitions import (
    LEGACY_SCRIPT_REPEAT_SERVICE, REPEAT_SERVICE_V1, RepeatDefinition, summarize_repeat_patterns,
)

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs" / "fkrtl_aggregates"
DETECTOR_PROFILE = RepeatDefinition("repeat-visit-exact-no-amount-v1", AMOUNT_WITHHELD_SIGNATURE_FIELDS)
_IDENTIFIER_PATTERN = re.compile(r"(case_|participant_)[0-9a-f]{8,}")


class SensitiveOutputError(ValueError):
    """The report would contain an identifier-like value."""


def assert_aggregate_only(report: Any, forbidden_values: Sequence[str] = ()) -> None:
    """Reject identifier-shaped strings and any explicitly forbidden raw value."""
    text = json.dumps(report, sort_keys=True, default=str)
    if _IDENTIFIER_PATTERN.search(text):
        raise SensitiveOutputError("Report contains an identifier-like value.")
    if any(value and value in text for value in forbidden_values):
        raise SensitiveOutputError("Report contains a forbidden raw value.")


def build_repeat_reconciliation(records: Sequence[Mapping[str, Any]], *, adapter_coverage: Mapping[str, Any],
                                selection: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Aggregate counts for the three repeat definitions on the same records."""
    started = time.perf_counter()
    definitions = {
        "repeat_service_v1": summarize_repeat_patterns(records, REPEAT_SERVICE_V1),
        "legacy_script_repeat_service": summarize_repeat_patterns(records, LEGACY_SCRIPT_REPEAT_SERVICE),
        "detector_profile_repeat_visit_exact_no_amount_v1": summarize_repeat_patterns(records, DETECTOR_PROFILE),
    }
    report = {
        "report": "fkrtl-repeat-reconciliation-v1",
        "selection": dict(selection or {}),
        "validation": {
            "status": "passed" if not adapter_coverage.get("missing_source_columns") else "passed_with_missing_optional_columns",
            "rows_accepted": adapter_coverage.get("row_count"),
            "missing_source_columns": adapter_coverage.get("missing_source_columns", []),
            "invalid_service_date_count": adapter_coverage.get("invalid_service_date_count"),
            "invalid_discharge_date_count": adapter_coverage.get("invalid_discharge_date_count"),
            "invalid_provider_amount_count": adapter_coverage.get("invalid_provider_amount_count"),
        },
        "field_non_missing_counts": dict(adapter_coverage.get("field_non_missing_counts", {})),
        "repeat_definitions": definitions,
        "reconciliation_note": (
            "The legacy script matched missing values as a literal value and counted missing FKL47 as 0; "
            "repeat_service_v1 makes such records ineligible. The same-amount subset is part of its key groups, "
            "not a separate pattern; equal amounts do not show a claim was paid twice."
        ),
        "repeat_seconds": round(time.perf_counter() - started, 3),
    }
    assert_aggregate_only(report)
    return report


def main() -> None:
    from app.data_sources.fkrtl_local_source import load_fkrtl_local_source

    started = time.perf_counter()
    loaded = load_fkrtl_local_source()
    read_seconds = time.perf_counter() - started
    report = build_repeat_reconciliation(
        loaded.dataset.records,
        adapter_coverage=loaded.dataset.source_metadata.get("adapter_coverage", {}),
        selection=loaded.selection,
    )
    report["read_seconds"] = round(read_seconds, 1)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "repeat_reconciliation.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
