"""The Android engine runner: file-based status reporting and stop/skip commands."""
import json
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import FakeSession

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "android"))
import runner  # noqa: E402

ITEMS = {"success": True, "items": {
    "1": ["Alpha", "", 1000, 1000, 1000, 2, 2, -1, -1, -1],
    "2": ["Bravo", "", 2000, 2000, 2000, 2, 2, -1, -1, -1],
}}
CONFIG = {"roblox_user_id": 42, "skip_unowned_items": False, "ads": [
    {"name": "A", "offer_item_ids": [1], "request_tags": ["any"]},
    {"name": "B", "offer_item_ids": [2], "request_tags": ["upgrade"]},
]}


def wait_for(predicate, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


@pytest.fixture
def home(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text(json.dumps(CONFIG), encoding="utf-8")
    (tmp_path / ".env").write_text("ROLI_VERIFICATION=aaaaaaaa.bbbbbbbb.cccccccc\n", encoding="utf-8")
    monkeypatch.delenv("ROLI_VERIFICATION", raising=False)
    import requests
    monkeypatch.setattr(requests, "Session", lambda: FakeSession(gets={"itemdetails": ITEMS}))
    yield tmp_path
    monkeypatch.delenv("ROLIPOSTER_HOME", raising=False)


def test_runner_reports_status_and_obeys_skip_and_stop(home):
    result = {}
    thread = threading.Thread(target=lambda: result.update(runner.run(home)), daemon=True)
    thread.start()
    # First ad posts immediately, then it waits out the cooldown with the next ad planned.
    assert wait_for(lambda: (runner.read_status(home).get("wait_until") or 0) > time.time())
    status = runner.read_status(home)
    assert status["running"] and status["next_ad"] == "B" and status["posted_24h"] == 1
    runner.send_command(home, "skip")
    assert wait_for(lambda: runner.read_status(home).get("next_ad") == "A")
    runner.send_command(home, "stop")
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert result["stopped_by_user"] and not result["running"] and result["error"] is None
    assert runner.read_status(home)["running"] is False


def test_runner_reports_startup_errors(home):
    (home / ".env").write_text("", encoding="utf-8")
    final = runner.run(home)
    assert not final["running"] and "cookie" in final["error"].lower()


def test_want_running_flag(tmp_path):
    runner.set_want_running(tmp_path, True)
    assert runner.wants_running(tmp_path)
    runner.set_want_running(tmp_path, False)
    assert not runner.wants_running(tmp_path)
