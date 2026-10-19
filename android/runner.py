"""Runs the posting engine and talks to the UI through two small JSON files.

On Android the engine lives in a separate foreground-service process, so the UI and engine can't share
memory: the engine writes status.json about once a second and reads control.json for stop/skip commands.
The desktop preview runs the same code in a thread, so both paths behave identically.
"""
import json
import logging
import os
import threading
import time
from pathlib import Path

STATUS_FILE = "status.json"
CONTROL_FILE = "control.json"
WANT_RUNNING_FILE = "want_running"  # present while the user wants posting on; survives service restarts
SERVICE_ALIVE_FILE = "service_alive"  # touched every few seconds while the background service runs
STALE_SECONDS = 15

log = logging.getLogger("roliposter.runner")


def write_json(path: Path, data: dict) -> None:
    """Atomic write (unique temp file + rename), retrying briefly if a reader holds the file (Windows)."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05)
    tmp.unlink(missing_ok=True)


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def send_command(home: Path, command: str) -> None:
    write_json(home / CONTROL_FILE, {"command": command, "t": time.time()})


def read_status(home: Path) -> dict:
    """The engine's last status; reports not-running if the engine stopped updating (process died)."""
    status = read_json(home / STATUS_FILE) or {}
    if status.get("running") and time.time() - status.get("updated", 0) > STALE_SECONDS:
        status["running"] = False
    return status


def set_want_running(home: Path, on: bool) -> None:
    path = home / WANT_RUNNING_FILE
    if on:
        path.write_text("1", encoding="utf-8")
    elif path.exists():
        path.unlink()


def wants_running(home: Path) -> bool:
    return (home / WANT_RUNNING_FILE).exists()


def mark_service_alive(home: Path, alive: bool = True) -> None:
    path = home / SERVICE_ALIVE_FILE
    if alive:
        path.write_text(str(time.time()), encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


def service_alive(home: Path) -> bool:
    """True while the background service (posting and/or checking for trades) is running."""
    try:
        return time.time() - float((home / SERVICE_ALIVE_FILE).read_text(encoding="utf-8")) < STALE_SECONDS
    except (OSError, ValueError):
        return False


def run(home: Path, on_event=None) -> dict:
    """Runs posting until stopped. Returns the final status dict (with 'error' / 'stopped_by_user').

    on_event(event) is called for each History event (see roliposter/events.py); the Android service uses
    it to send notifications. Stops that happen outside the posting loop are recorded here too.
    """
    os.environ["ROLIPOSTER_HOME"] = str(home)
    home.mkdir(parents=True, exist_ok=True)
    import requests

    from roliposter import events as ev
    from roliposter.logsetup import setup_logging
    from roliposter.paths import config_path, log_dir, state_path
    from roliposter.poster import AuthError, Poster
    from roliposter.startup import StartupError, prepare
    from roliposter.state import PostHistory

    setup_logging(log_dir())
    control = home / CONTROL_FILE
    if control.exists():
        control.unlink()  # ignore commands left over from a previous run
    stop_event = threading.Event()
    state = {"poster": None, "done": False, "error": None, "stopped_by_user": False, "last": None}

    def handle(event: dict) -> None:
        state["last"] = event
        if on_event is not None:
            try:
                on_event(event)
            except Exception:
                log.exception("Event handler failed")

    def record(code: str, params: dict | None = None) -> None:
        """Records a stop that happened outside the posting loop (it records its own events)."""
        handle(PostHistory(state_path()).record_event(code, params or {}))

    def snapshot() -> dict:
        p = state["poster"]
        return {
            "running": not state["done"],
            "updated": time.time(),
            "status_text": p.status_text if p else "Checking setup",
            "wait_until": p.wait_until if p else None,
            "next_ad": p.next_ad.name if p and p.next_ad else None,
            "unavailable": p.unavailable if p else {},
            "posted_24h": p.history.count_24h() if p else None,
            "error": state["error"],
            "stopped_by_user": state["stopped_by_user"],
        }

    def status_loop() -> None:
        while not state["done"]:
            command = read_json(control)
            if command:
                control.unlink(missing_ok=True)
                if command.get("command") == "stop":
                    state["stopped_by_user"] = True
                    stop_event.set()
                elif command.get("command") == "skip" and state["poster"] is not None:
                    state["poster"].skip_next()
            write_json(home / STATUS_FILE, snapshot())
            stop_event.wait(1.0)

    status_thread = threading.Thread(target=status_loop, daemon=True)
    status_thread.start()
    try:
        # Android may reuse this process for the next run; always re-read the cookie from .env.
        os.environ.pop("ROLI_VERIFICATION", None)
        session = requests.Session()
        cfg, cookie, catalog = prepare(config_path(), session, stop_event)
        if not stop_event.is_set():
            state["poster"] = Poster(cfg, config_path(), cookie, catalog, stop_event, session, on_event=handle)
            state["poster"].run()
    except AuthError as e:
        log.error("Rolimons rejected your cookie: %s", e)  # the poster already recorded STOPPED_AUTH
    except StartupError as e:
        log.error("%s", e)
        record(ev.STOPPED_ERROR, {"reason": str(e)})
    except Exception:
        log.exception("Unexpected error")
        record(ev.STOPPED_ERROR, {"reason": "An unexpected error occurred (details are in the log)."})
    finally:
        state["done"] = True
        stop_event.set()  # wakes the status loop so it exits before the final write
        status_thread.join(timeout=5)
        last = state["last"]
        if state["stopped_by_user"]:
            record(ev.STOPPED_BY_USER)
        elif last is None or not last["code"].startswith("stopped"):
            record(ev.STOPPED_ERROR, {"reason": "Posting ended unexpectedly."})
        if not state["stopped_by_user"]:
            info = ev.describe(state["last"])
            state["error"] = " ".join(part for part in (info.body, info.action) if part)
            state["error_title"] = info.title
        final = snapshot()
        final["running"] = False
        final["error_title"] = state.get("error_title")
        write_json(home / STATUS_FILE, final)
    return final
