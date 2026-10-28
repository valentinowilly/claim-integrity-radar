"""Read views over a stored AnalysisRun result: summary, paged candidates and one case.

Every view is computed from the persisted snapshot; nothing here runs detectors,
scoring or ML inference. Terminal results are immutable (SQLite triggers reject
updates and deletes), so a parsed result can be cached per database and run and
shared read-only between requests: callers must never mutate what they receive.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
import json
import sqlite3
import threading
from typing import Any

from app.db import UndefinedTable, cache_key, is_missing_table, table_exists

_CACHE_SIZE = 2  # a large FKRTL result parses to a few hundred MB; keep at most two
_cache: OrderedDict[tuple[str, str], Any] = OrderedDict()
_lock = threading.Lock()
_MISSING = object()

# "stored" keeps the snapshot's own case order (as the full result lists them).
SORT_KEYS = ("rule_index", "checks", "similarity_rarity", "ml_rank", "review_updated", "case_ref", "stored")
PREVIEW_SIZE = 5
REASON_SUMMARIES_PER_INDICATOR = 5
MAX_PAGE_SIZE = 100


def _database_path(connection: sqlite3.Connection) -> str:
    return cache_key(connection)


def stored_result(connection: sqlite3.Connection, run_id: str) -> Any:
    """Parsed ``result_json`` of a run, or the module sentinel ``MISSING`` when no row exists."""
    key = (_database_path(connection), run_id)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    row = connection.execute("SELECT result_json FROM analysis_run_results WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        return _MISSING
    value = json.loads(row[0]) if row[0] is not None else None
    with _lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return value


def is_missing(value: Any) -> bool:
    return value is _MISSING


def _has_cases(result: Any) -> bool:
    return isinstance(result, Mapping) and isinstance(result.get("cases"), Mapping)


def _listed_case_ids(result: Mapping[str, Any]) -> set[str]:
    ml = result.get("ml_anomaly") if isinstance(result.get("ml_anomaly"), Mapping) else {}
    los = result.get("length_of_stay") if isinstance(result.get("length_of_stay"), Mapping) else {}
    return {item.get("case_id") for item in [*(ml.get("items") or []), *(los.get("candidates") or [])]
            if isinstance(item, Mapping)}


def _scoped(result: Mapping[str, Any], case_ids: list[str], view: dict[str, Any]) -> dict[str, Any]:
    """Shallow copy of the result whose per-case maps hold only ``case_ids``; the rest is shared."""
    cases = result["cases"]
    policy = result.get("action_policy")
    scoped = {**result, "cases": {case_id: cases[case_id] for case_id in case_ids if case_id in cases},
              "result_view": view}
    if isinstance(policy, Mapping) and isinstance(policy.get("cases"), Mapping):
        lanes = policy["cases"]
        scoped["action_policy"] = {**policy, "cases": {case_id: lanes[case_id] for case_id in case_ids if case_id in lanes}}
    return scoped


def summary_view(result: Any) -> Any:
    """Run result without per-case objects; counts and lists that the pages need are precomputed.

    ``cases`` is empty in this view; ``result_view.case_count`` is the number of flagged
    claims, so an empty map is never a negative result. Results without a case map
    (failed or legacy shapes) are returned unchanged.
    """
    if not _has_cases(result):
        return result
    cases = result["cases"]
    order = list(cases)
    listed = _listed_case_ids(result)
    summaries: dict[str, list[str]] = {}
    for case in cases.values():
        for reason in case.get("reasons") or []:
            code, text = reason.get("indicator"), reason.get("summary")
            bucket = summaries.setdefault(code, [])
            if isinstance(text, str) and len(bucket) < REASON_SUMMARIES_PER_INDICATOR and text not in bucket:
                bucket.append(text)
    preview = order[:PREVIEW_SIZE]
    view = _scoped(result, [], {
        "kind": "summary",
        "case_count": len(order),
        "case_preview": [cases[case_id] for case_id in preview],
        "case_preview_lanes": {case_id: lane for case_id, lane in
                               ((result.get("action_policy") or {}).get("cases") or {}).items() if case_id in preview},
        # Which ML-ranked or duration-screen claims are also rule-flagged (those lists stay complete).
        "rule_flagged_listed_case_ids": sorted(case_id for case_id in listed if case_id in cases),
        "indicator_reason_summaries": summaries,
    })
    return view


def case_view(result: Any, case_id: str) -> dict[str, Any] | None:
    """Result scoped to one claim (rule case, ML-ranked item or duration candidate), or None."""
    if not _has_cases(result):
        return None
    cases = result["cases"]
    if case_id not in cases and case_id not in _listed_case_ids(result):
        return None
    scoped = _scoped(result, [case_id], {"kind": "case", "case_id": case_id, "case_count": len(cases)})
    ml = result.get("ml_anomaly")
    if isinstance(ml, Mapping) and isinstance(ml.get("items"), list):
        scoped["ml_anomaly"] = {**ml, "items": [item for item in ml["items"]
                                               if isinstance(item, Mapping) and item.get("case_id") == case_id]}
    los = result.get("length_of_stay")
    if isinstance(los, Mapping) and isinstance(los.get("candidates"), list):
        scoped["length_of_stay"] = {**los, "candidates": [item for item in los["candidates"]
                                                          if isinstance(item, Mapping) and item.get("case_id") == case_id]}
    return scoped


def _sort_value(case: Mapping[str, Any], sort: str, reviews: Mapping[str, Mapping[str, Any]]) -> Any:
    if sort == "rule_index":
        return None if case.get("risk_score") is None else -case["risk_score"]
    if sort == "checks":
        return -len(case.get("indicators") or [])
    if sort == "ml_rank":
        return (case.get("ml_anomaly") or {}).get("rank")
    if sort == "similarity_rarity":
        expected = [reason["supporting_values"]["expected_chance_pairs"] for reason in case.get("reasons") or []
                    if reason.get("indicator") == "near_duplicate_claim_candidate"
                    and isinstance((reason.get("supporting_values") or {}).get("expected_chance_pairs"), (int, float))]
        return min(expected) if expected else None
    if sort == "review_updated":
        return (reviews.get(case["case_id"]) or {}).get("updated_at")
    return None


def case_page(
    result: Any, *, sort: str = "rule_index", offset: int = 0, limit: int = 10, indicator: str | None = None,
    search: str | None = None, review_filter: str | None = None, reviews: Mapping[str, Mapping[str, Any]] | None = None,
    lane: str | None = None, only_case_ids: set[str] | None = None, except_case_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    """One page of rule-flagged claims; the same order and filters as the review queue.

    Missing sort values go last; ties fall back to the case reference. ``review_updated``
    sorts the most recent first. ``reviews`` maps case IDs to their review state.
    """
    if not _has_cases(result):
        return None
    loaded_reviews = reviews is not None
    reviews = reviews or {}
    cases = result["cases"]
    needle = (search or "").strip().lower()
    selected = []
    for case_id, case in cases.items():
        if indicator and indicator not in (case.get("indicators") or []):
            continue
        if needle and needle not in case_id.lower():
            continue
        if (only_case_ids is not None and case_id not in only_case_ids) or (except_case_ids and case_id in except_case_ids):
            continue
        if lane and ((result.get("action_policy") or {}).get("cases") or {}).get(case_id, {}).get("lane") != lane:
            continue
        if review_filter:
            review = reviews.get(case_id)
            if review_filter == "not_started" and review:
                continue
            if review_filter == "has_outcome" and not (review or {}).get("review_outcome"):
                continue
            if review_filter not in ("not_started", "has_outcome") \
                    and (review or {}).get("review_status", "pending_review") != review_filter:
                continue
        selected.append(case_id)
    if sort == "stored":
        ordered = selected
    else:
        present = [case_id for case_id in selected if _sort_value(cases[case_id], sort, reviews) is not None]
        absent = sorted(case_id for case_id in selected if _sort_value(cases[case_id], sort, reviews) is None)
        present.sort()  # stable tie-break by case reference
        present.sort(key=lambda case_id: _sort_value(cases[case_id], sort, reviews), reverse=sort == "review_updated")
        ordered = present + absent
    lanes = (result.get("action_policy") or {}).get("cases") or {}
    window = ordered[offset:offset + limit]
    return {
        "items": [{"case": cases[case_id], "lane": lanes.get(case_id)} for case_id in window],
        "total_matching": len(ordered),
        "total_cases": len(cases),
        "reviewed_case_count": sum(case_id in reviews for case_id in cases) if loaded_reviews else None,
        "offset": offset, "limit": limit, "sort": sort,
    }


# --- Per-case storage -------------------------------------------------------------------------
# Runs persisted with this layer also store one row per rule-flagged claim and a precomputed
# summary, written in the same transaction as the immutable result and protected by the same
# kind of triggers. Reads then never parse the full result. Runs stored before it have no rows
# and use the snapshot-based views above (``has_case_rows`` is False).
VIEW_VERSION = "run-case-rows-v1"
CASE_ROWS_SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_run_result_views (
    run_id TEXT PRIMARY KEY REFERENCES analysis_runs(run_id),
    view_version TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    listed_case_ids_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_run_cases (
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id),
    position INTEGER NOT NULL,
    case_id TEXT NOT NULL,
    case_json TEXT NOT NULL,
    lane_json TEXT,
    indicators TEXT NOT NULL,
    sort_rule_index REAL,
    sort_checks INTEGER NOT NULL,
    sort_ml_rank REAL,
    sort_similarity_rarity REAL,
    PRIMARY KEY (run_id, case_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_run_cases_position ON analysis_run_cases(run_id, position);
CREATE INDEX IF NOT EXISTS idx_run_cases_rule_index ON analysis_run_cases(run_id, sort_rule_index, case_id);
CREATE INDEX IF NOT EXISTS idx_run_cases_checks ON analysis_run_cases(run_id, sort_checks, case_id);
CREATE INDEX IF NOT EXISTS idx_run_cases_ml_rank ON analysis_run_cases(run_id, sort_ml_rank, case_id);
CREATE INDEX IF NOT EXISTS idx_run_cases_similarity ON analysis_run_cases(run_id, sort_similarity_rarity, case_id);
CREATE TRIGGER IF NOT EXISTS analysis_run_views_insert_guard
BEFORE INSERT ON analysis_run_result_views
WHEN NOT EXISTS (SELECT 1 FROM analysis_run_results WHERE run_id=NEW.run_id)
BEGIN SELECT RAISE(ABORT, 'result views need a stored result'); END;
CREATE TRIGGER IF NOT EXISTS analysis_run_views_no_update
BEFORE UPDATE ON analysis_run_result_views
BEGIN SELECT RAISE(ABORT, 'AnalysisRun result is immutable'); END;
DROP TRIGGER IF EXISTS analysis_run_views_no_delete_v2;
CREATE TRIGGER IF NOT EXISTS analysis_run_views_no_delete
BEFORE DELETE ON analysis_run_result_views
BEGIN SELECT RAISE(ABORT, 'AnalysisRun result is immutable'); END;
CREATE TRIGGER IF NOT EXISTS analysis_run_cases_insert_guard
BEFORE INSERT ON analysis_run_cases
WHEN NOT EXISTS (SELECT 1 FROM analysis_run_results WHERE run_id=NEW.run_id)
  OR EXISTS (SELECT 1 FROM analysis_run_result_views WHERE run_id=NEW.run_id)
BEGIN SELECT RAISE(ABORT, 'case rows are written once, with the stored result'); END;
CREATE TRIGGER IF NOT EXISTS analysis_run_cases_no_update
BEFORE UPDATE ON analysis_run_cases
BEGIN SELECT RAISE(ABORT, 'AnalysisRun result is immutable'); END;
DROP TRIGGER IF EXISTS analysis_run_cases_no_delete_v2;
CREATE TRIGGER IF NOT EXISTS analysis_run_cases_no_delete
BEFORE DELETE ON analysis_run_cases
BEGIN SELECT RAISE(ABORT, 'AnalysisRun result is immutable'); END;
"""


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def write_case_rows(connection: sqlite3.Connection, run_id: str, stored: Any) -> bool:
    """Write the per-case rows and summary of ``stored`` (the parsed stored result).

    Case rows go first: their trigger refuses rows once a view row exists, so they are
    written exactly once. Returns False for results without a case map (nothing written).
    """
    if not _has_cases(stored):
        return False
    lanes = (stored.get("action_policy") or {}).get("cases") or {}
    connection.executemany(
        "INSERT INTO analysis_run_cases(run_id,position,case_id,case_json,lane_json,indicators,"
        "sort_rule_index,sort_checks,sort_ml_rank,sort_similarity_rarity) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ((run_id, position, case_id, _dumps(case),
          _dumps(lanes[case_id]) if case_id in lanes else None,
          "|" + "|".join(case.get("indicators") or []) + "|",
          _sort_value(case, "rule_index", {}), _sort_value(case, "checks", {}),
          _sort_value(case, "ml_rank", {}), _sort_value(case, "similarity_rarity", {}))
         for position, (case_id, case) in enumerate(stored["cases"].items())),
    )
    connection.execute(
        "INSERT INTO analysis_run_result_views(run_id,view_version,summary_json,listed_case_ids_json) VALUES (?,?,?,?)",
        (run_id, VIEW_VERSION, _dumps(summary_view(stored)),
         _dumps(sorted(case_id for case_id in _listed_case_ids(stored) if case_id))),
    )
    return True


