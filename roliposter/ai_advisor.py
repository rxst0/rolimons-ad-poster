"""AI trade recommendations (optional, off by default): upgrades and downgrades for your inventory.

The user connects their own Claude (Anthropic) or ChatGPT (OpenAI) API key. The app sends the AI a summary
of the user's limiteds and of the market around them (Rolimons value, RAP, demand, trend, projected/hyped/
rare flags, current best price, the inventory's value history) and gets back recommendations in a fixed
JSON shape. Recommendations are checked before they're shown: you must own everything it says to give,
and everything it says to get must be a real item.

Plain `requests` is used for both providers: the Anthropic and OpenAI Python SDKs need compiled
dependencies that python-for-android can't build for the Android app.
"""
import json
import time
from dataclasses import dataclass, field

import requests

from .inventory import Inventory
from .items import ItemCatalog
from .portfolio import History, realistic_price

PROVIDERS = {
    "claude": {"label": "Claude (Anthropic)", "model": "claude-opus-5-5", "key_env": "AI_KEY_CLAUDE",
               "key_hint": "sk-ant-...", "key_url": "console.anthropic.com"},
    "openai": {"label": "ChatGPT (OpenAI)", "model": "gpt-5", "key_env": "AI_KEY_OPENAI",
               "key_hint": "sk-...", "key_url": "platform.openai.com"},
}
CLAUDE_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MAX_CANDIDATES = 250  # market items sent besides your own (keeps each request to a few cents)
TIMEOUT = 300

