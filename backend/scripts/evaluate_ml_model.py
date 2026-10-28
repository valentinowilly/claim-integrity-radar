"""Evaluate the saved FKRTL anomaly model on a held-out window (aggregates only).

Run from ``backend/`` with the same environment as a run, the held-out window in
BPJS_FKRTL_DATE_FROM/BPJS_FKRTL_DATE_TO (it must start after the training window):

    python -m scripts.evaluate_ml_model --seeds 1-3 --save

Two separate parts:
1. Real, unlabeled held-out records: coverage, score distribution against the
   training reference, overlap with rule flags, runtime and memory. No fraud
   precision or recall is computed, because there are no labels.
2. Controlled synthetic injections into copies of held-out records (labels are
   the injections themselves): top-K hits and score separation for the model,
   the existing rules on the same augmented records, and a transparent
   single-feature baseline. K is fixed before running.

Prints and saves counts and rates only: no rows, identifiers, codes or paths.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
import json
from pathlib import Path
import random
import time
import tracemalloc

from app.analytics.ml_model import (
    FEATURE_NAMES, _quantile_position, build_features, eligibility_reason, load_artifact, score_records,
)
from app.data_sources.fkrtl_local_source import FkrtlSourceUnavailable, configured_date_window, load_fkrtl_local_source
from app.services.analytics import build_analytics_snapshot

TOP_K = (200, 500)  # 200 = the stored top list in a run; fixed before evaluation
PER_TYPE = 50
INJECTION_TYPES = ("code_mismatch", "procedure_mismatch", "long_stay", "repeat_visits", "compound")
# Single-feature transparent baseline per injection type (the feature a reviewer would sort by).
SINGLE_FEATURE = {
    "code_mismatch": "pair_primary_diagnosis__claim_group",
    "procedure_mismatch": "pair_claim_group__procedure_code",
    "long_stay": "length_of_stay_deviation",
    "repeat_visits": "participant_week_visits",
    "compound": "length_of_stay_deviation",
}


def _cmg(code: str | None) -> str:
    return (code or "").split("-")[0]


def _auc(positive: list[float], negative: list[float]) -> float | None:
    """Mann-Whitney AUC: chance that an injected record outranks an unchanged one (ties count half)."""
    if not positive or not negative:
        return None
    ordered = sorted(negative)
    from bisect import bisect_left, bisect_right
    wins = sum(bisect_left(ordered, value) + 0.5 * (bisect_right(ordered, value) - bisect_left(ordered, value))
               for value in positive)
    return round(wins / (len(positive) * len(ordered)), 3)


def inject(records: list[dict], seed: int) -> tuple[list[dict], dict[str, set[str]], set[str]]:
    """Copies of held-out records with one controlled change each; originals of changed records are replaced."""
    rng = random.Random(seed)
    eligible = [index for index, row in enumerate(records) if eligibility_reason(row) is None]
    chosen = rng.sample(eligible, PER_TYPE * len(INJECTION_TYPES))
    out = [dict(row) for row in records]
    labels: dict[str, set[str]] = {name: set() for name in INJECTION_TYPES}
    affected: set[str] = set()
    with_procedure = [index for index in eligible if records[index].get("procedure_code")]
    extra = []
    for number, index in enumerate(chosen):
        kind = INJECTION_TYPES[number // PER_TYPE]
        row = out[index]
        case_id = f"syn-inj-{seed}-{kind}-{number:03d}"
        affected.add(row["case_id"])
        row["case_id"] = case_id
        if kind in ("code_mismatch", "compound"):
            # An INA-CBG from another case-mix group, taken from a real held-out claim.
            while True:
                donor = records[rng.choice(eligible)]
                if _cmg(donor.get("claim_group")) != _cmg(row.get("claim_group")):
                    row["claim_group"] = donor["claim_group"]
                    break
        if kind == "procedure_mismatch":
            while True:
                donor = records[rng.choice(with_procedure)]
                if _cmg(donor.get("claim_group")) != _cmg(row.get("claim_group")):
                    row["procedure_code"] = donor["procedure_code"]
                    break
        if kind in ("long_stay", "compound"):
            start = date.fromisoformat(str(row["service_date"])[:10])
            row["discharge_date"] = (start + timedelta(days=30)).isoformat()
        if kind == "repeat_visits":
            # Two further same-day visits of the same participant with identical codes.
            for copy in range(2):
                duplicate = dict(row, case_id=f"{case_id}-r{copy}")
                extra.append(duplicate)
                labels[kind].add(duplicate["case_id"])
        labels[kind].add(case_id)
    return out + extra, labels, affected


def evaluate_seed(records: list[dict], artifact: dict, seed: int) -> dict:
    augmented, labels, _affected = inject(records, seed)
    injected = set().union(*labels.values())
    started = time.perf_counter()
    snapshot = build_analytics_snapshot(records=augmented, facilities=[], data_source=SOURCE_METADATA)
    pipeline_seconds = time.perf_counter() - started
    _summary, results = score_records(augmented, artifact)
    scored = {case_id: item for case_id, item in results.items() if item["inference_status"] == "scored"}
    order = sorted(scored, key=lambda case_id: -scored[case_id]["anomaly_score"])
    rank = {case_id: position for position, case_id in enumerate(order)}
    unchanged = [scored[case_id]["anomaly_score"] for case_id in scored if case_id not in injected]

    eligible_rows = [row for row in augmented if row["case_id"] in scored]
    matrix = build_features(eligible_rows, artifact["reference"])
    feature_value = {name: {row["case_id"]: values[column] for row, values in zip(eligible_rows, matrix)}
                     for column, name in enumerate(FEATURE_NAMES)}
    # Transparent baseline: the highest training percentile over all features (no model).
    quantiles = [artifact["reference"]["feature_quantiles"][name] for name in FEATURE_NAMES]
    max_percentile = {row["case_id"]: max(_quantile_position(q, value) for q, value in zip(quantiles, values))
                      for row, values in zip(eligible_rows, matrix)}
    baseline_order = sorted(max_percentile, key=lambda case_id: (-max_percentile[case_id], case_id))
    baseline_rank = {case_id: position for position, case_id in enumerate(baseline_order)}

    rule_flags = {code: {case_id for case_id, case in snapshot["cases"].items() if code in case["indicators"]}
                  for code in ("repeat_billing_candidate", "near_duplicate_claim_candidate")}
    los_flags = {item["case_id"] for item in snapshot["length_of_stay"].get("candidates", [])}
    by_type = {}
    for kind, ids in list(labels.items()) + [("all_injected", injected)]:
        ids = {case_id for case_id in ids if case_id in scored}
        single = SINGLE_FEATURE.get(kind)
        by_type[kind] = {
            "injected_scored": len(ids),
            "model_auc_vs_unchanged": _auc([scored[c]["anomaly_score"] for c in ids], unchanged),
            "model_median_training_percentile": sorted(scored[c]["reference_percentile"] for c in ids)[len(ids) // 2],
            **{f"model_top_{k}_hits": sum(rank[c] < k for c in ids) for k in TOP_K},
            **{f"max_feature_baseline_top_{k}_hits": sum(baseline_rank[c] < k for c in ids) for k in TOP_K},
            **({"single_feature": single,
                "single_feature_auc_vs_unchanged": _auc([feature_value[single][c] for c in ids],
                                                        [feature_value[single][c] for c in scored if c not in injected])}
               if single else {}),
            "rule_repeat_flagged": len(ids & rule_flags["repeat_billing_candidate"]),
            "rule_similar_claim_flagged": len(ids & rule_flags["near_duplicate_claim_candidate"]),
            "duration_screen_flagged": len(ids & los_flags),
        }
    snapshot_ml = snapshot["ml_anomaly"]
    return {
        "seed": seed, "records": len(augmented), "injected": len(injected), "pipeline_seconds": round(pipeline_seconds, 1),
        "snapshot_ml_mode": snapshot_ml.get("mode"), "snapshot_ml_status": snapshot_ml.get("status"),
        "snapshot_ml_matches_direct_inference": snapshot_ml.get("records_scored") == len(scored),
        "rule_flag_volume": {code: len(ids) for code, ids in rule_flags.items()} | {"duration_screen": len(los_flags)},
        "by_type": by_type,
    }


def evaluate_real(records: list[dict], artifact: dict) -> dict:
    tracemalloc.start()
    started = time.perf_counter()
    summary, results = score_records(records, artifact)
    seconds = time.perf_counter() - started
    peak_mb = tracemalloc.get_traced_memory()[1] / 1e6
    tracemalloc.stop()
    scored = [item for item in results.values() if item["inference_status"] == "scored"]
    percentiles = sorted(item["reference_percentile"] for item in scored)
    signal_counts = Counter(signal["feature"] for item in summary["items"] for signal in item["supporting_signals"])
    return {
        "records": len(records), "scored": summary["records_scored"], "not_assessed": summary["records_not_assessed"],
        "not_assessed_reasons": summary["not_assessed_reason_counts"],
        "share_above_training_p99": summary.get("share_above_training_p99"),
        "share_above_training_p90": round(sum(p >= 0.9 for p in percentiles) / len(percentiles), 4) if percentiles else None,
        "median_training_percentile": percentiles[len(percentiles) // 2] if percentiles else None,
        "top_200_without_any_signal": sum(not item["supporting_signals"] for item in summary["items"]),
        "top_200_signal_feature_counts": dict(signal_counts.most_common()),
        "inference_seconds": round(seconds, 2), "inference_peak_traced_mb": round(peak_mb, 1),
    }


SOURCE_METADATA: dict = {}


def main() -> int:
    global SOURCE_METADATA
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", default="1-3")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    first, last = (int(part) for part in args.seeds.split("-"))
    artifact = load_artifact()
    training = artifact["manifest"]["training"]
    window = configured_date_window()
    if date.fromisoformat(training["date_to"]) >= window[0]:
        print("error: held-out window overlaps the training window")
        return 1
    try:
        loaded = load_fkrtl_local_source()
    except FkrtlSourceUnavailable as exc:
        print(f"error {exc.code}")
        return 1
    records = [dict(row) for row in loaded.dataset.records]
    SOURCE_METADATA = dict(loaded.dataset.source_metadata)
    report = {
        "label": "Real held-out window: unlabeled, no fraud accuracy. Injections: synthetic controlled changes, not fraud.",
        "model_version": artifact["manifest"]["model_version"],
        "artifact_checksum": artifact["manifest"]["files"]["model.joblib"][:12],
        "training_window": [training["date_from"], training["date_to"]], "training_rows": training["rows_eligible"],
        "holdout_window": [window[0].isoformat(), window[1].isoformat()],
        "top_k": list(TOP_K), "per_type": PER_TYPE,
        "real_holdout": evaluate_real(records, artifact),
        "injection": [evaluate_seed(records, artifact, seed) for seed in range(first, last + 1)],
    }
    text = json.dumps(report, indent=1)
    print(text)
    if args.save:
        out = Path("outputs/benchmarks"); out.mkdir(parents=True, exist_ok=True)
        (out / f"ml_holdout_{report['holdout_window'][0]}_{report['holdout_window'][1]}.json").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
