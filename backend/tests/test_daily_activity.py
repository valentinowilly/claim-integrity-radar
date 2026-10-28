"""Claims per service date with their high and medium-risk counts (aggregate only; synthetic records)."""

from app.analytics.daily_activity import build_daily_activity


def _record(case_id, day, amount=None):
    return {"case_id": case_id, "service_date": day, "provider_billed_amount_unverified": amount}


def test_days_are_counted_in_order_with_risk_and_display_only_value():
    records = [_record("a", "2024-09-03", "1000"), _record("b", "2024-09-02", "500"), _record("c", "2024-09-02", "250"),
               _record("d", "2024-09-02"), _record("e", None)]
    lanes = {"a": {"lane": "red"}, "b": {"lane": "yellow"}, "c": {"lane": "green"}}
    activity = build_daily_activity(records, lanes)
    assert activity["status"] == "available" and activity["undated_claims"] == 1
    assert [day["date"] for day in activity["days"]] == ["2024-09-02", "2024-09-03"]
    first, second = activity["days"]
    assert (first["claims"], first["high"], first["medium"]) == (3, 0, 1)
    assert first["billed_high_or_medium"] == 500 and second["billed_high_or_medium"] == 1000
    assert set(first) == {"date", "claims", "high", "medium", "billed_high_or_medium"}  # counts only, no claim ids
    assert lanes == {"a": {"lane": "red"}, "b": {"lane": "yellow"}, "c": {"lane": "green"}}


def test_without_dates_there_is_no_trend_and_amounts_are_optional():
    assert build_daily_activity([_record("a", None)], {})["status"] == "unavailable"
    assert build_daily_activity([_record("a", "2024-09-02")], {})["days"][0]["billed_high_or_medium"] is None
