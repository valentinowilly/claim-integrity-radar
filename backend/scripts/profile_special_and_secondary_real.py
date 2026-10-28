"""Aggregate profile of the special top-up columns (FKL33-FKL46) and the secondary-diagnosis file (counts only).

Decides whether two planned checks are supportable on the BPJS sample before they are built:
- upcoding v2: does a severity II/III claim carry secondary diagnoses (comorbidity/complication) at all,
  and can FKRTL visits be matched to the secondary-diagnosis file?
- special drugs/prosthesis: are the special top-up columns filled often enough to compare?

Nothing row-level is printed: participant and visit numbers are hashed in memory only and never written;
codes are listed only when they occur at least ``MIN_CODE_COUNT`` times. FKL48 is not read.

Usage (local, authorised data use):
  python -m scripts.profile_special_and_secondary_real <fkrtl.dta> <diagnosissekunder.dta>
"""

from __future__ import annotations

import json
import sys
from collections import Counter

import numpy as np
import pandas as pd

MIN_CODE_COUNT = 100
CHUNK = 200_000
EMPTY = {"", "nan", "none", "-", "0", "<na>", "nat"}
SPECIAL = {  # group -> (code, description, tariff)
    "sub_acute_SA": ("FKL33", None, "FKL34"),
    "procedure_SP": ("FKL35", "FKL36", "FKL37"),
    "prosthesis_RR": ("FKL38", "FKL39", "FKL40"),
    "investigation_SI": ("FKL41", "FKL42", "FKL43"),
    "drugs_SD": ("FKL44", "FKL45", "FKL46"),
}
FKRTL_COLUMNS = ["PSTV01", "FKL02", "FKL03", "FKL06", "FKL07", "FKL08", "FKL09", "FKL10", "FKL19",
                 *[column for triple in SPECIAL.values() for column in triple if column]]


def _hash(series: pd.Series) -> np.ndarray:
    return pd.util.hash_pandas_object(series.astype(str), index=False).to_numpy()


def _filled(series: pd.Series) -> pd.Series:
    return ~series.astype(str).str.strip().str.lower().isin(EMPTY)


def _severity(groups: pd.Series) -> tuple[pd.Series, pd.Series]:
    parts = groups.astype(str).str.strip().str.split("-", expand=True)
    if parts.shape[1] < 4:
        empty = pd.Series([None] * len(groups), index=groups.index)
        return empty, empty
    return parts[1], parts[3]


