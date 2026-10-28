"""Claims per service date and how many of them are high or medium risk (aggregate, for the trend page).

Counts only: no claim, participant or facility appears. The billed value is display-only, as in the facility
groups' exposure, and never enters scoring, lanes or ordering.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from app.analytics.facility_groups import _amount

VERSION = "daily-activity-v1"
MAX_DAYS = 400  # about a year of service dates; longer files keep the latest days


def build_daily_activity(records: list[Mapping[str, Any]], lanes: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    lane_of = {case_id: (entry or {}).get("lane") for case_id, entry in lanes.items()}
    days: dict[str, dict[str, Any]] = {}
    undated = 0
    for record in records:
        day = str(record.get("service_date") or "")[:10]
        if len(day) != 10:
            undated += 1
            continue
        bucket = days.setdefault(day, {"date": day, "claims": 0, "high": 0, "medium": 0, "billed": Decimal(0), "with_amount": 0})
        bucket["claims"] += 1
        lane = lane_of.get(record.get("case_id"))
        if lane == "red":
            bucket["high"] += 1
        elif lane == "yellow":
            bucket["medium"] += 1
        amount = _amount(record)
        if amount is not None:
            bucket["with_amount"] += 1
            if lane in ("red", "yellow"):
                bucket["billed"] += amount
    ordered = sorted(days.values(), key=lambda item: item["date"])
    truncated = len(ordered) > MAX_DAYS
    ordered = ordered[-MAX_DAYS:]
    return {
        "version": VERSION,
        "status": "available" if ordered else "unavailable",
        "days": [{"date": item["date"], "claims": item["claims"], "high": item["high"], "medium": item["medium"],
                  "billed_high_or_medium": int(item["billed"]) if item["with_amount"] else None} for item in ordered],
        "days_truncated": truncated,
        "undated_claims": undated,
        "note": "Tanggal = tanggal masuk/layanan klaim. Porsi berisiko per hari adalah petunjuk pemeriksaan, bukan bukti kecurangan.",
    }
