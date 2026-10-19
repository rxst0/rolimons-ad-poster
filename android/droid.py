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
CHANNEL_POSTING = "posting"
CHANNEL_TRADES = "trades"
POSTING_NOTIFICATION_ID = 3001  # pause/resume/stop share one slot, so the newest replaces the last
OPEN_TAB_EXTRA = "roliposter_open_tab"


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
POSTING_TEXT = "Posting your trade ads"
WATCHING_TEXT = "Checking for new Roblox trades"


class Engine:
    """Starts/stops the poster: an Android foreground service, or a thread on desktop.

    On Android the same service also checks for new trades when "Read my trades directly" is on, so it
    may already be running when posting starts; it notices want_running by itself then.
    """

    def __init__(self, home: Path):
        self.home = home
        self._thread: threading.Thread | None = None

    def start(self, text: str = POSTING_TEXT) -> None:
        if IS_ANDROID:
            import runner
            if runner.service_alive(self.home):
                return
            from jnius import autoclass  # type: ignore
            service = autoclass(SERVICE_CLASS)
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            service.start(activity, "icon", "Rolimons Ad Poster", text, "")
        elif text == POSTING_TEXT:
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


TABS_FROM_NOTIFICATIONS = ("history", "trades", "home")


def notify(title: str, text: str, notification_id: int = 2001, channel: str = NOTIFY_CHANNEL,
           tab: str | None = None) -> None:
    """Shows a notification; tapping it opens the app (on `tab` if given)."""
    if not IS_ANDROID:
        log.info("[notification] %s: %s", title, text)
        return
    try:
        from jnius import autoclass, cast  # type: ignore
        Context = autoclass("android.content.Context")
        Builder = autoclass("android.app.Notification$Builder")
        PendingIntent = autoclass("android.app.PendingIntent")
        ctx = _context()
        manager = cast("android.app.NotificationManager", ctx.getSystemService(Context.NOTIFICATION_SERVICE))
        ensure_channels(manager)
        launch = ctx.getPackageManager().getLaunchIntentForPackage(ctx.getPackageName())
        if tab in TABS_FROM_NOTIFICATIONS:
            launch.putExtra(OPEN_TAB_EXTRA, tab)
        # A different request code per tab, so each notification keeps its own "open this tab" extra.
        pending = PendingIntent.getActivity(ctx, 100 + TABS_FROM_NOTIFICATIONS.index(tab) if tab in
                                            TABS_FROM_NOTIFICATIONS else 0, launch,
                                            PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT)
        builder = Builder(ctx, channel)
        builder.setContentTitle(_jstr(title))
        builder.setContentText(_jstr(text))
        builder.setStyle(autoclass("android.app.Notification$BigTextStyle")().bigText(_jstr(text)))
        builder.setSmallIcon(ctx.getApplicationInfo().icon)
        builder.setContentIntent(pending)
        builder.setAutoCancel(True)
        manager.notify(notification_id, builder.build())
    except Exception as e:
        log.warning("Couldn't show a notification: %s", e)


def ensure_channels(manager=None) -> None:
    """Notification channels (Android lets the user mute each one separately in system settings)."""
    if not IS_ANDROID:
        return
    from jnius import autoclass, cast  # type: ignore
    NotificationManager = autoclass("android.app.NotificationManager")
    NotificationChannel = autoclass("android.app.NotificationChannel")
    if manager is None:
        Context = autoclass("android.content.Context")
        manager = cast("android.app.NotificationManager", _context().getSystemService(Context.NOTIFICATION_SERVICE))
    for channel_id, name, importance in (
            (CHANNEL_POSTING, "Posting paused, resumed or stopped", NotificationManager.IMPORTANCE_HIGH),
            (CHANNEL_TRADES, "New trades", NotificationManager.IMPORTANCE_HIGH),
            (NOTIFY_CHANNEL, "Other alerts", NotificationManager.IMPORTANCE_DEFAULT)):
        manager.createNotificationChannel(NotificationChannel(channel_id, _jstr(name), importance))


def active_notification_titles() -> list[str]:
    """Titles of this app's notifications currently shown (used by the self-test)."""
    if not IS_ANDROID:
        return []
    from jnius import autoclass, cast  # type: ignore
    Context = autoclass("android.content.Context")
    manager = cast("android.app.NotificationManager", _context().getSystemService(Context.NOTIFICATION_SERVICE))
    titles = []
    for sbn in manager.getActiveNotifications():
        title = sbn.getNotification().extras.getCharSequence("android.title")
        if title is not None:
            titles.append(str(title))  # pyjnius already converts CharSequence to str
    return titles


