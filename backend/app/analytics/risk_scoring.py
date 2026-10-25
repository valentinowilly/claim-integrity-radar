"""Provisional weighted rule-risk index over six isolated detectors."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from app.analytics.capacity import detect_capacity_candidates
from app.analytics.detector_utils import date_value, text_value, valid_records
from app.analytics.evidence_completeness import detect_evidence_completeness
from app.analytics.near_duplicate_claims import detect_near_duplicate_claims
from app.analytics.repeat_billing import detect_repeat_billing_candidates
from app.analytics.similar_claim_pattern import detect_similar_claim_patterns
from app.analytics.temporal_patterns import detect_temporal_patterns


SCORING_VERSION = "rule-risk-index-v1-provisional"
# Manually maintained contract identifier; this is not a source/build hash.
DETECTOR_SUITE_VERSION = "detector-suite-v1-manual"
DETECTOR_ORDER = (
    "repeat_billing_candidate",
    "similar_claim_pattern_candidate",
    "near_duplicate_claim_candidate",
    "synthetic_capacity_candidate",
    "temporal_pattern_candidate",
    "supporting_evidence_completeness_candidate",
)
DEFAULT_WEIGHTS = {indicator: Decimal("1") for indicator in DETECTOR_ORDER}
_SAFE_DETAIL_FIELDS = (
    "matched_attributes", "differing_attributes", "candidate_record_count",
    "distinct_participant_count", "mode", "case_count", "pattern_type",
    "period", "supporting_values", "observed_service_units", "capacity_service_units",
    "capacity_threshold_multiplier", "utilization_ratio", "missing_evidence",
    "recorded_evidence", "rule", "similarity_ratio", "matched_attribute_count",
    "compared_attribute_count",
)
LIMITATIONS = [
    "Indeks adalah agregasi aturan prototipe, bukan probabilitas fraud, kerugian, atau keputusan pelanggaran.",
    "Bobot default sama besar untuk transparansi dan belum dilatih, dikalibrasi, atau disahkan ahli domain.",
    "Status tidak terpicu hanya berarti tidak ditemukan sinyal pada pemeriksaan yang tercakup; bukan bukti risiko nihil.",
]


@dataclass(frozen=True)
class RiskScoringConfig:
    weights: Mapping[str, int | float | Decimal] | None = None
    version: str = SCORING_VERSION
    max_reasons_per_indicator: int = 5

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version wajib diisi")
        if self.max_reasons_per_indicator < 1:
            raise ValueError("max_reasons_per_indicator minimal 1")
        for key, value in (self.weights or {}).items():
            if key not in DETECTOR_ORDER:
                raise ValueError(f"Bobot tidak dikenal: {key}")
            try:
                decimal_value = Decimal(str(value))
            except InvalidOperation as error:
                raise ValueError(f"Bobot {key} tidak valid") from error
            if not decimal_value.is_finite() or decimal_value <= 0:
                raise ValueError(f"Bobot {key} harus positif dan finite")


def _effective_weights(config: RiskScoringConfig) -> dict[str, Decimal]:
    weights = dict(DEFAULT_WEIGHTS)
    for key, value in (config.weights or {}).items():
        weights[key] = Decimal(str(value))
    return weights


def run_detector_suite(
    records: Sequence[Mapping[str, Any]],
    facilities: Sequence[Mapping[str, Any]],
    *,
    near_duplicate_candidate_pair_observer: Callable[[str, str], None] | None = None,
    near_duplicate_similarity_observer: Callable[[str, str, bool], None] | None = None,
) -> dict[str, dict[str, Any]]:
    """Run the six rule detectors on feature records only.

    Exceptions are surfaced as per-detector unavailable states; no ground truth
    argument exists in this interface.
    """
    calls = (
        ("repeat_billing_candidate", lambda: detect_repeat_billing_candidates(records)),
        ("similar_claim_pattern_candidate", lambda: detect_similar_claim_patterns(records)),
        ("near_duplicate_claim_candidate", lambda: detect_near_duplicate_claims(
            records,
            candidate_pair_observer=near_duplicate_candidate_pair_observer,
            similarity_observer=near_duplicate_similarity_observer,
        )),
        ("synthetic_capacity_candidate", lambda: detect_capacity_candidates(records, facilities)),
        ("temporal_pattern_candidate", lambda: detect_temporal_patterns(records)),
        ("supporting_evidence_completeness_candidate", lambda: detect_evidence_completeness(records)),
    )
    results: dict[str, dict[str, Any]] = {}
    for indicator, call in calls:
        try:
            results[indicator] = call()
        except Exception as error:  # convert a detector failure to explicit coverage metadata
            results[indicator] = {
                "indicator": indicator,
                "status": "unavailable",
                "error_type": type(error).__name__,
            }
    return results


def _candidate_ids(candidate: Mapping[str, Any]) -> list[str] | None:
    raw_ids = candidate.get("case_ids")
    if isinstance(raw_ids, (list, tuple)):
        if any(not isinstance(case_id, str) for case_id in raw_ids):
            return None
        return list(raw_ids)
    case_id = candidate.get("case_id")
    return [case_id] if isinstance(case_id, str) else None


def _candidate_details(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {field: candidate[field] for field in _SAFE_DETAIL_FIELDS if field in candidate}


def _capacity_membership(candidate: Mapping[str, Any], rows: list[tuple[str, Mapping[str, Any]]]) -> list[str]:
    """Recover all members of an explicitly described truncated capacity group."""
    if candidate.get("case_ids_truncated") is not True:
        ids = _candidate_ids(candidate)
        return ids or []
    facility_id = text_value(candidate.get("facility_id"))
    service_type = text_value(candidate.get("service_type"))
    period = candidate.get("period")
    if facility_id is None or service_type is None or not isinstance(period, Mapping):
        ids = _candidate_ids(candidate)
        return ids or []
    start, end = date_value(period.get("from")), date_value(period.get("to"))
    if start is None or end is None:
        ids = _candidate_ids(candidate)
        return ids or []
    return [
        case_id for case_id, row in rows
        if row.get("facility_id") == facility_id
        and row.get("service_type") == service_type
        and (day := date_value(row.get("service_date"))) is not None
        and start <= day <= end
    ]


def score_claims(
    records: Sequence[Mapping[str, Any]],
    detector_results: Mapping[str, Mapping[str, Any]] | None,
    config: RiskScoringConfig | None = None,
    *,
    include_untriggered_cases: bool = True,
) -> dict[str, Any]:
    """Map six detector outputs to claims and compute a normalized weighted index.

    Each detector contributes at most once to a case, regardless of how many
    pairs/groups from that detector contain the case. An unassessed indicator
    is excluded from the denominator instead of being treated as a negative.
    """
    config = config or RiskScoringConfig()
    weights = _effective_weights(config)
    validated = valid_records(records)
    case_ids = {case_id for case_id, _ in validated}
    status_by_indicator: dict[str, str] = {}
    search_truncated_by_indicator: dict[str, bool] = {indicator: False for indicator in DETECTOR_ORDER}
    # Keep reasons sparse. The former case × indicator × empty-list matrix
    # dominated memory on large inputs even though only a small fraction of
    # claims had detector findings.
    reasons_by_case: dict[str, dict[str, list[dict[str, Any]]]] = {}
    unassessed_by_indicator: dict[str, set[str]] = {indicator: set() for indicator in DETECTOR_ORDER}
    not_applicable_by_indicator: dict[str, set[str]] = {indicator: set() for indicator in DETECTOR_ORDER}
    partial_group_notes: list[dict[str, Any]] = []

    for indicator in DETECTOR_ORDER:
        result = (detector_results or {}).get(indicator)
        if not isinstance(result, Mapping) or result.get("indicator") != indicator:
            status_by_indicator[indicator] = "unavailable"
            unassessed_by_indicator[indicator] = set(case_ids)
            continue
        declared_status = result.get("status")
        if declared_status not in {None, "complete", "partial", "unavailable", "not_applicable"}:
            status_by_indicator[indicator] = "unavailable"
            unassessed_by_indicator[indicator] = set(case_ids)
            continue
        if declared_status == "unavailable":
            status_by_indicator[indicator] = "unavailable"
            unassessed_by_indicator[indicator] = set(case_ids)
            continue
        if result.get("input_record_count") != len(validated):
            status_by_indicator[indicator] = "unavailable"
            unassessed_by_indicator[indicator] = set(case_ids)
            continue
        candidate_key = "candidate_groups" if "candidate_groups" in result else "candidates"
        candidates = result.get(candidate_key)
        if not isinstance(candidates, (list, tuple)) or any(not isinstance(item, Mapping) for item in candidates):
            status_by_indicator[indicator] = "unavailable"
            unassessed_by_indicator[indicator] = set(case_ids)
            continue

        ineligible: set[str] = set()
        not_applicable: set[str] = set()
        unassessed: set[str] = set()
        malformed = False
        for collection_key in ("ineligible_cases", "unassessed_cases", "unassessed_time_cases"):
            items = result.get(collection_key, [])
            if not isinstance(items, (list, tuple)):
                malformed = True
                break
            if any(not isinstance(item, Mapping) or not isinstance(item.get("case_id"), str) for item in items):
                malformed = True
                break
            ids = {item["case_id"] for item in items}
            (ineligible if collection_key == "ineligible_cases" else unassessed).update(ids)
        explicit_unassessed_ids = result.get("unassessed_case_ids", [])
        if not isinstance(explicit_unassessed_ids, (list, tuple)) or any(
            not isinstance(case_id, str) for case_id in explicit_unassessed_ids
        ):
            malformed = True
        else:
            unassessed.update(explicit_unassessed_ids)
        applicable_items = result.get("not_applicable_cases", [])
        if not isinstance(applicable_items, (list, tuple)):
            malformed = True
        else:
            if any(not isinstance(item, Mapping) or not isinstance(item.get("case_id"), str) for item in applicable_items):
                malformed = True
            else:
                not_applicable.update(item["case_id"] for item in applicable_items)
        if (ineligible | unassessed | not_applicable) - case_ids:
            malformed = True
        if (ineligible & not_applicable) or (unassessed & not_applicable):
            malformed = True
        if malformed:
            status_by_indicator[indicator] = "unavailable"
            unassessed_by_indicator[indicator] = set(case_ids)
            continue

        truncated_value = result.get("search_truncated", False)
        if not isinstance(truncated_value, bool):
            status_by_indicator[indicator] = "unavailable"
            unassessed_by_indicator[indicator] = set(case_ids)
            continue
        partial = truncated_value or declared_status == "partial"
        # Keep the hard-search flag separate from assessment completeness.
        # Explicit unassessed cases can exist even when a bounded sampler did
        # not exhaust a hard comparison/candidate limit.
        search_truncated_by_indicator[indicator] = truncated_value
        for candidate in candidates:
            ids = _capacity_membership(candidate, validated) if indicator == "synthetic_capacity_candidate" else _candidate_ids(candidate)
            if ids is None:
                malformed = True
                break
            unknown = set(ids) - case_ids
            if unknown:
                malformed = True
                break
            candidate_id = candidate.get("candidate_id", candidate.get("group_id"))
            reason = candidate.get("reason")
            reason_entry = {
                "indicator": indicator,
                "candidate_id": candidate_id if isinstance(candidate_id, str) else None,
                "reason": reason if isinstance(reason, str) else "Kandidat terdeteksi; alasan tekstual tidak tersedia.",
                "supporting_values": _candidate_details(candidate),
                "limitations": list(candidate.get("limitations", [])) if isinstance(candidate.get("limitations"), list) else [],
            }
            for case_id in sorted(set(ids)):
                reasons_by_case.setdefault(case_id, {}).setdefault(indicator, []).append(reason_entry)
            if candidate.get("case_ids_truncated") is True and indicator != "synthetic_capacity_candidate":
                partial = True
                search_truncated_by_indicator[indicator] = True
                explicit_ids = _candidate_ids(candidate) or []
                unresolved = max(0, int(candidate.get("case_count", len(explicit_ids))) - len(explicit_ids))
                known_facilities = sorted({
                    text_value(row.get("facility_id")) for case_id, row in validated
                    if case_id in explicit_ids and text_value(row.get("facility_id")) is not None
                })
                partial_group_notes.append({
                    "indicator": indicator,
                    "known_case_ids": explicit_ids,
                    "unresolved_case_count": unresolved,
                    "known_facility_ids": known_facilities,
                })
        if malformed:
            status_by_indicator[indicator] = "unavailable"
            unassessed_by_indicator[indicator] = set(case_ids)
            for case_id in list(reasons_by_case):
                reasons_by_case[case_id].pop(indicator, None)
                if not reasons_by_case[case_id]:
                    del reasons_by_case[case_id]
            continue
        if declared_status == "not_applicable" and any(
            reasons_by_case.get(case_id, {}).get(indicator) for case_id in case_ids
        ):
            malformed = True
        if malformed:
            status_by_indicator[indicator] = "unavailable"
            unassessed_by_indicator[indicator] = set(case_ids)
            not_applicable_by_indicator[indicator].clear()
            for case_id in list(reasons_by_case):
                reasons_by_case[case_id].pop(indicator, None)
                if not reasons_by_case[case_id]:
                    del reasons_by_case[case_id]
            continue
        if declared_status == "not_applicable":
            not_applicable = set(case_ids)
        not_applicable_by_indicator[indicator] = not_applicable
        if partial and result.get("truncation_scope") != "explicit_unassessed_cases":
            # Legacy detectors expose only a global truncation flag. In that
            # case, conservatively withhold negative findings for the full
            # applicable population. Detectors with explicit per-case scope
            # can retain completed assessments outside skipped search regions.
            unassessed.update(case_id for case_id in case_ids if case_id not in not_applicable)
        unassessed_by_indicator[indicator] = ineligible | unassessed
        status_by_indicator[indicator] = (
            "not_applicable" if not_applicable == case_ids and not case_ids.intersection(ineligible)
            else "partial" if partial or ineligible or unassessed else "available"
        )

    scored_cases: list[dict[str, Any]] = []
    unassessable_case_count = 0
    assessable_case_count = 0
    triggered_case_count = 0
    for case_id, row in validated:
        trigger_states: list[str] = []
        assessed: list[str] = []
        unassessed: list[str] = []
        reasons: list[dict[str, Any]] = []
        numerator = Decimal(0)
        denominator = Decimal(0)
        for indicator in DETECTOR_ORDER:
            matches = sorted(
                reasons_by_case.get(case_id, {}).get(indicator, []),
                key=lambda item: (item["candidate_id"] or "", item["reason"]),
            )
            state = "triggered" if matches else (
                "not_applicable" if case_id in not_applicable_by_indicator[indicator] else
                "not_assessed" if case_id in unassessed_by_indicator[indicator] else "not_triggered"
            )
            trigger_states.append(state)
            if state in {"triggered", "not_triggered"}:
                assessed.append(indicator)
                denominator += weights[indicator]
            elif state == "not_assessed":
                unassessed.append(indicator)
            if state == "triggered":
                numerator += weights[indicator]
                for match in matches[:config.max_reasons_per_indicator]:
                    reasons.append(match)
                if len(matches) > config.max_reasons_per_indicator:
                    reasons.append({
                        "indicator": indicator,
                        "additional_candidate_reason_count": len(matches) - config.max_reasons_per_indicator,
                        "reason": "Kontribusi indikator tetap dihitung satu kali untuk klaim ini.",
                    })
        if denominator == 0:
            score = None
            score_status = "not_assessable"
            unassessable_case_count += 1
        else:
            score = round(float(numerator / denominator), 6)
            assessable_case_count += 1
            score_status = "assessed_no_signal" if numerator == 0 and not unassessed else (
                "partial_coverage" if unassessed else "assessed"
            )
            if numerator == 0 and unassessed:
                score_status = "partial_coverage"
        if trigger_states and "triggered" in trigger_states:
            triggered_case_count += 1
        if include_untriggered_cases or (trigger_states and "triggered" in trigger_states):
            scored_cases.append({
                "case_id": case_id,
                "facility_id": text_value(row.get("facility_id")),
                "risk_score": score,
                "score_status": score_status,
                "score_formula": "sum(weights of distinct triggered indicators) / sum(weights of assessable indicators)",
                "score_version": config.version,
                "triggered_indicators": [
                    indicator for indicator, state in zip(DETECTOR_ORDER, trigger_states)
                    if state == "triggered"
                ],
                "assessed_indicators": assessed,
                "not_assessed_indicators": unassessed,
                "not_applicable_indicators": [
                    indicator for indicator, state in zip(DETECTOR_ORDER, trigger_states)
                    if state == "not_applicable"
                ],
                "indicator_coverage": [
                    {"indicator": indicator, "status": state}
                    for indicator, state in zip(DETECTOR_ORDER, trigger_states)
                ],
                "indicator_reasons": reasons,
                "limitations": LIMITATIONS.copy() + ([
                    "Sebagian pemeriksaan tidak tersedia untuk klaim ini; skor dapat berubah ketika cakupan bertambah."
                ] if unassessed else []),
            })

    detector_coverage = []
    for indicator in DETECTOR_ORDER:
        not_applicable_count = len(not_applicable_by_indicator[indicator])
        triggered_ids = {
            case_id for case_id, case_reasons in reasons_by_case.items()
            if indicator in case_reasons
        }
        # A positive finding remains an assessed result even when the detector
        # also marks that case's wider search neighborhood incomplete.
        unassessed_ids = unassessed_by_indicator[indicator] - triggered_ids - not_applicable_by_indicator[indicator]
        unassessed_count = len(unassessed_ids)
        assessed_count = max(0, len(case_ids) - not_applicable_count - unassessed_count)
        detector_coverage.append({
            "indicator": indicator,
            "status": status_by_indicator[indicator],
            "assessed_case_count": assessed_count,
            "triggered_case_count": len(triggered_ids),
            "not_applicable_case_count": not_applicable_count,
            "not_assessed_case_count": unassessed_count,
            "search_truncated": search_truncated_by_indicator[indicator],
        })
    scored_cases.sort(key=lambda item: item["case_id"])
    return {
        "scoring_version": config.version,
        "score_range": [0.0, 1.0],
        "weights": {indicator: float(weight) for indicator, weight in weights.items()},
        "weight_basis": "Bobot awal sama besar; dapat diubah lewat konfigurasi; belum dikalibrasi atau disahkan ahli domain.",
        "detector_coverage": detector_coverage,
        "cases": scored_cases,
        "case_detail_scope": "all_cases" if include_untriggered_cases else "triggered_cases_only",
        "assessable_case_count": assessable_case_count,
        "triggered_case_count": triggered_case_count,
        "partial_group_membership": partial_group_notes,
        "unassessable_case_count": unassessable_case_count,
        "limitations": LIMITATIONS.copy(),
    }
