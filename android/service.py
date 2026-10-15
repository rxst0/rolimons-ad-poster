"""Android foreground service: keeps posting while the app is closed or the screen is off."""
import droid
import runner
from jnius import autoclass, cast  # type: ignore

PythonService = autoclass("org.kivy.android.PythonService")
Context = autoclass("android.content.Context")
PowerManager = autoclass("android.os.PowerManager")


def main() -> None:
    service = PythonService.mService
    home = droid.data_home()
    if not runner.wants_running(home):
        # Android restarted a sticky service the user had already stopped.
        service.setAutoRestartService(False)
        service.stopSelf()
        return
    service.setAutoRestartService(True)
    # A partial wake lock keeps timers on schedule while the screen is off (the CPU otherwise sleeps).
    power = cast("android.os.PowerManager", service.getSystemService(Context.POWER_SERVICE))
    wake = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "RolimonsAdPoster::posting")
    wake.acquire()
    try:
        runner.run(home, on_event=notify_event)
    finally:
        if wake.isHeld():
            wake.release()
    runner.set_want_running(home, False)
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
