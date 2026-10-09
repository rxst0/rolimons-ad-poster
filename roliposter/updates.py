"""Checks GitHub for a newer release."""
import re

import requests

from . import __version__

LATEST_RELEASE_API = "https://api.github.com/repos/rxst0/rolimons-ad-poster/releases/latest"


def _parse(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


def is_newer(candidate: str, current: str = __version__) -> bool:
    return _parse(candidate) > _parse(current)


def check_for_update(session: requests.Session, timeout: float = 10) -> tuple[str, str] | None:
    """Returns (version, release page URL) if GitHub has a newer release, else None."""
    resp = session.get(LATEST_RELEASE_API, headers={"Accept": "application/vnd.github+json"}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    tag = str(data.get("tag_name", ""))
    if tag and is_newer(tag):
        return tag.lstrip("v"), str(data.get("html_url", ""))
    return None
