"""Reading accuracy on the demo-4 PDFs (synthetic): document type and every printed value, digital vs scanned.

    python -m scripts.evaluate_document_reader [--model] [--limit N] [--out path.json]

Without ``--model`` only the form reader runs (no language model). With it, the configured model also reads
the free-text documents. Values are compared after the same normalisation the intake uses.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from app.intake.documents import FIELDS, _plain, read_document
from app.intake.pdf_reader import read_pdf
from app.services import llm

DEMO = Path(__file__).resolve().parents[2] / "demo-data" / "demo-4-multisumber"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="store_true", help="also use the configured language model")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    answers = json.loads((DEMO / "demo-4-multisumber.answers.json").read_text(encoding="utf-8"))["documents"]
    names = sorted(answers)[: args.limit or None]
    totals: dict[str, Counter] = defaultdict(Counter)
    misses: list[dict[str, str]] = []
    seconds = Counter()
    for name in names:
        truth = answers[name]
        kind = "scan" if truth["scanned"] else "digital"
        started = time.monotonic()
        reading = read_pdf((DEMO / "berkas" / name).read_bytes())
        result = read_document(reading, use_model=None if args.model else False)
        seconds[kind] += time.monotonic() - started
        totals[kind]["documents"] += 1
        totals[kind]["type_correct"] += result.doc_type == truth["doc_type"]
        for field, expected in truth["values"].items():
            got = result.value(field)
            # Free text counts as read when at least 97% of its characters match (OCR may miss a character).
            ok = got is not None and (_plain(got).replace(" ", "") == _plain(expected).replace(" ", "")
                                      if FIELDS[field].get("kind") != "text"
                                      else SequenceMatcher(None, _plain(got), _plain(expected), autojunk=False).ratio() >= 0.97)
            totals[kind]["fields"] += 1
            totals[kind]["fields_correct"] += ok
            totals[f"field:{field}"]["n"] += 1
            totals[f"field:{field}"]["ok"] += ok
            if not ok and len(misses) < 60:
                misses.append({"file": name, "field": field, "expected": expected[:60], "got": (got or "-")[:60]})
    report = {
        "documents": len(names), "model": llm.describe() if args.model else None,
        "by_kind": {kind: {"documents": totals[kind]["documents"],
                           "type_accuracy": round(totals[kind]["type_correct"] / max(1, totals[kind]["documents"]), 4),
                           "field_accuracy": round(totals[kind]["fields_correct"] / max(1, totals[kind]["fields"]), 4),
                           "fields": totals[kind]["fields"],
                           "seconds_per_document": round(seconds[kind] / max(1, totals[kind]["documents"]), 2)}
                    for kind in ("digital", "scan")},
        "by_field": {key[6:]: round(value["ok"] / value["n"], 4) for key, value in sorted(totals.items()) if key.startswith("field:")},
        "examples_of_misses": misses,
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