def has_case_rows(connection: sqlite3.Connection, run_id: str) -> bool:
    try:
        return connection.execute(
            "SELECT 1 FROM analysis_run_result_views WHERE run_id=?", (run_id,)).fetchone() is not None
    except UndefinedTable as exc:
        if is_missing_table(exc):
            return False
        raise


def stored_summary(connection: sqlite3.Connection, run_id: str) -> Any:
    row = connection.execute("SELECT summary_json FROM analysis_run_result_views WHERE run_id=?", (run_id,)).fetchone()
    return json.loads(row[0]) if row else None


def stored_case_view(connection: sqlite3.Connection, run_id: str, case_id: str) -> dict[str, Any] | None:
    """Case view from the rows: the stored summary scoped to one claim plus its case and lane."""
    views = connection.execute(
        "SELECT summary_json, listed_case_ids_json FROM analysis_run_result_views WHERE run_id=?", (run_id,)).fetchone()
    if views is None:
        return None
    row = connection.execute("SELECT case_json, lane_json FROM analysis_run_cases WHERE run_id=? AND case_id=?",
                             (run_id, case_id)).fetchone()
    if row is None and case_id not in json.loads(views[1]):
        return None
    summary = json.loads(views[0])
    case_count = summary.pop("result_view")["case_count"]
    summary["cases"] = {case_id: json.loads(row[0])} if row else {}
    policy = summary.get("action_policy")
    if isinstance(policy, dict):
        summary["action_policy"] = {**policy, "cases": {case_id: json.loads(row[1])} if row and row[1] else {}}
    scoped = case_view(summary, case_id)
    scoped["result_view"] = {"kind": "case", "case_id": case_id, "case_count": case_count}
    return scoped


