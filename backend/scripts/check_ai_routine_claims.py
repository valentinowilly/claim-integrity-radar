"""Real-data sanity check of the AI, aggregate only: are routine claims (most common INA-CBG codes) scored as unusual?

Reads the configured local FKRTL window (same settings as the backend) and writes counts and shares only;
no row, code, identifier or amount is written.

Usage: python -m scripts.check_ai_routine_claims --output ../outputs/synthetic_evaluations/ai-routine-check.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.analytics.ml_model import load_artifact, score_records
from app.data_sources.fkrtl_local_source import configured_date_window, load_fkrtl_local_source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = list(load_fkrtl_local_source().dataset.records)
    summary, results = score_records(records, load_artifact())
    counts = Counter(record.get("claim_group") for record in records)
    top10 = {code for code, _ in counts.most_common(10)}
    rare = {code for code, count in counts.items() if count <= 5}

    def share_high(selected: list[str]) -> dict[str, float | int | None]:
        scored = [results[case_id]["reference_percentile"] for case_id in selected
                  if results.get(case_id, {}).get("inference_status") == "scored"]
        return {"claims": len(selected), "share_ai_high": round(sum(p >= 0.95 for p in scored) / len(scored), 4) if scored else None}

    window = configured_date_window()
    report = {
        "report": "cir-ai-routine-check-v1",
        "data_source": "bpjs_sample_aggregate",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window": [window[0].isoformat(), window[1].isoformat()],
        "model_version": summary.get("model_version"),
        "claims": len(records),
        "common_codes_share_of_claims": round(sum(counts[code] for code in top10) / len(records), 4) if records else None,
        "common_codes": share_high([r["case_id"] for r in records if r.get("claim_group") in top10]),
        "rare_codes": share_high([r["case_id"] for r in records if r.get("claim_group") in rare]),
        "all_claims": share_high([r["case_id"] for r in records]),
        "definition": "Kode umum = 10 kode INA-CBG paling sering; kode langka = muncul ≤ 5 kali; anomali tinggi = persentil AI ≥ 95%.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
