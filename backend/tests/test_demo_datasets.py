"""The demo claim files (BPJS column format, example data) import cleanly and tell their stories."""

from pathlib import Path

import pytest

from app.analytics.ml_model import category_labels
from app.data_sources.bpjs_csv import is_bpjs_csv, parse_bpjs_csv
from app.data_sources.synthetic_csv import GROUND_TRUTH_COLUMNS

DEMO_DIR = Path(__file__).resolve().parents[2] / "demo-data"
DEMOS = ("demo-1-faskes-jujur", "demo-2-kasus-kpk", "demo-3-operasional")
# Building and checking the stories needs the trained model and its category names (local, not committed).
needs_model = pytest.mark.skipif(not category_labels(), reason="model AI lokal dan category_labels.json tidak tersedia")


@pytest.mark.parametrize("name", DEMOS)
def test_demo_csv_is_bpjs_format_example_data_without_label_columns(name):
    raw = (DEMO_DIR / f"{name}.csv").read_bytes()
    header = raw.split(b"\n", 1)[0].decode().split(",")
    assert is_bpjs_csv(raw) and "FKL48" not in header and not set(header) & GROUND_TRUTH_COLUMNS
    records, summary = parse_bpjs_csv(raw, max_rows=200_000)
    assert summary["error_count"] == 0 and len(records) == summary["row_count"]


def test_daily_files_split_demo_3_by_admission_day():
    daily = sorted((DEMO_DIR / "harian").glob("klaim-*.csv"))
    assert len(daily) >= 28
    total = sum(parse_bpjs_csv(path.read_bytes(), max_rows=200_000)[1]["row_count"] for path in daily)
    assert total == parse_bpjs_csv((DEMO_DIR / "demo-3-operasional.csv").read_bytes(), max_rows=200_000)[1]["row_count"]


@needs_model
def test_demo_files_match_the_generator():
    from scripts.make_bpjs_demo_datasets import Vocabulary, build, to_csv
    vocabulary = Vocabulary()
    for name in DEMOS:
        assert to_csv(build(name, vocabulary).rows) == (DEMO_DIR / f"{name}.csv").read_bytes(), name


@needs_model
def test_demo_1_has_no_high_risk_hospital_and_demo_2_points_at_the_billing_hospital():
    from scripts.make_bpjs_demo_datasets import Vocabulary, build, check
    vocabulary = Vocabulary()
    honest = check(build("demo-1-faskes-jujur", vocabulary))
    assert honest["ai_mode"] == "pretrained_artifact"
    assert all(group["level"] != "high" for group in honest["top_groups"])
    assert honest["by_label"]["honest_routine_high_volume"] == {"not_flagged": 168}
    story = check(build("demo-2-kasus-kpk", vocabulary))
    top, second = story["top_groups"][:2]
    assert top["level"] == "high" and top["lane_counts"]["red"] >= 2 * second["lane_counts"]["red"]


def test_the_fast_leak_check_still_catches_synthetic_participant_tokens():
    from app.services.runs import _safe_snapshot
    features = [{"participant_token": f"syn-participant-{index:07d}"} for index in range(5000)]
    clean = {"cases": {"c1": {"reason": "pola identik pada 3 klaim"}}}
    assert _safe_snapshot(clean, features) == clean
    for leaked in ("syn-participant-0004321", "awal syn-participant-0000007 akhir", "xsyn-participant-0001234"):
        with pytest.raises(ValueError):
            _safe_snapshot({"cases": {"c1": {"reason": leaked}}}, features)