SYSTEM_PROMPT = """You are a Roblox limited-items trading advisor inside the Rolimons Ad Poster app.
You get the user's inventory and a slice of the Rolimons market as JSON. Suggest trades that improve the
user's position over the coming weeks to months:
- "upgrade": trade several lower-value items for fewer, higher-value items.
- "downgrade": trade one higher-value item for several lower-value items (more liquidity or demand).
- "hold": an item the user owns that they should keep, and why.

How to judge where an item's value is heading, using only the data given:
- Demand (terrible..amazing) and trend (lowering, unstable, stable, raising, fluctuating) matter most.
- RAP well above value can mean the value is about to be raised; RAP well below value can mean it's falling.
- A best price below value suggests sellers are undercutting (weak); none or far above suggests scarcity.
- Projected items have manipulated RAP: never recommend receiving one. Hyped items are risky.
- Rare items (few copies) are hard to trade quickly.

Rules: only suggest giving items the user owns (by item_id, respecting counts); only suggest getting items
listed in the data; keep each side to at most 4 items; aim for trades other traders would plausibly accept
(roughly fair by value, small overpay on demand). Say plainly when you're unsure. Values change and this is
not financial advice: be concrete and short."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["upgrade", "downgrade", "hold"]},
                    "give_item_ids": {"type": "array", "items": {"type": "integer"}},
                    "get_item_ids": {"type": "array", "items": {"type": "integer"}},
                    "reason": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["kind", "give_item_ids", "get_item_ids", "reason", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "recommendations"],
    "additionalProperties": False,
}


class AdvisorError(Exception):
    """A plain-English problem to show the user (bad key, no credit, network, ...)."""


@dataclass
class Recommendation:
    kind: str
    give: list[int]
    get: list[int]
    reason: str
    confidence: str


@dataclass
class Advice:
    summary: str
    recommendations: list[Recommendation] = field(default_factory=list)
    dropped: int = 0          # recommendations thrown away for naming items you don't own / that don't exist
    provider: str = ""
    model: str = ""
    created: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"summary": self.summary, "dropped": self.dropped, "provider": self.provider, "model": self.model,
                "created": self.created, "recommendations": [r.__dict__ for r in self.recommendations]}

    @classmethod
    def from_dict(cls, data: dict) -> "Advice":
        recs = [Recommendation(**r) for r in data.get("recommendations", [])]
        return cls(summary=data.get("summary", ""), recommendations=recs, dropped=data.get("dropped", 0),
                   provider=data.get("provider", ""), model=data.get("model", ""),
                   created=data.get("created", time.time()))


# ---- what the AI sees -------------------------------------------------------------------------
def _item_facts(info, prices: dict[int, int] | None) -> dict:
    price = realistic_price(prices.get(info.id), info.default_value, info.rap) if prices else None
    facts = {"item_id": info.id, "name": info.name, "acronym": info.acronym or None, "value": info.default_value,
             "has_rolimons_value": info.value > 0, "rap": info.rap, "demand": info.demand_label,
             "trend": info.trend_label, "projected": info.projected, "hyped": info.hyped, "rare": info.rare,
             "best_price": price}
    return {k: v for k, v in facts.items() if v not in (None, False)}


def build_context(inventory: Inventory, catalog: ItemCatalog, prices: dict[int, int] | None = None,
                  history: History | None = None, now: float | None = None) -> dict:
    """The JSON the AI gets: your items, the market around their values, and your value trend."""
    now = now or time.time()
    owned = []
    for item_id, count in sorted(inventory.counts.items()):
        info = catalog.get(item_id)
        if info:
            facts = _item_facts(info, prices)
            facts["count"] = count
            if inventory.on_hold.get(item_id):
                facts["on_trade_hold"] = inventory.on_hold[item_id]
            owned.append(facts)
    values = [o["value"] for o in owned if o["value"] > 0]
    lo, hi = (min(values) * 0.25, max(values) * 3) if values else (0, 0)
    pool = [i for i in catalog.items.values()
            if i.id not in inventory.counts and lo <= i.default_value <= hi and i.default_value > 0]
    pool.sort(key=lambda i: (-i.demand, -(i.trend == 3), -i.default_value))  # most wanted first
    market = [_item_facts(i, prices) for i in pool[:MAX_CANDIDATES]]
    context = {"your_items": owned, "market_items": market,
               "your_totals": {"value": sum(o["value"] * o["count"] for o in owned),
                               "rap": sum(o["rap"] * o["count"] for o in owned)}}
    if history and history.value.values:
        changes = {}
        for label, days in (("1_month", 30), ("6_months", 182), ("1_year", 365)):
            diff, pct = history.value.since(days * 86400, now=now).change()
            if pct is not None:
                changes[label] = f"{pct:+.1f}%"
        context["your_value_change"] = changes
    return context


# ---- asking the AI ---------------------------------------------------------------------------
def _user_prompt(context: dict) -> str:
    return ("Here is my inventory and the market. Give me up to 6 recommendations (upgrades, downgrades, or "
            "items to hold), best first.\n\n" + json.dumps(context, separators=(",", ":")))


def ask(provider: str, api_key: str, context: dict, model: str | None = None,
        session: requests.Session | None = None) -> dict:
    """Sends the request and returns the AI's JSON answer (not yet checked against your inventory)."""
    if provider not in PROVIDERS:
        raise AdvisorError(f"Unknown AI provider: {provider}")
    if not api_key:
        raise AdvisorError(f"Add your {PROVIDERS[provider]['label']} API key in Settings first.")
    session = session or requests.Session()
    model = model or PROVIDERS[provider]["model"]
    try:
        if provider == "claude":
            return _ask_claude(session, api_key, model, context)
        return _ask_openai(session, api_key, model, context)
    except requests.RequestException as e:
        raise AdvisorError(f"Couldn't reach {PROVIDERS[provider]['label']}: {type(e).__name__}. "
                           "Check your internet connection.") from None


def _http_error(provider: str, resp: requests.Response) -> AdvisorError:
    try:
        detail = resp.json().get("error", {}).get("message", "")
    except ValueError:
        detail = ""
    label = PROVIDERS[provider]["label"]
    plain = {401: f"{label} rejected your API key. Check it in Settings.",
             403: f"Your {label} API key isn't allowed to use this model.",
             404: f"{label} doesn't know that model name. Check the model in Settings.",
             429: f"{label} says you've hit a rate limit or are out of credit. Check your account billing.",
             529: f"{label} is overloaded right now. Try again in a few minutes."}
    message = plain.get(resp.status_code) or (f"{label} is having problems ({resp.status_code}). Try again later."
                                             if resp.status_code >= 500 else f"{label} error {resp.status_code}.")
    return AdvisorError(message + (f"\n({detail})" if detail else ""))


