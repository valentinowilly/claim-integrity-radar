"""Offline-trained Isolation Forest for FKRTL records: shared features, artifact I/O and inference.

Training (``scripts/train_ml_model.py``) fits a frozen feature reference and the
model on an earlier admission-date window of the configured FKRTL source, then
writes a versioned artifact. A run only loads that artifact and scores its
records; nothing is refitted per request.

The score is a relative anomaly measure against the training reference: higher
means more unusual. It is not a fraud probability, is never trained on labels,
and stays separate from the rule detectors, risk index, action lanes and audit
priority. Features are built from verified codes, dates and pseudonymous
visit counts only. No identifier, HMAC value or amount (FKL47/FKL48) is a
feature, and the artifact stores no row-level records: only code frequency
tables with small counts suppressed, peer-group duration statistics, feature
quantiles and the fitted trees.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
from statistics import median
from typing import Any

from app.analytics.detector_utils import date_value, text_value


MODEL_VERSION = "cir-iforest-fkrtl-v2"
FEATURE_PIPELINE_VERSION = "cir-ml-features-v2"
MODEL_DIR_VARIABLE = "CIR_ML_MODEL_DIR"
DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[2] / "models" / MODEL_VERSION
SCORE_TYPE = "relative_anomaly_vs_training_reference_not_fraud_probability"
SCORE_DIRECTION = "higher_is_more_unusual"
# Code values seen fewer times than this in training are not stored; at inference they
# share one "rare or unseen" frequency, so the artifact never lists near-unique values.
MIN_REFERENCE_COUNT = 5
# Peer groups for the duration feature need this many training stays, else a coarser group.
MIN_STAY_SUPPORT = 30
QUANTILE_STEPS = 1000
_MISSING = "__missing__"

# v1 also scored the rarity of each single code. On the held-out FKRTL week 187 of its top 200
# claims were driven by a rare INA-CBG alone, and in the controlled injections a transparent
# max-percentile baseline found twice as many injected records in the top 200, so v2 keeps only
# combination, duration, visit and diagnosis-change features (single codes are still counted to
# condition the combination features, but are not features themselves).
CATEGORICAL_FEATURES: tuple[tuple[str, str], ...] = ()
# Conditional frequency P(second | first) in training: unusual combinations of common codes.
PAIR_FEATURES = (
    ("primary_diagnosis", "claim_group", "Kombinasi diagnosis primer dan INA-CBG jarang"),
    ("claim_group", "procedure_code", "Kombinasi INA-CBG dan prosedur jarang"),
    ("admission_diagnosis", "primary_diagnosis", "Kombinasi diagnosis masuk dan primer jarang"),
    ("facility_class", "claim_group", "INA-CBG jarang untuk tipe/kelas fasilitas ini"),
)
DERIVED_FEATURES = (
    ("length_of_stay_deviation", "Lama rawat menyimpang dari median kelompok INA-CBG dan kelas rawat pada data latih"),
    ("participant_week_visits", "Jumlah kunjungan peserta yang sama pada minggu kalender yang sama tinggi"),
    ("diagnosis_changed", "Diagnosis masuk berbeda dari diagnosis primer"),
)
FEATURE_NAMES = (
    [f"freq_{field}" for field, _ in CATEGORICAL_FEATURES]
    + [f"pair_{first}__{second}" for first, second, _ in PAIR_FEATURES]
    + [name for name, _ in DERIVED_FEATURES]
)
FEATURE_DESCRIPTIONS = (
    [text for _, text in CATEGORICAL_FEATURES]
    + [text for _, _, text in PAIR_FEATURES]
    + [text for _, text in DERIVED_FEATURES]
)
# Frequency columns are low when unusual; they are negated so every column grows with unusualness.
_FREQUENCY_COLUMNS = len(CATEGORICAL_FEATURES) + len(PAIR_FEATURES)
REQUIRED_FIELDS = ("service_date", "primary_diagnosis", "claim_group")
EXCLUDED_FIELDS = (
    "identitas peserta/kunjungan, case_id dan nilai HMAC (token peserta hanya untuk menghitung kunjungan per minggu)",
    "biaya tagih provider (semantik belum terverifikasi; tidak dipakai untuk skor)",
    "biaya pascaverifikasi (tidak pernah dibaca)",
    "wilayah dan kategori fasilitas sebagai fitur frekuensi tunggal (bukan perilaku klaim)",
    "kelangkaan satu kode saja (kode langka yang sah mendominasi peringkat v1)",
)
LIMITATIONS = [
    "Skor anomali relatif terhadap distribusi data latih (jendela tanggal sebelumnya pada sumber FKRTL yang sama); bukan probabilitas fraud dan tidak dilatih dengan label.",
    "Tidak ada label fraud terkonfirmasi, sehingga presisi atau recall fraud model tidak dapat dan tidak diklaim; hanya injeksi anomali sintetis yang diukur.",
    "Record yang jarang dapat sah secara klinis/administratif (kasus langka, rujukan khusus); skor hanya membantu urutan tinjauan manusia.",
    "Sinyal pendukung menunjukkan fitur yang berada pada persentil tinggi dibanding data latih; itu bukan atribusi atau penjelasan kausal model.",
    "Jumlah kunjungan per minggu dihitung di dalam jendela run; minggu yang terpotong oleh batas jendela dapat menurunkan hitungan.",
]


class ModelArtifactError(Exception):
    """The artifact is missing, incomplete or does not match its manifest."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TrainingConfig:
    n_estimators: int = 300
    max_samples: int = 512
    random_state: int = 20260
    min_training_records: int = 1000


