"""Roblox trades for the app's own trades list ("Read my trades directly" on Android).

Turns Roblox's replies into what the screens show: who the trade is with, what each side gives, and
Rolimons values. Requests are made elsewhere (android/java/org/roliposter/RobloxApi.java); this module
only parses, so it is tested on the PC.
"""
import json
import re
import time
from calendar import timegm
from dataclasses import dataclass, field

from .items import ItemCatalog

KINDS = ("inbound", "outbound", "completed", "inactive")
KIND_LABELS = {"inbound": "Inbound", "outbound": "Outbound", "completed": "Completed", "inactive": "Inactive"}
ROBUX_AFTER_TAX = 0.7  # Roblox keeps 30% of robux added to a trade


@dataclass
class TradeSummary:
    id: int
    partner_id: int
    partner_name: str
    created: float | None   # unix time
    expires: float | None
    status: str


@dataclass
class TradeItem:
    asset_id: int
    name: str
    serial: int | None
    rap: int
    value: int        # Rolimons value, or RAP when Rolimons has none
    projected: bool
    rare: bool


@dataclass
class Side:
    items: list[TradeItem] = field(default_factory=list)
    robux: int = 0

    @property
    def item_value(self) -> int:
        return sum(i.value for i in self.items)


@dataclass
class TradeDetails:
    id: int
    give: Side   # what you give
    get: Side    # what you get

    @property
    def give_value(self) -> int:
        return self.give.item_value + self.give.robux

    @property
    def get_value(self) -> int:
        return self.get.item_value + int(self.get.robux * ROBUX_AFTER_TAX)

    @property
    def difference(self) -> int:
        return self.get_value - self.give_value

    @property
    def percent(self) -> float | None:
        return self.difference / self.give_value * 100 if self.give_value else None

    @property
    def has_projected(self) -> bool:
        return any(i.projected for i in self.get.items)


def parse_time(text) -> float | None:
    """Roblox's ISO times ("2026-10-20T12:34:56.1234567Z") as unix time."""
    m = re.match(r"^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(\.\d+)?(Z|[+-]\d\d:?\d\d)?$", str(text or "").strip())
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups()[:6])
    t = timegm((y, mo, d, h, mi, s, 0, 0, 0)) + float(m.group(7) or 0)
    tz = m.group(8)
    if tz and tz != "Z":
        sign = 1 if tz[0] == "+" else -1
        digits = tz[1:].replace(":", "")
        t -= sign * (int(digits[:2]) * 3600 + int(digits[2:]) * 60)
    return t


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load(body):
    return json.loads(body) if isinstance(body, (str, bytes)) else body


def parse_list(body) -> tuple[list[TradeSummary], str]:
    """A /v1/trades/{kind} reply: (trades newest first, cursor for the next page or "")."""
    data = _load(body)
    trades = []
    for row in data.get("data") or []:
        user = row.get("user") or {}
        trade_id = _int(row.get("id"))
        if trade_id <= 0:
            continue
        trades.append(TradeSummary(
            id=trade_id, partner_id=_int(user.get("id")),
            partner_name=str(user.get("name") or user.get("displayName") or "Someone"),
            created=parse_time(row.get("created")), expires=parse_time(row.get("expiration")),
            status=str(row.get("status") or "")))
    return trades, str(data.get("nextPageCursor") or "")


def _side(offer: dict, catalog: ItemCatalog | None) -> Side:
    side = Side(robux=max(0, _int((offer or {}).get("robux"))))
    for raw in (offer or {}).get("items") or []:
        asset_id = _int((raw.get("itemTarget") or {}).get("targetId") or raw.get("assetId"))
        info = catalog.get(asset_id) if catalog else None
        rap = info.rap if info else _int(raw.get("recentAveragePrice"))
        serial = raw.get("serialNumber")
        side.items.append(TradeItem(
            asset_id=asset_id, name=(info.label if info else str(raw.get("itemName") or raw.get("name") or f"Item {asset_id}")),
            serial=_int(serial) if serial not in (None, "") else None, rap=rap,
            value=info.default_value if info else rap,
            projected=bool(info and info.projected), rare=bool(info and info.rare)))
    return side


def parse_details(body, partner_id: int, catalog: ItemCatalog | None) -> TradeDetails:
    """A /v2/trades/{id} reply, from your side: the partner's offer is what you get."""
    data = _load(body)
    a, b = data.get("participantAOffer") or {}, data.get("participantBOffer") or {}
    a_id = _int((a.get("user") or {}).get("id"))
    mine, theirs = (b, a) if partner_id and a_id == partner_id else (a, b)
    return TradeDetails(id=_int(data.get("tradeId") or data.get("id")),
                        give=_side(mine, catalog), get=_side(theirs, catalog))


def ago(t: float | None, now: float | None = None) -> str:
    if not t:
        return ""
    seconds = max(0, (now or time.time()) - t)
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= size:
            return f"{int(seconds // size)}{unit} ago"
    return "just now"


def verdict(details: TradeDetails) -> tuple[str, str]:
    """("win"/"loss"/"even", "You give 1,000 · You get 1,200 (+20%)")."""
    pct = details.percent
    text = f"You give {details.give_value:,}  ·  You get {details.get_value:,}"
    if pct is not None:
        text += f" ({pct:+.0f}%)"
    kind = "even" if details.difference == 0 else "win" if details.difference > 0 else "loss"
    return kind, text
