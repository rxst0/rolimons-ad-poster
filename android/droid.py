"""Android integration (pyjnius) with desktop stand-ins so the UI can be previewed on a PC.

Everything here is a no-op or a local fallback when not running on Android.
"""
import logging
import os
import threading
import webbrowser
from pathlib import Path

log = logging.getLogger("roliposter.android")

IS_ANDROID = "ANDROID_ARGUMENT" in os.environ or "ANDROID_PRIVATE" in os.environ
PACKAGE = "io.github.rxst0.rolimonsadposter"
SERVICE_CLASS = f"{PACKAGE}.ServicePoster"
ROLIMONS_URL = "https://www.rolimons.com/"
NOTIFY_CHANNEL = "alerts"


def data_home() -> Path:
    """Private folder for config.json, .env (cookie), state and logs."""
    if IS_ANDROID:
        from android.storage import app_storage_path  # type: ignore
        return Path(app_storage_path()) / "roliposter"
    return Path(__file__).resolve().parent / ".devdata"


# ---- Java helpers -----------------------------------------------------------
def _context():
    from jnius import autoclass  # type: ignore
    activity = autoclass("org.kivy.android.PythonActivity").mActivity
    if activity is not None:
        return activity
    return autoclass("org.kivy.android.PythonService").mService


def _jstr(text: str):
    from jnius import autoclass, cast  # type: ignore
    return cast("java.lang.CharSequence", autoclass("java.lang.String")(text))


# ---- background service -------------------------------------------------------
class Engine:
    """Starts/stops the poster: an Android foreground service, or a thread on desktop."""

    def __init__(self, home: Path):
        self.home = home
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if IS_ANDROID:
            from jnius import autoclass  # type: ignore
            service = autoclass(SERVICE_CLASS)
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            service.start(activity, "icon", "Rolimons Ad Poster", "Posting your trade ads", "")
        else:
            import runner
            self._thread = threading.Thread(target=runner.run, args=(self.home,), daemon=True)
            self._thread.start()

    def stop_service(self) -> None:
        """Hard stop of the Android service (used if it stops responding to the stop command)."""
        if IS_ANDROID:
            from jnius import autoclass  # type: ignore
            autoclass(SERVICE_CLASS).stop(autoclass("org.kivy.android.PythonActivity").mActivity)


# ---- notifications ------------------------------------------------------------
def request_notification_permission() -> None:
    if not IS_ANDROID:
        return
    try:
        from android.permissions import request_permissions  # type: ignore
        request_permissions(["android.permission.POST_NOTIFICATIONS"])
    except Exception as e:
        log.debug("Notification permission request failed: %s", e)


def notify(title: str, text: str, notification_id: int = 2001) -> None:
    """Shows a notification that opens the app when tapped."""
    if not IS_ANDROID:
        log.info("[notification] %s: %s", title, text)
        return
    try:
        from jnius import autoclass, cast  # type: ignore
        Context = autoclass("android.content.Context")
        NotificationManager = autoclass("android.app.NotificationManager")
        NotificationChannel = autoclass("android.app.NotificationChannel")
        Builder = autoclass("android.app.Notification$Builder")
        PendingIntent = autoclass("android.app.PendingIntent")
        ctx = _context()
        manager = cast("android.app.NotificationManager", ctx.getSystemService(Context.NOTIFICATION_SERVICE))
        manager.createNotificationChannel(
            NotificationChannel(NOTIFY_CHANNEL, _jstr("Alerts"), NotificationManager.IMPORTANCE_DEFAULT))
        launch = ctx.getPackageManager().getLaunchIntentForPackage(ctx.getPackageName())
        pending = PendingIntent.getActivity(ctx, 0, launch,
                                            PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT)
        builder = Builder(ctx, NOTIFY_CHANNEL)
        builder.setContentTitle(_jstr(title))
        builder.setContentText(_jstr(text))
        builder.setStyle(autoclass("android.app.Notification$BigTextStyle")().bigText(_jstr(text)))
        builder.setSmallIcon(ctx.getApplicationInfo().icon)
        builder.setContentIntent(pending)
        builder.setAutoCancel(True)
        manager.notify(notification_id, builder.build())
    except Exception as e:
        log.warning("Couldn't show a notification: %s", e)


# ---- battery optimisation -------------------------------------------------------
def ignoring_battery_optimizations() -> bool | None:
    """True/False on Android, None elsewhere."""
    if not IS_ANDROID:
        return None
    try:
        from jnius import autoclass, cast  # type: ignore
        Context = autoclass("android.content.Context")
        ctx = _context()
        power = cast("android.os.PowerManager", ctx.getSystemService(Context.POWER_SERVICE))
        return bool(power.isIgnoringBatteryOptimizations(ctx.getPackageName()))
    except Exception:
        return None


