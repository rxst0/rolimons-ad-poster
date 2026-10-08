"""Rolimons Ad Poster - simple desktop app."""
import copy
import logging
import queue
import re
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import requests

from roliposter import __version__
from roliposter.config import (MAX_OFFER_ITEMS, MAX_REQUEST_SLOTS, VALID_TAGS, Ad, Config, ConfigError,
                               load_config, save_config, validate_config)
from roliposter.cookie import COOKIE_ENV_VAR, clean_cookie, get_cookie, load_env_file, save_env_value
from roliposter.items import ItemCatalog
from roliposter.logsetup import REDACTOR, setup_logging
from roliposter.paths import config_path, env_path, log_dir, state_path
from roliposter.poster import AuthError, Poster, fmt_duration
from roliposter.startup import StartupError, fetch_catalog_with_retry, prepare
from roliposter.state import PostHistory
from roliposter.values import evaluate_ad

log = logging.getLogger("roliposter.gui")

APP_NAME = "Rolimons Ad Poster"
REPO_URL = "https://github.com/rxst0/rolimons-ad-poster"
PAD = 8

HELP_TEXT = f"""\
GETTING STARTED

1. Roblox user ID
   Open your Roblox profile. The number in the address bar is your ID:
   roblox.com/users/123456789/profile  ->  123456789
   (You can paste the whole profile link; the ID is pulled out for you.)

2. Rolimons cookie
   This lets the app post ads as you on Rolimons. It is NOT your Roblox login.
   a) Go to rolimons.com, log in and verify your Roblox account.
   b) Press F12 to open developer tools.
   c) Chrome/Edge: Application tab > Cookies > https://www.rolimons.com
      Firefox: Storage tab > Cookies > https://www.rolimons.com
   d) Find "_RoliVerification" and copy its Value.
   e) Click "Set cookie" here and paste it.
   Never share this value with anyone. If posting says the cookie expired,
   repeat these steps.

3. Ads
   Click "New ad". Search items by name, add up to 4 you offer and up to 4
   things you want (items and/or tags like "upgrade" or "any"). Save.

4. Start
   Click "Start posting". One ad is posted roughly every 15 minutes
   (Rolimons' cooldown) plus a small random delay, cycling through your ads.
   Leave the app open. Click "Stop" any time.

SAFETY
- This app only posts Rolimons trade ads. It never sends Roblox trades and
  never asks for your .ROBLOSECURITY cookie. Anyone who asks for that is
  trying to steal your account.
- Your cookie is saved in a ".env" file next to the app. Don't share that file.

FILES (next to the app)
  config.json  your ads and settings
  .env         your Rolimons cookie
  logs\\        a log of every post attempt

Version {__version__} - {REPO_URL}
"""


# ---- helpers ---------------------------------------------------------------
def system_uses_dark_mode() -> bool:
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except (ImportError, OSError):
        return False


def apply_theme(root: tk.Tk) -> bool:
    """Applies the Sun Valley (Windows 11) theme if available. Returns True for dark mode."""
    dark = system_uses_dark_mode()
    try:
        import sv_ttk
        sv_ttk.set_theme("dark" if dark else "light", root)
        return dark
    except Exception:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        return False


def short_name(catalog: ItemCatalog | None, item_id: int) -> str:
    item = catalog.get(item_id) if catalog else None
    if item is None:
        return str(item_id)
    return item.acronym or item.name


def parse_user_id(text: str) -> int | None:
    text = text.strip()
    m = re.search(r"users/(\d+)", text) or re.fullmatch(r"(\d+)", text)
    return int(m.group(1)) if m else None


class QueueLogHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.q.put((record.levelno, self.format(record)))
        except Exception:
            self.handleError(record)


class Dialog(tk.Toplevel):
    """Modal dialog base: centered on the parent, Esc closes."""

    def __init__(self, parent: tk.Misc, title: str):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.transient(parent)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.body = ttk.Frame(self, padding=16)
        self.body.pack(fill="both", expand=True)

    def show(self) -> None:
        self.update_idletasks()
        parent = self.master
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_reqwidth()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.deiconify()
        self.grab_set()
        self.focus_set()


