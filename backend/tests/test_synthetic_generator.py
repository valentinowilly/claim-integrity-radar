from copy import deepcopy
from datetime import date

from app.analytics.repeat_billing import detect_repeat_billing_candidates
from app.analytics.similar_claim_pattern import detect_similar_claim_patterns
from app.data_sources.synthetic_generator import (
    SCENARIO_CODES,
    SyntheticGeneratorConfig,
    generate_synthetic_dataset,
)


def _small_config(seed: int = 731) -> SyntheticGeneratorConfig:
    return SyntheticGeneratorConfig(
        seed=seed,
        claim_count=250,
        facility_count=12,
        target_anomaly_rate=0.04,
    )


def test_same_seed_and_config_produce_same_features_and_labels():
    left = generate_synthetic_dataset(_small_config())
    right = generate_synthetic_dataset(_small_config())

    assert left.facilities == right.facilities
    assert left.records == right.records
    assert left.ground_truth.claim_labels == right.ground_truth.claim_labels
    assert left.ground_truth.group_labels == right.ground_truth.group_labels
    assert left.metadata == right.metadata


def test_counts_ids_references_dates_and_target_rounding():
    config = _small_config()
    result = generate_synthetic_dataset(config)
    facility_ids = {facility["facility_id"] for facility in result.facilities}
    claim_ids = [row["claim_id"] for row in result.records]
    labels = result.ground_truth.claim_labels
    anomaly_labels = [label for label in labels if label["is_synthetic_anomaly"]]

    assert len(result.facilities) == config.facility_count
    assert len(result.records) == config.claim_count
    assert len(set(claim_ids)) == len(claim_ids)
    assert len(anomaly_labels) == 10  # floor(250 * .04 + .5)
    assert result.metadata["target_anomalous_claim_count"] == 10
    assert all(row["facility_id"] in facility_ids for row in result.records)
    assert all(row["claim_id"].startswith("syn-claim-") for row in result.records)
    assert all(row["facility_id"].startswith("syn-facility-") for row in result.records)
    assert all(row["participant_token"].startswith("syn-participant-") for row in result.records)
    assert all(date(2024, 1, 1) <= date.fromisoformat(row["service_date"]) <= date(2024, 12, 31) for row in result.records)
    assert all(label["case_id"] in set(claim_ids) for label in labels)
    assert all(case_id in set(claim_ids) for group in result.ground_truth.group_labels for case_id in group["case_ids"])


def test_all_five_scenarios_and_negative_repeat_control_are_present():
    result = generate_synthetic_dataset(_small_config())
    groups = result.ground_truth.group_labels
    claim_labels = result.ground_truth.claim_labels
    scenario_labels = {label["primary_scenario"] for label in claim_labels if label["is_synthetic_anomaly"]}
    group_scenarios = {group["scenario_code"] for group in groups}

    assert set(SCENARIO_CODES).issubset(scenario_labels)
    assert {"cloning", "repeat_billing", "mixed_light_severe"}.issubset(group_scenarios)
    assert "phantom_physiotherapy" not in group_scenarios
    assert "action_without_support" not in group_scenarios
    assert all(group["is_synthetic_anomaly"] for group in groups if group["scenario_code"] != "legitimate_repeat_control")
    control = next(group for group in groups if group["scenario_code"] == "legitimate_repeat_control")
    assert control["is_synthetic_anomaly"] is False
    control_label_map = {row["case_id"]: row for row in claim_labels}
    assert all(control_label_map[case_id]["is_synthetic_anomaly"] is False for case_id in control["case_ids"])

    record_by_id = {row["case_id"]: row for row in result.records}
    labels_by_scenario = {}
    for label in claim_labels:
        if label["is_synthetic_anomaly"]:
            labels_by_scenario.setdefault(label["primary_scenario"], []).append(label)
    phantom = labels_by_scenario["phantom_physiotherapy"]
    assert all(record_by_id[label["case_id"]]["service_type"] == "physiotherapy" for label in phantom)
    assert all(record_by_id[label["case_id"]]["supporting_evidence_present"] is False for label in phantom)
    unsupported = labels_by_scenario["action_without_support"]
    assert all(record_by_id[label["case_id"]]["service_type"] == "synthetic_supported_action" for label in unsupported)
    assert all(record_by_id[label["case_id"]]["supporting_evidence_types"] == [] for label in unsupported)
    assert all(label["scenario_group_id"] is None for label in phantom + unsupported)
    clone_group = next(group for group in groups if group["scenario_code"] == "cloning")
    clone_rows = [record_by_id[case_id] for case_id in clone_group["case_ids"]]
    assert len({row["participant_token"] for row in clone_rows}) == len(clone_rows)
    assert all(row["service_date"] == clone_rows[0]["service_date"] for row in clone_rows)
    assert any(row["procedure_code"] != clone_rows[0]["procedure_code"] or row["billed_amount"] != clone_rows[0]["billed_amount"] for row in clone_rows[1:])
    repeat_group = next(group for group in groups if group["scenario_code"] == "repeat_billing")
    repeat_rows = [record_by_id[case_id] for case_id in repeat_group["case_ids"]]
    signature_fields = (
        "participant_token", "service_date", "province_code", "municipality_code",
        "facility_ownership", "facility_type", "facility_class", "admission_diagnosis",
        "primary_diagnosis", "claim_group", "procedure_code", "billed_amount",
    )
    assert len({tuple(row[field] for field in signature_fields) for row in repeat_rows}) == 1
    control_rows = [record_by_id[case_id] for case_id in control["case_ids"]]
    assert len({tuple(row[field] for field in signature_fields) for row in control_rows}) == 1
    mixed_group = next(group for group in groups if group["scenario_code"] == "mixed_light_severe")
    assert set(mixed_group["intensity_levels"]) == {"light", "severe"}


