"""Measure the current CIR pipeline (rule checks + AI + risk levels) on labelled synthetic data.

Aggregate-only and reproducible (fixed seed). Labels come from the synthetic generator and are
never passed to the pipeline; they are joined afterwards to count hits. Results describe the
synthetic scenarios only, not real-world fraud detection performance.

Usage: python -m scripts.evaluate_current_pipeline --claims 30000 --facilities 60 --output <file.json>
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from app.analytics.action_policy import EXPLORATORY_INDICATORS, evaluate_action_policy, get_action_policy_config
from app.data_sources.synthetic_benchmark_generator import SyntheticBenchmarkProfile, generate_synthetic_benchmark_dataset
from app.data_sources.synthetic_generator import SyntheticGeneratorConfig
from app.services.analytics import build_analytics_snapshot

LANES = ("red", "yellow", "green")


def add_honest_lookalikes(dataset) -> dict[str, list[str]]:
    """Honest claims that resemble fraud patterns (labelled honest), placed at one honest high-volume facility.

    A: routine physiotherapy with one package tariff for many different patients (10 a day, 20 days).
    B: scheduled therapy series, 20 patients with one session a week for 6 weeks (legitimate repeats).
    """
    honest = sorted(item["facility_id"] for item in dataset.ground_truth.facility_labels if not item["is_synthetic_anomaly_facility"])
    facility_id = honest[0]
    template = next(row for row in dataset.records if row.get("facility_id") == facility_id)
    for facility in dataset.facilities:
        if facility["facility_id"] == facility_id:
            facility["daily_capacity_units"] = max(int(facility["daily_capacity_units"]), 120)  # a large hospital
    start = date(2024, 9, 2)
    # Routine care uses the most common honest physiotherapy code combination, as it would in real data.
    labels = {label["case_id"]: label for label in dataset.ground_truth.claim_labels}
    codes = ("claim_group", "admission_diagnosis", "primary_diagnosis", "procedure_code", "billed_amount")
    common = Counter(tuple(row.get(field) for field in codes) for row in dataset.records
                     if row.get("service_type") == "physiotherapy" and not labels[row["case_id"]].get("is_synthetic_anomaly"))
    if not common:
        raise ValueError("Data sintetis tidak memiliki klaim fisioterapi jujur sebagai acuan kode")
    package = {"service_type": "physiotherapy", **dict(zip(codes, common.most_common(1)[0][0])),
               "service_units": 1, "facility_daily_capacity": 120,
               "supporting_evidence_required": ["clinical_note", "session_record"],
               "supporting_evidence_types": ["clinical_note", "session_record"],
               "supporting_evidence_present": True, "supporting_evidence_recording_status": "recorded"}
    groups: dict[str, list[str]] = {"routine_high_volume": [], "scheduled_therapy": []}

    def add(group: str, index: int, day: date, minute: int, patient: str) -> None:
        case_id = f"syn-honest-{group}-{index:04d}"
        stamp = datetime(day.year, day.month, day.day, 8, 0) + timedelta(minutes=minute)
        dataset.records.append({**template, **package, "claim_id": case_id, "case_id": case_id, "participant_token": patient,
                                "service_date": day.isoformat(), "service_timestamp": stamp.isoformat(timespec="minutes"),
                                "facility_daily_claim_count": 10})
        dataset.ground_truth.claim_labels.append({"case_id": case_id, "is_synthetic_anomaly": False, "primary_scenario": None})
        groups[group].append(case_id)

    for index in range(200):
        add("routine_high_volume", index, start + timedelta(days=index // 10), 37 * (index % 10) + index // 10, f"syn-honest-patient-a{index:04d}")
    for patient in range(20):
        for week in range(6):
            add("scheduled_therapy", patient * 6 + week, start + timedelta(days=7 * week + patient % 5), 20 * patient + 3, f"syn-honest-patient-b{patient:03d}")
    return groups


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _demo_inputs() -> dict[str, Any]:
    """The demo-3 world in the BPJS column format, analysed exactly as an uploaded file (trained AI included)."""
    from app.data_sources.bpjs_csv import BPJS_CSV_MAPPING_VERSION, BPJS_CSV_SCHEMA_VERSION, parse_bpjs_csv
    from app.data_sources.providers import SyntheticBatchProvider
    from app.services.provider_orchestrator import execute_provider_snapshot
    from scripts.make_bpjs_demo_datasets import build, case_reference, to_csv

    world = build("demo-3-operasional")
    records, _summary = parse_bpjs_csv(to_csv(world.rows), max_rows=200_000)
    batch = {"source_type": "synthetic_csv", "schema_version": BPJS_CSV_SCHEMA_VERSION, "mapping_version": BPJS_CSV_MAPPING_VERSION,
             "status": "ready", "batch_version": 1, "content_checksum": "0" * 64}
    _, snapshot = execute_provider_snapshot(SyntheticBatchProvider(batch=batch, normalized_records=records), get_action_policy_config())
    lookalike_names = {"honest_routine_high_volume": "routine_high_volume", "honest_scheduled_therapy": "scheduled_therapy"}
    facility_of = {case_reference(row): row["FKL06"] for row in world.rows}
    labels = {case_id: {"is_synthetic_anomaly": False, "primary_scenario": None} for case_id in facility_of}
    lookalikes: dict[str, list[str]] = defaultdict(list)
    for case_id, label in world.labels.items():
        if label in lookalike_names:
            lookalikes[lookalike_names[label]].append(case_id)
        elif not label.startswith("honest"):
            labels[case_id] = {"is_synthetic_anomaly": True, "primary_scenario": label}
    fraud_facilities = {facility_of[case_id] for case_id, label in labels.items() if label["is_synthetic_anomaly"]}
    return {"snapshot": snapshot, "policy": snapshot["action_policy"], "labels": labels, "lookalikes": dict(lookalikes),
            "control_ids": set(), "facility_of": facility_of, "fraud_facilities": fraud_facilities,
            "generator_version": "demo-3-operasional (format kolom BPJS, AI terlatih)", "facilities": len(world.hospitals)}


def _v4_inputs(claims: int, facilities: int, seed: int) -> dict[str, Any]:
    """The labelled v4 benchmark generator (random codes) plus honest lookalikes."""
    config = SyntheticGeneratorConfig(seed=seed, claim_count=claims, facility_count=facilities, target_anomaly_rate=0.04)
    dataset = generate_synthetic_benchmark_dataset(config, SyntheticBenchmarkProfile())
    lookalikes = add_honest_lookalikes(dataset)
    snapshot = build_analytics_snapshot(records=dataset.records, facilities=dataset.facilities,
                                        data_source={"kind": "synthetic", "label": "synthetic_benchmark"})
    return {"snapshot": snapshot, "policy": evaluate_action_policy(snapshot, get_action_policy_config()),
            "labels": {label["case_id"]: label for label in dataset.ground_truth.claim_labels}, "lookalikes": lookalikes,
            "control_ids": {case_id for group in dataset.ground_truth.group_labels
                            if group.get("scenario_code") == "legitimate_repeat_control" for case_id in group["case_ids"]},
            "facility_of": {row["case_id"]: row.get("facility_id") for row in dataset.records},
            "fraud_facilities": {item["facility_id"] for item in dataset.ground_truth.facility_labels if item["is_synthetic_anomaly_facility"]},
            "generator_version": dataset.metadata.get("generator_version"), "facilities": facilities}


def evaluate(claims: int, facilities: int, seed: int, source: str = "demo") -> dict[str, Any]:
    started = perf_counter()
    inputs = _demo_inputs() if source == "demo" else _v4_inputs(claims, facilities, seed)
    snapshot, policy, labels, lookalikes = inputs["snapshot"], inputs["policy"], inputs["labels"], inputs["lookalikes"]
    control_ids, facility_of = inputs["control_ids"], inputs["facility_of"]
    flagged = snapshot["cases"]
    lane_of = {case_id: item["lane"] for case_id, item in policy["cases"].items()}
    # Claims the trained AI rates more unusual than the "risiko sedang" threshold of the reference data
    # (the "Temuan tambahan AI" list and the AI confirmation of rule findings).
    ai_min = get_action_policy_config().ml_yellow_min
    ai_flagged = {item["case_id"] for item in (snapshot.get("ml_anomaly") or {}).get("items", [])
                  if (item.get("reference_percentile") if item.get("reference_percentile") is not None
                      else item.get("anomaly_percentile", 0)) >= ai_min}
    honest_facilities = set(facility_of.values()) - inputs["fraud_facilities"]

    def rules_only(case_id: str) -> str | None:
        """The v3 lane without the AI signal: specific rule findings only."""
        if case_id not in flagged:
            return None
        specific = [code for code in flagged[case_id].get("indicators") or [] if code not in EXPLORATORY_INDICATORS]
        return "red" if len(specific) >= 2 else "yellow" if specific else "green"

    def tally(case_ids: list[str]) -> dict[str, Any]:
        lanes = Counter(lane_of.get(case_id, "not_flagged") for case_id in case_ids)
        rule_lanes = Counter(rules_only(case_id) for case_id in case_ids)
        detected = sum(case_id in flagged for case_id in case_ids)
        by_ai = sum(case_id in ai_flagged for case_id in case_ids)
        either = sum(case_id in flagged or case_id in ai_flagged for case_id in case_ids)
        return {
            "claims": len(case_ids),
            "detected_by_rules": detected, "detected_share": _share(detected, len(case_ids)),
            "flagged_by_ai": by_ai, "flagged_by_ai_share": _share(by_ai, len(case_ids)),
            "detected_any": either, "detected_any_share": _share(either, len(case_ids)),
            "high": lanes["red"], "medium": lanes["yellow"],
            "high_or_medium_share": _share(lanes["red"] + lanes["yellow"], len(case_ids)),
            "rules_only_high": rule_lanes["red"], "rules_only_medium": rule_lanes["yellow"],
        }

    by_scenario: dict[str, list[str]] = defaultdict(list)
    negatives: list[str] = []
    for case_id, label in labels.items():
        if label.get("is_synthetic_anomaly"):
            by_scenario[str(label.get("primary_scenario"))].append(case_id)
        else:
            negatives.append(case_id)
    positives = {case_id for ids in by_scenario.values() for case_id in ids}
    honest_claims = [case_id for case_id in negatives if facility_of.get(case_id) in honest_facilities]

    high = [case_id for case_id, lane in lane_of.items() if lane == "red"]
    high_medium = [case_id for case_id, lane in lane_of.items() if lane in ("red", "yellow")]
    base_rate = len(positives) / len(labels)
    high_precision = _share(sum(case_id in positives for case_id in high), len(high))
    high_medium_precision = _share(sum(case_id in positives for case_id in high_medium), len(high_medium))

    # Facility level: rank facilities by high-risk claims, then medium; compare the top fifth with the labels.
    per_facility: dict[str, Counter[str]] = defaultdict(Counter)
    for case_id, lane in lane_of.items():
        per_facility[facility_of.get(case_id)][lane] += 1
    ranked = sorted({facility_of[c] for c in labels}, key=lambda f: (-per_facility[f]["red"], -per_facility[f]["yellow"], f))
    top = ranked[: max(1, len(ranked) // 5)]
    positive_facilities = inputs["fraud_facilities"]

    # Method comparison (proposal slide "Hasil Eksperimen"): the same metrics for a random audit, a simple rule
    # and the Radar. K claims are reviewed first; "flagged" is what each method sends for review.
    k = 100
    negatives_set = set(negatives)

    def percentile(case_id: str) -> float:
        item = flagged.get(case_id, {}).get("ml_anomaly") or {}
        value = item.get("reference_percentile", item.get("anomaly_percentile"))
        return float(value) if isinstance(value, (int, float)) else 0.0

    radar_order = sorted(high_medium, key=lambda c: (lane_of[c] != "red", -percentile(c), c))
    simple = sorted(flagged)  # any one rule fired; no AI, no combination, no ordering (expected = set precision)

    def method(name: str, description: str, reviewed: list[str], first_k_precision: float | None) -> dict[str, Any]:
        caught = sum(case_id in positives for case_id in reviewed)
        honest_flagged = sum(case_id in negatives_set for case_id in reviewed)
        return {"name": name, "description": description, "reviewed_claims": len(reviewed),
                "precision_at_k": first_k_precision,
                "fraud_per_100": round(100 * first_k_precision, 1) if first_k_precision is not None else None,
                "recall": _share(caught, len(positives)),
                "honest_kept_green": _share(len(negatives_set) - honest_flagged, len(negatives_set)),
                "honest_flagged": _share(honest_flagged, len(negatives_set))}

    simple_precision = _share(sum(c in positives for c in simple), len(simple))
    random_volume = len(high_medium)
    comparison = {"k": k, "methods": [
        {"name": "Audit acak", "description": f"{random_volume} klaim dipilih acak (sama dengan beban kerja Radar).",
         "reviewed_claims": random_volume, "precision_at_k": round(base_rate, 4), "fraud_per_100": round(100 * base_rate, 1),
         "recall": _share(random_volume, len(labels)), "honest_kept_green": _share(len(labels) - random_volume, len(labels)),
         "honest_flagged": _share(random_volume, len(labels))},
        method("Aturan sederhana", "Klaim ditandai bila satu pemeriksaan aturan mana pun terpicu; tanpa AI dan tanpa urutan.",
               simple, simple_precision),
        method("Claim Integrity Radar", f"Risiko tinggi dan sedang; {k} klaim pertama diurutkan dari risiko tinggi lalu skor AI.",
               high_medium, _share(sum(c in positives for c in radar_order[:k]), min(k, len(radar_order)))),
    ]}

    return {
        "report": "cir-current-pipeline-synthetic-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_source": "synthetic_experiment_only",
        "configuration": {"claims": len(labels), "facilities": inputs["facilities"], "seed": seed if source != "demo" else 303,
                          "source": source, "generator_version": inputs["generator_version"],
                          "action_policy_version": policy["policy_version"]},
        "population": {"claims": len(labels), "fraud_claims": len(positives), "base_rate": round(base_rate, 4),
                       "facilities": len(ranked), "fraud_facilities": len(positive_facilities)},
        "scenarios": {name: tally(ids) for name, ids in sorted(by_scenario.items())},
        "honest_claims": tally(negatives),
        "honest_facility_claims": tally(honest_claims),
        "legitimate_repeat_control": tally(sorted(control_ids)),
        "honest_lookalikes": {name: tally(ids) for name, ids in lookalikes.items()},
        "workload": {"high": len(high), "high_or_medium": len(high_medium),
                     "high_or_medium_share_of_claims": _share(len(high_medium), len(labels))},
        "precision": {"high": high_precision, "high_or_medium": high_medium_precision,
                      "lift_high_vs_random": round(high_precision / base_rate, 2) if high_precision is not None else None},
        "method_comparison": comparison,
        "facility_ranking": {"top_fifth": len(top), "fraud_facilities_in_top_fifth": sum(f in positive_facilities for f in top),
                             "precision_top_fifth": _share(sum(f in positive_facilities for f in top), len(top)),
                             "fraud_facility_share": _share(len(positive_facilities), len(ranked))},
        "seconds": round(perf_counter() - started, 1),
        "limitations": [
            "Data sintetis dengan skenario yang sengaja disuntikkan; bukan kinerja pada data JKN asli.",
            "Label skenario hanya dipakai setelah analisis selesai untuk menghitung hasil.",
            "Data contoh berformat kolom data klaim BPJS; kode dan kombinasinya diambil dari tabel agregat model AI "
            "(kombinasi yang muncul minimal 5 kali di data latih), lalu dinilai AI yang dilatih dari data sampel BPJS.",
            "Kolom BPJS tidak memuat ID faskes, nilai klaim terverifikasi, kapasitas, jam layanan, dan dokumen pendukung; "
            "pemeriksaan yang membutuhkannya tidak berlaku, sehingga sebagian modus hanya dapat ditandai AI.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=int, default=30_000)
    parser.add_argument("--facilities", type=int, default=60)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", choices=("demo", "v4"), default="demo",
                        help="demo = dunia demo-3 dengan kode realistis (default); v4 = generator benchmark lama dengan kode acak")
    args = parser.parse_args()
    report = evaluate(args.claims, args.facilities, args.seed, args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("population", "scenarios", "honest_claims", "legitimate_repeat_control", "honest_lookalikes",
                                             "workload", "precision", "facility_ranking", "seconds")}, indent=1))


if __name__ == "__main__":
    main()
