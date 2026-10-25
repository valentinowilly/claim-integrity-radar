"""Coordinate the active synthetic source, six detectors, scoring, and priority."""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from app.analytics.audit_priority import build_audit_priority_queue
from app.analytics.capacity import LIMITATIONS as CAPACITY_LIMITATIONS
from app.analytics.evidence_completeness import LIMITATIONS as EVIDENCE_LIMITATIONS
from app.analytics.near_duplicate_claims import LIMITATIONS as NEAR_LIMITATIONS
from app.analytics.repeat_billing import LIMITATIONS as REPEAT_LIMITATIONS
from app.analytics.risk_scoring import DETECTOR_ORDER, run_detector_suite, score_claims
from app.analytics.similar_claim_pattern import LIMITATIONS as SIMILAR_LIMITATIONS
from app.analytics.temporal_patterns import LIMITATIONS as TEMPORAL_LIMITATIONS
from app.data_sources.providers import (
    FeatureDataset, FeatureSourceProvider, SyntheticDemoProvider, load_feature_dataset,
)


DATA_SOURCE = {"kind": "synthetic", "label": "synthetic_demo"}
INDICATOR_DEFINITIONS = (
    {
        "code": "repeat_billing_candidate",
        "name": "Repeat billing candidate",
        "definition": "Exact match signature klaim lengkap untuk peserta sintetis yang sama.",
        "limitations": REPEAT_LIMITATIONS,
    },
    {
        "code": "similar_claim_pattern_candidate",
        "name": "Similar claim-pattern candidate",
        "definition": "Exact match pola klaim pada peserta sintetis berbeda.",
        "limitations": SIMILAR_LIMITATIONS,
    },
    {
        "code": "near_duplicate_claim_candidate",
        "name": "Near-duplicate claim candidate",
        "definition": "Blocking deterministik dan perbandingan atribut berbatas untuk menemukan pasangan klaim yang sangat serupa.",
        "limitations": NEAR_LIMITATIONS,
    },
    {
        "code": "synthetic_capacity_candidate",
        "name": "Synthetic service capacity candidate",
        "definition": "Membandingkan unit layanan per fasilitas, jenis layanan, dan hari dengan metadata kapasitas sintetis.",
        "limitations": CAPACITY_LIMITATIONS,
    },
    {
        "code": "temporal_pattern_candidate",
        "name": "Temporal pattern candidate",
        "definition": "Mencari pengulangan jangka pendek dan waktu layanan sintetis yang seragam.",
        "limitations": TEMPORAL_LIMITATIONS,
    },
    {
        "code": "supporting_evidence_completeness_candidate",
        "name": "Supporting evidence completeness candidate",
        "definition": "Memeriksa inventaris bukti sintetis terhadap aturan layanan yang dikonfigurasi.",
        "limitations": EVIDENCE_LIMITATIONS,
    },
)
INDICATOR_BY_CODE = {item["code"]: item for item in INDICATOR_DEFINITIONS}
PLANNED_INDICATORS = [
    {
        "code": "billing_amount_anomaly",
        "name": "Billing amount anomaly",
        "status": "planned",
        "definition": "Belum diimplementasikan; memerlukan populasi pembanding dan validasi ahli.",
    },
    {
        "code": "claim_data_quality",
        "name": "Claim data quality",
        "status": "planned",
        "definition": "Belum diimplementasikan; aturan kelengkapan sumber belum ditetapkan.",
    },
    {
        "code": "code_combination_validity",
        "name": "Code combination validity",
        "status": "planned",
        "definition": "Belum diimplementasikan; memerlukan aturan klinis resmi dan validasi ahli.",
    },
]

_SAFE_REASON_FIELDS = {
    "matched_attributes", "differing_attributes", "candidate_record_count",
    "distinct_participant_count", "mode", "case_count", "pattern_type",
    "supporting_values", "observed_service_units", "capacity_service_units",
    "capacity_threshold_multiplier", "utilization_ratio", "missing_evidence",
    "recorded_evidence", "rule", "similarity_ratio", "matched_attribute_count",
    "compared_attribute_count",
}


