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


ACTION_POLICY_VERSION = "action-policy-demo-v1-provisional"
_VERSION_PATTERN = re.compile(r"^action-policy-[a-z0-9][a-z0-9._-]{0,60}-provisional$")
_ASSESSABLE_STATES = {"triggered", "not_triggered"}


@dataclass(frozen=True)
class ActionPolicyConfig:
    """Explicit configurable partitions of the normalized rule index [0, 1]."""

    version: str = ACTION_POLICY_VERSION
    green_upper: float = 1 / 3
    yellow_upper: float = 2 / 3

    def __post_init__(self) -> None:
        if not _VERSION_PATTERN.fullmatch(self.version):
            raise ValueError("Versi policy harus eksplisit dan berakhiran -provisional")
        if (not math.isfinite(self.green_upper) or not math.isfinite(self.yellow_upper)
                or not 0 < self.green_upper < self.yellow_upper < 1):
            raise ValueError("Batas lane harus memenuhi 0 < green_upper < yellow_upper < 1")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# Server-side registry: operators may select a reviewed version, but cannot
# submit their own lane thresholds through the API.
ACTION_POLICY_CONFIGURATIONS: dict[str, ActionPolicyConfig] = {
    ACTION_POLICY_VERSION: ActionPolicyConfig(),
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
