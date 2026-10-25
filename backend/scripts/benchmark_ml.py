"""Synthetic-only ML benchmark for Claim Integrity Radar.

Run from the backend directory:
    python -m scripts.benchmark_ml

This module generates independent train/validation/test datasets from separate
synthetic generator seeds. It never reads real BPJS files and writes aggregate
metrics only, not claim-level records.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, Sequence

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.analytics.evaluation import evaluate_synthetic_dataset, run_detector_suite
from app.analytics.risk_scoring import score_claims
from app.data_sources.synthetic_benchmark_generator import (
    SyntheticBenchmarkProfile,
    generate_synthetic_benchmark_dataset,
)
from app.data_sources.synthetic_generator import SyntheticGeneratorConfig


SYNTHETIC_SERVICE_ALIASES = {
    # These generator-only names disclose which injected scenario created a row.
    # Collapse them to the broad operational bucket used by ordinary procedures.
    "synthetic_supported_action": "other",
    "synthetic_mixed_action": "other",
}

ID_AND_LABEL_FIELDS = {
    "claim_id", "case_id", "facility_id", "participant_token",
    "is_anomaly", "is_synthetic_anomaly", "scenario", "scenario_label",
    "scenario_labels", "primary_scenario", "scenario_group_id", "scenario_code",
    "intensity_level", "injected_signals", "label_scope", "claim_labels",
    "group_labels", "ground_truth", "claim_labels", "facility_labels",
}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _text(value: Any, default: str = "unknown") -> str:
    if value is None:
        return default
    result = str(value).strip()
    return result if result else default


def _service_group(value: Any) -> str:
    service = _text(value, "unknown")
    service = SYNTHETIC_SERVICE_ALIASES.get(service, service)
    # Reduce synthetic-specific detail: retain only a broad, plausible category.
    return "physiotherapy" if service == "physiotherapy" else "other"


def _clean_category(value: Any, field: str) -> str:
    """Remove generator-only category labels while keeping broad semantics."""
    raw = _text(value, "unknown").strip().lower()
    if field == "facility_ownership":
        if raw.endswith("public"):
            return "public"
        if raw.endswith("private"):
            return "private"
        return "other"
    if field == "facility_type":
        for label in ("general", "specialty", "rehabilitation"):
            if raw.endswith(label):
                return label
        return "other"
    if field == "facility_class":
        match = re.search(r"(?:class[-_ ]?)([0-9]+)$", raw)
        return f"class_{match.group(1)}" if match else "other"
    return raw


def _date_parts(row: Mapping[str, Any]) -> tuple[int, int, int, int]:
    raw_ts = row.get("service_timestamp")
    try:
        stamp = datetime.fromisoformat(str(raw_ts))
        return stamp.hour, stamp.minute, stamp.weekday(), stamp.month
    except (TypeError, ValueError):
        pass
    try:
        day = date.fromisoformat(str(row.get("service_date")))
        return 0, 0, day.weekday(), day.month
    except (TypeError, ValueError):
        return 0, 0, 0, 0


def _count_by_key(
    records: Sequence[Mapping[str, Any]], key_fn,
) -> list[int]:
    keys = [key_fn(row) for row in records]
    counts = Counter(keys)
    return [counts[key] for key in keys]


def engineer_features(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Clean and engineer claim-level features without accessing ground truth."""
    rows = list(records)
    date_parts = [_date_parts(row) for row in rows]
    service_groups = [_service_group(row.get("service_type")) for row in rows]

    participant_signature_counts = _count_by_key(
        rows,
        lambda r: (
            _text(r.get("participant_token")),
            _text(r.get("service_date")),
            _text(r.get("facility_id")),
            _service_group(r.get("service_type")),
            _text(r.get("admission_diagnosis")),
            _text(r.get("primary_diagnosis")),
            _text(r.get("claim_group")),
            _text(r.get("procedure_code")),
            round(_float(r.get("billed_amount")), 2),
        ),
    )
    facility_day_diagnosis_counts = _count_by_key(
        rows,
        lambda r: (
            _text(r.get("facility_id")),
            _text(r.get("service_date")),
            _text(r.get("admission_diagnosis")),
            _text(r.get("primary_diagnosis")),
            _text(r.get("claim_group")),
        ),
    )
    near_duplicate_block_counts = _count_by_key(
        rows,
        lambda r: (
            _text(r.get("service_date")),
            _text(r.get("municipality_code")),
            _text(r.get("primary_diagnosis")),
        ),
    )
    minute_cluster_keys = [
        (
            _text(row.get("facility_id")),
            _text(row.get("service_date")),
            service_groups[i],
            date_parts[i][0],
            date_parts[i][1],
        )
        for i, row in enumerate(rows)
    ]
    minute_cluster_counter = Counter(minute_cluster_keys)
    minute_cluster_counts = [minute_cluster_counter[key] for key in minute_cluster_keys]

    features: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        hour, minute, weekday, month = date_parts[i]
        required_value = row.get("supporting_evidence_required")
        present_value = row.get("supporting_evidence_types")
        required = set(required_value) if isinstance(required_value, (list, tuple, set)) else set()
        present = set(present_value) if isinstance(present_value, (list, tuple, set)) else set()
        required_count = len(required)
        present_required_count = len(required & present)
        missing_count = len(required - present)
        capacity = _float(row.get("facility_daily_capacity"))
        units = _float(row.get("service_units"))
        amount = _float(row.get("billed_amount"))
        ratio = units / capacity if capacity > 0 else 0.0
        recording_status = _text(row.get("supporting_evidence_recording_status"))

        # Only low-cardinality, broadly interpretable categories are retained.
        # Facility/participant/claim IDs, diagnosis strings, labels, and scenario
        # metadata never enter the feature matrix.
        feature = {
            "billed_amount": amount,
            "service_units": units,
            "facility_daily_capacity": capacity,
            "facility_daily_claim_count": _float(row.get("facility_daily_claim_count")),
            "capacity_utilization_ratio": ratio,
            "capacity_excess_units": max(0.0, units - capacity),
            "required_evidence_count": float(required_count),
            "present_required_evidence_count": float(present_required_count),
            "missing_evidence_count": float(missing_count),
            "evidence_completeness_ratio": (
                present_required_count / required_count if required_count else 1.0
            ),
            "evidence_inventory_recorded": float(recording_status == "recorded"),
            "service_hour": float(hour),
            "service_minute": float(minute),
            "service_weekday": float(weekday),
            "service_month": float(month),
            "participant_signature_frequency": float(participant_signature_counts[i]),
            "facility_day_diagnosis_frequency": float(facility_day_diagnosis_counts[i]),
            "near_duplicate_block_frequency": float(near_duplicate_block_counts[i]),
            "same_minute_service_cluster_frequency": float(minute_cluster_counts[i]),
            "service_group": service_groups[i],
            "facility_ownership": _clean_category(row.get("facility_ownership"), "facility_ownership"),
            "facility_type": _clean_category(row.get("facility_type"), "facility_type"),
            "facility_class": _clean_category(row.get("facility_class"), "facility_class"),
        }
        features.append(feature)

    return features