def stored_case_is_listed(connection: sqlite3.Connection, run_id: str, case_id: str) -> bool:
    """Whether a claim is part of the run's stored result (rule case, ML item or duration candidate)."""
    if connection.execute("SELECT 1 FROM analysis_run_cases WHERE run_id=? AND case_id=?",
                          (run_id, case_id)).fetchone():
        return True
    row = connection.execute("SELECT listed_case_ids_json FROM analysis_run_result_views WHERE run_id=?",
                             (run_id,)).fetchone()
    return bool(row) and case_id in json.loads(row[0])


# Same order as ``case_page``: missing values last, ties by case reference (BINARY collation
# orders ASCII case references like Python strings), review_updated most recent first.
_SQL_ORDER = {
    "rule_index": "c.sort_rule_index IS NULL, c.sort_rule_index, c.case_id",
    "checks": "c.sort_checks, c.case_id",
    "ml_rank": "c.sort_ml_rank IS NULL, c.sort_ml_rank, c.case_id",
    "similarity_rarity": "c.sort_similarity_rarity IS NULL, c.sort_similarity_rarity, c.case_id",
    "review_updated": "r.updated_at IS NULL, r.updated_at DESC, c.case_id",
    "case_ref": "c.case_id",
    "stored": "c.position",
}


def _review_table_exists(connection: sqlite3.Connection) -> bool:
    return table_exists(connection, "run_case_reviews")


