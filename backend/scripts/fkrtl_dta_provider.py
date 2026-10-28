"""Explicit local-only FKRTL .dta provider.

Callers pass a path and a locally managed pseudonym key explicitly. The API
reaches it only through ``app.data_sources.fkrtl_local_source``, which reads
the path from server-side configuration; request input never selects a path.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

from app.data_sources.bpjs_fkrtl_adapter import FKRTL_MAPPING_VERSION
from app.data_sources.providers import FeatureDataset
from scripts.fkrtl_dta_reader import iter_fkrtl_dta, load_secondary_lookup


FKRTL_SCHEMA_PROFILE = "bpjs-fkrtl-sample-compatible-v1"
# Primary repeat definition repeat_service_v1 (see repeat_billing.py); the
# facility-category/region fields and admission diagnosis are reviewer context.
FKRTL_REPEAT_SIGNATURE_PROFILE = "repeat-service-v1"
# Checks whose required fields this source does not provide (verified against
# the data dictionary); reported as not applicable rather than incomplete.
FKRTL_NOT_APPLICABLE_DETECTORS = {
    "similar_claim_pattern_candidate": "signature requires a verified pre-verification claim amount; the provider-billed amount is unconfirmed and the post-verification amount is excluded",
    "synthetic_capacity_candidate": "no verified facility identifier, service units, or facility capacity",
    "temporal_pattern_candidate": "no verified facility identifier, service type, or service timestamp",
    "supporting_evidence_completeness_candidate": "no supporting-evidence inventory or recording status",
}


class LocalFkrtlDtaProvider:
    def __init__(
        self, input_path: str | Path, *, case_reference_secret: bytes,
        source_classification: Literal["synthetic_fixture", "bpjs_sample"],
        chunk_size: int = 50_000,
        date_window: tuple[date, date] | None = None,
        max_rows: int | None = None,
        secondary_path: str | Path | None = None,
    ) -> None:
        if source_classification not in {"synthetic_fixture", "bpjs_sample"}:
            raise ValueError("Source classification is invalid.")
        self._input_path = input_path
        self._secret = case_reference_secret
        self._source_classification = source_classification
        self._chunk_size = chunk_size
        self._date_window = date_window
        self._max_rows = max_rows
        self._secondary_path = secondary_path

    def load(self) -> FeatureDataset:
        records: list[dict[str, Any]] = []
        chunk_coverage: list[dict[str, Any]] = []
        secondary = (load_secondary_lookup(self._input_path, self._secondary_path, self._date_window)
                     if self._secondary_path is not None else None)
        for chunk, coverage in iter_fkrtl_dta(
            self._input_path,
            case_reference_secret=self._secret,
            chunk_size=self._chunk_size,
            date_window=self._date_window,
            max_rows=self._max_rows,
            secondary_lookup=secondary,
        ):
            records.extend(chunk)
            chunk_coverage.append(coverage)
        limitations = [
            "Facility identity, pre-verification claim amount, capacity, evidence inventory, and minute-level time are unavailable.",
            "Repeat-visit signals (repeat_service_v1) compare same-participant visits on admission date, primary diagnosis, INA-CBG and procedure without any amount; a blank procedure (FKL30) leaves the visit unassessed. Region, facility-category and admission-diagnosis differences are shown as context only. The provider-billed amount semantics are unconfirmed and the post-verification amount column is never read.",
            "No confirmed fraud labels exist in the sample; signals are review prompts, not findings, and no accuracy is claimed.",
            "Full detector execution retains canonical features/results in memory; synthetic target-scale timing does not validate source-profile performance.",
            "The synthetic target-scale near-duplicate search was partial/truncated; candidate absence is not a negative finding.",
        ]
        if self._date_window is not None:
            limitations[:0] = [
                f"Only claims admitted {self._date_window[0].isoformat()} to {self._date_window[1].isoformat()} "
                "(inclusive) were analysed; results do not represent the whole FKRTL sample.",
                "Repeat and near-duplicate checks compare claims with the same admission date, so pairs inside the "
                "window are fully in scope; ML frequency and visits-per-participant features describe this window only.",
            ]
        return FeatureDataset(
            records=records,
            facilities=(),
            source_metadata={
                "kind": "synthetic" if self._source_classification == "synthetic_fixture" else "local",
                "label": (
                    "synthetic_fkrtl_fixture"
                    if self._source_classification == "synthetic_fixture" else "bpjs_sample"
                ),
                "classification": self._source_classification,
                "source_schema_profile": FKRTL_SCHEMA_PROFILE,
                "mapping_version": FKRTL_MAPPING_VERSION,
                "repeat_signature_profile": FKRTL_REPEAT_SIGNATURE_PROFILE,
                "not_applicable_detectors": dict(FKRTL_NOT_APPLICABLE_DETECTORS),
                "selection": _selection(chunk_coverage, self._date_window, self._max_rows),
                "adapter_coverage": _aggregate_coverage(chunk_coverage),
                "limitations": limitations,
                "category_labels": _category_labels(self._input_path),
                "secondary_diagnoses": "linked" if secondary is not None else "not_configured",
            },
        )


_LABELLED_COLUMNS = {"FKL05": "province_code", "FKL06": "municipality_code", "FKL07": "facility_ownership",
                     "FKL08": "facility_type", "FKL09": "facility_class"}


def _category_labels(path: str | Path) -> dict[str, dict[str, str]]:
    """Official names of the facility category codes from the file's own value labels (dictionary, no rows)."""
    try:
        import pandas as pd

        with pd.io.stata.StataReader(path) as reader:
            value_labels = reader.value_labels()
            label_sets = dict(zip(reader._varlist, reader._lbllist))
    except Exception:
        return {}
    return {field: {str(int(code)): str(name) for code, name in value_labels.get(label_sets.get(column) or "", {}).items()}
            for column, field in _LABELLED_COLUMNS.items()}


