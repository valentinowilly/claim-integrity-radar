"""Facility-group summary: flagged claims rolled up per group of facility attributes.

The FKRTL sample has no facility identifier. A group is the combination of the
recorded facility attributes (province, district/city, ownership, type, class);
it is labelled as a group, never as a single hospital. Groups smaller than
``min_claims`` are not ranked or shown, so no small group can single out a
facility. Order ("worth auditing"): suspicious claims found per medical record
requested, without any amount (FKL47/FKL48 are not used).
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from app.analytics.action_policy import EXPLORATORY_INDICATORS

FACILITY_GROUP_VERSION = "facility-group-v1"
GROUP_FIELDS = ("province_code", "municipality_code", "facility_ownership", "facility_type", "facility_class")
MIN_CLAIMS = 30
MAX_GROUPS = 60
MAX_SAMPLE = 30  # every record the verdict asks for is listed in the evidence pack
MAX_RECORDS_REQUESTED = 30
LIMITATIONS = [
    "Kelompok faskes adalah gabungan provinsi, kabupaten/kota, kepemilikan, jenis, dan kelas faskes; "
    "satu kelompok bisa berisi lebih dari satu faskes dan bukan identitas rumah sakit.",
    f"Kelompok dengan kurang dari {MIN_CLAIMS} klaim tidak ditampilkan agar faskes tidak dapat dikenali.",
    "Urutan memakai jumlah klaim merah/kuning per rekam medis yang perlu diminta; tidak memakai nominal biaya.",
    "Tingkat risiko kelompok adalah prioritas tinjauan, bukan temuan kecurangan.",
    "Sinyal pembanding wilayah membandingkan porsi klaim dengan kelompok faskes sekelas di provinsi yang sama; "
    "ditampilkan sebagai alasan, tidak mengubah tingkat risiko atau urutan.",
]


def _key(record: Mapping[str, Any]) -> tuple[str, ...] | None:
    values = tuple(record.get(field) for field in GROUP_FIELDS)
    if any(value in (None, "") for value in values):
        return None
    return tuple(str(value) for value in values)


def _label(key: tuple[str, ...], labels: Mapping[str, Mapping[str, str]]) -> dict[str, str]:
    named = {field: (labels.get(field) or {}).get(code, code) for field, code in zip(GROUP_FIELDS, key)}
    return {
        "title": f"{named['facility_class']} · {named['facility_ownership']}",
        "region": f"{named['municipality_code']}, {named['province_code']}",
        "facility_type": named["facility_type"],
        "province_code": key[GROUP_FIELDS.index("province_code")],  # for the province filter and the map
    }


def _ml_percentile(case: Mapping[str, Any]) -> float:
    ml = case.get("ml_anomaly") if isinstance(case.get("ml_anomaly"), Mapping) else {}
    value = ml.get("reference_percentile", ml.get("anomaly_percentile"))
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _level(red: int, yellow: int, claims: int, overall_red_share: float, red_specific: int | None = None) -> str:
    """High needs several high-risk claims with a specific rule finding and a share well above the average.

    Size alone never decides, and neither does the exploratory similar-claim screen: high-risk claims found
    only by similarity (even when the AI agrees) make a group medium, because similarity is not a finding.
    """
    red_specific = red if red_specific is None else red_specific
    if red_specific >= 3 and claims and red / claims >= 2 * overall_red_share:
        return "high"
    if red >= 1 or yellow >= 3:
        return "medium"
    return "low"


LEVEL_TEXT = {"high": "RISIKO TINGGI", "medium": "RISIKO SEDANG", "low": "RISIKO RENDAH"}
INDICATOR_TEXT = {
    "length_of_stay_extreme_candidate": "lama rawat jauh di atas kebiasaan INA-CBG yang sama",
    "rapid_readmission_candidate": "pasien dirawat inap lagi dengan diagnosis sama tak lama setelah pulang",
    "unusual_severity_candidate": "keparahan INA-CBG tidak lazim untuk diagnosisnya",
    "cloned_clinical_note_candidate": "catatan klinis kembar antar pasien",
    "severity_without_secondary_candidate": "keparahan tinggi tanpa diagnosis sekunder",
    "unusual_special_topup_candidate": "tambahan obat/alat/tindakan khusus tidak lazim",
    "near_duplicate_claim_candidate": "klaim sangat mirip klaim peserta lain di hari yang sama",
    "similar_claim_pattern_candidate": "klaim berpola identik antar-peserta",
    "repeat_billing_candidate": "layanan berulang untuk peserta yang sama",
    "synthetic_capacity_candidate": "volume layanan melebihi kapasitas",
    "temporal_pattern_candidate": "pola waktu kunjungan tidak wajar",
    "supporting_evidence_completeness_candidate": "tindakan tanpa dokumen pendukung",
}


# Regional comparison (materi BPJS: upcoding leaves "statistical anomalies compared to regional averages").
# A group is compared with the other groups of the same province and facility class. Display and reasons
# only: it never changes the group level or order. Predeclared minimums keep small bases from triggering.
PEER_RULES = {
    # kind: (minimum base in the group, minimum base among peers, minimum ratio, minimum share in the group)
    "severity": (30, 100, 2.0, 0.10),
    "special": (100, 300, 3.0, 0.02),
}
PEER_TEXT = {
    "severity": "rawat inap keparahan II/III",
    "special": "klaim dengan tambahan obat/alat/tindakan khusus",
}
INPATIENT_CASE_TYPES = {"1", "4", "6"}


def _peer_counts(record: Mapping[str, Any]) -> dict[str, tuple[int, int]]:
    """(base, hits) per comparison kind for one claim; a kind is absent when the claim cannot count."""
    counts: dict[str, tuple[int, int]] = {}
    parts = str(record.get("claim_group") or "").split("-")
    if len(parts) == 4 and parts[1] in INPATIENT_CASE_TYPES:
        counts["severity"] = (1, int(parts[3] in ("II", "III")))
    if record.get("special_codes") is not None:
        counts["special"] = (1, int(bool(record.get("special_codes"))))
    return counts


def _peer_signals(key: tuple[str, ...], stats: Mapping[tuple[str, ...], Mapping[str, list[int]]]) -> list[dict[str, Any]]:
    signals = []
    for kind, (min_base, min_peer_base, min_ratio, min_share) in PEER_RULES.items():
        base, hits = stats.get(key, {}).get(kind, (0, 0))
        peers = [other for other in stats if other != key and other[0] == key[0] and other[4] == key[4]]
        peer_base = sum(stats[other].get(kind, (0, 0))[0] for other in peers)
        peer_hits = sum(stats[other].get(kind, (0, 0))[1] for other in peers)
        if base < min_base or peer_base < min_peer_base or len(peers) < 2:
            continue
        share, peer_share = hits / base, peer_hits / peer_base
        ratio = share / peer_share if peer_share else None
        if share >= min_share and (ratio is None or ratio >= min_ratio):
            signals.append({"kind": kind, "share": round(share, 4), "peer_share": round(peer_share, 4),
                            "ratio": round(ratio, 2) if ratio is not None else None, "peer_groups": len(peers),
                            "text": (f"{PEER_TEXT[kind]} {share:.0%} dari {base} klaim, sedangkan faskes sekelas di "
                                     f"provinsi yang sama {peer_share:.1%}")})
    return signals


def _verdict(group: Mapping[str, Any]) -> str:
    reasons = []
    if group["lane_counts"]["red"]:
        reasons.append(f"{group['lane_counts']['red']} klaim berisiko tinggi (beberapa pemeriksaan sepakat atau dikuatkan AI)")
    reasons.extend(signal["text"] for signal in group.get("peer_signals") or [])
    for code, count in group["indicator_counts"].items():
        share = round(100 * count / group["claim_count"])
        reasons.append(f"{count} dari {group['claim_count']} klaim ({share}%): {INDICATOR_TEXT.get(code, code)}")
    numbered = "; ".join(f"({index}) {text}" for index, text in enumerate(reasons[:3], start=1))
    advice = (f"minta rekam medis {group['records_to_request']} klaim sampel."
              if group["records_to_request"] else "lanjut proses biasa.")
    return f"{LEVEL_TEXT[group['level']]}. Alasan: {numbered or 'tidak ada temuan'}. Saran: {advice}"


# Display only: the billed amount (FKL47 for FKRTL, billed_amount for synthetic batches) is summed to
# show how much billing awaits re-verification. It never enters scoring, lanes, ordering or the AI.
AMOUNT_FIELDS = ("provider_billed_amount_unverified", "billed_amount")


def _amount(record: Mapping[str, Any]) -> Decimal | None:
    for field in AMOUNT_FIELDS:
        value = record.get(field)
        if value in (None, ""):
            continue
        try:
            amount = Decimal(str(value))
        except InvalidOperation:
            return None
        return amount if amount.is_finite() and amount >= 0 else None
    return None


def build_exposure(records: list[Mapping[str, Any]], lanes: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Billed value per risk level (aggregate); a value awaiting re-verification, not a loss."""
    lane_of = {case_id: (entry or {}).get("lane") for case_id, entry in lanes.items()}
    totals = {"all": Decimal(0), "red": Decimal(0), "yellow": Decimal(0)}
    with_amount = 0
    for record in records:
        amount = _amount(record)
        if amount is None:
            continue
        with_amount += 1
        totals["all"] += amount
        lane = lane_of.get(record.get("case_id"))
        if lane in ("red", "yellow"):
            totals[lane] += amount
    at_risk = totals["red"] + totals["yellow"]
    source = "provider_billed_amount_unverified" if any(r.get("provider_billed_amount_unverified") not in (None, "") for r in records[:50]) else "billed_amount"
    return {
        "status": "available" if with_amount else "unavailable",
        "amount_source": "FKL47 (biaya tagih faskes sebelum verifikasi)" if source == "provider_billed_amount_unverified" else "nilai tagihan berkas unggahan",
        "claims_with_amount": with_amount,
        "billed_total": int(totals["all"]),
        "billed_high": int(totals["red"]),
        "billed_medium": int(totals["yellow"]),
        "billed_high_or_medium": int(at_risk),
        "share_of_billed": round(float(at_risk / totals["all"]), 5) if totals["all"] else None,
        "note": "Nilai tagihan yang perlu diverifikasi ulang, bukan kerugian. Tidak dipakai untuk skor atau urutan.",
    }


