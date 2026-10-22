"""Versioned synthetic benchmark with facility-level negative controls.

The v3 experiment generator remains unchanged. This v4 profile redistributes
only synthetic feature records and labels to create a seeded subset of
positive facilities while balancing total claim counts across facilities.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import random
from typing import Any

from app.data_sources.synthetic_generator import (
    GeneratedSyntheticDataset,
    SyntheticGeneratorConfig,
    SyntheticGroundTruth,
    generate_synthetic_dataset,
)


BENCHMARK_GENERATOR_VERSION = "4"
BENCHMARK_PROFILE = "facility-stratified-sparse-positive-v1"


@dataclass(frozen=True)
class SyntheticBenchmarkProfile:
    positive_facility_fraction: float = 0.20

    def __post_init__(self) -> None:
        if not 0 < self.positive_facility_fraction < 1:
            raise ValueError("positive_facility_fraction harus berada pada (0, 1)")


@dataclass
class SyntheticBenchmarkGroundTruth(SyntheticGroundTruth):
    """Labels for claims, event groups, and their derived facility outcomes."""

    facility_labels: list[dict[str, Any]] | None = None


def _apply_facility_features(record: dict[str, Any], facility: dict[str, Any]) -> None:
    record.update({
        "facility_id": facility["facility_id"],
        "province_code": facility["province_code"],
        "municipality_code": facility["municipality_code"],
        "facility_ownership": facility["facility_ownership"],
        "facility_type": facility["facility_type"],
        "facility_class": facility["facility_class"],
        "facility_daily_capacity": facility["daily_capacity_units"],
    })


def generate_synthetic_benchmark_dataset(
    config: SyntheticGeneratorConfig | None = None,
    profile: SyntheticBenchmarkProfile | None = None,
) -> GeneratedSyntheticDataset:
    """Create deterministic v4 features and separately labeled facility controls.

    Facility positive selection and event placement use seeded RNGs. Total
    claims per facility are balanced to differ by at most one. Scenario groups
    remain colocated where the detector semantics need a shared facility.
    """
    config = config or SyntheticGeneratorConfig.proposal_target()
    profile = profile or SyntheticBenchmarkProfile()
    if config.facility_count < 2:
        raise ValueError("Benchmark fasilitas memerlukan minimal dua fasilitas")

    dataset = generate_synthetic_dataset(config)
    facilities_by_id = {item["facility_id"]: item for item in dataset.facilities}
    facility_ids = sorted(facilities_by_id)
    claim_rows = {row["case_id"]: row for row in dataset.records}
    labels_by_id = {label["case_id"]: label for label in dataset.ground_truth.claim_labels}
    if len(claim_rows) != len(dataset.records) or set(claim_rows) != set(labels_by_id):
        raise ValueError("Generator v3 menghasilkan ID klaim/label yang tidak konsisten")

    anomaly_ids = {
        case_id for case_id, label in labels_by_id.items()
        if label["is_synthetic_anomaly"] is True
    }
    if not anomaly_ids:
        raise ValueError("Benchmark fasilitas memerlukan label anomali sintetis")
    rng = random.Random(config.seed ^ 0x5A17_2026)
    positive_facility_count = min(
        len(facility_ids) - 1,
        len(anomaly_ids),
        max(1, math.floor(len(facility_ids) * profile.positive_facility_fraction + 0.5)),
    )
    facility_strata: dict[str, list[str]] = {}
    for facility_id, facility in facilities_by_id.items():
        facility_strata.setdefault(str(facility["facility_type"]), []).append(facility_id)
    quota_rows = []
    selected_quota = 0
    for facility_type, members in sorted(facility_strata.items()):
        raw_quota = len(members) * positive_facility_count / len(facility_ids)
        quota = math.floor(raw_quota)
        selected_quota += quota
        quota_rows.append([facility_type, members, quota, raw_quota - quota, rng.random()])
    remainder = positive_facility_count - selected_quota
    for row in sorted(quota_rows, key=lambda item: (-item[3], item[4]))[:remainder]:
        row[2] += 1
    positive_facility_ids = {
        facility_id
        for _facility_type, members, quota, _remainder_fraction, _tie_break in quota_rows
        for facility_id in rng.sample(members, quota)
    }
    negative_facility_ids = sorted(set(facility_ids) - positive_facility_ids)

    # Events, not claim IDs, determine colocation. Multi-claim scenario groups
    # stay together; independent evidence scenarios are singleton events.
    events: list[tuple[list[str], str]] = []
    grouped_anomaly_ids: set[str] = set()
    for group in dataset.ground_truth.group_labels:
        if group.get("is_synthetic_anomaly") is not True:
            continue
        members = list(group["case_ids"])
        if not members or any(case_id not in anomaly_ids for case_id in members):
            raise ValueError("Keanggotaan grup anomali sintetis tidak valid")
        if grouped_anomaly_ids.intersection(members):
            raise ValueError("Klaim anomali muncul pada lebih dari satu grup")
        grouped_anomaly_ids.update(members)
        events.append((members, str(group["scenario_code"])))
    for case_id in sorted(anomaly_ids - grouped_anomaly_ids):
        scenario = labels_by_id[case_id].get("primary_scenario")
        events.append(([case_id], str(scenario)))
    if len(events) < positive_facility_count:
        raise ValueError("Jumlah fasilitas positif benchmark tidak boleh melebihi jumlah kejadian anomali")
    rng.shuffle(events)

    anomaly_load: Counter[str] = Counter()
    anomaly_facility_by_claim: dict[str, str] = {}
    for members, _scenario in events:
        least_load = min(anomaly_load[facility_id] for facility_id in positive_facility_ids)
        tied = sorted(
            facility_id for facility_id in positive_facility_ids
            if anomaly_load[facility_id] == least_load
        )
        facility_id = rng.choice(tied)
        facility = facilities_by_id[facility_id]
        for case_id in members:
            row = claim_rows[case_id]
            _apply_facility_features(row, facility)
            if labels_by_id[case_id].get("primary_scenario") == "mixed_light_severe":
                excess = 1 if labels_by_id[case_id].get("intensity_level") == "light" else 8
                row["service_units"] = int(facility["daily_capacity_units"]) + excess
            anomaly_facility_by_claim[case_id] = facility_id
        anomaly_load[facility_id] += len(members)

    # The stipulated legitimate repeat group stays non-anomalous and is placed
    # on a negative-control facility so it cannot change facility ground truth.
    control_group = next(
        (group for group in dataset.ground_truth.group_labels if group.get("scenario_code") == "legitimate_repeat_control"),
        None,
    )
    control_claim_ids: set[str] = set()
    if control_group is not None:
        control_claim_ids = set(control_group["case_ids"])
        control_facility_id = rng.choice(negative_facility_ids)
        for case_id in control_claim_ids:
            if labels_by_id[case_id]["is_synthetic_anomaly"]:
                raise ValueError("Kontrol repeat sah harus berlabel negatif")
            _apply_facility_features(claim_rows[case_id], facilities_by_id[control_facility_id])

    # Balance total facility claim counts independently of positivity, avoiding
    # a volume-only shortcut for ranking. Seeded remainder placement is stable.
    loads = {facility_id: config.claim_count // len(facility_ids) for facility_id in facility_ids}
    remainder_facilities = facility_ids.copy()
    rng.shuffle(remainder_facilities)
    for facility_id in remainder_facilities[:config.claim_count % len(facility_ids)]:
        loads[facility_id] += 1
    assigned_counts = Counter(anomaly_facility_by_claim.values())
    if control_claim_ids:
        control_facility_id = claim_rows[next(iter(control_claim_ids))]["facility_id"]
        assigned_counts[control_facility_id] += len(control_claim_ids)
    if any(assigned_counts[facility_id] > loads[facility_id] for facility_id in facility_ids):
        raise ValueError("Jumlah kejadian anomali melebihi kapasitas klaim fasilitas benchmark")

    normal_ids = [
        case_id for case_id, label in labels_by_id.items()
        if label["is_synthetic_anomaly"] is False and case_id not in control_claim_ids
    ]
    rng.shuffle(normal_ids)
    slots = [
        facility_id
        for facility_id in facility_ids
        for _ in range(loads[facility_id] - assigned_counts[facility_id])
    ]
    rng.shuffle(slots)
    if len(slots) != len(normal_ids):
        raise ValueError("Alokasi slot fasilitas tidak sesuai jumlah klaim normal")
    for case_id, facility_id in zip(normal_ids, slots):
        _apply_facility_features(claim_rows[case_id], facilities_by_id[facility_id])

    # Recalculate this observable feature after facility assignment. It is not
    # used as ground truth and contains no label information.
    daily_counts = Counter((row["facility_id"], row["service_date"]) for row in dataset.records)
    for row in dataset.records:
        row["facility_daily_claim_count"] = daily_counts[(row["facility_id"], row["service_date"])]

    anomaly_counts_by_facility: Counter[str] = Counter(anomaly_facility_by_claim.values())
    scenario_counts_by_facility: dict[str, Counter[str]] = {key: Counter() for key in facility_ids}
    for case_id, facility_id in anomaly_facility_by_claim.items():
        scenario = labels_by_id[case_id]["primary_scenario"]
        scenario_counts_by_facility[facility_id][str(scenario)] += 1
    facility_labels = [
        {
            "facility_id": facility_id,
            "is_synthetic_anomaly_facility": facility_id in positive_facility_ids,
            "anomaly_claim_count": anomaly_counts_by_facility[facility_id],
            "anomaly_claim_count_by_scenario": dict(sorted(scenario_counts_by_facility[facility_id].items())),
        }
        for facility_id in facility_ids
    ]
    dataset.ground_truth = SyntheticBenchmarkGroundTruth(
        claim_labels=dataset.ground_truth.claim_labels,
        group_labels=dataset.ground_truth.group_labels,
        facility_labels=facility_labels,
    )
    dataset.metadata = {
        **dataset.metadata,
        "generator_version": BENCHMARK_GENERATOR_VERSION,
        "base_generator_version": "3",
        "benchmark_profile": BENCHMARK_PROFILE,
        "positive_facility_fraction": profile.positive_facility_fraction,
        "realized_positive_facility_fraction": positive_facility_count / len(facility_ids),
        "positive_facility_count": positive_facility_count,
        "facility_claim_count_min": min(loads.values()),
        "facility_claim_count_max": max(loads.values()),
    }
    return dataset
