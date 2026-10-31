"""Rolimons Ad Poster - Android app (Kivy). Also runs on a PC for previewing: python android/main.py"""
import copy
import logging
import os
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if not (HERE / "roliposter").exists():
    sys.path.insert(0, str(HERE.parent))  # desktop preview: use the repo's roliposter package

import droid  # noqa: E402

HOME = droid.data_home()
HOME.mkdir(parents=True, exist_ok=True)
os.environ["ROLIPOSTER_HOME"] = str(HOME)

import requests  # noqa: E402
from kivy.app import App  # noqa: E402
from kivy.clock import Clock, mainthread  # noqa: E402
from kivy.core.window import Window  # noqa: E402
from kivy.factory import Factory  # noqa: E402
from kivy.graphics import Color, Ellipse, Line, Rectangle  # noqa: E402
from kivy.lang import Builder  # noqa: E402
from kivy.metrics import dp  # noqa: E402
from kivy.properties import BooleanProperty, ColorProperty, ListProperty, NumericProperty, StringProperty  # noqa: E402
from kivy.uix.behaviors import ButtonBehavior  # noqa: E402
from kivy.uix.boxlayout import BoxLayout  # noqa: E402
from kivy.uix.label import Label  # noqa: E402
from kivy.uix.modalview import ModalView  # noqa: E402
from kivy.uix.screenmanager import Screen, ScreenManager, SlideTransition  # noqa: E402
from kivy.uix.widget import Widget  # noqa: E402
from kivy.utils import get_color_from_hex  # noqa: E402

import runner  # noqa: E402
from roliposter import __version__  # noqa: E402
from roliposter import events as ev  # noqa: E402
from roliposter import palette as P  # noqa: E402
from roliposter.config import (MAX_OFFER_ITEMS, MAX_REQUEST_SLOTS, VALID_TAGS, Ad, Config,  # noqa: E402
                               ConfigError, load_config, save_config, validate_config)
from roliposter.cookie import (COOKIE_ENV_VAR, clean_cookie, cookie_info, get_cookie,  # noqa: E402
                               load_env_file, looks_like_cookie, save_env_value)
from roliposter.inventory import fetch_inventory, missing_offer_items  # noqa: E402
from roliposter.items import ItemCatalog, fetch_catalog  # noqa: E402
from roliposter.logsetup import REDACTOR, setup_logging  # noqa: E402
from roliposter.paths import cache_dir, config_path, env_path, log_dir, state_path  # noqa: E402
from roliposter.poster import fmt_duration  # noqa: E402
from roliposter.roblox_trades import (KINDS, KIND_LABELS, ago, parse_details, parse_list, sort_trades,  # noqa: E402
                                      verdict)
from roliposter.portfolio import RANGES, PriceLog, fetch_best_prices, fetch_history, totals  # noqa: E402
from roliposter.state import PostHistory  # noqa: E402
from roliposter.thumbs import ThumbnailCache  # noqa: E402
from roliposter.updates import check_for_update  # noqa: E402
from roliposter.trades_viewer import TRADE_POLL_JS, TRADES_URL, VIEW_ONLY_JS  # noqa: E402
from roliposter.values import evaluate_ad  # noqa: E402

log = logging.getLogger("roliposter.app")
COOKIE_WARN_DAYS = 3
HELP_TEXT = """[b]Getting started[/b]

[b]1. Sign in to Rolimons[/b]
Tap "Sign in to Rolimons" on the Ads tab, then log in and verify like on the website. The app picks up your Rolimons cookie by itself. (On a PC you can also copy the _RoliVerification cookie and use "Paste cookie".)

[b]2. Make ads[/b]
Tap "+ New ad", search items by name, tap Offer or Want, pick tags, and save. Ads offering items you no longer own are skipped automatically.

[b]3. Start posting[/b]
Tap "Start posting". One ad goes out about every 15 minutes (Rolimons' cooldown) with a small random delay. A notification stays while it posts, even with the screen off. In Settings, tap "Allow running in the background" so Android doesn't pause it.

[b]Trades[/b]
The Trades tab shows Roblox's trades page. Sign in to Roblox there the first time. It is view-only: accepting, declining, countering and sending are blocked inside the app. Respond on roblox.com or in the Roblox app. Settings > "Sign out of Roblox" signs you out.

[b]Items[/b]
The Items tab shows the limiteds in your Rolimons inventory, their total value and RAP (robux), and a chart of your value over the last day, month, 6 months or year (from your Rolimons player page). When you make an ad, "Add item you offer" lists only items you own.

[b]Read my trades directly (optional)[/b]
Turn this on in Settings to see your trades as a list in the app (received, sent, completed, inactive) with item pictures and Rolimons values, sorted newest first or by best or worst deal, and to get alerts for new and accepted trades even when the app is closed. To do this, the app keeps an encrypted copy of your Roblox sign-in (.ROBLOSECURITY) on this phone and uses it only to read your trades. It's never sent anywhere except Roblox, and it can't be used to accept, decline or send trades. Turning the option off deletes the copy.

[b]Notifications[/b]
You get a notification when posting pauses (daily ad limit, outside your posting hours, no internet), when it resumes, and if it stops. Tap it to see why in History. Once you're signed in to Roblox in the Trades tab, you also get "New trade from ..." when someone sends you a trade (Settings > "Notify me about new Roblox trades"). Without "Read my trades directly", Android only checks while the app is open or recently used. With it, the app checks every couple of minutes in the background (status bar: "Checking for new Roblox trades"), and also tells you "... accepted your trade" when someone accepts a trade you sent. New-trade alerts show what you would give and get, and the % gain or loss. Tap it to see the trade in Completed.

[b]History[/b]
Every post, pause and problem in plain English. Use Problems to see only what went wrong, and tap an entry to see what to do about it.

[b]Safety[/b]
This app never asks you to type or paste your Roblox password or .ROBLOSECURITY cookie. Anyone who asks you to paste those is trying to steal your account. Your Roblox sign-in is only read if you turn on "Read my trades directly", and then only to read your trades.

Run posting on one device at a time: two devices posting for the same account hit each other's cooldown.
"""
TABS = ("home", "trades", "items", "history", "settings", "help")
DIRECT_TRADES_TEXT = ("Your trades now show as a list in the Trades tab, and new-trade alerts work with the app "
                      "closed.\n\nThe app keeps an encrypted copy of your Roblox sign-in on this phone and uses it "
                      "only to read your trades. Turn this off any time to delete the copy.\n\n"
                      "If you aren't signed in to Roblox yet, open the Trades tab and sign in there.")


def asset(relative: str) -> Path:
    """Shared assets: copied next to main.py in the APK, or the repo's assets/ in the desktop preview."""
    bundled = HERE / relative
    return bundled if bundled.exists() else HERE.parent / relative


def register_fonts() -> None:
    """Makes Inter (the PC app's font too) the default for every label."""
    from kivy.core.text import LabelBase
    regular, bold = asset(P.FONT_FILES["regular"]), asset(P.FONT_FILES["bold"])
    if regular.exists() and bold.exists():
        LabelBase.register(name="Roboto", fn_regular=str(regular), fn_bold=str(bold))


# ---- widgets -------------------------------------------------------------------
class FlatButton(ButtonBehavior, Label):
    bg = ColorProperty()
    bg_down = ColorProperty()


class Chip(ButtonBehavior, Label):
    selected = BooleanProperty(False)


class Switchy(ButtonBehavior, Widget):
    active = BooleanProperty(False)

    def on_release(self):
        self.active = not self.active


class SettingRow(BoxLayout):
    text = StringProperty("")
    active = BooleanProperty(False)


class ItemRow(BoxLayout):
    thumb = StringProperty("")
    name = StringProperty("")
    value = StringProperty("")
    warn = BooleanProperty(False)

    def add_action(self, text: str, callback, accent: bool = False) -> None:
        btn = FlatButton(text=text, size_hint=(None, None), size=(max(56, len(text) * 11 + 28), 40),
                         font_size="14sp")
        if accent:
            btn.bg, btn.bg_down = get_color_from_hex(P.ACCENT), get_color_from_hex(P.ACCENT_PRESSED)
        btn.bind(on_release=lambda *_: callback())
        self.ids.actions.add_widget(btn)