def _category(row: Mapping[str, Any], field: str) -> str:
    return text_value(row.get(field)) or _MISSING


def eligibility_reason(row: Mapping[str, Any]) -> str | None:
    """Missing-data eligibility, kept apart from scoring: None means the record can be scored."""
    missing = [field for field in REQUIRED_FIELDS
               if (date_value(row.get(field)) if field == "service_date" else text_value(row.get(field))) is None]
    return f"missing:{'+'.join(missing)}" if missing else None


def _stay(row: Mapping[str, Any]) -> float | None:
    start, end = date_value(row.get("service_date")), date_value(row.get("discharge_date"))
    if start is None or end is None or end < start:
        return None
    return float((end - start).days)


def _peer_keys(row: Mapping[str, Any]) -> tuple[str, str]:
    group = _category(row, "claim_group")
    return f"{group}|{_category(row, 'care_class')}", group


def _robust(values: list[float]) -> list[float]:
    center = median(values)
    return [center, median(abs(value - center) for value in values)]


def _week_visit_counts(rows: Sequence[Mapping[str, Any]]) -> list[int]:
    """Visits by the same pseudonymous participant in the same ISO week (grouping only, never encoded)."""
    keys = []
    for row in rows:
        token, day = text_value(row.get("participant_token")), date_value(row.get("service_date"))
        keys.append((token, tuple(day.isocalendar()[:2])) if token and day else None)
    counts = Counter(key for key in keys if key is not None)
    return [counts[key] if key is not None else 1 for key in keys]


