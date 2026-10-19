"""On-device usability test (debug builds only, launched with the "selftest" extra).

Drives the real screens through the main flows - create an ad from a search, tag it, save it, turn it
off, change a setting, open history, set a cookie, start posting - and checks each result on disk.
Results go to <home>/selftest.json, screenshots to <home>/selftest/, and "SELFTEST" lines to logcat.
"""
import base64
import json
import threading
import time
import traceback
from pathlib import Path

from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.input.motionevent import MotionEvent
from kivy.core.window import Window
from kivy.logger import Logger
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView

import droid
import runner
from roliposter.config import load_config
from roliposter.paths import config_path

AD_NAME = "Selftest ad"


class _Touch(MotionEvent):
    """A simulated finger (same idea as kivy.tests.common.UnitTestTouch, which isn't in the APK)."""

    def __init__(self, x, y):
        win = EventLoop.window
        super().__init__("selftest", 99, {"x": x / (win.width - 1.0), "y": y / (win.height - 1.0)},
                         is_touch=True, type_id="touch")
        self.profile = ["pos"]

    def depack(self, args):
        self.sx, self.sy = args["x"], args["y"]
        super().depack(args)

    def touch_down(self):
        EventLoop.post_dispatch_input("begin", self)

    def touch_move(self, x, y):
        win = EventLoop.window
        self.move({"x": x / (win.width - 1.0), "y": y / (win.height - 1.0)})
        EventLoop.post_dispatch_input("update", self)

    def touch_up(self):
        EventLoop.post_dispatch_input("end", self)


