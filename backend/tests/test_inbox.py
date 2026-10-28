"""Automatic intake from the server drop folder (example data only, same path as an upload)."""

from datetime import datetime, timedelta
import time

import pytest

from app.services import inbox
from tests.test_analysis_runs import call, operator_session, setup, verifier_session
from tests.test_bpjs_csv_upload import _csv, _rows


@pytest.fixture
def folder(tmp_path, monkeypatch):
    directory = tmp_path / "kiriman"
    directory.mkdir()
    monkeypatch.setenv(inbox.INBOX_DIR_VARIABLE, str(directory))
    monkeypatch.setenv(inbox.SCHEDULER_VARIABLE, "off")  # tests drive the schedule explicitly
    return directory


def _wait_idle(app, cookies, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = call(app, "GET", "/api/v1/inbox", cookies=cookies).json()
        if not state["running"] and not state["waiting_count"]:
            return state
        time.sleep(0.3)
    raise AssertionError("inbox pull did not finish")


def test_a_pull_analyses_new_files_once_rejects_real_exports_and_hides_the_path(tmp_path, folder):
    app, batch_db, users = setup(tmp_path)
    operator, verifier = operator_session(app, users), verifier_session(app, users)
    (folder / "klaim-2024-09-02.csv").write_bytes(_csv(_rows(120)))
    (folder / "ekspor-asli.csv").write_bytes(_csv([dict(row, PSTV01=f"{index:010d}") for index, row in enumerate(_rows(30))]))

    state = call(app, "GET", "/api/v1/inbox", cookies=verifier).json()
    assert state["configured"] and state["folder_name"] == "kiriman" and state["waiting_count"] == 2
    assert str(tmp_path) not in str(state)
    assert call(app, "POST", "/api/v1/inbox/pull", cookies=verifier,
                headers={"X-CSRF-Token": verifier["cir_csrf"]}).status_code == 403
    assert call(app, "POST", "/api/v1/inbox/pull", cookies=operator,
                headers={"X-CSRF-Token": operator["cir_csrf"]}).status_code == 202
    state = _wait_idle(app, verifier)

    files = {item["file_name"]: item for item in state["files"]}
    assert files["klaim-2024-09-02.csv"]["status"] == "analysed" and files["klaim-2024-09-02.csv"]["run_id"]
    assert files["ekspor-asli.csv"]["status"] == "rejected"
    assert files["ekspor-asli.csv"]["message_code"] == "real_participant_not_allowed"
    assert (folder / "selesai" / "klaim-2024-09-02.csv").exists() and (folder / "gagal" / "ekspor-asli.csv").exists()
    run_id = files["klaim-2024-09-02.csv"]["run_id"]
    assert call(app, "GET", f"/api/v1/runs/{run_id}?view=summary", cookies=verifier).status_code == 200
    assert "0000000001" not in str(state)

    # The same content dropped again is recognised and not analysed twice.
    (folder / "klaim-ulang.csv").write_bytes((folder / "selesai" / "klaim-2024-09-02.csv").read_bytes())
    result = inbox.pull_inbox(batch_db, trigger="manual", actor_user_id="test")
    assert result == {"configured": True, "files_found": 1, "files_processed": 0}
    assert len(call(app, "GET", "/api/v1/inbox", cookies=verifier).json()["files"]) == 2


def test_without_a_folder_the_intake_reports_not_configured(tmp_path, monkeypatch):
    monkeypatch.delenv(inbox.INBOX_DIR_VARIABLE, raising=False)
    app, _batch_db, users = setup(tmp_path)
    operator = operator_session(app, users)
    state = call(app, "GET", "/api/v1/inbox", cookies=operator).json()
    assert state["configured"] is False and state["next_pull_at"] is None
    refused = call(app, "POST", "/api/v1/inbox/pull", cookies=operator, headers={"X-CSRF-Token": operator["cir_csrf"]})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "INBOX_NOT_CONFIGURED"


def test_the_daily_time_and_the_next_pull(monkeypatch):
    monkeypatch.setenv(inbox.INBOX_TIME_VARIABLE, "06:30")
    morning = datetime(2024, 9, 2, 5, 0).astimezone()
    assert inbox.next_scheduled(morning).strftime("%d %H:%M") == "02 06:30"
    assert inbox.next_scheduled(morning + timedelta(hours=2)).strftime("%d %H:%M") == "03 06:30"
    monkeypatch.setenv(inbox.INBOX_TIME_VARIABLE, "tidak-valid")
    assert inbox.daily_time().strftime("%H:%M") == "06:00"


def test_the_scheduler_pulls_once_per_scheduled_day(tmp_path, folder, monkeypatch):
    app, batch_db, users = setup(tmp_path)
    (folder / "klaim-2024-09-03.csv").write_bytes(_csv(_rows(80, seed=9)))
    calls = []
    monkeypatch.setattr(inbox, "_safe_pull", lambda db, trigger, actor: calls.append(trigger) or inbox.pull_inbox(
        db, trigger=trigger, actor_user_id=actor))

    assert inbox.scheduled_tick(batch_db) is True
    assert inbox.scheduled_tick(batch_db) is False  # already pulled for this scheduled day
    assert calls == ["schedule"]
    state = call(app, "GET", "/api/v1/inbox", cookies=verifier_session(app, users)).json()
    assert state["last_pull"]["trigger"] == "schedule" and state["files"][0]["status"] == "analysed"
