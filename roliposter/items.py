"""Rolimons item catalog (public itemdetails API)."""
import time
from dataclasses import dataclass

import requests

ITEM_DETAILS_URL = "https://www.rolimons.com/itemapi/itemdetails"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
DEMAND_LABELS = {-1: "unassigned", 0: "terrible", 1: "low", 2: "normal", 3: "high", 4: "amazing"}


@dataclass(frozen=True)
class ItemInfo:
    id: int
    name: str
    acronym: str
    rap: int
    value: int          # -1 when Rolimons has no value assigned
    default_value: int  # value if assigned, else RAP
    demand: int         # -1..4
    trend: int
    projected: bool
    hyped: bool
    rare: bool

    @property
    def label(self) -> str:
        return f"{self.name} ({self.acronym})" if self.acronym else self.name

    @property
    def demand_label(self) -> str:
        return DEMAND_LABELS.get(self.demand, str(self.demand))


class ItemCatalog:
    def __init__(self, items: dict[int, ItemInfo], fetched_at: float):
        self.items = items
        self.fetched_at = fetched_at

    def get(self, item_id: int) -> ItemInfo | None:
        return self.items.get(item_id)

    def age_seconds(self) -> float:
        return time.time() - self.fetched_at

    def __len__(self) -> int:
        return len(self.items)


def parse_item_details(data: dict) -> ItemCatalog:
    # Format: {"success": true, "items": {"<id>": [name, acronym, rap, value, default_value,
    #           demand, trend, projected, hyped, rare]}}
    if not data.get("success") or not isinstance(data.get("items"), dict):
        raise ValueError("Unexpected itemdetails response format")
    items = {}
    for key, row in data["items"].items():
        items[int(key)] = ItemInfo(
            id=int(key), name=row[0], acronym=row[1] or "", rap=int(row[2]), value=int(row[3]),
            default_value=int(row[4]), demand=int(row[5]), trend=int(row[6]),
            projected=row[7] == 1, hyped=row[8] == 1, rare=row[9] == 1,
        )
    return ItemCatalog(items, time.time())


def fetch_catalog(session: requests.Session, timeout: float = 20) -> ItemCatalog:
    resp = session.get(ITEM_DETAILS_URL, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return parse_item_details(resp.json())