def fit_reference(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate, suppressed statistics shared by training and inference (no row-level values)."""
    n = len(rows)
    categorical: dict[str, dict[str, int]] = {}
    full_counts: dict[str, Counter] = {}
    for field, _ in CATEGORICAL_FEATURES + tuple((first, "") for first, _, _ in PAIR_FEATURES):
        if field in full_counts:
            continue
        counts = Counter(_category(row, field) for row in rows)
        full_counts[field] = counts
        categorical[field] = {value: count for value, count in sorted(counts.items()) if count >= MIN_REFERENCE_COUNT}
    pairs: dict[str, dict[str, int]] = {}
    for first, second, _ in PAIR_FEATURES:
        counts = Counter(f"{_category(row, first)}\x1f{_category(row, second)}" for row in rows)
        pairs[f"{first}__{second}"] = {
            value: count for value, count in sorted(counts.items()) if count >= MIN_REFERENCE_COUNT
        }
    fine: dict[str, list[float]] = defaultdict(list)
    coarse: dict[str, list[float]] = defaultdict(list)
    every: list[float] = []
    for row in rows:
        stay = _stay(row)
        if stay is None:
            continue
        fine_key, coarse_key = _peer_keys(row)
        fine[fine_key].append(stay)
        coarse[coarse_key].append(stay)
        every.append(stay)
    return {
        "training_records": n,
        "min_reference_count": MIN_REFERENCE_COUNT,
        "categorical_counts": categorical,
        "pair_counts": pairs,
        "stay_peer_fine": {key: _robust(values) for key, values in sorted(fine.items()) if len(values) >= MIN_STAY_SUPPORT},
        "stay_peer_coarse": {key: _robust(values) for key, values in sorted(coarse.items()) if len(values) >= MIN_STAY_SUPPORT},
        "stay_global": _robust(every) if every else [0.0, 0.0],
    }


def build_features(rows: Sequence[Mapping[str, Any]], reference: Mapping[str, Any]) -> list[list[float]]:
    """Deterministic feature matrix; identical code for training and inference."""
    n_train = reference["training_records"]
    rare = MIN_REFERENCE_COUNT / 2  # shared count for rare or unseen values
    categorical, pairs = reference["categorical_counts"], reference["pair_counts"]
    visits = _week_visit_counts(rows)
    matrix = []
    for row, visit_count in zip(rows, visits):
        values = []
        for field, _ in CATEGORICAL_FEATURES:
            values.append(math.log(categorical[field].get(_category(row, field), rare) / n_train))
        for first, second, _ in PAIR_FEATURES:
            first_value = _category(row, first)
            first_count = categorical[first].get(first_value, rare)
            pair_count = pairs[f"{first}__{second}"].get(f"{first_value}\x1f{_category(row, second)}", rare)
            # An unseen first value carries no combination evidence (its own rarity is a separate column).
            values.append(math.log(min(pair_count, first_count) / first_count))
        stay = _stay(row)
        if stay is None:
            values.append(0.0)  # neutral when a date is missing or reversed
        else:
            fine_key, coarse_key = _peer_keys(row)
            center, mad = (reference["stay_peer_fine"].get(fine_key)
                           or reference["stay_peer_coarse"].get(coarse_key) or reference["stay_global"])
            values.append(abs(stay - center) / (mad + 1.0))
        values.append(math.log(visit_count))
        admission, primary = text_value(row.get("admission_diagnosis")), text_value(row.get("primary_diagnosis"))
        values.append(1.0 if admission and primary and admission != primary else 0.0)
        matrix.append([-value if index < _FREQUENCY_COLUMNS else value for index, value in enumerate(values)])
    return matrix


def _quantiles(values: Sequence[float]) -> list[float]:
    ordered = sorted(values)
    last = len(ordered) - 1
    return [round(ordered[round(step * last / QUANTILE_STEPS)], 6) for step in range(QUANTILE_STEPS + 1)]


def _quantile_position(quantiles: Sequence[float], value: float) -> float:
    """Approximate share of training values strictly below ``value`` (resolution 1/QUANTILE_STEPS)."""
    return round(bisect_left(quantiles, round(value, 6)) / len(quantiles), 4)


def train_model(rows: Sequence[Mapping[str, Any]], config: TrainingConfig | None = None) -> dict[str, Any]:
    """Fit reference statistics and the model on eligible training rows; returns in-memory parts."""
    from sklearn.ensemble import IsolationForest

    config = config or TrainingConfig()
    eligible = [row for row in rows if eligibility_reason(row) is None]
    if len(eligible) < config.min_training_records:
        raise ValueError("Data latih tidak cukup untuk melatih model anomali.")
    reference = fit_reference(eligible)
    matrix = build_features(eligible, reference)
    # Canonical (sorted feature-vector) order: the fit depends on the feature multiset only.
    canonical = sorted(matrix)
    model = IsolationForest(n_estimators=config.n_estimators, max_samples=min(config.max_samples, len(canonical)),
                            random_state=config.random_state)
    model.fit(canonical)
    scores = [-float(value) for value in model.score_samples(canonical).tolist()]
    reference["score_quantiles"] = _quantiles(scores)
    reference["feature_quantiles"] = {name: _quantiles(column) for name, column in zip(FEATURE_NAMES, zip(*canonical))}
    return {"model": model, "reference": reference, "config": config,
            "rows_seen": len(rows), "rows_eligible": len(eligible),
            "not_eligible_reasons": dict(sorted(Counter(
                reason for row in rows if (reason := eligibility_reason(row)) is not None).items()))}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def save_artifact(trained: Mapping[str, Any], directory: Path, training_metadata: Mapping[str, Any]) -> dict[str, Any]:
    import joblib
    import sklearn

    directory.mkdir(parents=True, exist_ok=True)
    model_path, reference_path = directory / "model.joblib", directory / "reference.json"
    joblib.dump(trained["model"], model_path)
    reference_path.write_text(json.dumps(trained["reference"], sort_keys=True, separators=(",", ":")), encoding="utf-8")
    config: TrainingConfig = trained["config"]
    manifest = {
        "model_version": MODEL_VERSION,
        "feature_pipeline_version": FEATURE_PIPELINE_VERSION,
        "algorithm": "IsolationForest (scikit-learn)",
        "sklearn_version": sklearn.__version__,
        "parameters": {"n_estimators": config.n_estimators, "max_samples": config.max_samples,
                       "random_state": config.random_state},
        "features": [{"name": name, "description": text} for name, text in zip(FEATURE_NAMES, FEATURE_DESCRIPTIONS)],
        "excluded_fields": list(EXCLUDED_FIELDS),
        "score_type": SCORE_TYPE,
        "score_direction": SCORE_DIRECTION,
        "training": {**training_metadata, "rows_seen": trained["rows_seen"], "rows_eligible": trained["rows_eligible"],
                     "not_eligible_reasons": trained["not_eligible_reasons"]},
        "files": {"model.joblib": _sha256(model_path), "reference.json": _sha256(reference_path)},
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def model_directory() -> Path:
    configured = os.environ.get(MODEL_DIR_VARIABLE, "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_MODEL_DIR


@lru_cache(maxsize=2)
def _load_cached(directory: str, stamp: tuple) -> dict[str, Any]:
    import joblib

    path = Path(directory)
    # Versions and checksums are verified before unpickling: a changed or truncated file is never loaded.
    manifest = _verified_manifest(path)
    reference = json.loads((path / "reference.json").read_text(encoding="utf-8"))
    return {"manifest": manifest, "reference": reference, "model": joblib.load(path / "model.joblib")}


def _verified_manifest(path: Path) -> dict[str, Any]:
    """Manifest of a complete artifact whose versions and checksums match, without unpickling."""
    files = [path / name for name in ("manifest.json", "reference.json", "model.joblib")]
    if not all(item.is_file() for item in files):
        raise ModelArtifactError("ML_MODEL_ARTIFACT_MISSING")
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ModelArtifactError("ML_MODEL_ARTIFACT_UNREADABLE") from None
    if manifest.get("model_version") != MODEL_VERSION or manifest.get("feature_pipeline_version") != FEATURE_PIPELINE_VERSION:
        raise ModelArtifactError("ML_MODEL_VERSION_MISMATCH")
    # Pickled estimators are only guaranteed to load on the scikit-learn version that wrote them.
    try:
        installed = importlib.metadata.version("scikit-learn")
    except importlib.metadata.PackageNotFoundError:
        raise ModelArtifactError("ML_MODEL_RUNTIME_UNAVAILABLE") from None
    if manifest.get("sklearn_version") != installed:
        raise ModelArtifactError("ML_MODEL_RUNTIME_MISMATCH")
    expected = manifest.get("files") or {}
    if set(expected) != {"model.joblib", "reference.json"}:
        raise ModelArtifactError("ML_MODEL_ARTIFACT_UNREADABLE")
    for name, digest in expected.items():
        if _sha256(path / name) != digest:
            raise ModelArtifactError("ML_MODEL_CHECKSUM_MISMATCH")
    return manifest


def model_status(directory: Path | None = None) -> dict[str, Any]:
    """Startup/status check of the configured artifact (no unpickling; never exposes a path)."""
    try:
        manifest = _verified_manifest(directory or model_directory())
    except ModelArtifactError as error:
        return {"available": False, "model_version": MODEL_VERSION, "error_code": error.code}
    training = manifest.get("training", {})
    return {"available": True, "model_version": MODEL_VERSION, "error_code": None,
            "feature_pipeline_version": FEATURE_PIPELINE_VERSION,
            "artifact_checksum": manifest["files"]["model.joblib"][:12],
            "training_window": [training.get("date_from"), training.get("date_to")]}


def load_artifact(directory: Path | None = None) -> dict[str, Any]:
    path = directory or model_directory()
    files = [path / name for name in ("manifest.json", "reference.json", "model.joblib")]
    if not all(item.is_file() for item in files):
        raise ModelArtifactError("ML_MODEL_ARTIFACT_MISSING")
    try:
        return _load_cached(str(path.resolve()), tuple(item.stat().st_mtime_ns for item in files))
    except ModelArtifactError:
        raise
    except Exception:
        raise ModelArtifactError("ML_MODEL_ARTIFACT_UNREADABLE") from None


def _summary_base(records_considered: int) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "mode": "pretrained_artifact",
        "model": "IsolationForest (scikit-learn)",
        "model_version": MODEL_VERSION,
        "feature_pipeline_version": FEATURE_PIPELINE_VERSION,
        "score_type": SCORE_TYPE,
        "score_direction": SCORE_DIRECTION,
        "records_considered": records_considered,
        "records_scored": 0,
        "records_not_assessed": records_considered,
        "not_assessed_reason_counts": {},
        "features": [{"name": name, "description": text} for name, text in zip(FEATURE_NAMES, FEATURE_DESCRIPTIONS)],
        "excluded_fields": list(EXCLUDED_FIELDS),
        "items": [],
        "items_truncated": False,
        "limitations": LIMITATIONS.copy(),
    }


def score_records(
    records: Sequence[Mapping[str, Any]],
    artifact: Mapping[str, Any] | None = None,
    *,
    top_n: int = 200,
    max_signals: int = 3,
    signal_min_percentile: float = 0.95,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Batch inference with a saved artifact; returns the persisted summary and per-case results."""
    summary = _summary_base(len(records))
    try:
        artifact = artifact or load_artifact()
    except ModelArtifactError as error:
        summary["error_code"] = error.code
        summary["limitations"].insert(0, "Artefak model ML tidak tersedia atau tidak valid; skor anomali tidak dihitung. Sinyal aturan tetap tersedia.")
        return summary, {}
    manifest, reference = artifact["manifest"], artifact["reference"]
    training = manifest.get("training", {})
    summary.update({
        "parameters": manifest.get("parameters"),
        "artifact_checksum": manifest["files"]["model.joblib"][:12],
        "training_reference": {key: training.get(key) for key in (
            "source_classification", "date_from", "date_to", "rows_eligible", "trained_at")},
    })
    results: dict[str, dict[str, Any]] = {}
    eligible: list[tuple[str, Mapping[str, Any]]] = []
    reasons: Counter = Counter()
    for row in records:
        case_id = text_value(row.get("case_id"))
        if case_id is None:
            reasons["missing:case_id"] += 1
            continue
        reason = eligibility_reason(row)
        if reason is None:
            eligible.append((case_id, row))
            continue
        reasons[reason] += 1
        results[case_id] = {"inference_status": "not_assessed", "reason": reason, "model_version": MODEL_VERSION}
    summary["not_assessed_reason_counts"] = dict(sorted(reasons.items()))
    summary["records_not_assessed"] = sum(reasons.values())
    if not eligible:
        summary["status"] = "insufficient_data"
        return summary, results
    try:
        matrix = build_features([row for _, row in eligible], reference)
        scores = [-float(value) for value in artifact["model"].score_samples(matrix).tolist()]
    except Exception as error:
        summary["error_code"] = "ML_INFERENCE_FAILED"
        summary["error_type"] = type(error).__name__
        summary["limitations"].insert(0, "Inferensi model ML gagal; skor anomali tidak dihitung. Sinyal aturan tetap tersedia.")
        return summary, {case_id: item for case_id, item in results.items()}
    n = len(eligible)
    tie_scores = [round(score, 6) for score in scores]
    sorted_scores = sorted(tie_scores)
    tie_counts = Counter(tie_scores)
    score_quantiles = reference["score_quantiles"]
    feature_quantiles = [reference["feature_quantiles"][name] for name in FEATURE_NAMES]
    # Ordering never uses keyed case IDs: score, then feature vector; equal vectors are twins.
    order = sorted(range(n), key=lambda index: (-tie_scores[index], matrix[index], index))
    items = []
    for position, index in enumerate(order):
        case_id = eligible[index][0]
        signals = []
        for column, value in enumerate(matrix[index]):
            percentile = _quantile_position(feature_quantiles[column], value)
            if percentile >= signal_min_percentile:
                signals.append({"feature": FEATURE_NAMES[column], "description": FEATURE_DESCRIPTIONS[column],
                                "training_percentile": percentile})
        signals.sort(key=lambda item: (-item["training_percentile"], item["feature"]))
        result = {
            "inference_status": "scored",
            "model_version": MODEL_VERSION,
            "anomaly_score": tie_scores[index],
            "score_direction": SCORE_DIRECTION,
            # Share of training records with a lower score: comparable across runs scored by this artifact.
            "reference_percentile": _quantile_position(score_quantiles, scores[index]),
            # Competition rank within this run; tied records share the best position of their group.
            "rank": n - bisect_right(sorted_scores, tie_scores[index]) + 1,
            "tie_count": tie_counts[tie_scores[index]],
            "anomaly_percentile": round(bisect_left(sorted_scores, tie_scores[index]) / n, 4),
            "supporting_signals": signals[:max_signals],
        }
        results[case_id] = result
        if position < top_n:
            items.append({
                "case_id": case_id, **result,
                "top_deviations": [{"feature": item["feature"], "description": item["description"],
                                    "percentile": item["training_percentile"]} for item in signals[:max_signals]],
                "explanation": ("; ".join(item["description"] for item in signals[:max_signals])
                                or "Tidak ada fitur tunggal di atas persentil 95 data latih; skor berasal dari kombinasi beberapa fitur."),
            })
    summary.update({
        "status": "available",
        "records_scored": n,
        "share_above_training_p99": round(sum(r["reference_percentile"] >= 0.99 for r in results.values()
                                              if r["inference_status"] == "scored") / n, 4),
        "items": items,
        "items_truncated": n > top_n,
    })
    return summary, results


@lru_cache(maxsize=4)
def _category_labels_from(directory: str) -> dict[str, dict[str, str]]:
    path = Path(directory) / "category_labels.json"
    try:
        labels = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return labels if isinstance(labels, dict) else {}


def category_labels() -> dict[str, dict[str, str]]:
    """Names of the FKRTL facility-category codes, exported next to the model (empty when absent)."""
    return _category_labels_from(str(Path(os.environ.get(MODEL_DIR_VARIABLE) or DEFAULT_MODEL_DIR)))


CODE_NAMES_FILE = "code_names.json"
SPECIAL_REFERENCE_FILE = "special_reference.json"


@lru_cache(maxsize=4)
def _special_reference_from(directory: str) -> dict[str, Any]:
    try:
        reference = json.loads((Path(directory) / SPECIAL_REFERENCE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return reference if isinstance(reference, dict) else {}


def special_reference() -> dict[str, Any]:
    """INA-CBG x special-code pair counts (scripts.export_special_reference; pairs < 5 never stored)."""
    return _special_reference_from(str(Path(os.environ.get(MODEL_DIR_VARIABLE) or DEFAULT_MODEL_DIR)))


@lru_cache(maxsize=4)
def _code_names_from(directory: str) -> dict[str, dict[str, str]]:
    try:
        names = json.loads((Path(directory) / CODE_NAMES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return names if isinstance(names, dict) else {}


def code_name(kind: str, code: str | None) -> str | None:
    """Name of a diagnosis ("diagnosis") or INA-CBG ("claim_group") code from scripts.export_code_names."""
    if not code:
        return None
    names = _code_names_from(str(Path(os.environ.get(MODEL_DIR_VARIABLE) or DEFAULT_MODEL_DIR))).get(kind) or {}
    return names.get(code) or names.get(code.replace(".", ""))
