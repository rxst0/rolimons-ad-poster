"""Rolimons Ad Poster - Android app (Kivy). Also runs on a PC for previewing: python android/main.py"""
import copy
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
from kivy.lang import Builder  # noqa: E402
from kivy.properties import BooleanProperty, ColorProperty, NumericProperty, StringProperty  # noqa: E402
from kivy.uix.behaviors import ButtonBehavior  # noqa: E402
from kivy.uix.boxlayout import BoxLayout  # noqa: E402
from kivy.uix.label import Label  # noqa: E402
from kivy.uix.modalview import ModalView  # noqa: E402
from kivy.uix.screenmanager import Screen, ScreenManager, SlideTransition  # noqa: E402
from kivy.uix.widget import Widget  # noqa: E402
from kivy.utils import get_color_from_hex  # noqa: E402

import runner  # noqa: E402
from roliposter import __version__  # noqa: E402
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
from roliposter.state import PostHistory  # noqa: E402
from roliposter.thumbs import ThumbnailCache  # noqa: E402
from roliposter.updates import check_for_update  # noqa: E402
from roliposter.values import evaluate_ad  # noqa: E402

COOKIE_WARN_DAYS = 3
RESULT_COLORS = {"SUCCESS": P.OK, "AUTH_ERROR": P.BAD, "REJECTED": P.BAD}


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


class CookieScreen(Screen):
    def on_pre_enter(self):
        self.ids.cookie.text = ""

    def save(self):
        app = App.get_running_app()
        if app.save_cookie(self.ids.cookie.text):
            app.go_back()


class HistoryScreen(Screen):
    def on_pre_enter(self):
        box = self.ids.attempts
        box.clear_widgets()
        attempts = list(reversed(PostHistory(state_path()).attempts))[:100]
        posted = sum(1 for a in attempts if a["result"] == "SUCCESS")
        self.ids.summary.text = (f"{len(attempts)} recent attempts  ·  {posted} posted" if attempts
                                 else "Nothing posted yet.")
        for a in attempts:
            color = RESULT_COLORS.get(a["result"], P.WARN)
            when = time.strftime("%d %b %H:%M", time.localtime(a["t"]))
            result = a["result"].replace("_", " ").title()
            row = ItemRow(name=f"{a['ad']}", value=f"{when}  ·  [color={color}]{result}[/color]  {a.get('message', '')[:60]}")
            row.height = 52
            box.add_widget(row)
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
        ids.updates_on.active = c.app.check_updates
        self.refresh_battery()

    def refresh_battery(self):
        ignoring = droid.ignoring_battery_optimizations()
        self.battery_text = ("" if ignoring in (None, True) else
                             "Android may pause posting to save battery. Allow the app to run in the "
                             "background so ads keep going with the screen off.")

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
        c.app.check_updates = ids.updates_on.active
        problems = [e for e in validate_config(c) if not e.startswith(("No ads", "All ads", "roblox_user_id"))
                    and not e.startswith("Ad '")]
        if problems:
            return app.notice("Check your settings", "\n".join(problems))
        app.cfg = c
        app.persist()
        app.go_back()


