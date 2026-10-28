"""Unsupervised Isolation Forest ranking over verified categorical claim features.

The ranking is a relative "how unusual is this record within this run"
ordering for reviewer triage. It is not a fraud probability, is not trained on
labels, and is kept separate from the rule detectors, risk index, and audit
priority. Identifiers (participant/visit references) and every amount field
(billed_amount; FKL47/FKL48 are never mapped) are excluded from the features.
The participant token is used only to count visits per participant in the run.

scikit-learn is imported lazily so the API/health import path stays free of
numerical dependencies until a run has enough records to score.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import math
from statistics import median
from typing import Any

from app.analytics.detector_utils import date_value, text_value, valid_records


ML_ANOMALY_VERSION = "isolation-forest-categorical-v1"
SCORE_TYPE = "relative_unsupervised_anomaly_rank_not_fraud_probability"
_MISSING = "__missing__"

# Verified FKRTL meanings: FKL05/06 region, FKL07-09 facility categories (not a
# facility ID), FKL16/18 diagnoses, FKL19 INA-CBG, FKL30 procedure.
CATEGORICAL_FEATURES = (
    ("province_code", "Provinsi fasilitas jarang muncul pada run ini"),
    ("municipality_code", "Kabupaten/kota fasilitas jarang muncul pada run ini"),
    ("facility_ownership", "Kategori kepemilikan fasilitas jarang"),
    ("facility_type", "Jenis fasilitas jarang"),
    ("facility_class", "Tipe/kelas fasilitas jarang"),
    ("admission_diagnosis", "Diagnosis masuk jarang"),
    ("primary_diagnosis", "Diagnosis primer jarang"),
    ("claim_group", "Kode INA-CBG jarang"),
    ("procedure_code", "Prosedur jarang (atau tidak tercatat)"),
)
# Conditional frequency P(second | first): unusual combinations of individually
# common codes, e.g. a diagnosis rarely grouped into this INA-CBG.
PAIR_FEATURES = (
    ("primary_diagnosis", "claim_group", "Kombinasi diagnosis primer dan INA-CBG jarang"),
    ("claim_group", "procedure_code", "Kombinasi INA-CBG dan prosedur jarang"),
    ("admission_diagnosis", "primary_diagnosis", "Kombinasi diagnosis masuk dan primer jarang"),
    ("facility_class", "claim_group", "INA-CBG jarang untuk tipe/kelas fasilitas ini"),
    ("municipality_code", "claim_group", "INA-CBG jarang untuk wilayah ini"),
)
DERIVED_FEATURES = (
    ("length_of_stay_deviation", "Lama rawat (tanggal datang-pulang) menyimpang dari median kelompok INA-CBG"),
    ("participant_visit_count", "Jumlah kunjungan peserta yang sama dalam jendela run tinggi"),
    ("diagnosis_changed", "Diagnosis masuk berbeda dari diagnosis primer"),
)
EXCLUDED_FIELDS = (
    "identitas peserta/kunjungan dan case_id",
    "biaya tagih provider (semantik belum terverifikasi)",
    "biaya pascaverifikasi (tidak pernah dibaca)",
    "facility_id, kapasitas, evidence, timestamp (tidak tersedia/terverifikasi)",
)
LIMITATIONS = [
    "Skor anomali bersifat relatif terhadap record dalam run ini; bukan probabilitas fraud dan tidak dilatih dengan label.",
    "Tidak ada label fraud terkonfirmasi, sehingga akurasi, presisi, atau recall model tidak dapat dan tidak diklaim.",
    "Record yang jarang dapat sah secara klinis/administratif (kasus langka, rujukan khusus); peringkat hanya membantu urutan tinjauan manusia.",
    "Penjelasan menunjukkan atribut yang paling menyimpang secara persentil, bukan atribusi kausal model.",
    "Record dengan skor sama berbagi peringkat yang sama (tie_count); urutan tampilan di antara record seri tidak bermakna.",
    "Jendela baris terbatas atau populasi kecil mengubah frekuensi pembanding; peringkat tidak dapat dibandingkan antar-run.",
]


@dataclass(frozen=True)
class MlAnomalyConfig:
    n_estimators: int = 200
    max_samples: int = 256
    random_state: int = 20260
    min_records: int = 50
    top_n: int = 200
    max_explanations: int = 3
    explanation_min_percentile: float = 0.9

    def __post_init__(self) -> None:
        if self.n_estimators < 1 or self.max_samples < 2 or self.min_records < 2 or self.top_n < 1:
            raise ValueError("Konfigurasi anomali ML tidak valid")
        if not 0 < self.explanation_min_percentile < 1:
            raise ValueError("explanation_min_percentile harus berada pada (0, 1)")


def feature_catalog() -> list[dict[str, str]]:
    return (
        [{"name": f"freq_{field}", "description": text} for field, text in CATEGORICAL_FEATURES]
        + [{"name": f"pair_{a}__{b}", "description": text} for a, b, text in PAIR_FEATURES]
        + [{"name": name, "description": text} for name, text in DERIVED_FEATURES]
    )


def _category(row: Mapping[str, Any], field: str) -> str:
    return text_value(row.get(field)) or _MISSING


def _robust_center(values: list[float]) -> tuple[float, float]:
    center = median(values)
    mad = median(abs(value - center) for value in values)
    return center, mad


def build_feature_matrix(
    rows: Sequence[tuple[str, Mapping[str, Any]]],
) -> list[list[float]]:
    """Encode categoricals as log (conditional) frequencies; no identifiers or amounts."""
    n = len(rows)
    columns: list[list[float]] = []
    for field, _ in CATEGORICAL_FEATURES:
        values = [_category(row, field) for _, row in rows]
        counts = Counter(values)
        columns.append([math.log(counts[value] / n) for value in values])
    for first, second, _ in PAIR_FEATURES:
        pairs = [(_category(row, first), _category(row, second)) for _, row in rows]
        pair_counts = Counter(pairs)
        first_counts = Counter(a for a, _ in pairs)
        columns.append([math.log(pair_counts[pair] / first_counts[pair[0]]) for pair in pairs])

    stays: list[float | None] = []
    for _, row in rows:
        start, end = date_value(row.get("service_date")), date_value(row.get("discharge_date"))
        stays.append(float((end - start).days) if start and end else None)
    by_group: dict[str, list[float]] = {}
    for (_, row), stay in zip(rows, stays):
        if stay is not None:
            by_group.setdefault(_category(row, "claim_group"), []).append(stay)
    centers = {group: _robust_center(values) for group, values in by_group.items()}
    deviations = []
    for (_, row), stay in zip(rows, stays):
        if stay is None:
            deviations.append(0.0)  # neutral when either date is unavailable
            continue
        center, mad = centers[_category(row, "claim_group")]
        deviations.append(abs(stay - center) / (mad + 1.0))
    columns.append(deviations)

    tokens = [text_value(row.get("participant_token")) for _, row in rows]
    token_counts = Counter(token for token in tokens if token is not None)
    columns.append([math.log1p(token_counts[token]) if token is not None else 0.0 for token in tokens])
    columns.append([
        1.0 if (text_value(row.get("admission_diagnosis")) and text_value(row.get("primary_diagnosis"))
                and text_value(row.get("admission_diagnosis")) != text_value(row.get("primary_diagnosis")))
        else 0.0
        for _, row in rows
    ])
    return [list(values) for values in zip(*columns)]


def _oriented(matrix: list[list[float]]) -> list[list[float]]:
    """Orient each column so that larger means more unusual (rare frequencies are low)."""
    frequency_columns = len(CATEGORICAL_FEATURES) + len(PAIR_FEATURES)
    return [[-value if index < frequency_columns else value for index, value in enumerate(row)] for row in matrix]


def build_ml_anomaly_ranking(
    records: Sequence[Mapping[str, Any]],
    config: MlAnomalyConfig | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Return the persisted summary and a per-case rank map for all scored records."""
    config = config or MlAnomalyConfig()
    rows = valid_records(records)
    summary: dict[str, Any] = {
        "status": "insufficient_data",
        "model": "IsolationForest (scikit-learn)",
        "model_version": ML_ANOMALY_VERSION,
        "score_type": SCORE_TYPE,
        "parameters": asdict(config),
        "records_considered": len(records),
        "records_scored": 0,
        "features": feature_catalog(),
        "excluded_fields": list(EXCLUDED_FIELDS),
        "items": [],
        "items_truncated": False,
        "limitations": LIMITATIONS.copy(),
    }
    if len(rows) < config.min_records:
        summary["limitations"].insert(0, f"Minimal {config.min_records} record diperlukan untuk peringkat anomali; run ini tidak diberi peringkat.")
        return summary, {}
    try:
        from sklearn.ensemble import IsolationForest
    except ImportError:
        summary["status"] = "unavailable"
        summary["limitations"].insert(0, "scikit-learn tidak terpasang; peringkat anomali ML tidak dijalankan.")
        return summary, {}

    matrix = build_feature_matrix(rows)
    n = len(rows)
    # Fit on a canonical row order (sorted feature vectors). IsolationForest
    # subsamples by row index, so fitting in input order made scores depend on
    # file order; identical vectors are interchangeable, so this order makes
    # the fitted model a function of the feature multiset only.
    canonical = sorted(range(n), key=lambda index: (matrix[index], index))
    model = IsolationForest(
        n_estimators=config.n_estimators,
        max_samples=min(config.max_samples, n),
        random_state=config.random_state,
    )
    model.fit([matrix[index] for index in canonical])
    # score_samples is higher for normal points; negate so higher = more unusual.
    scores = [-float(value) for value in model.score_samples(matrix).tolist()]
    # Tie groups use the reported precision so displayed equal scores share a rank.
    tie_scores = [round(score, 6) for score in scores]
    sorted_scores = sorted(tie_scores)
    tie_counts = Counter(tie_scores)
    # Presentation order never uses keyed case IDs: score, then feature vector;
    # equal vectors are indistinguishable, so input position only orders twins.
    order = sorted(range(n), key=lambda index: (-tie_scores[index], matrix[index], index))
    ranks: dict[str, dict[str, Any]] = {}
    for index in order:
        higher = n - bisect_right(sorted_scores, tie_scores[index])
        ranks[rows[index][0]] = {
            # Competition rank: tied records share the best position of their group.
            "rank": higher + 1,
            "tie_count": tie_counts[tie_scores[index]],
            "anomaly_score": round(scores[index], 6),
            # Share of scored records with a strictly lower anomaly score.
            "anomaly_percentile": round(bisect_left(sorted_scores, tie_scores[index]) / n, 4),
        }

    oriented = _oriented(matrix)
    sorted_columns = [sorted(column) for column in zip(*oriented)]
    catalog = feature_catalog()
    items = []
    for index in order[:config.top_n]:
        case_id = rows[index][0]
        deviations = []
        for column, value in enumerate(oriented[index]):
            percentile = bisect_left(sorted_columns[column], value) / n
            if percentile >= config.explanation_min_percentile:
                deviations.append({
                    "feature": catalog[column]["name"],
                    "description": catalog[column]["description"],
                    "percentile": round(percentile, 4),
                })
        deviations.sort(key=lambda item: (-item["percentile"], item["feature"]))
        items.append({
            "case_id": case_id,
            **ranks[case_id],
            "top_deviations": deviations[:config.max_explanations],
            "explanation": (
                "; ".join(item["description"] for item in deviations[:config.max_explanations])
                or "Kombinasi beberapa atribut yang masing-masing tidak ekstrem."
            ),
        })
    summary.update({
        "status": "available",
        "records_scored": n,
        "items": items,
        "items_truncated": n > config.top_n,
    })
    return summary, ranks
