"""Fill an empty demo installation with the synthetic example files, through the API like a user would.

Uploads demo-1, demo-2 and demo-3 (oldest first, so the overview compares analyses), analyses each, then
on the demo-3 analysis records a handful of review decisions (so review status and system accuracy show data)
and, when asked, AI readings of a few clinical notes (so a reading opens without waiting).

Synthetic data only: the files carry SYN participant numbers and the server must be a local demo instance.
The review decisions are examples for the demo; each note says so.

Usage (backend running on the demo database, see start-cir-demo.ps1 outside the repository):
    python -m scripts.seed_demo_database --username demo [--base-url http://127.0.0.1:8001] [--ai-readings 3]
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

DEMO_DIR = Path(__file__).resolve().parents[2] / "demo-data"
FILES = ("demo-1-faskes-jujur", "demo-2-kasus-kpk", "demo-3-operasional")
HEADERS = {"Content-Type": "text/csv", "X-Synthetic-Schema-Version": "bpjs-fkrtl-csv-v1",
           "X-Synthetic-Mapping-Version": "bpjs-fkrtl-sample-map-v2", "X-Data-Classification": "synthetic_only"}
NOTE = "Contoh keputusan untuk demo (data sintetis)."
# Decisions on the demo-3 analysis: (scenario labels, how many, review status, outcome).
DECISIONS = (
    (("phantom_physiotherapy",), 3, "escalated", "signal_supported"),
    (("cloning",), 2, "closed", "signal_supported"),
    (("repeat_billing",), 2, "awaiting_evidence", "signal_supported"),
    (("fictitious_drug_device", "special_topup"), 2, "in_review", "signal_supported"),
    (("honest_group_session", "honest_busy_physiotherapy"), 2, "closed", "signal_not_supported"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--username", required=True)
    parser.add_argument("--ai-readings", type=int, default=0, help="Claims whose clinical note the AI reads in advance (±40 s each).")
    args = parser.parse_args()
    if urlparse(args.base_url).hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Hanya untuk server demo lokal (127.0.0.1/localhost).")

    client = httpx.Client(base_url=args.base_url, timeout=600)
    password = os.environ.get("CIR_DEMO_PASSWORD") or getpass.getpass("Password: ")
    session = client.post("/api/v1/auth/login", json={"username": args.username, "password": password})
    if session.status_code != 200:
        raise SystemExit("Login gagal.")
    client.headers["X-CSRF-Token"] = session.json()["csrf_token"]
    if client.get("/api/v1/runs", params={"limit": 1}).json().get("total_items"):
        raise SystemExit("Database ini sudah berisi analysis. Pengisi demo hanya untuk database demo yang masih kosong.")

    runs: dict[str, str] = {}
    for name in FILES:
        imported = client.post("/api/v1/batches/import", content=(DEMO_DIR / f"{name}.csv").read_bytes(),
                               headers={**HEADERS, "X-Batch-Key": f"synthetic-{name}"})
        imported.raise_for_status()
        batch = imported.json()["batch"]
        if batch["status"] == "rejected":
            raise SystemExit(f"{name}: berkas ditolak.")
        created = client.post("/api/v1/runs", json={"batch_id": batch["batch_id"]})
        created.raise_for_status()
        runs[name] = created.json()["run"]["run_id"]
        print(f"{name}: dianalisis ({batch.get('row_count', '?')} klaim).")

    run_id = runs["demo-3-operasional"]
    labels = json.loads((DEMO_DIR / "demo-3-operasional.answers.json").read_text(encoding="utf-8"))["labels"]
    flagged = []
    for lane in ("red", "yellow"):
        offset = 0
        while True:
            page = client.get(f"/api/v1/runs/{run_id}/cases",
                              params={"lane": lane, "limit": 100, "offset": offset, "sort": "ml_rank"}).json()
            flagged += [item["case"]["case_id"] for item in page["items"]]
            offset += 100
            if offset >= page["total_matching"]:
                break
    decided = 0
    for wanted, count, status, outcome in DECISIONS:
        for case_id in [case_id for case_id in flagged if labels.get(case_id) in wanted][:count]:
            path = f"/api/v1/runs/{run_id}/cases/{case_id}/review"
            client.patch(path, json={"review_status": status, "note": NOTE}).raise_for_status()
            client.post(f"{path}/outcome", json={"review_outcome": outcome, "note": NOTE}).raise_for_status()
            decided += 1
    print(f"Keputusan tinjauan contoh: {decided} klaim.")

    if args.ai_readings:
        noted = [case_id for case_id in flagged if labels.get(case_id) in ("cloning", "prolonged_stay", "upcoding")]
        for case_id in noted[:args.ai_readings]:
            reading = client.post(f"/api/v1/runs/{run_id}/cases/{case_id}/clinical-analysis")
            engine = reading.json().get("analysis", {}).get("engine") if reading.status_code == 200 else f"gagal ({reading.status_code})"
            print(f"Pembacaan AI {case_id[:12]}...: {engine}")
    print("Selesai. Buka aplikasi: analisis terbaru adalah demo-3.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
