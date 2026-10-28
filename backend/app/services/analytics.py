"""Coordinate the active synthetic source, six detectors, scoring, and priority."""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from app.analytics.audit_priority import build_audit_priority_queue
from app.analytics.capacity import LIMITATIONS as CAPACITY_LIMITATIONS
from app.analytics.detector_utils import membership_incomplete
from app.analytics.evidence_completeness import LIMITATIONS as EVIDENCE_LIMITATIONS
from app.analytics.length_of_stay import INDICATOR as LOS_INDICATOR, LOS_VERSION, detect_length_of_stay_outliers
from app.analytics.ml_anomaly import ML_ANOMALY_VERSION, build_ml_anomaly_ranking
from app.analytics.clinical_rules import detect_rapid_readmission
from app.analytics.ml_model import load_artifact, score_records as score_pretrained_records, special_reference
from app.data_sources.fkrtl_local_source import FKRTL_SCHEMA_PROFILE
from app.analytics.near_duplicate_claims import LIMITATIONS as NEAR_LIMITATIONS
from app.analytics.repeat_billing import (
    INTERPRETATION as REPEAT_INTERPRETATION, LIMITATIONS as REPEAT_LIMITATIONS, SIGNATURE_PROFILES,
    detect_repeat_billing_candidates,
)
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
        "name": "Repeated-service pattern (Repeat Billing screening)",
        "definition": "Exact match signature klaim lengkap untuk peserta sintetis yang sama.",
        "limitations": REPEAT_LIMITATIONS,
        "interpretation": REPEAT_INTERPRETATION,
    },
    {
        "code": "similar_claim_pattern_candidate",
        "name": "Similar claim-pattern candidate",
        "definition": "Exact match pola klaim pada peserta sintetis berbeda.",
        "limitations": SIMILAR_LIMITATIONS,
    },
    {
        "code": "near_duplicate_claim_candidate",
        "name": "Cross-participant similar-claim screening (exploratory)",
        "definition": "Penyaringan eksploratif pasangan klaim dari peserta berbeda yang cocok pada sebagian besar atribut yang dibandingkan; bukan deteksi cloning tervalidasi dan tidak memakai identitas fasilitas.",
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
    {
        "code": "length_of_stay_extreme_candidate",
        "name": "Extreme length of stay",
        "definition": "Lama rawat inap jauh di atas kebiasaan INA-CBG dan kelas rawat yang sama di data acuan "
                      "(minimal 7 hari dan 5 simpangan robust di atas median).",
        "limitations": ["Data acuan adalah data sampel latih, bukan standar klinis; komplikasi dan status pulang tidak tersedia."],
    },
    {
        "code": "rapid_readmission_candidate",
        "name": "Rapid readmission",
        "definition": "Peserta yang sama dirawat inap lagi dengan diagnosis utama sama paling lama 3 hari setelah pulang.",
        "limitations": ["Rawat inap ulang yang sah tetap mungkin; hanya klaim di dalam data yang dianalisis yang dibandingkan."],
    },
    {
        "code": "unusual_severity_candidate",
        "name": "Unusual INA-CBG severity for the diagnosis",
        "definition": "INA-CBG keparahan II atau III yang dipakai pada kurang dari 5% klaim acuan dengan diagnosis "
                      "utama dan kelompok INA-CBG yang sama.",
        "limitations": ["Petunjuk untuk memeriksa resume medis; diagnosis sekunder diperiksa terpisah bila tersedia."],
    },
    {
        "code": "cloned_clinical_note_candidate",
        "name": "Cloned clinical notes",
        "definition": "Catatan klinis klaim dari peserta berbeda yang identik kata demi kata, termasuk angka pemeriksaannya.",
        "limitations": ["Hanya untuk file unggahan yang berisi kolom CATATAN_KLINIS; parafrase tidak tertangkap."],
    },
    {
        "code": "severity_without_secondary_candidate",
        "name": "Severity without a secondary diagnosis",
        "definition": "Rawat inap dengan INA-CBG keparahan II atau III tanpa satu pun diagnosis sekunder (komorbid atau "
                      "komplikasi yang mendasari keparahan).",
        "limitations": ["Hanya untuk sumber yang menyertakan diagnosis sekunder; diagnosis yang tidak terekam tetap mungkin."],
    },
    {
        "code": "unusual_special_topup_candidate",
        "name": "Special top-up unusual for the INA-CBG",
        "definition": "Obat, alat/prostesis, prosedur, atau pemeriksaan khusus yang ditagihkan bersama INA-CBG yang di data "
                      "acuan jarang (kurang dari 5 kali) mendapat tambahan tersebut.",
        "limitations": ["Pasangan langka bisa sah; bukti pemberian obat atau alat tidak tersedia di data klaim."],
    },
)
INDICATOR_BY_CODE = {item["code"]: item for item in INDICATOR_DEFINITIONS}
DEFAULT_REPEAT_SIGNATURE_PROFILE = "repeat-billing-exact-v1"
_REPEAT_PROFILE_DEFINITIONS = {
    "repeat-service-v1": (
        "Kunjungan peserta yang sama dengan tanggal datang, diagnosis primer, kode INA-CBG, dan prosedur identik "
        "(repeat_service_v1); prosedur kosong berarti tidak dinilai. Wilayah, kategori fasilitas, dan diagnosis "
        "masuk hanya ditampilkan sebagai konteks; nilai tagih tidak dibandingkan karena belum terverifikasi."
    ),
    "repeat-visit-exact-no-amount-v1": (
        "Exact match kunjungan untuk peserta yang sama pada tanggal datang, wilayah/kategori fasilitas, "
        "diagnosis masuk/primer, kode INA-CBG, dan prosedur; nilai tagih tidak dibandingkan karena belum terverifikasi."
    ),
}
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
    "matched_attributes", "differing_attributes", "context_unavailable_attributes", "candidate_record_count",
    "distinct_participant_count", "mode", "case_count", "pattern_type", "earlier_claim_count",
    "supporting_values", "observed_service_units", "capacity_service_units",
    "capacity_threshold_multiplier", "utilization_ratio", "missing_evidence",
    "recorded_evidence", "rule", "similarity_ratio", "matched_attribute_count",
    "compared_attribute_count", "interpretation", "billing_status_evidence",
    "match_support", "expected_chance_pairs", "evidence_class",
}