FAIRNESS_DIMENSIONS = {"province_code": "Provinsi", "facility_class": "Kelas faskes", "facility_ownership": "Kepemilikan faskes"}


def build_fairness(records: list[Mapping[str, Any]], lanes: Mapping[str, Mapping[str, Any]],
                   labels: Mapping[str, Mapping[str, str]], min_claims: int = MIN_CLAIMS) -> dict[str, Any]:
    """Share of high/medium-risk claims per province, facility class and ownership against the overall share.

    A large ratio is a prompt to check for bias (or for a real regional pattern); it is not a finding.
    """
    lane_of = {case_id: (entry or {}).get("lane") for case_id, entry in lanes.items()}
    total = len(records)
    flagged_total = sum(lane in ("red", "yellow") for lane in lane_of.values())
    overall = flagged_total / total if total else 0.0
    dimensions = []
    for field, title in FAIRNESS_DIMENSIONS.items():
        claims: Counter[str] = Counter()
        high: Counter[str] = Counter()
        medium: Counter[str] = Counter()
        billed: dict[str, Decimal] = {}  # display only, as in build_exposure
        groups: dict[str, set[tuple[str, ...]]] = {}
        for record in records:
            value = record.get(field)
            if value in (None, ""):
                continue
            key = str(value)
            claims[key] += 1
            groups.setdefault(key, set()).add(tuple(str(record.get(name) or "") for name in GROUP_FIELDS))
            lane = lane_of.get(record.get("case_id"))
            if lane == "red":
                high[key] += 1
            elif lane == "yellow":
                medium[key] += 1
            amount = _amount(record)
            if amount is not None:
                billed[key] = billed.get(key, Decimal(0)) + (amount if lane in ("red", "yellow") else Decimal(0))
        rows = []
        for key, count in claims.items():
            if count < min_claims:
                continue
            share = (high[key] + medium[key]) / count
            rows.append({"label": (labels.get(field) or {}).get(key, key), "code": key, "claims": count, "high": high[key],
                         "medium": medium[key], "share": round(share, 5),
                         "ratio_to_overall": round(share / overall, 2) if overall else None,
                         "facility_groups": len(groups[key]),
                         "billed_high_or_medium": int(billed[key]) if key in billed else None})
        rows.sort(key=lambda row: (-(row["ratio_to_overall"] or 0), -row["claims"], row["label"]))
        dimensions.append({"field": field, "title": title, "rows": rows,
                           "hidden_categories": sum(1 for count in claims.values() if count < min_claims)})
    return {"overall_share": round(overall, 5), "claims": total, "high_or_medium": flagged_total,
            "min_claims": min_claims, "dimensions": dimensions,
            "note": "Rasio di atas 2 atau di bawah 0,5 perlu dicek: bisa bias data atau pola wilayah yang nyata."}


