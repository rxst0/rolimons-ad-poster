import pytest

from conftest import response
from roliposter.api import Outcome, classify_response


@pytest.mark.parametrize("status,body,expected", [
    (201, {"success": True}, Outcome.SUCCESS),  # confirmed live reply
    (200, {"success": False, "message": "Something else"}, Outcome.REJECTED),
    (200, {"success": False, "message": "Ad cooldown active"}, Outcome.COOLDOWN),
    (401, {"success": False, "code": 5, "message": "Invalid verification data"}, Outcome.AUTH_ERROR),
    (401, {"success": False, "code": 4, "message": "Missing verification cookie"}, Outcome.AUTH_ERROR),
    (400, {"success": False, "code": 2, "message": "Invalid offered item count"}, Outcome.REJECTED),
    (429, {"message": "slow down"}, Outcome.RATE_LIMITED),
    (503, "oops", Outcome.SERVER_ERROR),
    (403, "<html><title>Attention Required! | Cloudflare</title>", Outcome.SERVER_ERROR),
])
def test_classify(status, body, expected):
    assert classify_response(response(status, body)).outcome is expected


def test_retry_after_and_raw_are_captured():
    r = classify_response(response(429, {"message": "slow"}, {"Retry-After": "90"}))
    assert r.retry_after == 90 and '"slow"' in r.raw
