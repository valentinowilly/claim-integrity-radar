"""Run the proposal-sized generator benchmark without printing records."""

import json
import math
from collections import Counter
from statistics import median
from time import perf_counter
import tracemalloc

from app.data_sources.synthetic_generator import SCENARIO_CODES, SyntheticGeneratorConfig, generate_synthetic_dataset


def main() -> None:
    config = SyntheticGeneratorConfig.proposal_target()
    tracemalloc.start()
    started = perf_counter()
    dataset = generate_synthetic_dataset(config)
    elapsed_seconds = perf_counter() - started
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    facility_counts = Counter(row["facility_id"] for row in dataset.records)
    facility_distribution = sorted(facility_counts.values())
    percentile_95 = facility_distribution[math.ceil(0.95 * len(facility_distribution)) - 1]
    group_labels = dataset.ground_truth.group_labels
    group_size_counts: dict[str, dict[str, int]] = {}
    group_counts: Counter[str] = Counter()
    for group in group_labels:
        scenario = group["scenario_code"]
        group_counts[scenario] += 1
        sizes = group_size_counts.setdefault(scenario, {})
        size = str(len(group["case_ids"]))
        sizes[size] = sizes.get(size, 0) + 1
    scenario_claim_counts = Counter(
        label["primary_scenario"]
        for label in dataset.ground_truth.claim_labels
        if label["is_synthetic_anomaly"]
    )
    service_dates = [row["service_date"] for row in dataset.records]
    summary = {
        "seed": dataset.metadata["seed"],
        "generator_version": dataset.metadata["generator_version"],
        "facilities": len(dataset.facilities),
        "claims": len(dataset.records),
        "anomalous_claims": sum(label["is_synthetic_anomaly"] for label in dataset.ground_truth.claim_labels),
        "scenario_claim_counts": dict(sorted(scenario_claim_counts.items())),
        "scenario_group_counts": {
            **{scenario: group_counts[scenario] for scenario in SCENARIO_CODES},
            "legitimate_repeat_control": group_counts["legitimate_repeat_control"],
        },
        "group_size_distributions": {
            **{
                scenario: dict(sorted(group_size_counts.get(scenario, {}).items(), key=lambda item: int(item[0])))
                for scenario in SCENARIO_CODES
            },
            "legitimate_repeat_control": dict(sorted(
                group_size_counts.get("legitimate_repeat_control", {}).items(),
                key=lambda item: int(item[0]),
            )),
        },
        "facility_claim_count_distribution": {
            "facility_count": len(facility_distribution),
            "min": facility_distribution[0],
            "median": median(facility_distribution),
            "p95": percentile_95,
            "max": facility_distribution[-1],
        },
        "service_date_range": {"from": min(service_dates), "to": max(service_dates)},
        "elapsed_seconds": round(elapsed_seconds, 3),
        "python_tracemalloc_current_mib": round(current_bytes / (1024 * 1024), 2),
        "python_tracemalloc_peak_mib": round(peak_bytes / (1024 * 1024), 2),
        "note": "Synthetic-only benchmark; tracemalloc measures Python allocations, not total process RSS.",
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
