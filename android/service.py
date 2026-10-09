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
        final = runner.run(home)
    finally:
        if wake.isHeld():
            wake.release()
    runner.set_want_running(home, False)
    service.setAutoRestartService(False)
    if not final.get("stopped_by_user"):
        droid.notify("Posting stopped", final.get("error") or "Open the app to see why.")
    service.stopSelf()


main()
