"""Local orchestration contract for an explicitly selected feature provider."""

from __future__ import annotations

from typing import Any

from app.analytics.action_policy import ActionPolicyConfig, evaluate_action_policy, get_action_policy_config
from app.data_sources.providers import (
    CANONICAL_FEATURE_CONTRACT_VERSION,
    FeatureSourceProvider,
    load_feature_dataset,
)
from app.services.analytics import build_analytics_snapshot_from_dataset


def execute_provider_snapshot(
    provider: FeatureSourceProvider,
    action_policy: ActionPolicyConfig | None = None,
    stage_observer=None,
):
    """Load one explicit provider and execute the shared pipeline exactly once."""
    dataset = load_feature_dataset(provider)
    if stage_observer:
        stage_observer("provider_loaded")
    snapshot = build_analytics_snapshot_from_dataset(dataset, stage_observer=stage_observer)
    policy = action_policy or get_action_policy_config()
    snapshot["action_policy"] = evaluate_action_policy(snapshot, policy)
    if stage_observer:
        stage_observer("action_policy_complete")
    return dataset, snapshot


def run_provider_analysis(provider: FeatureSourceProvider, stage_observer=None) -> dict[str, Any]:
    """Run detectors, scoring, priority, and provisional policy once.

    This is a trusted service/local interface, not an API provider selector.
    Returned data is restricted to safe source metadata and the existing
    sanitized analytic snapshot; source rows, labels, and private paths do not
    appear in the envelope.
    """
    dataset, snapshot = execute_provider_snapshot(provider, stage_observer=stage_observer)
    metadata = dataset.source_metadata
    public_source = {
        key: metadata[key]
        for key in (
            "kind", "label", "classification", "source_schema_profile",
            "mapping_version", "adapter_coverage", "limitations",
        )
        if key in metadata
    }
    return {
        "feature_contract_version": CANONICAL_FEATURE_CONTRACT_VERSION,
        "data_source": public_source,
        "execution_status": snapshot["execution_status"],
        "coverage": snapshot["indicator_coverage"],
        "indicators": snapshot["indicators"],
        "signals": snapshot["cases"],
        "signal_count": len(snapshot["cases"]),
        "score_type": "provisional_rule_based_index_not_fraud_probability",
        "risk_scoring": snapshot["risk_scoring"],
        "audit_priority": snapshot["audit_priority"],
        "action_policy": snapshot["action_policy"],
        "limitations": list(dict.fromkeys(
            list(snapshot["risk_scoring"].get("limitations", []))
            + list(snapshot["audit_priority"].get("limitations", []))
            + list(metadata.get("limitations", []))
        )),
    }
