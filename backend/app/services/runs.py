"""Persistent, immutable analysis-run execution over ready synthetic batches."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator
from uuid import uuid4

from app.analytics.action_policy import ActionPolicyConfig, evaluate_action_policy, get_action_policy_config
from app.analytics.audit_priority import AuditEffortConfig
from app.analytics.batch_adapter import BatchAdapterError, adapt_batch_features
from app.analytics.capacity import CapacityConfig
from app.analytics.evidence_completeness import DEFAULT_REQUIRED_EVIDENCE
from app.analytics.near_duplicate_claims import NearDuplicateConfig
from app.analytics.risk_scoring import DETECTOR_ORDER, DETECTOR_SUITE_VERSION
from app.analytics.temporal_patterns import TemporalConfig
from app.services.analytics import build_analytics_snapshot
from app.services.batches import BatchStorageError, BatchStore


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
SYNTHETIC_BATCH_SOURCE = {"kind": "synthetic", "label": "synthetic_data_batch"}


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


def _safe_snapshot(snapshot: Mapping[str, Any], features: list[dict[str, Any]]) -> dict[str, Any]:
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

    def clean(value: Any, parent_key: str = "") -> Any:
        if isinstance(value, Mapping):
            return {key: clean(item, str(key)) for key, item in value.items()
                    if str(key) not in forbidden_keys}
        if isinstance(value, (list, tuple)):
            items = list(value)
            if parent_key in {"matched_attributes", "differing_attributes"}:
                items = [item for item in items if item not in ("participant_token", "PSTV01")]
            return [clean(item, parent_key) for item in items]
        if isinstance(value, str) and any(token in value for token in sensitive_values):
            raise ValueError("Sensitive value detected in analysis output.")
        return value

    return clean(snapshot)


def _execution_configuration(snapshot: Mapping[str, Any], action_policy: ActionPolicyConfig) -> dict[str, Any]:
    priority = snapshot.get("audit_priority", {})
    scoring = snapshot.get("risk_scoring", {})
    return {
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
    }


class AnalysisRunStore:
    """SQLite run manifest and result store sharing the immutable batch database."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=20)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(
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
                CREATE TRIGGER IF NOT EXISTS analysis_run_result_delete_guard
                BEFORE DELETE ON analysis_run_results
                BEGIN SELECT RAISE(ABORT, 'AnalysisRun result is immutable'); END;
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(analysis_runs)")}
            if "action_policy_version" not in columns:
                connection.execute("ALTER TABLE analysis_runs ADD COLUMN action_policy_version TEXT")
            yield connection
            connection.commit()
        except (OSError, sqlite3.Error) as exc:
            if connection is not None:
                connection.rollback()
            raise RunStorageError("Penyimpanan AnalysisRun lokal tidak tersedia.") from exc
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _manifest(row: sqlite3.Row, result: Any = None) -> dict[str, Any]:
        return {
            "run_id": row["run_id"], "batch_id": row["batch_id"],
            "batch_version": row["batch_version"], "content_checksum": row["content_checksum"],
            "source_type": row["source_type"],
            "source_schema_version": row["source_schema_version"],
            "source_mapping_version": row["source_mapping_version"],
            "creator_user_id": row["creator_user_id"], "retry_of_run_id": row["retry_of_run_id"],
            "created_at": row["created_at"], "started_at": row["started_at"],
            "completed_at": row["completed_at"], "execution_status": row["execution_status"],
            "failure_category": row["failure_category"],
            "detector_suite_version": row["detector_suite_version"],
            "scoring_version": row["scoring_version"], "priority_version": row["priority_version"],
            "action_policy_version": row["action_policy_version"],
            "configuration": _loads(row["configuration_json"]),
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
                 json.dumps({"detector_suite_version": DETECTOR_SUITE_VERSION,
                             "action_policy": action_policy.as_dict()}, sort_keys=True, separators=(",", ":"))),
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
        config = _execution_configuration(snapshot, action_policy) if snapshot is not None else {
            "detector_suite_version": DETECTOR_SUITE_VERSION,
            "action_policy": action_policy.as_dict(),
        }
        scoring = snapshot.get("risk_scoring", {}) if snapshot is not None else {}
        priority = snapshot.get("audit_priority", {}) if snapshot is not None else {}
        serialized = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=_json_default) if snapshot is not None else None
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT execution_status FROM analysis_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise RunInputError("RUN_NOT_FOUND")
            if row["execution_status"] != "running":
                raise RunInputError("RUN_TERMINAL")
            if serialized is not None:
                connection.execute("INSERT INTO analysis_run_results(run_id,result_json) VALUES(?,?)", (run_id, serialized))
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
            result_row = connection.execute(
                "SELECT result_json FROM analysis_run_results WHERE run_id=?", (run_id,)
            ).fetchone()
        return self._manifest(row, _loads(result_row["result_json"]) if result_row else None)

    def list_runs(self, limit: int, offset: int, batch_id: str | None = None) -> dict[str, Any]:
        where = " WHERE batch_id=?" if batch_id is not None else ""
        args: tuple[Any, ...] = (batch_id,) if batch_id is not None else ()
        with self._connection() as connection:
            total = connection.execute("SELECT COUNT(*) FROM analysis_runs" + where, args).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM analysis_runs" + where + " ORDER BY created_at DESC,run_id DESC LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
        return {"items": [self._manifest(row) for row in rows], "total_items": total}