def _entries(result: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    raw = result.get(key, [])
    return [item for item in raw if isinstance(item, Mapping)] if isinstance(raw, (list, tuple)) else []


def _entry_index(result: Mapping[str, Any], *keys: str) -> dict[str, Mapping[str, Any]]:
    """Index detector case metadata once instead of rescanning it per case."""
    indexed: dict[str, Mapping[str, Any]] = {}
    for key in keys:
        for item in _entries(result, key):
            case_id = item.get("case_id")
            if isinstance(case_id, str):
                indexed.setdefault(case_id, item)
    return indexed


def _candidate_group_count(result: Mapping[str, Any]) -> int:
    candidates = result.get("candidate_groups", result.get("candidates", []))
    if isinstance(candidates, (list, tuple)):
        return len(candidates)
    return 0


def _coverage_for_indicator(
    indicator: str,
    result: Mapping[str, Any],
    scoring_coverage: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    aggregate = next((item for item in scoring_coverage
                      if item.get("indicator") == indicator), {})
    unavailable = result.get("status") == "unavailable"
    truncated = result.get("search_truncated") is True or any(
        item.get("case_ids_truncated") is True
        for item in _entries(result, "candidate_groups") + _entries(result, "candidates")
    )
    assessed_count = int(aggregate.get("assessed_case_count", 0))
    not_assessed_count = int(aggregate.get("not_assessed_case_count", 0))
    not_applicable_count = int(aggregate.get("not_applicable_case_count", 0))
    if unavailable:
        status = "unavailable"
    elif not assessed_count and not not_assessed_count and not_applicable_count:
        status = "not_applicable"
    else:
        status = "partial" if truncated or not_assessed_count else "complete"
    return {
        "indicator": indicator,
        "status": status,
        "records_assessed": assessed_count,
        "records_not_applicable": not_applicable_count,
        "records_unassessed": not_assessed_count,
        "search_truncated": truncated,
        "candidate_group_count": _candidate_group_count(result) if not unavailable else None,
        "limitations": list(result.get("limitations", INDICATOR_BY_CODE[indicator]["limitations"])),
    }


def _api_reason(reason: Mapping[str, Any]) -> dict[str, Any]:
    values = reason.get("supporting_values")
    safe_values = {
        key: value for key, value in values.items()
        if key in _SAFE_REASON_FIELDS
    } if isinstance(values, Mapping) else {}
    evidence: list[str] = []
    for key in ("matched_attributes", "differing_attributes"):
        value = safe_values.get(key)
        if isinstance(value, (list, tuple)) and value:
            evidence.append(f"{key}: {', '.join(str(item) for item in value)}")
    for key in (
        "candidate_record_count", "case_count", "distinct_participant_count",
        "observed_service_units", "capacity_service_units", "utilization_ratio",
        "similarity_ratio", "missing_evidence", "recorded_evidence",
    ):
        if key in safe_values:
            evidence.append(f"{key}: {safe_values[key]}")
    limitations = reason.get("limitations")
    return {
        "indicator": reason.get("indicator"),
        "summary": str(reason.get("reason") or "Sinyal kandidat terdeteksi oleh pemeriksaan."),
        "evidence": evidence,
        "limitations": [str(item) for item in limitations] if isinstance(limitations, list) else [],
        "supporting_values": safe_values,
    }


def build_analytics_snapshot(
    records: Sequence[Mapping[str, Any]] | None = None,
    period_from: date | None = None,
    period_to: date | None = None,
    facilities: Sequence[Mapping[str, Any]] | None = None,
    data_source: Mapping[str, Any] | None = None,
    stage_observer=None,
) -> dict[str, Any]:
    """Run one coordinated detector, scoring, and priority pass on features only."""
    if records is None:
        dataset = SyntheticDemoProvider().load()
        source_records = list(dataset.records)
        if facilities is None:
            facilities = dataset.facilities
        if data_source is None:
            data_source = dataset.source_metadata
    else:
        source_records = list(records)
    if period_from is not None or period_to is not None:
        selected = []
        for record in source_records:
            raw_date = record.get("service_date")
            try:
                service_date = date.fromisoformat(str(raw_date)[:10])
            except (TypeError, ValueError):
                continue
            if period_from is not None and service_date < period_from:
                continue
            if period_to is not None and service_date > period_to:
                continue
            selected.append(record)
        source_records = selected

    facility_metadata = list(facilities or [])
    if stage_observer:
        stage_observer("input_materialized")
    detector_results = run_detector_suite(source_records, facility_metadata)
    if stage_observer:
        stage_observer("detectors_complete")
    # The snapshot and priority queue only expose signaled claims. Avoid
    # retaining a full six-indicator detail object for every untriggered row;
    # aggregate coverage remains computed over the complete population.
    scoring = score_claims(source_records, detector_results, include_untriggered_cases=False)
    if stage_observer:
        stage_observer("scoring_complete")
    priority = build_audit_priority_queue(source_records, scoring)
    if stage_observer:
        stage_observer("priority_complete")
    scored_cases = scoring["cases"]
    coverage = {
        code: _coverage_for_indicator(code, detector_results[code], scoring["detector_coverage"])
        for code in DETECTOR_ORDER
    }
    execution_statuses = [item["status"] for item in coverage.values()]
    execution_status = (
        "failed" if execution_statuses and all(status == "unavailable" for status in execution_statuses)
        else "partial" if any(status in {"partial", "unavailable"} for status in execution_statuses)
        else "completed"
    )

    indicator_summaries: list[dict[str, Any]] = []
    for definition in INDICATOR_DEFINITIONS:
        code = definition["code"]
        result = detector_results[code]
        detector_coverage = coverage[code]
        candidate_ids = {
            item["case_id"] for item in scored_cases
            if code in item.get("triggered_indicators", [])
        }
        unavailable = detector_coverage["status"] == "unavailable"
        indicator_summaries.append({
            **definition,
            "status": detector_coverage["status"],
            "candidate_count": None if unavailable else len(candidate_ids),
            "candidate_group_count": detector_coverage["candidate_group_count"],
            "eligible_count": detector_coverage["records_assessed"],
            "not_applicable_count": detector_coverage["records_not_applicable"],
            "unassessed_count": detector_coverage["records_unassessed"],
            "search_truncated": detector_coverage["search_truncated"],
            "search_diagnostics": {
                "pair_comparisons": result.get("pair_comparisons"),
                **({key: value for key, value in result.get("search_diagnostics", {}).items()
                    if isinstance(value, (int, bool, str))}
                   if isinstance(result.get("search_diagnostics"), Mapping) else {}),
            },
        })

    candidates: dict[str, dict[str, Any]] = {}
    detector_case_indexes = {
        indicator: {
            "ineligible": _entry_index(result, "ineligible_cases"),
            "not_applicable": _entry_index(result, "not_applicable_cases"),
            "unassessed": _entry_index(result, "unassessed_cases", "unassessed_time_cases"),
        }
        for indicator, result in detector_results.items()
    }
    for scored in scored_cases:
        case_id = scored["case_id"]
        triggered = list(scored.get("triggered_indicators", []))
        if not triggered:
            continue
        coverage_rows = []
        not_applicable = []
        not_assessed = []
        for indicator in DETECTOR_ORDER:
            result = detector_results[indicator]
            entry_indexes = detector_case_indexes[indicator]
            state = next((
                item.get("status") for item in scored.get("indicator_coverage", [])
                if item.get("indicator") == indicator
            ), "not_assessed")
            state_reason = None
            ineligible_entry = entry_indexes["ineligible"].get(case_id)
            not_applicable_entry = entry_indexes["not_applicable"].get(case_id)
            matching_unassessed = entry_indexes["unassessed"].get(case_id)
            if state == "triggered":
                api_state = "triggered"
            elif state == "not_triggered":
                api_state = "not_triggered"
            elif not_applicable_entry is not None:
                api_state = "not_applicable"
                not_applicable.append(indicator)
                state_reason = str(not_applicable_entry.get("reason", "Pemeriksaan ini tidak berlaku untuk ruang lingkup record."))
            elif ineligible_entry is not None:
                api_state = "not_assessed"
                not_assessed.append(indicator)
                state_reason = str(ineligible_entry.get("reason", "Prasyarat atribut tidak terpenuhi; hasil negatif tidak dapat disimpulkan."))
            else:
                matching_reason = str(matching_unassessed.get("reason", "")) if matching_unassessed else ""
                api_state = "not_assessed"
                not_assessed.append(indicator)
                state_reason = matching_reason or (
                    "Detektor tidak tersedia." if result.get("status") == "unavailable" else
                    "Pencarian dibatasi; ketiadaan sinyal untuk kasus ini belum dapat dinilai."
                    if result.get("search_truncated") is True else
                    "Pemeriksaan belum menghasilkan penilaian untuk kasus ini."
                )
            coverage_rows.append({"indicator": indicator, "status": api_state, "reason": state_reason})

        reasons = [_api_reason(item) for item in scored.get("indicator_reasons", [])]
        reasons = [
            item for item in reasons
            if not item["summary"].startswith("Kontribusi indikator tetap dihitung")
        ]
        limitations = list(scored.get("limitations", []))
        if not_applicable:
            limitations.append("Satu atau lebih pemeriksaan tidak berlaku karena atribut/metadata yang diperlukan tidak tersedia atau aturan tidak mencakup layanan.")
        if not_assessed:
            limitations.append("Satu atau lebih pemeriksaan belum tuntas atau cakupannya terbatas; skor hanya memakai pemeriksaan yang dapat dinilai.")
        candidates[case_id] = {
            "case_id": case_id,
            "risk_level": None,
            "risk_score": scored.get("risk_score"),
            "score_status": scored.get("score_status"),
            "scoring_version": scored.get("score_version"),
            "indicators": triggered,
            "assessed_indicators": list(scored.get("assessed_indicators", [])),
            "not_applicable_indicators": sorted(not_applicable),
            "not_assessed_indicators": sorted(not_assessed),
            "indicator_coverage": coverage_rows,
            "status": "pending",
            "detected_at": None,
            "reasons": reasons,
            "limitations": list(dict.fromkeys(limitations)),
            "review": {"decision": None, "reviewed_at": None},
        }

    active_statuses = [item["status"] for item in coverage.values()]
    available_count = sum(status != "unavailable" for status in active_statuses)
    availability = "unavailable" if not available_count else ("insufficient_data" if not source_records else "available")
    snapshot = {
        "availability": availability,
        "execution_status": execution_status,
        "data_source": dict(data_source or DATA_SOURCE),
        "records_considered": len(source_records),
        "records_eligible": scoring["assessable_case_count"],
        "indicators": indicator_summaries,
        "indicator_coverage": [coverage[code] for code in DETECTOR_ORDER],
        "risk_scoring": {
            "version": scoring["scoring_version"],
            "weights": scoring["weights"],
            "weight_basis": scoring["weight_basis"],
            "unassessable_case_count": scoring["unassessable_case_count"],
            "limitations": scoring["limitations"],
        },
        "audit_priority": {
            "status": priority["status"],
            "priority_version": priority["priority_version"],
            "unit": priority["unit"],
            "formula": priority["formula"],
            "sorted_by": priority["sorted_by"],
            "items": priority["items"],
            "unit_count": len(priority["items"]),
            "unassigned_triggered_case_count": priority["unassigned_triggered_case_count"],
            "eligible_unit_count": priority["eligible_unit_count"],
            "eligibility_reasons": priority["eligibility_reasons"],
            "limitations": priority["limitations"] + ([
                "Sumber demo tidak menyediakan ID fasilitas dan metadata kapasitas yang tervalidasi; sinyal kasus tidak dapat diagregasi menjadi unit fasilitas tanpa mengarang identitas."
            ] if priority["unassigned_triggered_case_count"] else []),
        },
        "cases": candidates,
    }
    if stage_observer:
        stage_observer("snapshot_complete")
    return snapshot


def build_analytics_snapshot_from_provider(
    provider: FeatureSourceProvider,
    period_from: date | None = None,
    period_to: date | None = None,
    stage_observer=None,
) -> dict[str, Any]:
    """Run the coordinated pipeline from an explicitly selected feature source.

    API routes do not accept provider names. Callers must construct the provider
    in trusted service code; the default API path remains ``synthetic_demo``.
    """
    dataset = load_feature_dataset(provider)
    if stage_observer:
        stage_observer("provider_loaded")
    return build_analytics_snapshot_from_dataset(dataset, period_from, period_to, stage_observer)


def build_analytics_snapshot_from_dataset(
    dataset: FeatureDataset,
    period_from: date | None = None,
    period_to: date | None = None,
    stage_observer=None,
) -> dict[str, Any]:
    """Run the pipeline on a validated, source-independent canonical dataset."""
    return build_analytics_snapshot(
        records=dataset.records,
        facilities=dataset.facilities,
        data_source=dataset.source_metadata,
        period_from=period_from,
        period_to=period_to,
        stage_observer=stage_observer,
    )