def profile(fkrtl_path: str, secondary_path: str) -> dict:
    frames = []
    special = {name: {"filled": 0, "tariff_positive": 0, "codes": Counter(), "descriptions": {}} for name in SPECIAL}
    months: Counter[str] = Counter()
    levels: Counter[str] = Counter()
    rows = 0
    with pd.read_stata(fkrtl_path, iterator=True, chunksize=CHUNK, columns=FKRTL_COLUMNS,
                       convert_categoricals=False) as reader:
        for chunk in reader:
            rows += len(chunk)
            months.update(pd.to_datetime(chunk["FKL03"], errors="coerce").dt.strftime("%Y-%m").fillna("invalid"))
            levels.update(chunk["FKL10"].astype(str))
            case_type, severity = _severity(chunk["FKL19"])
            kept = pd.DataFrame({
                "visit": _hash(chunk["FKL02"]), "participant": _hash(chunk["PSTV01"]),
                "day": pd.to_datetime(chunk["FKL03"], errors="coerce"),
                "facility": _hash(chunk[["FKL06", "FKL07", "FKL08", "FKL09"]].astype(str).agg("|".join, axis=1)),
                "group": chunk["FKL19"].astype(str), "case_type": case_type.astype(str), "severity": severity.astype(str),
            })
            for name, (code, description, tariff) in SPECIAL.items():
                filled = _filled(chunk[code])
                special[name]["filled"] += int(filled.sum())
                special[name]["tariff_positive"] += int((pd.to_numeric(chunk[tariff], errors="coerce") > 0).sum())
                codes = chunk.loc[filled, code].astype(str).str.strip()
                special[name]["codes"].update(codes)
                if description:
                    for value, text in zip(codes, chunk.loc[filled, description].astype(str)):
                        special[name]["descriptions"].setdefault(value, text[:60])
                kept[name] = np.where(filled, chunk[code].astype(str).str.strip(), "")
            frames.append(kept)
    data = pd.concat(frames, ignore_index=True)
    inpatient = data["case_type"].isin(["1", "4", "6"])

    report: dict = {"fkrtl_rows": rows, "admission_months_top": months.most_common(6),
                    "service_level_FKL10": dict(levels.most_common(6)),
                    "inpatient_rows": int(inpatient.sum()),
                    "severity_inpatient": dict(Counter(data.loc[inpatient, "severity"]).most_common())}

    # Special top-up columns: fill rate, codes, and whether pairs with the INA-CBG are concentrated.
    report["special"] = {}
    for name in SPECIAL:
        info = special[name]
        codes = info["codes"]
        entry = {"filled": info["filled"], "filled_share": round(info["filled"] / rows, 5),
                 "tariff_positive": info["tariff_positive"], "distinct_codes": len(codes),
                 "top_codes": [(code, count, info["descriptions"].get(code)) for code, count in codes.most_common(8)
                               if count >= MIN_CODE_COUNT]}
        used = data[data[name] != ""]
        if len(used):
            pairs = used.groupby(["group", name]).size()
            entry["claims_in_pairs_seen_lt5"] = int(pairs[pairs < 5].sum())
            entry["claims_in_pairs_seen_lt20"] = int(pairs[pairs < 20].sum())
            # Same participant, same special code again within 30 / 90 days (prosthesis is usually fitted once).
            ordered = used.dropna(subset=["day"]).sort_values(["participant", name, "day"])
            gap = ordered.groupby(["participant", name])["day"].diff().dt.days
            entry["repeat_same_code_le30d"] = int((gap <= 30).sum())
            entry["repeat_same_code_le90d"] = int((gap <= 90).sum())
            # Facility spread: share of claims with this top-up per facility group (groups >= 200 claims).
            per_facility = data.groupby("facility").agg(claims=("visit", "size"), used=(name, lambda s: (s != "").sum()))
            per_facility = per_facility[per_facility["claims"] >= 200]
            share = per_facility["used"] / per_facility["claims"]
            entry["facility_share_quantiles"] = {q: round(float(share.quantile(q)), 4) for q in (0.5, 0.9, 0.99, 1.0)}
            entry["facility_groups_ge200"] = int(len(per_facility))
        report["special"][name] = entry

    # Secondary diagnoses: can the visits be matched, and do severe inpatient claims carry them?
    counts: Counter[int] = Counter()
    secondary_rows = 0
    with pd.read_stata(secondary_path, iterator=True, chunksize=CHUNK, columns=["FKL02", "FKL24"],
                       convert_categoricals=False) as reader:
        for chunk in reader:
            secondary_rows += len(chunk)
            filled = chunk[_filled(chunk["FKL24"])]
            counts.update(_hash(filled["FKL02"]).tolist())
    per_visit = pd.Series(counts, dtype="int64")
    data["secondary"] = data["visit"].map(per_visit).fillna(0).astype(int)
    matched = data["secondary"] > 0
    report["secondary"] = {
        "rows": secondary_rows, "visits_with_secondary": int(len(per_visit)),
        "fkrtl_visits_matched": int(matched.sum()), "fkrtl_matched_share": round(float(matched.mean()), 4),
        "matched_share_by_admission_month": {month: round(float(matched[data["day"].dt.strftime("%Y-%m") == month].mean()), 4)
                                             for month, _ in months.most_common(4)},
        "inpatient_by_severity": {
            level: {"claims": int(len(part)), "with_any_secondary": round(float((part["secondary"] > 0).mean()), 4),
                    "mean_secondary": round(float(part["secondary"].mean()), 3),
                    "median_secondary": float(part["secondary"].median())}
            for level, part in data[inpatient].groupby("severity") if len(part) >= 100},
    }
    return report


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    print(json.dumps(profile(sys.argv[1], sys.argv[2]), indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