# ---- dialogs ---------------------------------------------------------------
class AdEditor(Dialog):
    def __init__(self, app: "App", ad: Ad, on_save):
        super().__init__(app, "Edit ad")
        self.app = app
        self.ad = copy.deepcopy(ad)
        self.on_save = on_save
        self.minsize(900, 520)

        b = self.body
        b.columnconfigure((0, 1, 2), weight=1, uniform="col")
        b.rowconfigure(1, weight=1)

        top = ttk.Frame(b)
        top.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        ttk.Label(top, text="Ad name").pack(side="left")
        self.var_name = tk.StringVar(value=self.ad.name)
        name_entry = ttk.Entry(top, textvariable=self.var_name, width=40)
        name_entry.pack(side="left", padx=8)
        self.var_enabled = tk.BooleanVar(value=self.ad.enabled)
        ttk.Checkbutton(top, text="Include in rotation", variable=self.var_enabled).pack(side="left", padx=8)

        # Search
        sf = ttk.LabelFrame(b, text=" Find items ", padding=8)
        sf.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        sf.rowconfigure(1, weight=1)
        sf.columnconfigure(0, weight=1)
        self.var_search = tk.StringVar()
        search = ttk.Entry(sf, textvariable=self.var_search)
        search.grid(row=0, column=0, sticky="ew")
        self.var_search.trace_add("write", lambda *_: self._search())
        self.results = ttk.Treeview(sf, columns=("name", "value"), show="headings", height=10, selectmode="browse")
        self.results.heading("name", text="Item")
        self.results.heading("value", text="Value")
        self.results.column("name", width=170)
        self.results.column("value", width=80, anchor="e")
        self.results.grid(row=1, column=0, sticky="nsew", pady=6)
        self.results.bind("<Double-1>", lambda _e: self._add("offer"))
        bf = ttk.Frame(sf)
        bf.grid(row=2, column=0, sticky="ew")
        ttk.Button(bf, text="Add to offer", command=lambda: self._add("offer")).pack(side="left", expand=True, fill="x")
        ttk.Button(bf, text="Add to want", command=lambda: self._add("request")).pack(side="left", expand=True, fill="x", padx=(6, 0))
        self.search_hint = ttk.Label(sf, text="Type a name, acronym or item ID.", foreground="gray")
        self.search_hint.grid(row=3, column=0, sticky="w", pady=(6, 0))

        # Offer
        of = ttk.LabelFrame(b, text=f" You offer (max {MAX_OFFER_ITEMS}) ", padding=8)
        of.grid(row=1, column=1, sticky="nsew", padx=6)
        of.columnconfigure(0, weight=1)
        self.offer_tree = self._item_list(of)
        self.offer_tree.grid(row=0, column=0, sticky="nsew")
        ttk.Button(of, text="Remove selected", command=lambda: self._remove("offer")).grid(row=1, column=0, sticky="ew", pady=(6, 0))

        # Request
        rf = ttk.LabelFrame(b, text=f" You want (max {MAX_REQUEST_SLOTS}, items + tags) ", padding=8)
        rf.grid(row=1, column=2, sticky="nsew", padx=(6, 0))
        rf.columnconfigure((0, 1), weight=1)
        self.request_tree = self._item_list(rf)
        self.request_tree.grid(row=0, column=0, columnspan=2, sticky="nsew")
        ttk.Button(rf, text="Remove selected", command=lambda: self._remove("request")).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 8))
        ttk.Label(rf, text="Tags").grid(row=2, column=0, columnspan=2, sticky="w")
        self.tag_vars: dict[str, tk.BooleanVar] = {}
        for i, tag in enumerate(VALID_TAGS):
            v = tk.BooleanVar(value=tag in self.ad.request_tags)
            self.tag_vars[tag] = v
            ttk.Checkbutton(rf, text=tag, variable=v, command=lambda t=tag: self._toggle_tag(t)).grid(
                row=3 + i // 2, column=i % 2, sticky="w")

        # Footer
        foot = ttk.Frame(b)
        foot.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        self.summary = ttk.Label(foot, text="")
        self.summary.pack(side="left")
        ttk.Button(foot, text="Save", style="Accent.TButton", width=12, command=self._save).pack(side="right")
        ttk.Button(foot, text="Cancel", width=12, command=self.destroy).pack(side="right", padx=8)

        self._refresh_lists()
        if not app.catalog:
            self.search_hint.config(text="Item list still loading... you can type an item ID.")
        self.show()
        search.focus_set() if self.ad.name else name_entry.focus_set()

    @staticmethod
    def _item_list(parent) -> ttk.Treeview:
        tree = ttk.Treeview(parent, columns=("name", "value"), show="headings", height=4, selectmode="browse")
        tree.heading("name", text="Item")
        tree.heading("value", text="Value")
        tree.column("name", width=150)
        tree.column("value", width=80, anchor="e", stretch=False)
        return tree

    def _search(self) -> None:
        self.results.delete(*self.results.get_children())
        q = self.var_search.get().strip().lower()
        if not q:
            return
        catalog = self.app.catalog
        matches = []
        if catalog:
            for item in catalog.items.values():
                if q == str(item.id) or q in item.name.lower() or q == item.acronym.lower():
                    rank = 0 if q in (item.acronym.lower(), str(item.id)) else 1 if item.name.lower().startswith(q) else 2
                    matches.append((rank, -item.default_value, item))
            matches.sort(key=lambda m: (m[0], m[1]))
            for _, _, item in matches[:60]:
                self.results.insert("", "end", iid=str(item.id), values=(item.label, f"{item.default_value:,}"))
        elif q.isdigit():
            self.results.insert("", "end", iid=q, values=(f"Item {q}", "?"))

    def _request_slots(self) -> int:
        return len(self.ad.request_item_ids) + sum(v.get() for v in self.tag_vars.values())

    def _add(self, side: str) -> None:
        sel = self.results.selection()
        if not sel:
            return
        item_id = int(sel[0])
        if side == "offer":
            if len(self.ad.offer_item_ids) >= MAX_OFFER_ITEMS:
                self.bell()
                return
            self.ad.offer_item_ids.append(item_id)
        else:
            if self._request_slots() >= MAX_REQUEST_SLOTS:
                self.bell()
                return
            self.ad.request_item_ids.append(item_id)
        self._refresh_lists()

    def _remove(self, side: str) -> None:
        tree = self.offer_tree if side == "offer" else self.request_tree
        sel = tree.selection()
        if not sel:
            return
        index = tree.index(sel[0])
        (self.ad.offer_item_ids if side == "offer" else self.ad.request_item_ids).pop(index)
        self._refresh_lists()

    def _toggle_tag(self, tag: str) -> None:
        if self.tag_vars[tag].get() and self._request_slots() > MAX_REQUEST_SLOTS:
            self.tag_vars[tag].set(False)
            self.bell()

    def _refresh_lists(self) -> None:
        catalog = self.app.catalog
        for tree, ids in ((self.offer_tree, self.ad.offer_item_ids), (self.request_tree, self.ad.request_item_ids)):
            tree.delete(*tree.get_children())
            for item_id in ids:
                item = catalog.get(item_id) if catalog else None
                tree.insert("", "end", values=(item.label, f"{item.default_value:,}") if item
                            else (f"Item {item_id}", "not found" if catalog else "?"))
        if catalog:
            av = evaluate_ad(self.ad, catalog)
            text = f"Offer value: {av.offer_value:,}"
            if av.request_value is not None:
                text += f"    Want value: {av.request_value:,}    ({av.overpay_percent:+.0f}%)"
            self.summary.config(text=text)

    def _save(self) -> None:
        self.ad.name = self.var_name.get().strip()
        self.ad.enabled = self.var_enabled.get()
        self.ad.request_tags = [t for t, v in self.tag_vars.items() if v.get()]
        problem = None
        if not self.ad.name:
            problem = "Give the ad a name."
        elif not self.ad.offer_item_ids:
            problem = "Add at least one item you offer."
        elif not self.ad.request_item_ids and not self.ad.request_tags:
            problem = "Add at least one item or tag you want."
        else:
            problem = self.on_save(self.ad)
        if problem:
            messagebox.showwarning("Can't save yet", problem, parent=self)
            return
        self.destroy()


class CookieDialog(Dialog):
    def __init__(self, app: "App"):
        super().__init__(app, "Rolimons cookie")
        self.app = app
        b = self.body
        ttk.Label(b, text="Paste your _RoliVerification cookie value", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(b, justify="left", text=(
            "rolimons.com (logged in + verified) > F12 > Application/Storage > Cookies >\n"
            "https://www.rolimons.com > _RoliVerification > copy the Value.\n"
            "This is NOT your Roblox password or .ROBLOSECURITY. Never share it."
        )).pack(anchor="w", pady=(4, 10))
        self.var = tk.StringVar()
        entry = ttk.Entry(b, textvariable=self.var, show="•", width=60)
        entry.pack(fill="x")
        entry.bind("<Return>", lambda _e: self._save())
        foot = ttk.Frame(b)
        foot.pack(fill="x", pady=(12, 0))
        ttk.Button(foot, text="Save", style="Accent.TButton", width=12, command=self._save).pack(side="right")
        ttk.Button(foot, text="Cancel", width=12, command=self.destroy).pack(side="right", padx=8)
        self.show()
        entry.focus_set()

    def _save(self) -> None:
        value = clean_cookie(self.var.get())
        if not value or re.search(r"[\s;,]", value):
            messagebox.showwarning("Cookie", "That doesn't look like a cookie value.", parent=self)
            return
        save_env_value(env_path(), COOKIE_ENV_VAR, value)
        REDACTOR.add_secret(value)
        log.info("Rolimons cookie saved.")
        self.app.update_cookie_status()
        self.destroy()


class SettingsDialog(Dialog):
    def __init__(self, app: "App"):
        super().__init__(app, "Settings")
        self.app = app
        c = app.cfg
        b = self.body
        b.columnconfigure(1, weight=1)
        row = 0

        def section(text):
            nonlocal row
            ttk.Label(b, text=text, font=("Segoe UI", 10, "bold")).grid(row=row, column=0, columnspan=2, sticky="w", pady=(10 if row else 0, 4))
            row += 1

        def field(label, widget):
            nonlocal row
            ttk.Label(b, text=label).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 12))
            widget.grid(row=row, column=1, sticky="w", pady=3)
            row += 1

        section("Posting")
        self.var_rotation = tk.StringVar(value=c.rotation)
        rot = ttk.Frame(b)
        ttk.Radiobutton(rot, text="In order", value="sequential", variable=self.var_rotation).pack(side="left")
        ttk.Radiobutton(rot, text="Random", value="random", variable=self.var_rotation).pack(side="left", padx=12)
        field("Ad order", rot)
        self.var_jmin = tk.StringVar(value=f"{c.jitter_seconds[0]:g}")
        self.var_jmax = tk.StringVar(value=f"{c.jitter_seconds[1]:g}")
        jit = ttk.Frame(b)
        ttk.Spinbox(jit, from_=0, to=1800, textvariable=self.var_jmin, width=6).pack(side="left")
        ttk.Label(jit, text=" to ").pack(side="left")
        ttk.Spinbox(jit, from_=0, to=1800, textvariable=self.var_jmax, width=6).pack(side="left")
        ttk.Label(jit, text=" seconds").pack(side="left")
        field("Extra random delay", jit)
        self.var_max = tk.StringVar(value=str(c.max_ads_per_24h))
        field("Max ads per 24 hours", ttk.Spinbox(b, from_=1, to=96, textvariable=self.var_max, width=6))

        section("Value checks (uses Rolimons values)")
        vm = c.value_mode
        self.var_value = tk.BooleanVar(value=vm.enabled)
        ttk.Checkbutton(b, text="Warn me when an ad overpays", variable=self.var_value).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        self.var_overpay = tk.StringVar(value=f"{vm.overpay_warn_percent:g}")
        op = ttk.Frame(b)
        ttk.Spinbox(op, from_=0, to=1000, textvariable=self.var_overpay, width=6).pack(side="left")
        ttk.Label(op, text=" % more value than it asks for").pack(side="left")
        field("Overpay threshold", op)
        self.var_skip = tk.BooleanVar(value=vm.skip_overpaying_ads)
        ttk.Checkbutton(b, text="Don't post ads that overpay", variable=self.var_skip).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        self.var_pick = tk.BooleanVar(value=vm.strategy == "pick")
        ttk.Checkbutton(b, text="Smart pick: post high-demand ads more often", variable=self.var_pick).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        foot = ttk.Frame(b)
        foot.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        ttk.Button(foot, text="Save", style="Accent.TButton", width=12, command=self._save).pack(side="right")
        ttk.Button(foot, text="Cancel", width=12, command=self.destroy).pack(side="right", padx=8)
        self.show()

    def _save(self) -> None:
        try:
            jmin, jmax = float(self.var_jmin.get()), float(self.var_jmax.get())
            max_ads = int(self.var_max.get())
            overpay = float(self.var_overpay.get())
        except ValueError:
            messagebox.showwarning("Settings", "Please enter numbers only.", parent=self)
            return
        if not (0 <= jmin <= jmax) or not 1 <= max_ads <= 96:
            messagebox.showwarning("Settings", "Delay must be min <= max, and max ads 1-96.", parent=self)
            return
        c = self.app.cfg
        c.rotation = self.var_rotation.get()
        c.jitter_seconds = [jmin, jmax]
        c.max_ads_per_24h = max_ads
        c.value_mode.enabled = self.var_value.get() or self.var_skip.get() or self.var_pick.get()
        c.value_mode.overpay_warn_percent = overpay
        c.value_mode.skip_overpaying_ads = self.var_skip.get()
        c.value_mode.strategy = "pick" if self.var_pick.get() else "warn"
        self.app.persist()
        self.destroy()