class AdCard(ButtonBehavior, BoxLayout):
    title = StringProperty("")
    summary = StringProperty("")
    badge = StringProperty("")
    active = BooleanProperty(True)
    warned = BooleanProperty(False)

    def __init__(self, **kw):
        self.register_event_type("on_toggle")
        super().__init__(**kw)

    def on_toggle(self, value):
        pass


class Notice(ModalView):
    title = StringProperty("")
    message = StringProperty("")

    def __init__(self, title: str, message: str, buttons=(("OK", None),), **kw):
        super().__init__(title=title, message=message, **kw)
        for i, (text, callback) in enumerate(buttons):
            btn = FlatButton(text=text)
            if i == len(buttons) - 1:
                btn.bg, btn.bg_down = get_color_from_hex(P.ACCENT), get_color_from_hex(P.ACCENT_PRESSED)
                btn.color = (1, 1, 1, 1)

            def press(*_, cb=callback):
                self.dismiss()
                if cb:
                    cb()
            btn.bind(on_release=press)
            self.ids.buttons.add_widget(btn)


# ---- screens -------------------------------------------------------------------
class HomeScreen(Screen):
    pass


class NavButton(ButtonBehavior, Label):
    tab = StringProperty("")


LIST_ERRORS = {
    0: "Sign in to Roblox on the Roblox page first.",
    401: "Roblox signed you out. Sign in again on the Roblox page.",
    429: "Roblox is busy. Tap Reload in a minute.",
    -1: "Couldn't reach Roblox. Check your internet connection.",
}


class TradeCard(ButtonBehavior, BoxLayout):
    """One trade in the app's own trades list: who with, item pictures on each side, and values."""
    partner = StringProperty("")
    when = StringProperty("")
    summary = StringProperty("Loading items...")
    tone = StringProperty("loading")
    note = StringProperty("")

    def __init__(self, trade, **kw):
        super().__init__(partner=trade.partner_name, when=ago(trade.created), **kw)
        self.trade = trade
        self.details = None

    def show(self, details) -> None:
        app = App.get_running_app()
        self.details = details
        self.tone, self.summary = verdict(details)
        self.note = "Projected item in what you get" if details.has_projected else ""
        for box, side in ((self.ids.give_box, details.give), (self.ids.get_box, details.get)):
            box.clear_widgets()
            for item in side.items:
                box.add_widget(Factory.TradeThumb(source=app.thumb_source(item.asset_id)))
            if side.robux:
                box.add_widget(Factory.Muted(text=f"+R$ {side.robux:,}", size_hint_x=None, width=dp(80),
                                             height=dp(34)))
            if not side.items and not side.robux:
                box.add_widget(Factory.Muted(text="Nothing", height=dp(34)))


class TradesScreen(Screen):
    """Roblox's trades page (WebView), or with "Read my trades directly" the app's own list."""
    placeholder = StringProperty("Loading Roblox..." if droid.TradesView.available else
                                 "The Received trades tab works in the Android app.\n\n"
                                 "It shows Roblox's own trades page, view-only.")
    direct = BooleanProperty(False)   # option on and signed in: the list is available
    page = BooleanProperty(False)     # showing the Roblox page instead of the list
    kind = StringProperty("inbound")
    sort = StringProperty("newest")   # newest / best / worst (see roblox_trades.sort_trades)
    status_text = StringProperty("")
    more = BooleanProperty(False)

    def __init__(self, **kw):
        super().__init__(**kw)
        self._token = None
        self._cursor = ""
        self._loaded_at = 0.0
        self._cards: list = []  # TradeCards in Roblox's order (newest first)
        self._raw_details: dict[int, str] = {}  # trade ID -> Roblox's reply (details never change)

    @property
    def native(self) -> bool:
        return self.direct and not self.page

    def on_enter(self):
        Clock.schedule_once(lambda *_: self.apply_view(), 0)

    def on_pre_leave(self):
        App.get_running_app().hide_trades_view()

    def apply_view(self):
        """Shows the WebView or the list, loading the list if it's old."""
        app = App.get_running_app()
        if self.manager is None or self.manager.current != "trades":
            return
        if self.native:
            app.hide_trades_view()
            if time.time() - self._loaded_at > 60:
                self.load()
        else:
            if app.cfg.app.direct_trades:
                droid.RobloxDirect.capture()  # hands the page any cookie Roblox rotated in the background
            app.show_trades_view()

    def first_button(self):
        if self.direct:
            self.page = not self.page
            self.apply_view()
        elif App.get_running_app().trades_view:
            App.get_running_app().trades_view.go_home()

    def reload(self):
        if self.native:
            self.load()
        elif App.get_running_app().trades_view:
            App.get_running_app().trades_view.reload()

    def set_kind(self, kind: str):
        if kind in KINDS:
            self.kind = kind
            self.load()

    def set_sort(self, how: str):
        self.sort = how
        self.resort()
        self.ids.trades_scroll.scroll_y = 1

    def resort(self):
        """Puts the cards in the chosen order; trades still loading their items stay at the end."""
        box = self.ids.trades_box
        ordered = sort_trades([(c, c.details) for c in self._cards], self.sort)
        box.clear_widgets()
        for card, _details in ordered:
            box.add_widget(card)

    def load(self, more: bool = False):
        token = object()
        self._token = token
        self._loaded_at = time.time()
        if not more:
            self._cursor = ""
            self._cards = []
            self.ids.trades_box.clear_widgets()
            self.ids.trades_scroll.scroll_y = 1
        self.status_text = "Loading..."
        self.more = False
        threading.Thread(target=self._fetch, args=(token, self.kind, self._cursor), daemon=True).start()

    def _fetch(self, token, kind: str, cursor: str):
        try:
            self._fetch_all(token, kind, cursor)
        except Exception as e:  # never leave the list stuck on "Loading..."
            log.exception("Loading trades failed")
            self._failed(token, -4, f"{type(e).__name__}: {e}"[:200])

    def _fetch_all(self, token, kind: str, cursor: str):
        status, body = droid.RobloxDirect.fetch("list", kind, cursor)
        if status != 200:
            return self._failed(token, status)
        try:
            trades, next_cursor = parse_list(body)
        except (ValueError, AttributeError, TypeError):
            return self._failed(token, -3)
        self._listed(token, trades, next_cursor)
        for trade in trades:
            if self._token is not token:
                return
            raw = self._raw_details.get(trade.id)
            if raw is None:
                status, raw = droid.RobloxDirect.fetch("trade", str(trade.id))
                if status == 429:  # Roblox limits how fast trades can be read
                    time.sleep(6)
                    status, raw = droid.RobloxDirect.fetch("trade", str(trade.id))
                if status != 200:
                    self._no_details(token, trade.id)
                    continue
                self._raw_details[trade.id] = raw
            try:
                details = parse_details(raw, trade.partner_id, App.get_running_app().catalog)
            except (ValueError, AttributeError, TypeError):
                self._no_details(token, trade.id)
                continue
            self._detailed(token, trade.id, details)

    @mainthread
    def _failed(self, token, status: int, detail: str = ""):
        if self._token is not token:
            return
        if detail:
            self.status_text = f"Couldn't load your trades. Tap Reload to try again.\n\n({detail})"
        else:
            self.status_text = LIST_ERRORS.get(status, f"Roblox replied with an error ({status}). "
                                                       "Tap Reload to try again.")
        self._loaded_at = 0.0
        if status in (0, 401):
            droid.RobloxDirect.clear()  # shows the Roblox page to sign in again
            App.get_running_app().sync_direct_trades()

    @mainthread
    def _listed(self, token, trades, next_cursor: str):
        if self._token is not token:
            return
        box = self.ids.trades_box
        for trade in trades:
            card = TradeCard(trade)
            card.bind(on_release=lambda c: self.open(c))
            self._cards.append(card)
            box.add_widget(card)
        self._cursor = next_cursor
        self.more = bool(next_cursor)
        self.status_text = "" if box.children else f"No {KIND_LABELS[self.kind].lower()} trades."

    def _card(self, trade_id: int):
        return next((c for c in self._cards if c.trade.id == trade_id), None)

    @mainthread
    def _detailed(self, token, trade_id: int, details):
        card = self._card(trade_id) if self._token is token else None
        if card:
            card.show(details)
            if self.sort != "newest":
                self.resort()
            App.get_running_app().request_thumbs([i.asset_id for i in details.give.items + details.get.items])

    @mainthread
    def _no_details(self, token, trade_id: int):
        card = self._card(trade_id) if self._token is token else None
        if card:
            card.summary, card.tone = "Couldn't load the items. Tap Reload to try again.", "loading"

    def refresh_thumbs(self):
        for card in self._cards:
            if card.details:
                card.show(card.details)

    def open(self, card):
        if card.details is None:
            return
        app = App.get_running_app()
        app.sm.get_screen("trade").load(card.trade, card.details)
        app.show("trade")


