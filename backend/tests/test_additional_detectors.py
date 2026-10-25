from copy import deepcopy
from datetime import date, timedelta

from app.analytics.capacity import CapacityConfig, detect_capacity_candidates
from app.analytics.evidence_completeness import detect_evidence_completeness
from app.analytics.near_duplicate_claims import NearDuplicateConfig, detect_near_duplicate_claims
from app.analytics.repeat_billing import detect_repeat_billing_candidates
from app.analytics.temporal_patterns import TemporalConfig, detect_temporal_patterns
from app.data_sources.synthetic_generator import SyntheticGeneratorConfig, generate_synthetic_dataset


def _dataset():
    config = SyntheticGeneratorConfig(seed=502, claim_count=250, facility_count=12, target_anomaly_rate=0.04)
    return generate_synthetic_dataset(config)


def test_capacity_detects_synthetic_overage_with_explanation_and_metadata():
    data = _dataset()
    original_records = deepcopy(data.records)
    result = detect_capacity_candidates(data.records, data.facilities)
    mixed_ids = next(group["case_ids"] for group in data.ground_truth.group_labels if group["scenario_code"] == "mixed_light_severe")

    assert result["candidate_count"] >= 1
    assert any(set(mixed_ids).issubset(set(candidate["case_ids"])) for candidate in result["candidates"])
    candidate = next(candidate for candidate in result["candidates"] if set(mixed_ids).issubset(set(candidate["case_ids"])) )
    assert candidate["observed_service_units"] > candidate["capacity_service_units"]
    assert candidate["period"]["unit"] == "day"
    assert "melebihi kapasitas simulasi" in candidate["reason"]
    assert data.records == original_records
    assert "participant_token" not in str(result)


def test_capacity_invalid_or_missing_metadata_is_ineligible_not_a_candidate():
    data = _dataset()
    row = deepcopy(data.records[0])
    facility = next(item for item in data.facilities if item["facility_id"] == row["facility_id"])
    facility["daily_capacity_units"] = "unknown"
    result = detect_capacity_candidates([row], [facility])

    assert result["candidate_count"] == 0
    assert result["ineligible_cases"][0]["case_id"] == row["case_id"]
    assert "tidak valid" in result["ineligible_cases"][0]["reason"]
    missing = detect_capacity_candidates([row], [])
    assert missing["candidate_count"] == 0
    assert "tidak tersedia" in missing["ineligible_cases"][0]["reason"]


def test_near_duplicate_finds_cloning_template_and_small_procedure_variation():
    data = _dataset()
    original_records = deepcopy(data.records)
    result = detect_near_duplicate_claims(data.records)
    clone_ids = set(next(group["case_ids"] for group in data.ground_truth.group_labels if group["scenario_code"] == "cloning"))
    clone_matches = [candidate for candidate in result["candidates"] if set(candidate["case_ids"]).issubset(clone_ids)]
    raw_tokens = {row["participant_token"] for row in data.records}
    raw_signatures = {row["procedure_code"] for row in data.records}

    assert clone_matches
    assert any(candidate["differing_attributes"] for candidate in clone_matches)
    assert all(candidate["matched_attributes"] for candidate in clone_matches)
    assert not any(token in str(result) for token in raw_tokens)
    assert not any(signature in str(result) for signature in raw_signatures)
    assert result == detect_near_duplicate_claims(data.records)
    assert data.records == original_records


def test_near_duplicate_bounds_common_pattern_search_and_output():
    data = _dataset()
    template = data.records[0]
    common = []
    for number in range(12):
        row = deepcopy(template)
        row["case_id"] = f"syn-common-{number:03d}"
        row["claim_id"] = row["case_id"]
        row["participant_token"] = f"syn-other-person-{number:03d}"
        common.append(row)
    result = detect_near_duplicate_claims(common, NearDuplicateConfig(
        max_block_size=3, max_pair_comparisons=5, max_candidates=3,
    ))

    assert result["candidate_count"] <= 3
    assert result["pair_comparisons"] <= 5
    assert result["search_diagnostics"]["oversized_primary_block_count"] > 0
    assert result["search_diagnostics"]["dense_bucket_sample_count"] > 0
    assert result["search_truncated"] is True
    assert result["candidates"], "bounded dense-block sampling should still expose a known match"


