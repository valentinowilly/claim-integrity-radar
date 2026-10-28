"""Write the names of diagnosis (ICD-10) and INA-CBG codes next to the ML artifact (a code dictionary only).

The FKRTL file carries a name next to each code (FKL16A admission diagnosis, FKL18A primary diagnosis,
FKL19A INA-CBG description). Only the code and name columns are read; a code is kept only when it occurs
at least ``MIN_COUNT`` times (the same rule as the model's aggregate tables), with its most frequent name.
No participant, visit, date or amount is read. Writes ``code_names.json`` in the model directory, which is
local and not committed. The app shows these names on claim pages and gives them to the note reader.

Usage: python -m scripts.export_code_names   (reads BPJS_FKRTL_SAMPLE_PATH)
"""

from __future__ import annotations

from collections import Counter, defaultdict
import json
import os
from pathlib import Path

import pandas as pd

from app.analytics.ml_model import CODE_NAMES_FILE, DEFAULT_MODEL_DIR, MODEL_DIR_VARIABLE
from app.data_sources.fkrtl_local_source import PATH_VARIABLE

MIN_COUNT = 5
PAIRS = {"diagnosis": (("FKL16", "FKL16A"), ("FKL18", "FKL18A")), "claim_group": (("FKL19", "FKL19A"),)}
EMPTY = {"", "nan", "none", "-", "<na>"}


def _clean(value: object) -> str:
    text = str(value).strip()
    return "" if text.lower() in EMPTY else text


def main() -> int:
    source = os.environ.get(PATH_VARIABLE, "").strip()
    if not source or not Path(source).is_file():
        print(f"Set {PATH_VARIABLE} ke file .dta FKRTL lokal.")
        return 1
    columns = sorted({column for pairs in PAIRS.values() for pair in pairs for column in pair})
    counts: dict[str, dict[str, Counter]] = {kind: defaultdict(Counter) for kind in PAIRS}
    with pd.read_stata(source, iterator=True, chunksize=200_000, columns=columns, convert_categoricals=False) as reader:
        for chunk in reader:
            for kind, pairs in PAIRS.items():
                for code_column, name_column in pairs:
                    for code, name in zip(chunk[code_column].map(_clean), chunk[name_column].map(_clean)):
                        if code and name:
                            counts[kind][code][name[:120]] += 1
    names = {kind: {code: by_name.most_common(1)[0][0] for code, by_name in sorted(codes.items())
                    if sum(by_name.values()) >= MIN_COUNT}
             for kind, codes in counts.items()}
    target = Path(os.environ.get(MODEL_DIR_VARIABLE) or DEFAULT_MODEL_DIR) / CODE_NAMES_FILE
    target.write_text(json.dumps(names, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    print("Nama kode tersimpan:", {kind: len(codes) for kind, codes in names.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
