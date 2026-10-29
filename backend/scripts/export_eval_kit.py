"""Export the inputs of the Healthkathon evaluation kit (workshop 3, github.com/Luche/healthkathon-eval-kit).

The benchmark is the demo-3 world (BPJS column format, synthetic) plus one fraud type no rule was written for
(``procedure_inflation``, held out). Every file names claims only by their case reference.

    scores_radar.csv     entity_id, group_id, score, kelas, provinsi: the queue order (risk lane, then AI score)
    scores_aturan.csv    the same claims ranked by rule findings only (lane without the AI signal, then rule score)
    scores_ai.csv        the same claims ranked by the AI score only
    scores_placebo.csv   the radar order on a fraud-free version of the same world (placebo test)
    truth.csv            entity_id, label, modus, excess_rupiah (overpayment where the data can price it)
    features.csv         entity_id plus the claim facts the checks and the AI read (leakage scan)
    conditions.json      the audit capacity assumption and the test conditions

Usage: python -m scripts.export_eval_kit [--out ../outputs/eval-kit]
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from app.analytics.action_policy import EXPLORATORY_INDICATORS, get_action_policy_config
from app.analytics.ml_model import score_records
from app.data_sources.bpjs_csv import BPJS_CSV_MAPPING_VERSION, BPJS_CSV_SCHEMA_VERSION, parse_bpjs_csv
from app.data_sources.providers import SyntheticBatchProvider
from app.services.provider_orchestrator import execute_provider_snapshot
from scripts.make_bpjs_demo_datasets import CBG, SPECIAL_COLUMN, World, build, case_reference, to_csv

# Audit capacity (an assumption, stated as the kit asks): verifiers x claims per verifier per day x working days.
VERIFIERS, CLAIMS_PER_DAY, WORKING_DAYS = 2, 20, 22
LANE_RANK = {"red": 2.0, "yellow": 1.0}
# Fraud types whose whole claim is an extra payment (the visit was billed again, copied, split or never given).
WHOLE_CLAIM = {"repeat_billing", "cloning", "phantom_physiotherapy", "readmission_split"}
SEVERITY = {"0": 0, "I": 1, "II": 2, "III": 3}


def _analyse(world: World) -> tuple[dict[str, Any], dict[str, float]]:
    """The same pipeline as an upload, plus the AI score of every claim (the stored result keeps the top 200)."""
    records, _summary = parse_bpjs_csv(to_csv(world.rows), max_rows=200_000)
    batch = {"source_type": "synthetic_csv", "schema_version": BPJS_CSV_SCHEMA_VERSION, "mapping_version": BPJS_CSV_MAPPING_VERSION,
             "status": "ready", "batch_version": 1, "content_checksum": "0" * 64}
    _, snapshot = execute_provider_snapshot(SyntheticBatchProvider(batch=batch, normalized_records=records), get_action_policy_config())
    _summary_ai, per_case = score_records(records)
    ai = {case_id: float(item.get("reference_percentile", item.get("anomaly_percentile", 0.0)) or 0.0)
          for case_id, item in per_case.items()}
    return snapshot, ai


def _scores(world: World, snapshot: dict[str, Any], ai: dict[str, float]) -> dict[str, list[dict[str, Any]]]:
    lanes = {case_id: item.get("lane") for case_id, item in snapshot["action_policy"]["cases"].items()}
    cases = snapshot["cases"]
    variants: dict[str, list[dict[str, Any]]] = {"radar": [], "aturan": [], "ai": []}
    for row in world.rows:
        case_id = case_reference(row)
        base = {"entity_id": case_id, "group_id": row["FKL06"], "kelas": f"kelas_{row['FKL09']}", "provinsi": f"prov_{row['FKL05']}"}
        ai_score = ai.get(case_id, 0.0)
        case = cases.get(case_id) or {}
        specific = [code for code in case.get("indicators") or [] if code not in EXPLORATORY_INDICATORS]
        rule_lane = 2.0 if len(specific) >= 2 else 1.0 if specific else 0.0
        rule_score = float(case.get("risk_score") or 0.0)
        variants["radar"].append(base | {"score": round(LANE_RANK.get(lanes.get(case_id) or "", 0.0) + 0.99 * ai_score, 6)})
        variants["aturan"].append(base | {"score": round(rule_lane + 0.99 * rule_score, 6)})
        variants["ai"].append(base | {"score": round(ai_score, 6)})
    return variants


def _truth(world: World) -> list[dict[str, Any]]:
    rows = []
    for row in world.rows:
        label = world.labels.get(case_reference(row), "")
        fraud = bool(label) and not label.startswith("honest")
        excess = 0
        if fraud and "_orig_tariff" in row:
            excess = int(row["FKL47"]) - int(row["_orig_tariff"])  # upcoding: the higher severity's tariff
        elif fraud and label in WHOLE_CLAIM:
            excess = int(row["FKL47"])
        rows.append({"entity_id": case_reference(row), "label": int(fraud), "modus": label if fraud else "jujur",
                     "excess_rupiah": excess})
    return rows


def _features(world: World) -> list[dict[str, Any]]:
    rows = []
    for row in world.rows:
        match = CBG.match(row["FKL19"])
        stay = (date.fromisoformat(row["FKL04"]) - date.fromisoformat(row["FKL03"])).days
        required = [item for item in row.get("BUKTI_WAJIB", "").split(";") if item]
        recorded = [item for item in row.get("BUKTI_TERCATAT", "").split(";") if item and item != "-"]
        time = row.get("JAM_LAYANAN") or ""
        rows.append({
            "entity_id": case_reference(row), "lama_rawat": stay, "rawat_inap": int(stay > 0),
            "keparahan": SEVERITY.get(match.group(4), 0) if match else 0, "kelas_rawat": row["FKL13"],
            "kelas_faskes": row["FKL09"], "jumlah_diagnosis_sekunder": len([code for code in row["FKL24"].split(";") if code]),
            "ada_tambahan_khusus": int(any(row[column] for column in SPECIAL_COLUMN.values())),
            "tarif_tagihan": int(row["FKL47"]), "diagnosis_masuk_beda": int(row["FKL16"] != row["FKL18"]),
            "ada_prosedur": int(bool(row["FKL30"])), "jumlah_layanan": int(row.get("JUMLAH_LAYANAN") or 0),
            "kapasitas_harian": int(row.get("KAPASITAS_HARIAN") or 0),
            "bukti_kurang": len(set(required) - set(recorded)) if row.get("STATUS_BUKTI") == "tercatat" else 0,
            "menit_layanan": int(time[:2]) * 60 + int(time[3:5]) if time else -1,
        })
    return rows


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[2] / "outputs" / "eval-kit")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    world = build("demo-3-operasional", held_out=True)
    snapshot, ai = _analyse(world)
    for name, rows in _scores(world, snapshot, ai).items():
        _write(args.out / f"scores_{name}.csv", rows)
    truth = _truth(world)
    _write(args.out / "truth.csv", truth)
    _write(args.out / "features.csv", _features(world))

    clean = build("demo-3-operasional", fraud=False)
    clean_snapshot, clean_ai = _analyse(clean)
    _write(args.out / "scores_placebo.csv", _scores(clean, clean_snapshot, clean_ai)["radar"])

    capacity = VERIFIERS * CLAIMS_PER_DAY * WORKING_DAYS
    fraud = sum(row["label"] for row in truth)
    conditions = {
        "capacity": capacity,
        "capacity_assumption": f"{VERIFIERS} verifikator x {CLAIMS_PER_DAY} klaim per hari x {WORKING_DAYS} hari kerja (asumsi tim, bukan angka BPJS)",
        "claims": len(truth), "fraud_claims": fraud, "fraud_rate": round(fraud / len(truth), 4),
        "placebo_claims": len(clean.rows), "held_out_modus": "procedure_inflation",
    }
    (args.out / "conditions.json").write_text(json.dumps(conditions, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(conditions, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
