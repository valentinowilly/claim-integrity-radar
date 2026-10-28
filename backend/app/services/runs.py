"""Persistent, immutable analysis-run execution over ready batches or the configured FKRTL sample."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import logging
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator
from uuid import uuid4

from app.data_sources.bpjs_csv import BPJS_CSV_SCHEMA_VERSION
from app.data_sources.providers import LOOKBACK_DAYS
from app.db import DatabaseError, connect_operational, is_postgres, sqlite_script
from app.analytics.action_policy import ActionPolicyConfig, get_action_policy_config
from app.analytics.audit_priority import AuditEffortConfig
from app.analytics.batch_adapter import BatchAdapterError
from app.analytics.capacity import CapacityConfig
from app.analytics.evidence_completeness import DEFAULT_REQUIRED_EVIDENCE
from app.analytics.near_duplicate_claims import NearDuplicateConfig
from app.analytics.risk_scoring import DETECTOR_ORDER, DETECTOR_SUITE_VERSION
from app.analytics.temporal_patterns import TemporalConfig
from app.data_sources.fkrtl_local_source import (
    FKRTL_BATCH_KEY, FKRTL_SCHEMA_PROFILE, FKRTL_SOURCE_CLASSIFICATION, FKRTL_SOURCE_TYPE,
    load_fkrtl_local_source,
)
from app.data_sources.providers import FeatureDataset, SyntheticBatchProvider
from app.services.provider_orchestrator import execute_provider_snapshot
from app.services.batches import BatchStorageError, BatchStore
from app.services.run_results import (
    CASE_ROWS_SCHEMA, case_page, case_view, has_case_rows, is_missing, stored_case_page, stored_case_view, stored_result,
    stored_summary, summary_view, write_case_rows,
)


class RunStorageError(Exception):
    """A safe local AnalysisRun storage error."""


class RunInputError(Exception):
    """A safe batch eligibility, retry, or request-reference error."""


class RunExecutionError(Exception):
    """The run was persisted as failed after a safe pipeline failure."""

    def __init__(self, run_id: str):
        super().__init__("AnalysisRun failed.")
        self.run_id = run_id


TERMINAL_STATUSES = frozenset({"completed", "partial", "failed"})
_SYNTHETIC_TOKEN_PREFIX = "syn-participant-"
_HMAC_PARTICIPANT_TOKEN = re.compile(r"participant_[0-9a-f]{32}")
SOURCE_CLASSIFICATIONS = {
    "synthetic_csv": "synthetic_only_declared",
    FKRTL_SOURCE_TYPE: FKRTL_SOURCE_CLASSIFICATION,
}


@dataclass(frozen=True)
class _PreloadedProvider:
    """Hands an already-read dataset to the shared orchestrator."""

    dataset: FeatureDataset

    def load(self) -> FeatureDataset:
        return self.dataset


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"Unsupported result type: {type(value).__name__}")


def _loads(value: str | None) -> Any:
    return json.loads(value) if value is not None else None


def _safe_snapshot(snapshot: Mapping[str, Any], features: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Remove identity/signature internals and guard against values leaking into results."""
    forbidden_keys = {
        "participant_token", "participant_id", "PSTV01", "ground_truth", "is_anomaly",
        "is_synthetic_anomaly", "scenario", "scenario_label", "scenario_labels",
        "scenario_group_id", "scenario_code", "primary_scenario", "intensity_level",
        "injected_signals", "claim_labels", "group_labels", "fingerprint", "signature",
        "signature_hash", "raw_signature",
    }
    sensitive_values = {row.get("participant_token") for row in features
                        if isinstance(row.get("participant_token"), str)}
    # HMAC tokens have a fixed shape, so a regex scan plus set lookup replaces a
    # per-string scan over every token (quadratic on large local sources).
    patterned = {token for token in sensitive_values if _HMAC_PARTICIPANT_TOKEN.fullmatch(token)}
    # Synthetic tokens share a fixed prefix: every place the prefix occurs is checked against the token
    # set at each token length (exact, and linear in the text instead of one scan per token).
    prefixed = {token for token in sensitive_values - patterned if token.startswith(_SYNTHETIC_TOKEN_PREFIX)}
    prefixed_lengths = sorted({len(token) for token in prefixed})
    other_values = sensitive_values - patterned - prefixed

    def leaks(value: str) -> bool:
        if patterned and any(match in patterned for match in _HMAC_PARTICIPANT_TOKEN.findall(value)):
            return True
        if prefixed:
            start = value.find(_SYNTHETIC_TOKEN_PREFIX)
            while start != -1:
                if any(value[start:start + length] in prefixed for length in prefixed_lengths):
                    return True
                start = value.find(_SYNTHETIC_TOKEN_PREFIX, start + 1)
        return any(token in value for token in other_values)

    def clean(value: Any, parent_key: str = "") -> Any:
        if isinstance(value, Mapping):
            return {key: clean(item, str(key)) for key, item in value.items()
                    if str(key) not in forbidden_keys}
        if isinstance(value, (list, tuple)):
            items = list(value)
            if parent_key in {"matched_attributes", "differing_attributes", "context_unavailable_attributes"}:
                items = [item for item in items if item not in ("participant_token", "PSTV01")]
            return [clean(item, parent_key) for item in items]
        if isinstance(value, str) and leaks(value):
            raise ValueError("Sensitive value detected in analysis output.")
        return value

    return clean(snapshot)