def make_dataset(
    *, claims: int, facilities: int, seed: int, anomaly_rate: float,
    positive_facility_fraction: float,
):
    config = SyntheticGeneratorConfig(
        seed=seed,
        claim_count=claims,
        facility_count=facilities,
        target_anomaly_rate=anomaly_rate,
    )
    profile = SyntheticBenchmarkProfile(
        positive_facility_fraction=positive_facility_fraction
    )
    dataset = generate_synthetic_benchmark_dataset(config, profile)
    label_by_id = {
        item["case_id"]: bool(item["is_synthetic_anomaly"])
        for item in dataset.ground_truth.claim_labels
    }
    ids = [row.get("case_id") for row in dataset.records]
    if len(ids) != len(set(ids)) or set(ids) != set(label_by_id):
        raise ValueError("ID fitur sintetis dan ground truth tidak konsisten.")
    X = engineer_features(dataset.records)
    y = np.asarray([int(label_by_id[case_id]) for case_id in ids], dtype=np.int8)
    if len(X) != len(y):
        raise ValueError("Jumlah fitur dan label berbeda.")
    return dataset, X, y


def _best_f1_threshold(y_true: np.ndarray, scores: np.ndarray) -> float:
    precision, recall, thresholds = precision_recall_curve(y_true, scores)
    if len(thresholds) == 0:
        return 0.5
    denominator = precision[:-1] + recall[:-1]
    f1 = np.divide(
        2 * precision[:-1] * recall[:-1],
        denominator,
        out=np.zeros_like(denominator),
        where=denominator > 0,
    )
    # If tied, np.argmax makes the selected threshold deterministic.
    return float(thresholds[int(np.argmax(f1))])


