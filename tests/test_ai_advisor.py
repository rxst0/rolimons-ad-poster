import json

import pytest

from roliposter.ai_advisor import (CLAUDE_URL, OPENAI_URL, Advice, AdvisorError, ask, build_context, check)
from roliposter.inventory import Inventory
from roliposter.items import parse_item_details
from roliposter.portfolio import History, Series

DAY = 86400
# [name, acronym, rap, value, default_value, demand, trend, projected, hyped, rare]
CATALOG = parse_item_details({"success": True, "items": {
    "1": ["Owned Hat", "OH", 900, 1000, 1000, 2, 2, -1, -1, -1],
    "2": ["Owned Face", "", 450, -1, 450, 3, 3, -1, -1, -1],
    "3": ["Big Upgrade", "BU", 2600, 2500, 2500, 4, 3, -1, -1, -1],
    "4": ["Projected Thing", "PT", 1800, -1, 1800, 1, 1, 1, -1, -1],
    "5": ["Way Too Big", "WTB", 99000, 100000, 100000, 4, 2, -1, -1, -1],
}})
INVENTORY = Inventory(counts={1: 2, 2: 1}, on_hold={1: 1})


class FakeResponse:
    def __init__(self, status: int, data: dict):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response, self.calls = response, []

    def post(self, url, json=None, timeout=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.response


ANSWER = {"summary": "Consolidate.", "recommendations": [
    {"kind": "upgrade", "give_item_ids": [1, 1, 2], "get_item_ids": [3], "reason": "demand", "confidence": "medium"},
    {"kind": "upgrade", "give_item_ids": [1, 1, 1], "get_item_ids": [3], "reason": "you only own 2", "confidence": "low"},
    {"kind": "upgrade", "give_item_ids": [2], "get_item_ids": [4], "reason": "projected", "confidence": "low"},
    {"kind": "downgrade", "give_item_ids": [1], "get_item_ids": [999], "reason": "made up", "confidence": "low"},
    {"kind": "hold", "give_item_ids": [2], "get_item_ids": [], "reason": "raising", "confidence": "high"},
]}


def test_context_has_your_items_and_nearby_market():
    history = History(Series([0, 200 * DAY, 400 * DAY], [100, 110, 121]), Series([0, 200 * DAY, 400 * DAY], [1, 1, 1]))
    ctx = build_context(INVENTORY, CATALOG, prices={1: 1100, 3: 9_999_999}, history=history, now=400 * DAY)
    owned = {o["item_id"]: o for o in ctx["your_items"]}
    assert owned[1]["count"] == 2 and owned[1]["on_trade_hold"] == 1 and owned[1]["best_price"] == 1100
    assert owned[2]["trend"] == "raising" and owned[2]["demand"] == "high"
    market = {m["item_id"]: m for m in ctx["market_items"]}
    assert set(market) == {3, 4}                    # 5 is far outside your value range
    assert "best_price" not in market[3]            # joke listing ignored
    assert market[4]["projected"] is True
    assert ctx["your_totals"]["value"] == 2 * 1000 + 450
    assert ctx["your_value_change"]["1_year"] == "+21.0%"


def test_check_keeps_only_sensible_recommendations():
    advice = check(ANSWER, INVENTORY, CATALOG, "claude", "claude-opus-5-5")
    assert [(r.kind, r.give, r.get) for r in advice.recommendations] == [
        ("upgrade", [1, 1, 2], [3]), ("hold", [2], [])]
    assert advice.dropped == 3
    assert Advice.from_dict(json.loads(json.dumps(advice.to_dict()))).recommendations == advice.recommendations


def test_claude_request_and_answer():
    session = FakeSession(FakeResponse(200, {"stop_reason": "end_turn", "content": [
        {"type": "thinking", "thinking": ""}, {"type": "text", "text": json.dumps(ANSWER)}]}))
    assert ask("claude", "sk-ant-test", {"your_items": []}, session=session) == ANSWER
    call = session.calls[0]
    assert call["url"] == CLAUDE_URL and call["headers"]["x-api-key"] == "sk-ant-test"
    assert call["headers"]["anthropic-version"] == "2026-10-21"
    body = call["json"]
    assert body["model"] == "claude-opus-5-5" and body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in call["headers"]["anthropic-beta"]


def test_openai_request_and_answer():
    session = FakeSession(FakeResponse(200, {"choices": [
        {"finish_reason": "stop", "message": {"content": json.dumps(ANSWER), "refusal": None}}]}))
    assert ask("openai", "sk-test", {}, model="gpt-5", session=session) == ANSWER
    call = session.calls[0]
    assert call["url"] == OPENAI_URL and call["headers"]["Authorization"] == "Bearer sk-test"
    assert call["json"]["response_format"]["json_schema"]["strict"] is True


@pytest.mark.parametrize("provider,status,text", [
    ("claude", 401, "rejected your API key"), ("openai", 429, "out of credit"), ("claude", 503, "having problems")])
def test_errors_are_plain_english(provider, status, text):
    session = FakeSession(FakeResponse(status, {"error": {"message": "detail"}}))
    with pytest.raises(AdvisorError, match=text):
        ask(provider, "key", {}, session=session)


def test_refusal_and_missing_key():
    session = FakeSession(FakeResponse(200, {"stop_reason": "refusal", "content": []}))
    with pytest.raises(AdvisorError, match="declined"):
        ask("claude", "key", {}, session=session)
    with pytest.raises(AdvisorError, match="API key in Settings"):
        ask("openai", "", {})
