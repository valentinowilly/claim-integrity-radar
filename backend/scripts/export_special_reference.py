"""Write the INA-CBG x special top-up code reference next to the ML artifact (aggregate counts only).

Counts how often each special code (FKL33 sub-acute, FKL35 procedure, FKL38 prosthesis, FKL41 investigation,
FKL44 drug) is billed with each INA-CBG (FKL19) in the FKRTL file, excluding the configured analysis window
(BPJS_FKRTL_DATE_FROM/TO) so analysed claims are not their own reference. Pairs and codes seen fewer than
``MIN_COUNT`` times are not stored (the same rule as the model's aggregate tables). Only these code columns
and the admission date are read. Writes ``special_reference.json`` in the model directory (local, not committed).

Usage: python -m scripts.export_special_reference   (reads BPJS_FKRTL_SAMPLE_PATH)
"""

from __future__ import annotations

from collections import Counter
from datetime import date
import json
import os
from pathlib import Path

import pandas as pd

from app.analytics.claim_detail_rules import SEP
from app.analytics.ml_model import DEFAULT_MODEL_DIR, MODEL_DIR_VARIABLE, SPECIAL_REFERENCE_FILE
from app.data_sources.bpjs_fkrtl_adapter import SPECIAL_CODE_COLUMNS, _clean
from app.data_sources.fkrtl_local_source import DATE_FROM_VARIABLE, DATE_TO_VARIABLE, PATH_VARIABLE

MIN_COUNT = 5


def main() -> int:
    source = os.environ.get(PATH_VARIABLE, "").strip()
    if not source or not Path(source).is_file():
        print(f"Set {PATH_VARIABLE} ke file .dta FKRTL lokal.")
        return 1
    excluded = None
    if os.environ.get(DATE_FROM_VARIABLE) and os.environ.get(DATE_TO_VARIABLE):
        excluded = (pd.Timestamp(date.fromisoformat(os.environ[DATE_FROM_VARIABLE])),
                    pd.Timestamp(date.fromisoformat(os.environ[DATE_TO_VARIABLE])))
    pairs: Counter[str] = Counter()
    codes: Counter[str] = Counter()
    claims = 0
    with pd.read_stata(source, iterator=True, chunksize=200_000, columns=["FKL03", "FKL19", *SPECIAL_CODE_COLUMNS],
                       convert_categoricals=False) as reader:
        for frame in reader:
            if excluded is not None:
                admitted = pd.to_datetime(frame["FKL03"], errors="coerce").dt.normalize()
                frame = frame[~((admitted >= excluded[0]) & (admitted <= excluded[1]))]
            claims += len(frame)
            for column in SPECIAL_CODE_COLUMNS:
                for group, code in zip(map(_clean, frame["FKL19"]), map(_clean, frame[column])):
                    if group and code:
                        pairs[f"{group}{SEP}{code}"] += 1
                        codes[code] += 1
    reference = {
        "claims": claims,
        "excluded_window": [day.date().isoformat() for day in excluded] if excluded else None,
        "min_count": MIN_COUNT,
        "pairs": {key: count for key, count in sorted(pairs.items()) if count >= MIN_COUNT},
        "codes": {key: count for key, count in sorted(codes.items()) if count >= MIN_COUNT},
    }
    target = Path(os.environ.get(MODEL_DIR_VARIABLE) or DEFAULT_MODEL_DIR) / SPECIAL_REFERENCE_FILE
    target.write_text(json.dumps(reference, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    print("Acuan tambahan khusus tersimpan:", {"klaim_acuan": claims, "pasangan": len(reference["pairs"]),
                                               "kode": len(reference["codes"])})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
