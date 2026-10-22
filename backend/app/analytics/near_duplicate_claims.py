"""Bounded deterministic blocking search for near-duplicate claim patterns.

This is a documented alternative to MinHash/LSH. It does not use participant
tokens as features; tokens are only compared internally to require different
participants, as in the existing exact-pattern detector.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from typing import Any

from app.analytics.detector_utils import date_value, nonnegative_decimal, text_value, valid_records


INDICATOR = "near_duplicate_claim_candidate"
NEAR_FIELDS = (
    "service_date", "province_code", "municipality_code", "facility_ownership",
    "facility_type", "facility_class", "admission_diagnosis", "primary_diagnosis",
    "claim_group", "procedure_code", "billed_amount",
)
BLOCKING_FIELDS = (
    ("service_date", "municipality_code", "primary_diagnosis"),
    ("service_date", "municipality_code", "claim_group"),
    ("service_date", "province_code", "admission_diagnosis"),
)
LIMITATIONS = [
    "Near-match adalah sinyal pola untuk ditinjau, bukan bukti cloning, fraud, atau layanan fiktif.",
    "Blocking dapat melewatkan pasangan yang berbeda pada semua atribut pemblokir.",
    "Field administrasi bukan ID fasilitas; kecocokan tidak memastikan fasilitas yang sama.",
    "Ambang, toleransi biaya, dan batas pencarian adalah parameter eksperimen, bukan aturan BPJS.",
]


@dataclass(frozen=True)
class NearDuplicateConfig:
    min_similarity: float = 0.8
    min_compared_attributes: int = 9
    amount_tolerance: Decimal = Decimal("1.00")
    max_block_size: int = 100
    max_pair_comparisons: int = 5000
    max_candidates: int = 500

    def __post_init__(self) -> None:
        if not 0 < self.min_similarity <= 1:
            raise ValueError("min_similarity harus berada pada (0, 1]")
        if self.min_compared_attributes < 1 or self.max_block_size < 2:
            raise ValueError("min_compared_attributes dan max_block_size tidak valid")
        if self.amount_tolerance < 0 or self.max_pair_comparisons < 1 or self.max_candidates < 1:
            raise ValueError("toleransi dan batas pencarian harus non-negatif/positif")


def _field_value(field: str, value: Any) -> Any:
    if field == "service_date":
        parsed = date_value(value)
        return parsed.isoformat() if parsed else None
    if field == "billed_amount":
        return nonnegative_decimal(value)
    return text_value(value)


def detect_near_duplicate_claims(
    records: Sequence[Mapping[str, Any]],
    config: NearDuplicateConfig | None = None,
) -> dict[str, Any]:
    """Compare bounded candidate pairs from deterministic attribute blocks."""
    config = config or NearDuplicateConfig()
    validated = valid_records(records)
    normalized: dict[str, dict[str, Any]] = {}
    participants: dict[str, str | None] = {}
    ineligible: list[dict[str, str]] = []
    for case_id, row in validated:
        normalized[case_id] = {field: _field_value(field, row.get(field)) for field in NEAR_FIELDS}
        participants[case_id] = text_value(row.get("participant_token"))

    blocks: dict[tuple[int, tuple[Any, ...]], list[str]] = defaultdict(list)
    for case_id in sorted(normalized):
        values = normalized[case_id]
        for block_number, fields in enumerate(BLOCKING_FIELDS):
            block_values = tuple(values[field] for field in fields)
            if all(value is not None for value in block_values):
                blocks[(block_number, block_values)].append(case_id)

    pair_keys: set[tuple[str, str]] = set()
    comparisons = 0
    large_blocks_chain_compared = 0
    search_truncated = False
    for block_key in sorted(blocks, key=lambda item: (item[0], tuple(str(value) for value in item[1]))):
        case_ids = sorted(set(blocks[block_key]))
        if len(case_ids) < 2:
            continue
        if len(case_ids) > config.max_block_size:
            pairs = zip(case_ids, case_ids[1:])
            large_blocks_chain_compared += 1
        else:
            pairs = combinations(case_ids, 2)
        for left, right in pairs:
            pair = (left, right)
            if pair in pair_keys:
                continue
            if comparisons >= config.max_pair_comparisons:
                search_truncated = True
                break
            pair_keys.add(pair)
            comparisons += 1
        if search_truncated:
            break

    candidates: list[dict[str, Any]] = []
    for left, right in sorted(pair_keys):
        left_participant, right_participant = participants[left], participants[right]
        if left_participant is None or right_participant is None or left_participant == right_participant:
            continue
        matched: list[str] = []
        differing: list[str] = []
        comparable = 0
        for field in NEAR_FIELDS:
            left_value, right_value = normalized[left][field], normalized[right][field]
            if left_value is None or right_value is None:
                continue
            comparable += 1
            if field == "billed_amount":
                same = abs(left_value - right_value) <= config.amount_tolerance
            else:
                same = left_value == right_value
            (matched if same else differing).append(field)
        if comparable < config.min_compared_attributes:
            continue
        similarity = len(matched) / comparable
        if similarity < config.min_similarity:
            continue
        candidates.append({
            "candidate_id": f"near-duplicate:{left}:{right}",
            "indicator": INDICATOR,
            "scope": "claim_pair",
            "case_ids": [left, right],
            "matched_attributes": matched,
            "differing_attributes": differing,
            "compared_attribute_count": comparable,
            "matched_attribute_count": len(matched),
            "similarity_ratio": round(similarity, 4),
            "reason": (
                f"Dua klaim dari peserta berbeda cocok pada {len(matched)} dari "
                f"{comparable} atribut yang dapat dibandingkan; atribut berbeda "
                f"{', '.join(differing) if differing else 'tidak ada'}. Nilai signature tidak ditampilkan."
            ),
            "limitations": LIMITATIONS.copy(),
        })
        if len(candidates) >= config.max_candidates:
            search_truncated = True
            break

    ineligible = [
        {"case_id": case_id, "reason": "Token peserta tidak tersedia untuk mensyaratkan peserta berbeda."}
        for case_id in sorted(normalized) if participants[case_id] is None
    ]
    return {
        "indicator": INDICATOR,
        "input_record_count": len(validated),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "ineligible_cases": ineligible,
        "pair_comparisons": comparisons,
        "large_blocks_chain_compared": large_blocks_chain_compared,
        "search_truncated": search_truncated,
        "search_parameters": {
            "blocking_fields": [list(fields) for fields in BLOCKING_FIELDS],
            "min_similarity": config.min_similarity,
            "min_compared_attributes": config.min_compared_attributes,
            "amount_tolerance": str(config.amount_tolerance),
            "max_block_size": config.max_block_size,
            "max_pair_comparisons": config.max_pair_comparisons,
            "max_candidates": config.max_candidates,
        },
        "limitations": LIMITATIONS.copy(),
    }
