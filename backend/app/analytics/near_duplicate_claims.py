"""Bounded deterministic blocking search for near-duplicate claim patterns.

This is a documented alternative to MinHash/LSH. It does not use participant
tokens as features; tokens are only compared internally to require different
participants, as in the existing exact-pattern detector.
"""

from collections import Counter, defaultdict
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
# Pigeonhole blocking: the nine exact-compared attributes besides the admission date are
# split into disjoint groups, each keyed together with the date. A pair that meets the
# similarity rule has at most k attributes that differ or are missing in either record
# (see _max_bad_attributes); with k + 1 groups at least one group agrees exactly, so the pair
# shares that block. The fewest groups that still guarantee this are used: three larger
# (more selective) groups when no record carries a claim amount (k = 2, e.g. the FKRTL
# sample), four otherwise (k = 3). Pairs with different admission dates are outside this
# screen's scope.
BLOCKING_PARTITIONS = {
    3: (
        ("municipality_code", "primary_diagnosis", "facility_ownership"),
        ("province_code", "claim_group", "facility_type"),
        ("admission_diagnosis", "procedure_code", "facility_class"),
    ),
    4: (
        ("municipality_code", "primary_diagnosis", "facility_ownership"),
        ("province_code", "claim_group"),
        ("admission_diagnosis", "facility_type"),
        ("procedure_code", "facility_class"),
    ),
}


def blocking_fields(group_count: int) -> tuple[tuple[str, ...], ...]:
    return tuple(("service_date", *group) for group in BLOCKING_PARTITIONS[group_count])


# The conservative partition, kept for callers that do not know whether amounts are present.
BLOCKING_FIELDS = blocking_fields(4)
# Compared with a tolerance, so never part of an exact blocking or refinement key.
_TOLERANCE_FIELDS = frozenset({"billed_amount"})
# For dense primary blocks, candidate generation requires exact agreement on
# all but at most the number of attributes the configured similarity permits
# to differ. The participant token is deliberately excluded.
LIMITATIONS = [
    "Near-match adalah sinyal pola untuk ditinjau, bukan bukti cloning, fraud, atau layanan fiktif.",
    "Blocking dapat melewatkan pasangan yang berbeda pada semua atribut pemblokir.",
    "Field administrasi bukan ID fasilitas; kecocokan tidak memastikan fasilitas yang sama.",
    "Ambang, toleransi biaya, dan batas pencarian adalah parameter eksperimen, bukan aturan BPJS.",
    "Penyaringan eksploratif: pada benchmark sintetis, klaim rutin hari yang sama dan pasangan dengan dua atribut berbeda juga lolos ambang, sehingga sebagian besar kandidat adalah kemiripan rutin, bukan pola target.",
]


# A matched combination of values held by no third claim on the same admission date is
# "informative": the similarity is not explained by a common combination. Not tuned: it is the
# smallest possible support of a pair.
INFORMATIVE_MAX_SUPPORT = 2
COMMON_ATTRIBUTE_LIMITATION = (
    "Pasangan yang hanya mirip karena kombinasi atribut umum (dimiliki tiga klaim atau lebih pada tanggal yang sama) "
    "dihitung secara agregat dan tidak ditandai per kasus; salinan klaim dengan kombinasi umum tidak dapat dibedakan "
    "dari klaim rutin."
)
BOUNDED_SELECTION_LIMITATION = (
    "Pencarian dibatasi: record yang selesai dinilai cenderung berasal dari kelompok kecil dengan sedikit "
    "klaim sebanding, sehingga proporsi tertandai di antara record yang dinilai tidak mewakili seluruh jendela."
)


@dataclass(frozen=True)
class NearDuplicateConfig:
    min_similarity: float = 0.8
    min_compared_attributes: int = 9
    amount_tolerance: Decimal = Decimal("1.00")
    max_block_size: int = 100
    # Sized from measurement: a 7-day FKRTL window (35,565 claims) needs ~378k comparisons for a
    # complete search (~7 s); larger inputs stay bounded and disclose the bounded selection.
    max_pair_comparisons: int = 1_000_000
    max_candidates: int = 200_000
    # Seed of the analytical record order used wherever the bounded search
    # must choose among records. Changing it changes which pairs a truncated
    # search samples; it never involves participant or visit identifiers.
    ordering_seed: int = 0

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


