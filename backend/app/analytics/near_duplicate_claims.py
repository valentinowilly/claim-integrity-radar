"""Bounded deterministic blocking search for near-duplicate claim patterns.

This is a documented alternative to MinHash/LSH. It does not use participant
tokens as features; tokens are only compared internally to require different
participants, as in the existing exact-pattern detector.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from hashlib import blake2b
from itertools import combinations
from typing import Any, Callable

from app.analytics.detector_utils import date_value, nonnegative_decimal, text_value, valid_records


INDICATOR = "near_duplicate_claim_candidate"
NEAR_FIELDS = (
    "service_date", "province_code", "municipality_code", "facility_ownership",
    "facility_type", "facility_class", "admission_diagnosis", "primary_diagnosis",
    "claim_group", "procedure_code", "billed_amount",
)
_FIELD_INDEX = {field: index for index, field in enumerate(NEAR_FIELDS)}
BLOCKING_FIELDS = (
    ("service_date", "municipality_code", "primary_diagnosis"),
    (
    "service_date",
    "municipality_code",
    "claim_group",
    "admission_diagnosis",
    ),
    ("service_date", "province_code", "admission_diagnosis"),
)
# For dense primary blocks, candidate generation requires exact agreement on
# all but at most the number of attributes the configured similarity permits
# to differ. The participant token is deliberately excluded.
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
    max_candidates: int = 5000

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
    *,
    candidate_pair_observer: Callable[[str, str], None] | None = None,
    similarity_observer: Callable[[str, str, bool], None] | None = None,
) -> dict[str, Any]:
    """Compare bounded candidate pairs from deterministic attribute blocks.

    Optional observers are for local evaluation instrumentation only. Pair
    identities are never added to the detector result or ordinary API output.
    """
    config = config or NearDuplicateConfig()
    validated = valid_records(records)
    # Tuples substantially reduce per-record Python object overhead compared
    # with one nested dictionary per claim. Field order is NEAR_FIELDS.
    normalized: dict[str, tuple[Any, ...]] = {}
    participants: dict[str, str | None] = {}
    ineligible: list[dict[str, str]] = []
    for case_id, row in validated:
        normalized[case_id] = tuple(_field_value(field, row.get(field)) for field in NEAR_FIELDS)
        participants[case_id] = text_value(row.get("participant_token"))

    blocks: dict[tuple[int, tuple[Any, ...]], list[str]] = defaultdict(list)
    for case_id in sorted(normalized):
        values = normalized[case_id]
        for block_number, fields in enumerate(BLOCKING_FIELDS):
            block_values = tuple(values[_FIELD_INDEX[field]] for field in fields)
            if all(value is not None for value in block_values):
                blocks[(block_number, block_values)].append(case_id)

    pair_keys: set[tuple[str, str]] = set()
    comparisons = 0
    search_truncated = False
    oversized_primary_blocks = 0
    refinement_bucket_count = 0
    oversized_refinement_buckets = 0
    sampled_dense_buckets = 0
    maximum_primary_block_size = 0
    maximum_refinement_bucket_size = 0
    comparison_limit_hit = False
    candidate_limit_hit = False
    ineligible_pair_count = 0
    blocks_skipped_by_pair_budget = 0
    stratified_block_sampling = False
    stratified_sampled_primary_block_count = 0
    unassessed_case_ids: set[str] = set()
    stratified_unassessed_case_ids: set[str] = set()
    comparison_budget_unassessed_case_ids: set[str] = set()
    candidate_limit_unassessed_case_ids: set[str] = set()
    bounded_block_unassessed_case_ids: set[str] = set()

    def add_pairs(pairs):
        nonlocal comparisons, search_truncated, comparison_limit_hit, ineligible_pair_count
        for left, right in pairs:
            if left == right:
                continue
            pair = (left, right) if left < right else (right, left)
            if pair in pair_keys:
                continue
            left_participant, right_participant = participants[left], participants[right]
            if left_participant is None or right_participant is None or left_participant == right_participant:
                ineligible_pair_count += 1
                continue
            if comparisons >= config.max_pair_comparisons:
                search_truncated = True
                comparison_limit_hit = True
                return False
            pair_keys.add(pair)
            comparisons += 1
            if candidate_pair_observer is not None:
                candidate_pair_observer(*pair)
        return True

    def first_cross_participant_pair(case_ids: Sequence[str]) -> tuple[str, str] | None:
        first_by_participant: dict[str, str] = {}
        for case_id in case_ids:
            participant = participants[case_id]
            if participant is not None:
                first_by_participant.setdefault(participant, case_id)
        representatives = sorted(first_by_participant.values())
        if len(representatives) < 2:
            return None
        return representatives[0], representatives[1]

    # A candidate may differ in at most this many comparable attributes and
    # still meet the configured similarity threshold. Search exact refinements
    # over remaining canonical features, then verify with the full comparator.
    max_omitted_fields = min(
        max(0, int((1 - config.min_similarity) * len(NEAR_FIELDS))),
        max(0, len(NEAR_FIELDS) - config.min_compared_attributes),
    )
    # Process the most selective blocks first, with a stable digest tie-break.
    # Lexicographic feature order had exhausted the global budget on an
    # arbitrary prefix, excluding later eligible patterns from assessment.
    ordered_block_keys = sorted(
        blocks,
        key=lambda item: (
            len(blocks[item]),
            blake2b(repr(item).encode("utf-8"), digest_size=8).digest(),
        ),
    )
    eligible_block_keys = [key for key in ordered_block_keys if len(blocks[key]) > 1]
    estimated_primary_pairs = sum(
        len(blocks[key]) * (len(blocks[key]) - 1) // 2
        for key in eligible_block_keys if len(blocks[key]) <= config.max_block_size
    )
    if len(eligible_block_keys) > config.max_pair_comparisons or estimated_primary_pairs > config.max_pair_comparisons:
        stratified_block_sampling = True
        sample_count = min(config.max_pair_comparisons, len(eligible_block_keys))
        selected_positions = {
            (position * len(eligible_block_keys)) // sample_count
            for position in range(sample_count)
        } if sample_count else set()
        spread_keys = [
            key for position, key in enumerate(eligible_block_keys)
            if position in selected_positions
        ]
        spread_key_set = set(spread_keys)
        # Spread the initial work across the complete block order, then use
        # remaining blocks to refill the budget when sampled pairs overlap.
        selected_block_keys = spread_keys + [key for key in eligible_block_keys if key not in spread_key_set]
    else:
        selected_block_keys = eligible_block_keys

    for selected_index, block_key in enumerate(selected_block_keys):
        case_ids = sorted(set(blocks[block_key]))
        if len(case_ids) < 2:
            continue
        maximum_primary_block_size = max(maximum_primary_block_size, len(case_ids))
        if len(case_ids) <= config.max_block_size:
            pair_iterator = combinations(case_ids, 2)
            # When the population exceeds the comparison budget, one pair per
            # evenly-spaced block prevents the first few groups monopolizing it.
            if stratified_block_sampling:
                sample = first_cross_participant_pair(case_ids)
                pairs = (sample,) if sample is not None else ()
                if len(case_ids) > 2:
                    stratified_sampled_primary_block_count += 1
                    unassessed_case_ids.update(case_ids)
                    stratified_unassessed_case_ids.update(case_ids)
            else:
                pairs = pair_iterator
            if not add_pairs(pair for pair in pairs if pair is not None):
                # The current block and every later selected block did not
                # complete assessment after the global pair budget was hit.
                for pending_key in selected_block_keys[selected_index:]:
                    unassessed_case_ids.update(blocks[pending_key])
                    comparison_budget_unassessed_case_ids.update(blocks[pending_key])
                blocks_skipped_by_pair_budget = max(0, len(selected_block_keys) - selected_index - 1)
                break
            continue

        oversized_primary_blocks += 1
        search_truncated = True
        unassessed_case_ids.update(case_ids)
        bounded_block_unassessed_case_ids.update(case_ids)
        # Oversized blocks are refined by exact agreement on the remaining
        # feature fields. A too-dense refinement bucket gets a bounded,
        # deterministic cross-participant sample; the result remains partial.
        primary_fields = BLOCKING_FIELDS[block_key[0]]
        remaining_fields = tuple(field for field in NEAR_FIELDS if field not in primary_fields)
        omitted_count = min(max_omitted_fields, len(remaining_fields))
        refinements = [
            tuple(field for field in remaining_fields if field not in omitted)
            for omitted in ((), *combinations(remaining_fields, omitted_count))
        ]
        seen_refinements: set[tuple[str, ...]] = set()
        for refinement_fields in refinements:
            if refinement_fields in seen_refinements:
                continue
            seen_refinements.add(refinement_fields)
            refinement_blocks: dict[tuple[Any, ...], list[str]] = defaultdict(list)
            for case_id in case_ids:
                key_values = tuple(normalized[case_id][_FIELD_INDEX[field]] for field in refinement_fields)
                # Missing values cannot establish a positive exact match.
                if all(value is not None for value in key_values):
                    refinement_blocks[key_values].append(case_id)
            for values in sorted(refinement_blocks, key=lambda key: tuple(str(value) for value in key)):
                refined_ids = refinement_blocks[values]
                if len(refined_ids) < 2:
                    continue
                refinement_bucket_count += 1
                maximum_refinement_bucket_size = max(maximum_refinement_bucket_size, len(refined_ids))
                if len(refined_ids) <= config.max_block_size:
                    if not add_pairs(combinations(refined_ids, 2)):
                        break
                else:
                    oversized_refinement_buckets += 1
                    sampled_dense_buckets += 1
                    unassessed_case_ids.update(refined_ids)
                    bounded_block_unassessed_case_ids.update(refined_ids)
                    # Keep only the first deterministic reference per internal
                    # participant token, then compare a bounded anchor sample.
                    # Tokens never enter the pair key or detector output.
                    representative_by_participant: dict[str, str] = {}
                    for case_id in refined_ids:
                        participant = participants[case_id]
                        if participant is not None:
                            representative_by_participant.setdefault(participant, case_id)
                    representatives = sorted(representative_by_participant.values())
                    if len(representatives) > 1:
                        sample_pairs = [(representatives[0], representatives[1])]
                        if len(representatives) > 2 and config.max_block_size > 2:
                            sample_pairs.append((representatives[0], representatives[-1]))
                        if not add_pairs(sample_pairs[:config.max_block_size - 1]):
                            break
            if comparison_limit_hit:
                break
        if comparison_limit_hit:
            for pending_key in selected_block_keys[selected_index:]:
                unassessed_case_ids.update(blocks[pending_key])
                comparison_budget_unassessed_case_ids.update(blocks[pending_key])
            blocks_skipped_by_pair_budget = max(0, len(selected_block_keys) - selected_index - 1)
            break

    candidates: list[dict[str, Any]] = []
    ordered_pairs = sorted(pair_keys)
    for pair_index, (left, right) in enumerate(ordered_pairs):
        left_participant, right_participant = participants[left], participants[right]
        if left_participant is None or right_participant is None or left_participant == right_participant:
            continue
        matched: list[str] = []
        differing: list[str] = []
        comparable = 0
        for field in NEAR_FIELDS:
            field_index = _FIELD_INDEX[field]
            left_value, right_value = normalized[left][field_index], normalized[right][field_index]
            if left_value is None or right_value is None:
                continue
            comparable += 1
            if field == "billed_amount":
                same = abs(left_value - right_value) <= config.amount_tolerance
            else:
                same = left_value == right_value
            (matched if same else differing).append(field)
        if comparable < config.min_compared_attributes:
            if similarity_observer is not None:
                similarity_observer(left, right, False)
            continue
        similarity = len(matched) / comparable
        if similarity < config.min_similarity:
            if similarity_observer is not None:
                similarity_observer(left, right, False)
            continue
        if similarity_observer is not None:
            similarity_observer(left, right, True)
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
            candidate_limit_hit = True
            for remaining_left, remaining_right in ordered_pairs[pair_index + 1:]:
                # Candidate generation after this output cap was not evaluated.
                unassessed_case_ids.update((remaining_left, remaining_right))
                candidate_limit_unassessed_case_ids.update((remaining_left, remaining_right))
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
        "unassessed_case_ids": sorted(unassessed_case_ids),
        "truncation_scope": "explicit_unassessed_cases",
        "pair_comparisons": comparisons,
        "search_diagnostics": {
            "primary_block_count": len(blocks),
            "oversized_primary_block_count": oversized_primary_blocks,
            "refinement_bucket_count": refinement_bucket_count,
            "oversized_refinement_bucket_count": oversized_refinement_buckets,
            "dense_bucket_sample_count": sampled_dense_buckets,
            "maximum_primary_block_size": maximum_primary_block_size,
            "maximum_refinement_bucket_size": maximum_refinement_bucket_size,
            "comparison_limit_hit": comparison_limit_hit,
            "candidate_limit_hit": candidate_limit_hit,
            "hard_search_limit_hit": comparison_limit_hit or candidate_limit_hit,
            "ineligible_pair_count": ineligible_pair_count,
            "stratified_block_sampling": stratified_block_sampling,
            "stratified_sampled_primary_block_count": stratified_sampled_primary_block_count,
            "stratified_sampling_left_unassessed": bool(stratified_unassessed_case_ids),
            "stratified_sampling_unassessed_case_count": len(stratified_unassessed_case_ids),
            "comparison_budget_unassessed_case_count": len(comparison_budget_unassessed_case_ids),
            "candidate_limit_unassessed_case_count": len(candidate_limit_unassessed_case_ids),
            "bounded_block_unassessed_case_count": len(bounded_block_unassessed_case_ids),
            "unassessed_case_count": len(unassessed_case_ids),
            "assessment_incomplete": bool(search_truncated or unassessed_case_ids),
            "unassessed_cause_counts_are_nonexclusive": True,
            "eligible_primary_block_count": len(eligible_block_keys),
            "selected_primary_block_count": len(selected_block_keys),
            "estimated_primary_pair_work": estimated_primary_pairs,
            "blocks_skipped_by_pair_budget": blocks_skipped_by_pair_budget,
            # Overlapping blocking keys are deduplicated, so exact skipped
            # pair count cannot be inferred from the raw block estimate.
            "estimated_primary_pairs_skipped": None,
            "oversized_bucket_strategy": "canonical_feature_refinement_with_bounded_cross_participant_sample",
        },
        # Kept as an additive compatibility field; the former chain strategy
        # is no longer used.
        "large_blocks_chain_compared": 0,
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
