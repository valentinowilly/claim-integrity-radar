"""Aggregate check of the claim-detail rules and the regional facility comparison on the configured FKRTL window.

Prints counts only (no row, identifier or code): how many claims the severity-without-secondary and unusual
special top-up checks flag, and how many facility groups show a regional comparison signal. Run before the
checks drive any risk level, as for the clinical rules.

Usage (local, authorised data use): set BPJS_FKRTL_SAMPLE_PATH, BPJS_FKRTL_SECONDARY_PATH,
BPJS_FKRTL_DATE_FROM/TO and CIR_FKRTL_PSEUDONYM_KEY, then python -m scripts.check_claim_detail_rules_real
"""

from __future__ import annotations

from collections import Counter
import json

from app.analytics.claim_detail_rules import detect_severity_without_secondary, detect_unusual_special_topup
from app.analytics.facility_groups import GROUP_FIELDS, MIN_CLAIMS, _key, _peer_counts, _peer_signals
from app.analytics.ml_model import special_reference
from app.data_sources.fkrtl_local_source import load_fkrtl_local_source


def _summary(result: dict) -> dict:
    flagged = {item["case_id"] for item in result.get("candidates", [])}
    assessed = result.get("assessed_count") or 0
    return {"status": result["status"], "assessed": assessed, "flagged_claims": len(flagged),
            "share_of_assessed": round(len(flagged) / assessed, 5) if assessed else None}


def main() -> None:
    loaded = load_fkrtl_local_source()
    records = list(loaded.dataset.records)
    linked = sum(record.get("secondary_diagnoses") is not None for record in records)
    with_secondary = sum(bool(record.get("secondary_diagnoses")) for record in records)
    with_special = sum(bool(record.get("special_codes")) for record in records)
    stats: dict = {}
    claims: Counter = Counter()
    for record in records:
        key = _key(record)
        if key is None:
            continue
        claims[key] += 1
        for kind, (base, hits) in _peer_counts(record).items():
            totals = stats.setdefault(key, {}).setdefault(kind, [0, 0])
            totals[0] += base
            totals[1] += hits
    signals = Counter(signal["kind"] for key, count in claims.items() if count >= MIN_CLAIMS
                      for signal in _peer_signals(key, stats))
    print(json.dumps({
        "claims": len(records), "window": [day.isoformat() for day in loaded.date_window],
        "secondary_linked": linked, "with_secondary_diagnosis": with_secondary, "with_special_code": with_special,
        "severity_without_secondary": _summary(detect_severity_without_secondary(records)),
        "unusual_special_topup": _summary(detect_unusual_special_topup(records, special_reference())),
        "facility_groups_shown": sum(count >= MIN_CLAIMS for count in claims.values()),
        "facility_groups_with_peer_signal": dict(signals), "group_fields": list(GROUP_FIELDS),
    }, indent=1))


if __name__ == "__main__":
    main()
