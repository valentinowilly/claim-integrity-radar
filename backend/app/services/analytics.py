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
from app.data_sources.synthetic import get_synthetic_records


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


def _candidate_group_count(result: Mapping[str, Any]) -> int:
    candidates = result.get("candidate_groups", result.get("candidates", []))
    if isinstance(candidates, (list, tuple)):
        return len(candidates)
    return 0


def _coverage_for_indicator(
    indicator: str,
    result: Mapping[str, Any],
    scored_cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    states = {
        item.get("case_id"): next((
            coverage.get("status") for coverage in item.get("indicator_coverage", [])
            if isinstance(coverage, Mapping) and coverage.get("indicator") == indicator
        ), "not_assessed")
        for item in scored_cases
    }
    ineligible_ids = {
        item.get("case_id") for item in _entries(result, "ineligible_cases")
        if isinstance(item.get("case_id"), str)
    }
    not_applicable_ids = set(ineligible_ids)
    unassessed_ids = {
        item.get("case_id") for key in ("unassessed_cases", "unassessed_time_cases")
        for item in _entries(result, key) if isinstance(item.get("case_id"), str)
    }
    # Evidence rules that do not cover a service are out of scope; an inventory
    # that was not recorded remains unassessed instead of being called absent.
    for item in _entries(result, "unassessed_cases"):
        if "Belum ada aturan bukti" in str(item.get("reason", "")):
            not_applicable_ids.add(item["case_id"])
            unassessed_ids.discard(item["case_id"])

    unavailable = result.get("status") == "unavailable"
    truncated = result.get("search_truncated") is True or any(
        item.get("case_ids_truncated") is True
        for item in _entries(result, "candidate_groups") + _entries(result, "candidates")
    )
    assessed_count = sum(state in {"triggered", "not_triggered"} for state in states.values())
    not_assessed_count = sum(
        state == "not_assessed" and case_id not in not_applicable_ids
        for case_id, state in states.items()
    )
    if unavailable:
        status = "unavailable"
    elif not assessed_count and not not_assessed_count and not_applicable_ids and states:
        status = "not_applicable"
    else:
        status = "partial" if truncated or not_assessed_count else "complete"
    return {
        "indicator": indicator,
        "status": status,
        "records_assessed": assessed_count,
        "records_not_applicable": len(not_applicable_ids),
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
) -> dict[str, Any]:
    """Run one coordinated detector, scoring, and priority pass on features only."""
    source_records = list(records if records is not None else get_synthetic_records())
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
    detector_results = run_detector_suite(source_records, facility_metadata)
    scoring = score_claims(source_records, detector_results)
    priority = build_audit_priority_queue(source_records, scoring)
    scored_cases = scoring["cases"]
    scored_by_id = {item["case_id"]: item for item in scored_cases}
    coverage = {
        code: _coverage_for_indicator(code, detector_results[code], scored_cases)
        for code in DETECTOR_ORDER
    }

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
        })

    candidates: dict[str, dict[str, Any]] = {}
    for case_id, scored in scored_by_id.items():
        triggered = list(scored.get("triggered_indicators", []))
        if not triggered:
            continue
        coverage_rows = []
        not_applicable = []
        not_assessed = []
        for indicator in DETECTOR_ORDER:
            result = detector_results[indicator]
            state = next((
                item.get("status") for item in scored.get("indicator_coverage", [])
                if item.get("indicator") == indicator
            ), "not_assessed")
            state_reason = None
            ineligible_entry = next((
                item for item in _entries(result, "ineligible_cases") if item.get("case_id") == case_id
            ), None)
            unassessed_items = _entries(result, "unassessed_cases") + _entries(result, "unassessed_time_cases")
            matching_unassessed = next((
                item for item in unassessed_items if item.get("case_id") == case_id
            ), None)
            if state == "triggered":
                api_state = "triggered"
            elif state == "not_triggered":
                api_state = "not_triggered"
            elif ineligible_entry is not None:
                api_state = "not_applicable"
                not_applicable.append(indicator)
                state_reason = str(ineligible_entry.get("reason", "Atribut yang diperlukan untuk pemeriksaan ini tidak tersedia."))
            else:
                matching_reason = str(matching_unassessed.get("reason", "")) if matching_unassessed else ""
                if "Belum ada aturan bukti" in matching_reason:
                    api_state = "not_applicable"
                    not_applicable.append(indicator)
                    state_reason = matching_reason
                else:
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
    return {
        "availability": availability,
        "data_source": dict(DATA_SOURCE),
        "records_considered": len(source_records),
        "records_eligible": len({
            item["case_id"] for item in scored_cases if item.get("assessed_indicators")
        }),
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
            "status": "available" if priority["items"] else "not_assessable",
            "priority_version": priority["priority_version"],
            "unit": priority["unit"],
            "formula": priority["formula"],
            "sorted_by": priority["sorted_by"],
            "items": priority["items"],
            "unit_count": len(priority["items"]),
            "unassigned_triggered_case_count": priority["unassigned_triggered_case_count"],
            "limitations": priority["limitations"] + ([
                "Sumber demo tidak menyediakan ID fasilitas dan metadata kapasitas yang tervalidasi; sinyal kasus tidak dapat diagregasi menjadi unit fasilitas tanpa mengarang identitas."
            ] if priority["unassigned_triggered_case_count"] else []),
        },
        "cases": candidates,
    }