def build_facility_groups(
    records: list[Mapping[str, Any]], cases: Mapping[str, Mapping[str, Any]],
    lanes: Mapping[str, Mapping[str, Any]], labels: Mapping[str, Mapping[str, str]] | None = None,
    min_claims: int = MIN_CLAIMS,
) -> dict[str, Any]:
    labels = labels or {}
    claims: Counter[tuple[str, ...]] = Counter()
    members: dict[tuple[str, ...], list[str]] = {}
    at_risk_amount: Counter[tuple[str, ...]] = Counter()
    peer_stats: dict[tuple[str, ...], dict[str, list[int]]] = {}
    unkeyed = 0
    for record in records:
        key = _key(record)
        if key is None:
            unkeyed += 1
            continue
        claims[key] += 1
        for kind, (base, hits) in _peer_counts(record).items():
            totals = peer_stats.setdefault(key, {}).setdefault(kind, [0, 0])
            totals[0] += base
            totals[1] += hits
        if (lanes.get(record.get("case_id")) or {}).get("lane") in ("red", "yellow"):
            at_risk_amount[key] += int(_amount(record) or 0)
        case_id = record.get("case_id")
        if case_id in cases:
            members.setdefault(key, []).append(case_id)

    keyed_claims = sum(claims.values())
    overall_red_share = (sum((lanes.get(r.get("case_id")) or {}).get("lane") == "red" for r in records if _key(r) is not None)
                         / keyed_claims) if keyed_claims else 0.0
    groups = []
    hidden_groups = hidden_claims = 0
    for key, claim_count in claims.items():
        if claim_count < min_claims:
            hidden_groups += 1
            hidden_claims += claim_count
            continue
        flagged = members.get(key, [])
        lane_of = {case_id: (lanes.get(case_id) or {}).get("lane", "cannot_recommend") for case_id in flagged}
        lane_counts = {lane: sum(value == lane for value in lane_of.values()) for lane in ("red", "yellow", "green")}
        actionable = sorted((case_id for case_id in flagged if lane_of[case_id] in ("red", "yellow")),
                            key=lambda case_id: (lane_of[case_id] != "red", -_ml_percentile(cases[case_id]), case_id))
        records_to_request = min(len(actionable), MAX_RECORDS_REQUESTED)
        weighted = 2 * lane_counts["red"] + lane_counts["yellow"]
        group = {
            "group_id": "fg-" + hashlib.sha256("|".join(key).encode()).hexdigest()[:10],
            **_label(key, labels),
            "claim_count": claim_count,
            "flagged_count": len(flagged),
            "lane_counts": lane_counts,
            "indicator_counts": dict(Counter(code for case_id in flagged for code in cases[case_id].get("indicators") or [])
                                     .most_common()),
            "records_to_request": records_to_request,
            "findings_per_record": round(weighted / records_to_request, 3) if records_to_request else 0.0,
            "max_ml_percentile": round(max((_ml_percentile(cases[c]) for c in flagged), default=0.0), 4),
            "billed_high_or_medium": at_risk_amount[key],
            "sample_case_ids": actionable[:MAX_SAMPLE],
            "sample_lanes": {case_id: lane_of[case_id] for case_id in actionable[:MAX_SAMPLE]},
            # Which checks flagged each sample claim, so a list can say why without loading every claim.
            "sample_findings": {case_id: list(cases[case_id].get("indicators") or []) for case_id in actionable[:MAX_SAMPLE]},
            "peer_signals": _peer_signals(key, peer_stats),
        }
        group["red_with_specific_finding"] = sum(
            lane_of[case_id] == "red" and any(code not in EXPLORATORY_INDICATORS for code in cases[case_id].get("indicators") or [])
            for case_id in flagged)
        group["level"] = _level(lane_counts["red"], lane_counts["yellow"], claim_count, overall_red_share,
                                group["red_with_specific_finding"])
        group["verdict"] = _verdict(group)
        groups.append(group)

    level_rank = {"high": 0, "medium": 1, "low": 2}
    groups.sort(key=lambda g: (level_rank[g["level"]], -g["lane_counts"]["red"], -g["findings_per_record"],
                               -g["lane_counts"]["yellow"], -g["max_ml_percentile"], g["group_id"]))
    for rank, group in enumerate(groups, start=1):
        group["rank"] = rank
    return {
        "status": "available" if groups else "insufficient_data",
        "version": FACILITY_GROUP_VERSION,
        "unit": "facility_group",
        "group_fields": list(GROUP_FIELDS),
        "min_claims": min_claims,
        "group_count": len(groups),
        "level_counts": {level: sum(g["level"] == level for g in groups) for level in ("high", "medium", "low")},
        "hidden_group_count": hidden_groups,
        "hidden_claim_count": hidden_claims,
        "records_without_group": unkeyed,
        "groups": groups[:MAX_GROUPS],
        "fairness": build_fairness(records, lanes, labels, min_claims),
        "exposure": build_exposure(records, lanes),
        "groups_truncated": len(groups) > MAX_GROUPS,
        "limitations": LIMITATIONS,
    }
