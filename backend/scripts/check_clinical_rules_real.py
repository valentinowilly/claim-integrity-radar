"""Aggregate check of the three clinical rule checks on the configured FKRTL window (counts only).

Prints how many claims each check flags at the declared thresholds and at nearby alternatives, so the
thresholds are chosen before the checks drive any risk level. No row, identifier or code is printed.

Usage (local, authorised data use): set BPJS_FKRTL_SAMPLE_PATH, BPJS_FKRTL_DATE_FROM/TO and
CIR_FKRTL_PSEUDONYM_KEY, then python -m scripts.check_clinical_rules_real
"""

from __future__ import annotations

import json
from dataclasses import replace

from app.analytics.clinical_rules import (
    ClinicalRulesConfig, detect_extreme_stay, detect_rapid_readmission, detect_unusual_severity,
)
from app.analytics.ml_model import load_artifact
from app.data_sources.fkrtl_local_source import load_fkrtl_local_source


def _summary(result: dict) -> dict:
    members = {case for item in result["candidates"] for case in (item.get("case_ids") or [item["case_id"]])}
    assessed = result.get("assessed_count") or 0
    return {"assessed": assessed, "flagged_claims": len(members),
            "share_of_assessed": round(len(members) / assessed, 4) if assessed else None}


def main() -> None:
    loaded = load_fkrtl_local_source()
    records = list(loaded.dataset.records)
    reference = load_artifact()["reference"]
    base = ClinicalRulesConfig()
    report = {"claims": len(records), "window": [day.isoformat() for day in loaded.date_window], "rules": {}}
    report["rules"]["extreme_stay"] = {
        f"excess>={days}d,z>={z}": _summary(detect_extreme_stay(records, reference, replace(base, min_excess_days=days, robust_z=z)))
        for days, z in ((5, 4.0), (7, 5.0), (10, 6.0))}
    report["rules"]["rapid_readmission"] = {
        f"<={days}d": _summary(detect_rapid_readmission(records, replace(base, readmission_days=days))) for days in (1, 3, 7)}
    report["rules"]["unusual_severity"] = {
        f"share<{share}": _summary(detect_unusual_severity(records, reference, replace(base, max_severity_share=share)))
        for share in (0.02, 0.05, 0.10)}
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