def _attach_match_evidence(candidates: list[dict[str, Any]], normalized: Mapping[str, tuple[Any, ...]]) -> None:
    """Add support, chance expectation and evidence class to every qualifying pair.

    ``match_support``: claims on the same admission date (over the whole input, whatever the
    search budget) that share every matched exact value, the pair itself included.
    ``expected_chance_pairs``: same-day pairs expected to agree on those values if attributes
    were independent; it orders candidates (most unexpected first) and is not a probability of
    fraud. Amounts are compared with a tolerance and are left out of both.
    """
    date_index = _FIELD_INDEX["service_date"]
    day_sizes = Counter(values[date_index] for values in normalized.values())
    frequencies: dict[tuple[Any, int], Counter] = {}
    supports: dict[tuple[str, ...], Counter] = {}
    for candidate in candidates:
        left = normalized[candidate["case_ids"][0]]
        fields = tuple(field for field in NEAR_FIELDS
                       if field in candidate["matched_attributes"] and field not in _TOLERANCE_FIELDS)
        indexes = tuple(_FIELD_INDEX[field] for field in fields)
        if fields not in supports:
            supports[fields] = Counter(
                tuple(values[index] for index in indexes) for values in normalized.values()
                if all(values[index] is not None for index in indexes)
            )
        support = supports[fields][tuple(left[index] for index in indexes)]
        day = left[date_index]
        size = day_sizes[day]
        probability = 1.0
        for index in indexes:
            if index == date_index:
                continue
            key = (day, index)
            if key not in frequencies:
                frequencies[key] = Counter(values[index] for values in normalized.values() if values[date_index] == day)
            probability *= (frequencies[key][left[index]] / size) ** 2
        candidate["match_support"] = support
        candidate["expected_chance_pairs"] = float(f"{size * (size - 1) / 2 * probability:.3g}")
        candidate["evidence_class"] = "informative" if support <= INFORMATIVE_MAX_SUPPORT else "common_attributes"
        if candidate["evidence_class"] == "informative":
            differing = candidate["differing_attributes"]
            candidate["reason"] = (
                f"Dua klaim dari peserta berbeda cocok pada {candidate['matched_attribute_count']} dari "
                f"{candidate['compared_attribute_count']} atribut yang dapat dibandingkan; atribut berbeda "
                f"{', '.join(differing) if differing else 'tidak ada'}. Tidak ada klaim lain pada tanggal yang sama "
                "dengan nilai yang sama pada atribut yang cocok, sehingga kemiripan ini tidak dijelaskan oleh kombinasi "
                "umum. Nilai signature tidak ditampilkan."
            )


def _max_bad_attributes(config: NearDuplicateConfig, amount_available: bool = True) -> int:
    """Most exact-key attributes a qualifying pair can have differing or missing.

    With ``m`` attributes missing in either record the pair compares ``n - m`` attributes and
    may differ in at most ``floor((1 - min_similarity) * (n - m))`` of them. Without any
    amount, the amount is missing for every pair and does not count among the ``n``.
    """
    total = len(NEAR_FIELDS) - (0 if amount_available else 1)
    worst = 0
    for missing in range(0, total - config.min_compared_attributes + 1):
        compared = total - missing
        differing = int((1 - config.min_similarity) * compared + 1e-9)
        worst = max(worst, missing + differing)
    return worst


def _group_count(config: NearDuplicateConfig, amount_available: bool) -> int:
    return 3 if _max_bad_attributes(config, amount_available) < 3 else 4


def _prerequisite(values: tuple[Any, ...], has_participant: bool, config: NearDuplicateConfig,
                  keys: tuple[tuple[str, ...], ...] = BLOCKING_FIELDS) -> str | None:
    """Row-level prerequisite, or the reason the record cannot be screened.

    No single attribute is required: a record needs a participant reference, at least
    ``min_compared_attributes`` present attributes (so one of the eleven may be missing,
    e.g. a blank procedure), and one complete blocking key to be reachable by the search.
    """
    if not has_participant:
        return "missing_participant"
    if sum(value is not None for value in values) < config.min_compared_attributes:
        return "too_few_attributes"
    if not any(all(values[_FIELD_INDEX[field]] is not None for field in fields) for fields in keys):
        return "no_complete_blocking_key"
    return None


