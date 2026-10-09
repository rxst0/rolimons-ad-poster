import threading
import time
from pathlib import Path

import pytest
import requests

from conftest import FakeSession, response
from roliposter import poster as P


def make_poster(cfg, catalog, script=(), gets=None, stop_after_posts=3):
    session = FakeSession(script, gets)
    p = P.Poster(cfg, Path("does-not-exist.json"), "cookie123456", catalog, threading.Event(), session)
    p.sleeps = []

    def fake_sleep(seconds, reason):
        p.sleeps.append((seconds, reason))
        if len(p.history.posts) >= stop_after_posts:
            p.stop()
        return not p.stopped
    p.sleep = fake_sleep
    return p


def test_backoff_then_cooldown_then_success_in_rotation(cfg, catalog):
    p = make_poster(cfg, catalog, [requests.ConnectionError(), requests.ConnectionError(),
                                   response(400, {"message": "Please wait for cooldown"})])
    p.run()
    waits = [s for s, _ in p.sleeps]
    assert waits[0] < waits[1]                                   # exponential backoff
    assert "cooldown" in p.sleeps[2][1]                          # cooldown retry
    offers = [b["offer_item_ids"] for b in p.session.posted]
    assert offers[3:6] == [[1], [2], [4]]                        # in-order rotation after retries
    cooldowns = [s for s, r in p.sleeps if r == "cooldown before next ad"]
    assert all(900 + 20 <= s <= 900 + 120 for s in cooldowns)    # 15 min + jitter
    results = [a["result"] for a in p.history.attempts]
    assert results.count("NETWORK_ERROR") == 2 and results.count("SUCCESS") == 3


def test_auth_error_stops(cfg, catalog):
    p = make_poster(cfg, catalog, [response(401, {"code": 5, "message": "Invalid verification data"})])
    with pytest.raises(P.AuthError):
        p.run()


def test_all_rejected_stops(cfg, catalog):
    p = make_poster(cfg, catalog, [response(400, {"code": 2, "message": "bad"})] * 3)
    p.run()
    assert len(p.session.posted) == 3 and not p.history.posts


def test_unowned_items_are_skipped(cfg, catalog):
    cfg.skip_unowned_items = True
    owned = {"success": True, "playerAssets": {"2": [1], "4": [2]}, "holds": []}  # item 1 not owned
    p = make_poster(cfg, catalog, gets={"playerassets": owned}, stop_after_posts=2)
    p.run()
    assert [b["offer_item_ids"] for b in p.session.posted] == [[2], [4]]
    assert p.unavailable == {"A": [1]}


def test_skip_next_changes_planned_ad(cfg, catalog):
    p = make_poster(cfg, catalog)
    p._plan_next()
    first = p.next_ad.name
    assert p.skip_next().name != first


def test_stop_interrupts_real_sleep(cfg, catalog):
    p = P.Poster(cfg, Path("x.json"), "cookie123456", catalog, threading.Event(), FakeSession())
    threading.Timer(0.5, p.stop).start()
    start = time.monotonic()
    assert p.sleep(600, "test") is False and time.monotonic() - start < 2