def _ask_claude(session, api_key, model, context) -> dict:
    body = {
        "model": model,
        "max_tokens": 16000,
        "fallbacks": "default",  # if a request is declined, Anthropic re-runs it on a fallback model
        "output_config": {"effort": "medium", "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": _user_prompt(context)}],
    }
    resp = session.post(CLAUDE_URL, json=body, timeout=TIMEOUT, headers={
        "x-api-key": api_key, "anthropic-version": "2026-10-21",
        "anthropic-beta": "server-side-fallback-2026-07-01", "content-type": "application/json"})
    if resp.status_code != 200:
        raise _http_error("claude", resp)
    data = resp.json()
    if data.get("stop_reason") == "refusal":
        raise AdvisorError("Claude declined this request. Try again, or switch to ChatGPT in Settings.")
    if data.get("stop_reason") == "max_tokens":
        raise AdvisorError("Claude's answer was cut off. Try again.")
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    return _parse_json(text, "Claude")


def _ask_openai(session, api_key, model, context) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": _user_prompt(context)}],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "trade_advice", "strict": True, "schema": RESPONSE_SCHEMA}},
    }
    resp = session.post(OPENAI_URL, json=body, timeout=TIMEOUT, headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    if resp.status_code != 200:
        raise _http_error("openai", resp)
    choice = (resp.json().get("choices") or [{}])[0]
    message = choice.get("message") or {}
    if message.get("refusal"):
        raise AdvisorError("ChatGPT declined this request. Try again, or switch to Claude in Settings.")
    if choice.get("finish_reason") == "length":
        raise AdvisorError("ChatGPT's answer was cut off. Try again.")
    return _parse_json(message.get("content") or "", "ChatGPT")


def _parse_json(text: str, label: str) -> dict:
    try:
        data = json.loads(text)
    except ValueError:
        raise AdvisorError(f"{label} sent an answer the app couldn't read. Try again.") from None
    if not isinstance(data, dict):
        raise AdvisorError(f"{label} sent an answer the app couldn't read. Try again.")
    return data


# ---- checking the answer ---------------------------------------------------------------------
def check(answer: dict, inventory: Inventory, catalog: ItemCatalog, provider: str = "", model: str = "") -> Advice:
    """Keeps only recommendations that make sense: you own what you'd give, what you'd get exists and isn't
    projected, and neither side is empty for a trade (holds name one item you own)."""
    kept, dropped = [], 0
    for raw in answer.get("recommendations") or []:
        try:
            kind = str(raw["kind"])
            give = [int(x) for x in raw.get("give_item_ids") or []]
            get = [int(x) for x in raw.get("get_item_ids") or []]
            reason, confidence = str(raw.get("reason", "")), str(raw.get("confidence", "low"))
        except (KeyError, TypeError, ValueError):
            dropped += 1
            continue
        needed = {}
        for item_id in give:
            needed[item_id] = needed.get(item_id, 0) + 1
        owns_all = all(inventory.counts.get(i, 0) >= n for i, n in needed.items())
        gets_ok = all(catalog.get(i) and not catalog.get(i).projected for i in get)
        if kind == "hold":
            ok = len(give) + len(get) >= 1 and all(inventory.counts.get(i) for i in give + get)
        else:
            ok = kind in ("upgrade", "downgrade") and give and get and owns_all and gets_ok \
                and len(give) <= 4 and len(get) <= 4
        if ok:
            kept.append(Recommendation(kind, give, get, reason, confidence if confidence in
                                       ("low", "medium", "high") else "low"))
        else:
            dropped += 1
    return Advice(summary=str(answer.get("summary", "")), recommendations=kept, dropped=dropped,
                  provider=provider, model=model)
