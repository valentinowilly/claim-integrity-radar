"""Rule-based completeness checks for recorded synthetic evidence metadata."""

from collections.abc import Mapping, Sequence
from typing import Any

from app.analytics.detector_utils import text_value, valid_records


INDICATOR = "supporting_evidence_completeness_candidate"
DEFAULT_REQUIRED_EVIDENCE: dict[str, tuple[str, ...]] = {
    "physiotherapy": ("therapy_session_log", "clinical_note"),
    "synthetic_supported_action": ("procedure_order", "clinical_note"),
    "synthetic_mixed_action": ("procedure_order", "clinical_note"),
    # Special drugs and devices billed on top of the INA-CBG (FKL33-FKL46): the order and the proof of dispensing.
    "special_drug": ("prescription", "dispensing_record"),
    "special_device": ("device_order", "delivery_record"),
}
LIMITATIONS = [
    "Aturan bukti adalah aturan skenario sintetis dan belum divalidasi ahli domain.",
    "Bukti yang tidak tercatat atau status pencatatan yang tidak diketahui tidak diperlakukan sebagai bukti tidak ada.",
    "Bukti pendukung yang tidak tersedia pada record tidak membuktikan layanan tidak diberikan atau fraud.",
]


def detect_evidence_completeness(
    records: Sequence[Mapping[str, Any]],
    required_evidence_by_service: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Find missing expected evidence only when an evidence inventory is recorded.

    ``supporting_evidence_recording_status='recorded'`` plus an explicit list
    (including an empty list) means the inventory was checked. Missing list,
    ``not_recorded``, or unsupported service rule is treated as unassessed.
    """
    rules = required_evidence_by_service or DEFAULT_REQUIRED_EVIDENCE
    validated = valid_records(records)
    candidates: list[dict[str, Any]] = []
    unassessed: list[dict[str, str]] = []
    ineligible: list[dict[str, str]] = []
    not_applicable: list[dict[str, str]] = []

    for case_id, row in validated:
        service_type = text_value(row.get("service_type"))
        required = rules.get(service_type) if service_type else None
        if required is None:
            not_applicable.append({"case_id": case_id, "reason": "Belum ada aturan bukti untuk jenis layanan ini."})
            continue
        status = text_value(row.get("supporting_evidence_recording_status"))
        if status == "not_recorded":
            unassessed.append({"case_id": case_id, "reason": "Inventaris bukti belum tercatat; ketiadaan bukti tidak dapat disimpulkan."})
            continue
        if status != "recorded":
            ineligible.append({"case_id": case_id, "reason": "Status pencatatan bukti tidak valid atau tidak tersedia."})
            continue

        raw_required = row.get("supporting_evidence_required")
        raw_present = row.get("supporting_evidence_types")
        if not isinstance(raw_required, (list, tuple)) or not isinstance(raw_present, (list, tuple)):
            ineligible.append({"case_id": case_id, "reason": "Daftar bukti wajib atau bukti tercatat tidak tersedia dalam format yang valid."})
            continue
        required_values = [text_value(value) for value in raw_required]
        present_values = [text_value(value) for value in raw_present]
        if any(value is None for value in required_values + present_values):
            ineligible.append({"case_id": case_id, "reason": "Daftar bukti berisi nilai kosong atau format tidak valid."})
            continue
        required_set = set(required_values)  # type: ignore[arg-type]
        expected_set = set(required)
        if required_set != expected_set:
            ineligible.append({"case_id": case_id, "reason": "Aturan bukti pada record tidak konsisten dengan konfigurasi jenis layanan."})
            continue
        present_set = set(present_values)  # type: ignore[arg-type]
        presence_flag = row.get("supporting_evidence_present")
        if not isinstance(presence_flag, bool) or presence_flag != bool(present_set):
            ineligible.append({"case_id": case_id, "reason": "Flag keberadaan bukti tidak konsisten dengan inventaris bukti."})
            continue
        missing = sorted(expected_set - present_set)
        if not missing:
            continue
        candidates.append({
            "candidate_id": f"evidence:{case_id}",
            "indicator": INDICATOR,
            "scope": "claim",
            "case_id": case_id,
            "missing_evidence": missing,
            "recorded_evidence": sorted(present_set),
            "rule": {"service_type": service_type, "required_evidence": sorted(expected_set)},
            "reason": (
                f"Inventaris bukti berstatus tercatat, tetapi {', '.join(missing)} "
                f"tidak tercantum untuk aturan sintetis jenis layanan {service_type}."
            ),
            "limitations": LIMITATIONS.copy(),
        })

    candidates.sort(key=lambda item: item["case_id"])
    return {
        "indicator": INDICATOR,
        "input_record_count": len(validated),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "unassessed_cases": sorted(unassessed, key=lambda item: item["case_id"]),
        "ineligible_cases": sorted(ineligible, key=lambda item: item["case_id"]),
        "not_applicable_cases": sorted(not_applicable, key=lambda item: item["case_id"]),
        "active_rules": {service: list(required) for service, required in sorted(rules.items())},
        "limitations": LIMITATIONS.copy(),
    }
