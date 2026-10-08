"""Persists recent post times so the cooldown and the 24h cap survive restarts."""
import json
import time
from pathlib import Path

DAY = 24 * 3600


class PostHistory:
    def __init__(self, path: Path):
        self.path = path
        self.posts: list[dict] = []
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.posts = [p for p in data.get("posts", []) if isinstance(p.get("t"), (int, float))]
        except (OSError, ValueError, AttributeError):
            self.posts = []
        self._prune()

    def _prune(self) -> None:
        cutoff = time.time() - DAY
        self.posts = sorted((p for p in self.posts if p["t"] >= cutoff), key=lambda p: p["t"])

    def record(self, ad_name: str) -> None:
        self.posts.append({"t": time.time(), "ad": ad_name})
        self._prune()
        try:
            self.path.write_text(json.dumps({"posts": self.posts}, indent=1), encoding="utf-8")
        except OSError:
            pass

    def last_post_time(self) -> float | None:
        return self.posts[-1]["t"] if self.posts else None

    def count_24h(self) -> int:
        self._prune()
        return len(self.posts)

    def seconds_until_quota(self, max_per_day: int) -> float:
        """0 if another ad may be posted now, else seconds until enough old posts age out."""
        self._prune()
        if len(self.posts) < max_per_day:
            return 0.0
        oldest_blocking = self.posts[len(self.posts) - max_per_day]["t"]
        return max(0.0, oldest_blocking + DAY - time.time())
