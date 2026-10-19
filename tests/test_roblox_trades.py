import json

from roliposter.items import parse_item_details
from roliposter.roblox_trades import ago, parse_details, parse_list, parse_time, verdict

CATALOG = parse_item_details({"success": True, "items": {
    "1001": ["Dominus Test", "DT", 9000, 10000, 10000, 3, 0, -1, -1, -1],
    "1002": ["Projected Hat", "PH", 5000, -1, 5000, 1, 0, 1, -1, -1],
}})

LIST = {"previousPageCursor": None, "nextPageCursor": "abc_123", "data": [
    {"id": 555, "user": {"id": 77, "name": "Builderman", "displayName": "Builder"},
     "created": "2026-10-20T10:00:00.1234567Z", "expiration": "2026-10-24T10:00:00Z", "isActive": True,
     "status": "Open"},
    {"id": 0, "user": {}},  # not a trade
]}

DETAILS = {"tradeId": 555,
           "participantAOffer": {"user": {"id": 1, "name": "me"}, "robux": 0, "items": [
               {"itemTarget": {"itemType": "Asset", "targetId": "1001"}, "itemName": "Dominus Test", "serialNumber": 12}]},
           "participantBOffer": {"user": {"id": 77, "name": "Builderman"}, "robux": 1000, "items": [
               {"itemTarget": {"itemType": "Asset", "targetId": "1002"}, "itemName": "Projected Hat"},
               {"itemTarget": {"itemType": "Asset", "targetId": "9999"}, "itemName": "Unknown UGC",
                "recentAveragePrice": 4000}]}}


def test_parse_list():
    trades, cursor = parse_list(json.dumps(LIST))
    assert cursor == "abc_123"
    assert len(trades) == 1
    t = trades[0]
    assert (t.id, t.partner_id, t.partner_name, t.status) == (555, 77, "Builderman", "Open")
    assert t.created == parse_time("2026-10-20T10:00:00.1234567Z")


def test_parse_time_formats():
    assert parse_time("2026-10-20T10:00:00Z") == 1792490400
    assert parse_time("2026-10-20T12:00:00+02:00") == 1792490400
    assert parse_time("not a time") is None
    assert parse_time(None) is None


def test_details_from_your_side_either_way_round():
    for body in (DETAILS, {**DETAILS, "participantAOffer": DETAILS["participantBOffer"],
                           "participantBOffer": DETAILS["participantAOffer"]}):
        d = parse_details(json.dumps(body), partner_id=77, catalog=CATALOG)
        assert [i.asset_id for i in d.give.items] == [1001]
        assert d.give.items[0].serial == 12
        assert [i.asset_id for i in d.get.items] == [1002, 9999]
        assert d.get.robux == 1000


def test_values_robux_tax_and_verdict():
    d = parse_details(DETAILS, partner_id=77, catalog=CATALOG)
    assert d.give_value == 10000
    assert d.get_value == 5000 + 4000 + 700  # unknown item falls back to RAP; robux after Roblox's 30% cut
    assert d.has_projected
    kind, text = verdict(d)
    assert kind == "loss"
    assert "You give 10,000" in text and "(-3%)" in text


def test_missing_catalog_uses_roblox_names_and_rap():
    d = parse_details(DETAILS, partner_id=77, catalog=None)
    assert d.get.items[1].name == "Unknown UGC" and d.get.items[1].value == 4000


def test_ago():
    assert ago(1000, now=1030) == "just now"
    assert ago(1000, now=1000 + 7200) == "2h ago"
    assert ago(None) == ""