def _fake_cookie(player_id: int) -> str:
    def b64(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    payload = {"exp": time.time() + 7 * 86400, "player_data": {"id": player_id, "name": "selftest"}}
    return f"{b64({'alg': 'HS256'})}.{b64(payload)}.c2lnbmF0dXJl"


class SelfTest:
    def __init__(self, app, home: Path):
        self.app = app
        self.home = home
        self.shots = home / "selftest"
        self.results: list[dict] = []

    def start(self) -> None:
        self.shots.mkdir(parents=True, exist_ok=True)
        (self.home / "selftest.json").unlink(missing_ok=True)
        self._steps = self.steps()
        Clock.schedule_once(self._advance, 1)

    # ---- plumbing ------------------------------------------------------------
    def _advance(self, *_):
        try:
            delay = next(self._steps)
        except StopIteration:
            return self._finish()
        except Exception:
            self.record("no crash", False, traceback.format_exc()[-600:])
            return self._finish()
        Clock.schedule_once(self._advance, delay)

    def record(self, step: str, ok: bool, detail: str = "") -> None:
        self.results.append({"step": step, "ok": bool(ok), "detail": detail})
        Logger.info(f"SELFTEST: {'PASS' if ok else 'FAIL'} | {step} | {detail}")

    def shot(self, name: str) -> None:
        Window.screenshot(name=str(self.shots / f"{name}.png"))

    @staticmethod
    def swipe(direction: int, start=None) -> None:
        """Simulates a finger swipe: direction -1 = swipe left (next tab), +1 = swipe right."""
        x, y = start or (Window.width * 0.5, Window.height * 0.6)
        touch = _Touch(x, y)
        touch.touch_down()
        for step in range(1, 9):
            touch.touch_move(x + direction * Window.width * 0.05 * step, y + step)
        touch.touch_up()

    @staticmethod
    def dismiss_popups() -> None:
        for widget in list(Window.children):
            if isinstance(widget, ModalView):
                widget.dismiss()

    def wait_until(self, condition, timeout: float):
        deadline = time.time() + timeout
        while not condition() and time.time() < deadline:
            yield 0.5
        return bool(condition())

    def _finish(self) -> None:
        passed = sum(r["ok"] for r in self.results)
        summary = {"passed": passed, "total": len(self.results), "results": self.results}
        (self.home / "selftest.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
        Logger.info(f"SELFTEST: DONE | {passed}/{len(self.results)} passed")

    def trades_steps(self):
        """Android only: the Received trades tab loads Roblox and blocks trade-changing requests."""
        app = self.app
        view = app.trades_view
        box = {}

        def ask(code):
            box.pop("v", None)
            view.eval_js(code, lambda value: box.__setitem__("v", value))

        app.switch_tab("trades")
        yield 2
        self.record("trades tab opens", app.sm.current == "trades")
        loaded = False
        for _ in range(60):
            ask("location.href")
            yield 1
            if "roblox.com" in box.get("v", ""):
                loaded = True
                break
        self.record("trades tab loads Roblox", loaded, box.get("v", ""))
        ask("(async () => { try { const r = await fetch('https://trades.roblox.com/v1/trades/1/decline', "
            "{method: 'POST', credentials: 'include'}); window.__roliTest = r.status + ' ' + r.statusText; } "
            "catch (e) { window.__roliTest = 'error ' + e; } })(); 'started'")
        result = ""
        for _ in range(30):
            yield 1
            ask("window.__roliTest || ''")
            yield 0.5
            value = box.get("v", "")
            if "403" in value or "error" in value:
                result = value
                break
        self.record("trades tab blocks trade-changing requests",
                    "Blocked" in result and droid.TradesView.blocked_count() > 0, result)
        # "Read my trades directly" can only make its fixed read-only requests.
        refused = [droid.RobloxDirect.fetch(kind, arg)[0] for kind, arg in
                   (("list", "../1/decline"), ("trade", "1/accept"), ("send", "1"))]
        self.record("direct trade reads refuse anything but their fixed requests", refused == [-2, -2, -2],
                    str(refused))
        # The trades list calls Java from a worker thread, which can't look up the app's classes itself.
        threaded = {}

        def from_thread():
            try:
                threaded["v"] = droid.RobloxDirect.fetch("trade", "1/accept")[0]
            except Exception as e:
                threaded["v"] = f"{type(e).__name__}: {e}"
        worker = threading.Thread(target=from_thread)
        worker.start()
        worker.join(15)
        self.record("direct trade reads work from a background thread", threaded.get("v") == -2,
                    str(threaded.get("v")))
        app.switch_tab("home")
        yield 1

    # ---- the test --------------------------------------------------------------
    def steps(self):
        app = self.app
        # Nothing may sit under the status bar or the gesture/navigation bar (Android 15 edge-to-edge).
        yield 2.5
        top, bottom = droid.system_bar_overlap(int(Window.height))
        header_top = app.sm.top
        self.record("header and tab bar clear of the system bars",
                    app.nav.y >= bottom - 1 and header_top <= Window.height - top + 1,
                    f"window {Window.height}px, bars top {top} bottom {bottom}, tab bar at {app.nav.y:.0f}, "
                    f"content top {header_top:.0f}")

        ok = yield from self.wait_until(lambda: app.catalog is not None, 90)
        self.record("item list loads", ok, f"{len(app.catalog) if app.catalog else 0} items")
        if not ok:
            return

        # Create an ad through the editor: search, add an item, pick a tag, save.
        ads_before = len(app.cfg.ads)
        app.new_ad()
        yield 1
        edit = app.sm.get_screen("edit")
        self.record("editor opens", app.sm.current == "edit")
        edit.ids.name.text = AD_NAME
        # "+ Add item you offer" opens the full-screen picker; tapping an item adds it and returns.
        edit.open_picker("offer")
        yield 1
        picker = app.sm.get_screen("picker")
        self.record("item picker opens", app.sm.current == "picker")
        picker.ids.search.text = "dom"
        ok = yield from self.wait_until(lambda: len(picker.ids.results.children) >= 5, 15)
        self.record("item search shows results", ok, f"{len(picker.ids.results.children)} rows")
        yield from self.wait_until(lambda: False, 4)  # let item pictures load
        self.shot("1-search")
        item_id = max((i for i in app.catalog.items.values() if "dominus" in i.name.lower()),
                      key=lambda i: i.default_value).id
        picker.choose(item_id)
        yield 1
        edit.toggle_tag("upgrade")
        yield 1
        self.dismiss_popups()
        self.record("item added to the offer", item_id in edit.ad.offer_item_ids and app.sm.current == "edit")
        edit.ids.scroll.scroll_y = 1
        yield 1
        self.shot("2-editor")
        edit.save()
        yield 1
        self.dismiss_popups()
        on_disk = load_config(config_path())
        saved = [a for a in on_disk.ads if a.name == AD_NAME]
        self.record("ad saved to disk", bool(saved) and len(app.cfg.ads) == ads_before + 1,
                    json.dumps(saved[0].__dict__) if saved else "missing")
        self.record("back on the home screen", app.sm.current == "home")
        ads_box = app.sm.get_screen("home").ids.ads_box
        self.record("ad listed on home", len(ads_box.children) == len(app.cfg.ads))
        self.shot("3-home")

        # Turn the ad off with its switch.
        index = next(i for i, a in enumerate(app.cfg.ads) if a.name == AD_NAME)
        app.set_enabled(index, False)
        yield 1
        self.record("ad turned off (saved)", not load_config(config_path()).ads[index].enabled)
        app.set_enabled(index, True)
        yield 1

        # Change a setting (Settings tab).
        app.switch_tab("settings")
        yield 1
        settings = app.sm.get_screen("settings")
        settings.set_order("random")
        self.shot("4-settings")
        settings.save()
        yield 2
        self.dismiss_popups()
        self.record("setting saved", load_config(config_path()).rotation == "random")

        # History and Help tabs, then Back returns to the Ads tab.
        app.switch_tab("history")
        yield 1
        self.record("history tab opens", app.sm.current == "history" and app.active_tab == "history")
        app.switch_tab("help")
        yield 1
        self.record("help tab opens", app.sm.current == "help")
        app.go_back()
        yield 1
        self.record("back from a tab returns to Ads", app.sm.current == "home")

        # Swiping between tabs (left = next tab, right = previous).
        app.switch_tab("history")
        yield 1
        self.swipe(-1)
        yield 1
        went_next = app.sm.current == "settings"
        self.swipe(+1)
        yield 1
        self.record("swiping moves between tabs", went_next and app.sm.current == "history", app.sm.current)
        # A swipe that starts on an ad card changes tab instead of opening the ad.
        app.switch_tab("home")
        yield 1
        cards = app.sm.get_screen("home").ids.ads_box.children
        if cards:
            card = cards[-1]
            scroll = card.parent
            while scroll is not None and not isinstance(scroll, ScrollView):
                scroll = scroll.parent
            if scroll is not None:  # small screens: bring the card into view before swiping on it
                scroll.scroll_to(card, padding=20, animate=False)
                yield 0.5
            cx, cy = card.to_window(card.center_x, card.center_y)
            self.swipe(-1, start=(cx, cy))
            yield 1
            self.record("swiping across an ad card doesn't open it", app.sm.current == "trades",
                        f"now on {app.sm.current}; swipe started at {cx:.0f},{cy:.0f} in a {Window.width}x{Window.height} window")
        app.switch_tab("home")
        yield 1

        if droid.TradesView.available:
            yield from self.trades_steps()

        # Set a cookie (fake but well-formed) and start posting.
        app.save_cookie(_fake_cookie(1))
        yield 1
        self.dismiss_popups()
        self.record("cookie saved and user ID filled in", app.cookie_state == "ok" and app.cfg.roblox_user_id == 1,
                    app.cookie_text)
        before = runner.read_status(self.home).get("updated", 0)
        app.toggle_run()
        yield 3
        self.shot("5-starting")
        ok = yield from self.wait_until(lambda: runner.read_status(self.home).get("updated", 0) > before, 120)
        self.record("background service starts and reports", ok)
        yield from self.wait_until(lambda: not runner.read_status(self.home).get("running"), 60)
        status = runner.read_status(self.home)
        self.record("Rolimons' rejection of the fake cookie is reported in plain English",
                    not status.get("running") and "signed out of rolimons" in (status.get("error_title") or "").lower()
                    and "sign in to rolimons again" in (status.get("error") or "").lower(),
                    f"{status.get('error_title')}: {status.get('error')}")
        yield 3
        self.shot("6-result")
        self.dismiss_popups()

        # The stop is in History as a friendly entry (Problems filter), with what to do in its details.
        app.switch_tab("history")
        yield 1
        history = app.sm.get_screen("history")
        history.set_filter("problems")
        yield 1
        rows = [w for w in history.ids.events.children if hasattr(w, "subtitle")]
        titles = [r.title for r in rows]
        self.record("history shows the stop in plain English",
                    any("signed out of Rolimons" in t for t in titles), "; ".join(titles[:5]))
        self.shot("7-history")
        if rows:
            stop_row = next((r for r in reversed(rows) if "signed out" in r.title), rows[-1])
            stop_row.dispatch("on_release")
            yield 1
            notices = [w for w in Window.children if isinstance(w, ModalView)]
            self.record("tapping an entry explains what to do",
                        any("What to do:" in getattr(n, "message", "") for n in notices))
            self.shot("8-history-details")
            self.dismiss_popups()
        history.set_filter("all")
        app.switch_tab("home")
        yield 1

        if droid.IS_ANDROID:
            yield from self.notification_steps()

    def notification_steps(self):
        """Android only: the stop became a phone notification, and new trades notify ("New trade from X")."""
        ok = yield from self.wait_until(
            lambda: any("signed out of Rolimons" in t for t in droid.active_notification_titles()), 15)
        self.record("posting stop sends a phone notification", ok, "; ".join(droid.active_notification_titles()))
        notifier = droid.trade_notifier()
        if not notifier.isSeeded():  # the first check only remembers the trades already there
            notifier.report('[{"id": "1000001", "name": "Seeded"}]')
        before = int(droid.autoclass_notifier().notifiedCount)
        notifier.report('[{"id": "1000002", "name": "SelfTestUser"}, {"id": "1000001", "name": "Seeded"}]')
        ok = yield from self.wait_until(
            lambda: "New trade from SelfTestUser" in droid.active_notification_titles(), 10)
        self.record("a new Roblox trade sends a notification", ok and droid.autoclass_notifier().notifiedCount == before + 1,
                    "; ".join(droid.active_notification_titles()))
        notifier.report('[{"id": "1000002", "name": "SelfTestUser"}]')
        yield 1
        self.record("the same trade doesn't notify twice", droid.autoclass_notifier().notifiedCount == before + 1)
        notifier.report('[{"id": "../etc", "name": "<b>x</b>"}]')
        yield 1
        self.record("malformed trade reports are ignored", droid.autoclass_notifier().notifiedCount == before + 1)