def create_analysis_run(db_path: str | Path, batch_id: str | None, creator_user_id: str,
                        retry_of_run_id: str | None = None,
                        action_policy: ActionPolicyConfig | None = None) -> dict[str, Any]:
    """Pin a ready batch, run the coordinated service once, then persist a terminal snapshot."""
    store = AnalysisRunStore(db_path)
    if retry_of_run_id is not None:
        prior = store.get_run(retry_of_run_id)
        if prior is None:
            raise RunInputError("RETRY_RUN_NOT_FOUND")
        if batch_id is not None and batch_id != prior["batch_id"]:
            raise RunInputError("RETRY_BATCH_MISMATCH")
        batch_id = prior["batch_id"]
        if action_policy is None:
            prior_policy = (prior.get("configuration") or {}).get("action_policy")
            if isinstance(prior_policy, Mapping):
                action_policy = ActionPolicyConfig(**prior_policy)
    action_policy = action_policy or get_action_policy_config()
    if not batch_id:
        raise RunInputError("BATCH_ID_REQUIRED")

    try:
        execution_input = BatchStore(db_path).get_execution_input(batch_id)
    except BatchStorageError as exc:
        raise RunStorageError("Penyimpanan batch lokal tidak tersedia.") from exc
    if execution_input is None:
        raise RunInputError("BATCH_NOT_FOUND")
    batch = execution_input["batch"]
    if batch["status"] not in {"ready", "ready_with_warnings"}:
        raise RunInputError("BATCH_NOT_RUNNABLE")
    if len(execution_input["records"]) != batch.get("row_count"):
        raise RunInputError("BATCH_RECORD_COUNT_MISMATCH")
    run_id = store.create_running(batch, creator_user_id, retry_of_run_id, action_policy)

    try:
        features, facilities = adapt_batch_features(batch, execution_input["records"])
        snapshot = build_analytics_snapshot(
            records=features, facilities=facilities, data_source=SYNTHETIC_BATCH_SOURCE,
        )
        snapshot = _safe_snapshot(snapshot, features)
        snapshot["action_policy"] = evaluate_action_policy(snapshot, action_policy)
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
    persisted = store.get_run(run_id)
    if persisted is None:
        raise RunStorageError("AnalysisRun tidak dapat dibaca setelah penyimpanan.")
    if status == "failed":
        raise RunExecutionError(run_id)
    return persisted