class TradeScreen(Screen):
    """One trade from the app's trades list: every item on both sides, with values. View only."""
    title = StringProperty("Trade")
    summary = StringProperty("")
    tone = StringProperty("even")
    note = StringProperty("")

    def load(self, trade, details):
        self.trade, self.details = trade, details
        self.title = f"Trade with {trade.partner_name}"
        self.refresh()
        self.ids.scroll.scroll_y = 1

    def refresh(self):
        app = App.get_running_app()
        details = self.details
        self.tone, self.summary = verdict(details)
        when = ago(self.trade.created)
        kind = KIND_LABELS.get(app.sm.get_screen("trades").kind, "")
        self.note = f"{kind} trade, created {when}." if when else f"{kind} trade."
        for box, side, robux_note in ((self.ids.give_box, details.give, ""),
                                      (self.ids.get_box, details.get, "  (you get 70% after Roblox's fee)")):
            box.clear_widgets()
            for item in side.items:
                box.add_widget(app.trade_item_row(item))
            if side.robux:
                box.add_widget(Factory.Txt(text=f"R$ {side.robux:,}{robux_note}"))
            if not side.items and not side.robux:
                box.add_widget(Factory.Muted(text="Nothing"))

    def open_roblox(self):
        droid.open_url("https://www.roblox.com/trades")


class HelpScreen(Screen):
    text = StringProperty(HELP_TEXT)


class CookieScreen(Screen):
    def on_pre_enter(self):
        self.ids.cookie.text = ""

    def save(self):
        app = App.get_running_app()
        if app.save_cookie(self.ids.cookie.text):
            app.go_back()


SEVERITY_COLORS = {ev.OK: P.OK, ev.INFO: P.ACCENT, ev.WARN: P.WARN, ev.ERROR: P.BAD}


class EventRow(ButtonBehavior, BoxLayout):
    """One History entry: coloured marker, plain-English title, time and a short explanation."""
    title = StringProperty("")
    subtitle = StringProperty("")
    marker = ColorProperty()


class HistoryScreen(Screen):
    """Plain-English history (see roliposter/events.py). Tap an entry for what to do and the raw reply."""
    filter = StringProperty("all")
    show_log = BooleanProperty(False)

    def on_pre_enter(self):
        self.refresh()

    def set_filter(self, flt: str):
        self.filter = flt
        self.refresh()

    def refresh(self):
        app = App.get_running_app()
        history = PostHistory(state_path())
        timeline = history.timeline()
        self.ids.summary.text = ev.summary(timeline, history.count_24h(), app.cfg.max_ads_per_24h)
        for key, _label in ev.FILTERS:
            self.ids[f"filter_{key}"].selected = key == self.filter
        box = self.ids.events
        box.clear_widgets()
        groups = ev.grouped(timeline, self.filter)
        if not groups:
            box.add_widget(Factory.Muted(text={"posted": "No ads posted yet.",
                                               "problems": "No problems. Everything is working."}
                                         .get(self.filter, "Nothing here yet. Start posting on the Ads tab.")))
        for day, entries in groups:
            box.add_widget(Factory.FieldLabel(text=day.upper()))
            for event, info in entries:
                row = EventRow(title=info.title, subtitle=f"{ev.time_label(event['t'])}  ·  {info.body}",
                               marker=get_color_from_hex(SEVERITY_COLORS.get(info.severity, P.MUTED)))
                row.bind(on_release=lambda _r, e=event, i=info: app.notice(i.title, ev.details(e, i)))
                box.add_widget(row)
        self.load_log()

    def toggle_log(self):
        self.show_log = not self.show_log
        self.load_log()

    def load_log(self):
        if not self.show_log:
            self.ids.activity.text = ""
            return
        try:
            lines = (log_dir() / "poster.log").read_text(encoding="utf-8").splitlines()[-60:]
        except OSError:
            lines = []
        self.ids.activity.text = "\n".join(line[11:] for line in lines) or "No activity yet."


class SettingsScreen(Screen):
    battery_text = StringProperty("")

    def on_pre_enter(self):
        c = App.get_running_app().cfg
        ids = self.ids
        self.set_order(c.rotation)
        ids.jmin.text, ids.jmax.text = f"{c.jitter_seconds[0]:g}", f"{c.jitter_seconds[1]:g}"
        ids.max_ads.text = str(c.max_ads_per_24h)
        ids.skip_unowned.active = c.skip_unowned_items
        ids.hours_on.active = c.posting_hours.enabled
        ids.hstart.text, ids.hend.text = c.posting_hours.start, c.posting_hours.end
        ids.value_on.active = c.value_mode.enabled
        ids.overpay.text = f"{c.value_mode.overpay_warn_percent:g}"
        ids.skip_overpay.active = c.value_mode.skip_overpaying_ads
        ids.smart_pick.active = c.value_mode.strategy == "pick"
        ids.notify_on.active = c.app.notifications
        ids.trade_notify_on.active = c.app.trade_notifications
        ids.direct_trades.active = c.app.direct_trades
        ids.updates_on.active = c.app.check_updates
        self.refresh_battery()

    def refresh_battery(self):
        ignoring = droid.ignoring_battery_optimizations()
        self.battery_text = ("" if ignoring in (None, True) else
                             "Android may pause posting to save battery. Allow the app to run in the "
                             "background so ads keep going with the screen off.")

    def sign_out_roblox(self):
        app = App.get_running_app()
        if not droid.TradesView.available:
            return app.notice("Roblox trades", "Signing in to Roblox happens in the Android app.")
        droid.sign_out_web()
        if app.trades_view:
            app.trades_view.go_home()
        app.sync_direct_trades()
        app.notice("Signed out", "You're signed out of Roblox in this app.")

    def request_battery(self):
        droid.request_ignore_battery_optimizations()
        Clock.schedule_once(lambda *_: self.refresh_battery(), 3)

    def set_order(self, order: str):
        self._order = order
        self.ids.order_seq.selected = order == "sequential"
        self.ids.order_rand.selected = order == "random"

    def save(self):
        app = App.get_running_app()
        ids = self.ids
        try:
            jmin, jmax = float(ids.jmin.text or 0), float(ids.jmax.text or 0)
            max_ads = int(ids.max_ads.text or 0)
            overpay = float(ids.overpay.text or 0)
        except ValueError:
            return app.notice("Settings", "Please enter numbers only.")
        c = copy.deepcopy(app.cfg)
        c.rotation = self._order
        c.jitter_seconds = [jmin, jmax]
        c.max_ads_per_24h = max_ads
        c.skip_unowned_items = ids.skip_unowned.active
        c.posting_hours.enabled = ids.hours_on.active
        c.posting_hours.start, c.posting_hours.end = ids.hstart.text.strip(), ids.hend.text.strip()
        c.value_mode.enabled = ids.value_on.active or ids.skip_overpay.active or ids.smart_pick.active
        c.value_mode.overpay_warn_percent = overpay
        c.value_mode.skip_overpaying_ads = ids.skip_overpay.active
        c.value_mode.strategy = "pick" if ids.smart_pick.active else "warn"
        c.app.notifications = ids.notify_on.active
        c.app.trade_notifications = ids.trade_notify_on.active
        c.app.direct_trades = ids.direct_trades.active
        c.app.check_updates = ids.updates_on.active
        problems = [e for e in validate_config(c) if not e.startswith(("No ads", "All ads", "roblox_user_id"))
                    and not e.startswith("Ad '")]
        if problems:
            return app.notice("Check your settings", "\n".join(problems))
        turned_on = c.app.direct_trades and not app.cfg.app.direct_trades
        app.cfg = c
        app.persist()
        app.apply_trade_notifications()
        if turned_on and droid.RobloxDirect.available:
            droid.request_notification_permission()
            app.notice("Read my trades directly", DIRECT_TRADES_TEXT)
        else:
            app.toast("Settings saved")


