"""Loads the _RoliVerification cookie from the environment or a .env file. Never logs it."""
import base64
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

COOKIE_ENV_VAR = "ROLI_VERIFICATION"
_PLACEHOLDER = "paste_your_cookie_value_here"


def load_env_file(path: Path) -> None:
    """Minimal .env parser (KEY=VALUE lines). Real environment variables take precedence."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key, value)


_TOKEN = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_NAMED = re.compile(r"_RoliVerification\s*[=:]\s*[\"']?([^\"'\s;,]+)", re.IGNORECASE)


@dataclass
class CookieInfo:
    player_id: int | None
    player_name: str | None
    expires_at: float | None

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= time.time()


def clean_cookie(value: str) -> str:
    """Pulls the cookie value out of whatever was pasted: the bare value, name=value,
    the DevTools row (_RoliVerification:"..."), a quoted value, or a whole Cookie header."""
    value = value.strip()
    m = _NAMED.search(value)
    if m:
        return m.group(1)
    tokens = _TOKEN.findall(value)
    if len(tokens) == 1:
        return tokens[0]
    return value.strip("'\"").split(";", 1)[0].strip()


def looks_like_cookie(value: str) -> bool:
    return bool(_TOKEN.fullmatch(value))


def cookie_info(value: str) -> CookieInfo | None:
    """Reads the (unverified) token payload: who it belongs to and when it expires."""
    if not looks_like_cookie(value):
        return None
    try:
        part = value.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        player = payload.get("player_data") or {}
        exp = payload.get("exp")
        return CookieInfo(
            player_id=int(player["id"]) if "id" in player else None,
            player_name=player.get("name"),
            expires_at=float(exp) if exp else None,
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def get_cookie() -> str | None:
    value = clean_cookie(os.environ.get(COOKIE_ENV_VAR, ""))
    if not value or value == _PLACEHOLDER:
        return None
    if re.search(r"[\s;,]", value):
        raise ValueError(f"{COOKIE_ENV_VAR} contains whitespace/semicolons; paste only the cookie value.")
    return value


def save_env_value(path: Path, key: str, value: str) -> None:
    """Writes/replaces KEY=value in the .env file, keeping other lines intact."""
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    out, replaced = [], False
    for line in lines:
        if line.strip().split("=", 1)[0].strip() == key and not line.strip().startswith("#"):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.environ[key] = value
