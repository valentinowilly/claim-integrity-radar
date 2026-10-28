"""Two rule checks on claim details of the BPJS FKRTL format: severity without a secondary diagnosis, and
special top-ups (drugs, prostheses, procedures, investigations, sub-acute) unusual for the INA-CBG.

Both follow the BPJS sample guide: the INA-CBG severity digit reflects comorbidity or complication, recorded
as secondary diagnoses (separate secondary-diagnosis file, FKL24); special top-ups are billed in FKL33-FKL46.
Results use the standard detector shape, so they are scored, laned and reviewed like the other rule checks.
Findings are review prompts, not evidence of fraud.

Predeclared rules (version ``claim-detail-rules-v1``), measured on the 2024 sample before use
(scripts/profile_special_and_secondary_real.py, aggregates only):
* severity without secondary diagnosis: an inpatient INA-CBG of severity II or III with no secondary
  diagnosis at all. In the sample, 99.8% of severity II and 99.96% of severity III inpatient claims carry at
  least one. Only claims whose source provides secondary diagnoses are assessed.
* unusual special top-up: a special code billed with an INA-CBG it accompanied fewer than
  ``MIN_PAIR_COUNT`` times in the reference (pairs below that count were never stored). Repeated special
  drugs are deliberately not a rule: monthly haemophilia and iron-chelation drugs repeat legitimately.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from app.analytics.detector_utils import text_value, valid_records

VERSION = "claim-detail-rules-v1"
SEVERITY_NO_SECONDARY = "severity_without_secondary_candidate"
UNUSUAL_SPECIAL = "unusual_special_topup_candidate"
INDICATORS = (SEVERITY_NO_SECONDARY, UNUSUAL_SPECIAL)
CBG = re.compile(r"^([A-Z])-(\d)-(\d{2})-(0|I|II|III)$")
INPATIENT_CASE_TYPES = {"1", "4", "6"}
MIN_PAIR_COUNT = 5
SEP = "\x1f"
SPECIAL_KIND = {"YY": "prosedur khusus", "DD": "obat khusus", "RR": "alat/prostesis khusus",
                "II": "pemeriksaan khusus", "SA": "perawatan sub-akut"}


def _result(indicator: str, rows: list, candidates: list, unassessed: list, not_applicable: list,
            limitations: list[str]) -> dict[str, Any]:
    status = "not_applicable" if rows and len(not_applicable) == len(rows) else "complete"
    return {
        "indicator": indicator, "status": status, "version": VERSION,
        "input_record_count": len(rows),
        "assessed_count": len(rows) - len(unassessed) - len(not_applicable),
        "candidate_count": len(candidates), "candidates": candidates,
        "unassessed_case_ids": unassessed,
        "not_applicable_cases": [{"case_id": case_id} for case_id in not_applicable],
        "search_truncated": False, "limitations": limitations,
    }


def _codes(value: Any) -> list[str] | None:
    """A list of non-empty codes, or None when the source does not provide the field at all."""
    if value is None:
        return None
    return [text for text in (text_value(item) for item in value) if text]


def detect_severity_without_secondary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = valid_records(records)
    candidates, unassessed, not_applicable = [], [], []
    for case_id, row in rows:
        secondary = _codes(row.get("secondary_diagnoses"))
        match = CBG.match(text_value(row.get("claim_group")) or "")
        if secondary is None:
            not_applicable.append(case_id)  # the source has no secondary-diagnosis data
            continue
        if match is None:
            unassessed.append(case_id)
            continue
        if match.group(2) not in INPATIENT_CASE_TYPES or match.group(4) not in ("II", "III"):
            not_applicable.append(case_id)
            continue
        if not secondary:
            candidates.append({
                "case_id": case_id, "candidate_id": f"nosecondary-{case_id}",
                "reason": (f"INA-CBG rawat inap keparahan {match.group(4)} tanpa satu pun diagnosis sekunder. "
                           "Keparahan II/III ditentukan oleh komorbid atau komplikasi; di data sampel BPJS 2024 "
                           "hampir semua klaim seperti ini (99,8%) mencatat diagnosis sekunder."),
                "supporting_values": {"severity": match.group(4), "secondary_diagnosis_count": 0},
            })
    return _result(SEVERITY_NO_SECONDARY, rows, candidates, unassessed, not_applicable, [
        "Diagnosis sekunder yang tidak terekam di sistem tetap mungkin; periksa resume medis sebelum menyimpulkan.",
    ])


def detect_unusual_special_topup(records: Sequence[Mapping[str, Any]],
                                 special_reference: Mapping[str, Any] | None) -> dict[str, Any]:
    rows = valid_records(records)
    if not special_reference or not special_reference.get("pairs"):
        return {"indicator": UNUSUAL_SPECIAL, "status": "unavailable", "error_type": "ReferenceUnavailable",
                "input_record_count": len(rows), "candidates": []}
    pairs, known = special_reference["pairs"], special_reference.get("codes") or {}
    candidates, unassessed, not_applicable = [], [], []
    for case_id, row in rows:
        codes = _codes(row.get("special_codes"))
        if not codes:
            not_applicable.append(case_id)  # no special top-up billed (or the source lacks the columns)
            continue
        group = text_value(row.get("claim_group"))
        if group is None:
            unassessed.append(case_id)
            continue
        unusual = [code for code in codes if pairs.get(f"{group}{SEP}{code}", 0) < MIN_PAIR_COUNT]
        if unusual:
            names = ", ".join(f"{code} ({SPECIAL_KIND.get(code[:2], 'tambahan khusus')})" for code in unusual)
            unknown = [code for code in unusual if code not in known]
            candidates.append({
                "case_id": case_id, "candidate_id": f"special-{case_id}",
                "reason": (f"Tambahan {names} ditagihkan bersama INA-CBG {group}, pasangan yang di data acuan muncul "
                           f"kurang dari {MIN_PAIR_COUNT} kali"
                           + (" (kode khusus ini sendiri tidak dikenal di data acuan)" if unknown else "")
                           + ". Periksa indikasi medis dan bukti pemberian obat/alat atau tindakannya."),
                "supporting_values": {"unusual_codes": unusual, "claim_group": group},
            })
    return _result(UNUSUAL_SPECIAL, rows, candidates, unassessed, not_applicable, [
        "Pasangan langka bisa sah (kasus jarang); bukti penyerahan obat atau alat tidak tersedia di data klaim.",
    ])
