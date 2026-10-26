"""What a player's limiteds are worth: totals from their inventory, and value history from Rolimons.

Rolimons has no API for value history, but each player page (rolimons.com/player/<id>) embeds the chart
it draws as `var chart_data = {...};`: one point per day with the inventory's value and RAP.
"""
import json
import re
import time
from dataclasses import dataclass

import requests

from .inventory import Inventory
from .items import USER_AGENT, ItemCatalog

PLAYER_PAGE_URL = "https://www.rolimons.com/player/{}"
RANGES = (("1d", "1D", 86400), ("1m", "1M", 30 * 86400), ("6m", "6M", 182 * 86400), ("1y", "1Y", 365 * 86400))
_CHART = re.compile(r"var\s+chart_data\s*=\s*(\{.*?\})\s*;", re.S)


@dataclass
class Holding:
    item_id: int
    name: str
    count: int
    on_hold: int
    value: int   # per copy: Rolimons value, or RAP when Rolimons has none
    rap: int     # per copy
    projected: bool


@dataclass
class Totals:
    value: int
    rap: int
    items: int
    holdings: list[Holding]


@dataclass
class History:
    times: list[float]
    values: list[int]
    raps: list[int]

    def since(self, seconds: float, now: float | None = None) -> "History":
        start = (now or time.time()) - seconds
        keep = [i for i, t in enumerate(self.times) if t >= start]
        if keep and keep[0] > 0:
            keep.insert(0, keep[0] - 1)  # the last point before the range, so the line starts at its edge
        return History([self.times[i] for i in keep], [self.values[i] for i in keep], [self.raps[i] for i in keep])

    def with_now(self, value: int, rap: int, now: float | None = None) -> "History":
        """Adds today's live total as the last point (Rolimons' chart updates once a day)."""
        return History(self.times + [now or time.time()], self.values + [value], self.raps + [rap])


def totals(inventory: Inventory, catalog: ItemCatalog | None) -> Totals:
    holdings = []
    for item_id, count in inventory.counts.items():
        info = catalog.get(item_id) if catalog else None
        holdings.append(Holding(
            item_id=item_id, name=info.label if info else f"Item {item_id}", count=count,
            on_hold=inventory.on_hold.get(item_id, 0), value=info.default_value if info else 0,
            rap=info.rap if info else 0, projected=bool(info and info.projected)))
    holdings.sort(key=lambda h: (-h.value * h.count, h.name))
    return Totals(value=sum(h.value * h.count for h in holdings), rap=sum(h.rap * h.count for h in holdings),
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
    return History([p[0] for p in points], [p[1] for p in points], [p[2] for p in points])


def fetch_history(session: requests.Session, user_id: int, timeout: float = 25) -> History:
    resp = session.get(PLAYER_PAGE_URL.format(user_id), headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return parse_history(resp.text)


def change(history: History) -> tuple[int, float | None]:
    """(difference, percent) from the first to the last point."""
    if len(history.values) < 2:
        return 0, None
    first, last = history.values[0], history.values[-1]
    return last - first, ((last - first) / first * 100 if first else None)