def test_near_duplicate_pair_budget_marks_unvisited_small_blocks_unassessed():
    data = _dataset()
    rows = []
    for number in range(8):
        left = deepcopy(data.records[0])
        right = deepcopy(data.records[0])
        for row, suffix, participant in (
            (left, "a", f"fixture-person-{number}-a"),
            (right, "b", f"fixture-person-{number}-b"),
        ):
            row["case_id"] = f"syn-budget-{number:02d}-{suffix}"
            row["claim_id"] = row["case_id"]
            row["participant_token"] = participant
            row["municipality_code"] = f"municipality-{number:02d}"
            row["primary_diagnosis"] = f"diagnosis-{number:02d}"
        rows.extend((left, right))

    result = detect_near_duplicate_claims(rows, NearDuplicateConfig(
        max_pair_comparisons=1, max_candidates=10,
    ))
    unassessed = set(result["unassessed_case_ids"])

    assert result["pair_comparisons"] == 1
    assert result["search_truncated"] is True
    assert result["search_diagnostics"]["comparison_limit_hit"] is True
    assert unassessed
    assert len(unassessed) >= 2


def test_near_duplicate_known_positive_and_similar_negative_control_are_distinguished():
    data = _dataset()
    positive_left = deepcopy(data.records[0])
    positive_right = deepcopy(data.records[0])
    negative_left = deepcopy(data.records[1])
    negative_right = deepcopy(data.records[1])
    for row, case_id, participant, municipality, diagnosis in (
        (positive_left, "syn-known-positive-a", "fixture-person-a", "fixture-muni-p", "fixture-dx-p"),
        (positive_right, "syn-known-positive-b", "fixture-person-b", "fixture-muni-p", "fixture-dx-p"),
        (negative_left, "syn-known-negative-a", "fixture-person-c", "fixture-muni-n", "fixture-dx-n"),
        (negative_right, "syn-known-negative-b", "fixture-person-d", "fixture-muni-n", "fixture-dx-n"),
    ):
        row["case_id"] = case_id
        row["claim_id"] = case_id
        row["participant_token"] = participant
        row["service_date"] = "2024-08-11"
        row["municipality_code"] = municipality
        row["primary_diagnosis"] = diagnosis
    positive_right["procedure_code"] = "SYN-PROC-VARIANT"
    negative_right["procedure_code"] = "SYN-OTHER-PROC"
    negative_right["claim_group"] = "SYN-OTHER-GROUP"
    negative_right["facility_class"] = "SYN-OTHER-CLASS"

    result = detect_near_duplicate_claims(
        [positive_left, positive_right, negative_left, negative_right],
        NearDuplicateConfig(max_pair_comparisons=20),
    )
    pairs = {frozenset(candidate["case_ids"]) for candidate in result["candidates"]}

    assert frozenset({"syn-known-positive-a", "syn-known-positive-b"}) in pairs
    assert frozenset({"syn-known-negative-a", "syn-known-negative-b"}) not in pairs
    assert result["search_truncated"] is False


def test_near_duplicate_dense_block_refinement_finds_known_cross_participant_pair():
    data = _dataset()
    template = deepcopy(data.records[0])
    rows = []
    for number in range(30):
        row = deepcopy(template)
        row["case_id"] = f"syn-dense-{number:03d}"
        row["claim_id"] = row["case_id"]
        row["participant_token"] = f"syn-member-{number:03d}"
        if number == 29:
            row["procedure_code"] = "SYN-PROC-NEAR-VARIATION"
        rows.append(row)
    config = NearDuplicateConfig(max_block_size=3, max_pair_comparisons=100, max_candidates=100)

    first = detect_near_duplicate_claims(rows, config)
    second = detect_near_duplicate_claims(rows, config)
    expected = {"syn-dense-000", "syn-dense-029"}

    assert any(set(candidate["case_ids"]) == expected for candidate in first["candidates"])
    assert first == second
    assert first["search_truncated"] is True
    assert first["search_diagnostics"]["oversized_refinement_bucket_count"] >= 1


def test_exact_repeat_detector_remains_independent_of_near_search_truncation():
    from fixtures.synthetic_claims import synthetic_claims_copy

    rows = synthetic_claims_copy()
    exact_before = detect_repeat_billing_candidates(rows)
    near = detect_near_duplicate_claims(rows, NearDuplicateConfig(max_pair_comparisons=1))
    exact_after = detect_repeat_billing_candidates(rows)

    assert near["search_truncated"] is True
    assert exact_before == exact_after
    assert any(
        set(group["case_ids"]) == {"syn-repeat-001", "syn-repeat-002"}
        for group in exact_after["candidate_groups"]
    )