class EditScreen(Screen):
    index = NumericProperty(-1)

    def load(self, index: int, ad: Ad):
        self.index = index
        self.ad = copy.deepcopy(ad)
        self.ids.name.text = ad.name
        self.ids.enabled.active = ad.enabled
        self.ids.search.text = ""
        self.ids.results.clear_widgets()
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
                row.add_action("✕", lambda s=side, n=i: self.remove(s, n))
                box.add_widget(row)
            if not ids:
                box.add_widget(Label(text="Nothing yet: search below to add items.", color=(0.55, 0.58, 0.64, 1),
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

    def add(self, side: str, item_id: int):
        app = App.get_running_app()
        if side == "offer":
            if len(self.ad.offer_item_ids) >= MAX_OFFER_ITEMS:
                return app.toast(f"You can offer at most {MAX_OFFER_ITEMS} items.")
            self.ad.offer_item_ids.append(item_id)
        else:
            if self._slots() >= MAX_REQUEST_SLOTS:
                return app.toast(f"You can want at most {MAX_REQUEST_SLOTS} items and tags.")
            self.ad.request_item_ids.append(item_id)
        app.toast("Added to " + ("offer" if side == "offer" else "want"))
        self.refresh()

    def schedule_search(self):
        Clock.unschedule(self.search)
        Clock.schedule_once(self.search, 0.3)

    def search(self, *_):
        app = App.get_running_app()
        box = self.ids.results
        box.clear_widgets()
        q = self.ids.search.text.strip().lower()
        if not q:
            return
        if not app.catalog:
            box.add_widget(Label(text="Item list still loading...", color=(0.55, 0.58, 0.64, 1),
                                 size_hint_y=None, height=36))
            return
        matches = []
        for item in app.catalog.items.values():
            if q == str(item.id) or q in item.name.lower() or q == item.acronym.lower():
                rank = 0 if q in (item.acronym.lower(), str(item.id)) else 1 if item.name.lower().startswith(q) else 2
                matches.append((rank, -item.default_value, item.id))
        matches.sort()
        ids = [m[2] for m in matches[:25]]
        for item_id in ids:
            row = app.item_row(item_id)
            row.add_action("Offer", lambda i=item_id: self.add("offer", i), accent=True)
            row.add_action("Want", lambda i=item_id: self.add("request", i))
            box.add_widget(row)
        if not ids:
            box.add_widget(Label(text="No matching items.", color=(0.55, 0.58, 0.64, 1), size_hint_y=None, height=36))
        app.request_thumbs(ids)

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
class RoliApp(App):
    title = "Rolimons Ad Poster"
    running = BooleanProperty(False)
    status_title = StringProperty("Stopped")
    status_detail = StringProperty("")
    cookie_text = StringProperty("")
    cookie_state = StringProperty("bad")
    ads_count = StringProperty("")
    update_text = StringProperty("")
    can_sign_in = BooleanProperty(droid.RolimonsLogin.available)
    icon_path = StringProperty(str(asset("assets/icon.png")))

    def build(self):
        Window.clearcolor = get_color_from_hex(P.BG)
        if not droid.IS_ANDROID:
            Window.size = (420, 880)  # phone-shaped preview window
        Window.softinput_mode = "below_target"
        Window.bind(on_keyboard=self._on_key)
        setup_logging(log_dir())
        load_env_file(env_path())
        self.cfg = self._load_cfg()
        self.catalog: ItemCatalog | None = None
        self.inventory = None
        self.thumbs = ThumbnailCache(cache_dir() / "thumbs")
        self._thumb_pending: set[int] = set()
        self.engine = droid.Engine(HOME)
        self.login = None
        self._start_requested_at = 0.0
        self._stop_requested_at = 0.0
        self._last_error_seen = None
        self._update_url = ""
        self._stack: list[str] = []
        register_fonts()
        Builder.load_file(str(HERE / "ui.kv"))
        self.sm = ScreenManager(transition=SlideTransition(duration=0.18))
        for screen in (HomeScreen(), EditScreen(), SettingsScreen(), HistoryScreen(), CookieScreen()):
            self.sm.add_widget(screen)
        self.refresh_ads()
        self.update_cookie_status()
        Clock.schedule_interval(self.tick, 0.5)
        threading.Thread(target=self._load_catalog, daemon=True).start()
        if self.cfg.app.check_updates:
            threading.Thread(target=self._check_updates, daemon=True).start()
        Clock.schedule_once(lambda *_: self._first_run_checks(), 1.0)
        return self.sm

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

    def go_back(self):
        if not self._stack:
            return False
        self.sm.transition.direction = "right"
        self.sm.current = self._stack.pop()
        return True

    def _on_key(self, _window, key, *_):
        if key == 27:  # Android back button
            if self.login and self.login.is_open:
                self.login.close()
                return True
            return self.go_back()
        return False

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
                self.notice("Posting stopped", error)
        if self._stop_requested_at and now - self._stop_requested_at > 12 and status.get("running"):
            self.engine.stop_service()  # didn't respond to the stop command
            self._stop_requested_at = 0.0
        if status.get("unavailable") is not None and status.get("unavailable") != getattr(self, "_unavail", None):
            self._unavail = status.get("unavailable")
            self.refresh_ads()
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
        screen = droid.launch_extra("screen")
        if screen == "edit" and self.cfg.ads:
            self.edit_ad(0)
        elif screen in ("settings", "history", "cookie"):
            self.show(screen)
        if droid.launch_extra("search"):
            self.sm.get_screen("edit").ids.search.text = droid.launch_extra("search")
        if droid.launch_extra("autostart") == "1":
            self.toggle_run()
        if droid.launch_extra("login") == "1":
            self.sign_in()

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
        wanted = [i for i in item_ids if not self.thumbs.cached(i) and i not in self._thumb_pending]
        if not wanted:
            return
        self._thumb_pending.update(wanted)

        def work():
            try:
                self.thumbs.fetch(requests.Session(), wanted)
            except Exception:
                pass
            self._thumbs_ready(wanted)
        threading.Thread(target=work, daemon=True).start()

    @mainthread
    def _thumbs_ready(self, ids):
        self._thumb_pending.difference_update(ids)
        if self.sm.current == "edit":
            edit = self.sm.get_screen("edit")
            edit.refresh()
            if edit.ids.search.text:
                edit.search()

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
