"""Secondary diagnoses, special top-ups and the regional facility comparison (BPJS column format)."""

from app.analytics.claim_detail_rules import (
    MIN_PAIR_COUNT, SEP, detect_severity_without_secondary, detect_unusual_special_topup,
)
from app.analytics.facility_groups import _peer_counts, _peer_signals
from app.data_sources.bpjs_csv import parse_bpjs_csv
from app.data_sources.bpjs_fkrtl_adapter import adapt_fkrtl_rows
from tests.test_bpjs_csv_upload import COLUMNS, _csv, _rows

SECRET = b"k" * 32


def _record(case, group, secondary=None, special=None, participant="p1"):
    return {"case_id": f"syn-{case}", "participant_token": participant, "claim_group": group,
            "secondary_diagnoses": secondary, "special_codes": special}


def test_severe_inpatient_claims_without_any_secondary_diagnosis_are_flagged():
    result = detect_severity_without_secondary([
        _record("a", "K-1-17-III", []),            # flagged
        _record("b", "K-1-17-II", ["E119"]),       # has a comorbidity
        _record("c", "K-1-17-I", []),              # severity I: not applicable
        _record("d", "Q-5-44-0", []),              # outpatient: not applicable
        _record("e", "K-1-17-III", None),          # source without secondary diagnoses
        _record("f", "bukan-kode", []),            # unreadable INA-CBG: not assessed
    ])
    assert [item["case_id"] for item in result["candidates"]] == ["syn-a"]
    assert result["assessed_count"] == 2 and result["unassessed_case_ids"] == ["syn-f"]
    assert {item["case_id"] for item in result["not_applicable_cases"]} == {"syn-c", "syn-d", "syn-e"}


def test_without_secondary_data_the_check_is_not_applicable():
    result = detect_severity_without_secondary([_record("a", "K-1-17-III", None)])
    assert result["status"] == "not_applicable" and result["candidates"] == []


def test_special_codes_rare_for_the_ina_cbg_are_flagged_and_the_check_needs_its_reference():
    reference = {"pairs": {f"H-1-30-I{SEP}YY-10-III": 500, f"H-1-30-I{SEP}YY-09-III": MIN_PAIR_COUNT},
                 "codes": {"YY-10-III": 5000, "YY-09-III": 300, "DD-10-II": 650}}
    result = detect_unusual_special_topup([
        _record("a", "H-1-30-I", special=["YY-10-III"]),      # usual pair
        _record("b", "K-1-17-II", special=["YY-10-III"]),     # cataract top-up on a digestive INA-CBG
        _record("c", "H-1-30-I", special=["DD-10-II"]),       # known code, never with this INA-CBG
        _record("d", "H-1-30-I", special=["XX-99-I"]),        # unknown code
        _record("e", "H-1-30-I", special=[]),                 # no top-up billed
        _record("f", "H-1-30-I", special=None),               # source without the columns
    ], reference)
    flagged = {item["case_id"]: item for item in result["candidates"]}
    assert set(flagged) == {"syn-b", "syn-c", "syn-d"}
    assert "tidak dikenal" in flagged["syn-d"]["reason"] and "tidak dikenal" not in flagged["syn-c"]["reason"]
    assert detect_unusual_special_topup([_record("a", "H-1-30-I", special=["YY-10-III"])], None)["status"] == "unavailable"


def test_the_adapter_keeps_special_codes_and_joins_secondary_diagnoses_by_visit():
    row = {"PSTV01": "SYN1", "FKL02": "V1", "FKL03": "2024-03-04", "FKL19": "K-1-17-III", "FKL35": "YY-10-III",
           "FKL44": " ", "FKL38": None}
    without, _ = adapt_fkrtl_rows([row], case_reference_secret=SECRET)
    assert without[0]["special_codes"] == ["YY-10-III"] and without[0]["secondary_diagnoses"] is None
    joined, _ = adapt_fkrtl_rows([row, dict(row, FKL02="V2")], case_reference_secret=SECRET,
                                 secondary_lookup={"V1": ["I10", "E119", "I10"]})
    assert joined[0]["secondary_diagnoses"] == ["E119", "I10"] and joined[1]["secondary_diagnoses"] == []
    plain = {key: value for key, value in row.items() if key not in ("FKL35", "FKL44", "FKL38")}
    assert adapt_fkrtl_rows([plain], case_reference_secret=SECRET)[0][0]["special_codes"] is None


def test_an_upload_may_carry_secondary_diagnoses_in_column_fkl24():
    rows = _rows(20)
    rows[0]["FKL24"] = "e119; I10 |N18"
    rows[0]["FKL35"] = "YY-10-III"
    records, summary = parse_bpjs_csv(_csv(rows, COLUMNS + ("FKL24", "FKL35")))
    assert summary["error_count"] == 0 and not summary.get("warning_counts", {}).get("unknown_columns_ignored")
    assert records[0]["secondary_diagnoses"] == ["E119", "I10", "N18"] and records[1]["secondary_diagnoses"] == []
    assert records[0]["special_codes"] == ["YY-10-III"]
    plain, _ = parse_bpjs_csv(_csv(rows))
    assert plain[0]["secondary_diagnoses"] is None and plain[0]["special_codes"] is None


def test_regional_comparison_names_a_group_well_above_its_peers_only():
    stats = {
        ("31", "3171", "9", "1", "2"): {"severity": [60, 40]},   # (inpatient, severe): 67% severe
        ("31", "3172", "9", "1", "2"): {"severity": [80, 10]},
        ("31", "3173", "9", "1", "2"): {"severity": [90, 12]},
        ("32", "3201", "9", "1", "2"): {"severity": [90, 80]},   # other province: not a peer
    }
    stats = {key: {kind: tuple(value) for kind, value in kinds.items()} for key, kinds in stats.items()}
    signals = _peer_signals(("31", "3171", "9", "1", "2"), stats)
    assert [signal["kind"] for signal in signals] == ["severity"] and signals[0]["peer_groups"] == 2
    assert signals[0]["peer_share"] == round(22 / 170, 4)
    assert _peer_signals(("31", "3172", "9", "1", "2"), stats) == []
    assert _peer_counts({"claim_group": "K-1-17-III", "special_codes": None}) == {"severity": (1, 1)}
    assert _peer_counts({"claim_group": "Q-5-44-0", "special_codes": ["DD-10-II"]}) == {"special": (1, 1)}
