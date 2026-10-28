"""Repeated-service pattern indicator (screening signal for possible Repeat Billing).

Official Repeat Billing is a claim for a case that was already billed and paid. No
supported source carries billing or payment status per visit, so a match is reported
as a repeated-service pattern and never as established Repeat Billing.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from app.analytics.records import validate_case_records
from app.analytics.repeat_definitions import REPEAT_SERVICE_KEY, RepeatDefinition, group_repeat_patterns, normalize_value

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
# Source profiles that withhold a verified pre-verification amount (for example
# the BPJS FKRTL sample, where FKL47 semantics are unconfirmed and FKL48 is
# post-verification) use the same exact signature without the amount field.
AMOUNT_WITHHELD_SIGNATURE_FIELDS = tuple(field for field in SIGNATURE_FIELDS if field != "billed_amount")
# Primary FKRTL profile (decision from the whole-file reconciliation, see
# docs/detection-semantics.md): the repeat_service_v1 key gates candidates; the
# region/facility-category fields and admission diagnosis are not a facility
# identity, so they are compared only as reviewer context and never decide
# eligibility or hide a candidate.
REPEAT_SERVICE_PROFILE = "repeat-service-v1"
REPEAT_CONTEXT_FIELDS = tuple(field for field in AMOUNT_WITHHELD_SIGNATURE_FIELDS if field not in REPEAT_SERVICE_KEY)
SIGNATURE_PROFILES = {
    "repeat-billing-exact-v1": SIGNATURE_FIELDS,
    "repeat-visit-exact-no-amount-v1": AMOUNT_WITHHELD_SIGNATURE_FIELDS,
    REPEAT_SERVICE_PROFILE: REPEAT_SERVICE_KEY,
}
PROFILE_CONTEXT_FIELDS = {REPEAT_SERVICE_PROFILE: REPEAT_CONTEXT_FIELDS}
# Machine-readable interpretation carried by every result and candidate so the API
# and UI cannot present a pattern as a billing finding.
SIGNAL_TYPE = "repeated_service_pattern"
BILLING_STATUS_EVIDENCE = "not_available"
INTERPRETATION = {
    "signal_type": SIGNAL_TYPE,
    "repeat_billing": "not_established",
    "billing_status_evidence": BILLING_STATUS_EVIDENCE,
}
LIMITATIONS = [
    "Kecocokan atribut adalah kandidat pemeriksaan, bukan bukti tagihan ganda atau fraud.",
    "Sumber tidak memuat status penagihan atau pembayaran per kunjungan; pola ini tidak menunjukkan bahwa klaim sebelumnya sudah ditagih atau dibayar.",
    "Kunjungan atau prosedur berulang yang sah dapat menghasilkan signature identik.",
    "Exact-match dapat melewatkan variasi pencatatan; aturan kode dan field belum divalidasi terhadap skema sumber.",
]


def detect_repeat_billing_candidates(
    records: Sequence[Mapping[str, Any]],
    signature_fields: Sequence[str] = SIGNATURE_FIELDS,
) -> dict[str, Any]:
    """Group complete exact signatures repeated at least twice.

    Input rows must use the canonical field names documented in
    ``docs/analytics-spec.md``. Participant tokens are only compared internally
    and are never included in returned values. ``signature_fields`` must be one
    of ``SIGNATURE_PROFILES``.
    """
    signature_fields = tuple(signature_fields)
    if signature_fields not in SIGNATURE_PROFILES.values():
        raise ValueError("Unknown repeat signature profile.")
    with_amount = "billed_amount" in signature_fields
    profile = next(name for name, fields in SIGNATURE_PROFILES.items() if fields == signature_fields)
    context_fields = PROFILE_CONTEXT_FIELDS.get(profile, ())
    # Grouping is defined once in repeat_definitions; missing key values make a
    # record ineligible rather than matching each other. Context fields are
    # never part of the key.
    grouping = group_repeat_patterns(records, RepeatDefinition(name=profile, key_fields=signature_fields))
    by_case = dict(validate_case_records(records)) if context_fields else {}
    ineligible = [
        {
            "case_id": case_id,
            "reason": "Signature tidak lengkap atau mengandung nilai tidak valid.",
            "missing_attributes": missing,
        }
        for case_id, missing in grouping.ineligible
    ]
    candidate_case_groups = grouping.groups

    candidates = []
    for number, case_ids in enumerate(candidate_case_groups, start=1):
        if context_fields:
            candidates.append(_context_candidate(number, case_ids, signature_fields, context_fields, by_case))
            continue
        candidates.append({
            "group_id": f"repeat-billing-{number:04d}",
            "case_ids": case_ids,
            "candidate_record_count": len(case_ids),
            "matched_attributes": list(signature_fields),
            "interpretation": SIGNAL_TYPE,
            "billing_status_evidence": BILLING_STATUS_EVIDENCE,
            "reason": (
                f"{len(case_ids)} record memiliki nilai exact-match pada seluruh "
                "atribut signature pola layanan berulang; nilai signature tidak ditampilkan. "
                "Pola ini memerlukan peninjauan auditor dan bukan bukti tagihan ganda atau fraud."
            ) if with_amount else (
                f"{len(case_ids)} kunjungan berbeda dari peserta yang sama memiliki tanggal datang, "
                "wilayah dan kategori fasilitas, diagnosis masuk/primer, kode INA-CBG, dan prosedur "
                "yang identik; nilai tidak ditampilkan dan nilai tagih tidak dibandingkan. "
                "Periksa apakah kunjungan ini episode terpisah yang sah (mis. rujukan atau layanan "
                "berbeda pada hari sama), cocokkan tanggal pulang, resume medis, dan berkas klaim. "
                "Ini sinyal tinjauan, bukan bukti tagihan ganda atau fraud."
            ),
            "limitations": LIMITATIONS.copy(),
        })

    return {
        "indicator": INDICATOR,
        "signature_profile": profile,
        "interpretation": dict(INTERPRETATION),
        "input_record_count": grouping.input_rows,
        "candidate_groups": candidates,
        "ineligible_cases": ineligible,
    }


def _context_candidate(number: int, case_ids: list[str], key_fields: Sequence[str],
                       context_fields: Sequence[str], by_case: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Core-key candidate with context compared by field name only (values are never returned)."""
    matched, differing, unavailable = [], [], []
    for field in context_fields:
        values = [normalize_value(field, by_case[case_id].get(field)) for case_id in case_ids]
        if any(value is None for value in values):
            unavailable.append(field)
        elif len(set(values)) > 1:
            differing.append(field)
        else:
            matched.append(field)
    context = (
        "Wilayah, kategori fasilitas, dan diagnosis masuk juga sama." if not differing and not unavailable
        else "Sebagian atribut konteks berbeda atau tidak tersedia (lihat daftar atribut); ini konteks peninjauan, "
             "bukan alasan menyingkirkan kandidat, dan field kategori bukan identitas fasilitas."
    )
    return {
        "group_id": f"repeat-billing-{number:04d}",
        "case_ids": case_ids,
        "candidate_record_count": len(case_ids),
        "matched_attributes": [*key_fields, *matched],
        "differing_attributes": differing,
        "context_unavailable_attributes": unavailable,
        "interpretation": SIGNAL_TYPE,
        "billing_status_evidence": BILLING_STATUS_EVIDENCE,
        "reason": (
            f"{len(case_ids)} kunjungan berbeda dari peserta yang sama memiliki tanggal datang, diagnosis primer, "
            "kode INA-CBG, dan prosedur yang identik (definisi repeat_service_v1); nilai tidak ditampilkan dan "
            f"nilai tagih tidak dibandingkan. {context} Periksa apakah kunjungan ini episode terpisah yang sah "
            "(mis. rujukan atau layanan berbeda pada hari sama), cocokkan tanggal pulang, resume medis, dan berkas "
            "klaim. Ini sinyal tinjauan, bukan bukti tagihan ganda atau fraud."
        ),
        "limitations": LIMITATIONS.copy(),
    }
