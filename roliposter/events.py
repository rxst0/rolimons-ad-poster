"""Plain-English descriptions of everything the poster does, shared by the PC and Android History tabs
and the Android notifications.

The engine records events as a code plus a few details (see PostHistory.record_event); describe() turns
them into what the user sees. Rolimons' raw reply is kept separately as "technical details".
"""
import time
from dataclasses import dataclass

# Event codes
STARTED = "started"
POSTED = "posted"
REJECTED = "rejected"
SKIPPED_UNOWNED = "skipped_unowned"
PAUSED_DAILY_LIMIT = "paused_daily_limit"
PAUSED_HOURS = "paused_hours"
PAUSED_OFFLINE = "paused_offline"
RESUMED = "resumed"
STOPPED_AUTH = "stopped_auth"
STOPPED_ALL_FAILED = "stopped_all_failed"
STOPPED_ERROR = "stopped_error"
STOPPED_BY_USER = "stopped_by_user"
LEGACY = "legacy"  # history saved by versions before events existed

# How long transient failures (no internet, Rolimons down) must last before it counts as a pause.
OFFLINE_PAUSE_SECONDS = 10 * 60

# Severity drives colours/icons; "kind" drives the History filters.
OK, INFO, WARN, ERROR = "ok", "info", "warn", "error"


@dataclass(frozen=True)
class EventInfo:
    title: str
    body: str
    action: str       # what the user can do about it ("" when nothing is needed)
    severity: str     # ok | info | warn | error
    kind: str         # posted | problem | status
    notify: bool      # worth a phone notification


# Friendlier wording for replies Rolimons is known to send.
KNOWN_REJECTIONS = {
    "invalid offered item count": "The ad needs at least one item you offer (and no more than 4).",
    "invalid requested item count": "The ad asks for too many items (4 at most, including tags).",
    "invalid request tags": "One of the ad's tags isn't accepted by Rolimons.",
}


def clock(ts: float | None, ref: float | None = None) -> str:
    """'3:42 PM', or 'tomorrow 9:00 AM' / '14 Oct 9:00 AM' when it isn't the same day as `ref` (the
    time the event happened, so old History entries still read right; default now)."""
    if not ts:
        return "soon"
    ref = ref or time.time()
    t = time.localtime(ts)
    hour = time.strftime("%I:%M %p", t).lstrip("0")
    today = time.localtime(ref)
    if t.tm_yday == today.tm_yday and t.tm_year == today.tm_year:
        return hour
    tomorrow = time.localtime(ref + 86400)
    if t.tm_yday == tomorrow.tm_yday and t.tm_year == tomorrow.tm_year:
        return f"tomorrow {hour}"
    return time.strftime("%d %b ", t).lstrip("0") + hour


def _rejection(reason: str) -> str:
    text = (reason or "").strip()
    friendly = KNOWN_REJECTIONS.get(text.lower().rstrip("."))
    return friendly or (f'Rolimons said: "{text}"' if text else "Rolimons didn't say why.")


