"""Example files a verifier can download to try the upload: synthetic claims only, never the answer keys.

The files come from the repository's ``demo-data`` folder (or ``CIR_SAMPLE_DIR``). Packages are built as ZIP files
on request and kept in memory for reuse; PDFs are stored without recompression (they are already compressed).
"""

from __future__ import annotations

import io
import json
import os
import threading
import zipfile
from pathlib import Path
from typing import Any

SAMPLE_DIR_VARIABLE = "CIR_SAMPLE_DIR"
PACKAGE = "demo-4-multisumber"
SAMPLES: dict[str, dict[str, str]] = {
    "paket-ringkas": {
        "label": "Paket contoh ringkas",
        "description": "Data E-Klaim (CSV), data RME (JSON FHIR), dan 24 berkas PDF (9 hasil pindai): 5 klaim yang "
                       "hanya ada sebagai PDF dan 3 berkas yang sengaja berbeda dari data klaim. Diproses sekitar 1 menit.",
        "file_name": "contoh-paket-klaim-ringkas.zip",
    },
    "paket-lengkap": {
        "label": "Paket contoh lengkap",
        "description": "Data E-Klaim (CSV), data RME (JSON FHIR), dan 240 berkas PDF (81 hasil pindai). Diproses sekitar 5 menit.",
        "file_name": "contoh-paket-klaim-lengkap.zip",
    },
    "klaim-csv": {
        "label": "Data klaim CSV saja",
        "description": "29.628 klaim sebulan dari 40 rumah sakit, format kolom klaim FKRTL.",
        "file_name": "contoh-klaim-september.csv",
    },
}
_cache: dict[str, bytes] = {}
_lock = threading.Lock()


class SampleUnavailable(LookupError):
    pass


def sample_directory() -> Path:
    configured = os.environ.get(SAMPLE_DIR_VARIABLE, "").strip()
    return Path(configured).expanduser() if configured else Path(__file__).resolve().parents[3] / "demo-data"


def _package_files(name: str) -> list[tuple[str, Path]]:
    folder = sample_directory() / PACKAGE
    answers = json.loads((folder / f"{PACKAGE}.answers.json").read_text(encoding="utf-8"))
    files = [("klaim-eklaim.csv", folder / "klaim-eklaim.csv"), ("rme-satusehat.json", folder / "rme-satusehat.json")]
    documents = answers["documents"]
    if name == "paket-ringkas":
        keep = set(answers["pdf_only"]) | set(answers["mismatches"])
        chosen = sorted(file for file, item in documents.items() if item["visit"] in keep)
    else:
        chosen = sorted(documents)
    return files + [(f"berkas/{file}", folder / "berkas" / file) for file in chosen]


def available() -> list[dict[str, Any]]:
    folder = sample_directory()
    ready = {"klaim-csv": (folder / "demo-3-operasional.csv").is_file(),
             "paket-ringkas": (folder / PACKAGE / f"{PACKAGE}.answers.json").is_file()}
    ready["paket-lengkap"] = ready["paket-ringkas"]
    return [{"sample_id": key, **spec} for key, spec in SAMPLES.items() if ready[key]]


def content(sample_id: str) -> tuple[bytes, str, str]:
    """File bytes, download name and media type of one sample."""
    if sample_id not in SAMPLES or sample_id not in {item["sample_id"] for item in available()}:
        raise SampleUnavailable(sample_id)
    spec = SAMPLES[sample_id]
    if sample_id == "klaim-csv":
        return (sample_directory() / "demo-3-operasional.csv").read_bytes(), spec["file_name"], "text/csv"
    with _lock:
        if sample_id not in _cache:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                for arcname, path in _package_files(sample_id):
                    method = zipfile.ZIP_STORED if path.suffix == ".pdf" else zipfile.ZIP_DEFLATED
                    archive.write(path, arcname, compress_type=method)
            _cache[sample_id] = buffer.getvalue()
        return _cache[sample_id], spec["file_name"], "application/zip"
