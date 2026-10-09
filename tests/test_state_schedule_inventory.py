import time
from datetime import datetime

from roliposter.config import Ad, PostingHours
from roliposter.inventory import Inventory, missing_offer_items, parse_player_assets
from roliposter.schedule import seconds_until_allowed
from roliposter.state import MAX_ATTEMPTS, PostHistory
from roliposter.updates import is_newer


def test_quota_waits_for_oldest_post(tmp_path):
    h = PostHistory(tmp_path / "s.json")
    now = time.time()
    h.posts = [{"t": now - 3600 * i, "ad": "x"} for i in range(3)]
    assert h.seconds_until_quota(4) == 0
    assert 20 * 3600 < h.seconds_until_quota(3) < 22 * 3600


def test_attempts_are_capped_and_persisted(tmp_path):
    h = PostHistory(tmp_path / "s.json")
    for i in range(MAX_ATTEMPTS + 5):
        h.record_attempt("ad", "SUCCESS", f"m{i}")
    again = PostHistory(tmp_path / "s.json")
    assert len(again.attempts) == MAX_ATTEMPTS and again.attempts[-1]["message"] == f"m{MAX_ATTEMPTS + 4}"


def test_posting_hours_daytime_window():
    hours = PostingHours(True, "09:00", "23:00")
    assert seconds_until_allowed(hours, datetime(2026, 1, 1, 12, 0)) == 0
    assert seconds_until_allowed(hours, datetime(2026, 1, 1, 8, 0)) == 3600
    assert seconds_until_allowed(hours, datetime(2026, 1, 1, 23, 30)) == 9.5 * 3600


def test_posting_hours_overnight_window():
    hours = PostingHours(True, "18:00", "02:00")
    assert seconds_until_allowed(hours, datetime(2026, 1, 1, 1, 0)) == 0
    assert seconds_until_allowed(hours, datetime(2026, 1, 1, 20, 0)) == 0
    assert seconds_until_allowed(hours, datetime(2026, 1, 1, 17, 0)) == 3600


def test_posting_hours_disabled():
    assert seconds_until_allowed(PostingHours(False, "09:00", "10:00"), datetime(2026, 1, 1, 3, 0)) == 0


def test_inventory_parsing_and_missing_items():
    inv = parse_player_assets({"success": True, "playerPrivacyEnabled": False,
                               "playerAssets": {"1": [11, 12], "2": [21]}, "holds": [12]})
    assert inv.counts == {1: 2, 2: 1} and inv.on_hold == {1: 1}
    assert missing_offer_items(Ad("x", [1, 1, 2]), inv) == []
    assert missing_offer_items(Ad("x", [2, 2, 3]), inv) == [2, 3]


def test_private_or_unknown_inventory_never_skips():
    assert missing_offer_items(Ad("x", [9]), None) == []
    assert missing_offer_items(Ad("x", [9]), Inventory(private=True)) == []


def test_version_compare():
    assert is_newer("v1.10.0", "1.9.9")
    assert not is_newer("v1.2.0", "1.2.0")
    assert not is_newer("1.1.9", "1.2.0")
