"""Explicit providers of canonical feature records for the analytics service.

The public API continues to select the synthetic provider/batch path only.
Restricted local sources must be constructed explicitly by an authorized
local caller; they are never selected from request parameters.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from app.analytics.batch_adapter import adapt_batch_features
from app.data_sources.synthetic import get_synthetic_records


CANONICAL_FEATURE_CONTRACT_VERSION = "canonical-analytic-features-v1"
CANONICAL_FEATURE_FIELDS = (
    "case_id", "participant_token", "service_date", "discharge_date",
    "service_timestamp", "facility_id", "service_type", "service_units",
    "facility_daily_capacity", "facility_daily_claim_count", "billed_amount",
    "province_code", "municipality_code", "facility_ownership", "facility_type",
    "facility_class", "admission_diagnosis", "primary_diagnosis", "claim_group",
    "procedure_code", "supporting_evidence_required", "supporting_evidence_types",
    "supporting_evidence_present", "supporting_evidence_recording_status",
)
_CANONICAL_FIELD_SET = frozenset(CANONICAL_FEATURE_FIELDS)
_FORBIDDEN_LABEL_FIELDS = frozenset({
    "is_anomaly", "is_synthetic_anomaly", "scenario", "scenario_label",
    "scenario_labels", "scenario_group_id", "scenario_code", "primary_scenario",
    "ground_truth", "intensity_level", "injected_signals", "claim_labels", "group_labels",
})


class CanonicalFeatureError(ValueError):
    """Safe error for provider records that violate the canonical feature contract."""


@dataclass(frozen=True)
class FeatureDataset:
    records: Sequence[Mapping[str, Any]]
    facilities: Sequence[Mapping[str, Any]]
    source_metadata: Mapping[str, Any]


class FeatureSourceProvider(Protocol):
    def load(self) -> FeatureDataset: ...


def canonicalize_feature_dataset(dataset: FeatureDataset) -> FeatureDataset:
    """Project provider output onto canonical feature names and reject leakage.

    Missing detector prerequisites remain ``None`` and are handled by detector
    coverage. Source-specific column names and ground-truth labels are rejected.
    """
    projected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in dataset.records:
        if not isinstance(row, Mapping):
            raise CanonicalFeatureError("Provider returned an invalid feature record.")
        keys = {str(key) for key in row}
        if keys.intersection(_FORBIDDEN_LABEL_FIELDS):
            raise CanonicalFeatureError("Ground-truth fields are not valid detector features.")
        unsupported = keys - _CANONICAL_FIELD_SET - {"claim_id"}
        if unsupported:
            raise CanonicalFeatureError("Provider record contains fields outside the canonical feature contract.")
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
            raise CanonicalFeatureError("Provider case references must be valid and unique.")
        participant_token = row.get("participant_token")
        if participant_token is not None and not isinstance(participant_token, str):
            raise CanonicalFeatureError("Internal participant comparison token has an invalid type.")
        seen.add(case_id)
        if keys == _CANONICAL_FIELD_SET:
            # Providers such as the FKRTL mapper already emit an exact canonical
            # shape. Reuse their freshly-owned, read-only-by-contract mapping to
            # avoid doubling memory for large datasets.
            projected.append(row)
        else:
            projected.append({field: deepcopy(row.get(field)) for field in CANONICAL_FEATURE_FIELDS})
    return FeatureDataset(
        records=projected,
        facilities=deepcopy(list(dataset.facilities)),
        source_metadata=deepcopy(dict(dataset.source_metadata)),
    )


def load_feature_dataset(provider: FeatureSourceProvider) -> FeatureDataset:
    return canonicalize_feature_dataset(provider.load())


class SyntheticDemoProvider:
    """Current runtime default, returning the existing deterministic fixture."""

    def load(self) -> FeatureDataset:
        return FeatureDataset(
            records=get_synthetic_records(), facilities=(),
            source_metadata={"kind": "synthetic", "label": "synthetic_demo"},
        )


@dataclass(frozen=True)
class SyntheticBatchProvider:
    """Validated normalized records from an immutable synthetic CSV batch."""

    batch: Mapping[str, Any]
    normalized_records: Sequence[Mapping[str, Any]]

    def load(self) -> FeatureDataset:
        features, facilities = adapt_batch_features(self.batch, self.normalized_records)
        return FeatureDataset(
            records=features,
            facilities=facilities,
            source_metadata={
                "kind": "synthetic",
                "label": "synthetic_data_batch",
                # This records the importer's required declaration. It is not
                # independent proof that uploaded content is synthetic.
                "classification": "synthetic_only_declared",
                "source_schema_profile": self.batch.get("schema_version"),
                "mapping_version": self.batch.get("mapping_version"),
                "limitations": [
                    "Klasifikasi synthetic_only berasal dari deklarasi saat impor; isi file tidak diverifikasi sebagai sintetis secara independen."
                ],
            },
        )