def _top_budget_metrics(y_true: np.ndarray, scores: np.ndarray) -> dict[str, Any]:
    order = np.argsort(-scores, kind="stable")
    positives = int(y_true.sum())
    result: dict[str, Any] = {}
    for fraction in (0.05, 0.10, 0.20):
        k = max(1, int(math.ceil(len(y_true) * fraction)))
        selected = order[:k]
        hits = int(y_true[selected].sum())
        key = f"top_{int(fraction * 100)}pct"
        result[key] = {
            "review_count": k,
            "true_anomalies_found": hits,
            "precision_at_budget": float(hits / k),
            "recall_at_budget": float(hits / positives) if positives else None,
        }
    return result


def evaluate_model(name: str, model, X_valid, y_valid, X_test, y_test) -> dict[str, Any]:
    valid_scores = model.predict_proba(X_valid)[:, 1]
    threshold = _best_f1_threshold(y_valid, valid_scores)
    test_scores = model.predict_proba(X_test)[:, 1]
    predicted = (test_scores >= threshold).astype(np.int8)
    tn, fp, fn, tp = confusion_matrix(y_test, predicted, labels=[0, 1]).ravel()
    return {
        "model": name,
        "threshold_selected_on_validation": threshold,
        "test": {
            "sample_count": int(len(y_test)),
            "positive_count": int(y_test.sum()),
            "negative_count": int(len(y_test) - y_test.sum()),
            "precision": float(precision_score(y_test, predicted, zero_division=0)),
            "recall": float(recall_score(y_test, predicted, zero_division=0)),
            "f1_score": float(f1_score(y_test, predicted, zero_division=0)),
            "accuracy": float(accuracy_score(y_test, predicted)),
            "pr_auc_average_precision": float(average_precision_score(y_test, test_scores)),
            "roc_auc": float(roc_auc_score(y_test, test_scores)) if len(np.unique(y_test)) > 1 else None,
            "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
            "audit_budget_ranking": _top_budget_metrics(y_test, test_scores),
        },
    }