LINE_COLORS = {"value": P.ACCENT, "rap": "#a78bfa", "price": P.WARN}  # chart lines and their legend
LINE_NAMES = {"value": "Value", "rap": "RAP", "price": "Price"}


class ValueChart(Widget):
    """A line chart of several series on one scale: series = [(hex color, [(unix time, value), ...]), ...]."""
    series = ListProperty([])

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(series=self.redraw, size=self.redraw, pos=self.redraw)

    def redraw(self, *_):
        self.canvas.clear()
        lines = [(color, pts) for color, pts in self.series if pts]
        if not lines or self.width < 10:
            return
        t0 = min(pts[0][0] for _c, pts in lines)
        t1 = max(pts[-1][0] for _c, pts in lines)
        values = [v for _c, pts in lines for _t, v in pts]
        lo, hi = min(values), max(values)
        pad = (hi - lo) * 0.08 or max(1, hi * 0.01)
        lo, hi = lo - pad, hi + pad
        with self.canvas:
            Color(*get_color_from_hex(P.BORDER))
            for frac in (0.0, 0.5, 1.0):  # light guide lines at the bottom, middle and top
                y = self.y + frac * self.height
                Line(points=[self.x, y, self.right, y], width=1)
            for color, pts in lines:
                coords = []
                for t, v in pts:
                    coords += [self.x + (t - t0) / ((t1 - t0) or 1) * self.width,
                               self.y + (v - lo) / (hi - lo) * self.height]
                Color(*get_color_from_hex(color))
                if len(pts) == 1:  # one reading so far (current price): a dot
                    Ellipse(pos=(coords[0] - dp(3), coords[1] - dp(3)), size=(dp(6), dp(6)))
                else:
                    Line(points=coords, width=dp(1.6), joint="round", cap="round")


def short_number(n: int) -> str:
    for size, unit in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(n) >= size:
            return f"{n / size:.2f}".rstrip("0").rstrip(".") + unit
    return f"{n:,}"


class ItemsScreen(Screen):
    """What you own on Roblox (your Rolimons inventory), what it's worth, and value, RAP and price over time."""
    value_text = StringProperty("")
    rap_text = StringProperty("")
    price_text = StringProperty("")
    count_text = StringProperty("")
    change_text = StringProperty("")
    legend_text = StringProperty("")
    tone = StringProperty("even")
    range = StringProperty("1m")
    chart_note = StringProperty("")
    message = StringProperty("")

    def on_pre_enter(self):
        app = App.get_running_app()
        app.load_portfolio()
        self.refresh()

    def set_range(self, key: str):
        self.range = key
        self.refresh()

    def reload(self):
        App.get_running_app().load_portfolio(force=True)
        self.refresh()

    def refresh(self):
        app = App.get_running_app()
        box = self.ids.holdings
        box.clear_widgets()
        inventory = app.inventory
        if app.cfg.roblox_user_id <= 0:
            self.message = "Sign in to Rolimons on the Ads tab to see your items."
        elif inventory is None:
            self.message = "Loading your items..."
        elif inventory.private:
            self.message = "Your Roblox inventory is private, so Rolimons can't see your items."
        else:
            self.message = ""
        if inventory is None or inventory.private:
            self.value_text = self.rap_text = self.price_text = self.count_text = ""
            self.change_text = self.legend_text = self.chart_note = ""
            self.ids.chart.series = []
            return
        t = totals(inventory, app.catalog, app.best_prices)
        if t.price is not None and app.catalog:
            app.price_log.record(t.price)  # the app's own daily record of what your items cost now
        self.value_text = f"{t.value:,}"
        self.rap_text = f"{t.rap:,}"
        self.price_text = ("loading..." if t.price is None else
                           f"{t.price:,}" + (f"  ({t.unpriced} with no realistic seller, not counted)" if t.unpriced else ""))
        self.count_text = f"{t.items} item{'s' if t.items != 1 else ''}"
        self.refresh_chart(t)
        ids = []
        for h in t.holdings:
            parts = [f"Value {h.value:,}", f"RAP {h.rap:,}"]
            if app.best_prices is not None:
                parts.append(f"Price {h.price:,}" if h.price else "No realistic seller")
            if h.count > 1:
                parts.insert(0, f"{h.count} copies")
            if h.on_hold:
                parts.append(f"{h.on_hold} on hold")
            if h.projected:
                parts.append(f"[color={P.WARN}]Projected[/color]")
            box.add_widget(ItemRow(thumb=app.thumb_source(h.item_id), name=h.name, value="  ·  ".join(parts),
                                   warn=h.projected))
            ids.append(h.item_id)
        app.request_thumbs(ids)

    def refresh_chart(self, t):
        app = App.get_running_app()
        history = app.value_history
        seconds = dict((key, secs) for key, _label, secs in RANGES)[self.range]
        label = dict((key, lbl) for key, lbl, _s in RANGES)[self.range]
        parts = {}
        if history is not None:
            parts["value"] = history.value.with_point(t.value).since(seconds)
            parts["rap"] = history.rap.with_point(t.rap).since(seconds)
        if t.price is not None:
            parts["price"] = app.price_log.series().since(seconds)
        self.ids.chart.series = [(LINE_COLORS[k], list(zip(s.times, s.values))) for k, s in parts.items()]
        legend, changes = [], []
        for key, s in parts.items():
            if not s.values:
                continue
            legend.append(f"[color={LINE_COLORS[key]}][b]—[/b][/color] {LINE_NAMES[key]} {short_number(s.values[-1])}")
            diff, pct = s.change()
            if len(s.values) > 1:
                changes.append(f"{LINE_NAMES[key]} {'+' if diff >= 0 else '-'}{short_number(abs(diff))}"
                               + (f" ({pct:+.1f}%)" if pct is not None else ""))
        self.legend_text = "     ".join(legend)
        self.change_text = (f"In {label}:  " + "   ·   ".join(changes)) if changes else ""
        diff = parts["value"].change()[0] if "value" in parts else 0
        self.tone = "even" if diff == 0 else "win" if diff > 0 else "loss"
        notes = []
        if history is None:
            notes.append(app.history_status or "Loading value and RAP history...")
        if "price" in parts and len(app.price_log.series().values) < 2:
            notes.append("Price history starts today: the app saves your items' current price once a day.")
        elif "price" in parts and len(parts["price"].values) < 2:
            notes.append("Not enough price history for this range yet.")
        self.chart_note = "\n".join(notes)