_IDENTITY_ATTRIBUTES = {"participant_token", "PSTV01"}


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


def _unassessed_reason_counts(result: Mapping[str, Any], excluded: set[str]) -> dict[str, int]:
    """One reason code per unassessed record, from the detector's own outputs.

    ``excluded`` holds records scoring counts as assessed or not applicable
    (flagged records stay assessed even when a truncated search also lists
    them), so the counts add up to ``records_unassessed``.

    Codes carry field names or the detector's fixed reason text only, never
    record values: ``missing:<field>[+<field>...]``, ``reason:<text>``, or
    ``not_reached_by_search`` for records the bounded search did not reach
    (a blocking attribute is missing or a search limit was hit).
    """
    reasons: dict[str, str] = {}
    excluded = excluded | {
        item["case_id"] for item in _entries(result, "not_applicable_cases") if isinstance(item.get("case_id"), str)
    }
    for key in ("ineligible_cases", "unassessed_cases", "unassessed_time_cases"):
        for item in _entries(result, key):
            case_id = item.get("case_id")
            if not isinstance(case_id, str) or case_id in reasons or case_id in excluded:
                continue
            missing = item.get("missing_attributes")
            if isinstance(missing, (list, tuple)) and missing and all(isinstance(field, str) for field in missing):
                reasons[case_id] = "missing:" + "+".join(missing)
            elif isinstance(item.get("reason"), str):
                reasons[case_id] = "reason:" + item["reason"]
            else:
                reasons[case_id] = "unspecified"
    explicit = result.get("unassessed_case_ids")
    for case_id in explicit if isinstance(explicit, (list, tuple)) else []:
        if isinstance(case_id, str) and case_id not in excluded:
            reasons.setdefault(case_id, "not_reached_by_search")
    counts: dict[str, int] = {}
    for code in reasons.values():
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _with_search_limited(counts: dict[str, int], records_unassessed: int) -> dict[str, int]:
    """Records withheld only because a search was limited are not listed per record by
    every detector (a global truncation flag withholds all unflagged records); count
    them as ``search_limited`` so the reasons add up to ``records_unassessed``."""
    remainder = records_unassessed - sum(counts.values())
    return {**counts, "search_limited": remainder} if remainder > 0 else counts


