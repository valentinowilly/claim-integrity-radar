"""Exact-match repeat billing candidate indicator."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from app.analytics.normalization import normalize_amount, normalize_date, normalize_text
from app.analytics.records import validate_case_records


INDICATOR = "repeat_billing_candidate"
SIGNATURE_FIELDS = (
    "participant_token",
    "service_date",
    "province_code",
    "municipality_code",
    "facility_ownership",
    "facility_type",
    "facility_class",
    "admission_diagnosis",
    "primary_diagnosis",
    "claim_group",
    "procedure_code",
    "billed_amount",
)
DATE_FIELDS = {"service_date"}
AMOUNT_FIELDS = {"billed_amount"}
LIMITATIONS = [
    "Kecocokan atribut adalah kandidat pemeriksaan, bukan bukti tagihan ganda atau fraud.",
    "Kunjungan atau prosedur berulang yang sah dapat menghasilkan signature identik.",
    "Exact-match dapat melewatkan variasi pencatatan; aturan kode dan field belum divalidasi terhadap skema sumber.",
]


def _normalize_field(field: str, value: Any) -> str | Decimal | None:
    if field in DATE_FIELDS:
        return normalize_date(value)
    if field in AMOUNT_FIELDS:
        return normalize_amount(value)
    return normalize_text(value)


def detect_repeat_billing_candidates(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Group complete exact signatures repeated at least twice.

    Input rows must use the canonical field names documented in
    ``docs/analytics-spec.md``. Participant tokens are only compared internally
    and are never included in returned values.
    """
    validated = validate_case_records(records)
    grouped: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    ineligible: list[dict[str, Any]] = []

    for case_id, record in validated:
        values = tuple(_normalize_field(field, record.get(field)) for field in SIGNATURE_FIELDS)
        missing = [field for field, value in zip(SIGNATURE_FIELDS, values) if value is None]
        if missing:
            ineligible.append({
                "case_id": case_id,
                "reason": "Signature tidak lengkap atau mengandung nilai tidak valid.",
                "missing_attributes": missing,
            })
            continue
        grouped[values].append(case_id)

    candidate_case_groups = [
        sorted(case_ids)
        for case_ids in grouped.values()
        if len(case_ids) >= 2
    ]
    candidate_case_groups.sort(key=tuple)

    candidates = []
    for number, case_ids in enumerate(candidate_case_groups, start=1):
        candidates.append({
            "group_id": f"repeat-billing-{number:04d}",
            "case_ids": case_ids,
            "candidate_record_count": len(case_ids),
            "matched_attributes": list(SIGNATURE_FIELDS),
            "reason": (
                f"{len(case_ids)} record memiliki nilai exact-match pada seluruh "
                "atribut signature repeat billing; nilai signature tidak ditampilkan. "
                "Pola ini memerlukan peninjauan auditor dan bukan bukti fraud."
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
