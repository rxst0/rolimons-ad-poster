"""Posting-hours window (e.g. only post between 09:00 and 23:00 local time)."""
from datetime import datetime, timedelta

from .config import PostingHours


def _minutes(hhmm: str) -> int:
    h, m = hhmm.strip().split(":")
    return int(h) * 60 + int(m)


def seconds_until_allowed(hours: PostingHours, now: datetime | None = None) -> float:
    """0 if posting is allowed right now, else seconds until the window next opens."""
    if not hours.enabled:
        return 0.0
    now = now or datetime.now()
    start, end = _minutes(hours.start), _minutes(hours.end)
    current = now.hour * 60 + now.minute
    inside = start <= current < end if start < end else (current >= start or current < end)
    if inside:
        return 0.0
    opens = now.replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)
    if opens <= now:
        opens += timedelta(days=1)
    return (opens - now).total_seconds()
