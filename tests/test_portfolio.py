import json

import pytest

from roliposter.inventory import Inventory
from roliposter.items import parse_item_details
from roliposter.portfolio import History, change, parse_history, totals

DAY = 86400
CATALOG = parse_item_details({"success": True, "items": {
    "1001": ["Dominus Test", "DT", 9000, 10000, 10000, 3, 0, -1, -1, -1],
    "1002": ["Projected Hat", "PH", 5000, -1, 5000, 1, 0, 1, -1, -1],
}})


def page(chart: dict) -> str:
    return f"<script>var player_id = 1;\nvar chart_data             = {json.dumps(chart)};\nvar x = 2;</script>"


def test_parse_history_sorts_and_reads_points():
    h = parse_history(page({"num_points": 3, "nominal_scan_time": [3 * DAY, DAY, 2 * DAY],
                            "value": [30, 10, 20], "rap": [3, 1, 2], "num_limiteds": [1, 1, 1]}))
    assert h.times == [DAY, 2 * DAY, 3 * DAY]
    assert h.values == [10, 20, 30] and h.raps == [1, 2, 3]


def test_parse_history_without_chart_fails():
    with pytest.raises(ValueError):
        parse_history("<html>no chart here</html>")


def test_since_keeps_the_point_before_the_range():
    h = History([0, DAY, 2 * DAY, 3 * DAY], [1, 2, 3, 4], [1, 2, 3, 4])
    part = h.since(DAY * 1.5, now=3 * DAY)
    assert part.values == [2, 3, 4]  # 2 is the last point before the range starts


def test_with_now_and_change():
    h = History([0, DAY], [100, 110], [90, 95]).with_now(121, 96, now=DAY + 10)
    assert h.values == [100, 110, 121]
    diff, pct = change(h)
    assert diff == 21 and round(pct) == 21
    assert change(History([0], [5], [5])) == (0, None)


def test_totals_count_copies_and_sort_by_worth():
    inv = Inventory(counts={1002: 1, 1001: 2, 9999: 1}, on_hold={1001: 1})
    t = totals(inv, CATALOG)
    assert t.value == 2 * 10000 + 5000 and t.rap == 2 * 9000 + 5000 and t.items == 4
    assert [h.item_id for h in t.holdings] == [1001, 1002, 9999]
    assert t.holdings[0].on_hold == 1 and t.holdings[1].projected
