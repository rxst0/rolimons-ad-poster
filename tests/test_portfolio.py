import json

import pytest

from roliposter.inventory import Inventory
from roliposter.items import parse_item_details
from roliposter.portfolio import PriceLog, Series, parse_best_prices, parse_history, realistic_price, totals

DAY = 86400
CATALOG = parse_item_details({"success": True, "items": {
    "1001": ["Dominus Test", "DT", 9000, 10000, 10000, 3, 0, -1, -1, -1],
    "1002": ["Projected Hat", "PH", 5000, -1, 5000, 1, 0, 1, -1, -1],
}})


def page(var: str, data: dict) -> str:
    return f"<script>var player_id = 1;\nvar {var}             = {json.dumps(data)};\nvar x = 2;</script>"


def test_parse_history_sorts_and_reads_points():
    h = parse_history(page("chart_data", {"num_points": 3, "nominal_scan_time": [3 * DAY, DAY, 2 * DAY],
                                          "value": [30, 10, 20], "rap": [3, 1, 2], "num_limiteds": [1, 1, 1]}))
    assert h.value.times == [DAY, 2 * DAY, 3 * DAY] == h.rap.times
    assert h.value.values == [10, 20, 30] and h.rap.values == [1, 2, 3]


def test_parse_history_without_chart_fails():
    with pytest.raises(ValueError):
        parse_history("<html>no chart here</html>")


def test_parse_best_prices_keeps_assets_with_sellers():
    prices = parse_best_prices(page("item_details", {
        "1:1001": ["Dominus Test", 9500, 9000, "DT", None, 10000, 10000, None, None, "url"],
        "1:1002": ["Projected Hat", None, 5000, "PH", None, None, 5000, None, None, "url"],  # nobody selling
        "2:939596": ["A UGC item", 20500, 19762, None, None, None, 19762, None, None, "url"],  # not an asset
    }))
    assert prices == {1001: 9500}


def test_since_keeps_the_point_before_the_range():
    s = Series([0, DAY, 2 * DAY, 3 * DAY], [1, 2, 3, 4])
    assert s.since(DAY * 1.5, now=3 * DAY).values == [2, 3, 4]  # 2 is the last point before the range


def test_with_point_and_change():
    s = Series([0, DAY], [100, 110]).with_point(121, now=DAY + 10)
    assert s.values == [100, 110, 121]
    diff, pct = s.change()
    assert diff == 21 and round(pct) == 21
    assert Series([0], [5]).change() == (0, None)


def test_totals_count_copies_prices_and_sort_by_worth():
    inv = Inventory(counts={1002: 1, 1001: 2, 9999: 1}, on_hold={1001: 1})
    t = totals(inv, CATALOG, prices={1001: 9500})
    assert t.value == 2 * 10000 + 5000 and t.rap == 2 * 9000 + 5000 and t.items == 4
    assert t.price == 2 * 9500 and t.unpriced == 2  # 1002 and 9999 have no seller
    assert [h.item_id for h in t.holdings] == [1001, 1002, 9999]
    assert t.holdings[0].on_hold == 1 and t.holdings[1].projected
    assert totals(inv, CATALOG).price is None  # prices not loaded yet


def test_joke_listings_are_not_prices():
    assert realistic_price(25_000, value=10_000, rap=9_000) == 25_000      # a normal premium
    assert realistic_price(999_999_999_999, value=3_600_000, rap=107_875) is None
    assert realistic_price(5_000, value=0, rap=0) is None                   # nothing to compare with
    assert realistic_price(None, value=10, rap=10) is None
    inv = Inventory(counts={1001: 1, 1002: 1})
    t = totals(inv, CATALOG, prices={1001: 9500, 1002: 999_999_999})
    assert t.price == 9500 and t.unpriced == 1


def test_price_log_keeps_one_point_a_day(tmp_path):
    log = PriceLog(tmp_path / "prices.json")
    log.record(100, now=DAY + 10)
    log.record(120, now=DAY + 500)    # same day: replaces
    log.record(130, now=2 * DAY + 5)
    again = PriceLog(tmp_path / "prices.json")
    assert again.series().values == [120, 130]
    assert PriceLog(tmp_path / "missing.json").series().values == []
