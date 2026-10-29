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
    "facility_class", "care_class", "tariff_region", "tariff_group",
    # Unverified FKL47: reconciliation subsets only, never a detector/ML feature.
    "provider_billed_amount_unverified",
    "admission_diagnosis", "primary_diagnosis", "claim_group",
    "procedure_code", "supporting_evidence_required", "supporting_evidence_types",
    "supporting_evidence_present", "supporting_evidence_recording_status",
    # Optional free-text clinical note of an uploaded example file (clone check and the AI reading aid only).
    "clinical_note",
    # Optional BPJS-format details: secondary diagnoses (FKL24) and special top-up codes (FKL33-FKL44).
    "secondary_diagnoses", "special_codes",
)
_CANONICAL_FIELD_SET = frozenset(CANONICAL_FEATURE_FIELDS)
OPTIONAL_FEATURE_FIELDS = frozenset({"clinical_note", "secondary_diagnoses", "special_codes"})
_CANONICAL_REQUIRED = _CANONICAL_FIELD_SET - OPTIONAL_FEATURE_FIELDS
_FORBIDDEN_LABEL_FIELDS = frozenset({
    "is_anomaly", "is_synthetic_anomaly", "scenario", "scenario_label",
    "scenario_labels", "scenario_group_id", "scenario_code", "primary_scenario",
    "ground_truth", "intensity_level", "injected_signals", "claim_labels", "group_labels",
})


class CanonicalFeatureError(ValueError):
    """Safe error for provider records that violate the canonical feature contract."""

# Cross-day checks compare a new file with claims of earlier files admitted up to this many days before it.
LOOKBACK_DAYS = 30


@dataclass(frozen=True)
class FeatureDataset:
    records: Sequence[Mapping[str, Any]]
    facilities: Sequence[Mapping[str, Any]]
    source_metadata: Mapping[str, Any]
    # Claims from earlier files, compared by the cross-day checks only; never analysed or stored as cases.
    earlier_records: Sequence[Mapping[str, Any]] = ()


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
        if _CANONICAL_REQUIRED <= keys:
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
        earlier_records=dataset.earlier_records,
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
    earlier_records: Sequence[Mapping[str, Any]] = ()

    def load(self) -> FeatureDataset:
        from app.data_sources.bpjs_csv import BPJS_CSV_SCHEMA_VERSION

        if self.batch.get("schema_version") == BPJS_CSV_SCHEMA_VERSION:
            return _bpjs_format_dataset(self.batch, self.normalized_records, self.earlier_records)
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


def _bpjs_format_dataset(batch: Mapping[str, Any], records: Sequence[Mapping[str, Any]],
                         earlier: Sequence[Mapping[str, Any]] = ()) -> FeatureDataset:
    """An uploaded file in the BPJS column format: same profile, checks and trained AI as the FKRTL source."""
    from app.analytics.batch_adapter import adapt_bpjs_batch_features
    from app.analytics.ml_model import category_labels
    from app.data_sources.bpjs_csv import BPJS_CSV_MAPPING_VERSION
    from app.data_sources.fkrtl_local_source import FKRTL_SCHEMA_PROFILE
    from scripts.fkrtl_dta_provider import FKRTL_NOT_APPLICABLE_DETECTORS, FKRTL_REPEAT_SIGNATURE_PROFILE

    features = adapt_bpjs_batch_features(batch, records)
    facilities, not_applicable, operational = _operational_inputs(features, FKRTL_NOT_APPLICABLE_DETECTORS)
    dates = sorted(record["service_date"] for record in features)
    current = {record["case_id"] for record in features}
    earlier = [dict(record) for record in earlier if record.get("case_id") not in current]
    return FeatureDataset(
        earlier_records=earlier,
        records=features,
        facilities=facilities,
        source_metadata={
            "kind": "synthetic",
            "label": "synthetic_data_batch",
            "classification": "synthetic_only_declared",
            "source_schema_profile": FKRTL_SCHEMA_PROFILE,
            "mapping_version": BPJS_CSV_MAPPING_VERSION,
            "repeat_signature_profile": FKRTL_REPEAT_SIGNATURE_PROFILE,
            "not_applicable_detectors": not_applicable,
            "selection": {"strategy": "uploaded_file", "date_from": dates[0], "date_to": dates[-1],
                          "date_field": "FKL03", "processed_rows": len(features),
                          "earlier_claims_compared": len(earlier), "lookback_days": LOOKBACK_DAYS},
            "category_labels": category_labels(),
            "limitations": [
                "Berkas unggahan berformat kolom data klaim FKRTL; nomor peserta anonim (berawalan SYN).",
                *([OPERATIONAL_NOTE] if operational else []),
            ],
        },
    )


# Detector -> fields it needs from the optional operational columns of an upload.
OPERATIONAL_DETECTOR_FIELDS = {
    "synthetic_capacity_candidate": ("facility_id", "facility_daily_capacity", "service_type", "service_units"),
    "temporal_pattern_candidate": ("facility_id", "service_type", "service_timestamp"),
    "supporting_evidence_completeness_candidate": ("service_type", "supporting_evidence_recording_status"),
}
OPERATIONAL_NOTE = ("Kolom tambahan kapasitas faskes, jenis/jumlah/jam layanan, dan bukti pendukung bukan bagian data sampel BPJS; "
                    "pada berkas contoh nilainya sintetis, di produksi diambil dari data faskes dan rekam medis elektronik.")


def _operational_inputs(features: Sequence[Mapping[str, Any]], declared: Mapping[str, str]
                        ) -> tuple[list[dict[str, Any]], dict[str, str], bool]:
    """Facility capacities and the detectors that apply, from the operational columns the file carries."""
    not_applicable = dict(declared)
    used = False
    for detector, fields in OPERATIONAL_DETECTOR_FIELDS.items():
        if any(all(record.get(field) is not None for field in fields) for record in features):
            not_applicable.pop(detector, None)
            used = True
    capacities: dict[str, int] = {}
    for record in features:
        if record.get("facility_id") is not None and record.get("facility_daily_capacity") is not None:
            capacities.setdefault(record["facility_id"], record["facility_daily_capacity"])
    facilities = [{"facility_id": key, "daily_capacity_units": capacities[key]} for key in sorted(capacities)]
    return facilities, not_applicable, used
