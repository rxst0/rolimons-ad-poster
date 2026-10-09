import base64
import json
import time

import pytest

from roliposter.cookie import clean_cookie, cookie_info, looks_like_cookie


def b64(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")


TOKEN = f"{b64({'alg': 'HS256'})}.{b64({'exp': time.time() + 3600, 'player_data': {'id': 42, 'name': 'bob'}})}.s1g_-X"


@pytest.mark.parametrize("pasted", [
    TOKEN, f'"{TOKEN}"', f"_RoliVerification={TOKEN}", f'_RoliVerification:"{TOKEN}',
    f'_RoliVerification:"{TOKEN}"', f"Cookie: a=1; _RoliVerification={TOKEN}; b=2", f"  {TOKEN}\n",
    f'"_RoliVerification": "{TOKEN}"',
])
def test_clean_cookie_extracts_token_from_any_paste(pasted):
    assert clean_cookie(pasted) == TOKEN


def test_garbage_is_not_a_cookie():
    assert not looks_like_cookie(clean_cookie("hello world"))


def test_cookie_info_reads_player_and_expiry():
    info = cookie_info(TOKEN)
    assert (info.player_id, info.player_name, info.expired) == (42, "bob", False)


def test_expired_cookie_detected():
    old = f"{b64({'alg': 'HS256'})}.{b64({'exp': time.time() - 10})}.sig"
    assert cookie_info(old).expired
