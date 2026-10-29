"""Synthetic facility/service/day capacity rule; not a clinical standard."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.analytics.detector_utils import date_value, nonnegative_decimal, text_value, valid_records


INDICATOR = "synthetic_capacity_candidate"
LIMITATIONS = [
    "Kapasitas adalah parameter buatan untuk simulasi, bukan standar klinis atau kapasitas BPJS.",
    "Metadata hanya menyediakan kapasitas fasilitas harian, bukan kapasitas per jenis layanan atau jumlah tenaga.",
    "Volume yang melampaui parameter tidak membuktikan layanan fiktif, pelanggaran, atau fraud.",
]


@dataclass(frozen=True)
class CapacityConfig:
    max_utilization: Decimal = Decimal("1.0")
    window_days: int = 1
    max_case_ids: int = 20

    def __post_init__(self) -> None:
        if self.max_utilization <= 0:
            raise ValueError("max_utilization harus lebih besar dari nol")
        if self.window_days != 1:
            raise ValueError("Generator saat ini menyediakan kapasitas harian; window_days harus 1")
        if self.max_case_ids < 1:
            raise ValueError("max_case_ids minimal 1")


def detect_capacity_candidates(
    records: Sequence[Mapping[str, Any]],
    facilities: Sequence[Mapping[str, Any]],
    config: CapacityConfig | None = None,
) -> dict[str, Any]:
    """Compare grouped synthetic service units with facility daily capacity.

    Groups are facility ID + service type + service date. The facility-wide
    capacity is used as a conservative upper bound for each service group;
    no service-specific capacity or staffing is fabricated here.
    """
    config = config or CapacityConfig()
    multiplier = Decimal(str(config.max_utilization))
    validated = valid_records(records)
    capacities: dict[str, Decimal] = {}
    invalid_facilities: set[str] = set()
    for facility in facilities:
        facility_id = text_value(facility.get("facility_id"))
        capacity = nonnegative_decimal(facility.get("daily_capacity_units"))
        if facility_id is None:
            continue
        if capacity is None or capacity <= 0 or facility_id in capacities:
            invalid_facilities.add(facility_id)
            capacities.pop(facility_id, None)
            continue
        if facility_id not in invalid_facilities:
            capacities[facility_id] = capacity

    grouped: dict[tuple[str, str, Any], dict[str, Any]] = defaultdict(lambda: {"units": Decimal(0), "case_ids": []})
    ineligible: list[dict[str, str]] = []
    not_applicable: list[dict[str, str]] = []
    for case_id, row in validated:
        facility_id = text_value(row.get("facility_id"))
        service_type = text_value(row.get("service_type"))
        service_day = date_value(row.get("service_date"))
        units = nonnegative_decimal(row.get("service_units"))
        if row.get("operational_scope") == "none":
            # The source marks this claim as no recorded service (operational columns present but empty).
            not_applicable.append({"case_id": case_id, "reason": "Klaim ini tidak memuat data layanan berkapasitas."})
            continue
        if facility_id is None or service_type is None or service_day is None or units is None:
            ineligible.append({"case_id": case_id, "reason": "Fasilitas, jenis layanan, tanggal, atau unit layanan tidak lengkap/tidak valid."})
            continue
        if facility_id in invalid_facilities:
            ineligible.append({"case_id": case_id, "reason": "Metadata kapasitas fasilitas duplikat atau tidak valid."})
            continue
        if facility_id not in capacities:
            ineligible.append({"case_id": case_id, "reason": "Metadata kapasitas fasilitas tidak tersedia."})
            continue
        group = grouped[(facility_id, service_type, service_day)]
        group["units"] += units
        group["case_ids"].append(case_id)

    candidates: list[dict[str, Any]] = []
    sorted_groups = sorted(grouped.items(), key=lambda item: item[0])
    for candidate_number, ((facility_id, service_type, service_day), group) in enumerate(sorted_groups, start=1):
        capacity = capacities[facility_id]
        limit = capacity * multiplier
        observed = group["units"]
        if observed <= limit:
            continue
        case_ids = sorted(group["case_ids"])
        ratio = observed / capacity
        candidates.append({
            "candidate_id": f"capacity-{candidate_number:06d}",
            "indicator": INDICATOR,
            "scope": "facility_service_day",
            "facility_id": facility_id,
            "case_ids": case_ids[:config.max_case_ids],
            "case_count": len(case_ids),
            "case_ids_truncated": len(case_ids) > config.max_case_ids,
            "service_type": service_type,
            "period": {"from": service_day.isoformat(), "to": service_day.isoformat(), "unit": "day"},
            "observed_service_units": int(observed) if observed == observed.to_integral_value() else float(observed),
            "capacity_service_units": int(capacity) if capacity == capacity.to_integral_value() else float(capacity),
            "capacity_threshold_multiplier": float(multiplier),
            "utilization_ratio": round(float(ratio), 4),
            "reason": (
                f"{len(case_ids)} klaim sintetis pada satu fasilitas/jenis layanan/tanggal "
                f"mencatat {observed} unit layanan, melebihi kapasitas simulasi {limit} unit per hari."
            ),
            "limitations": LIMITATIONS.copy(),
        })
    return {
        "indicator": INDICATOR,
        "input_record_count": len(validated),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "ineligible_cases": sorted(ineligible, key=lambda item: item["case_id"]),
        "not_applicable_cases": sorted(not_applicable, key=lambda item: item["case_id"]),
        "capacity_unit": "synthetic service units per facility per day",
        "limitations": LIMITATIONS.copy(),
    }