class PickerScreen(Screen):
    """Full-screen item search: tap an item to add it to the ad being edited."""
    title = StringProperty("Add item")
    side = "want"

    def open_for(self, side: str):
        self.side = side
        self.title = "Add item you offer" if side == "offer" else "Add item you want"
        self.ids.search.text = ""
        self.search()

    def on_enter(self):
        # Offers start with your items listed, so the keyboard only opens for "want".
        if self.side != "offer":
            Clock.schedule_once(lambda *_: setattr(self.ids.search, "focus", True), 0.15)

    def schedule_search(self):
        Clock.unschedule(self.search)
        Clock.schedule_once(self.search, 0.3)

    def _note(self, text: str):
        self.ids.results.add_widget(Factory.Muted(text=text, halign="center", height=dp(40)))

    def search(self, *_):
        """Offers: only items in your Rolimons inventory (all of them until you type). Wants: any item."""
        app = App.get_running_app()
        box = self.ids.results
        box.clear_widgets()
        q = self.ids.search.text.strip().lower()
        owned = app.owned_counts() if self.side == "offer" else None
        if self.side == "offer" and owned is None:
            self._note("Your Rolimons inventory isn't available (not loaded yet, or private), so this searches "
                       "all items.")
        if not q and owned is None:
            if self.side != "offer":
                self._note("Type to search all Rolimons items.")
            return
        if not app.catalog:
            return self._note("Item list still loading...")
        pool = ([i for i in (app.catalog.get(item_id) for item_id in owned) if i] if owned is not None
                else app.catalog.items.values())
        matches = []
        for item in pool:
            if not q or q == str(item.id) or q in item.name.lower() or q == item.acronym.lower():
                rank = (0 if q and q in (item.acronym.lower(), str(item.id)) else
                        1 if item.name.lower().startswith(q) else 2)
                matches.append((rank, -item.default_value, item.id))
        matches.sort()
        ids = [m[2] for m in matches[:200 if owned is not None else 30]]
        if owned is not None:
            self._note(f"Your items ({len(ids)})" if not q else f"Your items matching \"{q}\" ({len(ids)})")
        for item_id in ids:
            row = app.item_row(item_id)
            if owned and owned.get(item_id, 0) > 1:
                row.name += f"  ×{owned[item_id]}"
            row.add_action("Add", lambda i=item_id: self.choose(i), accent=True)
            box.add_widget(row)
        if not ids:
            self._note("You don't own a matching item." if owned is not None else "No matching items.")
        self.ids.scroll.scroll_y = 1
        app.request_thumbs(ids)

    def choose(self, item_id: int):
        app = App.get_running_app()
        if app.sm.get_screen("edit").add(self.side, item_id):
            self.ids.search.focus = False
            app.go_back()


class EditScreen(Screen):
    index = NumericProperty(-1)

    def load(self, index: int, ad: Ad):
        self.index = index
        self.ad = copy.deepcopy(ad)
        self.ids.name.text = ad.name
        self.ids.enabled.active = ad.enabled
        tags = self.ids.tags
        tags.clear_widgets()
        self._chips = {}
        for tag in VALID_TAGS:
            chip = Chip(text=tag, selected=tag in ad.request_tags)
            chip.bind(on_release=lambda c, t=tag: self.toggle_tag(t))
            self._chips[tag] = chip
            tags.add_widget(chip)
        self.refresh()
        App.get_running_app().request_thumbs(ad.all_item_ids())
        self.ids.scroll.scroll_y = 1

    def _slots(self) -> int:
        return len(self.ad.request_item_ids) + sum(c.selected for c in self._chips.values())

    def toggle_tag(self, tag: str):
        chip = self._chips[tag]
        if not chip.selected and self._slots() >= MAX_REQUEST_SLOTS:
            return App.get_running_app().toast(f"You can want at most {MAX_REQUEST_SLOTS} items and tags.")
        chip.selected = not chip.selected
        self.refresh_summary()

    def refresh(self):
        app = App.get_running_app()
        missing = set(missing_offer_items(self.ad, app.inventory))
        for box, ids, side in ((self.ids.offer_box, self.ad.offer_item_ids, "offer"),
                               (self.ids.want_box, self.ad.request_item_ids, "request")):
            box.clear_widgets()
            for i, item_id in enumerate(ids):
                row = app.item_row(item_id, warn=side == "offer" and item_id in missing)
                row.add_action("×", lambda s=side, n=i: self.remove(s, n))
                box.add_widget(row)
            if not ids:
                box.add_widget(Label(text="Nothing added yet.", color=(0.55, 0.58, 0.64, 1),
                                     size_hint_y=None, height=36, font_size="14sp"))
        self.ids.owned_hint.text = ("Highlighted items aren't in your Rolimons inventory, so this ad will be skipped."
                                    if missing else "")
        self.refresh_summary()

    def refresh_summary(self):
        catalog = App.get_running_app().catalog
        if not catalog:
            self.ids.summary.text = ""
            return
        av = evaluate_ad(self.ad, catalog)
        text = f"Offer value {av.offer_value:,}"
        if av.request_value is not None:
            text += f"   ·   Want value {av.request_value:,} ({av.overpay_percent:+.0f}%)"
        self.ids.summary.text = text

    def remove(self, side: str, index: int):
        (self.ad.offer_item_ids if side == "offer" else self.ad.request_item_ids).pop(index)
        self.refresh()

    def add(self, side: str, item_id: int) -> bool:
        app = App.get_running_app()
        if side == "offer":
            if len(self.ad.offer_item_ids) >= MAX_OFFER_ITEMS:
                app.toast(f"You can offer at most {MAX_OFFER_ITEMS} items.")
                return False
            self.ad.offer_item_ids.append(item_id)
        else:
            if self._slots() >= MAX_REQUEST_SLOTS:
                app.toast(f"You can want at most {MAX_REQUEST_SLOTS} items and tags.")
                return False
            self.ad.request_item_ids.append(item_id)
        self.refresh()
        return True

    def open_picker(self, side: str):
        app = App.get_running_app()
        full = (len(self.ad.offer_item_ids) >= MAX_OFFER_ITEMS if side == "offer"
                else self._slots() >= MAX_REQUEST_SLOTS)
        if full:
            limit = (f"You can offer at most {MAX_OFFER_ITEMS} items." if side == "offer"
                     else f"You can want at most {MAX_REQUEST_SLOTS} items and tags.")
            return app.toast(limit)
        app.sm.get_screen("picker").open_for(side)
        app.show("picker")

    def save(self):
        app = App.get_running_app()
        self.ad.name = self.ids.name.text.strip()
        self.ad.enabled = self.ids.enabled.active
        self.ad.request_tags = [t for t, c in self._chips.items() if c.selected]
        if not self.ad.name:
            return app.notice("Can't save yet", "Give the ad a name.")
        if any(a.name == self.ad.name for i, a in enumerate(app.cfg.ads) if i != self.index):
            return app.notice("Can't save yet", "Another ad already has that name.")
        if not self.ad.offer_item_ids:
            return app.notice("Can't save yet", "Add at least one item you offer.")
        if not self.ad.request_item_ids and not self.ad.request_tags:
            return app.notice("Can't save yet", "Add at least one item or tag you want.")
        if self.index >= 0:
            app.cfg.ads[self.index] = self.ad
        else:
            app.cfg.ads.append(self.ad)
        app.persist()
        app.go_back()

    def delete(self):
        app = App.get_running_app()

        def really():
            del app.cfg.ads[self.index]
            app.persist()
            app.go_back()
        app.notice("Delete ad", f"Delete '{self.ad.name}'?", (("Cancel", None), ("Delete", really)))