def opened_tab(intent=None) -> str | None:
    """The tab a tapped notification asked for (works in release builds; only a fixed set of tabs)."""
    if not IS_ANDROID:
        return None
    try:
        from jnius import autoclass  # type: ignore
        intent = intent or autoclass("org.kivy.android.PythonActivity").mActivity.getIntent()
        value = intent.getStringExtra(OPEN_TAB_EXTRA) if intent is not None else None
        if value is not None:
            intent.removeExtra(OPEN_TAB_EXTRA)  # handle it once
        value = str(value) if value else None
        return value if value in TABS_FROM_NOTIFICATIONS else None
    except Exception:
        return None


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


def move_to_background() -> None:
    """What the back button does on the main screen: hide the app instead of closing it."""
    if IS_ANDROID:
        from jnius import autoclass  # type: ignore
        autoclass("org.kivy.android.PythonActivity").mActivity.moveTaskToBack(True)
    else:
        log.debug("Back pressed on the home screen (ignored in the desktop preview).")


def system_bar_overlap(window_height: int) -> tuple[int, int]:
    """(top, bottom) pixels of the app hidden under the status bar / navigation bar.

    Android 15 draws apps edge-to-edge, under the system bars; older versions don't. So this only
    reports an overlap when the app's drawing surface really extends under the bars.
    """
    if not IS_ANDROID:
        return 0, 0
    try:
        from jnius import autoclass  # type: ignore
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        decor = activity.getWindow().getDecorView()
        insets = decor.getRootWindowInsets()
        if insets is None:
            return 0, 0
        if autoclass("android.os.Build$VERSION").SDK_INT >= 30:
            Type = autoclass("android.view.WindowInsets$Type")
            bars = insets.getInsets(Type.systemBars() | Type.displayCutout())
            top, bottom = int(bars.top), int(bars.bottom)
        else:
            top, bottom = int(insets.getSystemWindowInsetTop()), int(insets.getSystemWindowInsetBottom())
        full = int(decor.getHeight())
        if full <= 0:
            return 0, 0
        if window_height >= full - 2:          # drawn under both bars (edge-to-edge)
            return top, bottom
        if window_height >= full - bottom - 2:  # under the status bar only
            return top, 0
        return 0, 0
    except Exception as e:
        log.debug("Couldn't read system bar insets: %s", e)
        return 0, 0


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


def is_debug_build() -> bool:
    if not IS_ANDROID:
        return True
    try:
        from jnius import autoclass  # type: ignore
        ApplicationInfo = autoclass("android.content.pm.ApplicationInfo")
        return bool(_context().getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE)
    except Exception:
        return False


def launch_extra(name: str) -> str | None:
    """A string extra from the launching intent, used by automated tests.

    Only honoured in debug builds: in the released app any other app could send these extras.
    """
    if not IS_ANDROID:
        return os.environ.get(f"ROLIPOSTER_{name.upper()}")
    if not is_debug_build():
        return None
    try:
        from jnius import autoclass  # type: ignore
        intent = autoclass("org.kivy.android.PythonActivity").mActivity.getIntent()
        value = intent.getStringExtra(name)
        return str(value) if value else None
    except Exception:
        return None