def _rule_claim_ranking(
    records: Sequence[Mapping[str, Any]], facilities: Sequence[Mapping[str, Any]],
    y_true: np.ndarray,
) -> dict[str, Any]:
    """Return claim-level ranking metrics for the existing rule risk scorer.

    Prefer the scorer's numeric per-claim risk score. If its schema only exposes
    trigger evidence, fall back to a transparent count of triggered indicators.
    The fallback is explicitly reported and must not be called the risk index.
    """
    try:
        detector_results = run_detector_suite(records, facilities)
        scoring = score_claims(records, detector_results)
        case_rows = None
        for key in ("scored_cases", "cases", "scored_claims", "claim_scores"):
            candidate = scoring.get(key) if isinstance(scoring, Mapping) else None
            if isinstance(candidate, list):
                case_rows = candidate
                break
        if case_rows is None:
            return {"status": "unavailable", "reason": "Per-claim score rows were not exposed by score_claims."}

        id_to_score: dict[str, float] = {}
        score_keys = (
            "risk_score", "risk_index", "claim_risk_score", "risk_score_value",
            "score", "weighted_score", "score_value",
        )
        score_source = None
        for row in case_rows:
            if not isinstance(row, Mapping) or not isinstance(row.get("case_id"), str):
                return {"status": "unavailable", "reason": "Scored claim rows do not contain valid case_id values."}
            score = None
            for key in score_keys:
                value = row.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
                    score = float(value)
                    score_source = key
                    break
            if score is None:
                break
            id_to_score[row["case_id"]] = score

        expected_ids = [str(row.get("case_id")) for row in records]
        if len(id_to_score) == len(case_rows) and set(expected_ids) == set(id_to_score):
            scores = np.asarray([id_to_score[case_id] for case_id in expected_ids], dtype=float)
        else:
            # Transparent ranking fallback: number of indicators triggered for each claim.
            id_to_count: dict[str, float] = {}
            for row in case_rows:
                case_id = row.get("case_id")
                triggered = row.get("triggered_indicators")
                if isinstance(triggered, (list, tuple, set)):
                    id_to_count[case_id] = float(len(set(triggered)))
                    continue
                coverage = row.get("indicator_coverage")
                if isinstance(coverage, list):
                    id_to_count[case_id] = float(sum(
                        1 for item in coverage
                        if isinstance(item, Mapping) and item.get("status") == "triggered"
                    ))
                    continue
                return {
                    "status": "unavailable",
                    "reason": "No per-claim risk score or trigger evidence was found.",
                }
            if set(expected_ids) != set(id_to_count):
                return {"status": "unavailable", "reason": "Scored case IDs do not match test records."}
            scores = np.asarray([id_to_count[case_id] for case_id in expected_ids], dtype=float)
            score_source = "triggered_indicator_count_fallback"

        if len(scores) != len(y_true) or not np.isfinite(scores).all():
            return {"status": "unavailable", "reason": "Rule scores are incomplete or non-finite."}
        return {
            "status": "complete",
            "score_source": score_source or "triggered_indicator_count_fallback",
            "score_interpretation": (
                "Existing per-claim risk score; not a fraud probability."
                if score_source != "triggered_indicator_count_fallback"
                else "Count of triggered detector indicators; fallback ranking only, not the weighted risk score."
            ),
            "pr_auc_average_precision": float(average_precision_score(y_true, scores)),
            "audit_budget_ranking": _top_budget_metrics(y_true, scores),
        }
    except Exception as exc:  # Preserve benchmark output while explicitly flagging unavailable ranking.
        return {
            "status": "unavailable",
            "reason": f"{type(exc).__name__}: {str(exc)[:180]}",
        }


