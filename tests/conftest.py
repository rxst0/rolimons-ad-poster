import json
import sys
import time
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from roliposter.config import Ad, Config  # noqa: E402
from roliposter.items import ItemCatalog, ItemInfo  # noqa: E402


def make_item(item_id: int, name: str, value: int, demand: int = 2) -> ItemInfo:
    return ItemInfo(item_id, name, "", value, value, value, demand, 2, False, False, False)


@pytest.fixture
def catalog() -> ItemCatalog:
    items = [make_item(1, "Alpha", 1000), make_item(2, "Bravo", 2000), make_item(3, "Charlie", 3000),
             make_item(4, "Delta", 4000, demand=4)]
    return ItemCatalog({i.id: i for i in items}, time.time())


@pytest.fixture
def cfg() -> Config:
    return Config(roblox_user_id=42, skip_unowned_items=False, ads=[
        Ad("A", [1], [], ["upgrade"]), Ad("B", [2], [3]), Ad("C", [4], [], ["any"])])


def response(status: int, body, headers: dict | None = None) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = (body if isinstance(body, str) else json.dumps(body)).encode()
    r.headers.update(headers or {})
    return r


class FakeSession(requests.Session):
    """Replays scripted POST responses (default: success) and canned GET responses by URL fragment."""

    def __init__(self, posts=(), gets: dict | None = None):
        super().__init__()
        self.posts = list(posts)
        self.gets = gets or {}
        self.posted: list[dict] = []

    def post(self, url, json=None, headers=None, timeout=None, **kw):
        self.posted.append(json)
        item = self.posts.pop(0) if self.posts else response(201, {"success": True})
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, headers=None, timeout=None, **kw):
        for fragment, body in self.gets.items():
            if fragment in url:
                return response(200, body)
        raise requests.ConnectionError(f"no fake for {url}")


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Keeps tests from touching the real state.json."""
    import roliposter.poster as poster_mod
    monkeypatch.setattr(poster_mod, "state_path", lambda: tmp_path / "state.json")
    return tmp_path
