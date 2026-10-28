"""Exploratory peer-relative screening for unusually long admission-to-discharge spans.

Standalone review signal: it does not feed the rule index, action lanes,
facility priority or the ML ranking. A long span relative to comparable claims
is statistically unusual; it is not evidence that the stay was unjustified or
that a claim is fraudulent.

Predeclared method (version ``los-peer-p99-v1``):
* span = discharge date (FKL04) - admission date (FKL03) in calendar days;
  date-only fields, so no hours are inferred;
* peer group = same INA-CBG (FKL19) and class of care (FKL13);
* reference = peer spans with exact copies of a record (same participant,
  dates and peer key) counted once;
* threshold = nearest-rank 99th percentile, the value at position
  ceil(0.99 * n) of the sorted reference spans;
* candidate = span strictly above the threshold and at least 1 day, so ties
  at the threshold and same-day stays are never flagged;
* minimum peer support = 100: below it the nearest-rank 99th percentile is the
  group maximum and nothing could be flagged, so records are unassessed.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
import math
from statistics import median
from typing import Any

from app.analytics.detector_utils import date_value, text_value, valid_records
from app.analytics.normalization import is_missing


INDICATOR = "length_of_stay_outlier"
LOS_VERSION = "los-peer-p99-v1"
PEER_DEFINITION = "same INA-CBG code (FKL19) and class of care (FKL13)"
UNASSESSED_REASONS = (
    "missing_date", "invalid_date", "reversed_dates", "missing_peer_key", "insufficient_peer_support",
)
LIMITATIONS = [
    "Durasi tidak biasa relatif terhadap klaim sebanding adalah sinyal statistik untuk ditinjau, bukan bukti fraud atau bukti rawat inap tidak layak.",
    "Ambang persentil ke-99 adalah pilihan penyaringan statistik, bukan batas klinis atau batas yang disetujui BPJS.",
    "Persentil dihitung dari jendela analisis terpilih; peringkat bersifat relatif terhadap jendela dan tidak sebanding antar-run.",
    "Tanggal hanya berupa tanggal (tanpa jam); kondisi klinis, komplikasi, dan status pulang tidak dipertimbangkan.",
]


@dataclass(frozen=True)
class LengthOfStayConfig:
    upper_percentile: float = 0.99
    min_peer_group_size: int = 100

    def __post_init__(self) -> None:
        if not 0 < self.upper_percentile < 1:
            raise ValueError("upper_percentile harus berada pada (0, 1)")
        if self.min_peer_group_size < 2:
            raise ValueError("min_peer_group_size minimal 2")


def nearest_rank_threshold(sorted_spans: Sequence[int], percentile: float) -> int:
    """Value at position ceil(p * n) (1-based) of an ascending sequence."""
    position = max(1, math.ceil(percentile * len(sorted_spans)))
    return sorted_spans[position - 1]


def _span(row: Mapping[str, Any]) -> tuple[int | None, str | None]:
    raw_start, raw_end = row.get("service_date"), row.get("discharge_date")
    if is_missing(raw_start) or is_missing(raw_end):
        return None, "missing_date"
    start, end = date_value(raw_start), date_value(raw_end)
    if not isinstance(start, date) or not isinstance(end, date):
        return None, "invalid_date"
    if end < start:
        return None, "reversed_dates"
    return (end - start).days, None


def row_prerequisite_reason(row: Mapping[str, Any]) -> str | None:
    """Row-level reason a record cannot enter a peer group (peer support is checked at run time)."""
    _span_days, reason = _span(row)
    if reason is not None:
        return reason
    if text_value(row.get("claim_group")) is None or text_value(row.get("care_class")) is None:
        return "missing_peer_key"
    return None


def detect_length_of_stay_outliers(
    records: Sequence[Mapping[str, Any]],
    config: LengthOfStayConfig | None = None,
) -> dict[str, Any]:
    config = config or LengthOfStayConfig()
    rows = valid_records(records)
    unassessed: dict[str, str] = {}
    eligible: list[tuple[int, str, int, tuple[str, str]]] = []  # position, case_id, span, peer key
    references: dict[tuple[str, str], dict[tuple[Any, ...], int]] = defaultdict(dict)
    for position, (case_id, row) in enumerate(rows):
        span, _ = _span(row)
        reason = row_prerequisite_reason(row)
        if reason is not None:
            unassessed[case_id] = reason
            continue
        claim_group, care_class = text_value(row.get("claim_group")), text_value(row.get("care_class"))
        key = (claim_group, care_class)
        eligible.append((position, case_id, span, key))
        # Exact copies contribute once to the reference distribution; the
        # participant token is compared only for this de-duplication.
        participant = text_value(row.get("participant_token"))
        copy_key = (participant, row.get("service_date"), row.get("discharge_date")) if participant else (case_id,)
        references[key].setdefault(copy_key, span)

    peer_stats: dict[tuple[str, str], dict[str, Any]] = {}
    for key, spans_by_copy in references.items():
        spans = sorted(spans_by_copy.values())
        if len(spans) < config.min_peer_group_size:
            peer_stats[key] = {"support": len(spans), "sufficient": False}
            continue
        peer_stats[key] = {
            "support": len(spans), "sufficient": True, "spans": spans,
            "threshold": nearest_rank_threshold(spans, config.upper_percentile),
            "median": median(spans),
        }

    candidates: list[dict[str, Any]] = []
    assessed = 0
    for position, case_id, span, key in eligible:
        stats = peer_stats[key]
        if not stats["sufficient"]:
            unassessed[case_id] = "insufficient_peer_support"
            continue
        assessed += 1
        if span < 1 or span <= stats["threshold"]:
            continue
        below = bisect_left(stats["spans"], span) / stats["support"]
        candidates.append({
            "case_id": case_id,
            "indicator": INDICATOR,
            "span_days": span,
            "peer_group_definition": PEER_DEFINITION,
            "peer_support": stats["support"],
            "peer_threshold_days": stats["threshold"],
            "peer_median_days": stats["median"],
            "share_of_peers_with_shorter_span": round(below, 4),
            "explanation": (
                f"Rentang tanggal datang-pulang {span} hari melampaui persentil ke-{round(config.upper_percentile * 100)} "
                f"({stats['threshold']} hari) dari {stats['support']} klaim sebanding (INA-CBG dan kelas rawat sama; "
                f"median {stats['median']} hari). Ini sinyal statistik, bukan bukti fraud."
            ),
            "_order": (-(span - stats["threshold"]), -span, position),
        })
    candidates.sort(key=lambda item: item.pop("_order"))
    reason_counts = Counter(unassessed.values())
    return {
        "indicator": INDICATOR,
        "status": "available" if assessed else "insufficient_data",
        "version": LOS_VERSION,
        "label": "Unusual duration relative to comparable claims (exploratory)",
        "method": {
            "span": "calendar days from admission (FKL03) to discharge (FKL04), date-only",
            "peer_group": PEER_DEFINITION,
            "reference": "peer spans in the analysed window; exact copies of a record counted once",
            "quantile": "nearest-rank: value at position ceil(p * n) of the sorted peer spans",
            "comparison": "span strictly above the threshold and at least 1 day; ties at the threshold are not flagged",
            **asdict(config),
        },
        "input_record_count": len(rows),
        "assessed_count": assessed,
        "unassessed_count": len(unassessed),
        "unassessed_reason_counts": {reason: reason_counts.get(reason, 0) for reason in UNASSESSED_REASONS},
        "peer_groups_assessed": sum(1 for stats in peer_stats.values() if stats["sufficient"]),
        "peer_groups_below_support": sum(1 for stats in peer_stats.values() if not stats["sufficient"]),
        "candidate_count": len(candidates),
        "candidates_per_1000_assessed": round(len(candidates) / assessed * 1000, 2) if assessed else None,
        "candidates": candidates,
        "limitations": LIMITATIONS.copy(),
    }
