"""Explicit local-only FKRTL .dta provider for controlled compatibility tests.

This module is not registered with any API route and requires the caller to
pass a path and a locally managed pseudonym key explicitly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from app.data_sources.bpjs_fkrtl_adapter import FKRTL_MAPPING_VERSION
from app.data_sources.providers import FeatureDataset
from scripts.fkrtl_dta_reader import iter_fkrtl_dta


class LocalFkrtlDtaProvider:
    def __init__(
        self, input_path: str | Path, *, case_reference_secret: bytes,
        source_classification: Literal["synthetic_fixture", "bpjs_sample"],
        chunk_size: int = 50_000,
    ) -> None:
        if source_classification not in {"synthetic_fixture", "bpjs_sample"}:
            raise ValueError("Source classification is invalid.")
        self._input_path = input_path
        self._secret = case_reference_secret
        self._source_classification = source_classification
        self._chunk_size = chunk_size

    def load(self) -> FeatureDataset:
        records: list[dict[str, Any]] = []
        chunk_coverage: list[dict[str, Any]] = []
        for chunk, coverage in iter_fkrtl_dta(
            self._input_path,
            case_reference_secret=self._secret,
            chunk_size=self._chunk_size,
        ):
            records.extend(chunk)
            chunk_coverage.append(coverage)
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
                "source_schema_profile": "bpjs-fkrtl-sample-compatible-v1",
                "mapping_version": FKRTL_MAPPING_VERSION,
                "adapter_coverage": _aggregate_coverage(chunk_coverage),
                "limitations": [
                    "Facility identity, pre-verification claim amount, capacity, evidence inventory, and minute-level time are unavailable.",
                    "Local-only adapter; no public API or runtime source selection is enabled.",
                    "Full detector execution retains canonical features/results in memory; synthetic target-scale timing does not validate source-profile performance.",
                    "The synthetic target-scale near-duplicate search was partial/truncated; candidate absence is not a negative finding.",
                ],
            },
        )


def _aggregate_coverage(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    if not chunks:
        return {"row_count": 0, "invalid_service_date_count": 0}
    return {
        "row_count": sum(int(item.get("row_count", 0)) for item in chunks),
        "invalid_service_date_count": sum(
            int(item.get("invalid_service_date_count", 0)) for item in chunks
        ),
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
