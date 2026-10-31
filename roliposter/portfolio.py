"""What a player's limiteds are worth: totals from their inventory, and value history from Rolimons.

- Value and RAP history: Rolimons has no API for it, but each player page (rolimons.com/player/<id>)
  embeds the chart it draws as `var chart_data = {...};`: one point per day with the inventory's value and RAP.
- Current price (the cheapest copy for sale): the Rolimons deals page (rolimons.com/deals) embeds every
  item's best price as `var item_details = {"1:<asset id>": [name, best price, rap, ...]}`. Nobody keeps a
  history of it for a whole inventory, so the app records its own (PriceLog), one point a day.
"""
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from .inventory import Inventory
from .items import USER_AGENT, ItemCatalog

PLAYER_PAGE_URL = "https://www.rolimons.com/player/{}"
DEALS_PAGE_URL = "https://www.rolimons.com/deals"
RANGES = (("1d", "1D", 86400), ("1m", "1M", 30 * 86400), ("6m", "6M", 182 * 86400), ("1y", "1Y", 365 * 86400))
_CHART = re.compile(r"var\s+chart_data\s*=\s*(\{.*?\})\s*;", re.S)
_DEALS = re.compile(r"var\s+item_details\s*=\s*(\{.*?\})\s*;", re.S)
DAY = 86400
# Sellers sometimes list at joke prices (999,999,999,999); a listing above this many times the item's value
# (or RAP) isn't a real price, so it's left out of the total like an item nobody is selling.
MAX_PRICE_RATIO = 3


@dataclass
class Holding:
    item_id: int
    name: str
    count: int
    on_hold: int
    value: int         # per copy: Rolimons value, or RAP when Rolimons has none
    rap: int           # per copy
    price: int | None  # per copy: cheapest realistic copy for sale now; None when none (or unknown)
    projected: bool


@dataclass
class Totals:
    value: int
    rap: int
    price: int | None  # None until best prices are known
    unpriced: int      # copies with no realistic seller, left out of price
    items: int
    holdings: list[Holding]


@dataclass
class Series:
    times: list[float]
    values: list[int]

    def since(self, seconds: float, now: float | None = None) -> "Series":
        start = (now or time.time()) - seconds
        keep = [i for i, t in enumerate(self.times) if t >= start]
        if keep and keep[0] > 0:
            keep.insert(0, keep[0] - 1)  # the last point before the range, so the line starts at its edge
        return Series([self.times[i] for i in keep], [self.values[i] for i in keep])

    def with_point(self, value: int, now: float | None = None) -> "Series":
        """Adds the live total as the last point (the daily records lag behind)."""
        return Series(self.times + [now or time.time()], self.values + [value])

    def change(self) -> tuple[int, float | None]:
        """(difference, percent) from the first to the last point."""
        if len(self.values) < 2:
            return 0, None
        first, last = self.values[0], self.values[-1]
        return last - first, ((last - first) / first * 100 if first else None)


@dataclass
class History:
    value: Series
    rap: Series


def realistic_price(price: int | None, value: int, rap: int) -> int | None:
    """The listed price, or None when there's none or it's a joke listing (see MAX_PRICE_RATIO)."""
    reference = max(value, rap)
    if not price or reference <= 0 or price > reference * MAX_PRICE_RATIO:
        return None
    return price


def totals(inventory: Inventory, catalog: ItemCatalog | None, prices: dict[int, int] | None = None) -> Totals:
    holdings = []
    for item_id, count in inventory.counts.items():
        info = catalog.get(item_id) if catalog else None
        value, rap = (info.default_value, info.rap) if info else (0, 0)
        holdings.append(Holding(
            item_id=item_id, name=info.label if info else f"Item {item_id}", count=count,
            on_hold=inventory.on_hold.get(item_id, 0), value=value, rap=rap,
            price=realistic_price(prices.get(item_id), value, rap) if prices is not None else None,
            projected=bool(info and info.projected)))
    holdings.sort(key=lambda h: (-h.value * h.count, h.name))
    price = sum(h.price * h.count for h in holdings if h.price) if prices is not None else None
    return Totals(value=sum(h.value * h.count for h in holdings), rap=sum(h.rap * h.count for h in holdings),
                  price=price, unpriced=sum(h.count for h in holdings if not h.price) if prices is not None else 0,
                  items=sum(h.count for h in holdings), holdings=holdings)


def parse_history(page: str) -> History:
    m = _CHART.search(page)
    if not m:
        raise ValueError("No value chart on the Rolimons player page")
    data = json.loads(m.group(1))
    times, values, raps = data.get("nominal_scan_time") or [], data.get("value") or [], data.get("rap") or []
    n = min(len(times), len(values), len(raps))
    points = sorted((float(times[i]), int(values[i] or 0), int(raps[i] or 0)) for i in range(n)
                    if times[i] is not None)
    t = [p[0] for p in points]
    return History(Series(t, [p[1] for p in points]), Series(list(t), [p[2] for p in points]))


def parse_best_prices(page: str) -> dict[int, int]:
    """Asset ID -> cheapest price for sale now, from the Rolimons deals page (items nobody sells are left out)."""
    m = _DEALS.search(page)
    if not m:
        raise ValueError("No item list on the Rolimons deals page")
    prices = {}
    for key, row in json.loads(m.group(1)).items():
        kind, _, item_id = str(key).partition(":")
        if kind == "1" and item_id.isdigit() and isinstance(row, list) and len(row) > 1 \
                and isinstance(row[1], (int, float)) and row[1] > 0:
            prices[int(item_id)] = int(row[1])
    return prices


def fetch_history(session: requests.Session, user_id: int, timeout: float = 25) -> History:
    resp = session.get(PLAYER_PAGE_URL.format(user_id), headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return parse_history(resp.text)


def fetch_best_prices(session: requests.Session, timeout: float = 25) -> dict[int, int]:
    resp = session.get(DEALS_PAGE_URL, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return parse_best_prices(resp.text)


class PriceLog:
    """The inventory's total current price, recorded by the app once a day (latest reading wins)."""

    def __init__(self, path: Path):
        self.path = path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.points = sorted((float(t), int(v)) for t, v in data.get("points", []))
        except (OSError, ValueError, TypeError, AttributeError):
            self.points = []

    def record(self, total: int, now: float | None = None) -> None:
        now = now or time.time()
        day = int(now // DAY)
        self.points = [p for p in self.points if int(p[0] // DAY) != day] + [(now, int(total))]
        self.points = self.points[-800:]  # a bit over two years
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"points": self.points}), encoding="utf-8")
        tmp.replace(self.path)

    def series(self) -> Series:
        return Series([p[0] for p in self.points], [p[1] for p in self.points])