# ---- Received trades tab (WebView) ---------------------------------------------------
class TradesView:
    """Roblox's trades page in a native WebView laid over the Received trades tab.

    View-only: org.roliposter.ViewOnlyWebViewClient (android/java) answers every trade-changing request
    with a local 403, so it never leaves the phone. The Roblox login stays in the WebView's own cookie
    store; only with "Read my trades directly" on does RobloxSession keep an encrypted copy (see RobloxDirect).
    """

    available = IS_ANDROID

    def __init__(self, url: str, page_script: str):
        self.url = url
        self.page_script = page_script
        self._web = None
        self._callbacks = []  # keep Java callback proxies alive until they fire

    def show(self, top_px: int, height_px: int) -> None:
        from android.runnable import run_on_ui_thread  # type: ignore
        run_on_ui_thread(self._show_ui)(int(top_px), int(height_px))

    def preload(self, top_px: int, height_px: int) -> None:
        """Creates the page hidden, so new-trade checks run without opening the tab."""
        from android.runnable import run_on_ui_thread  # type: ignore
        run_on_ui_thread(self._show_ui)(int(top_px), int(height_px), False)

    def _show_ui(self, top_px: int, height_px: int, visible: bool = True) -> None:
        from jnius import autoclass  # type: ignore
        FrameParams = autoclass("android.widget.FrameLayout$LayoutParams")
        Gravity = autoclass("android.view.Gravity")
        View = autoclass("android.view.View")
        params = FrameParams(FrameParams.MATCH_PARENT, max(height_px, 1), Gravity.TOP)
        params.topMargin = top_px
        if self._web is None:
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            WebView = autoclass("android.webkit.WebView")
            CookieManager = autoclass("android.webkit.CookieManager")
            Client = autoclass("org.roliposter.ViewOnlyWebViewClient")
            Color = autoclass("android.graphics.Color")
            from roliposter.palette import BG
            web = WebView(activity)
            settings = web.getSettings()
            settings.setJavaScriptEnabled(True)
            settings.setDomStorageEnabled(True)
            web.setBackgroundColor(Color.parseColor(BG))
            web.setWebViewClient(Client(self.page_script))
            # Bridge for the new-trade check: it only accepts trade IDs and sender names (see TradeNotifier).
            web.addJavascriptInterface(trade_notifier(), "RoliTrades")
            cookies = CookieManager.getInstance()
            cookies.setAcceptCookie(True)
            cookies.setAcceptThirdPartyCookies(web, True)
            if not visible:
                web.setVisibility(View.INVISIBLE)
            activity.addContentView(web, params)
            web.loadUrl(self.url)
            self._web = web
        elif visible:
            self._web.setLayoutParams(params)
            self._web.setVisibility(View.VISIBLE)

    def hide(self) -> None:
        if self._web is None:
            return
        from android.runnable import run_on_ui_thread  # type: ignore

        def hide_ui():
            from jnius import autoclass  # type: ignore
            # INVISIBLE (not GONE) keeps the page running, so the new-trade check carries on.
            self._web.setVisibility(autoclass("android.view.View").INVISIBLE)
        run_on_ui_thread(hide_ui)()

    def _on_ui(self, func) -> None:
        if self._web is not None:
            from android.runnable import run_on_ui_thread  # type: ignore
            run_on_ui_thread(func)()

    def reload(self) -> None:
        self._on_ui(lambda: self._web.reload())

    def go_home(self) -> None:
        self._on_ui(lambda: self._web.loadUrl(self.url))

    def go_back(self, otherwise) -> None:
        """Android back button: go back a page inside the tab, or call otherwise() on Kivy's thread."""
        if self._web is None:
            otherwise()
            return
        from kivy.clock import Clock

        def back():  # WebView methods must run on the UI thread
            if self._web.canGoBack():
                self._web.goBack()
            else:
                Clock.schedule_once(lambda *_: otherwise(), 0)
        self._on_ui(back)

    def eval_js(self, code: str, callback) -> None:
        """Runs JavaScript in the page; callback(json_text) gets the result (used by the self-test)."""
        from jnius import PythonJavaClass, java_method  # type: ignore

        class Result(PythonJavaClass):
            __javainterfaces__ = ["android/webkit/ValueCallback"]
            __javacontext__ = "app"

            @java_method("(Ljava/lang/Object;)V")
            def onReceiveValue(self, value):
                callback(str(value) if value is not None else "null")

        proxy = Result()
        self._callbacks = self._callbacks[-20:] + [proxy]
        self._on_ui(lambda: self._web.evaluateJavascript(code, proxy))

    @staticmethod
    def blocked_count() -> int:
        from jnius import autoclass  # type: ignore
        return int(autoclass("org.roliposter.ViewOnlyWebViewClient").blockedCount)


_notifier = None


def trade_notifier():
    """The one org.roliposter.TradeNotifier ("New trade from X" notifications)."""
    global _notifier
    if _notifier is None:
        from jnius import autoclass  # type: ignore
        _notifier = autoclass("org.roliposter.TradeNotifier")(_context())
    return _notifier


def autoclass_notifier():
    """The TradeNotifier class itself (static counters, used by the self-test)."""
    from jnius import autoclass  # type: ignore
    return autoclass("org.roliposter.TradeNotifier")


def set_trade_notifications(enabled: bool) -> None:
    if IS_ANDROID:
        try:
            trade_notifier().setEnabled(bool(enabled))
        except Exception as e:
            log.warning("Couldn't change trade notifications: %s", e)


