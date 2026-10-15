import threading
import time
from pathlib import Path

import pytest
import requests

from conftest import FakeSession, response
from roliposter import events as ev
from roliposter import poster as P
from roliposter.state import PostHistory


def make_poster(cfg, catalog, script=(), stop_when=None):
    events = []
    p = P.Poster(cfg, Path("does-not-exist.json"), "cookie123456", catalog, threading.Event(),
                 FakeSession(script), on_event=events.append)
    p.sleeps = []

    def fake_sleep(seconds, reason):
        p.sleeps.append((seconds, reason))
        if stop_when and stop_when(events):
            p.stop()
        return not p.stopped
    p.sleep = fake_sleep
    return p, events


def codes(events):
    return [e["code"] for e in events]


def test_every_code_has_a_friendly_description():
    for code in (ev.STARTED, ev.POSTED, ev.REJECTED, ev.SKIPPED_UNOWNED, ev.PAUSED_DAILY_LIMIT, ev.PAUSED_HOURS,
                 ev.PAUSED_OFFLINE, ev.RESUMED, ev.STOPPED_AUTH, ev.STOPPED_ALL_FAILED, ev.STOPPED_ERROR,
                 ev.STOPPED_BY_USER):
        info = ev.describe({"code": code, "params": {"ad": "My ad", "items": ["Domino Crown"]}})
        assert info.title and info.severity in ("ok", "info", "warn", "error")


@pytest.mark.parametrize("code,notify", [
    (ev.PAUSED_DAILY_LIMIT, True), (ev.PAUSED_HOURS, True), (ev.PAUSED_OFFLINE, True), (ev.RESUMED, True),
    (ev.STOPPED_AUTH, True), (ev.STOPPED_ALL_FAILED, True), (ev.POSTED, False), (ev.REJECTED, False),
    (ev.STOPPED_BY_USER, False),
])
def test_which_events_notify(code, notify):
    assert ev.describe({"code": code, "params": {}}).notify is notify


def test_known_rolimons_rejection_is_explained():
    info = ev.describe({"code": ev.REJECTED, "params": {"ad": "A", "reason": "Invalid offered item count"}})
    assert "at least one item" in info.body
    unknown = ev.describe({"code": ev.REJECTED, "params": {"ad": "A", "reason": "Weird new error"}})
    assert '"Weird new error"' in unknown.body


def test_daily_limit_pauses_then_resumes(cfg, catalog):
    cfg.max_ads_per_24h = 2
    p, events = make_poster(cfg, catalog, stop_when=lambda e: ev.POSTED in codes(e))
    now = time.time()
    p.history.posts = [{"t": now - 3600, "ad": "x"}, {"t": now - 1800, "ad": "x"}]  # limit already reached
    original = p.history.seconds_until_quota
    calls = {"n": 0}

    def quota(cap):  # full on the first check, free after the (fake) wait
        calls["n"] += 1
        return original(cap) if calls["n"] == 1 else 0.0
    p.history.seconds_until_quota = quota
    p.run()
    c = codes(events)
    assert c[:4] == [ev.STARTED, ev.PAUSED_DAILY_LIMIT, ev.RESUMED, ev.POSTED]
    paused = events[1]["params"]
    assert paused["count"] == 2 and paused["cap"] == 2 and paused["resume_at"] > now
    assert "daily ad limit" in ev.describe(events[2]).body.lower()


def test_posting_hours_pause_and_resume(cfg, catalog, monkeypatch):
    cfg.posting_hours.enabled = True
    waits = iter([3600.0, 0.0, 0.0, 0.0])
    monkeypatch.setattr(P, "seconds_until_allowed", lambda hours: next(waits, 0.0))
    p, events = make_poster(cfg, catalog, stop_when=lambda e: ev.POSTED in codes(e))
    p.run()
    assert codes(events)[:4] == [ev.STARTED, ev.PAUSED_HOURS, ev.RESUMED, ev.POSTED]


def test_long_outage_pauses_once_and_resumes_on_success(cfg, catalog, monkeypatch):
    monkeypatch.setattr(P, "BACKOFF_BASE_SECONDS", 200.0)  # reach 10 minutes of retrying quickly
    outage = [requests.ConnectionError()] * 6
    p, events = make_poster(cfg, catalog, outage, stop_when=lambda e: ev.POSTED in codes(e))
    p.run()
    c = codes(events)
    assert c.count(ev.PAUSED_OFFLINE) == 1
    assert c.index(ev.PAUSED_OFFLINE) < c.index(ev.RESUMED) < c.index(ev.POSTED)


def test_short_blip_is_not_a_pause(cfg, catalog):
    p, events = make_poster(cfg, catalog, [requests.ConnectionError()],
                            stop_when=lambda e: ev.POSTED in codes(e))
    p.run()
    assert ev.PAUSED_OFFLINE not in codes(events) and ev.RESUMED not in codes(events)


def test_stops_are_recorded(cfg, catalog):
    p, events = make_poster(cfg, catalog, [response(400, {"code": 2, "message": "Invalid offered item count"})] * 3)
    p.run()
    assert codes(events).count(ev.REJECTED) == 3 and codes(events)[-1] == ev.STOPPED_ALL_FAILED
    p, events = make_poster(cfg, catalog, [response(401, {"code": 5, "message": "Invalid verification data"})])
    with pytest.raises(P.AuthError):
        p.run()
    assert codes(events)[-1] == ev.STOPPED_AUTH


def test_old_history_still_shows(tmp_path):
    h = PostHistory(tmp_path / "s.json")
    h.record_attempt("Old ad", "SUCCESS", '{"success":true}')
    h.record_attempt("Old ad", "REJECTED", "Invalid offered item count")
    timeline = PostHistory(tmp_path / "s.json").timeline()
    titles = [ev.describe(e).title for e in timeline]
    assert titles == ['Rolimons rejected "Old ad"', 'Posted "Old ad"']  # newest first


def test_events_persist(tmp_path):
    h = PostHistory(tmp_path / "s.json")
    h.record_event(ev.POSTED, {"ad": "A"}, "raw")
    again = PostHistory(tmp_path / "s.json")
    assert again.timeline()[0]["code"] == ev.POSTED and again.timeline()[0]["raw"] == "raw"


def test_history_filters_and_groups():
    now = time.time()
    timeline = [
        {"t": now, "code": ev.REJECTED, "params": {"ad": "B", "reason": "x"}},
        {"t": now - 60, "code": ev.POSTED, "params": {"ad": "A"}},
        {"t": now - 3 * 86400, "code": ev.STARTED, "params": {"ads": 2}},
    ]
    all_groups = ev.grouped(timeline)
    assert all_groups[0][0] == "Today" and len(all_groups[0][1]) == 2 and len(all_groups) == 2
    assert [i.title for _, i in ev.grouped(timeline, "posted")[0][1]] == ['Posted "A"']
    assert [i.title for _, i in ev.grouped(timeline, "problems")[0][1]] == ['Rolimons rejected "B"']
    assert ev.summary(timeline, 1, 55) == "1 of 55 ads posted in the last 24h  ·  1 problem"


def test_details_include_action_and_raw():
    event = {"t": time.time(), "code": ev.STOPPED_AUTH, "params": {}, "raw": '{"code":5}'}
    text = ev.details(event, ev.describe(event))
    assert "What to do: Sign in" in text and 'Technical details: {"code":5}' in text
