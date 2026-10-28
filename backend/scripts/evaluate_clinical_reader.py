"""Measure the stage 2 note reading (language model and fallback) on labelled demo claims (example data only).

Claims are drawn from the demo-3 world: honest inpatient claims and the fraud modes whose trace is in the
note (upcoding keeps a mild note under a severity III INA-CBG, a prolonged stay keeps the original stay,
a split readmission says it continues an earlier admission). Rule findings and the AI score are left out,
so only the reading of the note itself is measured. Cloned notes are not included: one note on its own
looks normal; copies are found by comparing notes (note_similarity), not by reading one.

The notes were written by our own generator, so the contradictions are plainer than in real records and
the fallback rules know its phrasing; the numbers describe this synthetic set only.

Usage: python -m scripts.evaluate_clinical_reader [--per-label 8] [--output report.json]
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from app.services import clinical_ai
from scripts.make_bpjs_demo_datasets import build, case_reference

LABELS = ("honest", "upcoding", "prolonged_stay", "readmission_split")
EXPECTED_FLAG = {"honest": False, "upcoding": True, "prolonged_stay": True, "readmission_split": True}


def _claim(row: dict[str, str]) -> dict:
    stay = (date.fromisoformat(row["FKL04"]) - date.fromisoformat(row["FKL03"])).days
    return {"admission_diagnosis": row["FKL16"], "primary_diagnosis": row["FKL18"], "claim_group": row["FKL19"],
            "procedure_code": row["FKL30"] or None, "care_class": row["FKL13"], "service_date": row["FKL03"],
            "discharge_date": row["FKL04"], "stay_days": stay, "clinical_note": row["CATATAN_KLINIS"],
            "findings": [], "ai_score": None, "ai_factors": []}


def sample(per_label: int, seed: int = 7) -> list[tuple[str, dict]]:
    world = build("demo-3-operasional")
    by_label: dict[str, list[dict]] = defaultdict(list)
    for row in world.rows:
        if row["FKL03"] == row["FKL04"]:
            continue  # inpatient claims only: the traces are about severity and stay
        label = world.labels.get(case_reference(row), "honest")
        if label in LABELS:
            by_label[label].append(row)
    rng = random.Random(seed)
    # Honest claims: half severity II/III so a high severity alone is not mistaken for a contradiction.
    honest = by_label["honest"]
    severe = [row for row in honest if row["FKL19"].endswith(("-II", "-III"))]
    mild = [row for row in honest if not row["FKL19"].endswith(("-II", "-III"))]
    picked = {"honest": rng.sample(severe, per_label // 2) + rng.sample(mild, per_label - per_label // 2)}
    for label in LABELS[1:]:
        picked[label] = rng.sample(by_label[label], min(per_label, len(by_label[label])))
    return [(label, _claim(row)) for label in LABELS for row in picked[label]]


def evaluate(per_label: int, case_set: str = "demo") -> dict:
    if case_set == "independent":
        from scripts.clinical_reader_cases import claims
        items = claims()
    else:
        items = sample(per_label)
    report: dict = {"case_set": case_set, "model": clinical_ai.model_name(), "provider": clinical_ai.provider(),
                    "model_available": clinical_ai.configured(), "claims": len(items), "engines": {}}
    for engine in ("llm", "fallback"):
        if engine == "llm" and not report["model_available"]:
            continue
        verdicts: dict[str, Counter] = defaultdict(Counter)
        seconds, failures = [], Counter()
        for label, claim in items:
            started = time.perf_counter()
            if engine == "llm":
                try:
                    verdict = clinical_ai.analyse(claim)[0].verdict
                except clinical_ai.ClinicalAiError as exc:
                    failures[exc.code] += 1
                    continue
            else:
                verdict = clinical_ai.fallback_reading(claim).verdict
            seconds.append(time.perf_counter() - started)
            verdicts[label][verdict] += 1
        flagged = {label: sum(count for verdict, count in counts.items() if verdict != "sesuai")
                   for label, counts in verdicts.items()}
        answered = {label: sum(counts.values()) for label, counts in verdicts.items()}
        report["engines"][engine] = {
            "verdicts": {label: dict(counts) for label, counts in verdicts.items()},
            "fraud_flagged": sum(flagged.get(label, 0) for label in LABELS[1:]),
            "fraud_answered": sum(answered.get(label, 0) for label in LABELS[1:]),
            "honest_flagged": flagged.get("honest", 0), "honest_answered": answered.get("honest", 0),
            "seconds_mean": round(sum(seconds) / len(seconds), 2) if seconds else None,
            "seconds_max": round(max(seconds), 2) if seconds else None,
            "failures": dict(failures),
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-label", type=int, default=8)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--set", dest="case_set", choices=("demo", "independent"), default="demo",
                        help="demo = claims of the demo-3 world; independent = hand-written notes (clinical_reader_cases)")
    args = parser.parse_args()
    report = evaluate(args.per_label, args.case_set)
    text = json.dumps(report, indent=1, ensure_ascii=False)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