def _selection(chunks: list[dict[str, Any]], date_window: tuple[date, date] | None,
               max_rows: int | None) -> dict[str, Any]:
    """Aggregate, non-identifying description of which rows were analysed."""
    processed = sum(int(item.get("row_count", 0)) for item in chunks)
    return {
        "strategy": "admission_date_window" if date_window is not None else "all_rows",
        "date_from": date_window[0].isoformat() if date_window else None,
        "date_to": date_window[1].isoformat() if date_window else None,
        "bounds_inclusive": True,
        "date_field": "FKL03",
        "rows_scanned": sum(int(item.get("rows_scanned", 0)) for item in chunks),
        "eligible_rows": processed,
        "processed_rows": processed,
        "excluded_outside_window": sum(int(item.get("excluded_outside_window", 0)) for item in chunks),
        "excluded_invalid_date": sum(int(item.get("excluded_invalid_date", 0)) for item in chunks),
        "row_cap": max_rows,
    }


def _aggregate_coverage(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    if not chunks:
        return {"row_count": 0, "invalid_service_date_count": 0}
    return {
        "row_count": sum(int(item.get("row_count", 0)) for item in chunks),
        "invalid_service_date_count": sum(
            int(item.get("invalid_service_date_count", 0)) for item in chunks
        ),
        "invalid_discharge_date_count": sum(int(item.get("invalid_discharge_date_count", 0)) for item in chunks),
        "invalid_provider_amount_count": sum(int(item.get("invalid_provider_amount_count", 0)) for item in chunks),
        "field_non_missing_counts": {
            field: sum(int(item.get("field_non_missing_counts", {}).get(field, 0)) for item in chunks)
            for field in sorted({field for item in chunks for field in item.get("field_non_missing_counts", {})})
        },
        "missing_source_columns": sorted({
            column for item in chunks
            for column in item.get("missing_source_columns", [])
        }),
        "facility_identity": "unavailable",
        "billed_amount": "withheld_pending_FKL47_semantics_confirmation",
        "capacity": "unavailable",
        "evidence_inventory": "unavailable",
        "minute_level_time": "unavailable",
        "ground_truth": "not_present",
    }