def test_scenario_groups_are_many_bounded_events_and_features_are_scattered():
    config = SyntheticGeneratorConfig(seed=42, claim_count=2500, facility_count=12, target_anomaly_rate=0.04)
    result = generate_synthetic_dataset(config)
    labels = result.ground_truth.claim_labels
    groups = result.ground_truth.group_labels
    anomaly_ids = {label["case_id"] for label in labels if label["is_synthetic_anomaly"]}
    id_to_index = {row["case_id"]: index for index, row in enumerate(result.records)}
    event_groups = [group for group in groups if group["scenario_code"] != "legitimate_repeat_control"]

    assert len(anomaly_ids) == 100
    assert len({id_to_index[case_id] // 250 for case_id in anomaly_ids}) == 10
    assert all(2 <= len(group["case_ids"]) <= 3 for group in event_groups)
    assert len([group for group in event_groups if group["scenario_code"] == "repeat_billing"]) > 1
    assert len([group for group in event_groups if group["scenario_code"] == "cloning"]) > 1
    assert all(len(group["case_ids"]) <= 3 for group in groups)

    records_by_id = {row["case_id"]: row for row in result.records}
    signature_fields = (
        "participant_token", "service_date", "province_code", "municipality_code",
        "facility_ownership", "facility_type", "facility_class", "admission_diagnosis",
        "primary_diagnosis", "claim_group", "procedure_code", "billed_amount",
    )
    repeat_groups = [group for group in event_groups if group["scenario_code"] == "repeat_billing"]
    assert all(
        len({tuple(records_by_id[case_id][field] for field in signature_fields) for case_id in group["case_ids"]}) == 1
        for group in repeat_groups
    )
    clone_groups = [group for group in event_groups if group["scenario_code"] == "cloning"]
    assert all(
        len({records_by_id[case_id]["participant_token"] for case_id in group["case_ids"]}) == len(group["case_ids"])
        for group in clone_groups
    )
    assert all(
        len({tuple(records_by_id[case_id][field] for field in signature_fields[1:]) for case_id in group["case_ids"]}) > 1
        for group in clone_groups
    )

    facility_counts = {}
    quarter_counts = [0, 0, 0, 0]
    scenario_facilities = {"cloning": set(), "repeat_billing": set(), "mixed_light_severe": set()}
    for row in result.records:
        facility_counts[row["facility_id"]] = facility_counts.get(row["facility_id"], 0) + 1
        month = int(row["service_date"][5:7])
        quarter_counts[(month - 1) // 3] += 1
    records_by_id = {row["case_id"]: row for row in result.records}
    for group in event_groups:
        if group["scenario_code"] in scenario_facilities:
            scenario_facilities[group["scenario_code"]].add(records_by_id[group["case_ids"][0]]["facility_id"])

    assert max(facility_counts.values()) / min(facility_counts.values()) < 1.6
    assert min(quarter_counts) > config.claim_count * 0.20
    assert all(len(facilities) >= 3 for facilities in scenario_facilities.values())
    assert result.metadata["generator_version"] == "3"


def test_truth_is_not_in_detector_features_and_isolation_is_preserved():
    result = generate_synthetic_dataset(_small_config())
    original_truth = deepcopy(result.ground_truth.claim_labels)
    forbidden_names = {
        "is_anomalous", "is_synthetic_anomaly", "scenario_label", "scenario_labels",
        "primary_scenario", "scenario_group_id", "scenario_code", "intensity_level",
        "injected_signals", "label_scope", "claim_labels", "group_labels", "ground_truth",
    }

    assert all(not (set(row) & forbidden_names) for row in result.records)
    result.records[0]["service_date"] = "1999-01-01"
    assert result.ground_truth.claim_labels == original_truth
    result.ground_truth.claim_labels[0]["is_synthetic_anomaly"] = "changed"
    assert result.records[0]["service_date"] == "1999-01-01"


def test_detector_input_works_and_does_not_mutate_feature_records():
    result = generate_synthetic_dataset(_small_config())
    original = deepcopy(result.records)

    repeat = detect_repeat_billing_candidates(result.records)
    similar = detect_similar_claim_patterns(result.records)

    assert repeat["input_record_count"] == len(result.records)
    assert similar["input_record_count"] == len(result.records)
    assert repeat["candidate_groups"]
    assert similar["candidate_groups"]
    assert result.records == original
    raw_tokens = {row["participant_token"] for row in result.records}
    repeat_text = str(repeat["candidate_groups"])
    similar_text = str(similar["candidate_groups"])
    assert not any(token in repeat_text for token in raw_tokens)
    assert not any(token in similar_text for token in raw_tokens)


def test_invalid_small_configuration_is_rejected_with_scenario_reason():
    config = SyntheticGeneratorConfig(claim_count=100, facility_count=10, target_anomaly_rate=0.04)
    try:
        generate_synthetic_dataset(config)
    except ValueError as error:
        assert "minimal 8 klaim anomali" in str(error)
    else:
        raise AssertionError("Konfigurasi yang tidak dapat memuat lima skenario semestinya ditolak")


def test_proposal_target_configuration_is_explicit_without_materializing_it():
    config = SyntheticGeneratorConfig.proposal_target(seed=91)
    assert config.facility_count == 200
    assert config.claim_count == 120_000
    assert config.target_anomaly_rate == 0.04
    assert config.start_date == date(2024, 1, 1)
    assert config.end_date == date(2024, 12, 31)