def _feature_audit(features: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Run structural and value-level checks against obvious generator leakage."""
    names = sorted(set().union(*(set(row) for row in features))) if features else []
    forbidden_fragments = (
        "scenario", "injected", "intensity", "ground_truth", "label",
        "claim_id", "case_id", "facility_id", "participant_token",
    )
    forbidden_names = [
        name for name in names
        if any(token in name.lower() for token in forbidden_fragments)
    ]
    generator_markers = []
    for row in features:
        for name, value in row.items():
            if isinstance(value, str) and (
                value.lower().startswith("syn-")
                or value.lower().startswith("synthetic_")
                or value.lower().startswith("synthetic-")
            ):
                generator_markers.append({"feature": name, "value_class": "generator_marker"})
    # Keep the report aggregate-only: unique marker pairs, never row-level values.
    markers = sorted({(item["feature"], item["value_class"]) for item in generator_markers})
    return {
        "forbidden_feature_names": forbidden_names,
        "generator_marker_values_remaining": [
            {"feature": feature, "value_class": kind} for feature, kind in markers
        ],
        "all_numeric_values_finite": all(
            math.isfinite(float(value))
            for row in features for value in row.values()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ),
        "status": "pass" if not forbidden_names and not markers else "review_required",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-claims", type=int, default=20_000)
    parser.add_argument("--validation-claims", type=int, default=5_000)
    parser.add_argument("--test-claims", type=int, default=10_000)
    parser.add_argument("--train-facilities", type=int, default=40)
    parser.add_argument("--validation-facilities", type=int, default=20)
    parser.add_argument("--test-facilities", type=int, default=20)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--anomaly-rate", type=float, default=0.04)
    parser.add_argument("--positive-facility-fraction", type=float, default=0.20)
    parser.add_argument("--random-seeds", type=int, default=3, help="seed untuk random baseline pada evaluator aturan")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if not (0 < args.anomaly_rate < 1):
        parser.error("--anomaly-rate harus berada pada (0, 1)")
    if not (0 < args.positive_facility_fraction < 1):
        parser.error("--positive-facility-fraction harus berada pada (0, 1)")
    for name in ("train_claims", "validation_claims", "test_claims", "train_facilities", "validation_facilities", "test_facilities"):
        if getattr(args, name) < 2:
            parser.error(f"--{name.replace('_', '-')} minimal 2")

    started = perf_counter()
    print("[1/5] Membuat dataset sintetis independen untuk train/validation/test...", flush=True)
    train_data, X_train_dict, y_train = make_dataset(
        claims=args.train_claims, facilities=args.train_facilities,
        seed=args.seed, anomaly_rate=args.anomaly_rate,
        positive_facility_fraction=args.positive_facility_fraction,
    )
    val_data, X_val_dict, y_val = make_dataset(
        claims=args.validation_claims, facilities=args.validation_facilities,
        seed=args.seed + 1, anomaly_rate=args.anomaly_rate,
        positive_facility_fraction=args.positive_facility_fraction,
    )
    test_data, X_test_dict, y_test = make_dataset(
        claims=args.test_claims, facilities=args.test_facilities,
        seed=args.seed + 2, anomaly_rate=args.anomaly_rate,
        positive_facility_fraction=args.positive_facility_fraction,
    )

    print("[2/5] Mengubah fitur numerik/kategorikal dan memeriksa kebocoran label...", flush=True)
    feature_names = sorted(set().union(*(set(row) for row in X_train_dict)))
    leakage_audit = _feature_audit(X_train_dict + X_val_dict + X_test_dict)
    if leakage_audit["forbidden_feature_names"]:
        raise ValueError(f"Kolom label/identitas terdeteksi di fitur: {leakage_audit['forbidden_feature_names']}")
    if not leakage_audit["all_numeric_values_finite"]:
        raise ValueError("Nilai numerik fitur berisi NaN atau infinity.")
    if leakage_audit["generator_marker_values_remaining"]:
        raise ValueError(
            "Nilai kategori yang menandai generator masih masuk fitur: "
            f"{leakage_audit['generator_marker_values_remaining']}"
        )

    vectorizer = DictVectorizer(sparse=True, sort=True)
    X_train = vectorizer.fit_transform(X_train_dict)
    X_valid = vectorizer.transform(X_val_dict)
    X_test = vectorizer.transform(X_test_dict)
    # HistGradientBoosting requires dense input; this feature set is deliberately
    # low dimensional (high-cardinality diagnosis codes/IDs are excluded).
    X_train_dense = X_train.toarray()
    X_valid_dense = X_valid.toarray()
    X_test_dense = X_test.toarray()

    print("[3/5] Melatih Logistic Regression...", flush=True)
    logistic = make_pipeline(
        StandardScaler(with_mean=False),
        LogisticRegression(max_iter=1000, class_weight="balanced", random_state=args.seed),
    )
    logistic.fit(X_train, y_train)

    print("[4/5] Melatih HistGradientBoosting (Gradient Boosting untuk data tabular)...", flush=True)
    gradient = HistGradientBoostingClassifier(
        max_iter=120,
        learning_rate=0.08,
        max_leaf_nodes=15,
        l2_regularization=1.0,
        early_stopping=True,
        random_state=args.seed,
    )
    gradient.fit(X_train_dense, y_train)

    print("[5/5] Evaluasi model dan baseline aturan pada dataset test yang sama...", flush=True)
    logistic_result = evaluate_model("LogisticRegression", logistic, X_valid, y_val, X_test, y_test)
    gradient_result = evaluate_model("HistGradientBoostingClassifier", gradient, X_valid_dense, y_val, X_test_dense, y_test)
    rule_report = evaluate_synthetic_dataset(
        test_data.records,
        test_data.facilities,
        test_data.ground_truth,
        seed=args.seed + 2,
        generator_version=str(test_data.metadata["generator_version"]),
        target_anomaly_rate=args.anomaly_rate,
        generator_metadata=test_data.metadata,
        audit_budget_fractions=(0.05, 0.10, 0.20),
        random_seed_count=args.random_seeds,
    )
    rule_baseline = {
        "method": "existing_rule_detectors_and_risk_score",
        "coverage": rule_report.get("combined", {}).get("coverage", {}),
        "metrics": rule_report.get("combined", {}).get("metrics", {}),
        "claim_level_ranking": _rule_claim_ranking(
            test_data.records, test_data.facilities, y_test
        ),
        "data_source": rule_report.get("data_source", "synthetic_experiment_only"),
    }

    report = {
        "experiment": "claim_integrity_radar_ml_benchmark_v2",
        "data_source": "synthetic_only",
        "interpretation_warning": (
            "Labels indicate injected synthetic scenarios, not verified BPJS fraud. "
            "Metrics measure generalization across independent generator seeds only; "
            "they do not establish real-world performance."
        ),
        "dataset": {
            "generator_version": str(test_data.metadata.get("generator_version", "unknown")),
            "train": {"seed": args.seed, "claims": int(len(y_train)), "positives": int(y_train.sum()), "negatives": int(len(y_train) - y_train.sum()), "facilities": args.train_facilities},
            "validation": {"seed": args.seed + 1, "claims": int(len(y_val)), "positives": int(y_val.sum()), "negatives": int(len(y_val) - y_val.sum()), "facilities": args.validation_facilities},
            "test": {"seed": args.seed + 2, "claims": int(len(y_test)), "positives": int(y_test.sum()), "negatives": int(len(y_test) - y_test.sum()), "facilities": args.test_facilities},
            "target_anomaly_rate": args.anomaly_rate,
            "positive_facility_fraction": args.positive_facility_fraction,
        },
        "data_cleaning_and_feature_engineering": {
            "feature_count_after_encoding": int(X_train.shape[1]),
            "features_before_encoding": feature_names,
            "missing_numeric_values_defaulted_to": 0.0,
            "amount_converted_to_numeric": True,
            "date_and_timestamp_engineering": ["hour", "minute", "weekday", "month"],
            "engineered_relation_features": [
                "participant_signature_frequency",
                "facility_day_diagnosis_frequency",
                "near_duplicate_block_frequency",
                "same_minute_service_cluster_frequency",
            ],
            "service_type_aliases_collapsed": SYNTHETIC_SERVICE_ALIASES,
            "synthetic_category_labels_normalized": True,
            "feature_leakage_audit": leakage_audit,
            "excluded_fields": sorted(ID_AND_LABEL_FIELDS),
            "diagnosis_and_procedure_codes_excluded_as_raw_categorical_features": True,
            "relation_frequencies_computed_independently_within_each_generated_dataset": True,
            "split_design": "independent synthetic datasets by seed; related event groups cannot cross train/validation/test datasets",
        },
        "models": [logistic_result, gradient_result],
        "rule_baseline_same_test_dataset": rule_baseline,
        "runtime_seconds": round(perf_counter() - started, 3),
        "random_state": args.seed,
    }

    project_root = Path(__file__).resolve().parents[2]
    output_path = args.output or (project_root / "outputs" / "ml_experiments" / f"ml-benchmark-seed{args.seed}.json")
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "status": "complete",
        "report_path": str(output_path),
        "dataset": report["dataset"],
        "models": [
            {"model": item["model"], "threshold": item["threshold_selected_on_validation"], "test": item["test"]}
            for item in report["models"]
        ],
        "rule_baseline": {
            "coverage_status": rule_baseline["coverage"].get("status"),
            "coverage_fraction": rule_baseline["coverage"].get("coverage_fraction"),
            "metrics": rule_baseline["metrics"],
            "claim_level_ranking": rule_baseline["claim_level_ranking"],
        },
        "feature_leakage_audit": leakage_audit,
        "runtime_seconds": report["runtime_seconds"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
