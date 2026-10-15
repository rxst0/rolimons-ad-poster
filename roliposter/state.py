"""Persists post times (so the cooldown and the 24h cap survive restarts) and the History tab's events."""
import json
import time
from pathlib import Path

DAY = 24 * 3600
MAX_ATTEMPTS = 300
MAX_EVENTS = 300


class PostHistory:
    def __init__(self, path: Path):
        self.path = path
        self.posts: list[dict] = []
        self.attempts: list[dict] = []  # low-level log of every post attempt (technical details)
        self.events: list[dict] = []    # what the History tab shows: see roliposter/events.py
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.posts = [p for p in data.get("posts", []) if isinstance(p.get("t"), (int, float))]
            self.attempts = [a for a in data.get("attempts", []) if isinstance(a.get("t"), (int, float))]
            self.events = [e for e in data.get("events", []) if isinstance(e.get("t"), (int, float))]
        except (OSError, ValueError, AttributeError):
            self.posts, self.attempts, self.events = [], [], []
        self._prune()

    def _prune(self) -> None:
        cutoff = time.time() - DAY
        self.posts = sorted((p for p in self.posts if p["t"] >= cutoff), key=lambda p: p["t"])

    def _save(self) -> None:
        try:
            data = {"posts": self.posts, "attempts": self.attempts, "events": self.events}
            self.path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        except OSError:
            pass

    def record(self, ad_name: str) -> None:
        self.posts.append({"t": time.time(), "ad": ad_name})
        self._prune()
        self._save()

    def record_attempt(self, ad_name: str, result: str, message: str) -> None:
        self.attempts.append({"t": time.time(), "ad": ad_name, "result": result, "message": message[:200]})
        del self.attempts[:-MAX_ATTEMPTS]
        self._save()

    def record_event(self, code: str, params: dict | None = None, raw: str = "") -> dict:
        event = {"t": time.time(), "code": code, "params": params or {}, "raw": raw[:300]}
        self.events.append(event)
        del self.events[:-MAX_EVENTS]
        self._save()
        return event

    def timeline(self) -> list[dict]:
        """Events for the History tab, newest first. Older versions only saved attempts; those are shown
        through the 'legacy' description so existing history doesn't disappear."""
        if self.events:
            items = list(self.events)
        else:
            items = [{"t": a["t"], "code": "legacy",
                      "params": {"ad": a.get("ad", ""), "result": a.get("result", ""), "message": a.get("message", "")},
                      "raw": a.get("message", "")} for a in self.attempts]
        # Reversed first so entries with the same timestamp (coarse clocks) still come out newest first.
        return sorted(reversed(items), key=lambda e: e["t"], reverse=True)

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
