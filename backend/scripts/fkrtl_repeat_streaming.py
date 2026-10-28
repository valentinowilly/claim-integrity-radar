"""Whole-file, two-pass streaming reconciliation of repeat-pattern definitions (aggregate only).

Run locally from ``backend/`` with BPJS_FKRTL_SAMPLE_PATH and CIR_FKRTL_PSEUDONYM_KEY::

    python -m scripts.fkrtl_repeat_streaming

Pass 1 counts an in-process hash of each definition's normalized key without
keeping records. Pass 2 keeps only records whose key hash occurred more than
once and regroups them by the exact key, so hash collisions cannot create
groups. Production definitions are only read, never changed. Output holds
counts only and is written to ``backend/outputs/fkrtl_aggregates/`` (ignored by
Git); identifiers stay in memory and are never written.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
import json
from pathlib import Path
import time
from typing import Any

from app.analytics.repeat_billing import AMOUNT_WITHHELD_SIGNATURE_FIELDS
from app.analytics.repeat_definitions import (
    LEGACY_SCRIPT_REPEAT_SERVICE, MISSING, REPEAT_SERVICE_V1, RepeatDefinition, normalize_value,
)
from scripts.fkrtl_repeat_reconciliation import assert_aggregate_only

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs" / "fkrtl_aggregates"
AMOUNT_FIELD = "provider_billed_amount_unverified"
APP_DETECTOR = RepeatDefinition("app_detector_repeat_visit_exact_no_amount_v1", AMOUNT_WITHHELD_SIGNATURE_FIELDS)
# Impact analysis only: ignores FKL30 entirely. Not a repeat-billing candidate definition.
PARTIAL_WITHOUT_PROCEDURE = RepeatDefinition(
    "impact_partial_without_fkl30",
    tuple(field for field in REPEAT_SERVICE_V1.key_fields if field != "procedure_code"),
)
DEFINITIONS = (REPEAT_SERVICE_V1, APP_DETECTOR, PARTIAL_WITHOUT_PROCEDURE, LEGACY_SCRIPT_REPEAT_SERVICE)
EXTRA_APP_FIELDS = tuple(field for field in APP_DETECTOR.key_fields if field not in REPEAT_SERVICE_V1.key_fields)
EXPLORATORY_AMOUNT_LABEL = "exploratory: FKL47 semantics unverified; equal amounts do not show double payment"


def _key(record: Mapping[str, Any], definition: RepeatDefinition) -> tuple[tuple[Any, ...] | None, list[str]]:
    values = tuple(normalize_value(field, record.get(field)) for field in definition.key_fields)
    missing = [field for field, value in zip(definition.key_fields, values) if value is None]
    if missing and definition.missing_policy == "ineligible":
        return None, missing
    return tuple(MISSING if value is None else value for value in values), missing


def run_streaming_reconciliation(
    chunks: Callable[[], Iterable[Sequence[Mapping[str, Any]]]],
    definitions: Sequence[RepeatDefinition] = DEFINITIONS,
) -> dict[str, Any]:
    """``chunks`` must return a fresh iterator of canonical record chunks on each call."""
    # Pass 1: key-hash counts, eligibility and missing-field counts.
    started = time.perf_counter()
    counts: dict[str, Counter] = {d.name: Counter() for d in definitions}
    not_assessable: dict[str, Counter] = {d.name: Counter() for d in definitions}
    rows_not_assessable: Counter = Counter()
    rows_scanned = 0
    for chunk in chunks():
        for record in chunk:
            rows_scanned += 1
            for definition in definitions:
                key, missing = _key(record, definition)
                if key is None:
                    rows_not_assessable[definition.name] += 1
                    not_assessable[definition.name].update(missing)
                    continue
                counts[definition.name][hash(key)] += 1
    repeated_hashes = {name: {h for h, n in counter.items() if n > 1} for name, counter in counts.items()}
    del counts
    pass1_seconds = time.perf_counter() - started

    # Pass 2: exact keys and in-memory details for records that may belong to a group.
    started = time.perf_counter()
    members: dict[str, dict[tuple[Any, ...], list[dict[str, Any]]]] = {d.name: defaultdict(list) for d in definitions}
    for chunk in chunks():
        for record in chunk:
            for definition in definitions:
                key, _missing = _key(record, definition)
                if key is None or hash(key) not in repeated_hashes[definition.name]:
                    continue
                members[definition.name][key].append({
                    "case": record["case_id"],  # in memory only, for overlap; never written
                    "month": (normalize_value("service_date", record.get("service_date")) or "unknown")[:7],
                    "amount": normalize_value(AMOUNT_FIELD, record.get(AMOUNT_FIELD)),
                    "procedure_missing": normalize_value("procedure_code", record.get("procedure_code")) is None,
                    "extras": tuple(normalize_value(field, record.get(field)) for field in EXTRA_APP_FIELDS),
                })
    pass2_seconds = time.perf_counter() - started

    groups = {name: [group for group in by_key.items() if len(group[1]) > 1] for name, by_key in members.items()}
    report: dict[str, Any] = {
        "report": "fkrtl-repeat-streaming-reconciliation-v1",
        "rows_scanned": rows_scanned,
        "label": "Repeat patterns are review signals, not evidence of double payment or fraud.",
        "definitions": {},
    }
    for definition in definitions:
        report["definitions"][definition.name] = _summarize(
            definition, groups[definition.name], rows_scanned,
            rows_not_assessable[definition.name], not_assessable[definition.name],
        )
    report["overlap"] = _overlap(groups)
    report["timing_seconds"] = {"pass1": round(pass1_seconds, 1), "pass2": round(pass2_seconds, 1)}
    assert_aggregate_only(report)
    return report


def _summarize(definition: RepeatDefinition, groups: list[tuple[tuple[Any, ...], list[dict[str, Any]]]],
               rows_scanned: int, rows_not_assessable: int, missing: Counter) -> dict[str, Any]:
    by_month: dict[str, Counter] = defaultdict(Counter)
    subset = Counter()
    complete_key = blank_procedure = 0
    for key, rows in groups:
        complete_key += int(MISSING not in key)
        blank_procedure += int(any(row["procedure_missing"] for row in rows))
        month = rows[0]["month"]
        by_month[month].update({"groups": 1, "rows_in_groups": len(rows), "extra_rows": len(rows) - 1})
        valid = [row["amount"] for row in rows if row["amount"] is not None]
        subset["rows_in_key_groups_without_valid_amount"] += len(rows) - len(valid)
        subset["key_groups_with_differing_amounts"] += int(len(set(valid)) > 1)
        for count in Counter(valid).values():
            if count >= 2:
                subset.update({"groups": 1, "rows_in_groups": count, "extra_rows": count - 1})
    rows_in_groups = sum(len(rows) for _key, rows in groups)
    return {
        "key_fields": list(definition.key_fields),
        "missing_policy": definition.missing_policy,
        "rows_assessed": rows_scanned - rows_not_assessable,
        "rows_not_assessable": rows_not_assessable,
        "rows_not_assessable_by_missing_field": dict(sorted(missing.items())),
        "groups": len(groups),
        "rows_in_groups": rows_in_groups,
        "extra_rows": rows_in_groups - len(groups),
        "group_size_distribution": dict(sorted(Counter(len(rows) for _key, rows in groups).items())),
        "groups_with_complete_key": complete_key,
        "groups_involving_blank_fkl30": blank_procedure,
        "by_admission_month": {month: dict(values) for month, values in sorted(by_month.items())},
        "same_fkl47_subset_exploratory": {
            "label": EXPLORATORY_AMOUNT_LABEL,
            **{key: subset.get(key, 0) for key in (
                "groups", "rows_in_groups", "extra_rows", "key_groups_with_differing_amounts",
                "rows_in_key_groups_without_valid_amount")},
        },
    }


def _overlap(groups: Mapping[str, list[tuple[tuple[Any, ...], list[dict[str, Any]]]]]) -> dict[str, Any]:
    core = [frozenset(row["case"] for row in rows) for _key, rows in groups[REPEAT_SERVICE_V1.name]]
    app = [frozenset(row["case"] for row in rows) for _key, rows in groups[APP_DETECTOR.name]]
    partial = groups[PARTIAL_WITHOUT_PROCEDURE.name]
    app_rows = frozenset().union(*app) if app else frozenset()
    core_rows = frozenset().union(*core) if core else frozenset()
    # Why a core group is not exactly reproduced by the app detector.
    reasons = Counter()
    for _key, rows in groups[REPEAT_SERVICE_V1.name]:
        cases = frozenset(row["case"] for row in rows)
        if cases in app:
            continue
        for index, field in enumerate(EXTRA_APP_FIELDS):
            values = [row["extras"][index] for row in rows]
            if any(value is None for value in values):
                reasons[f"missing_{field}"] += 1
            elif len(set(values)) > 1:
                reasons[f"differs_on_{field}"] += 1
    partial_sets = [(frozenset(row["case"] for row in rows), any(row["procedure_missing"] for row in rows))
                    for _key, rows in partial]
    return {
        "core_vs_app_detector": {
            "core_groups": len(core),
            "app_groups": len(app),
            "app_groups_inside_a_core_group": sum(1 for group in app if any(group <= other for other in core)),
            "core_groups_identical_to_an_app_group": sum(1 for group in core if group in app),
            "core_groups_partly_covered_by_app_groups": sum(
                1 for group in core if group not in app and any(other <= group for other in app)),
            "core_groups_without_any_app_group": sum(1 for group in core if not any(other <= group for other in app)),
            "rows_in_both": len(core_rows & app_rows),
            "core_rows_not_in_app_groups": len(core_rows - app_rows),
            "core_groups_not_reproduced_by_reason": dict(sorted(reasons.items())),
            "reason_counts_nonexclusive": True,
        },
        "partial_without_fkl30_vs_core": {
            "partial_groups": len(partial_sets),
            "partial_groups_containing_a_core_group": sum(
                1 for group, _blank in partial_sets if any(core_group <= group for core_group in core)),
            "partial_groups_involving_blank_fkl30": sum(1 for _group, blank in partial_sets if blank),
            "partial_groups_with_all_fkl30_present_but_differing": sum(
                1 for group, blank in partial_sets
                if not blank and not any(core_group <= group for core_group in core)),
        },
    }


def main() -> None:
    import os

    from app.data_sources.bpjs_fkrtl_adapter import pseudonym_secret_from_environment
    from scripts.fkrtl_dta_reader import iter_fkrtl_dta

    path = os.environ.get("BPJS_FKRTL_SAMPLE_PATH", "").strip()
    if not path:
        raise SystemExit("Set BPJS_FKRTL_SAMPLE_PATH to the local FKRTL .dta file.")
    secret = pseudonym_secret_from_environment()

    def chunks():
        # Whole file: no date window and no row cap; the reader yields mapped chunks.
        return (records for records, _coverage in iter_fkrtl_dta(path, case_reference_secret=secret, chunk_size=100_000))

    report = run_streaming_reconciliation(chunks)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "repeat_streaming_full_file.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