def stored_case_page(
    connection: sqlite3.Connection, run_id: str, *, sort: str = "rule_index", offset: int = 0, limit: int = 10,
    indicator: str | None = None, search: str | None = None, review_filter: str | None = None,
    reviews_visible: bool = False, lane: str | None = None,
    only_case_ids: set[str] | None = None, except_case_ids: set[str] | None = None,
) -> dict[str, Any]:
    """The same page as ``case_page`` (order, filters, counts), computed in SQL over the case rows."""
    reviews = _review_table_exists(connection)
    join = ("LEFT JOIN run_case_reviews r ON r.run_id=c.run_id AND r.case_id=c.case_id" if reviews else
            "LEFT JOIN (SELECT NULL AS case_id, NULL AS review_status, NULL AS review_outcome, "
            "NULL AS updated_at) r ON 0")
    where, params = ["c.run_id=?"], [run_id]
    if indicator:
        where.append("instr(c.indicators, ?) > 0")
        params.append(f"|{indicator}|")
    if search and search.strip():
        where.append("instr(lower(c.case_id), ?) > 0")
        params.append(search.strip().lower())
    if lane:
        where.append("instr(c.lane_json, ?) > 0")
        params.append(f'"lane":"{lane}"')
    if only_case_ids is not None:
        chosen = sorted(only_case_ids) or [""]
        where.append("c.case_id IN (" + ",".join("?" * len(chosen)) + ")")
        params.extend(chosen)
    if except_case_ids:
        left_out = sorted(except_case_ids)
        where.append("c.case_id NOT IN (" + ",".join("?" * len(left_out)) + ")")
        params.extend(left_out)
    if review_filter == "not_started":
        where.append("r.case_id IS NULL")
    elif review_filter == "has_outcome":
        where.append("r.review_outcome IS NOT NULL")
    elif review_filter:
        where.append("COALESCE(r.review_status, 'pending_review') = ?")
        params.append(review_filter)
    clause = " AND ".join(where)
    total_matching = connection.execute(
        f"SELECT COUNT(*) FROM analysis_run_cases c {join} WHERE {clause}", params).fetchone()[0]
    rows = connection.execute(
        f"SELECT c.case_json, c.lane_json FROM analysis_run_cases c {join} WHERE {clause} "
        f"ORDER BY {_SQL_ORDER[sort]} LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
    total_cases = connection.execute(
        "SELECT COUNT(*) FROM analysis_run_cases WHERE run_id=?", (run_id,)).fetchone()[0]
    reviewed = None
    if reviews_visible:
        reviewed = connection.execute(
            "SELECT COUNT(*) FROM analysis_run_cases c JOIN run_case_reviews r "
            "ON r.run_id=c.run_id AND r.case_id=c.case_id WHERE c.run_id=?", (run_id,)).fetchone()[0] if reviews else 0
    return {
        "items": [{"case": json.loads(case_json), "lane": json.loads(lane_json) if lane_json else None}
                  for case_json, lane_json in rows],
        "total_matching": total_matching, "total_cases": total_cases, "reviewed_case_count": reviewed,
        "offset": offset, "limit": limit, "sort": sort,
    }