# ---- app -----------------------------------------------------------------------
class SwipeManager(ScreenManager):
    """Swipe left/right on a main tab to go to the next/previous tab.

    A mostly-horizontal drag counts as a swipe; it cancels any button press it started on (so swiping
    across an ad card doesn't open it). Screens that aren't tabs (ad editor, item picker) ignore swipes.
    """
    START = 24  # dp of horizontal travel before a drag counts as a swipe
    MIN = 70    # dp of travel needed to change tab

    def on_touch_down(self, touch):
        touch.ud["swipe_start"] = (touch.x, touch.y)
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        from kivy.metrics import dp
        start = touch.ud.get("swipe_start")
        if start and not touch.ud.get("swiping") and self.current in TABS:
            dx, dy = touch.x - start[0], touch.y - start[1]
            if abs(dx) > dp(self.START) and abs(dx) > 2 * abs(dy):
                touch.ud["swiping"] = True
                for ref in list(touch.grab_list):  # cancel presses/scrolls this touch started
                    widget = ref() if callable(ref) else ref
                    if widget is not None and widget is not self:
                        touch.ungrab(widget)
                        if hasattr(widget, "state"):
                            widget.state = "normal"
        if touch.ud.get("swiping"):
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        from kivy.metrics import dp
        if touch.ud.get("swiping"):
            dx = touch.x - touch.ud["swipe_start"][0]
            if abs(dx) >= dp(self.MIN):
                App.get_running_app().swipe_tab(1 if dx < 0 else -1)
            return True
        return super().on_touch_up(touch)


