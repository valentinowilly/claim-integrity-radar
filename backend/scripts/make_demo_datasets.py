"""Build the three demo CSV files (wholly synthetic) and check that each tells its story.

1. demo-1-faskes-jujur.csv     no fraud; honest claims that resemble fraud (routine therapy, weekly series)
2. demo-2-kasus-kpk.csv        the same honest world plus one facility that bills physiotherapy without records
                               (about 75% without session logs, as in the KPK finding of 1,072 of 4,341), cloning
                               and repeat billing
3. demo-3-operasional.csv      a month of operations: about 4% fraud over all five modes, plus honest lookalikes

Codes follow a long-tailed distribution (a few very common, many rare) and tariffs follow the service, so the
AI sees routine care as routine. Answer keys are written next to each CSV (never inside it: the importer
rejects label columns). Usage: python -m scripts.make_demo_datasets --out ../demo-data [--check]
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.data_sources.synthetic_csv import CSV_COLUMNS, export_synthetic_csv

START = date(2024, 9, 2)
DAYS = 28
PROVINCES = ["Provinsi Contoh A", "Provinsi Contoh B", "Provinsi Contoh C", "Provinsi Contoh D", "Provinsi Contoh E"]
CLASSES = [("RS Kelas A", 160), ("RS Kelas B", 110), ("RS Kelas C", 70), ("RS Kelas D", 45)]
OWNERSHIP = ["Pemerintah", "Swasta"]
# service type -> (share of claims, tariff range in rupiah, evidence rule or None, number of codes)
SERVICES: dict[str, tuple[float, tuple[int, int], tuple[str, ...] | None, int]] = {
    "outpatient": (0.55, (150_000, 300_000), None, 40),
    "laboratory": (0.12, (90_000, 180_000), None, 15),
    "physiotherapy": (0.13, (140_000, 160_000), ("therapy_session_log", "clinical_note"), 8),
    "synthetic_supported_action": (0.08, (2_000_000, 4_500_000), ("procedure_order", "clinical_note"), 12),
    "inpatient": (0.12, (2_500_000, 9_000_000), None, 25),
}


class World:
    """Facilities, code catalogues and a claim factory with long-tailed codes and per-facility minutes."""

    def __init__(self, seed: int, facility_count: int):
        self.rng = random.Random(seed)
        self.records: list[dict[str, Any]] = []
        self.labels: dict[str, str] = {}
        self.minutes: dict[tuple[str, str], set[int]] = defaultdict(set)
        self.next_claim = 1
        self.next_patient = 1
        self.facilities = []
        for index in range(facility_count):
            klass, capacity = CLASSES[min(index % 7, 3)]
            province = PROVINCES[index % len(PROVINCES)]
            self.facilities.append({
                "facility_id": f"syn-facility-{index + 1:04d}", "province_code": province,
                "municipality_code": f"Kota Contoh {index + 1:02d}", "facility_ownership": OWNERSHIP[index % 2],
                "facility_type": "Rumah sakit", "facility_class": klass, "capacity": capacity,
                "weight": {"RS Kelas A": 3.0, "RS Kelas B": 2.0, "RS Kelas C": 1.3, "RS Kelas D": 0.8}[klass],
            })
        self.catalog: dict[str, list[dict[str, Any]]] = {}
        for service, (_, (low, high), _, count) in SERVICES.items():
            entries = []
            for code in range(count):
                tariff = self.rng.randrange(low, high, 50)
                diagnoses = [f"SYN-DX-{service[:3].upper()}{code:02d}{d}" for d in range(6)]
                entries.append({"claim_group": f"SYN-CBG-{service[:3].upper()}-{code:02d}", "billed_amount": f"{tariff}.00",
                                "procedures": [f"SYN-PROC-{service[:3].upper()}{code:02d}{p}" for p in range(3)],
                                "diagnoses": diagnoses})
            self.catalog[service] = entries

    def zipf(self, items: list[Any], exponent: float = 1.1) -> Any:
        weights = [1 / (rank + 1) ** exponent for rank in range(len(items))]
        return self.rng.choices(items, weights=weights, k=1)[0]

    def patient(self) -> str:
        token = f"syn-participant-{self.next_patient:07d}"
        self.next_patient += 1
        return token

    def free_minute(self, facility_id: str, day: date) -> int:
        used = self.minutes[(facility_id, day.isoformat())]
        while True:
            minute = self.rng.randrange(0, 600)
            if minute not in used:
                used.add(minute)
                return minute

    def claim(self, facility: dict[str, Any], day: date, service: str, label: str, *, patient: str | None = None,
              entry: dict[str, Any] | None = None, diagnosis: str | None = None, procedure: str | None = None,
              evidence: tuple[str, ...] | None = None, units: int = 1) -> dict[str, Any]:
        entry = entry or self.zipf(self.catalog[service])
        diagnosis = diagnosis or self.zipf(entry["diagnoses"], 1.4)
        rule = SERVICES[service][2]
        evidence_types = list(rule) if evidence is None and rule else list(evidence or [])
        case_id = f"syn-claim-{self.next_claim:07d}"
        self.next_claim += 1
        stamp = datetime(day.year, day.month, day.day, 7, 0) + timedelta(minutes=self.free_minute(facility["facility_id"], day))
        record = {
            "claim_id": case_id, "case_id": case_id, "facility_id": facility["facility_id"],
            "participant_token": patient or self.patient(), "service_date": day.isoformat(),
            "province_code": facility["province_code"], "municipality_code": facility["municipality_code"],
            "facility_ownership": facility["facility_ownership"], "facility_type": facility["facility_type"],
            "facility_class": facility["facility_class"], "admission_diagnosis": diagnosis, "primary_diagnosis": diagnosis,
            "claim_group": entry["claim_group"], "procedure_code": procedure or self.zipf(entry["procedures"], 1.6),
            "billed_amount": entry["billed_amount"], "service_type": service, "service_units": units,
            "facility_daily_capacity": facility["capacity"],
            "supporting_evidence_required": list(rule or []), "supporting_evidence_types": evidence_types,
            "supporting_evidence_present": bool(evidence_types) or not rule,
            "service_timestamp": stamp.isoformat(timespec="minutes"), "supporting_evidence_recording_status": "recorded",
        }
        self.records.append(record)
        self.labels[case_id] = label
        return record

    def honest_month(self, claims: int) -> None:
        """Ordinary care; about a third of claims come from patients returning to the same hospital a week or more later."""
        services = list(SERVICES)
        shares = [SERVICES[s][0] for s in services]
        weights = [f["weight"] for f in self.facilities]
        made = 0
        while made < claims:
            facility = self.rng.choices(self.facilities, weights=weights, k=1)[0]
            service = self.rng.choices(services, weights=shares, k=1)[0]
            if self.rng.random() < 0.15 and service in ("outpatient", "physiotherapy", "laboratory"):
                patient, visits = self.patient(), self.rng.randint(2, 4)
                day = self.rng.randrange(DAYS - 7 * (visits - 1))
                for visit in range(min(visits, claims - made)):
                    self.claim(facility, START + timedelta(days=day + visit * self.rng.randint(7, 9)), service, "honest", patient=patient)
                    made += 1
            else:
                self.claim(facility, START + timedelta(days=self.rng.randrange(DAYS)), service, "honest")
                made += 1

    def honest_lookalikes(self, facility: dict[str, Any]) -> None:
        """Routine physiotherapy (one common package for many patients) and weekly therapy series."""
        package = self.catalog["physiotherapy"][0]
        diagnosis, procedure = package["diagnoses"][0], package["procedures"][0]
        for day in range(25):
            for _ in range(8):
                self.claim(facility, START + timedelta(days=day), "physiotherapy", "honest_routine_high_volume",
                           entry=package, diagnosis=diagnosis, procedure=procedure)
        for series in range(20):
            patient = self.patient()
            for week in range(4):
                self.claim(facility, START + timedelta(days=series % 7 + 7 * week), "physiotherapy", "honest_scheduled_therapy",
                           patient=patient, entry=package, diagnosis=diagnosis, procedure=procedure)

    def phantom_physiotherapy(self, facility: dict[str, Any], days: int, per_day: int, without_log: float) -> None:
        """Physiotherapy billed above capacity; most claims lack the therapy session log."""
        for day in range(days):
            for _ in range(per_day):
                missing = self.rng.random() < without_log
                self.claim(facility, START + timedelta(days=day), "physiotherapy", "phantom_physiotherapy",
                           evidence=("clinical_note",) if missing else None)

    def cloning(self, facility: dict[str, Any], groups: int, size: int) -> None:
        """One template claim copied to many patients on the same day."""
        for group in range(groups):
            entry = self.rng.choice(self.catalog["inpatient"][5:])
            diagnosis, procedure = self.rng.choice(entry["diagnoses"]), self.rng.choice(entry["procedures"])
            day = START + timedelta(days=self.rng.randrange(DAYS))
            for _ in range(size):
                self.claim(facility, day, "inpatient", "cloning", entry=entry, diagnosis=diagnosis, procedure=procedure)

    def repeat_billing(self, facility: dict[str, Any], count: int) -> None:
        """A claim billed twice: same patient, day, codes and amount under a new claim number."""
        for _ in range(count):
            original = self.claim(facility, START + timedelta(days=self.rng.randrange(DAYS)), "outpatient", "repeat_billing")
            day = date.fromisoformat(original["service_date"])
            self.claim(facility, day, "outpatient", "repeat_billing", patient=original["participant_token"],
                       entry={"claim_group": original["claim_group"], "billed_amount": original["billed_amount"],
                              "procedures": [original["procedure_code"]], "diagnoses": [original["primary_diagnosis"]]},
                       diagnosis=original["primary_diagnosis"], procedure=original["procedure_code"])

    def action_without_support(self, facility: dict[str, Any], count: int) -> None:
        """Procedures billed without the procedure order that should accompany them."""
        for _ in range(count):
            self.claim(facility, START + timedelta(days=self.rng.randrange(DAYS)), "synthetic_supported_action",
                       "action_without_support", evidence=("clinical_note",))

    def finish(self) -> list[dict[str, Any]]:
        daily = Counter((r["facility_id"], r["service_date"]) for r in self.records)
        for record in self.records:
            record["facility_daily_claim_count"] = daily[(record["facility_id"], record["service_date"])]
        self.rng.shuffle(self.records)
        return self.records


def build(name: str) -> World:
    if name == "demo-1-faskes-jujur":
        world = World(seed=101, facility_count=20)
        world.honest_month(9_500)
        world.honest_lookalikes(world.facilities[0])
    elif name == "demo-2-kasus-kpk":
        world = World(seed=202, facility_count=25)
        world.honest_month(11_200)
        world.honest_lookalikes(world.facilities[0])
        bad = world.facilities[10]  # an unremarkable class C hospital
        world.phantom_physiotherapy(bad, days=10, per_day=48, without_log=0.75)  # billed above daily capacity
        world.cloning(bad, groups=3, size=12)
        world.repeat_billing(bad, count=15)
    elif name == "demo-3-operasional":
        world = World(seed=303, facility_count=50)
        world.honest_month(23_600)
        world.honest_lookalikes(world.facilities[0])
        world.honest_lookalikes(world.facilities[1])
        world.phantom_physiotherapy(world.facilities[12], days=10, per_day=14, without_log=0.7)
        world.phantom_physiotherapy(world.facilities[33], days=6, per_day=12, without_log=0.6)
        world.cloning(world.facilities[18], groups=6, size=10)
        world.cloning(world.facilities[41], groups=4, size=8)
        world.repeat_billing(world.facilities[25], count=60)
        world.repeat_billing(world.facilities[7], count=40)
        world.action_without_support(world.facilities[29], count=120)
        world.action_without_support(world.facilities[46], count=60)
    else:
        raise ValueError(name)
    world.finish()
    return world


DEMOS = ("demo-1-faskes-jujur", "demo-2-kasus-kpk", "demo-3-operasional")


def check(world: World) -> dict[str, Any]:
    """Run the import path and the production pipeline, then join the answer key (aggregate story numbers)."""
    from app.analytics.action_policy import get_action_policy_config
    from app.data_sources.providers import SyntheticBatchProvider
    from app.data_sources.synthetic_csv import SYNTHETIC_CSV_MAPPING_VERSION, SYNTHETIC_CSV_SCHEMA_VERSION, parse_synthetic_csv
    from app.services.provider_orchestrator import execute_provider_snapshot

    records, _summary = parse_synthetic_csv(export_synthetic_csv(world.records))
    batch = {"source_type": "synthetic_csv", "schema_version": SYNTHETIC_CSV_SCHEMA_VERSION, "mapping_version": SYNTHETIC_CSV_MAPPING_VERSION,
             "status": "ready", "batch_version": 1, "content_checksum": "0" * 64}
    _, snapshot = execute_provider_snapshot(SyntheticBatchProvider(batch=batch, normalized_records=records), get_action_policy_config())
    lane_of = {case_id: item["lane"] for case_id, item in snapshot["action_policy"]["cases"].items()}
    by_label: dict[str, Counter[str]] = defaultdict(Counter)
    for case_id, label in world.labels.items():
        by_label[label][lane_of.get(case_id, "not_flagged")] += 1
    groups = snapshot["facility_groups"]["groups"]
    return {
        "claims": len(records), "lanes": snapshot["action_policy"]["lane_counts"],
        "by_label": {label: dict(counts) for label, counts in sorted(by_label.items())},
        "top_groups": [{"rank": g["rank"], "title": g["title"], "region": g["region"], "level": g["level"],
                        "lane_counts": g["lane_counts"]} for g in groups[:3]],
        "exposure": {k: snapshot["facility_groups"]["exposure"][k] for k in ("billed_total", "billed_high_or_medium")},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="run the pipeline and print the story numbers")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name in DEMOS:
        world = build(name)
        (args.out / f"{name}.csv").write_bytes(export_synthetic_csv(world.records))
        key = {"dataset": f"{name}.csv", "claims": len(world.records), "label_counts": dict(Counter(world.labels.values())),
               "labels": world.labels, "note": "Kunci jawaban sintetis; jangan diunggah ke sistem."}
        (args.out / f"{name}.answers.json").write_text(json.dumps(key, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        line = {"dataset": name, "claims": len(world.records), "labels": key["label_counts"]}
        if args.check:
            line["check"] = check(world)
        print(json.dumps(line, ensure_ascii=False, indent=1))
    assert set(CSV_COLUMNS) >= {"claim_id", "case_id"}


if __name__ == "__main__":
    main()