def request_ignore_battery_optimizations() -> None:
    if not IS_ANDROID:
        return
    from jnius import autoclass  # type: ignore
    Intent = autoclass("android.content.Intent")
    Settings = autoclass("android.provider.Settings")
    Uri = autoclass("android.net.Uri")
    ctx = _context()
    intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
    intent.setData(Uri.parse(f"package:{ctx.getPackageName()}"))
    ctx.startActivity(intent)


def open_url(url: str) -> None:
    if IS_ANDROID:
        from jnius import autoclass  # type: ignore
        Intent = autoclass("android.content.Intent")
        Uri = autoclass("android.net.Uri")
        intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        _context().startActivity(intent)
    else:
        webbrowser.open(url)


def launch_extra(name: str) -> str | None:
    """A string extra from the launching intent (used by automated screenshot tests)."""
    if not IS_ANDROID:
        return os.environ.get(f"ROLIPOSTER_{name.upper()}")
    try:
        from jnius import autoclass  # type: ignore
        intent = autoclass("org.kivy.android.PythonActivity").mActivity.getIntent()
        value = intent.getStringExtra(name)
        return str(value) if value else None
    except Exception:
        return None


# ---- Rolimons sign-in (WebView) -----------------------------------------------------
class RolimonsLogin:
    """Opens rolimons.com in an in-app browser and watches for the _RoliVerification cookie.

    The user signs in and verifies exactly as on the website; the cookie is read from the WebView's
    own cookie store, so nothing has to be copied or pasted.
    """

    available = IS_ANDROID

    def __init__(self, on_cookie, on_close):
        self.on_cookie = on_cookie
        self.on_close = on_close
        self._layout = None
        self._listener = None

    def open(self) -> None:
        from android.runnable import run_on_ui_thread  # type: ignore
        run_on_ui_thread(self._open_ui)()

    def _open_ui(self) -> None:
        from jnius import PythonJavaClass, autoclass, java_method  # type: ignore

        class ClickListener(PythonJavaClass):
            __javainterfaces__ = ["android/view/View$OnClickListener"]
            __javacontext__ = "app"

            def __init__(self, callback):
                super().__init__()
                self.callback = callback

            @java_method("(Landroid/view/View;)V")
            def onClick(self, view):
                self.callback()

        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        WebView = autoclass("android.webkit.WebView")
        WebViewClient = autoclass("android.webkit.WebViewClient")
        CookieManager = autoclass("android.webkit.CookieManager")
        LinearLayout = autoclass("android.widget.LinearLayout")
        Button = autoclass("android.widget.Button")
        LayoutParams = autoclass("android.view.ViewGroup$LayoutParams")
        Color = autoclass("android.graphics.Color")

        layout = LinearLayout(activity)
        layout.setOrientation(LinearLayout.VERTICAL)
        from roliposter.palette import BG
        layout.setBackgroundColor(Color.parseColor(BG))
        close = Button(activity)
        close.setText(_jstr("Done"))
        self._listener = ClickListener(self.close)
        close.setOnClickListener(self._listener)
        web = WebView(activity)
        settings = web.getSettings()
        settings.setJavaScriptEnabled(True)
        settings.setDomStorageEnabled(True)
        web.setWebViewClient(WebViewClient())
        cookies = CookieManager.getInstance()
        cookies.setAcceptCookie(True)
        cookies.setAcceptThirdPartyCookies(web, True)
        layout.addView(close, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT))
        layout.addView(web, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        activity.addContentView(layout, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        web.loadUrl(ROLIMONS_URL)
        self._layout = layout

    @property
    def is_open(self) -> bool:
        return self._layout is not None

    def poll_cookie(self) -> str | None:
        """The current rolimons.com cookie header (may include _RoliVerification)."""
        try:
            from jnius import autoclass  # type: ignore
            value = autoclass("android.webkit.CookieManager").getInstance().getCookie(ROLIMONS_URL)
            return str(value) if value else None
        except Exception:
            return None

    def close(self) -> None:
        from android.runnable import run_on_ui_thread  # type: ignore
        run_on_ui_thread(self._close_ui)()

    def _close_ui(self) -> None:
        if self._layout is not None:
            from jnius import cast  # type: ignore
            parent = self._layout.getParent()
            if parent is not None:
                cast("android.view.ViewGroup", parent).removeView(self._layout)
            self._layout = None
            self.on_close()