class HelpDialog(Dialog):
    def __init__(self, app: "App"):
        super().__init__(app, "How to use")
        text = tk.Text(self.body, width=78, height=34, wrap="word", relief="flat", font=("Segoe UI", 10),
                       padx=8, pady=8, **app.text_colors)
        text.insert("1.0", HELP_TEXT)
        text.config(state="disabled")
        text.pack(fill="both", expand=True)
        foot = ttk.Frame(self.body)
        foot.pack(fill="x", pady=(10, 0))
        ttk.Button(foot, text="Open GitHub page", command=lambda: webbrowser.open(REPO_URL)).pack(side="left")
        ttk.Button(foot, text="Close", style="Accent.TButton", width=12, command=self.destroy).pack(side="right")
        self.show()


# ---- main window -----------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title(APP_NAME)
        self.geometry("900x720")
        self.minsize(760, 600)
        dark = apply_theme(self)
        self.text_colors = ({"bg": "#1c1c1c", "fg": "#e6e6e6", "insertbackground": "#e6e6e6"} if dark
                            else {"bg": "#fafafa", "fg": "#1a1a1a", "insertbackground": "#1a1a1a"})
        self.colors = {"ok": "#3fb950" if dark else "#1a7f37", "bad": "#f85149" if dark else "#cf222e",
                       "warn": "#d29922" if dark else "#9a6700", "muted": "#8b949e" if dark else "#6e7781"}

        self.log_queue: queue.Queue = queue.Queue()
        self.events: queue.Queue = queue.Queue()
        setup_logging(log_dir(), (QueueLogHandler(self.log_queue),))
        load_env_file(env_path())

        self.cfg_path = config_path()
        self.cfg = self._load_cfg()
        self.catalog: ItemCatalog | None = None
        self.poster: Poster | None = None
        self.worker: threading.Thread | None = None
        self.stop_event: threading.Event | None = None
        self.history = PostHistory(state_path())

        self._build()
        self.refresh_ads()
        self.update_cookie_status()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        threading.Thread(target=self._load_catalog, daemon=True).start()
        self.after(100, self._poll)
        self.after(500, self._tick)
        self.deiconify()
        if not self.cfg.roblox_user_id and not self.cfg.ads:
            self.after(300, lambda: HelpDialog(self))

    def _load_cfg(self) -> Config:
        try:
            return load_config(self.cfg_path)
        except ConfigError as e:
            if self.cfg_path.exists():
                messagebox.showwarning(APP_NAME, f"{e}\n\nStarting with an empty setup.")
            return Config()

    def persist(self) -> None:
        save_config(self.cfg, self.cfg_path)
        self.refresh_ads()

    # ---- layout --------------------------------------------------------
    def _build(self) -> None:
        root = ttk.Frame(self, padding=(16, 12, 16, 12))
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)
        root.rowconfigure(4, weight=1)

        # Header
        head = ttk.Frame(root)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(head, text=APP_NAME, font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Button(head, text="Help", command=lambda: HelpDialog(self)).pack(side="right")
        ttk.Button(head, text="Settings", command=lambda: SettingsDialog(self)).pack(side="right", padx=8)

        # Account
        acc = ttk.LabelFrame(root, text=" Account ", padding=12)
        acc.grid(row=1, column=0, sticky="ew")
        acc.columnconfigure(4, weight=1)
        ttk.Label(acc, text="Roblox user ID").grid(row=0, column=0, sticky="w")
        self.var_user = tk.StringVar(value=str(self.cfg.roblox_user_id or ""))
        user = ttk.Entry(acc, textvariable=self.var_user, width=22)
        user.grid(row=0, column=1, padx=(8, 4))
        user.bind("<FocusOut>", lambda _e: self._save_user_id())
        user.bind("<Return>", lambda _e: self._save_user_id())
        self.user_status = ttk.Label(acc, text="")
        self.user_status.grid(row=0, column=2, padx=(0, 24), sticky="w")
        ttk.Label(acc, text="Rolimons cookie").grid(row=0, column=3, sticky="e")
        self.cookie_status = ttk.Label(acc, text="")
        self.cookie_status.grid(row=0, column=4, padx=8, sticky="w")
        ttk.Button(acc, text="Set cookie", command=lambda: CookieDialog(self)).grid(row=0, column=5)

        # Ads
        ads = ttk.LabelFrame(root, text=" Your ads ", padding=12)
        ads.grid(row=2, column=0, sticky="nsew", pady=12)
        ads.columnconfigure(0, weight=1)
        ads.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(ads, columns=("name", "on", "offer", "want"), show="headings", height=6, selectmode="browse")
        self.tree.heading("name", text="Ad", anchor="w")
        self.tree.heading("on", text="On")
        self.tree.heading("offer", text="Offering", anchor="w")
        self.tree.heading("want", text="Wants", anchor="w")
        self.tree.column("name", width=200)
        self.tree.column("on", width=44, anchor="center", stretch=False)
        self.tree.column("offer", width=260)
        self.tree.column("want", width=260)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", lambda _e: self._edit_ad())
        self.tree.bind("<Delete>", lambda _e: self._delete_ad())
        self.empty_hint = ttk.Label(ads, text='No ads yet. Click "New ad" to make one.', foreground=self.colors["muted"])
        btns = ttk.Frame(ads)
        btns.grid(row=0, column=1, sticky="n", padx=(12, 0))
        for text, cmd, style in (("New ad", self._new_ad, "Accent.TButton"), ("Edit", self._edit_ad, "TButton"),
                                 ("On / Off", self._toggle_ad, "TButton"), ("Move up", lambda: self._move(-1), "TButton"),
                                 ("Move down", lambda: self._move(1), "TButton"), ("Delete", self._delete_ad, "TButton")):
            ttk.Button(btns, text=text, command=cmd, style=style, width=12).pack(fill="x", pady=(0, 6))

        # Run
        run = ttk.Frame(root)
        run.grid(row=3, column=0, sticky="ew")
        self.btn_run = ttk.Button(run, text="Start posting", style="Accent.TButton", width=18, command=self._toggle_run)
        self.btn_run.pack(side="left", ipady=4)
        info = ttk.Frame(run)
        info.pack(side="left", padx=16)
        self.status = ttk.Label(info, text="Stopped", font=("Segoe UI", 12, "bold"))
        self.status.pack(anchor="w")
        self.substatus = ttk.Label(info, text="", foreground=self.colors["muted"])
        self.substatus.pack(anchor="w")

        # Log
        logf = ttk.LabelFrame(root, text=" Activity ", padding=8)
        logf.grid(row=4, column=0, sticky="nsew", pady=(12, 0))
        self.logbox = ScrolledText(logf, height=8, state="disabled", font=("Consolas", 9), wrap="word",
                                   relief="flat", **self.text_colors)
        self.logbox.pack(fill="both", expand=True)
        self.logbox.tag_config("warn", foreground=self.colors["warn"])
        self.logbox.tag_config("error", foreground=self.colors["bad"])
        self.logbox.tag_config("ok", foreground=self.colors["ok"])

    # ---- account -------------------------------------------------------
    def _save_user_id(self) -> None:
        text = self.var_user.get()
        uid = parse_user_id(text)
        if text.strip() and uid is None:
            self.user_status.config(text="Numbers only", foreground=self.colors["bad"])
            return
        uid = uid or 0
        if uid != self.cfg.roblox_user_id:
            self.cfg.roblox_user_id = uid
            self.persist()
        self.var_user.set(str(uid) if uid else "")
        self._update_user_status()

    def _update_user_status(self) -> None:
        ok = self.cfg.roblox_user_id > 0
        self.user_status.config(text="✓" if ok else "Required", foreground=self.colors["ok" if ok else "bad"])

    def update_cookie_status(self) -> None:
        try:
            ok = bool(get_cookie())
        except ValueError:
            ok = False
        self.cookie_status.config(text="✓ Saved" if ok else "Not set", foreground=self.colors["ok" if ok else "bad"])
        self._update_user_status()

    # ---- ads -----------------------------------------------------------
    def refresh_ads(self) -> None:
        selected = self._selected_index()
        self.tree.delete(*self.tree.get_children())
        for i, ad in enumerate(self.cfg.ads):
            offer = ", ".join(short_name(self.catalog, x) for x in ad.offer_item_ids)
            want = ", ".join([short_name(self.catalog, x) for x in ad.request_item_ids] + ad.request_tags)
            self.tree.insert("", "end", iid=str(i), values=(ad.name, "✓" if ad.enabled else "–", offer, want))
        if self.cfg.ads:
            self.empty_hint.place_forget()
            if selected is not None:
                self._select(min(selected, len(self.cfg.ads) - 1))
        else:
            self.empty_hint.place(in_=self.tree, relx=0.5, rely=0.55, anchor="center")

    def _selected_index(self) -> int | None:
        sel = self.tree.selection() if hasattr(self, "tree") else ()
        return int(sel[0]) if sel else None

    def _select(self, index: int) -> None:
        self.tree.selection_set(str(index))
        self.tree.see(str(index))

    def _name_taken(self, name: str, ignore: int | None) -> bool:
        return any(a.name == name for i, a in enumerate(self.cfg.ads) if i != ignore)

    def _new_ad(self) -> None:
        n = len(self.cfg.ads) + 1
        while self._name_taken(f"Ad {n}", None):
            n += 1

        def on_save(ad: Ad):
            if self._name_taken(ad.name, None):
                return "Another ad already has that name."
            self.cfg.ads.append(ad)
            self.persist()
            self._select(len(self.cfg.ads) - 1)
        AdEditor(self, Ad(name=f"Ad {n}"), on_save)

    def _edit_ad(self) -> None:
        index = self._selected_index()
        if index is None:
            return

        def on_save(ad: Ad):
            if self._name_taken(ad.name, index):
                return "Another ad already has that name."
            self.cfg.ads[index] = ad
            self.persist()
        AdEditor(self, self.cfg.ads[index], on_save)

    def _toggle_ad(self) -> None:
        index = self._selected_index()
        if index is not None:
            self.cfg.ads[index].enabled = not self.cfg.ads[index].enabled
            self.persist()

    def _move(self, delta: int) -> None:
        i = self._selected_index()
        if i is None or not 0 <= i + delta < len(self.cfg.ads):
            return
        ads = self.cfg.ads
        ads[i], ads[i + delta] = ads[i + delta], ads[i]
        self.persist()
        self._select(i + delta)

    def _delete_ad(self) -> None:
        index = self._selected_index()
        if index is not None and messagebox.askyesno("Delete ad", f"Delete '{self.cfg.ads[index].name}'?"):
            del self.cfg.ads[index]
            self.persist()

    # ---- running -------------------------------------------------------
    def _toggle_run(self) -> None:
        if self.worker and self.worker.is_alive():
            if self.stop_event:
                self.stop_event.set()
            self.btn_run.config(state="disabled")
            self.status.config(text="Stopping...")
            return
        self._save_user_id()
        try:
            has_cookie = bool(get_cookie())
        except ValueError:
            has_cookie = False
        if not has_cookie:
            messagebox.showinfo(APP_NAME, "Set your Rolimons cookie first (click \"Set cookie\").")
            return
        errors = validate_config(self.cfg)
        if errors:
            messagebox.showwarning(APP_NAME, "Fix these first:\n\n• " + "\n• ".join(errors))
            return
        self.stop_event = threading.Event()
        self.worker = threading.Thread(target=self._run_worker, args=(self.stop_event,), daemon=True)
        self.worker.start()
        self._set_running(True)

    def _run_worker(self, stop_event: threading.Event) -> None:
        session = requests.Session()
        try:
            cfg, cookie, catalog = prepare(self.cfg_path, session, stop_event)
            self.events.put(("catalog", catalog))
            if not stop_event.is_set():
                self.poster = Poster(cfg, self.cfg_path, cookie, catalog, stop_event, session)
                self.history = self.poster.history
                self.poster.run()
        except AuthError:
            log.error("Rolimons rejected your cookie (invalid or expired).")
            self.events.put(("error", "Rolimons rejected your cookie. It is wrong or has expired.\n\n"
                                      "Log in to rolimons.com again, copy a fresh _RoliVerification value, "
                                      "click \"Set cookie\", and start again."))
        except StartupError as e:
            log.error("%s", e)
            self.events.put(("error", str(e)))
        except Exception:
            log.exception("Unexpected error")
            self.events.put(("error", "Something went wrong. See the Activity log for details."))
        finally:
            self.poster = None
            self.events.put(("stopped", None))

    def _set_running(self, running: bool) -> None:
        self.btn_run.config(text="Stop" if running else "Start posting", state="normal",
                            style="TButton" if running else "Accent.TButton")
        self.status.config(text="Running" if running else "Stopped",
                           foreground=self.colors["ok"] if running else "")

    def _tick(self) -> None:
        poster = self.poster
        count = f"Ads posted in the last 24h: {self.history.count_24h()} / {self.cfg.max_ads_per_24h}"
        if poster and poster.wait_until:
            remaining = max(0, poster.wait_until - time.time())
            self.status.config(text=f"Next ad in {fmt_duration(remaining)}")
            self.substatus.config(text=f"{poster.status_text.capitalize()}  ·  {count}")
        elif poster:
            self.status.config(text=poster.status_text)
            self.substatus.config(text=count)
        elif self.worker and self.worker.is_alive():
            self.status.config(text="Checking setup...")
        else:
            self.substatus.config(text=count)
        self.after(500, self._tick)

    # ---- background events --------------------------------------------
    def _load_catalog(self) -> None:
        try:
            self.events.put(("catalog", fetch_catalog_with_retry(requests.Session())))
        except StartupError as e:
            log.warning("%s", e)

    def _poll(self) -> None:
        lines = []
        while True:
            try:
                lines.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        if lines:
            self.logbox.config(state="normal")
            for level, text in lines:
                tag = ("error" if level >= logging.ERROR else "warn" if level >= logging.WARNING
                       else "ok" if "result=SUCCESS" in text else "")
                self.logbox.insert("end", text + "\n", tag)
            if int(self.logbox.index("end-1c").split(".")[0]) > 3000:
                self.logbox.delete("1.0", "1000.0")
            self.logbox.see("end")
            self.logbox.config(state="disabled")
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "stopped":
                self._set_running(False)
            elif kind == "error":
                messagebox.showerror(APP_NAME, payload)
            elif kind == "catalog":
                self.catalog = payload
                self.refresh_ads()
        self.after(100, self._poll)

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_NAME, "Posting is running. Stop and quit?"):
                return
            if self.stop_event:
                self.stop_event.set()
            self.worker.join(timeout=3)
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
