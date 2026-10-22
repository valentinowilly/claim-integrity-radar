"""Deterministic, bounded time-pattern and repeat-window rules."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.analytics.detector_utils import date_value, text_value, timestamp_value, valid_records


INDICATOR = "temporal_pattern_candidate"
LIMITATIONS = [
    "Pengulangan dalam jendela pendek dapat merupakan layanan sah atau episode perawatan.",
    "Timestamp sintetis tidak membuktikan waktu layanan yang tercatat pada sistem nyata.",
    "Jadwal seragam dapat timbul dari slot layanan atau proses pencatatan yang wajar.",
    "Detektor tidak menyimpulkan klaim duplikat atau fraud dan tidak membuat skor gabungan.",
]


@dataclass(frozen=True)
class TemporalConfig:
    repeat_window_days: int = 3
    min_repeat_claims: int = 2
    uniform_time_min_claims: int = 3
    max_case_ids: int = 20
    max_candidates: int = 500

    def __post_init__(self) -> None:
        if self.repeat_window_days < 0 or self.min_repeat_claims < 2 or self.uniform_time_min_claims < 2:
            raise ValueError("Jendela atau ambang temporal tidak valid")
        if self.max_case_ids < 1 or self.max_candidates < 1:
            raise ValueError("Batas output temporal harus positif")


def _candidate(
    kind: str, case_ids: list[str], period_from: date, period_to: date,
    details: dict[str, Any], config: TemporalConfig,
) -> dict[str, Any]:
    ids = sorted(case_ids)
    return {
        "candidate_id": f"temporal:{kind}:{ids[0]}:{ids[-1]}",
        "indicator": INDICATOR,
        "pattern_type": kind,
        "scope": "claim_group",
        "case_ids": ids[:config.max_case_ids],
        "case_count": len(ids),
        "case_ids_truncated": len(ids) > config.max_case_ids,
        "period": {"from": period_from.isoformat(), "to": period_to.isoformat(), "unit": "day"},
        "supporting_values": details,
        "reason": details["explanation"],
        "limitations": LIMITATIONS.copy(),
    }


def detect_temporal_patterns(
    records: Sequence[Mapping[str, Any]],
    config: TemporalConfig | None = None,
) -> dict[str, Any]:
    """Detect short-window repeats and exact-minute multi-participant clusters.

    A busy date by itself is not a signal. Repeats require the same participant,
    synthetic facility and service type within a configured short window.
    Uniform-time groups require several distinct participants at the same
    facility/service/date/minute.
    """
    config = config or TemporalConfig()
    validated = valid_records(records)
    repeats: dict[tuple[str, str, str], list[tuple[date, str]]] = defaultdict(list)
    uniform: dict[tuple[str, str, date, str], list[tuple[str, str]]] = defaultdict(list)
    invalid_dates: list[dict[str, str]] = []
    unassessed_times: list[dict[str, str]] = []
    for case_id, row in validated:
        participant = text_value(row.get("participant_token"))
        facility_id = text_value(row.get("facility_id"))
        service_type = text_value(row.get("service_type"))
        service_day = date_value(row.get("service_date"))
        if service_day is None:
            invalid_dates.append({"case_id": case_id, "reason": "Tanggal layanan tidak valid untuk pemeriksaan temporal."})
            continue
        if participant and facility_id and service_type:
            repeats[(participant, facility_id, service_type)].append((service_day, case_id))
        timestamp = timestamp_value(row.get("service_timestamp"))
        if timestamp is not None and facility_id and service_type and participant:
            uniform[(facility_id, service_type, timestamp.date(), timestamp.strftime("%H:%M"))].append((case_id, participant))
        elif row.get("service_timestamp") is None or timestamp is None:
            unassessed_times.append({"case_id": case_id, "reason": "Timestamp layanan tidak tersedia atau tidak valid untuk pemeriksaan waktu seragam."})

    candidates: list[dict[str, Any]] = []
    window = timedelta(days=config.repeat_window_days)
    for key in sorted(repeats):
        ordered = sorted(repeats[key], key=lambda item: (item[0], item[1]))
        start = 0
        while start < len(ordered):
            end = start + 1
            while end < len(ordered) and ordered[end][0] - ordered[start][0] <= window:
                end += 1
            chunk = ordered[start:end]
            if len(chunk) >= config.min_repeat_claims:
                day_from, day_to = chunk[0][0], chunk[-1][0]
                candidates.append(_candidate(
                    "short_window_repeat", [case_id for _, case_id in chunk], day_from, day_to,
                    {
                        "claim_count": len(chunk),
                        "participant_count": 1,
                        "window_days": config.repeat_window_days,
                        "explanation": f"{len(chunk)} klaim untuk peserta sintetis yang sama, jenis layanan dan fasilitas sintetis yang sama muncul dalam rentang {config.repeat_window_days} hari.",
                    }, config,
                ))
            start = end

    for (facility_id, service_type, service_day, minute), entries in sorted(uniform.items()):
        case_ids = sorted(case_id for case_id, _ in entries)
        participant_count = len({participant for _, participant in entries})
        if len(case_ids) >= config.uniform_time_min_claims and participant_count >= config.uniform_time_min_claims:
            candidates.append(_candidate(
                "uniform_service_minute", case_ids, service_day, service_day,
                {
                    "claim_count": len(case_ids),
                    "distinct_participant_count": participant_count,
                    "service_time_minute": minute,
                    "explanation": f"{len(case_ids)} klaim dari {participant_count} peserta berbeda tercatat pada menit layanan yang sama untuk jenis layanan dan fasilitas sintetis yang sama pada tanggal tersebut.",
                }, config,
            ))

    candidates.sort(key=lambda item: (item["pattern_type"], tuple(item["case_ids"])))
    truncated = len(candidates) > config.max_candidates
    candidates = candidates[:config.max_candidates]
    return {
        "indicator": INDICATOR,
        "input_record_count": len(validated),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "ineligible_cases": sorted(invalid_dates, key=lambda item: item["case_id"]),
        "unassessed_time_cases": sorted(unassessed_times, key=lambda item: item["case_id"]),
        "search_parameters": {
            "repeat_window_days": config.repeat_window_days,
            "min_repeat_claims": config.min_repeat_claims,
            "uniform_time_min_claims": config.uniform_time_min_claims,
            "uniform_time_unit": "same local synthetic minute within one service date",
            "max_case_ids": config.max_case_ids,
            "max_candidates": config.max_candidates,
        },
        "search_truncated": truncated,
        "limitations": LIMITATIONS.copy(),
    }
