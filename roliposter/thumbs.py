"""Item pictures from Roblox's thumbnail API, cached on disk."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

THUMBNAILS_API = "https://thumbnails.roblox.com/v1/assets"
SIZE = "42x42"


class ThumbnailCache:
    def __init__(self, folder: Path):
        self.folder = folder

    def path(self, item_id: int) -> Path:
        return self.folder / f"{item_id}.png"

    def cached(self, item_id: int) -> bool:
        return self.path(item_id).exists()

    def fetch(self, session: requests.Session, item_ids: list[int], timeout: float = 15) -> list[int]:
        """Downloads any missing pictures. Returns the IDs that are now on disk."""
        wanted = [i for i in dict.fromkeys(item_ids) if not self.cached(i)]
        self.folder.mkdir(parents=True, exist_ok=True)
        for start in range(0, len(wanted), 100):
            batch = wanted[start:start + 100]
            resp = session.get(THUMBNAILS_API, timeout=timeout, params={
                "assetIds": ",".join(map(str, batch)), "size": SIZE, "format": "Png"})
            resp.raise_for_status()
            jobs = [(int(row["targetId"]), row["imageUrl"]) for row in resp.json().get("data", [])
                    if row.get("state") == "Completed" and row.get("imageUrl")]
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda job: self._download(session, *job, timeout), jobs))
        return [i for i in item_ids if self.cached(i)]

    def _download(self, session: requests.Session, item_id: int, url: str, timeout: float) -> None:
        try:
            img = session.get(url, timeout=timeout)
        except requests.RequestException:
            return
        if img.ok and img.content[:8] == b"\x89PNG\r\n\x1a\n":
            self.path(item_id).write_bytes(img.content)
