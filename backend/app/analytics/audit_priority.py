"""Transparent audit-effort estimate and proposal-formula priority queue."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Any

from app.analytics.detector_utils import nonnegative_decimal, text_value, valid_records
from app.analytics.risk_scoring import DETECTOR_ORDER


PRIORITY_VERSION = "audit-priority-v1-synthetic-assumption"
LIMITATIONS = [
    "Prioritas adalah indeks pengurutan prototipe, bukan prediksi kerugian atau probabilitas fraud.",
    "Unit fasilitas hanya valid untuk generator eksperimen; ID fasilitas BPJS belum diverifikasi.",
    "Estimasi jumlah berkas adalah asumsi sampling dan bukan pengukuran waktu kerja atau standar operasional.",
]


@dataclass(frozen=True)
class AuditEffortConfig:
    files_per_claim: Decimal = Decimal("1")
    max_files_per_unit: int | None = 20
    max_case_ids_in_output: int = 50
    max_reasons_in_output: int = 30

    def __post_init__(self) -> None:
        try:
            value = Decimal(str(self.files_per_claim))
        except InvalidOperation as error:
            raise ValueError("files_per_claim tidak valid") from error
        if not value.is_finite() or value <= 0:
            raise ValueError("files_per_claim harus positif dan finite")
        if self.max_files_per_unit is not None and self.max_files_per_unit < 1:
            raise ValueError("max_files_per_unit harus positif atau None")
        if self.max_case_ids_in_output < 1 or self.max_reasons_in_output < 1:
            raise ValueError("Batas output harus positif")


def _coverage_for_unit(scored_cases: list[Mapping[str, Any]], top_coverage: Mapping[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for indicator in DETECTOR_ORDER:
        states = []
        for case in scored_cases:
            for coverage in case.get("indicator_coverage", []):
                if isinstance(coverage, Mapping) and coverage.get("indicator") == indicator:
                    states.append(coverage.get("status"))
                    break
        assessed = sum(state in {"triggered", "not_triggered"} for state in states)
        not_assessed = len(states) - assessed
        status = top_coverage.get(indicator, "unavailable")
        if status == "unavailable":
            unit_status = "unavailable"
        elif status == "partial" or not_assessed:
            unit_status = "partial"
        elif assessed == 0:
            unit_status = "unavailable"
        else:
            unit_status = "available"
        rows.append({
            "indicator": indicator,
            "status": unit_status,
            "assessed_claim_count": assessed,
            "not_assessed_claim_count": not_assessed,
            "triggered_claim_count": sum(state == "triggered" for state in states),
        })
    return rows


def build_audit_priority_queue(
    records: Sequence[Mapping[str, Any]],
    scoring_result: Mapping[str, Any],
    config: AuditEffortConfig | None = None,
) -> dict[str, Any]:
    """Aggregate signaled claims by synthetic facility and apply proposal formula.

    Unit risk score is the maximum assessable per-claim rule index among
    signaled claims in that unit. Claim value is summed once per unique signaled
    claim. Effort estimates distinct record files and is capped transparently.
    """
    config = config or AuditEffortConfig()
    rows = valid_records(records)
    record_by_id = {case_id: row for case_id, row in rows}
    raw_cases = scoring_result.get("cases")
    if not isinstance(raw_cases, (list, tuple)):
        raise ValueError("scoring_result.cases harus berupa daftar hasil skor")
    score_by_id: dict[str, Mapping[str, Any]] = {}
    for item in raw_cases:
        if not isinstance(item, Mapping) or not isinstance(item.get("case_id"), str):
            raise ValueError("Setiap hasil skor harus memiliki case_id")
        if item["case_id"] in score_by_id or item["case_id"] not in record_by_id:
            raise ValueError("Hasil skor berisi case_id duplikat atau tidak dikenal")
        score_by_id[item["case_id"]] = item

    grouped: dict[str, set[str]] = defaultdict(set)
    unassigned: list[str] = []
    for case_id, item in score_by_id.items():
        if not item.get("triggered_indicators"):
            continue
        facility_id = text_value(record_by_id[case_id].get("facility_id"))
        if facility_id is None:
            unassigned.append(case_id)
        else:
            grouped[facility_id].add(case_id)

    top_coverage = {
        item.get("indicator"): item.get("status", "unavailable")
        for item in scoring_result.get("detector_coverage", [])
        if isinstance(item, Mapping) and isinstance(item.get("indicator"), str)
    }
    partial_group_notes = scoring_result.get("partial_group_membership", [])
    queue: list[dict[str, Any]] = []
    hidden_sort_values: dict[str, Decimal | None] = {}

    for facility_id in sorted(grouped):
        triggered_ids = sorted(grouped[facility_id])
        case_scores = [score_by_id[case_id] for case_id in triggered_ids]
        assessable_scores = [
            (float(item["risk_score"]), item["case_id"])
            for item in case_scores
            if isinstance(item.get("risk_score"), (int, float)) and not isinstance(item.get("risk_score"), bool)
        ]
        if assessable_scores:
            max_score = max(score for score, _ in assessable_scores)
            anchor_case_id = min(case_id for score, case_id in assessable_scores if score == max_score)
            unit_score = max_score
        else:
            anchor_case_id = triggered_ids[0]
            unit_score = None

        total_value = Decimal(0)
        valid_value_count = 0
        invalid_value_count = 0
        for case_id in triggered_ids:
            amount = nonnegative_decimal(record_by_id[case_id].get("billed_amount"))
            if amount is None:
                invalid_value_count += 1
            else:
                total_value += amount
                valid_value_count += 1
        value_status = "unavailable" if valid_value_count == 0 else (
            "partial" if invalid_value_count else "available"
        )

        effort_multiplier = Decimal(str(config.files_per_claim))
        raw_effort = int((Decimal(len(triggered_ids)) * effort_multiplier).to_integral_value(rounding=ROUND_CEILING))
        raw_effort = max(raw_effort, 1)
        capped = config.max_files_per_unit is not None and raw_effort > config.max_files_per_unit
        effort_files = min(raw_effort, config.max_files_per_unit) if config.max_files_per_unit is not None else raw_effort
        effort_status = "capped" if capped else "estimated"

        priority_index: float | None = None
        priority_decimal: Decimal | None = None
        if unit_score is not None and valid_value_count and effort_files > 0:
            priority_decimal = Decimal(str(round(unit_score, 6))) * total_value / Decimal(effort_files)
            priority_index = round(float(priority_decimal), 8)

        coverage = _coverage_for_unit(case_scores, top_coverage)
        coverage_partial = any(item["status"] == "partial" for item in coverage)
        unresolved_case_count = sum(
            int(note.get("unresolved_case_count", 0))
            for note in partial_group_notes
            if isinstance(note, Mapping) and facility_id in note.get("known_facility_ids", [])
        )
        group_truncated = unresolved_case_count > 0
        partial_reasons = []
        if coverage_partial:
            partial_reasons.append("Sebagian pemeriksaan indikator tidak tersedia atau cakupannya terpotong; posisi antrean dapat berubah.")
        if value_status == "partial":
            partial_reasons.append("Total nilai hanya menjumlahkan klaim dengan billed_amount valid; nilai hilang/tidak valid tidak diganti.")
        if value_status == "unavailable":
            partial_reasons.append("Tidak ada billed_amount valid pada klaim terindikasi; indeks prioritas tidak dihitung.")
        if capped:
            partial_reasons.append("Estimasi berkas dibatasi konfigurasi; metode pemilihan berkas sampel belum ditetapkan.")
        if group_truncated:
            partial_reasons.append(f"Keanggotaan grup indikator terpotong; sedikitnya {unresolved_case_count} klaim belum dipetakan.")

        all_reasons: list[dict[str, Any]] = []
        for case_id in triggered_ids:
            item = score_by_id[case_id]
            for reason in item.get("indicator_reasons", []):
                if isinstance(reason, Mapping):
                    all_reasons.append({"case_id": case_id, **dict(reason)})
        all_reasons.sort(key=lambda item: (item["case_id"], item.get("indicator", ""), item.get("candidate_id", "")))
        triggered_indicators = sorted({
            indicator for item in case_scores for indicator in item.get("triggered_indicators", [])
            if isinstance(indicator, str)
        })
        item = {
            "unit_id": f"synthetic-audit-unit:{facility_id}",
            "unit_kind": "synthetic_facility",
            "data_scope": "synthetic_experiment",
            "risk_score": unit_score,
            "risk_score_aggregation": "maximum per-claim risk index among signaled claims in the facility unit",
            "risk_score_version": scoring_result.get("scoring_version"),
            "triggered_indicators": triggered_indicators,
            "triggered_claim_count": len(triggered_ids),
            "triggered_case_ids": triggered_ids[:config.max_case_ids_in_output],
            "case_ids_truncated": len(triggered_ids) > config.max_case_ids_in_output,
            "tie_break_case_id": anchor_case_id,
            "claim_value": {
                "amount": f"{total_value:.2f}" if valid_value_count else None,
                "currency_unit": "synthetic billed_amount units",
                "unique_claim_count": len(triggered_ids),
                "valid_amount_claim_count": valid_value_count,
                "invalid_or_missing_claim_count": invalid_value_count,
                "status": value_status,
                "deduplicated_by_case_id": True,
            },
            "audit_effort": {
                "recommended_record_files": effort_files,
                "raw_recommended_record_files": raw_effort,
                "unit": "record files",
                "files_per_unique_signaled_claim": str(effort_multiplier),
                "max_files_per_unit": config.max_files_per_unit,
                "status": effort_status,
                "basis": "ceil(unique signaled claims × configured files per claim), then optional cap",
            },
            "priority_formula": "risk_score × known_indicated_claim_value ÷ recommended_record_files",
            "priority_index": priority_index,
            "priority_status": "not_assessable" if priority_index is None else (
                "partial" if coverage_partial or value_status == "partial" or capped or group_truncated else "available"
            ),
            "priority_components": {
                "risk_score": unit_score,
                "known_indicated_claim_value": f"{total_value:.2f}" if valid_value_count else None,
                "recommended_record_files": effort_files,
            },
            "coverage": coverage,
            "unresolved_group_case_count": unresolved_case_count,
            "indicator_reasons": all_reasons[:config.max_reasons_in_output],
            "reason_count": len(all_reasons),
            "reasons_truncated": len(all_reasons) > config.max_reasons_in_output,
            "limitations": LIMITATIONS.copy() + partial_reasons,
        }
        queue.append(item)
        hidden_sort_values[item["unit_id"]] = priority_decimal

    queue.sort(key=lambda item: (
        item["priority_index"] is None,
        -(hidden_sort_values[item["unit_id"]] or Decimal(0)),
        item["tie_break_case_id"],
    ))
    for index, item in enumerate(queue, start=1):
        item["priority_order"] = index

    return {
        "priority_version": PRIORITY_VERSION,
        "unit": "synthetic facility",
        "formula": "risk_score × unique indicated claim value ÷ estimated record-file effort",
        "sorted_by": ["priority_index desc", "tie_break_case_id asc"],
        "items": queue,
        "unassigned_triggered_case_ids": sorted(unassigned),
        "unassigned_triggered_case_count": len(unassigned),
        "limitations": LIMITATIONS.copy(),
    }
