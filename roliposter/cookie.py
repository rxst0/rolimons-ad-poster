"""Loads the _RoliVerification cookie from the environment or a .env file. Never logs it."""
import os
import re
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


def clean_cookie(value: str) -> str:
    """Accepts either the bare value or a pasted '_RoliVerification=...' string."""
    value = value.strip().strip("'\"")
    if value.lower().startswith("_roliverification="):
        value = value.split("=", 1)[1]
    return value.split(";", 1)[0].strip()


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