def _coverage_for_indicator(
    indicator: str,
    result: Mapping[str, Any],
    scoring_coverage: Sequence[Mapping[str, Any]],
    triggered_case_ids: set[str] | None = None,
) -> dict[str, Any]:
    aggregate = next((item for item in scoring_coverage
                      if item.get("indicator") == indicator), {})
    unavailable = result.get("status") == "unavailable"
    truncated = result.get("search_truncated") is True or any(
        membership_incomplete(item)
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
        # Unavailable detectors have no per-record reasons; the whole population is unassessed.
        "unassessed_reason_counts": {} if unavailable else _with_search_limited(
            _unassessed_reason_counts(result, triggered_case_ids or set()), not_assessed_count),
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
    # Identity fields are compared internally only; drop their names here so the
    # structured lists and the evidence lines below describe the same attributes.
    for key in ("matched_attributes", "differing_attributes", "context_unavailable_attributes"):
        if isinstance(safe_values.get(key), (list, tuple)):
            safe_values[key] = [item for item in safe_values[key] if item not in _IDENTITY_ATTRIBUTES]
    evidence: list[str] = []
    for key in ("matched_attributes", "differing_attributes", "context_unavailable_attributes"):
        value = safe_values.get(key)
        if isinstance(value, (list, tuple)) and value:
            evidence.append(f"{key}: {', '.join(str(item) for item in value)}")
    for key in (
        "candidate_record_count", "case_count", "distinct_participant_count",
        "observed_service_units", "capacity_service_units", "utilization_ratio",
        "similarity_ratio", "match_support", "missing_evidence", "recorded_evidence", "earlier_claim_count",
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
    earlier_records: Sequence[Mapping[str, Any]] = (),
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
    # The profile comes from trusted provider metadata, never from request input.
    repeat_profile = str((data_source or {}).get("repeat_signature_profile") or DEFAULT_REPEAT_SIGNATURE_PROFILE)
    if repeat_profile not in SIGNATURE_PROFILES:
        raise ValueError("Unknown repeat signature profile.")
    # Checks the trusted source declares it cannot support are reported as not
    # applicable, never as failed or incomplete searches.
    declared = (data_source or {}).get("not_applicable_detectors") or {}
    if not isinstance(declared, Mapping) or not all(
        isinstance(code, str) and isinstance(reason, str) for code, reason in declared.items()
    ):
        raise ValueError("not_applicable_detectors must map detector codes to reasons.")
    if stage_observer:
        stage_observer("input_materialized")
    bpjs_columns = (data_source or {}).get("source_schema_profile") == FKRTL_SCHEMA_PROFILE
    clinical_reference = special = None
    if bpjs_columns:
        try:
            clinical_reference = load_artifact()["reference"]
        except Exception:
            clinical_reference = None  # the stay and severity checks then report themselves unavailable
        special = special_reference() or None  # without it the special top-up check reports itself unavailable
    detector_results = run_detector_suite(
        source_records, facility_metadata, repeat_signature_fields=SIGNATURE_PROFILES[repeat_profile],
        not_applicable=declared, clinical_rules=bpjs_columns, clinical_reference=clinical_reference,
        special_reference=special,
    )
    if earlier_records:
        _compare_with_earlier_claims(detector_results, source_records, earlier_records,
                                     SIGNATURE_PROFILES[repeat_profile])
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
    # Separate unsupervised ranking: never feeds rule coverage, the risk index,
    # execution_status, or audit priority.
    try:
        if (data_source or {}).get("source_schema_profile") == FKRTL_SCHEMA_PROFILE:
            # FKRTL runs score with the offline-trained artifact; nothing is refitted per run.
            ml_anomaly, ml_ranks = score_pretrained_records(source_records)
        else:
            ml_anomaly, ml_ranks = build_ml_anomaly_ranking(source_records)
    except Exception as error:
        ml_anomaly = {
            "status": "unavailable", "model_version": ML_ANOMALY_VERSION, "error_type": type(error).__name__,
            "records_considered": len(source_records), "records_scored": 0, "items": [],
            "items_truncated": False, "limitations": ["Peringkat anomali ML gagal dijalankan; sinyal aturan tetap tersedia."],
        }
        ml_ranks = {}
    if stage_observer:
        stage_observer("ml_anomaly_complete")
    # Standalone exploratory duration screen: like the ML ranking, it never
    # feeds rule coverage, the risk index, action lanes or audit priority.
    try:
        length_of_stay = detect_length_of_stay_outliers(source_records)
    except Exception as error:
        length_of_stay = {
            "indicator": LOS_INDICATOR, "status": "unavailable", "version": LOS_VERSION,
            "error_type": type(error).__name__, "input_record_count": len(source_records),
            "assessed_count": 0, "unassessed_count": len(source_records), "candidate_count": 0, "candidates": [],
            "limitations": ["Penyaringan durasi gagal dijalankan; sinyal lain tetap tersedia."],
        }
    los_by_case = {item["case_id"]: item for item in length_of_stay.get("candidates", [])}
    scored_cases = scoring["cases"]
    coverage = {
        code: _coverage_for_indicator(code, detector_results[code], scoring["detector_coverage"], {
            item["case_id"] for item in scored_cases if code in item.get("triggered_indicators", [])
        })
        for code in DETECTOR_ORDER
    }
    execution_statuses = [item["status"] for item in coverage.values()]
    nothing_assessed = not any(item["records_assessed"] for item in coverage.values())
    execution_status = (
        "failed" if execution_statuses and all(status == "unavailable" for status in execution_statuses)
        # "completed" requires at least one check to have assessed records;
        # a run where every check is not applicable has no result to complete.
        else "partial" if nothing_assessed or any(status in {"partial", "unavailable"} for status in execution_statuses)
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
        if code == "repeat_billing_candidate" and repeat_profile in _REPEAT_PROFILE_DEFINITIONS:
            definition = {**definition, "definition": _REPEAT_PROFILE_DEFINITIONS[repeat_profile]}
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
            elif not_applicable_entry is not None or state == "not_applicable":
                # A check the source declares unsupported has no per-record list; it is
                # still not applicable (as in the indicator summary), never "not assessed".
                api_state = "not_applicable"
                not_applicable.append(indicator)
                declared = result.get("limitations") if result.get("status") == "not_applicable" else None
                state_reason = str(
                    not_applicable_entry.get("reason", "Pemeriksaan ini tidak berlaku untuk ruang lingkup record.")
                    if not_applicable_entry is not None else
                    declared[0] if isinstance(declared, list) and declared else
                    "Pemeriksaan ini tidak berlaku untuk ruang lingkup record."
                )
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
            "score_basis": scored.get("score_basis"),
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
            # Scored records carry their rank; a record the model could not score carries its
            # inference status instead, so "not ranked" is never confused with "not assessed".
            "ml_anomaly": ml_ranks.get(case_id) if "rank" in (ml_ranks.get(case_id) or {}) else None,
            **({"ml_inference": ml_ranks[case_id]}
               if (ml_ranks.get(case_id) or {}).get("inference_status") == "not_assessed" else {}),
            "length_of_stay": los_by_case.get(case_id),
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
            "insufficient_indicator_case_count": scoring["insufficient_indicator_case_count"],
            "minimum_assessed_indicators": scoring["minimum_assessed_indicators"],
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
        "ml_anomaly": ml_anomaly,
        "length_of_stay": length_of_stay,
    }
    if stage_observer:
        stage_observer("snapshot_complete")
    return snapshot


CROSS_DAY_INDICATORS = ("repeat_billing_candidate", "rapid_readmission_candidate")


def _keep_current(result: Mapping[str, Any], current: set[str], current_count: int) -> dict[str, Any]:
    """A cross-day detector result reduced to the claims of this analysis; earlier claims are only named by count."""
    key = "candidate_groups" if "candidate_groups" in result else "candidates"
    kept = []
    for candidate in result.get(key) or []:
        members = list(candidate.get("case_ids") or ([candidate["case_id"]] if candidate.get("case_id") else []))
        own = [case_id for case_id in members if case_id in current]
        if not own:
            continue
        item = {field: value for field, value in candidate.items() if field != "case_id"}
        item["case_ids"] = own
        earlier = len(members) - len(own)
        if earlier:
            item["earlier_claim_count"] = earlier
            item["reason"] = (f"{candidate.get('reason', '')} Termasuk {earlier} klaim dari data sebelumnya "
                              "yang sudah dianalisis.").strip()
        kept.append(item)
    reduced = {**result, key: kept, "input_record_count": current_count}
    for list_key in ("ineligible_cases", "unassessed_cases", "unassessed_time_cases", "not_applicable_cases"):
        if isinstance(result.get(list_key), list):
            reduced[list_key] = [item for item in result[list_key] if item.get("case_id") in current]
    if isinstance(result.get("unassessed_case_ids"), list):
        reduced["unassessed_case_ids"] = [case_id for case_id in result["unassessed_case_ids"] if case_id in current]
    if "assessed_count" in result:
        reduced["assessed_count"] = current_count - len(reduced.get("unassessed_case_ids", [])) - len(
            reduced.get("not_applicable_cases", [])) - len(reduced.get("ineligible_cases", []))
    return reduced


def _compare_with_earlier_claims(results: dict[str, Any], records: Sequence[Mapping[str, Any]],
                                 earlier: Sequence[Mapping[str, Any]], signature_fields: Sequence[str]) -> None:
    """Re-run the repeat and readmission checks over this file plus earlier claims (cross-day duplicates)."""
    current = {str(record.get("case_id")) for record in records}
    combined = list(records) + [record for record in earlier if record.get("case_id") not in current]
    if len(combined) == len(records):
        return
    calls = {
        "repeat_billing_candidate": lambda: detect_repeat_billing_candidates(combined, signature_fields),
        "rapid_readmission_candidate": lambda: detect_rapid_readmission(combined),
    }
    for code, call in calls.items():
        if (results.get(code) or {}).get("status") in {"not_applicable", "unavailable"}:
            continue
        try:
            results[code] = _keep_current(call(), current, len(records))
        except Exception:
            pass  # the same-file result stays in place


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
        earlier_records=dataset.earlier_records,
        facilities=dataset.facilities,
        data_source=dataset.source_metadata,
        period_from=period_from,
        period_to=period_to,
        stage_observer=stage_observer,
    )
