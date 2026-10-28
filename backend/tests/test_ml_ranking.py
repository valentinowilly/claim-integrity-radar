"""Phase 3: ML ranking ties, key/order invariance, and separation from rule risk (synthetic only)."""

import random

import pytest

pytest.importorskip("sklearn")

from app.analytics.ml_anomaly import build_ml_anomaly_ranking  # noqa: E402
from app.data_sources.providers import FeatureDataset  # noqa: E402
from app.services import analytics as analytics_service  # noqa: E402
from tests.test_ml_anomaly import _records  # noqa: E402
from tests.test_near_duplicate_allocation import _relabel  # noqa: E402


def test_identical_records_share_a_competition_rank_and_report_ties():
    records = _records(count=60, unusual=("case_unusual_1",))
    for row in records[:60]:  # make the 60 normal records exactly identical
        row.update({key: records[0][key] for key in records[0] if key not in {"case_id", "participant_token"}})
    _summary, ranks = build_ml_anomaly_ranking(records)
    normal = [ranks[row["case_id"]] for row in records[:60]]
    assert {item["rank"] for item in normal} == {2}  # one shared rank after the outlier
    assert {item["tie_count"] for item in normal} == {60}
    assert ranks["case_unusual_1"]["rank"] == 1 and ranks["case_unusual_1"]["tie_count"] == 1


def test_presentation_order_among_ties_does_not_change_rank():
    summary, _ = build_ml_anomaly_ranking(_records())
    items = summary["items"]
    assert [item["rank"] for item in items] == sorted(item["rank"] for item in items)
    for item in items:
        tied = [other for other in items if other["rank"] == item["rank"]]
        assert {other["anomaly_score"] for other in tied} == {item["anomaly_score"]}


def _by_original(ranks, back=None):
    back = back or {}
    return {back.get(case_id, case_id): (item["rank"], item["tie_count"], item["anomaly_score"])
            for case_id, item in ranks.items()}


# More rows than IsolationForest max_samples (256): each tree subsamples by row
# index, which is where input order used to leak into the scores.
LARGE = 400


def test_changing_the_pseudonym_key_does_not_change_scores_or_ranks():
    records = _records(count=LARGE)
    baseline = _by_original(build_ml_anomaly_ranking(records)[1])
    for key in ("key-one", "key-two"):
        relabelled, back = _relabel(records, key)
        assert _by_original(build_ml_anomaly_ranking(relabelled)[1], back) == baseline


@pytest.mark.parametrize("seed", [1, 2])
def test_shuffled_input_rows_give_identical_scores_and_ranks(seed):
    records = _records(count=LARGE)
    shuffled = records[:]
    random.Random(seed).shuffle(shuffled)
    assert _by_original(build_ml_anomaly_ranking(shuffled)[1]) == _by_original(build_ml_anomaly_ranking(records)[1])


def test_repeated_runs_are_deterministic():
    records = _records()
    assert build_ml_anomaly_ranking(records) == build_ml_anomaly_ranking(records)


def test_ml_ranking_does_not_change_rule_risk_or_audit_priority(monkeypatch):
    records = _records()
    dataset = FeatureDataset(records=records, facilities=(), source_metadata={"kind": "synthetic", "label": "fixture"})
    with_ml = analytics_service.build_analytics_snapshot_from_dataset(dataset)

    def no_ml(source_records):
        return {"status": "insufficient_data", "model_version": "disabled", "records_considered": len(source_records),
                "records_scored": 0, "items": [], "items_truncated": False, "limitations": []}, {}

    monkeypatch.setattr(analytics_service, "build_ml_anomaly_ranking", no_ml)
    without_ml = analytics_service.build_analytics_snapshot_from_dataset(dataset)
    rule_view = lambda snapshot: {  # noqa: E731
        case_id: (case["risk_score"], case["score_status"], case["indicators"])
        for case_id, case in snapshot["cases"].items()
    }
    assert rule_view(with_ml) == rule_view(without_ml)
    assert with_ml["audit_priority"] == without_ml["audit_priority"]
    assert with_ml["risk_scoring"] == without_ml["risk_scoring"]
    assert with_ml["execution_status"] == without_ml["execution_status"]
    assert with_ml["ml_anomaly"]["score_type"] == "relative_unsupervised_anomaly_rank_not_fraud_probability"
