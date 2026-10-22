"""Deterministic artificial benchmark data with isolated scenario labels.

This experiment generator is deliberately separate from ``synthetic.py``. Its
records contain detector features only; scenario ground truth is returned in a
different object and must never be passed to detectors.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
import math
import random
from typing import Any


SCENARIO_CODES = (
    "phantom_physiotherapy",
    "cloning",
    "repeat_billing",
    "action_without_support",
    "mixed_light_severe",
)
_BASE_SCENARIO_SIZES = (1, 2, 2, 1, 2)
_DETECTOR_SIGNATURE_FIELDS = (
    "participant_token", "service_date", "province_code", "municipality_code",
    "facility_ownership", "facility_type", "facility_class", "admission_diagnosis",
    "primary_diagnosis", "claim_group", "procedure_code", "billed_amount",
)
_PATTERN_FIELDS = tuple(field for field in _DETECTOR_SIGNATURE_FIELDS if field != "participant_token")
_LABEL_KEYS = {
    "is_anomalous", "is_synthetic_anomaly", "scenario_label", "scenario_labels",
    "primary_scenario", "scenario_group_id", "scenario_code", "intensity_level",
    "injected_signals", "label_scope", "claim_labels", "group_labels", "ground_truth",
}


@dataclass(frozen=True)
class SyntheticGeneratorConfig:
    """Parameters for a small test dataset or the proposal-sized experiment."""

    seed: int = 2026
    claim_count: int = 250
    facility_count: int = 12
    target_anomaly_rate: float = 0.04
    start_date: date = date(2024, 1, 1)
    end_date: date = date(2024, 12, 31)

    @classmethod
    def proposal_target(cls, seed: int = 2026, target_anomaly_rate: float = 0.04) -> "SyntheticGeneratorConfig":
        """Return the 200-facility, 120,000-claim proposal experiment settings."""
        return cls(seed=seed, claim_count=120_000, facility_count=200, target_anomaly_rate=target_anomaly_rate)


@dataclass
class SyntheticGroundTruth:
    """Scenario labels are separated from records used as detector input."""

    claim_labels: list[dict[str, Any]]
    group_labels: list[dict[str, Any]]


@dataclass
class GeneratedSyntheticDataset:
    """Fresh in-memory experiment data. ``records`` contains features only."""

    facilities: list[dict[str, Any]]
    records: list[dict[str, Any]]
    ground_truth: SyntheticGroundTruth
    metadata: dict[str, Any]


def _rounded_anomaly_count(claim_count: int, rate: float) -> int:
    # Round half up, rather than Python's ties-to-even ``round``.
    return math.floor(claim_count * rate + 0.5)


def _validate(config: SyntheticGeneratorConfig) -> int:
    if config.claim_count < 10 or config.facility_count < 1:
        raise ValueError("claim_count minimal 10 dan facility_count minimal 1")
    if config.facility_count > config.claim_count:
        raise ValueError("facility_count tidak boleh melebihi claim_count")
    if not (0 < config.target_anomaly_rate < 1):
        raise ValueError("target_anomaly_rate harus lebih besar dari 0 dan kurang dari 1")
    if config.start_date > config.end_date:
        raise ValueError("start_date harus tidak melewati end_date")
    target = _rounded_anomaly_count(config.claim_count, config.target_anomaly_rate)
    # Eight labels are needed to instantiate the five scenarios, including two
    # members each for cloning, repeat billing, and the mixed group.
    if target < sum(_BASE_SCENARIO_SIZES) or config.claim_count - target < 2:
        raise ValueError("Konfigurasi harus menyediakan minimal 8 klaim anomali sintetis dan 2 kontrol negatif")
    return target


def _scenario_sizes(target: int) -> dict[str, int]:
    sizes = list(_BASE_SCENARIO_SIZES)
    extra = target - sum(sizes)
    for index in range(extra):
        sizes[index % len(sizes)] += 1
    return dict(zip(SCENARIO_CODES, sizes))


def _facilities(config: SyntheticGeneratorConfig, rng: random.Random) -> list[dict[str, Any]]:
    ownerships = ("synthetic_public", "synthetic_private")
    types = ("synthetic_general", "synthetic_specialty", "synthetic_rehabilitation")
    return [
        {
            "facility_id": f"syn-facility-{index:04d}",
            "province_code": f"SYN-PROV-{(index - 1) % 8 + 1:02d}",
            "municipality_code": f"SYN-CITY-{(index - 1) % 40 + 1:03d}",
            "facility_ownership": ownerships[(index - 1) % len(ownerships)],
            "facility_type": types[(index - 1) % len(types)],
            "facility_class": f"synthetic-class-{(index - 1) % 4 + 1}",
            "daily_capacity_units": rng.randint(24, 64),
        }
        for index in range(1, config.facility_count + 1)
    ]


def _make_feature_record(
    index: int, config: SyntheticGeneratorConfig, rng: random.Random,
    facilities: list[dict[str, Any]],
) -> dict[str, Any]:
    facility = rng.choice(facilities)
    day_count = (config.end_date - config.start_date).days
    service_day = config.start_date + timedelta(days=rng.randint(0, day_count))
    service_hour = rng.randint(7, 18)
    service_minute = rng.randint(0, 59)
    service_type = rng.choice(("physiotherapy", "outpatient", "imaging", "laboratory", "minor_procedure"))
    evidence = ["procedure_order", "clinical_note"]
    required_evidence = ["procedure_order", "clinical_note"]
    if service_type == "physiotherapy":
        evidence.append("therapy_session_log")
        required_evidence = ["therapy_session_log", "clinical_note"]
    return {
        "claim_id": f"syn-claim-{index + 1:06d}",
        "case_id": f"syn-claim-{index + 1:06d}",
        "facility_id": facility["facility_id"],
        "participant_token": f"syn-participant-{index + 1:06d}",
        "service_date": service_day.isoformat(),
        "service_timestamp": f"{service_day.isoformat()}T{service_hour:02d}:{service_minute:02d}:00",
        "province_code": facility["province_code"],
        "municipality_code": facility["municipality_code"],
        "facility_ownership": facility["facility_ownership"],
        "facility_type": facility["facility_type"],
        "facility_class": facility["facility_class"],
        "admission_diagnosis": f"SYN-ADM-{rng.randint(1, 9999):04d}",
        "primary_diagnosis": f"SYN-DX-{rng.randint(1, 9999):04d}",
        "claim_group": f"SYN-GROUP-{rng.randint(1, 12):02d}",
        "procedure_code": f"SYN-PROC-{rng.randint(1, 999):03d}",
        "billed_amount": f"{rng.randrange(25_000, 2_000_001, 250):.2f}",
        "service_type": service_type,
        "service_units": rng.randint(1, 6),
        "facility_daily_capacity": facility["daily_capacity_units"],
        "supporting_evidence_required": required_evidence,
        "supporting_evidence_types": evidence,
        "supporting_evidence_present": True,
        "supporting_evidence_recording_status": "recorded",
    }


def _partition_groups(indices: list[int], rng: random.Random) -> list[list[int]]:
    """Split a scenario's members into deterministic bounded groups of 2 or 3."""
    remaining = list(indices)
    rng.shuffle(remaining)
    groups: list[list[int]] = []
    while remaining:
        if len(remaining) <= 3:
            size = len(remaining)
        elif len(remaining) == 4:
            size = 2
        else:
            size = rng.choice((2, 3))
        groups.append(remaining[:size])
        del remaining[:size]
    return groups


