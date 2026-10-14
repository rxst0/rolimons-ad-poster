import pytest

from roliposter.trades_viewer import is_blocked


@pytest.mark.parametrize("method,url", [
    ("POST", "https://trades.roblox.com/v1/trades/123/accept"),
    ("POST", "https://trades.roblox.com/v1/trades/123/decline"),
    ("POST", "https://trades.roblox.com/v1/trades/123/counter"),
    ("POST", "https://trades.roblox.com/v1/trades/send"),
    ("POST", "https://trades.roblox.com/v2/trades/send"),
    ("POST", "https://trades.roblox.com/v1/trades/expire-outdated"),
    ("post", "https://TRADES.ROBLOX.COM/v2/trades/9/counter"),
    ("PATCH", "https://apis.roblox.com/trades-api/v1/trades/1"),
    ("DELETE", "https://trades.roblox.com/v1/trades/1"),
])
def test_trade_changing_requests_are_blocked(method, url):
    assert is_blocked(method, url)


@pytest.mark.parametrize("method,url", [
    ("GET", "https://trades.roblox.com/v1/trades/inbound?limit=25"),
    ("GET", "https://trades.roblox.com/v2/trades/123"),
    ("OPTIONS", "https://trades.roblox.com/v1/trades/123/accept"),   # CORS preflight; the POST is blocked
    ("POST", "https://thumbnails.roblox.com/v1/batch"),              # item pictures on the trades page
    ("POST", "https://auth.roblox.com/v2/login"),                    # signing in
    ("POST", "https://example.com/trades/accept"),                    # not Roblox
    ("POST", "https://roblox.com.evil.example/v1/trades/1/accept"),   # look-alike host
])
def test_reading_and_signing_in_still_work(method, url):
    assert not is_blocked(method, url)