def test_temporal_detector_finds_short_repeats_and_uniform_synthetic_minute():
    data = _dataset()
    original_records = deepcopy(data.records)
    result = detect_temporal_patterns(data.records)
    patterns = {candidate["pattern_type"] for candidate in result["candidates"]}
    repeat_ids = set(next(group["case_ids"] for group in data.ground_truth.group_labels if group["scenario_code"] == "repeat_billing"))
    clone_ids = set(next(group["case_ids"] for group in data.ground_truth.group_labels if group["scenario_code"] == "cloning"))
    repeat_candidate = next(candidate for candidate in result["candidates"] if candidate["pattern_type"] == "short_window_repeat" and set(candidate["case_ids"]).issubset(repeat_ids))
    uniform_candidate = next(candidate for candidate in result["candidates"] if candidate["pattern_type"] == "uniform_service_minute" and set(candidate["case_ids"]).issubset(clone_ids))

    assert "short_window_repeat" in patterns
    assert "uniform_service_minute" in patterns
    assert repeat_candidate["supporting_values"]["claim_count"] >= 2
    assert uniform_candidate["supporting_values"]["distinct_participant_count"] >= 3
    assert "tidak menyimpulkan" in " ".join(result["limitations"])
    assert "participant_token" not in str(result)
    assert data.records == original_records


def test_regular_weekly_service_is_not_marked_by_short_window_rule():
    data = _dataset()
    template = deepcopy(data.records[0])
    rows = []
    initial = date.fromisoformat(template["service_date"])
    for number in range(3):
        row = deepcopy(template)
        row["case_id"] = f"syn-weekly-{number:03d}"
        row["claim_id"] = row["case_id"]
        row["participant_token"] = "syn-weekly-participant"
        day = initial + timedelta(days=number * 7)
        row["service_date"] = day.isoformat()
        row["service_timestamp"] = f"{day.isoformat()}T09:00:00"
        rows.append(row)
    result = detect_temporal_patterns(rows, TemporalConfig(repeat_window_days=3))

    assert result["candidate_count"] == 0


def test_evidence_checker_uses_recording_status_and_scenario_service_rules():
    data = _dataset()
    original_records = deepcopy(data.records)
    result = detect_evidence_completeness(data.records)
    phantom_ids = {label["case_id"] for label in data.ground_truth.claim_labels if label["primary_scenario"] == "phantom_physiotherapy"}
    unsupported_ids = {label["case_id"] for label in data.ground_truth.claim_labels if label["primary_scenario"] == "action_without_support"}
    candidate_ids = {candidate["case_id"] for candidate in result["candidates"]}

    assert phantom_ids.issubset(candidate_ids)
    assert unsupported_ids.issubset(candidate_ids)
    assert all(candidate["missing_evidence"] for candidate in result["candidates"])
    assert all("fraud" in " ".join(candidate["limitations"]) for candidate in result["candidates"])
    assert data.records == original_records
    assert "participant_token" not in str(result)


def test_evidence_checker_distinguishes_not_recorded_from_recorded_empty_and_invalid():
    data = _dataset()
    phantom_labels = [label for label in data.ground_truth.claim_labels if label["primary_scenario"] == "phantom_physiotherapy"]
    rows_by_id = {row["case_id"]: deepcopy(row) for row in data.records}
    not_recorded = rows_by_id[phantom_labels[0]["case_id"]]
    not_recorded["supporting_evidence_recording_status"] = "not_recorded"
    invalid = rows_by_id[phantom_labels[-1]["case_id"]]
    invalid["supporting_evidence_types"] = None
    result = detect_evidence_completeness([not_recorded, invalid])

    assert result["candidate_count"] == 0
    assert result["unassessed_cases"][0]["case_id"] == not_recorded["case_id"]
    assert result["ineligible_cases"][0]["case_id"] == invalid["case_id"]


def test_evidence_rule_outside_configured_service_scope_is_explicitly_not_applicable():
    data = _dataset()
    row = deepcopy(data.records[0])
    row["service_type"] = "synthetic_service_without_rule"
    result = detect_evidence_completeness([row])

    assert result["not_applicable_cases"] == [{
        "case_id": row["case_id"],
        "reason": "Belum ada aturan bukti untuk jenis layanan ini.",
    }]
    assert result["unassessed_cases"] == []
    assert result["candidates"] == []
