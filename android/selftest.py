"""On-device usability test (debug builds only, launched with the "selftest" extra).

Drives the real screens through the main flows - create an ad from a search, tag it, save it, turn it
off, change a setting, open history, set a cookie, start posting - and checks each result on disk.
Results go to <home>/selftest.json, screenshots to <home>/selftest/, and "SELFTEST" lines to logcat.
"""
import base64
import json
import time
import traceback
from pathlib import Path

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.logger import Logger
from kivy.uix.modalview import ModalView

import droid
import runner
from roliposter.config import load_config
from roliposter.paths import config_path

AD_NAME = "Selftest ad"


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
        app.switch_tab("home")
        yield 1

    # ---- the test --------------------------------------------------------------
    def steps(self):
        app = self.app
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
        edit.ids.search.text = "dom"
        ok = yield from self.wait_until(lambda: len(edit.ids.results.children) >= 5, 15)
        self.record("item search shows results", ok, f"{len(edit.ids.results.children)} rows")
        yield from self.wait_until(lambda: False, 4)  # let item pictures load
        self.shot("1-search")
        item_id = max((i for i in app.catalog.items.values() if "dominus" in i.name.lower()),
                      key=lambda i: i.default_value).id
        edit.add("offer", item_id)
        edit.toggle_tag("upgrade")
        yield 1
        self.dismiss_popups()
        self.record("item added to the offer", item_id in edit.ad.offer_item_ids)
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
        self.record("Rolimons' rejection of the fake cookie is reported",
                    not status.get("running") and "cookie" in (status.get("error") or "").lower(),
                    status.get("error") or "")
        yield 3
        self.shot("6-result")
        self.dismiss_popups()