RESULT_CONTRACT = "run-result-shared-text-v1"


def _compact_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Store shared explanatory text once instead of on every case (lossless, same semantics).

    A reason's limitations are dropped only when every text is already in that indicator's
    summary limitations; case limitations drop only texts held in ``risk_scoring.limitations``;
    a not-applicable coverage row of a check the whole source does not support drops its
    reason, which the indicator summary states. Case states, reasons, scores and evidence are
    unchanged.
    """
    indicators = {item.get("code"): item for item in snapshot.get("indicators", []) if isinstance(item, Mapping)}
    shared_scoring = set((snapshot.get("risk_scoring") or {}).get("limitations") or [])
    unsupported = {code for code, item in indicators.items() if item.get("status") == "not_applicable"}
    for case in (snapshot.get("cases") or {}).values():
        for reason in case.get("reasons", []):
            summary = set((indicators.get(reason.get("indicator")) or {}).get("limitations") or [])
            if reason.get("limitations") and set(reason["limitations"]) <= summary:
                reason["limitations"] = []
        case["limitations"] = [text for text in case.get("limitations", []) if text not in shared_scoring]
        for row in case.get("indicator_coverage", []):
            if row.get("status") == "not_applicable" and row.get("indicator") in unsupported:
                row["reason"] = None
    snapshot["result_contract"] = {
        "version": RESULT_CONTRACT,
        "shared_text": "Check limitations are in indicators[].limitations; scoring limitations in "
                       "risk_scoring.limitations; reasons of source-wide not-applicable checks in the indicator summary.",
    }
    return snapshot


def _execution_configuration(snapshot: Mapping[str, Any], action_policy: ActionPolicyConfig,
                             source_type: str) -> dict[str, Any]:
    priority = snapshot.get("audit_priority", {})
    scoring = snapshot.get("risk_scoring", {})
    data_source = snapshot.get("data_source", {})
    return {
        "source": {
            "source_type": source_type,
            "classification": SOURCE_CLASSIFICATIONS[source_type],
            "mapping_version": data_source.get("mapping_version"),
            "schema_profile": data_source.get("source_schema_profile"),
            **({"selection": data_source["selection"]} if data_source.get("selection") else {}),
            **({"repeat_signature_profile": data_source["repeat_signature_profile"]}
               if data_source.get("repeat_signature_profile") else {}),
        },
        "detector_suite_version": DETECTOR_SUITE_VERSION,
        "detector_order": list(DETECTOR_ORDER),
        "detector_defaults": {
            "synthetic_capacity_candidate": asdict(CapacityConfig()),
            "near_duplicate_claim_candidate": asdict(NearDuplicateConfig()),
            "temporal_pattern_candidate": asdict(TemporalConfig()),
            "supporting_evidence_completeness_candidate": {
                key: list(values) for key, values in sorted(DEFAULT_REQUIRED_EVIDENCE.items())
            },
            "repeat_billing_candidate": "function defaults; no version/config object declared",
            "similar_claim_pattern_candidate": "function defaults; no version/config object declared",
        },
        "risk_scoring": {
            "version": scoring.get("version"),
            "weights": scoring.get("weights"),
            "weight_basis": scoring.get("weight_basis"),
        },
        "audit_priority": {
            "version": priority.get("priority_version"),
            "effort_config": asdict(AuditEffortConfig()),
            "formula": priority.get("formula"),
        },
        "action_policy": action_policy.as_dict(),
        "ml_anomaly": {
            key: (snapshot.get("ml_anomaly") or {}).get(key)
            for key in ("model_version", "parameters", "score_type")
        },
        "length_of_stay": {
            key: (snapshot.get("length_of_stay") or {}).get(key) for key in ("version", "method")
        },
    }


class AnalysisRunStore:
    """SQLite run manifest and result store sharing the immutable batch database."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = connect_operational(self.path, timeout=20)
            sqlite_script(connection, 
                """
                CREATE TABLE IF NOT EXISTS analysis_runs (
                    run_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL REFERENCES data_batches(batch_id),
                    batch_version INTEGER NOT NULL,
                    content_checksum TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_schema_version TEXT NOT NULL,
                    source_mapping_version TEXT NOT NULL,
                    creator_user_id TEXT NOT NULL,
                    retry_of_run_id TEXT REFERENCES analysis_runs(run_id),
                    created_at TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    execution_status TEXT NOT NULL CHECK(execution_status IN ('running','completed','partial','failed')),
                    failure_category TEXT,
                    detector_suite_version TEXT,
                    scoring_version TEXT,
                    priority_version TEXT,
                    action_policy_version TEXT,
                    configuration_json TEXT NOT NULL,
                    coverage_summary_json TEXT,
                    result_available INTEGER NOT NULL DEFAULT 0 CHECK(result_available IN (0,1))
                );
                CREATE TABLE IF NOT EXISTS analysis_run_results (
                    run_id TEXT PRIMARY KEY REFERENCES analysis_runs(run_id),
                    result_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS action_policy_configurations (
                    version TEXT PRIMARY KEY,
                    configuration_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS action_policy_config_no_update
                BEFORE UPDATE ON action_policy_configurations
                BEGIN SELECT RAISE(ABORT, 'Action policy configuration is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS action_policy_config_no_delete
                BEFORE DELETE ON action_policy_configurations
                BEGIN SELECT RAISE(ABORT, 'Action policy configuration is immutable'); END;
                CREATE TABLE IF NOT EXISTS analysis_run_audit_events (
                    event_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    actor_user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    target_run_id TEXT NOT NULL REFERENCES analysis_runs(run_id),
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS analysis_run_archives (
                    run_id TEXT PRIMARY KEY REFERENCES analysis_runs(run_id),
                    archived_at TEXT NOT NULL,
                    actor_user_id TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_runs_created
                    ON analysis_runs(created_at DESC, run_id DESC);
                CREATE INDEX IF NOT EXISTS idx_analysis_runs_batch
                    ON analysis_runs(batch_id, created_at DESC);
                CREATE TRIGGER IF NOT EXISTS analysis_run_transition_guard
                BEFORE UPDATE ON analysis_runs
                WHEN OLD.execution_status <> 'running'
                  OR NEW.execution_status NOT IN ('completed','partial','failed')
                  OR NEW.run_id <> OLD.run_id OR NEW.batch_id <> OLD.batch_id
                  OR NEW.batch_version <> OLD.batch_version
                  OR NEW.content_checksum <> OLD.content_checksum
                  OR NEW.source_type <> OLD.source_type
                  OR NEW.source_schema_version <> OLD.source_schema_version
                  OR NEW.source_mapping_version <> OLD.source_mapping_version
                  OR NEW.creator_user_id <> OLD.creator_user_id
                  OR COALESCE(NEW.retry_of_run_id,'') <> COALESCE(OLD.retry_of_run_id,'')
                  OR NEW.created_at <> OLD.created_at OR NEW.started_at <> OLD.started_at
                  OR (NEW.execution_status IN ('completed','partial') AND NOT EXISTS (
                      SELECT 1 FROM analysis_run_results WHERE run_id=OLD.run_id
                  ))
                BEGIN SELECT RAISE(ABORT, 'AnalysisRun terminal state is immutable'); END;
                -- The short-lived retention variant (_v2) is removed; terminal runs are never deleted.
                DROP TRIGGER IF EXISTS analysis_run_terminal_delete_guard_v2;
                CREATE TRIGGER IF NOT EXISTS analysis_run_terminal_delete_guard
                BEFORE DELETE ON analysis_runs
                WHEN OLD.execution_status IN ('completed','partial','failed')
                BEGIN SELECT RAISE(ABORT, 'AnalysisRun terminal state is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS analysis_run_result_insert_guard
                BEFORE INSERT ON analysis_run_results
                WHEN (SELECT execution_status FROM analysis_runs WHERE run_id=NEW.run_id) <> 'running'
                BEGIN SELECT RAISE(ABORT, 'result may only be attached to a running run'); END;
                CREATE TRIGGER IF NOT EXISTS analysis_run_result_update_guard
                BEFORE UPDATE ON analysis_run_results
                BEGIN SELECT RAISE(ABORT, 'AnalysisRun result is immutable'); END;
                DROP TRIGGER IF EXISTS analysis_run_result_delete_guard_v2;
                CREATE TRIGGER IF NOT EXISTS analysis_run_result_delete_guard
                BEFORE DELETE ON analysis_run_results
                BEGIN SELECT RAISE(ABORT, 'AnalysisRun result is immutable'); END;
                """
            )
            # Per-case rows and summary of new results (additive migration; old runs keep reading
            # their snapshot).
            sqlite_script(connection, CASE_ROWS_SCHEMA)
            columns = {"action_policy_version"} if is_postgres(connection) else {
                row["name"] for row in connection.execute("PRAGMA table_info(analysis_runs)")}
            if "action_policy_version" not in columns:
                connection.execute("ALTER TABLE analysis_runs ADD COLUMN action_policy_version TEXT")
            yield connection
            connection.commit()
        except (OSError, *DatabaseError) as exc:
            if connection is not None:
                connection.rollback()
            raise RunStorageError("Penyimpanan AnalysisRun lokal tidak tersedia.") from exc
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _manifest(row: sqlite3.Row, result: Any = None) -> dict[str, Any]:
        configuration = _loads(row["configuration_json"])
        source_classification = (configuration.get("source") or {}).get(
            "classification", SOURCE_CLASSIFICATIONS.get(row["source_type"], "synthetic_only_declared")
        )
        return {
            "run_id": row["run_id"], "batch_id": row["batch_id"],
            "batch_version": row["batch_version"], "content_checksum": row["content_checksum"],
            "source_type": row["source_type"],
            "source_classification": source_classification,
            "source_schema_version": row["source_schema_version"],
            "source_mapping_version": row["source_mapping_version"],
            "creator_user_id": row["creator_user_id"], "retry_of_run_id": row["retry_of_run_id"],
            "created_at": row["created_at"], "started_at": row["started_at"],
            "completed_at": row["completed_at"], "execution_status": row["execution_status"],
            "failure_category": row["failure_category"],
            "detector_suite_version": row["detector_suite_version"],
            "scoring_version": row["scoring_version"], "priority_version": row["priority_version"],
            "action_policy_version": row["action_policy_version"],
            "configuration": configuration,
            "coverage": _loads(row["coverage_summary_json"]),
            "result_available": bool(row["result_available"]),
            "result_storage_reference": f"analysis_run_results:{row['run_id']}" if row["result_available"] else None,
            "result": result,
        }

    def create_running(self, batch: Mapping[str, Any], creator_user_id: str,
                       retry_of_run_id: str | None = None,
                       action_policy: ActionPolicyConfig | None = None) -> str:
        action_policy = action_policy or ActionPolicyConfig()
        run_id = f"run_{uuid4().hex}"
        now = utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            policy_json = json.dumps(action_policy.as_dict(), sort_keys=True, separators=(",", ":"))
            connection.execute(
                "INSERT OR IGNORE INTO action_policy_configurations(version,configuration_json,created_at) VALUES(?,?,?)",
                (action_policy.version, policy_json, now),
            )
            registered = connection.execute(
                "SELECT configuration_json FROM action_policy_configurations WHERE version=?",
                (action_policy.version,),
            ).fetchone()
            if registered is None or registered["configuration_json"] != policy_json:
                raise RunInputError("ACTION_POLICY_VERSION_CONFLICT")
            pinned = connection.execute(
                "SELECT batch_version, content_checksum, source_type, schema_version, mapping_version, status "
                "FROM data_batches WHERE batch_id=?", (batch.get("batch_id"),),
            ).fetchone()
            if pinned is None:
                raise RunInputError("BATCH_NOT_FOUND")
            if (pinned["status"] not in {"ready", "ready_with_warnings"}
                    or pinned["batch_version"] != batch.get("batch_version")
                    or pinned["content_checksum"] != batch.get("content_checksum")
                    or pinned["source_type"] != batch.get("source_type")
                    or pinned["schema_version"] != batch.get("schema_version")
                    or pinned["mapping_version"] != batch.get("mapping_version")):
                raise RunInputError("BATCH_VERSION_MISMATCH")
            if retry_of_run_id is not None:
                prior = connection.execute(
                    "SELECT batch_id,batch_version,content_checksum,execution_status FROM analysis_runs WHERE run_id=?",
                    (retry_of_run_id,),
                ).fetchone()
                if prior is None:
                    raise RunInputError("RETRY_RUN_NOT_FOUND")
                if prior["execution_status"] != "failed":
                    raise RunInputError("RUN_NOT_RETRYABLE")
                if (prior["batch_id"] != batch["batch_id"]
                        or prior["batch_version"] != batch["batch_version"]
                        or prior["content_checksum"] != batch["content_checksum"]):
                    raise RunInputError("RETRY_BATCH_MISMATCH")
            connection.execute(
                "INSERT INTO analysis_runs(run_id,batch_id,batch_version,content_checksum,source_type,"
                "source_schema_version,source_mapping_version,creator_user_id,retry_of_run_id,"
                "created_at,started_at,execution_status,action_policy_version,configuration_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,'running',?,?)",
                (run_id, batch["batch_id"], batch["batch_version"], batch["content_checksum"], batch["source_type"],
                 batch["schema_version"], batch["mapping_version"], creator_user_id,
                 retry_of_run_id, now, now, action_policy.version,
                 json.dumps({
                     "source": {
                         "source_type": batch["source_type"],
                         "batch_key": batch.get("batch_key"),
                         "classification": SOURCE_CLASSIFICATIONS[batch["source_type"]],
                         "mapping_version": batch["mapping_version"],
                         "schema_profile": batch["schema_version"],
                     },
                     "detector_suite_version": DETECTOR_SUITE_VERSION,
                     "action_policy": action_policy.as_dict(),
                 }, sort_keys=True, separators=(",", ":"))),
            )
            event_type = "analysis_run_retry_created" if retry_of_run_id else "analysis_run_created"
            connection.execute(
                "INSERT INTO analysis_run_audit_events VALUES(?,?,?,?,?,?)",
                (f"evt_{uuid4().hex}", now, creator_user_id, event_type, run_id,
                 json.dumps({"batch_version": batch["batch_version"],
                             "action_policy_version": action_policy.version}, sort_keys=True)),
            )
        return run_id

    def finalize(self, run_id: str, status: str, *, creator_user_id: str,
                snapshot: Mapping[str, Any] | None, failure_category: str | None,
                action_policy: ActionPolicyConfig) -> None:
        if status not in TERMINAL_STATUSES:
            raise ValueError("Run status must be terminal.")
        now = utc_now()
        coverage = snapshot.get("indicator_coverage") if snapshot is not None else None
        scoring = snapshot.get("risk_scoring", {}) if snapshot is not None else {}
        priority = snapshot.get("audit_priority", {}) if snapshot is not None else {}
        serialized = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=_json_default) if snapshot is not None else None
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT execution_status,source_type,source_schema_version,source_mapping_version,configuration_json "
                "FROM analysis_runs WHERE run_id=?", (run_id,),
            ).fetchone()
            if row is None:
                raise RunInputError("RUN_NOT_FOUND")
            if row["execution_status"] != "running":
                raise RunInputError("RUN_TERMINAL")
            if snapshot is not None:
                config = _execution_configuration(snapshot, action_policy, row["source_type"])
            else:
                config = {
                    "source": {
                        "source_type": row["source_type"],
                        "classification": SOURCE_CLASSIFICATIONS[row["source_type"]],
                        "mapping_version": row["source_mapping_version"],
                        "schema_profile": row["source_schema_version"],
                    },
                    "detector_suite_version": DETECTOR_SUITE_VERSION,
                    "action_policy": action_policy.as_dict(),
                }
            # Keep the uploaded file name recorded when the run was created, so the run can be told apart.
            batch_key = ((_loads(row["configuration_json"]) or {}).get("source") or {}).get("batch_key")
            if batch_key:
                config["source"]["batch_key"] = batch_key
            if serialized is not None:
                connection.execute("INSERT INTO analysis_run_results(run_id,result_json) VALUES(?,?)", (run_id, serialized))
                # Derived from the stored text itself, in the same transaction.
                write_case_rows(connection, run_id, json.loads(serialized))
            connection.execute(
                "UPDATE analysis_runs SET completed_at=?,execution_status=?,failure_category=?,"
                "detector_suite_version=?,scoring_version=?,priority_version=?,configuration_json=?,"
                "coverage_summary_json=?,result_available=? WHERE run_id=?",
                (now, status, failure_category, config.get("detector_suite_version"),
                 scoring.get("version"), priority.get("priority_version"),
                 json.dumps(config, sort_keys=True, separators=(",", ":"), default=_json_default),
                 json.dumps(coverage, sort_keys=True, separators=(",", ":"), default=_json_default)
                 if coverage is not None else None, int(serialized is not None), run_id),
            )
            event_type = {"completed": "analysis_run_completed", "partial": "analysis_run_partial",
                          "failed": "analysis_run_failed"}[status]
            connection.execute(
                "INSERT INTO analysis_run_audit_events VALUES(?,?,?,?,?,?)",
                (f"evt_{uuid4().hex}", now, creator_user_id, event_type, run_id,
                 json.dumps({"failure_category": failure_category} if failure_category else {}, sort_keys=True)),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM analysis_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                return None
            # Shared read-only parse of the immutable stored snapshot (see run_results).
            result = stored_result(connection, run_id)
        return self._manifest(row, None if is_missing(result) else result)

    def get_run_view(self, run_id: str, *, view: str, case_id: str | None = None) -> dict[str, Any] | None:
        """Manifest plus a summary (``view="summary"``) or one-claim (``view="case"``) result.

        Runs stored with per-case rows are served from those rows without reading the full
        result; older runs fall back to views computed from their stored snapshot.
        ``result`` is None when the claim is not part of the run (case view).
        """
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM analysis_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                return None
            if has_case_rows(connection, run_id):
                result = stored_summary(connection, run_id) if view == "summary"                     else stored_case_view(connection, run_id, case_id)
                return {**self._manifest(row, result), "served_from": "case_rows"}
            stored = stored_result(connection, run_id)
        stored = None if is_missing(stored) else stored
        result = summary_view(stored) if view == "summary" else case_view(stored, case_id)
        return {**self._manifest(row, result), "served_from": "snapshot"}

    def calibration_inputs(self, run_id: str) -> dict[str, tuple[int, int | None]] | None:
        """Per flagged claim: specific rule findings (capped at 2) and the AI percentile bin (0–100), nothing else."""
        from app.analytics.action_policy import EXPLORATORY_INDICATORS

        with self._connection() as connection:
            if connection.execute("SELECT 1 FROM analysis_runs WHERE run_id=?", (run_id,)).fetchone() is None:
                raise RunInputError("RUN_NOT_FOUND")
            if not has_case_rows(connection, run_id):
                return None
            rows = connection.execute("SELECT case_id, case_json FROM analysis_run_cases WHERE run_id=?", (run_id,)).fetchall()
        inputs: dict[str, tuple[int, int | None]] = {}
        for case_id, case_json in rows:
            case = json.loads(case_json)
            specific = sum(1 for code in case.get("indicators") or [] if code not in EXPLORATORY_INDICATORS)
            ml = case.get("ml_anomaly") or {}
            percentile = ml.get("reference_percentile", ml.get("anomaly_percentile"))
            bin_ = int(percentile * 100) if isinstance(percentile, (int, float)) and not isinstance(percentile, bool) else None
            inputs[case_id] = (min(specific, 2), bin_)
        return inputs

    def get_case_page(self, run_id: str, *, reviews: dict | None, **query: Any) -> dict[str, Any] | None:
        """One page of flagged claims; None when the run has no stored case map."""
        with self._connection() as connection:
            if connection.execute("SELECT 1 FROM analysis_runs WHERE run_id=?", (run_id,)).fetchone() is None:
                raise RunInputError("RUN_NOT_FOUND")
            if has_case_rows(connection, run_id):
                return stored_case_page(connection, run_id, reviews_visible=reviews is not None, **query)
            stored = stored_result(connection, run_id)
        return case_page(None if is_missing(stored) else stored, reviews=reviews, **query)

    def list_runs(self, limit: int, offset: int, batch_id: str | None = None, archived: bool = False) -> dict[str, Any]:
        where = f" WHERE run_id {'IN' if archived else 'NOT IN'} (SELECT run_id FROM analysis_run_archives)"
        where += " AND batch_id=?" if batch_id is not None else ""
        args: tuple[Any, ...] = (batch_id,) if batch_id is not None else ()
        with self._connection() as connection:
            total = connection.execute("SELECT COUNT(*) FROM analysis_runs" + where, args).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM analysis_runs" + where + " ORDER BY created_at DESC,run_id DESC LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
        return {"items": [self._manifest(row) for row in rows], "total_items": total}

    def archive_run(self, run_id: str, actor_user_id: str) -> None:
        """Hide a finished run from the history; its result, reviews and audit records stay intact."""
        with self._connection() as connection:
            row = connection.execute("SELECT execution_status FROM analysis_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise RunInputError("RUN_NOT_FOUND")
            if row["execution_status"] == "running":
                raise RunInputError("RUN_STILL_RUNNING")
            if connection.execute("SELECT 1 FROM analysis_run_archives WHERE run_id=?", (run_id,)).fetchone() is None:
                now = utc_now()
                connection.execute("INSERT INTO analysis_run_archives VALUES (?, ?, ?)", (run_id, now, actor_user_id))
                connection.execute("INSERT INTO analysis_run_audit_events VALUES (?, ?, ?, 'run_archived', ?, ?)",
                                   (f"evt_{uuid4().hex}", now, actor_user_id, run_id, "{}"))

    def restore_run(self, run_id: str, actor_user_id: str) -> None:
        """Show an archived run in the history again."""
        with self._connection() as connection:
            if connection.execute("SELECT 1 FROM analysis_runs WHERE run_id=?", (run_id,)).fetchone() is None:
                raise RunInputError("RUN_NOT_FOUND")
            if connection.execute("DELETE FROM analysis_run_archives WHERE run_id=?", (run_id,)).rowcount:
                connection.execute("INSERT INTO analysis_run_audit_events VALUES (?, ?, ?, 'run_restored', ?, ?)",
                                   (f"evt_{uuid4().hex}", utc_now(), actor_user_id, run_id, "{}"))


def create_analysis_run(db_path: str | Path, batch_id: str | None, creator_user_id: str,
                        retry_of_run_id: str | None = None,
                        action_policy: ActionPolicyConfig | None = None,
                        *, source_type: str = "synthetic_csv") -> dict[str, Any]:
    """Pin a ready batch, run the coordinated service once, then persist a terminal snapshot.

    ``bpjs_fkrtl_local`` reads the server-configured sample instead of a stored
    batch; ``batch_id`` is not accepted for it because the path is never
    request-selected.
    """
    if source_type not in SOURCE_CLASSIFICATIONS:
        raise RunInputError("RUN_SOURCE_UNSUPPORTED")
    store = AnalysisRunStore(db_path)
    if retry_of_run_id is not None:
        prior = store.get_run(retry_of_run_id)
        if prior is None:
            raise RunInputError("RETRY_RUN_NOT_FOUND")
        if prior["source_type"] != source_type:
            raise RunInputError("RUN_SOURCE_BATCH_MISMATCH")
        if batch_id is not None and batch_id != prior["batch_id"]:
            raise RunInputError("RETRY_BATCH_MISMATCH")
        batch_id = prior["batch_id"]
        if action_policy is None:
            prior_policy = (prior.get("configuration") or {}).get("action_policy")
            if isinstance(prior_policy, Mapping):
                action_policy = ActionPolicyConfig(**prior_policy)
    action_policy = action_policy or get_action_policy_config()
    if source_type == FKRTL_SOURCE_TYPE:
        return _create_fkrtl_local_run(store, db_path, batch_id, creator_user_id, retry_of_run_id, action_policy)
    if not batch_id:
        raise RunInputError("BATCH_ID_REQUIRED")

    try:
        execution_input = BatchStore(db_path).get_execution_input(batch_id)
    except BatchStorageError as exc:
        raise RunStorageError("Penyimpanan batch lokal tidak tersedia.") from exc
    if execution_input is None:
        raise RunInputError("BATCH_NOT_FOUND")
    batch = execution_input["batch"]
    if batch.get("source_type") != source_type:
        raise RunInputError("RUN_SOURCE_BATCH_MISMATCH")
    if batch["status"] not in {"ready", "ready_with_warnings"}:
        raise RunInputError("BATCH_NOT_RUNNABLE")
    if len(execution_input["records"]) != batch.get("row_count"):
        raise RunInputError("BATCH_RECORD_COUNT_MISMATCH")
    earlier: list[dict[str, Any]] = []
    if batch.get("schema_version") == BPJS_CSV_SCHEMA_VERSION:
        dates = sorted(str(record.get("service_date")) for record in execution_input["records"] if record.get("service_date"))
        if dates:
            start = (date.fromisoformat(dates[0]) - timedelta(days=LOOKBACK_DAYS)).isoformat()
            try:
                earlier = BatchStore(db_path).earlier_records(batch["batch_id"], start, dates[-1])
            except BatchStorageError as exc:
                raise RunStorageError("Penyimpanan batch lokal tidak tersedia.") from exc
    run_id = store.create_running(batch, creator_user_id, retry_of_run_id, action_policy)
    return _execute_and_persist(
        store, run_id, SyntheticBatchProvider(batch, execution_input["records"], earlier),
        creator_user_id, action_policy,
    )


def _create_fkrtl_local_run(store: AnalysisRunStore, db_path: str | Path, retry_batch_id: str | None,
                            creator_user_id: str, retry_of_run_id: str | None,
                            action_policy: ActionPolicyConfig) -> dict[str, Any]:
    """Read the configured FKRTL sample, register metadata-only batch, then run."""
    if retry_of_run_id is None and retry_batch_id is not None:
        raise RunInputError("RUN_SOURCE_BATCH_MISMATCH")
    # Raises FkrtlSourceUnavailable (safe, actionable) before any run is created.
    loaded = load_fkrtl_local_source()
    validation = {
        "error_count": 0, "error_counts": {}, "errors": [], "errors_truncated": False,
        "row_count": loaded.row_count,
        "warning_counts": ({"invalid_service_date": loaded.invalid_service_date_count}
                           if loaded.invalid_service_date_count else {}),
        "selection": loaded.selection,
        "fingerprint_basis": "file_size_mtime_date_window_row_cap_mapping",
        "rows_stored": 0,
    }
    try:
        batch, _reused = BatchStore(db_path).register_local_source(
            source_type=FKRTL_SOURCE_TYPE, batch_key=FKRTL_BATCH_KEY,
            schema_version=FKRTL_SCHEMA_PROFILE,
            mapping_version=str(loaded.dataset.source_metadata["mapping_version"]),
            content_fingerprint=loaded.content_fingerprint, row_count=loaded.row_count,
            validation_summary=validation, creator_user_id=creator_user_id,
        )
    except BatchStorageError as exc:
        raise RunStorageError("Penyimpanan batch lokal tidak tersedia.") from exc
    if retry_batch_id is not None and batch["batch_id"] != retry_batch_id:
        # The configured file or row window changed since the failed run.
        raise RunInputError("RETRY_BATCH_MISMATCH")
    batch["content_checksum"] = loaded.content_fingerprint
    run_id = store.create_running(batch, creator_user_id, retry_of_run_id, action_policy)
    return _execute_and_persist(store, run_id, _PreloadedProvider(loaded.dataset), creator_user_id, action_policy)


def _execute_and_persist(store: AnalysisRunStore, run_id: str, provider: Any, creator_user_id: str,
                         action_policy: ActionPolicyConfig) -> dict[str, Any]:
    try:
        dataset, snapshot = execute_provider_snapshot(provider, action_policy)
        snapshot = _compact_snapshot(_safe_snapshot(snapshot, list(dataset.records)))
        status = snapshot.get("execution_status")
        if status not in TERMINAL_STATUSES:
            raise RuntimeError("Invalid pipeline execution status")
        failure = "ALL_DETECTORS_UNAVAILABLE" if status == "failed" else None
    except BatchAdapterError:
        snapshot = None
        status = "failed"
        failure = "BATCH_ADAPTER_REJECTED"
    except Exception:
        snapshot = None
        status = "failed"
        failure = "PIPELINE_EXECUTION_FAILED"

    store.finalize(run_id, status, creator_user_id=creator_user_id,
                   snapshot=snapshot, failure_category=failure, action_policy=action_policy)
    if status != "failed":
        # Daily continuity: the same claim keeps its review decision in this new analysis.
        try:
            from app.services.run_reviews import RunReviewStore
            RunReviewStore(store.path).carry_over(run_id)
        except Exception:
            logging.getLogger("cir.runs").warning("Review carry-over failed for a run; the run itself is stored.")
        # A new analysis of the same file or window replaces the earlier ones in the lists.
        try:
            from app.services.retention import supersede_earlier_runs
            supersede_earlier_runs(store.path, run_id)
        except Exception:
            logging.getLogger("cir.runs").warning("Archiving superseded runs failed; the run itself is stored.")
    persisted = store.get_run(run_id)
    if persisted is None:
        raise RunStorageError("AnalysisRun tidak dapat dibaca setelah penyimpanan.")
    if status == "failed":
        raise RunExecutionError(run_id)
    return persisted
