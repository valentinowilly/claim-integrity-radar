"""Run a reproducible aggregate-only synthetic evaluation and save its report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter
import tracemalloc
from typing import Any

from app.analytics.evaluation import evaluate_synthetic_dataset
from app.data_sources.synthetic_benchmark_generator import (
    SyntheticBenchmarkProfile,
    generate_synthetic_benchmark_dataset,
)
from app.data_sources.synthetic_generator import SyntheticGeneratorConfig, generate_synthetic_dataset


def run_benchmark(
    *,
    claims: int,
    facilities: int,
    seed: int,
    target_anomaly_rate: float = 0.04,
    audit_budget_fractions: tuple[float, ...] = (0.05, 0.10, 0.20),
    random_seed_count: int = 30,
    generator_version: str = "4",
    positive_facility_fraction: float = 0.20,
) -> dict[str, Any]:
    config = SyntheticGeneratorConfig(
        seed=seed,
        claim_count=claims,
        facility_count=facilities,
        target_anomaly_rate=target_anomaly_rate,
    )
    tracemalloc.start()
    started = perf_counter()
    if generator_version == "4":
        dataset = generate_synthetic_benchmark_dataset(
            config, SyntheticBenchmarkProfile(positive_facility_fraction=positive_facility_fraction)
        )
    elif generator_version == "3":
        dataset = generate_synthetic_dataset(config)
    else:
        raise ValueError("generator_version hanya mendukung 3 atau 4")
    report = evaluate_synthetic_dataset(
        dataset.records,
        dataset.facilities,
        dataset.ground_truth,
        seed=seed,
        generator_version=str(dataset.metadata["generator_version"]),
        target_anomaly_rate=target_anomaly_rate,
        generator_metadata=dataset.metadata,
        audit_budget_fractions=audit_budget_fractions,
        random_seed_count=random_seed_count,
    )
    elapsed = perf_counter() - started
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    report["performance"] = {
        "end_to_end_seconds": round(elapsed, 3),
        "python_tracemalloc_peak_mib": round(peak_bytes / (1024 * 1024), 2),
        "python_tracemalloc_current_mib_before_release_mib": round(current_bytes / (1024 * 1024), 2),
        "memory_measurement": "Python traced allocations only; not total process RSS or native allocator memory.",
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=int, default=250, help="jumlah klaim sintetis (default smoke test 250)")
    parser.add_argument("--facilities", type=int, help="default min(200, claims)")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--target-anomaly-rate", type=float, default=0.04)
    parser.add_argument("--audit-budgets", type=float, nargs="+", default=[0.05, 0.10, 0.20], help="fraksi fasilitas K untuk dibandingkan")
    parser.add_argument("--random-seeds", type=int, default=30, help="jumlah seed baseline acak")
    parser.add_argument("--generator-version", choices=("3", "4"), default="4")
    parser.add_argument("--positive-facility-fraction", type=float, default=0.20)
    parser.add_argument("--output", type=Path, help="default ../outputs/synthetic_evaluations/stage16-v<version>-<claims>-seed<seed>.json")
    args = parser.parse_args()
    if args.claims < 10:
        parser.error("--claims minimal 10")
    facility_count = args.facilities if args.facilities is not None else min(200, args.claims)
    if not 1 <= facility_count <= args.claims:
        parser.error("--facilities harus berada antara 1 dan --claims")
    if args.random_seeds < 1:
        parser.error("--random-seeds minimal 1")

    report = run_benchmark(
        claims=args.claims,
        facilities=facility_count,
        seed=args.seed,
        target_anomaly_rate=args.target_anomaly_rate,
        audit_budget_fractions=tuple(args.audit_budgets),
        random_seed_count=args.random_seeds,
        generator_version=args.generator_version,
        positive_facility_fraction=args.positive_facility_fraction,
    )
    default_output = Path(__file__).resolve().parents[3] / "outputs" / "synthetic_evaluations" / f"stage16-v{args.generator_version}-{args.claims}-seed{args.seed}.json"
    output = args.output if args.output is not None else default_output
    if not output.is_absolute():
        output = Path.cwd() / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "report_path": str(output),
        "data_source": report["data_source"],
        "metadata": report["metadata"],
        "performance": report["performance"],
        "detectors": report["detectors"],
        "combined": report["combined"],
        "priority_ranking": report["priority_ranking"],
        "limitations": report["limitations"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