def prerequisite_reason(row: Mapping[str, Any], config: NearDuplicateConfig | None = None,
                        amount_available: bool | None = None) -> str | None:
    """Prerequisite check of one canonical record, identical to the detector's own rule.

    ``amount_available`` is a property of the whole input (does any record carry an amount);
    when not given it is taken from this record, which matches sources where amounts are
    either always present or always withheld (the FKRTL sample).
    """
    config = config or NearDuplicateConfig()
    values = tuple(_field_value(field, row.get(field)) for field in NEAR_FIELDS)
    if amount_available is None:
        amount_available = values[_FIELD_INDEX["billed_amount"]] is not None
    keys = blocking_fields(_group_count(config, amount_available))
    return _prerequisite(values, text_value(row.get("participant_token")) is not None, config, keys)


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

    # Analytical order: a seeded digest of the record's non-identifier feature
    # values, tie-broken by input position. Case IDs are keyed pseudonyms, so
    # ordering by them made the secret decide which pairs a bounded search
    # examined (and therefore candidates and coverage counts).
    order_key: dict[str, tuple[bytes, int]] = {
        case_id: (
            blake2b(f"{config.ordering_seed}|{normalized[case_id]!r}".encode("utf-8"), digest_size=8).digest(),
            position,
        )
        for position, (case_id, _row) in enumerate(validated)
    }

    def analytical(case_ids):
        return sorted(case_ids, key=order_key.__getitem__)

    # Whether any record carries an amount decides the partition (see BLOCKING_PARTITIONS).
    amount_available = any(values[_FIELD_INDEX["billed_amount"]] is not None for values in normalized.values())
    group_count = _group_count(config, amount_available)
    keys = blocking_fields(group_count)
    blocks: dict[tuple[int, tuple[Any, ...]], list[str]] = defaultdict(list)
    # Records that can never meet the comparison minimum, or that no blocking
    # key can reach, were not evaluated; they must not count as negatives.
    too_few_attribute_ids: set[str] = set()
    unblockable_case_ids: set[str] = set()
    for case_id in analytical(normalized):
        values = normalized[case_id]
        reason = _prerequisite(values, participants[case_id] is not None, config, keys)
        if reason == "missing_participant":
            continue  # cannot satisfy the different-participant rule; reported ineligible
        if reason == "too_few_attributes":
            # Can never become a candidate; keep it out of blocks so it does
            # not consume the comparison budget.
            too_few_attribute_ids.add(case_id)
            continue
        in_block = False
        for block_number, fields in enumerate(keys):
            block_values = tuple(values[_FIELD_INDEX[field]] for field in fields)
            if all(value is not None for value in block_values):
                blocks[(block_number, block_values)].append(case_id)
                in_block = True
        if not in_block:
            unblockable_case_ids.add(case_id)

    # Budget allocation (deterministic; never ordered by keyed case IDs):
    #  * Pair pre-filter: only cross-participant pairs whose shared non-missing
    #    attributes reach ``min_compared_attributes`` can become candidates,
    #    so only those pairs are charged to the comparison budget.
    #  * Phase A: search units (primary blocks <= max_block_size and the exact
    #    refinement buckets of oversized blocks) are taken cheapest first and
    #    processed completely whenever their remaining pairs fit the budget.
    #  * Phase C: units that did not fit share the leftover budget round-robin
    #    with a sorted-neighbourhood sample: members are sorted by feature
    #    values and each record is paired with its d-th neighbour for
    #    d = 1, 2, ... (d is capped at max_block_size for oversized buckets).
    #  * A record counts as assessed only if every unit containing it was
    #    completed, it is not in an oversized primary block, and none of its
    #    planned pairs was cut by the candidate cap.
    present_mask = {
        case_id: sum(1 << index for index, value in enumerate(values) if value is not None)
        for case_id, values in normalized.items()
    }
    pair_validity: dict[tuple[str, str], bool] = {}
    same_participant_pairs = 0
    insufficient_attribute_pairs = 0

    def ordered_pair(left: str, right: str) -> tuple[str, str]:
        return (left, right) if order_key[left] < order_key[right] else (right, left)

    def is_valid(pair: tuple[str, str]) -> bool:
        nonlocal same_participant_pairs, insufficient_attribute_pairs
        known = pair_validity.get(pair)
        if known is not None:
            return known
        left, right = pair
        if participants[left] == participants[right]:
            same_participant_pairs += 1
            valid = False
        elif (present_mask[left] & present_mask[right]).bit_count() < config.min_compared_attributes:
            insufficient_attribute_pairs += 1
            valid = False
        else:
            valid = True
        pair_validity[pair] = valid
        return valid

    def unit_digest(unit_key: tuple[Any, ...]) -> bytes:
        return blake2b(f"{config.ordering_seed}|{unit_key!r}".encode("utf-8"), digest_size=8).digest()

    # A qualifying pair has at most this many differing-or-missing exact attributes; oversized
    # blocks are split into exact refinement buckets that omit that many of the remaining
    # attributes, so every qualifying pair inside the block still shares some bucket.
    max_omitted_fields = _max_bad_attributes(config, amount_available)
    blocking_complete = max_omitted_fields < group_count
    oversized_primary_blocks = 0
    refinement_bucket_count = 0
    oversized_refinement_buckets = 0
    maximum_primary_block_size = 0
    maximum_refinement_bucket_size = 0
    oversized_primary_case_ids: set[str] = set()
    units: list[tuple[bytes, tuple[Any, ...], list[str], bool]] = []  # digest, key, members, enumerable
    for block_key, members in blocks.items():
        if len(members) < 2:
            continue
        maximum_primary_block_size = max(maximum_primary_block_size, len(members))
        if len(members) <= config.max_block_size:
            unit_key = ("block", block_key)
            units.append((unit_digest(unit_key), unit_key, analytical(members), True))
            continue
        oversized_primary_blocks += 1
        oversized_primary_case_ids.update(members)
        primary_fields = keys[block_key[0]]
        remaining_fields = tuple(field for field in NEAR_FIELDS
                                 if field not in primary_fields and field not in _TOLERANCE_FIELDS)
        omitted_count = min(max_omitted_fields, len(remaining_fields))
        refinements = list(dict.fromkeys(
            tuple(field for field in remaining_fields if field not in omitted)
            for omitted in ((), *combinations(remaining_fields, omitted_count))
        ))
        for refinement_fields in refinements:
            buckets: dict[tuple[Any, ...], list[str]] = defaultdict(list)
            for case_id in members:
                key_values = tuple(normalized[case_id][_FIELD_INDEX[field]] for field in refinement_fields)
                # Missing values cannot establish a positive exact match.
                if all(value is not None for value in key_values):
                    buckets[key_values].append(case_id)
            for values, bucket in buckets.items():
                if len(bucket) < 2:
                    continue
                refinement_bucket_count += 1
                maximum_refinement_bucket_size = max(maximum_refinement_bucket_size, len(bucket))
                enumerable = len(bucket) <= config.max_block_size
                oversized_refinement_buckets += int(not enumerable)
                unit_key = ("refinement", block_key, refinement_fields, values)
                units.append((unit_digest(unit_key), unit_key, analytical(bucket), enumerable))

    planned: list[tuple[str, str]] = []
    planned_set: set[tuple[str, str]] = set()

    def plan(pair: tuple[str, str]) -> None:
        planned.append(pair)
        planned_set.add(pair)
        if candidate_pair_observer is not None:
            candidate_pair_observer(*pair)

    # Phase A: complete the cheapest units that fit.
    costed: list[tuple[int, bytes, list[str], list[tuple[str, str]]]] = []
    deferred: list[tuple[int, bytes, list[str], bool]] = []
    for digest, _unit_key, members, enumerable in units:
        if len({participants[case_id] for case_id in members}) < 2:
            continue  # no cross-participant pair exists: the unit is trivially complete
        if not enumerable:
            deferred.append((len(members) ** 2, digest, members, False))
            continue
        pairs = [
            pair for index, left in enumerate(members) for right in members[index + 1:]
            if is_valid(pair := ordered_pair(left, right))
        ]
        costed.append((len(pairs), digest, members, pairs))
    costed.sort(key=lambda item: (item[0], item[1]))
    estimated_valid_pair_work = sum(item[0] for item in costed)
    fully_processed_units = 0
    for cost, digest, members, pairs in costed:
        new_pairs = [pair for pair in pairs if pair not in planned_set]
        if len(new_pairs) <= config.max_pair_comparisons - len(planned):
            for pair in new_pairs:
                plan(pair)
            fully_processed_units += 1
        else:
            deferred.append((cost, digest, members, True))

    # Phase C: share the leftover budget across deferred units round-robin.
    deferred.sort(key=lambda item: (not item[3], item[0], item[1]))
    neighbour_orders = [
        sorted(members, key=lambda case_id: (
            tuple((value is None, str(value)) for value in normalized[case_id]), order_key[case_id],
        ))
        for _cost, _digest, members, _enumerable in deferred
    ]
    max_distance = [
        len(order) - 1 if enumerable else min(len(order) - 1, config.max_block_size)
        for order, (_c, _d, _m, enumerable) in zip(neighbour_orders, deferred)
    ]
    finished_distance = [0] * len(deferred)
    comparison_limit_hit = False
    distance = 1
    while not comparison_limit_hit and any(distance <= limit for limit in max_distance):
        for unit_index, order in enumerate(neighbour_orders):
            if distance > max_distance[unit_index]:
                continue
            for position in range(len(order) - distance):
                pair = ordered_pair(order[position], order[position + distance])
                if pair in planned_set or not is_valid(pair):
                    continue
                if len(planned) >= config.max_pair_comparisons:
                    comparison_limit_hit = True
                    break
                plan(pair)
            if comparison_limit_hit:
                break
            finished_distance[unit_index] = distance
        distance += 1
    completed_deferred = sum(
        1 for unit_index, (_c, _d, _m, enumerable) in enumerate(deferred)
        if enumerable and finished_distance[unit_index] >= len(neighbour_orders[unit_index]) - 1
    )
    partial_unit_case_ids: set[str] = set()
    for unit_index, (_cost, _digest, members, enumerable) in enumerate(deferred):
        if not enumerable or finished_distance[unit_index] < len(neighbour_orders[unit_index]) - 1:
            partial_unit_case_ids.update(members)
    sampled_units = len(deferred) - completed_deferred

    # Compare planned pairs in plan order; the candidate cap is independent of the budget.
    candidates: list[dict[str, Any]] = []
    comparisons = 0
    candidate_limit_hit = False
    candidate_limit_unassessed_case_ids: set[str] = set()
    for pair_index, (left, right) in enumerate(planned):
        if len(candidates) >= config.max_candidates:
            candidate_limit_hit = True
            for remaining_left, remaining_right in planned[pair_index:]:
                # Pairs after the output cap were never compared.
                candidate_limit_unassessed_case_ids.update((remaining_left, remaining_right))
            break
        comparisons += 1
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

    # Only informative pairs flag records; pairs explained by a common combination are kept
    # in memory (common_attribute_candidates, never persisted) and counted in the diagnostics.
    _attach_match_evidence(candidates, normalized)
    candidates.sort(key=lambda item: (item["expected_chance_pairs"], -item["similarity_ratio"], item["candidate_id"]))
    informative = [item for item in candidates if item["evidence_class"] == "informative"]
    common = [item for item in candidates if item["evidence_class"] != "informative"]
    informative_ids = {case_id for item in informative for case_id in item["case_ids"]}
    common_only_ids = {case_id for item in common for case_id in item["case_ids"]} - informative_ids

    ineligible = []
    for case_id in sorted(normalized):
        if participants[case_id] is None:
            ineligible.append({"case_id": case_id, "reason": "Token peserta tidak tersedia untuk mensyaratkan peserta berbeda."})
        elif case_id in too_few_attribute_ids:
            ineligible.append({"case_id": case_id, "reason": "Atribut yang dapat dibandingkan kurang dari batas minimum; kemiripan tidak dapat dinilai."})
    ineligible_ids = {item["case_id"] for item in ineligible}
    unblockable_case_ids -= ineligible_ids
    # Members of an oversized primary block are assessed through its refinement buckets; a
    # member stays unassessed only if a bucket containing it was sampled (partial_unit_case_ids)
    # or the blocking cannot guarantee completeness for the configured threshold.
    incomplete_blocking_ids = oversized_primary_case_ids if not blocking_complete else set()
    unassessed_case_ids = (
        unblockable_case_ids | incomplete_blocking_ids | partial_unit_case_ids
        | candidate_limit_unassessed_case_ids
    ) - ineligible_ids
    search_truncated = bool(comparison_limit_hit or candidate_limit_hit or sampled_units
                            or (oversized_primary_blocks and not blocking_complete))
    return {
        "indicator": INDICATOR,
        "input_record_count": len(validated),
        "candidate_count": len(informative),
        "candidates": informative,
        "common_attribute_candidates": common,
        "ineligible_cases": ineligible,
        "unassessed_case_ids": sorted(unassessed_case_ids),
        "truncation_scope": "explicit_unassessed_cases",
        "pair_comparisons": comparisons,
        "search_diagnostics": {
            "allocation_strategy": "complete_cheapest_units_then_round_robin_sorted_neighbourhood",
            # With a bounded search the fully assessed records come mostly from small blocks
            # (few comparable neighbours), so their flag rate understates the window's.
            "assessment_selection": "bounded_small_neighbourhoods_first" if unassessed_case_ids else "complete",
            "qualifying_pair_count": len(candidates),
            "informative_pair_count": len(informative),
            "common_attribute_pair_count": len(common),
            "records_matched_only_on_common_attributes": len(common_only_ids),
            "informative_max_support": INFORMATIVE_MAX_SUPPORT,
            "primary_block_count": len(blocks),
            "search_unit_count": len(units),
            "fully_processed_unit_count": fully_processed_units + completed_deferred,
            "sampled_unit_count": sampled_units,
            "oversized_primary_block_count": oversized_primary_blocks,
            "refinement_bucket_count": refinement_bucket_count,
            "oversized_refinement_bucket_count": oversized_refinement_buckets,
            "dense_bucket_sample_count": oversized_refinement_buckets,
            "maximum_primary_block_size": maximum_primary_block_size,
            "maximum_refinement_bucket_size": maximum_refinement_bucket_size,
            "planned_pair_count": len(planned),
            "estimated_valid_pair_work": estimated_valid_pair_work,
            "estimated_primary_pair_work": estimated_valid_pair_work,
            "comparison_limit_hit": comparison_limit_hit,
            "candidate_limit_hit": candidate_limit_hit,
            "hard_search_limit_hit": comparison_limit_hit or candidate_limit_hit,
            "same_participant_pair_count": same_participant_pairs,
            "insufficient_comparable_pair_count": insufficient_attribute_pairs,
            "ineligible_pair_count": same_participant_pairs + insufficient_attribute_pairs,
            # Compatibility names: "stratified" now means sampled (partially searched) units.
            "stratified_block_sampling": sampled_units > 0,
            "stratified_sampling_left_unassessed": bool(partial_unit_case_ids),
            "stratified_sampling_unassessed_case_count": len(partial_unit_case_ids),
            "comparison_budget_unassessed_case_count": len(partial_unit_case_ids) if comparison_limit_hit else 0,
            "candidate_limit_unassessed_case_count": len(candidate_limit_unassessed_case_ids),
            "bounded_block_unassessed_case_count": len(incomplete_blocking_ids),
            "blocking_complete_for_threshold": blocking_complete,
            "max_differing_or_missing_attributes": max_omitted_fields,
            "unassessed_case_count": len(unassessed_case_ids),
            "missing_blocking_key_case_count": len(unblockable_case_ids),
            "too_few_comparable_attributes_case_count": len(too_few_attribute_ids),
            "assessment_incomplete": bool(search_truncated or unassessed_case_ids),
            "unassessed_cause_counts_are_nonexclusive": True,
        },
        # Kept as an additive compatibility field; the former chain strategy
        # is no longer used.
        "large_blocks_chain_compared": 0,
        "search_truncated": search_truncated,
        "search_parameters": {
            "blocking_fields": [list(fields) for fields in keys],
            "min_similarity": config.min_similarity,
            "min_compared_attributes": config.min_compared_attributes,
            "amount_tolerance": str(config.amount_tolerance),
            "max_block_size": config.max_block_size,
            "max_pair_comparisons": config.max_pair_comparisons,
            "max_candidates": config.max_candidates,
            "ordering": "seeded digest of non-identifier features, then input position",
            "ordering_seed": config.ordering_seed,
        },
        "limitations": LIMITATIONS.copy() + [COMMON_ATTRIBUTE_LIMITATION]
        + ([BOUNDED_SELECTION_LIMITATION] if unassessed_case_ids else []),
    }
