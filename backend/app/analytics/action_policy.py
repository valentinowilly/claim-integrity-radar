"""Versioned, provisional action lanes for synthetic AnalysisRun results.

This policy is deliberately separate from risk scoring and audit priority. It
does not create or alter ``risk_level`` and is not a fraud determination.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import math
import re
from typing import Any


ACTION_POLICY_V1 = "action-policy-demo-v1-provisional"
# v2: when too few checks apply to compute the rule index (e.g. the FKRTL sample), a rule-flagged
# claim is laned by the independent ML signal: both signals agree -> red, ML moderately unusual -> yellow.
ACTION_POLICY_V2 = "action-policy-two-signal-v2-provisional"
# v3: every flagged claim is laned by its evidence. Two or more specific rule findings, or any finding
# confirmed by a very unusual AI score, is high; one specific finding is medium; the exploratory
# similar-claim screen alone needs AI support. A specific rule finding is never laned as low risk.
ACTION_POLICY_V3 = "action-policy-evidence-v3-provisional"
# v4 (default): as v3, but the similar-claim screen confirmed only by the AI no longer enters the queue.
# On the evaluation-kit benchmark those claims were fraud about as often as a random pick (about 2.5%
# against a 3.1% base rate), and they pushed specific findings out of the audit capacity.
ACTION_POLICY_VERSION = "action-policy-evidence-v4-provisional"
EXPLORATORY_INDICATORS = frozenset({"near_duplicate_claim_candidate"})
_VERSION_PATTERN = re.compile(r"^action-policy-[a-z0-9][a-z0-9._-]{0,60}-provisional$")
_ASSESSABLE_STATES = {"triggered", "not_triggered"}


@dataclass(frozen=True)
class ActionPolicyConfig:
    """Explicit configurable partitions of the normalized rule index [0, 1]."""

    version: str = ACTION_POLICY_V1
    green_upper: float = 1 / 3
    yellow_upper: float = 2 / 3
    ml_red_min: float | None = None
    ml_yellow_min: float | None = None
    evidence_rule: bool = False
    similarity_needs_rule: bool = False

    def __post_init__(self) -> None:
        if not _VERSION_PATTERN.fullmatch(self.version):
            raise ValueError("Versi policy harus eksplisit dan berakhiran -provisional")
        if (not math.isfinite(self.green_upper) or not math.isfinite(self.yellow_upper)
                or not 0 < self.green_upper < self.yellow_upper < 1):
            raise ValueError("Batas lane harus memenuhi 0 < green_upper < yellow_upper < 1")
        if (self.ml_red_min is None) != (self.ml_yellow_min is None) or (
                self.ml_red_min is not None and not 0 < self.ml_yellow_min < self.ml_red_min < 1):
            raise ValueError("Batas AI harus memenuhi 0 < ml_yellow_min < ml_red_min < 1")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# Server-side registry: operators may select a reviewed version, but cannot
# submit their own lane thresholds through the API.
ACTION_POLICY_CONFIGURATIONS: dict[str, ActionPolicyConfig] = {
    ACTION_POLICY_V1: ActionPolicyConfig(version=ACTION_POLICY_V1),
    ACTION_POLICY_V2: ActionPolicyConfig(version=ACTION_POLICY_V2, ml_red_min=0.95, ml_yellow_min=0.90),
    ACTION_POLICY_V3: ActionPolicyConfig(version=ACTION_POLICY_V3, ml_red_min=0.95, ml_yellow_min=0.90, evidence_rule=True),
    ACTION_POLICY_VERSION: ActionPolicyConfig(version=ACTION_POLICY_VERSION, ml_red_min=0.95, ml_yellow_min=0.90,
                                              evidence_rule=True, similarity_needs_rule=True),
}


def get_action_policy_config(version: str | None = None) -> ActionPolicyConfig:
    key = version or ACTION_POLICY_VERSION
    config = ACTION_POLICY_CONFIGURATIONS.get(key)
    if config is None:
        raise ValueError("ACTION_POLICY_VERSION_UNKNOWN")
    return config


def _cannot(version: str, reason: str, limitations: list[str]) -> dict[str, Any]:
    return {
        "lane": "cannot_recommend",
        "policy_version": version,
        "input_assessment_status": "not_assessable",
        "reasons": [reason],
        "limitations": limitations,
    }


def _case_lane(
    case: Mapping[str, Any],
    global_coverage: Mapping[str, Mapping[str, Any]],
    execution_status: str,
    config: ActionPolicyConfig,
) -> dict[str, Any]:
    limitations = [str(item) for item in case.get("limitations", []) if isinstance(item, str)]
    limitations.append("Lane adalah saran alur demo sintetis, bukan risk_level, probabilitas fraud, atau keputusan pelanggaran.")
    if execution_status == "failed":
        return _cannot(config.version, "AnalysisRun gagal; rekomendasi tidak dibuat.", limitations)

    if config.evidence_rule and case.get("indicators"):
        return _evidence_lane(case, config, limitations)
    if (config.ml_red_min is not None and case.get("risk_score") is None
            and case.get("score_status") == "insufficient_assessed_indicators" and case.get("indicators")):
        return _two_signal_lane(case, config, limitations)

    score = case.get("risk_score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)) or not 0 <= score <= 1:
        return _cannot(config.version, "Indeks aturan tidak tersedia atau di luar rentang yang didefinisikan.", limitations)
    if case.get("score_status") not in {"assessed", "assessed_no_signal"}:
        return _cannot(config.version, "Penilaian kasus tidak lengkap atau tidak dapat dinilai.", limitations)

    coverage_rows = case.get("indicator_coverage")
    if not isinstance(coverage_rows, list) or not coverage_rows:
        return _cannot(config.version, "Rincian cakupan indikator tidak tersedia.", limitations)
    relevant_count = 0
    unassessed: list[str] = []
    truncated: list[str] = []
    unavailable: list[str] = []
    for item in coverage_rows:
        if not isinstance(item, Mapping) or not isinstance(item.get("indicator"), str):
            return _cannot(config.version, "Rincian cakupan indikator tidak valid.", limitations)
        indicator, state = item["indicator"], item.get("status")
        if state == "not_applicable":
            continue
        relevant_count += 1
        if state == "not_assessed":
            unassessed.append(indicator)
        elif state not in _ASSESSABLE_STATES:
            unassessed.append(indicator)
        global_item = global_coverage.get(indicator, {})
        if global_item.get("status") == "unavailable":
            unavailable.append(indicator)
        if global_item.get("search_truncated") is True:
            truncated.append(indicator)
    if not relevant_count:
        return _cannot(config.version, "Tidak ada indikator yang berlaku dan berhasil dinilai.", limitations)
    if unassessed:
        return _cannot(config.version, "Satu atau lebih indikator yang relevan belum dinilai: " + ", ".join(sorted(set(unassessed))) + ".", limitations)
    if unavailable:
        return _cannot(config.version, "Pemeriksaan relevan tidak tersedia: " + ", ".join(sorted(set(unavailable))) + ".", limitations)
    if truncated:
        return _cannot(config.version, "Pencarian pemeriksaan relevan terpotong: " + ", ".join(sorted(set(truncated))) + ".", limitations)

    if execution_status == "partial":
        limitations.append("AnalysisRun memiliki cakupan parsial pada populasi; kasus ini hanya memakai indikator yang terukur lengkap.")
    if score <= config.green_upper:
        lane = "green"
        band = f"indeks aturan <= {config.green_upper:.6f}"
    elif score <= config.yellow_upper:
        lane = "yellow"
        band = f"{config.green_upper:.6f} < indeks aturan <= {config.yellow_upper:.6f}"
    else:
        lane = "red"
        band = f"indeks aturan > {config.yellow_upper:.6f}"
    return {
        "lane": lane,
        "policy_version": config.version,
        "input_assessment_status": "assessed",
        "reasons": [f"Indeks aturan {float(score):.6f} berada pada interval demo {band}."],
        "limitations": list(dict.fromkeys(limitations)),
    }


def _two_signal_lane(case: Mapping[str, Any], config: ActionPolicyConfig, limitations: list[str]) -> dict[str, Any]:
    """Rule-flagged claim without a rule index: lane by agreement with the independent ML signal."""
    ml = case.get("ml_anomaly") if isinstance(case.get("ml_anomaly"), Mapping) else {}
    percentile = ml.get("reference_percentile", ml.get("anomaly_percentile"))
    if isinstance(percentile, bool) or not isinstance(percentile, (int, float)) or not math.isfinite(float(percentile)):
        return _cannot(config.version, "Indeks aturan tidak dihitung dan penilaian AI tidak tersedia.", limitations)
    limitations.append("Indeks aturan tidak dihitung karena terlalu sedikit pemeriksaan yang berlaku; lane memakai "
                       "kesepakatan pemeriksaan aturan dan AI, bukan bobot yang dilatih.")
    if percentile >= config.ml_red_min:
        lane, reason = "red", f"Terdeteksi pemeriksaan aturan dan AI menilai lebih tidak biasa dari {config.ml_red_min:.0%} klaim acuan."
    elif percentile >= config.ml_yellow_min:
        lane, reason = "yellow", (f"Terdeteksi pemeriksaan aturan; AI menilai cukup tidak biasa "
                                  f"({config.ml_yellow_min:.0%}–{config.ml_red_min:.0%}).")
    else:
        lane, reason = "green", "Terdeteksi pemeriksaan aturan, tetapi AI menilai pola klaim wajar."
    return {
        "lane": lane,
        "policy_version": config.version,
        "input_assessment_status": "assessed",
        "reasons": [reason],
        "limitations": list(dict.fromkeys(limitations)),
    }


def _evidence_lane(case: Mapping[str, Any], config: ActionPolicyConfig, limitations: list[str]) -> dict[str, Any]:
    """Lane of a flagged claim from the number of specific rule findings and the independent AI signal."""
    indicators = [str(code) for code in case.get("indicators") or []]
    specific = [code for code in indicators if code not in EXPLORATORY_INDICATORS]
    ml = case.get("ml_anomaly") if isinstance(case.get("ml_anomaly"), Mapping) else {}
    percentile = ml.get("reference_percentile", ml.get("anomaly_percentile"))
    scored = isinstance(percentile, (int, float)) and not isinstance(percentile, bool) and math.isfinite(float(percentile))
    ai_high = scored and percentile >= config.ml_red_min
    ai_mid = scored and percentile >= config.ml_yellow_min
    # A score against the fixed training reference is absolute. A score from a model fitted on this run is
    # relative (its top 5% always exists, fraud or not), so it cannot confirm the exploratory screen alone.
    absolute = "reference_percentile" in ml
    if len(specific) >= 2:
        lane, reason = "red", f"{len(specific)} pemeriksaan aturan menemukan kejanggalan pada klaim ini."
    elif not specific and config.similarity_needs_rule:
        lane, reason = "green", "Hanya kemiripan dengan klaim lain, tanpa temuan pemeriksaan aturan yang spesifik."
    elif ai_high and (specific or absolute):
        lane, reason = "red", f"Terdeteksi pemeriksaan aturan dan AI menilai lebih tidak biasa dari {config.ml_red_min:.0%} klaim acuan."
    elif specific:
        lane, reason = "yellow", "Satu pemeriksaan aturan menemukan kejanggalan pada klaim ini."
    elif ai_mid and absolute:
        lane, reason = "yellow", (f"Terdeteksi kemiripan klaim; AI menilai cukup tidak biasa "
                                  f"({config.ml_yellow_min:.0%}–{config.ml_red_min:.0%}).")
    else:
        lane, reason = "green", "Hanya kemiripan dengan klaim lain dan AI menilai polanya wajar."
    if not scored:
        limitations.append("Penilaian AI tidak tersedia untuk klaim ini; lane hanya memakai pemeriksaan aturan.")
    return {
        "lane": lane,
        "policy_version": config.version,
        "input_assessment_status": "assessed",
        "reasons": [reason],
        "limitations": list(dict.fromkeys(limitations)),
    }


def evaluate_action_policy(
    snapshot: Mapping[str, Any], config: ActionPolicyConfig | None = None,
) -> dict[str, Any]:
    """Classify only the case findings present in the supplied saved snapshot."""
    config = config or ActionPolicyConfig()
    raw_coverage = snapshot.get("indicator_coverage", [])
    coverage = {
        item["indicator"]: item for item in raw_coverage
        if isinstance(item, Mapping) and isinstance(item.get("indicator"), str)
    } if isinstance(raw_coverage, list) else {}
    raw_cases = snapshot.get("cases", {})
    cases = raw_cases if isinstance(raw_cases, Mapping) else {}
    outputs: dict[str, dict[str, Any]] = {}
    for case_id in sorted(cases):
        case = cases[case_id]
        if isinstance(case, Mapping):
            outputs[str(case_id)] = _case_lane(case, coverage, str(snapshot.get("execution_status", "failed")), config)

    counts = {lane: sum(item["lane"] == lane for item in outputs.values())
              for lane in ("green", "yellow", "red", "cannot_recommend")}
    assessable = counts["green"] + counts["yellow"] + counts["red"]
    limitations = [
        "Ambang pembagian 0–1 menjadi tiga interval sama besar adalah konfigurasi demo sementara; belum divalidasi pada data BPJS atau disetujui pemilik kebijakan.",
        *(["Ambang AI (persentil klaim acuan) untuk lane dua-sinyal adalah pilihan kapasitas audit sementara, bukan hasil kalibrasi berlabel."]
          if config.ml_red_min is not None else []),
        "Lane hanya diterapkan pada kandidat kasus yang tersedia di snapshot; ketiadaan item tidak menyatakan klaim lain berstatus green.",
        "Policy tidak mengubah risk_score, risk_level, audit_priority, review status, atau review outcome.",
    ]
    return {
        "status": "not_assessable" if not outputs else ("partial" if counts["cannot_recommend"] else "available"),
        "unit": "case_finding",
        "policy_version": config.version,
        "configuration": config.as_dict(),
        "input_assessment_status": "not_assessable" if not outputs else ("partial" if counts["cannot_recommend"] else "assessed"),
        "lane_counts": counts,
        "cases": outputs,
        "limitations": limitations,
    }