def sign_out_web() -> None:
    """Clears every website sign-in in the app's WebViews (signs out of Roblox in the trades tab),
    and the stored copy "Read my trades directly" uses."""
    if not IS_ANDROID:
        return
    from jnius import autoclass  # type: ignore
    from android.runnable import run_on_ui_thread  # type: ignore
    RobloxDirect.clear()

    def clear():
        manager = autoclass("android.webkit.CookieManager").getInstance()
        manager.removeAllCookies(None)
        manager.flush()
    run_on_ui_thread(clear)()


# ---- "Read my trades directly" ------------------------------------------------------
# The app's own Java classes can only be looked up from the main thread: a Python worker thread uses
# Android's system class loader, which doesn't know them. So they're looked up once by prime_java() on
# the main thread and reused from any thread.
APP_CLASSES = ("org.roliposter.RobloxSession", "org.roliposter.RobloxApi", "org.roliposter.TradeWatcher",
               "org.roliposter.ForegroundText")
_classes: dict = {}
_app_context = None


def prime_java() -> None:
    """Call on the main thread (app start, service start) before any worker thread uses the classes below."""
    global _app_context
    if not IS_ANDROID:
        return
    from jnius import autoclass  # type: ignore
    for name in APP_CLASSES:
        if name not in _classes:
            _classes[name] = autoclass(name)
    if _app_context is None:
        _app_context = _context().getApplicationContext()


def _jclass(name: str):
    if name not in _classes:
        prime_java()  # only works on the main thread; worker threads rely on an earlier call
    return _classes[name]


def _app_ctx():
    if _app_context is None:
        prime_java()
    return _app_context


class RobloxDirect:
    """Read-only Roblox trade requests made in Java with a stored, encrypted copy of the Roblox sign-in
    (org.roliposter.RobloxSession / RobloxApi). Python only ever sees the replies, never the cookie.

    fetch() blocks: call it from a worker thread (pyjnius detaches Python threads from Java when they end),
    after prime_java() has run on the main thread.
    """

    available = IS_ANDROID

    @staticmethod
    def set_enabled(enabled: bool) -> None:
        """On: copy the sign-in from the trades page after it loads. Off: delete the copy (cookieless)."""
        if not IS_ANDROID:
            return
        session = _jclass("org.roliposter.RobloxSession")
        session.setCaptureEnabled(bool(enabled))
        if enabled:
            RobloxDirect.capture()
        else:
            session.clear(_app_ctx())

    @staticmethod
    def capture() -> None:
        """Copies the trades page's current Roblox sign-in (and applies any cookie Roblox rotated)."""
        if not IS_ANDROID:
            return
        from android.runnable import run_on_ui_thread  # type: ignore
        session, ctx = _jclass("org.roliposter.RobloxSession"), _app_ctx()
        run_on_ui_thread(lambda: session.captureFromWebView(ctx))()

    @staticmethod
    def signed_in() -> bool:
        if not IS_ANDROID:
            return False
        return bool(_jclass("org.roliposter.RobloxSession").isSignedIn(_app_ctx()))

    @staticmethod
    def clear() -> None:
        if IS_ANDROID:
            _jclass("org.roliposter.RobloxSession").clear(_app_ctx())

    @staticmethod
    def fetch(kind: str, arg: str, cursor: str = "") -> tuple[int, str]:
        """(HTTP status, reply text). Status 0 = not signed in, -1 = network error, -2 = not allowed."""
        if not IS_ANDROID:
            return 0, ""
        import json
        reply = json.loads(str(_jclass("org.roliposter.RobloxApi").fetch(_app_ctx(), kind, arg, cursor)))
        return int(reply.get("status", -1)), str(reply.get("body", ""))


def trade_watch_wanted(cfg) -> bool:
    """Should the background service check for new trades? Only with "Read my trades directly" on."""
    return (IS_ANDROID and cfg.app.direct_trades and cfg.app.notifications and cfg.app.trade_notifications
            and RobloxDirect.signed_in())


def start_trade_watcher(on: bool, interval_seconds: int = 90) -> None:
    if not IS_ANDROID:
        return
    watcher = _jclass("org.roliposter.TradeWatcher")
    if on:
        watcher.start(_app_ctx(), interval_seconds)
    else:
        watcher.stop()


def set_service_text(text: str) -> None:
    """The background service's status-bar text (posting vs. only checking for trades)."""
    if IS_ANDROID:
        _jclass("org.roliposter.ForegroundText").update(_app_ctx(), text)


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
