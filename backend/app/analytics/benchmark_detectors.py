"""Benchmark the isolated detectors on generated data; prints aggregates only."""

import argparse
import json
from time import perf_counter
import tracemalloc

from app.analytics.capacity import detect_capacity_candidates
from app.analytics.evidence_completeness import detect_evidence_completeness
from app.analytics.near_duplicate_claims import detect_near_duplicate_claims
from app.analytics.repeat_billing import detect_repeat_billing_candidates
from app.analytics.audit_priority import build_audit_priority_queue
from app.analytics.risk_scoring import score_claims
from app.analytics.similar_claim_pattern import detect_similar_claim_patterns
from app.analytics.temporal_patterns import detect_temporal_patterns
from app.data_sources.synthetic_generator import SyntheticGeneratorConfig, generate_synthetic_dataset


def _measure(name, function):
    tracemalloc.start()
    started = perf_counter()
    result = function()
    elapsed = perf_counter() - started
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    if "candidate_count" in result:
        count = result["candidate_count"]
    elif "cases" in result:
        count = sum(bool(item.get("triggered_indicators")) for item in result["cases"])
    elif "items" in result:
        count = len(result["items"])
    else:
        count = len(result.get("candidates", result.get("candidate_groups", [])))
    measurement = {
        "detector": name,
        "candidate_count": count,
        "elapsed_seconds": round(elapsed, 3),
        "python_tracemalloc_peak_mib": round(peak / (1024 * 1024), 2),
        "python_tracemalloc_current_mib": round(current / (1024 * 1024), 2),
    }
    if "search_truncated" in result:
        measurement["search_truncated"] = result["search_truncated"]
    if "pair_comparisons" in result:
        measurement["pair_comparisons"] = result["pair_comparisons"]
    return measurement, result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=int, default=10_000, help="jumlah klaim sintetis (default 10.000)")
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    if args.claims < 10:
        parser.error("--claims minimal 10")
    config = SyntheticGeneratorConfig(
        seed=args.seed,
        claim_count=args.claims,
        facility_count=min(200, args.claims),
        target_anomaly_rate=0.04,
    )
    dataset = generate_synthetic_dataset(config)
    records, facilities = dataset.records, dataset.facilities
    measurements = []
    detector_results = {}
    for indicator, name, function in (
        ("repeat_billing_candidate", "repeat_billing_exact", lambda: detect_repeat_billing_candidates(records)),
        ("similar_claim_pattern_candidate", "similar_pattern_exact", lambda: detect_similar_claim_patterns(records)),
        ("synthetic_capacity_candidate", "capacity", lambda: detect_capacity_candidates(records, facilities)),
        ("near_duplicate_claim_candidate", "near_duplicate_blocking", lambda: detect_near_duplicate_claims(records)),
        ("temporal_pattern_candidate", "temporal", lambda: detect_temporal_patterns(records)),
        ("supporting_evidence_completeness_candidate", "evidence_completeness", lambda: detect_evidence_completeness(records)),
    ):
        measurement, result = _measure(name, function)
        measurements.append(measurement)
        detector_results[indicator] = result
    scoring_result, risk_output = _measure("risk_scoring", lambda: score_claims(records, detector_results))
    measurements.append(scoring_result)
    priority_measurement, _ = _measure("audit_priority", lambda: build_audit_priority_queue(records, risk_output))
    measurements.append(priority_measurement)
    print(json.dumps({
        "seed": args.seed,
        "claims": len(records),
        "facilities": len(facilities),
        "ground_truth_passed_to_detectors": False,
        "measurements": measurements,
        "note": "Synthetic-only. Peak values are Python tracemalloc allocations for each detector, not total process RSS. No 120,000-record performance claim is implied.",
    }, indent=2))


if __name__ == "__main__":
    main()
