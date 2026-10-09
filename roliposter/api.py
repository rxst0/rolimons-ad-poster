"""Rolimons trade ad API client. Only creates Rolimons trade ads; never talks to Roblox."""
from dataclasses import dataclass
from enum import Enum

import requests

from .config import Ad
from .items import USER_AGENT

# Unofficial endpoint (verified live Oct 2026). Body fields match the open-source `roli` crate.
CREATE_AD_URL = "https://api.rolimons.com/tradeads/v1/createad"
AUTH_ERROR_CODES = {4, 5}  # 4 = missing verification cookie, 5 = invalid verification data
# Codes seen from createad: 2 = invalid ad contents (e.g. "Invalid offered item count").
# A successful post returns 201 {"success": true}. The cooldown reply has not been observed yet.
INVALID_AD_CODES = {2}
COOLDOWN_HINTS = ("cooldown", "wait", "too soon", "recently", "too many ads")


class Outcome(Enum):
    SUCCESS = "SUCCESS"
    COOLDOWN = "COOLDOWN"
    AUTH_ERROR = "AUTH_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    REJECTED = "REJECTED"
    SERVER_ERROR = "SERVER_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"


@dataclass
class PostResult:
    outcome: Outcome
    status_code: int | None
    message: str
    retry_after: float | None = None
    raw: str = ""  # first part of Rolimons' reply, logged so new response formats can be spotted


def build_payload(user_id: int, ad: Ad) -> dict:
    return {
        "player_id": user_id,
        "offer_item_ids": ad.offer_item_ids,
        "request_item_ids": ad.request_item_ids,
        "request_tags": ad.request_tags,
    }


def _retry_after(resp: requests.Response) -> float | None:
    try:
        return float(resp.headers.get("Retry-After", ""))
    except ValueError:
        return None


def classify_response(resp: requests.Response) -> PostResult:
    status = resp.status_code
    text = resp.text or ""
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    head = text[:2000].lower()
    message = str(data.get("message") or text[:200]).strip()
    lower = message.lower()
    code = data.get("code")
    retry = _retry_after(resp)
    result = _classify(status, data, head, message, lower, code, retry)
    result.raw = " ".join(text[:300].split())
    return result


def _classify(status, data, head, message, lower, code, retry) -> PostResult:
    if "cloudflare" in head and "<html" in head:
        return PostResult(Outcome.SERVER_ERROR, status, "Blocked by a Cloudflare challenge page", retry)
    if 200 <= status < 300 and data.get("success", True) is not False:
        return PostResult(Outcome.SUCCESS, status, message or "Ad posted")
    if code in INVALID_AD_CODES:
        return PostResult(Outcome.REJECTED, status, message or f"Invalid ad (code {code})")
    if any(h in lower for h in COOLDOWN_HINTS):
        return PostResult(Outcome.COOLDOWN, status, message, retry)
    if status in (401, 403, 422) or code in AUTH_ERROR_CODES:
        return PostResult(Outcome.AUTH_ERROR, status, message or "Unauthorized")
    if status == 429:
        return PostResult(Outcome.RATE_LIMITED, status, message or "Too many requests", retry)
    if status >= 500:
        return PostResult(Outcome.SERVER_ERROR, status, message or "Server error", retry)
    return PostResult(Outcome.REJECTED, status, message or "Rejected")


class RolimonsClient:
    def __init__(self, session: requests.Session, cookie: str, user_id: int, timeout: float = 20):
        self.session = session
        self._cookie = cookie
        self.user_id = user_id
        self.timeout = timeout

    def _headers(self) -> dict:
        # Sent as an explicit header on this request only, so the cookie never rides along
        # to other hosts (e.g. the item catalog request) through the session cookie jar.
        return {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://www.rolimons.com",
            "Referer": "https://www.rolimons.com/",
            "Cookie": f"_RoliVerification={self._cookie}",
        }

    def post_ad(self, ad: Ad) -> PostResult:
        try:
            resp = self.session.post(
                CREATE_AD_URL, json=build_payload(self.user_id, ad), headers=self._headers(), timeout=self.timeout
            )
        except requests.RequestException as e:
            return PostResult(Outcome.NETWORK_ERROR, None, type(e).__name__)
        return classify_response(resp)