class RoliApp(App):
    title = "Rolimons Ad Poster"
    running = BooleanProperty(False)
    status_title = StringProperty("Stopped")
    status_detail = StringProperty("")
    cookie_text = StringProperty("")
    cookie_state = StringProperty("bad")
    ads_count = StringProperty("")
    update_text = StringProperty("")
    active_tab = StringProperty("home")
    can_sign_in = BooleanProperty(droid.RolimonsLogin.available)
    icon_path = StringProperty(str(asset("assets/icon.png")))

    def build(self):
        Window.clearcolor = get_color_from_hex(P.BG)
        if not droid.IS_ANDROID:
            Window.size = (420, 880)  # phone-shaped preview window
        Window.softinput_mode = "below_target"
        Window.bind(on_keyboard=self._on_key)
        setup_logging(log_dir())
        droid.prime_java()  # worker threads (the trades list) use the app's Java classes
        load_env_file(env_path())
        self.cfg = self._load_cfg()
        self.catalog: ItemCatalog | None = None
        self.inventory = None
        self.thumbs = ThumbnailCache(cache_dir() / "thumbs")
        self._thumb_tried: set[int] = set()
        self.engine = droid.Engine(HOME)
        self.login = None
        self._start_requested_at = 0.0
        self._stop_requested_at = 0.0
        self._last_error_seen = None
        self._update_url = ""
        self._direct_checked_at = 0.0
        self.value_history = None   # roliposter.portfolio.History, from your Rolimons player page
        self.best_prices = None     # asset ID -> cheapest copy for sale now (Rolimons deals page)
        self.price_log = PriceLog(HOME / "price_history.json")
        self.history_status = ""
        self._portfolio_at = 0.0
        self._stack: list[str] = []
        register_fonts()
        from kivy.metrics import Metrics
        if Metrics.fontscale > 1.2:  # very large system font sizes would push text out of the layout
            Metrics.fontscale = 1.2
        Builder.load_file(str(HERE / "ui.kv"))
        self.sm = SwipeManager(transition=SlideTransition(duration=0.18))
        for screen in (HomeScreen(), EditScreen(), SettingsScreen(), HistoryScreen(), CookieScreen(),
                       TradesScreen(), TradeScreen(), ItemsScreen(), HelpScreen(), PickerScreen()):
            self.sm.add_widget(screen)
        # Before anything opens the Trades tab (e.g. a tapped notification): list or Roblox page.
        Clock.schedule_once(lambda *_: self.sync_direct_trades(), 0)
        self.refresh_ads()
        self.update_cookie_status()
        Clock.schedule_interval(self.tick, 0.5)
        threading.Thread(target=self._load_catalog, daemon=True).start()
        if self.cfg.app.check_updates:
            threading.Thread(target=self._check_updates, daemon=True).start()
        Clock.schedule_once(lambda *_: self._first_run_checks(), 1.0)
        self.trades_view = (droid.TradesView(TRADES_URL, VIEW_ONLY_JS + TRADE_POLL_JS)
                            if droid.TradesView.available else None)
        Clock.schedule_once(lambda *_: self.apply_trade_notifications(), 2.5)  # after the insets are known
        if droid.IS_ANDROID:
            from android import activity  # type: ignore
            activity.bind(on_new_intent=self._on_new_intent)
        self.nav = Factory.NavBar()
        root = BoxLayout(orientation="vertical")
        root.add_widget(self.sm)
        root.add_widget(self.nav)
        self.sm.bind(current=lambda _sm, name: setattr(self, "active_tab", name) if name in TABS else None)
        self.root_box = root
        self.inset_top = self.inset_bottom = 0
        with root.canvas.before:  # fills the strip behind the gesture bar in the tab bar's colour
            Color(*get_color_from_hex(P.SURFACE))
            self._bottom_fill = Rectangle(pos=(0, 0), size=(0, 0))
        Clock.schedule_once(self._apply_insets, 0.5)
        Clock.schedule_once(self._apply_insets, 2.0)  # again once Android has finished laying out
        Window.bind(on_resize=lambda *_: Clock.schedule_once(self._apply_insets, 0.3))
        return root

    def _apply_insets(self, *_):
        """Keeps the header and tab bar out from under Android 15's edge-to-edge system bars."""
        top, bottom = droid.system_bar_overlap(int(Window.height))
        self.inset_top, self.inset_bottom = top, bottom
        self.root_box.padding = [0, top, 0, bottom]
        self._bottom_fill.size = (Window.width, bottom)
        if self.sm.current == "trades":
            self.show_trades_view()

    def _load_cfg(self) -> Config:
        try:
            return load_config(config_path())
        except ConfigError:
            if (droid.launch_extra("demo") or "") == "1":  # sample ads for screenshots/tests
                example = HERE / "config.example.json"
                if not example.exists():
                    example = HERE.parent / "config.example.json"
                if example.exists():
                    cfg = load_config(example)
                    save_config(cfg, config_path())
                    return cfg
            return Config()

    def persist(self):
        save_config(self.cfg, config_path())
        self.refresh_ads()

    # ---- navigation ------------------------------------------------------
    def show(self, name: str):
        if name == self.sm.current:
            return
        self._stack.append(self.sm.current)
        self.sm.transition.direction = "left"
        self.sm.current = name

    def switch_tab(self, name: str):
        """Bottom tab bar: jump to a tab (tabs aren't stacked, so Back from a tab goes to Ads)."""
        if name == self.sm.current:
            return
        self._stack.clear()
        order = list(TABS)
        current = self.sm.current if self.sm.current in order else "home"
        self.sm.transition.direction = "left" if order.index(name) > order.index(current) else "right"
        self.sm.current = name

    def swipe_tab(self, step: int):
        """Swipe left (step +1) / right (step -1) between the main tabs, in tab-bar order."""
        order = list(TABS)
        if self.sm.current in order:
            target = order.index(self.sm.current) + step
            if 0 <= target < len(order):
                self.switch_tab(order[target])

    def go_back(self):
        if self._stack:
            self.sm.transition.direction = "right"
            self.sm.current = self._stack.pop()
            return True
        if self.sm.current in TABS and self.sm.current != "home":
            self.switch_tab("home")
            return True
        return False

    def _on_key(self, _window, key, *_):
        if key == 27:  # Android back button (Escape on a PC)
            if self.login and self.login.is_open:
                self.login.close()
            elif self.sm.current == "trades" and self.trades_view and not self.sm.get_screen("trades").native:
                self.trades_view.go_back(otherwise=lambda: self.switch_tab("home"))
            elif not self.go_back():
                droid.move_to_background()  # like Home: never quit, posting keeps running
            return True
        return False

    # ---- received trades -------------------------------------------------
    def _trades_area(self) -> tuple[int, int]:
        """Pixels between the trades tab's top bar and the bottom tab bar (Android view coordinates)."""
        from kivy.metrics import dp
        top = self.inset_top + int(dp(58))
        return top, int(Window.height - top - self.nav.height - self.inset_bottom)

    def show_trades_view(self):
        if self.trades_view:
            self.trades_view.show(*self._trades_area())

    def hide_trades_view(self):
        if self.trades_view:
            self.trades_view.hide()

    def apply_trade_notifications(self):
        """"New trade from X": with "Read my trades directly" the background service checks; otherwise
        the (hidden) trades page does, so it's loaded at startup."""
        enabled = self.cfg.app.notifications and self.cfg.app.trade_notifications
        direct = self.cfg.app.direct_trades and droid.RobloxDirect.available
        droid.RobloxDirect.set_enabled(direct)  # off deletes the stored sign-in
        droid.set_trade_notifications(enabled and not direct)
        if enabled and not direct and self.trades_view:
            self.trades_view.preload(*self._trades_area())
        Clock.schedule_once(lambda *_: self.sync_direct_trades(), 1.0)  # after the sign-in is copied

    def sync_direct_trades(self):
        """Follows the Roblox sign-in for "Read my trades directly": list or Roblox page, background checks."""
        self._direct_checked_at = time.time()
        screen = self.sm.get_screen("trades")
        direct = self.cfg.app.direct_trades and droid.RobloxDirect.signed_in()
        if direct != screen.direct:
            screen.direct = direct
            screen.page = False
            screen._loaded_at = 0.0
            screen.apply_view()
        if droid.trade_watch_wanted(self.cfg):
            try:
                self.engine.start(droid.WATCHING_TEXT)  # no-op if the service is already running
            except Exception as e:  # e.g. Android refusing a start while the app is in the background
                log.debug("Couldn't start the trade checks: %s", e)

    def thumb_source(self, item_id: int) -> str:
        return str(self.thumbs.path(item_id)) if self.thumbs.cached(item_id) else ""

    def trade_item_row(self, item) -> ItemRow:
        parts = [f"Value {item.value:,}", f"RAP {item.rap:,}"]
        if item.serial:
            parts.append(f"#{item.serial}")
        if item.projected:
            parts.append(f"[color={P.WARN}]Projected[/color]")
        return ItemRow(thumb=self.thumb_source(item.asset_id), name=item.name, value="  ·  ".join(parts),
                       warn=item.projected)

    def _on_new_intent(self, intent):
        """A notification was tapped while the app was already open."""
        tab, kind = droid.opened_tab(intent), droid.opened_trades_list(intent)
        if tab:
            Clock.schedule_once(lambda *_: self.open_tab_from_notification(tab, kind), 0)

    def open_tab_from_notification(self, tab: str, kind: str = "inbound"):
        if tab == "trades":  # a trade alert: show the trades list (not the Roblox page) it's about
            self.sync_direct_trades()
            trades = self.sm.get_screen("trades")
            trades.page, trades.kind = False, kind
            trades._loaded_at = 0.0
            if self.sm.current == "trades":
                trades.apply_view()
        self.switch_tab(tab)

    def notice(self, title: str, message: str, buttons=(("OK", None),)):
        Notice(title, message, buttons).open()

    def toast(self, message: str):
        Notice("", message).open()
        Clock.schedule_once(lambda *_: [w.dismiss() for w in Window.children if isinstance(w, Notice)], 0.9)

    # ---- status ------------------------------------------------------------
    def tick(self, *_):
        status = runner.read_status(HOME)
        now = time.time()
        starting = now - self._start_requested_at < 25 and not status.get("running")
        self.running = bool(status.get("running")) or starting
        history = PostHistory(state_path())
        count = f"{history.count_24h()} of {self.cfg.max_ads_per_24h} posted in the last 24h"
        if status.get("running"):
            nxt = f"Next: {status['next_ad']}  ·  " if status.get("next_ad") else ""
            if status.get("wait_until"):
                self.status_title = f"Next ad in {fmt_duration(max(0, status['wait_until'] - now))}"
                self.status_detail = f"{nxt}{str(status.get('status_text', '')).capitalize()}  ·  {count}"
            else:
                self.status_title = str(status.get("status_text") or "Posting").capitalize()
                self.status_detail = f"{nxt}{count}"
        elif starting:
            self.status_title, self.status_detail = "Starting...", count
        else:
            self.status_title, self.status_detail = "Stopped", f"Ready when you are  ·  {count}"
            if self._stop_requested_at:
                self._stop_requested_at = 0.0
            error = status.get("error")
            if error and not status.get("stopped_by_user") and status.get("updated") != self._last_error_seen \
                    and self._start_requested_at:
                self._last_error_seen = status.get("updated")
                self._start_requested_at = 0.0
                self.notice(status.get("error_title") or "Posting stopped", error)
        if self._stop_requested_at and now - self._stop_requested_at > 12 and status.get("running"):
            self.engine.stop_service()  # didn't respond to the stop command
            self._stop_requested_at = 0.0
        if status.get("unavailable") is not None and status.get("unavailable") != getattr(self, "_unavail", None):
            self._unavail = status.get("unavailable")
            self.refresh_ads()
        if self.cfg.app.direct_trades and now - self._direct_checked_at > 3:
            self.sync_direct_trades()  # picks up signing in (or out) on the Roblox page
        if self.login and self.login.is_open:
            found = clean_cookie(self.login.poll_cookie() or "")
            if looks_like_cookie(found):
                self.login.close()
                self.save_cookie(found, from_login=True)

    def toggle_run(self):
        if self.running:
            runner.send_command(HOME, "stop")
            runner.set_want_running(HOME, False)
            self._stop_requested_at = time.time()
            self._start_requested_at = 0.0
            self.status_title = "Stopping..."
            return
        problems = []
        try:
            if not get_cookie():
                problems.append("Sign in to Rolimons (or paste your cookie) first.")
        except ValueError:
            problems.append("Your saved cookie looks wrong. Set it again.")
        problems += [p for p in validate_config(self.cfg) if not p.startswith("roblox_user_id")]
        if self.cfg.roblox_user_id <= 0:
            problems.append("Your Roblox user ID is missing. Setting the cookie fills it in.")
        if problems:
            return self.notice("Before you start", "\n\n".join(problems))
        droid.request_notification_permission()
        runner.set_want_running(HOME, True)
        self._start_requested_at = time.time()
        self.engine.start()

    def skip(self):
        runner.send_command(HOME, "skip")
        self.toast("Skipping to the next ad")

    # ---- account -----------------------------------------------------------
    def update_cookie_status(self):
        try:
            cookie = get_cookie()
        except ValueError:
            cookie = None
        info = cookie_info(cookie) if cookie else None
        if not cookie:
            self.cookie_text, self.cookie_state = "Not set", "bad"
        elif info and info.expired:
            self.cookie_text, self.cookie_state = "Expired: sign in again", "bad"
        elif info and info.expires_at:
            who = f"{info.player_name}  ·  " if info.player_name else ""
            soon = info.expires_at - time.time() < COOKIE_WARN_DAYS * 86400
            self.cookie_text = f"{who}expires {time.strftime('%d %b %Y', time.localtime(info.expires_at))}"
            self.cookie_state = "warn" if soon else "ok"
        else:
            self.cookie_text, self.cookie_state = "Saved", "ok"

    def save_cookie(self, pasted: str, from_login: bool = False) -> bool:
        value = clean_cookie(pasted)
        if not looks_like_cookie(value):
            self.notice("Cookie", "Couldn't find a Rolimons cookie in that. Copy the _RoliVerification value "
                                  "(it starts with \"eyJ\").")
            return False
        info = cookie_info(value)
        if info and info.expired:
            self.notice("Cookie", "That cookie has already expired.")
            return False
        save_env_value(env_path(), COOKIE_ENV_VAR, value)
        REDACTOR.add_secret(value)
        if info and info.player_id and info.player_id != self.cfg.roblox_user_id:
            self.cfg.roblox_user_id = info.player_id
            self.inventory = None
            self.persist()
            threading.Thread(target=self._load_inventory, daemon=True).start()
        self.update_cookie_status()
        who = f" as {info.player_name}" if info and info.player_name else ""
        self.notice("Signed in" if from_login else "Cookie saved", f"You're all set{who}.")
        return True

    def sign_in(self):
        if not droid.RolimonsLogin.available:
            return self.show("cookie")
        self.login = droid.RolimonsLogin(on_cookie=None, on_close=lambda: None)
        self.login.open()
        self.toast("Log in and verify on Rolimons. This closes by itself once you're verified.")

    def _first_run_checks(self):
        try:
            cookie = get_cookie()
        except ValueError:
            cookie = None
        info = cookie_info(cookie) if cookie else None
        if info and info.expires_at and not info.expired and self.cfg.app.notifications:
            days = (info.expires_at - time.time()) / 86400
            if days < COOKIE_WARN_DAYS:
                droid.notify("Rolimons cookie expiring soon",
                             f"Your cookie expires in {max(1, round(days * 24))} hours. Sign in again to keep posting.")
        tab, kind = droid.opened_tab(), droid.opened_trades_list()  # opened by tapping one of our notifications
        if tab:
            self.open_tab_from_notification(tab, kind)
        screen = droid.launch_extra("screen")
        if screen == "edit" and self.cfg.ads:
            self.edit_ad(0)
        elif screen in ("settings", "history", "help", "trades"):
            self.switch_tab(screen)
        elif screen == "cookie":
            self.show(screen)
        if droid.launch_extra("search") and self.cfg.ads:
            self.sm.get_screen("edit").open_picker("offer")
            self.show("picker")
            self.sm.get_screen("picker").ids.search.text = droid.launch_extra("search")
        if droid.launch_extra("autostart") == "1":
            self.toggle_run()
        if droid.launch_extra("login") == "1":
            self.sign_in()
        if droid.launch_extra("selftest") == "1":
            from selftest import SelfTest
            self._selftest = SelfTest(self, HOME)  # keep a reference: Kivy's Clock only holds weak ones
            self._selftest.start()

    # ---- ads ---------------------------------------------------------------
    def _short(self, item_id: int) -> str:
        item = self.catalog.get(item_id) if self.catalog else None
        return (item.acronym or item.name) if item else str(item_id)

    def refresh_ads(self):
        box = self.sm.get_screen("home").ids.ads_box
        box.clear_widgets()
        unavailable = getattr(self, "_unavail", None) or (
            {a.name: m for a in self.cfg.ads if (m := missing_offer_items(a, self.inventory))}
            if self.cfg.skip_unowned_items else {})
        for i, ad in enumerate(self.cfg.ads):
            offer = ", ".join(self._short(x) for x in ad.offer_item_ids)
            want = ", ".join([self._short(x) for x in ad.request_item_ids] + ad.request_tags)
            warned = ad.enabled and ad.name in unavailable
            card = AdCard(title=ad.name, summary=f"{offer}  for  {want}", active=ad.enabled, warned=warned,
                          badge="Item not owned: skipped" if warned else ("On" if ad.enabled else "Off"))
            card.bind(on_release=lambda _c, n=i: self.edit_ad(n))
            card.bind(on_toggle=lambda _c, value, n=i: self.set_enabled(n, value))
            box.add_widget(card)
        on = len(self.cfg.enabled_ads())
        self.ads_count = f"{len(self.cfg.ads)} total · {on} on" if self.cfg.ads else ""

    def set_enabled(self, index: int, value: bool):
        if self.cfg.ads[index].enabled != value:
            self.cfg.ads[index].enabled = value
            Clock.schedule_once(lambda *_: self.persist(), 0)

    def new_ad(self):
        n = len(self.cfg.ads) + 1
        while any(a.name == f"Ad {n}" for a in self.cfg.ads):
            n += 1
        self.sm.get_screen("edit").load(-1, Ad(name=f"Ad {n}"))
        self.show("edit")

    def edit_ad(self, index: int):
        self.sm.get_screen("edit").load(index, self.cfg.ads[index])
        self.show("edit")

    # ---- items ---------------------------------------------------------------
    def item_row(self, item_id: int, warn: bool = False) -> ItemRow:
        item = self.catalog.get(item_id) if self.catalog else None
        thumb = str(self.thumbs.path(item_id)) if self.thumbs.cached(item_id) else ""
        return ItemRow(thumb=thumb, warn=warn, name=item.label if item else f"Item {item_id}",
                       value=f"Value {item.default_value:,}" if item else "")

    def request_thumbs(self, item_ids: list[int]):
        # Each picture is tried once per session, so a failed download can't trigger endless refetches.
        wanted = [i for i in item_ids if not self.thumbs.cached(i) and i not in self._thumb_tried]
        if not wanted:
            return
        self._thumb_tried.update(wanted)

        def work():
            try:
                self.thumbs.fetch(requests.Session(), wanted)
            except Exception:
                pass
            self._thumbs_ready(wanted)
        threading.Thread(target=work, daemon=True).start()

    @mainthread
    def _thumbs_ready(self, ids):
        if self.sm.current == "edit":
            self.sm.get_screen("edit").refresh()
        elif self.sm.current == "trades":
            self.sm.get_screen("trades").refresh_thumbs()
        elif self.sm.current == "trade":
            self.sm.get_screen("trade").refresh()
        elif self.sm.current == "picker":
            self.sm.get_screen("picker").search()
        elif self.sm.current == "items":
            self.sm.get_screen("items").refresh()

    def owned_counts(self) -> dict[int, int] | None:
        """Item ID -> copies you own, or None when your Rolimons inventory isn't known (or is private)."""
        if self.inventory is None or self.inventory.private:
            return None
        return self.inventory.counts

    def _load_catalog(self):
        for attempt in range(4):
            try:
                self._catalog_ready(fetch_catalog(requests.Session()))
                break
            except Exception:
                time.sleep(5 * (attempt + 1))
        self._load_inventory()

    @mainthread
    def _catalog_ready(self, catalog):
        self.catalog = catalog
        self.refresh_ads()

    def _load_inventory(self):
        if self.cfg.roblox_user_id > 0:
            try:
                self._inventory_ready(fetch_inventory(requests.Session(), self.cfg.roblox_user_id))
            except Exception:
                pass

    @mainthread
    def _inventory_ready(self, inventory):
        self.inventory = inventory
        self.refresh_ads()
        if self.sm.current == "items":
            self.sm.get_screen("items").refresh()
        elif self.sm.current == "picker":
            self.sm.get_screen("picker").search()

    def load_portfolio(self, force: bool = False):
        """Items tab: refreshes your inventory, value history and current prices (at most every 10 minutes)."""
        if self.cfg.roblox_user_id <= 0 or (not force and time.time() - self._portfolio_at < 600):
            return
        self._portfolio_at = time.time()
        user_id = self.cfg.roblox_user_id

        def work():
            session = requests.Session()
            self._load_inventory()
            try:
                history, status = fetch_history(session, user_id), ""
            except Exception as e:
                log.warning("Couldn't load value history: %s", e)
                history, status = None, "Couldn't load your value history from Rolimons. Tap Reload to try again."
            try:
                prices = fetch_best_prices(session)
            except Exception as e:
                log.warning("Couldn't load current prices: %s", e)
                prices = None
            self._history_ready(history, status, prices)
        threading.Thread(target=work, daemon=True).start()

    @mainthread
    def _history_ready(self, history, status: str, prices=None):
        if history is not None or self.value_history is None:
            self.value_history = history
        if prices is not None:
            self.best_prices = prices
        self.history_status = status
        if history is None or prices is None:
            self._portfolio_at = 0.0  # try again next time the tab opens
        if self.sm.current == "items":
            self.sm.get_screen("items").refresh()

    def _check_updates(self):
        try:
            found = check_for_update(requests.Session())
        except Exception:
            return
        if found:
            self._update_found(*found)

    @mainthread
    def _update_found(self, version: str, url: str):
        self.update_text = f"Version {version} is available (you have {__version__})."
        self._update_url = url

    def open_update(self):
        droid.open_url(self._update_url or "https://github.com/rxst0/rolimons-ad-poster/releases/latest")


if __name__ == "__main__":
    RoliApp().run()
