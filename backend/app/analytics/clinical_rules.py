"""Three rule checks on the BPJS FKRTL columns: extreme stay, rapid readmission, unusual severity.

Each check returns the standard detector result (``candidates`` with reasons, ``unassessed_case_ids``,
``not_applicable_cases``) so it is scored, laned and reviewed like the other rule checks. Findings are
review prompts, not evidence of fraud.

Reference statistics come from the aggregate tables of the trained model (median and MAD of the stay per
INA-CBG and class of care, diagnosis–INA-CBG combination counts; combinations seen fewer than 5 times were
never kept). They describe the training sample, not a clinical standard. Without the model the stay and
severity checks are unavailable for the run; the readmission check needs no reference.

Predeclared thresholds (version ``clinical-rules-v1``):
* extreme stay: inpatient stay at least ``min_excess_days`` above the reference median of the same INA-CBG
  and class of care and at least ``robust_z`` robust deviations (1.4826 x MAD, MAD at least 1 day) above it;
* rapid readmission: the same participant admitted again as an inpatient with the same primary diagnosis
  within ``readmission_days`` days of the previous discharge;
* unusual severity: an INA-CBG of severity II or III whose severity, for the same primary diagnosis and
  base INA-CBG, makes up less than ``max_severity_share`` of the reference claims (at least
  ``min_severity_support`` reference claims of that diagnosis and base INA-CBG).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from app.analytics.detector_utils import date_value, text_value, valid_records

VERSION = "clinical-rules-v1"
LONG_STAY = "length_of_stay_extreme_candidate"
READMISSION = "rapid_readmission_candidate"
SEVERITY = "unusual_severity_candidate"
INDICATORS = (LONG_STAY, READMISSION, SEVERITY)
CBG = re.compile(r"^([A-Z])-(\d)-(\d{2})-(0|I|II|III)$")
SEVERITY_LEVEL = {"0": 0, "I": 1, "II": 2, "III": 3}
SEP = "\x1f"


@dataclass(frozen=True)
class ClinicalRulesConfig:
    min_excess_days: int = 7
    robust_z: float = 5.0
    readmission_days: int = 3
    max_severity_share: float = 0.05
    min_severity_support: int = 30


def _stay(row: Mapping[str, Any]) -> int | None:
    start, end = date_value(row.get("service_date")), date_value(row.get("discharge_date"))
    if start is None or end is None or end < start:
        return None
    return (end - start).days


def _result(indicator: str, rows: list[tuple[str, Mapping[str, Any]]], candidates: list[dict[str, Any]],
            unassessed: list[str], not_applicable: list[str], limitations: list[str]) -> dict[str, Any]:
    return {
        "indicator": indicator,
        "status": "complete",
        "version": VERSION,
        "input_record_count": len(rows),
        "assessed_count": len(rows) - len(unassessed) - len(not_applicable),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "unassessed_case_ids": unassessed,
        "not_applicable_cases": [{"case_id": case_id} for case_id in not_applicable],
        "search_truncated": False,
        "limitations": limitations,
    }


def _unavailable(indicator: str, rows: list[tuple[str, Mapping[str, Any]]]) -> dict[str, Any]:
    return {"indicator": indicator, "status": "unavailable", "error_type": "ReferenceUnavailable",
            "input_record_count": len(rows), "candidates": []}


def detect_extreme_stay(records: Sequence[Mapping[str, Any]], reference: Mapping[str, Any] | None,
                        config: ClinicalRulesConfig | None = None) -> dict[str, Any]:
    config = config or ClinicalRulesConfig()
    rows = valid_records(records)
    if not reference:
        return _unavailable(LONG_STAY, rows)
    fine, coarse = reference.get("stay_peer_fine") or {}, reference.get("stay_peer_coarse") or {}
    candidates, unassessed, not_applicable = [], [], []
    for case_id, row in rows:
        stay, group = _stay(row), text_value(row.get("claim_group"))
        if stay is None or group is None:
            unassessed.append(case_id)
            continue
        if stay < 1:
            not_applicable.append(case_id)  # same-day care: no stay to compare
            continue
        peer = fine.get(f"{group}|{text_value(row.get('care_class')) or '__missing__'}") or coarse.get(group)
        if not peer:
            unassessed.append(case_id)
            continue
        center, mad = float(peer[0]), float(peer[1])
        limit = max(center + config.min_excess_days, center + config.robust_z * 1.4826 * max(mad, 1.0))
        if stay > limit:
            candidates.append({
                "case_id": case_id, "candidate_id": f"los-{case_id}",
                "reason": (f"Lama rawat {stay} hari, jauh di atas kebiasaan INA-CBG yang sama di data acuan "
                           f"(median {center:g} hari; batas {limit:.0f} hari)."),
                "supporting_values": {"stay_days": stay, "reference_median_days": center, "limit_days": round(limit, 1)},
            })
    return _result(LONG_STAY, rows, candidates, unassessed, not_applicable, [
        "Data acuan adalah data sampel latih, bukan standar klinis; komplikasi dan status pulang tidak tersedia di data.",
    ])


def detect_rapid_readmission(records: Sequence[Mapping[str, Any]],
                             config: ClinicalRulesConfig | None = None) -> dict[str, Any]:
    config = config or ClinicalRulesConfig()
    rows = valid_records(records)
    by_patient: dict[tuple[str, str], list[tuple[Any, Any, str]]] = defaultdict(list)
    unassessed, not_applicable = [], []
    for case_id, row in rows:
        participant, diagnosis = text_value(row.get("participant_token")), text_value(row.get("primary_diagnosis"))
        stay = _stay(row)
        if participant is None or diagnosis is None or stay is None:
            unassessed.append(case_id)
            continue
        if stay < 1:
            not_applicable.append(case_id)
            continue
        by_patient[(participant, diagnosis)].append((date_value(row["service_date"]), date_value(row["discharge_date"]), case_id))
    candidates = []
    for admissions in by_patient.values():
        admissions.sort()
        for previous, current in zip(admissions, admissions[1:]):
            gap = (current[0] - previous[1]).days
            if 0 <= gap <= config.readmission_days:
                candidates.append({
                    "case_ids": [previous[2], current[2]], "candidate_id": f"readmit-{current[2]}",
                    "reason": (f"Peserta yang sama dirawat inap lagi {gap} hari setelah pulang dengan diagnosis utama "
                               "yang sama. Periksa apakah ini satu episode yang dipecah menjadi dua klaim."),
                    "supporting_values": {"days_between": gap},
                })
    return _result(READMISSION, rows, candidates, unassessed, not_applicable, [
        "Hanya membandingkan klaim di dalam data yang dianalisis; rawat inap ulang yang sah (mis. kontrol terjadwal "
        "atau kondisi berbeda dengan diagnosis sama) tetap mungkin.",
    ])


def severity_reference(reference: Mapping[str, Any] | None) -> dict[tuple[str, str], dict[int, int]]:
    """Reference claims per (primary diagnosis, base INA-CBG) and severity level, from the pair table."""
    table: dict[tuple[str, str], dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for key, count in ((reference or {}).get("pair_counts", {}).get("primary_diagnosis__claim_group") or {}).items():
        diagnosis, group = key.split(SEP)
        match = CBG.match(group)
        if match:
            table[(diagnosis, "-".join(match.group(1, 2, 3)))][SEVERITY_LEVEL[match.group(4)]] += count
    return table


def detect_unusual_severity(records: Sequence[Mapping[str, Any]], reference: Mapping[str, Any] | None,
                            config: ClinicalRulesConfig | None = None) -> dict[str, Any]:
    config = config or ClinicalRulesConfig()
    rows = valid_records(records)
    if not reference:
        return _unavailable(SEVERITY, rows)
    table = severity_reference(reference)
    candidates, unassessed, not_applicable = [], [], []
    for case_id, row in rows:
        diagnosis, group = text_value(row.get("primary_diagnosis")), text_value(row.get("claim_group"))
        match = CBG.match(group or "")
        if diagnosis is None or match is None:
            unassessed.append(case_id)
            continue
        level = SEVERITY_LEVEL[match.group(4)]
        if level < 2:
            not_applicable.append(case_id)
            continue
        counts = table.get((diagnosis, "-".join(match.group(1, 2, 3))))
        support = sum(counts.values()) if counts else 0
        if support < config.min_severity_support:
            unassessed.append(case_id)
            continue
        share = sum(count for severity, count in counts.items() if severity >= level) / support
        if share < config.max_severity_share:
            candidates.append({
                "case_id": case_id, "candidate_id": f"severity-{case_id}",
                "reason": (f"INA-CBG keparahan {match.group(4)} jarang dipakai untuk diagnosis utama ini: hanya "
                           f"{share:.0%} dari {support} klaim acuan dengan diagnosis dan kelompok INA-CBG yang sama. "
                           "Periksa diagnosis sekunder dan resume medis yang mendasari tingkat keparahan."),
                "supporting_values": {"severity_share": round(share, 4), "reference_support": support},
            })
    return _result(SEVERITY, rows, candidates, unassessed, not_applicable, [
        "Perbandingan dengan pola diagnosis di data acuan; temuan ini adalah petunjuk untuk memeriksa resume medis, "
        "bukan bukti upcoding. Klaim keparahan tinggi tanpa diagnosis sekunder diperiksa terpisah.",
    ])