def generate_synthetic_dataset(config: SyntheticGeneratorConfig | None = None) -> GeneratedSyntheticDataset:
    """Generate deterministic artificial features and separate scenario labels.

    Detector functions should receive only ``result.records``. Labels live in
    ``result.ground_truth`` and refer to the artificial ``claim_id``/``case_id``.
    """
    config = config or SyntheticGeneratorConfig()
    anomaly_count = _validate(config)
    rng = random.Random(config.seed)
    facilities = _facilities(config, rng)
    records = [_make_feature_record(i, config, rng, facilities) for i in range(config.claim_count)]
    sizes = _scenario_sizes(anomaly_count)

    scenario_indices: dict[str, list[int]] = {}
    shuffled_indices = list(range(config.claim_count))
    rng.shuffle(shuffled_indices)
    offset = 0
    for scenario in SCENARIO_CODES:
        scenario_indices[scenario] = shuffled_indices[offset:offset + sizes[scenario]]
        offset += sizes[scenario]

    group_labels: list[dict[str, Any]] = []
    claim_scenario: dict[int, tuple[str, str | None, str]] = {}
    group_numbers = Counter()

    def add_group(scenario: str, indices: list[int], intensities: list[str], signals: list[str]) -> str:
        group_numbers[scenario] += 1
        group_id = f"syn-group-{scenario}-{group_numbers[scenario]:04d}"
        case_ids = [records[index]["case_id"] for index in indices]
        for index, intensity in zip(indices, intensities):
            claim_scenario[index] = (scenario, group_id, intensity)
        group_labels.append({
            "group_id": group_id,
            "scenario_code": scenario,
            "case_ids": case_ids,
            "label_scope": "claim_group",
            "is_synthetic_anomaly": True,
            "intensity_levels": sorted(set(intensities)),
            "injected_signals": list(signals),
        })
        return group_id

    # Single-claim evidence scenarios have no group relation, so only claim labels apply.
    phantom = scenario_indices["phantom_physiotherapy"]
    for index in phantom:
        row = records[index]
        row.update({
            "service_type": "physiotherapy",
            "supporting_evidence_required": ["therapy_session_log", "clinical_note"],
            "supporting_evidence_types": [],
            "supporting_evidence_present": False,
        })
        claim_scenario[index] = ("phantom_physiotherapy", None, "moderate")

    # Similar-pattern scenario: exact templates across distinct participants;
    # later members add a small selected-field variation.
    clones = scenario_indices["cloning"]
    for clone_group in _partition_groups(clones, rng):
        template = dict(records[clone_group[0]])
        for position, index in enumerate(clone_group[1:], start=1):
            row = records[index]
            for field in _PATTERN_FIELDS:
                row[field] = template[field]
            row["facility_id"] = template["facility_id"]
            row["facility_daily_capacity"] = template["facility_daily_capacity"]
            row["service_type"] = template["service_type"]
            row["service_timestamp"] = template["service_timestamp"]
            row["service_units"] = template["service_units"]
            for field in ("supporting_evidence_required", "supporting_evidence_types"):
                row[field] = template[field].copy()
            row["supporting_evidence_present"] = template["supporting_evidence_present"]
            row["supporting_evidence_recording_status"] = template["supporting_evidence_recording_status"]
            if position % 2:
                row["procedure_code"] = f"{template['procedure_code']}-VAR"
            else:
                row["billed_amount"] = f"{float(template['billed_amount']) + 0.50:.2f}"
        add_group("cloning", clone_group, ["moderate"] * len(clone_group), [
            "similar_pattern_across_synthetic_participants", "controlled_near_duplicate_variation",
        ])

    # Repeat billing scenario: duplicate signature for the same artificial
    # participant/service; IDs stay unique, while signature fields repeat.
    repeats = scenario_indices["repeat_billing"]
    for repeat_group in _partition_groups(repeats, rng):
        repeat_template = dict(records[repeat_group[0]])
        for index in repeat_group[1:]:
            row = records[index]
            for field in _DETECTOR_SIGNATURE_FIELDS:
                row[field] = repeat_template[field]
            row["facility_id"] = repeat_template["facility_id"]
            row["facility_daily_capacity"] = repeat_template["facility_daily_capacity"]
            row["service_type"] = repeat_template["service_type"]
            row["service_timestamp"] = repeat_template["service_timestamp"]
            row["service_units"] = repeat_template["service_units"]
            for field in ("supporting_evidence_required", "supporting_evidence_types"):
                row[field] = repeat_template[field].copy()
            row["supporting_evidence_present"] = repeat_template["supporting_evidence_present"]
            row["supporting_evidence_recording_status"] = repeat_template["supporting_evidence_recording_status"]
        add_group("repeat_billing", repeat_group, ["moderate"] * len(repeat_group), ["repeated_claim_signature"])

    # General actions without the scenario-required supporting documents.
    unsupported = scenario_indices["action_without_support"]
    for index in unsupported:
        row = records[index]
        row.update({
            "service_type": "synthetic_supported_action",
            "supporting_evidence_required": ["procedure_order", "clinical_note"],
            "supporting_evidence_types": [],
            "supporting_evidence_present": False,
        })
        claim_scenario[index] = ("action_without_support", None, "moderate")

    # Mixed group: shared pattern, synthetic service units over facility
    # capacity, with a light/severe split and missing evidence on severe rows.
    mixed = scenario_indices["mixed_light_severe"]
    for mixed_group in _partition_groups(mixed, rng):
        mixed_template = dict(records[mixed_group[0]])
        mixed_intensities: list[str] = []
        for position, index in enumerate(mixed_group):
            row = records[index]
            if position:
                for field in _PATTERN_FIELDS:
                    row[field] = mixed_template[field]
                row["facility_id"] = mixed_template["facility_id"]
                row["facility_daily_capacity"] = mixed_template["facility_daily_capacity"]
            intensity = "light" if position % 2 == 0 else "severe"
            mixed_intensities.append(intensity)
            row["service_type"] = "synthetic_mixed_action"
            row["service_units"] = row["facility_daily_capacity"] + (1 if intensity == "light" else 8)
            row["supporting_evidence_required"] = ["procedure_order", "clinical_note"]
            if intensity == "severe":
                row["supporting_evidence_types"] = []
                row["supporting_evidence_present"] = False
                row["supporting_evidence_recording_status"] = "recorded"
            else:
                row["supporting_evidence_types"] = ["procedure_order", "clinical_note"]
                row["supporting_evidence_present"] = True
                row["supporting_evidence_recording_status"] = "recorded"
            row["service_timestamp"] = mixed_template["service_timestamp"]
        add_group("mixed_light_severe", mixed_group, mixed_intensities, [
            "service_units_above_synthetic_capacity", "mixed_supporting_evidence_state",
        ])

    # A negative control intentionally repeats a signature but represents a
    # stipulated legitimate repeat, so it can support future false-positive
    # measurement without changing the anomaly label count.
    negative_indices = [index for index in range(config.claim_count) if index not in claim_scenario]
    controls = rng.sample(negative_indices, 2)
    control_template = dict(records[controls[0]])
    for field in _DETECTOR_SIGNATURE_FIELDS:
        records[controls[1]][field] = control_template[field]
    records[controls[1]]["facility_id"] = control_template["facility_id"]
    records[controls[1]]["facility_daily_capacity"] = control_template["facility_daily_capacity"]
    records[controls[1]]["service_type"] = control_template["service_type"]
    records[controls[1]]["service_timestamp"] = control_template["service_timestamp"]
    records[controls[1]]["service_units"] = control_template["service_units"]
    for field in ("supporting_evidence_required", "supporting_evidence_types"):
        records[controls[1]][field] = control_template[field].copy()
    records[controls[1]]["supporting_evidence_present"] = control_template["supporting_evidence_present"]
    records[controls[1]]["supporting_evidence_recording_status"] = control_template["supporting_evidence_recording_status"]
    group_labels.append({
        "group_id": "syn-group-legitimate-repeat-control-001",
        "scenario_code": "legitimate_repeat_control",
        "case_ids": [records[index]["case_id"] for index in controls],
        "label_scope": "claim_group",
        "is_synthetic_anomaly": False,
        "intensity_levels": ["none"],
        "injected_signals": ["repeated_signature_stipulated_as_legitimate_control"],
    })

    daily_counts = Counter((row["facility_id"], row["service_date"]) for row in records)
    for row in records:
        row["facility_daily_claim_count"] = daily_counts[(row["facility_id"], row["service_date"])]

    claim_labels: list[dict[str, Any]] = []
    for index, row in enumerate(records):
        scenario = claim_scenario.get(index)
        claim_labels.append({
            "claim_id": row["claim_id"],
            "case_id": row["case_id"],
            "is_synthetic_anomaly": scenario is not None,
            "primary_scenario": scenario[0] if scenario else None,
            "scenario_group_id": scenario[1] if scenario else None,
            "intensity_level": scenario[2] if scenario else "none",
        })

    if any(set(record) & _LABEL_KEYS for record in records):
        raise AssertionError("label ground truth tidak boleh menjadi field fitur")

    return GeneratedSyntheticDataset(
        facilities=facilities,
        records=records,
        ground_truth=SyntheticGroundTruth(claim_labels=claim_labels, group_labels=group_labels),
        metadata={
            "generator": "claim_integrity_radar_synthetic_experiment",
            "generator_version": "3",
            "seed": config.seed,
            "claim_count": config.claim_count,
            "facility_count": config.facility_count,
            "target_anomaly_rate": config.target_anomaly_rate,
            "target_anomalous_claim_count": anomaly_count,
            "anomaly_count_rounding": "floor(n * rate + 0.5), half up",
            "period_from": config.start_date.isoformat(),
            "period_to": config.end_date.isoformat(),
            "scenario_claim_counts": sizes,
            "scenario_group_counts": {
                scenario: group_numbers[scenario] for scenario in SCENARIO_CODES
            },
        },
    )
