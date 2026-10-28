"""Copy the FKRTL facility-category code names (Stata value labels) next to the ML artifact.

Reads only the file's label dictionary (province, municipality, ownership, type and class
names); no data row is read. Uploaded files in the BPJS column format carry the same codes,
and the app shows these names for them. Writes ``category_labels.json`` in the model
directory, which is local and not committed.

Usage: python -m scripts.export_category_labels   (reads BPJS_FKRTL_SAMPLE_PATH)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.analytics.ml_model import DEFAULT_MODEL_DIR, MODEL_DIR_VARIABLE
from app.data_sources.fkrtl_local_source import PATH_VARIABLE
from scripts.fkrtl_dta_provider import _category_labels

LABELS_FILE = "category_labels.json"


def main() -> int:
    source = os.environ.get(PATH_VARIABLE, "").strip()
    if not source or not Path(source).is_file():
        print(f"Set {PATH_VARIABLE} ke file .dta FKRTL lokal.")
        return 1
    labels = _category_labels(source)
    if not any(labels.values()):
        print("File tidak memuat label kategori.")
        return 1
    target = Path(os.environ.get(MODEL_DIR_VARIABLE) or DEFAULT_MODEL_DIR) / LABELS_FILE
    target.write_text(json.dumps(labels, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    print("Label kategori tersimpan:", {field: len(names) for field, names in labels.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
