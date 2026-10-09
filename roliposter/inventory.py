"""Which limiteds a player owns, from Rolimons' public player assets API."""
import time
from collections import Counter
from dataclasses import dataclass, field

import requests

from .config import Ad
from .items import USER_AGENT

PLAYER_ASSETS_URL = "https://api.rolimons.com/players/v1/playerassets/{}"


@dataclass
class Inventory:
    counts: dict[int, int] = field(default_factory=dict)   # item id -> copies owned
    on_hold: dict[int, int] = field(default_factory=dict)  # item id -> copies on trade hold
    private: bool = False
    fetched_at: float = field(default_factory=time.time)

    def age_seconds(self) -> float:
        return time.time() - self.fetched_at


def parse_player_assets(data: dict) -> Inventory:
    if not data.get("success"):
        raise ValueError("Unexpected playerassets response")
    assets = data.get("playerAssets") or {}
    holds = set(data.get("holds") or [])
    counts, on_hold = {}, {}
    for item_id, uaids in assets.items():
        counts[int(item_id)] = len(uaids)
        held = sum(1 for u in uaids if u in holds)
        if held:
            on_hold[int(item_id)] = held
    return Inventory(counts, on_hold, bool(data.get("playerPrivacyEnabled")))


def fetch_inventory(session: requests.Session, user_id: int, timeout: float = 20) -> Inventory:
    resp = session.get(PLAYER_ASSETS_URL.format(user_id), headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return parse_player_assets(resp.json())


def missing_offer_items(ad: Ad, inventory: Inventory | None) -> list[int]:
    """Offered item IDs you don't own enough copies of. Empty when unknown (private/unfetched)."""
    if inventory is None or inventory.private:
        return []
    missing = []
    for item_id, wanted in Counter(ad.offer_item_ids).items():
        if inventory.counts.get(item_id, 0) < wanted:
            missing.append(item_id)
    return missing