def describe(event: dict) -> EventInfo:
    code = event.get("code", LEGACY)
    p = event.get("params") or {}
    ad = p.get("ad", "")
    at = event.get("t")

    if code == STARTED:
        return EventInfo("Posting started", f"{p.get('ads', 0)} ad(s) in rotation.", "", INFO, "status", False)
    if code == POSTED:
        return EventInfo(f'Posted "{ad}"', "Your trade ad is live on Rolimons.", "", OK, "posted", False)
    if code == REJECTED:
        return EventInfo(f'Rolimons rejected "{ad}"', _rejection(p.get("reason", "")),
                         "Fix or turn off this ad in your ad list. Your other ads keep posting.", WARN, "problem", False)
    if code == SKIPPED_UNOWNED:
        items = ", ".join(p.get("items", [])) or "an item"
        return EventInfo(f'Skipped "{ad}"', f"You no longer own {items}.",
                         "Edit the ad or turn it off. It's posted again once you own the item.", WARN, "problem", False)
    if code == PAUSED_DAILY_LIMIT:
        return EventInfo("Posting paused: daily ad limit reached",
                         f"{p.get('count', 0)} ads posted in the last 24 hours (limit {p.get('cap', 0)}). "
                         f"Resumes automatically at {clock(p.get('resume_at'), at)}.",
                         "Nothing to do. You can raise the limit in Settings.", WARN, "status", True)
    if code == PAUSED_HOURS:
        return EventInfo("Posting paused: outside posting hours",
                         f"Your posting hours are {p.get('start', '')}–{p.get('end', '')}. "
                         f"Resumes automatically at {clock(p.get('resume_at'), at)}.",
                         "Nothing to do. Change the hours in Settings.", INFO, "status", True)
    if code == PAUSED_OFFLINE:
        why = "Rolimons isn't responding" if p.get("reason") == "server" else "There's no internet connection"
        return EventInfo("Posting paused: can't reach Rolimons",
                         f"{why} (for {p.get('minutes', 10)} minutes). Retrying automatically.",
                         "Check your connection. Posting resumes by itself.", WARN, "problem", True)
    if code == RESUMED:
        nxt = f" Next ad: {p['next_ad']}." if p.get("next_ad") else ""
        return EventInfo("Posting resumed", f"{p.get('after', 'The pause')} is over.{nxt}", "", OK, "status", True)
    if code == STOPPED_AUTH:
        return EventInfo("Posting stopped: signed out of Rolimons",
                         "Rolimons rejected your sign-in (it may have expired or been reset).",
                         "Sign in to Rolimons again (or set a fresh cookie), then start posting again.", ERROR, "problem", True)
    if code == STOPPED_ALL_FAILED:
        return EventInfo("Posting stopped: every ad was rejected",
                         "Rolimons rejected each of your ads in a row, so posting stopped.",
                         "Check your ads (the entries below say what Rolimons didn't like), then start posting again.", ERROR,
                         "problem", True)
    if code == STOPPED_ERROR:
        return EventInfo("Posting stopped: something went wrong", p.get("reason") or "An unexpected error occurred.",
                         "Start posting again. If it keeps happening, report it on GitHub.", ERROR, "problem", True)
    if code == STOPPED_BY_USER:
        return EventInfo("Posting stopped", "You stopped posting.", "", INFO, "status", False)

    # Legacy attempt records (result + message) from older versions.
    result = str(p.get("result", "")).upper()
    if result == "SUCCESS":
        return EventInfo(f'Posted "{ad}"', "Your trade ad is live on Rolimons.", "", OK, "posted", False)
    if result == "AUTH_ERROR":
        return describe({"code": STOPPED_AUTH, "params": p})
    if result == "REJECTED":
        return describe({"code": REJECTED, "params": {"ad": ad, "reason": p.get("message", "")}})
    if result in ("NETWORK_ERROR", "SERVER_ERROR"):
        return EventInfo("Couldn't reach Rolimons", "A post attempt failed and was retried automatically.", "",
                         INFO, "problem", False)
    if result in ("COOLDOWN", "RATE_LIMITED"):
        return EventInfo("Waited for Rolimons' cooldown", "Normal: the ad was retried shortly after.", "", INFO,
                         "status", False)
    return EventInfo("Posting update", p.get("message", "") or result.title(), "", INFO, "status", False)


# ---- History tab helpers (PC and Android) ---------------------------------------------
FILTERS = (("all", "All"), ("posted", "Posted"), ("problems", "Problems"))


def matches(info: EventInfo, flt: str) -> bool:
    if flt == "posted":
        return info.kind == "posted"
    if flt == "problems":
        return info.kind == "problem" or info.severity in (WARN, ERROR)
    return True


def day_label(ts: float) -> str:
    """'Today', 'Yesterday' or '14 Oct' (group headings in the History tab)."""
    t = time.localtime(ts)
    for offset, label in ((0, "Today"), (1, "Yesterday")):
        d = time.localtime(time.time() - offset * 86400)
        if (t.tm_year, t.tm_yday) == (d.tm_year, d.tm_yday):
            return label
    return time.strftime("%d %b", t).lstrip("0")


def time_label(ts: float) -> str:
    return time.strftime("%I:%M %p", time.localtime(ts)).lstrip("0")


def grouped(timeline: list[dict], flt: str = "all", limit: int = 150) -> list[tuple[str, list[tuple[dict, EventInfo]]]]:
    """Newest-first timeline -> [(day label, [(event, info), ...]), ...] for one filter."""
    groups: list[tuple[str, list]] = []
    shown = 0
    for event in timeline:
        info = describe(event)
        if not matches(info, flt):
            continue
        day = day_label(event["t"])
        if not groups or groups[-1][0] != day:
            groups.append((day, []))
        groups[-1][1].append((event, info))
        shown += 1
        if shown >= limit:
            break
    return groups


def summary(timeline: list[dict], posted_24h: int, cap: int) -> str:
    """One line at the top of the History tab."""
    day_ago = time.time() - 86400
    problems = sum(1 for e in timeline if e["t"] >= day_ago and matches(describe(e), "problems"))
    text = f"{posted_24h} of {cap} ads posted in the last 24h"
    if problems:
        text += f"  ·  {problems} problem{'s' if problems != 1 else ''}"
    return text


def details(event: dict, info: EventInfo) -> str:
    """Full text for the details view: what happened, what to do, and Rolimons' raw reply."""
    when = time.strftime("%d %b %Y, ", time.localtime(event["t"])).lstrip("0") + time_label(event["t"])
    parts = [info.body]
    if info.action:
        parts.append(f"What to do: {info.action}")
    parts.append(f"When: {when}")
    if event.get("raw"):
        parts.append(f"Technical details: {event['raw']}")
    return "\n\n".join(parts)
