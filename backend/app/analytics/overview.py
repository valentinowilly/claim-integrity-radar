"""Headline figures of one analysis that the overview shows and that need every claim to compute.

The overview reads a summary of the result without per-claim data, so anything that counts claims is
computed here, once, when the analysis runs:

* ``ai_confirmed_high``: high-risk claims whose pattern the claim-pattern AI also ranks among the rarest
  (at or above the policy's threshold);
* ``evidence``: of the services that must carry supporting documents, how many carry all of them;
* ``top_high_claims``: the high-risk claims with the largest billed amount (FKL47, before verification).

Amounts are for display only: they never change scores, lanes or order.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from app.analytics.facility_groups import _amount, _patterns_of

TOP_CLAIMS = 10


def _percentile(case: Mapping[str, Any] | None) -> float | None:
    anomaly = (case or {}).get("ml_anomaly") or {}
    value = anomaly.get("reference_percentile")
    if value is None:
        value = anomaly.get("anomaly_percentile")
    return float(value) if isinstance(value, (int, float)) else None


def build_overview(records: list[Mapping[str, Any]], cases: Mapping[str, Mapping[str, Any]],
                   lanes: Mapping[str, Mapping[str, Any]], ml_red_min: float | None, *,
                   per_claim_amounts: bool = True) -> dict[str, Any]:
    lane_of = {case_id: (entry or {}).get("lane") for case_id, entry in lanes.items()}
    threshold = 0.95 if ml_red_min is None else float(ml_red_min)
    confirmed = sum(1 for case_id, lane in lane_of.items()
                    if lane == "red" and (_percentile(cases.get(case_id)) or 0.0) >= threshold)

    required = complete = 0
    high: list[tuple[Decimal, str]] = []
    for record in records:
        needed = set(record.get("supporting_evidence_required") or [])
        if needed:
            required += 1
            complete += needed <= set(record.get("supporting_evidence_types") or [])
        case_id = record.get("case_id")
        if per_claim_amounts and lane_of.get(case_id) == "red":
            amount = _amount(record)
            if amount is not None:
                high.append((amount, case_id))
    high.sort(key=lambda item: (-item[0], item[1]))
    top = []
    for amount, case_id in high[:TOP_CLAIMS]:
        case = cases.get(case_id) or {}
        top.append({"case_id": case_id, "amount": int(amount), "indicators": list(case.get("indicators") or []),
                    "fraud_patterns": _patterns_of(case)})
    return {
        "version": "overview-v1",
        "ai_confirmed_high": confirmed,
        "ai_threshold": threshold,
        "evidence": {"services_requiring_evidence": required, "services_complete": complete,
                     "share_complete": round(complete / required, 4) if required else None},
        "top_high_claims": top,
        "note": "Nilai tagihan (FKL47) sebelum verifikasi, untuk tampilan saja; tidak dipakai untuk skor atau urutan.",
    }


def attach_claim_amounts(records: list[Mapping[str, Any]], cases: dict[str, dict[str, Any]]) -> None:
    """Each flagged claim carries its billed amount, so lists and claim pages can show it without the record."""
    for record in records:
        case = cases.get(record.get("case_id"))
        if case is None:
            continue
        amount = _amount(record)
        case["claim_billed_amount"] = int(amount) if amount is not None else None
