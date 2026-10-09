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


def run(home: Path) -> dict:
    """Runs posting until stopped. Returns the final status dict (with 'error' / 'stopped_by_user')."""
    os.environ["ROLIPOSTER_HOME"] = str(home)
    home.mkdir(parents=True, exist_ok=True)
    import requests

    from roliposter.logsetup import setup_logging
    from roliposter.paths import config_path, log_dir
    from roliposter.poster import AuthError, Poster
    from roliposter.startup import StartupError, prepare

    setup_logging(log_dir())
    control = home / CONTROL_FILE
    if control.exists():
        control.unlink()  # ignore commands left over from a previous run
    stop_event = threading.Event()
    state = {"poster": None, "done": False, "error": None, "stopped_by_user": False}

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
            state["poster"] = Poster(cfg, config_path(), cookie, catalog, stop_event, session)
            state["poster"].run()
    except AuthError as e:
        log.error("Rolimons rejected your cookie: %s", e)
        state["error"] = (f"Rolimons rejected your cookie (\"{e}\"). Sign in to Rolimons again "
                          "or paste a fresh cookie, then start again.")
    except StartupError as e:
        log.error("%s", e)
        state["error"] = str(e)
    except Exception:
        log.exception("Unexpected error")
        state["error"] = "Something went wrong. See History > Activity for details."
    finally:
        state["done"] = True
        stop_event.set()  # wakes the status loop so it exits before the final write
        status_thread.join(timeout=5)
        if not state["error"] and not state["stopped_by_user"]:
            state["error"] = "Posting stopped. See History > Activity for details."
        final = snapshot()
        final["running"] = False
        write_json(home / STATUS_FILE, final)
    return final
