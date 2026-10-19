"""Android foreground service: keeps posting while the app is closed or the screen is off.

With "Read my trades directly" on, it also checks for new Roblox trades (org.roliposter.TradeWatcher),
and keeps running for that while posting is off.
"""
import threading
import time

import droid
import runner
from jnius import autoclass, cast  # type: ignore

PythonService = autoclass("org.kivy.android.PythonService")
Context = autoclass("android.content.Context")
PowerManager = autoclass("android.os.PowerManager")
CHECK_SECONDS = 3


def watch_wanted() -> bool:
    from roliposter.config import load_config
    from roliposter.paths import config_path
    try:
        return droid.trade_watch_wanted(load_config(config_path()))
    except Exception:
        return False


def main() -> None:
    service = PythonService.mService
    home = droid.data_home()
    if not runner.wants_running(home) and not watch_wanted():
        # Android restarted a sticky service the user had already stopped.
        service.setAutoRestartService(False)
        service.stopSelf()
        return
    service.setAutoRestartService(True)
    # A partial wake lock keeps timers on schedule while the screen is off (the CPU otherwise sleeps).
    power = cast("android.os.PowerManager", service.getSystemService(Context.POWER_SERVICE))
    wake = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "RolimonsAdPoster::posting")
    wake.acquire()
    done = threading.Event()

    def heartbeat():
        """Tells the app the service is running, and follows the trade-check setting (also mid-posting)."""
        shown = None
        while not done.is_set():
            runner.mark_service_alive(home)
            watching = watch_wanted()
            droid.start_trade_watcher(watching)
            if runner.wants_running(home):
                text = droid.POSTING_TEXT + (" and checking for new trades" if watching else "")
            else:
                text = droid.WATCHING_TEXT
            if text != shown:
                droid.set_service_text(text)
                shown = text
            done.wait(CHECK_SECONDS)
    beat = threading.Thread(target=heartbeat, daemon=True)
    beat.start()

    try:
        while True:
            if runner.wants_running(home):
                runner.run(home, on_event=notify_event)
                runner.set_want_running(home, False)
                continue
            if not watch_wanted():
                break
            time.sleep(CHECK_SECONDS)
    finally:
        done.set()
        beat.join(timeout=10)
        droid.start_trade_watcher(False)
        runner.mark_service_alive(home, False)
        if wake.isHeld():
            wake.release()
    service.setAutoRestartService(False)
    service.stopSelf()


def notify_event(event: dict) -> None:
    """Pauses, resumes and stops become a phone notification (they share one slot, so 'resumed'
    replaces 'paused'). Tapping it opens the History tab."""
    from roliposter import events as ev
    from roliposter.config import load_config
    from roliposter.paths import config_path
    info = ev.describe(event)
    if not info.notify:
        return
    try:
        if not load_config(config_path()).app.notifications:
            return
    except Exception:
        pass
    body = " ".join(part for part in (info.body, info.action) if part)
    droid.notify(info.title, body, notification_id=droid.POSTING_NOTIFICATION_ID,
                 channel=droid.CHANNEL_POSTING, tab="history")


main()
