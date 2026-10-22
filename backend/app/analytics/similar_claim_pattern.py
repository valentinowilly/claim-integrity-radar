"""Exact-match claim-pattern candidate indicator across distinct participants."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from app.analytics.normalization import normalize_amount, normalize_date, normalize_text
from app.analytics.records import validate_case_records


INDICATOR = "similar_claim_pattern_candidate"
BASE_SIGNATURE_FIELDS = (
    "service_date",
    "province_code",
    "municipality_code",
    "facility_ownership",
    "facility_type",
    "facility_class",
    "admission_diagnosis",
    "primary_diagnosis",
    "claim_group",
    "billed_amount",
)
COMPLETE_SIGNATURE_FIELDS = BASE_SIGNATURE_FIELDS + ("procedure_code",)
LIMITATIONS = [
    "Pola serupa bukan bukti cloning, fraud, atau layanan fiktif.",
    "Field wilayah dan karakteristik fasilitas bukan ID fasilitas; skema yang tersedia belum memastikan fasilitas yang sama.",
    "Protokol dan kombinasi layanan yang lazim dapat cocok secara sah.",
    "Signature parsial tanpa prosedur lebih rentan false positive; exact-match juga dapat melewatkan variasi pencatatan.",
]


def _normalized(field: str, value: Any) -> str | Decimal | None:
    if field == "service_date":
        return normalize_date(value)
    if field == "billed_amount":
        return normalize_amount(value)
    return normalize_text(value)


def detect_similar_claim_patterns(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Find complete and procedure-missing exact patterns across participants.

    Participant tokens are required for comparison but are not part of the
    pattern signature and never appear in the result.
    """
    validated = validate_case_records(records)
    # key -> case IDs and private participant set; neither signature values nor
    # participant tokens are copied into the returned structure.
    grouped: dict[tuple[str, tuple[Any, ...]], dict[str, Any]] = defaultdict(
        lambda: {"case_ids": [], "participants": set()}
    )
    ineligible: list[dict[str, Any]] = []

    for case_id, record in validated:
        participant = normalize_text(record.get("participant_token"))
        if participant is None:
            ineligible.append({
                "case_id": case_id,
                "reason": "Token peserta kosong atau tidak valid untuk membandingkan peserta berbeda.",
                "missing_attributes": ["participant_token"],
            })
            continue

        base_values = tuple(_normalized(field, record.get(field)) for field in BASE_SIGNATURE_FIELDS)
        missing_base = [
            field for field, value in zip(BASE_SIGNATURE_FIELDS, base_values)
            if value is None
        ]
        if missing_base:
            ineligible.append({
                "case_id": case_id,
                "reason": "Atribut dasar pola tidak lengkap atau tidak valid.",
                "missing_attributes": missing_base,
            })
            continue

        procedure = normalize_text(record.get("procedure_code"))
        if procedure is None:
            mode = "procedure_missing"
            signature = base_values
        else:
            mode = "complete"
            signature = base_values + (procedure,)

        group = grouped[(mode, signature)]
        group["case_ids"].append(case_id)
        group["participants"].add(participant)

    candidate_groups = []
    for (mode, _signature), group in grouped.items():
        case_ids = sorted(group["case_ids"])
        participants = group["participants"]
        if len(case_ids) < 2 or len(participants) < 2:
            continue
        fields = (
            COMPLETE_SIGNATURE_FIELDS if mode == "complete"
            else BASE_SIGNATURE_FIELDS
        )
        candidate_groups.append({
            "mode": mode,
            "case_ids": case_ids,
            "candidate_record_count": len(case_ids),
            "distinct_participant_count": len(participants),
            "matched_attributes": list(fields),
        })

    candidate_groups.sort(key=lambda group: (group["mode"], tuple(group["case_ids"])))
    candidates = []
    for number, group in enumerate(candidate_groups, start=1):
        mode_label = "signature lengkap" if group["mode"] == "complete" else "signature parsial tanpa kode prosedur"
        candidates.append({
            "group_id": f"similar-pattern-{number:04d}",
            **group,
            "reason": (
                f"{group['candidate_record_count']} record dari "
                f"{group['distinct_participant_count']} peserta berbeda memiliki {mode_label} "
                "yang cocok exact-match; nilai signature dan token peserta tidak ditampilkan. "
                "Kecocokan ini hanya sinyal untuk ditinjau, bukan bukti cloning atau fraud."
            ),
            "limitations": LIMITATIONS.copy(),
        })

    ineligible.sort(key=lambda item: item["case_id"])
    return {
        "indicator": INDICATOR,
        "input_record_count": len(validated),
        "candidate_groups": candidates,
        "ineligible_cases": ineligible,
    }
