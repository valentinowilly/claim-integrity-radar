"""Coordinate the implemented rule detectors over the active demo source."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from app.analytics.repeat_billing import detect_repeat_billing_candidates
from app.analytics.similar_claim_pattern import detect_similar_claim_patterns
from app.data_sources.synthetic import get_synthetic_records


DATA_SOURCE = {"kind": "synthetic", "label": "synthetic_demo"}
INDICATORS = (
    {
        "code": "repeat_billing_candidate",
        "name": "Repeat billing candidate",
        "definition": (
            "Exact match atas signature lengkap pada peserta, tanggal layanan, "
            "atribut klaim, prosedur, dan biaya; minimal dua record."
        ),
        "limitations": [
            "Kecocokan adalah kandidat tinjauan, bukan bukti tagihan ganda atau fraud.",
            "Layanan berulang yang sah dan variasi skema sumber dapat memengaruhi hasil.",
        ],
    },
    {
        "code": "similar_claim_pattern_candidate",
        "name": "Similar claim-pattern candidate",
        "definition": (
            "Exact match pola klaim pada minimal dua peserta berbeda; prosedur "
            "dipakai bila tersedia dan signature parsial ditandai terpisah."
        ),
        "limitations": [
            "Pola serupa bukan bukti cloning, fraud, atau layanan fiktif.",
            "Kategori/wilayah bukan ID fasilitas; pola layanan lazim dapat cocok sah.",
            "Signature parsial lebih rentan false positive.",
        ],
    },
)
PLANNED_INDICATORS = [
    {
        "code": "billing_amount_anomaly",
        "name": "Billing amount anomaly",
        "status": "planned",
        "definition": "Belum diimplementasikan; perlu populasi pembanding dan validasi ahli.",
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
    {
        "code": "temporal_pattern_change",
        "name": "Temporal pattern change",
        "status": "planned",
        "definition": "Belum diimplementasikan; memerlukan periode dasar dan aturan perubahan volume.",
    },
]


def _reason(indicator: str, group: Mapping[str, Any]) -> dict[str, Any]:
    attrs = ", ".join(group["matched_attributes"])
    evidence = [
        f"Kelompok kandidat: {group['group_id']}.",
        f"Jumlah record kandidat: {group['candidate_record_count']}.",
        f"Atribut yang cocok: {attrs}.",
    ]
    if "distinct_participant_count" in group:
        evidence.append(
            f"Jumlah peserta berbeda: {group['distinct_participant_count']}."
        )
    if "mode" in group:
        evidence.append(f"Mode signature: {group['mode']}.")
    return {
        "indicator": indicator,
        "summary": group["reason"],
        "evidence": evidence,
        "limitations": list(group["limitations"]),
    }


def build_analytics_snapshot(
    records: Sequence[Mapping[str, Any]] | None = None,
    period_from: date | None = None,
    period_to: date | None = None,
) -> dict[str, Any]:
    """Run both rule detectors and return only minimized, explainable output."""
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

    repeat_result = detect_repeat_billing_candidates(source_records)
    similar_result = detect_similar_claim_patterns(source_records)
    results = {
        "repeat_billing_candidate": repeat_result,
        "similar_claim_pattern_candidate": similar_result,
    }
    candidates: dict[str, dict[str, Any]] = {}
    indicator_summaries = []
    eligible_union: set[str] = set()

    for definition in INDICATORS:
        code = definition["code"]
        result = results[code]
        ineligible_ids = {entry["case_id"] for entry in result["ineligible_cases"]}
        eligible_ids = {record["case_id"] for record in source_records} - ineligible_ids
        eligible_union.update(eligible_ids)
        candidate_ids: set[str] = set()
        groups = result["candidate_groups"]

        for group in groups:
            for case_id in group["case_ids"]:
                candidate_ids.add(case_id)
                item = candidates.setdefault(
                    case_id,
                    {
                        "case_id": case_id,
                        "risk_level": None,
                        "risk_score": None,
                        "indicators": [],
                        "status": "pending",
                        "detected_at": None,
                        "reasons": [],
                        "limitations": [],
                        "review": {"decision": None, "reviewed_at": None},
                    },
                )
                if code not in item["indicators"]:
                    item["indicators"].append(code)
                item["reasons"].append(_reason(code, group))
                for limitation in group["limitations"]:
                    if limitation not in item["limitations"]:
                        item["limitations"].append(limitation)

        indicator_summaries.append(
            {
                **definition,
                "candidate_count": len(candidate_ids),
                "candidate_group_count": len(groups),
                "eligible_count": len(eligible_ids),
            }
        )

    return {
        "data_source": dict(DATA_SOURCE),
        "records_considered": len(source_records),
        "records_eligible": len(eligible_union),
        "indicators": indicator_summaries,
        "cases": candidates,
    }
