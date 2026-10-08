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

import requests

from roliposter import __version__
from roliposter import theme
from roliposter.config import (MAX_OFFER_ITEMS, MAX_REQUEST_SLOTS, VALID_TAGS, Ad, Config, ConfigError,
                               load_config, save_config, validate_config)
from roliposter.cookie import (COOKIE_ENV_VAR, clean_cookie, cookie_info, get_cookie, load_env_file,
                               looks_like_cookie, save_env_value)
from roliposter.items import ItemCatalog
from roliposter.logsetup import REDACTOR, setup_logging
from roliposter.paths import config_path, env_path, log_dir, resource_path, state_path
from roliposter.poster import AuthError, Poster, fmt_duration
from roliposter.startup import StartupError, fetch_catalog_with_retry, prepare
from roliposter.state import PostHistory
from roliposter.values import evaluate_ad

log = logging.getLogger("roliposter.gui")

APP_NAME = "Rolimons Ad Poster"
REPO_URL = "https://github.com/rxst0/rolimons-ad-poster"
C = theme.COLORS

HELP_TEXT = f"""\
GETTING STARTED

1. Rolimons cookie
   This lets the app post ads as you on Rolimons. It is NOT your Roblox login.
   a) Go to rolimons.com, log in and verify your Roblox account.
   b) Press F12 to open developer tools.
   c) Chrome/Edge: Application tab > Cookies > https://www.rolimons.com
      Firefox: Storage tab > Cookies > https://www.rolimons.com
   d) Find "_RoliVerification" and copy its Value (or the whole row).
   e) Click "Set cookie" here and paste it.
   Your Roblox user ID is filled in automatically from the cookie.
   Never share this value with anyone.

2. Ads
   Click "New ad". Search items by name, add up to 4 you offer and up to 4
   things you want (items and/or tags like "upgrade" or "any"). Save.

3. Start
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
def set_app_icon(root: tk.Tk) -> None:
    """Window/taskbar icon. The explicit AppUserModelID keeps the taskbar from grouping us under python.exe."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("rxst0.RolimonsAdPoster")
    except (ImportError, AttributeError, OSError):
        pass
    icon = resource_path("assets/icon.ico")
    if icon.exists():
        try:
            root.iconbitmap(default=str(icon))
        except tk.TclError:
            pass


def short_name(catalog: ItemCatalog | None, item_id: int) -> str:
    item = catalog.get(item_id) if catalog else None
    if item is None:
        return str(item_id)
    return item.acronym or item.name


def parse_user_id(text: str) -> int | None:
    text = text.strip()
    m = re.search(r"users/(\d+)", text) or re.fullmatch(r"(\d+)", text)
    return int(m.group(1)) if m else None


def card(parent: tk.Misc, title: str | None = None, subtitle: str | None = None) -> ttk.Frame:
    """A bordered surface with an optional heading; returns the frame to put content in."""
    frame = ttk.Frame(parent, style="Card.TFrame", padding=(18, 14, 18, 16))
    if title:
        head = ttk.Frame(frame)
        head.pack(fill="x", pady=(0, 10))
        ttk.Label(head, text=title, style="Title.TLabel").pack(side="left")
        if subtitle:
            ttk.Label(head, text=subtitle, style="Muted.TLabel").pack(side="left", padx=(10, 0), pady=(3, 0))
        frame.head = head
    return frame


def scrolled_tree(parent: tk.Misc, columns: tuple[str, ...], height: int) -> tuple[ttk.Frame, ttk.Treeview]:
    wrap = ttk.Frame(parent)
    wrap.columnconfigure(0, weight=1)
    wrap.rowconfigure(0, weight=1)
    tree = ttk.Treeview(wrap, columns=columns, show="headings", height=height, selectmode="browse")
    bar = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    tree.grid(row=0, column=0, sticky="nsew")
    bar.grid(row=0, column=1, sticky="ns")
    tree.tag_configure("odd", background=theme.STRIPE)
    tree.tag_configure("off", foreground=theme.MUTED)
    return wrap, tree


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
    """Modal dialog base: themed, centered on the parent, Esc closes."""

    def __init__(self, parent: tk.Misc, title: str):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.configure(bg=theme.SURFACE)
        self.transient(parent)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.body = ttk.Frame(self, padding=22)
        self.body.pack(fill="both", expand=True)

    def footer(self, parent: tk.Misc, save_text: str, on_save, cancel: bool = True) -> ttk.Frame:
        foot = ttk.Frame(parent)
        ttk.Button(foot, text=save_text, style="Accent.TButton", width=12, command=on_save).pack(side="right")
        if cancel:
            ttk.Button(foot, text="Cancel", width=12, command=self.destroy).pack(side="right", padx=(0, 8))
        return foot

    def show(self) -> None:
        self.update_idletasks()
        parent = self.master
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_reqwidth()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        theme.dark_title_bar(self)
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
        self.minsize(1000, 560)

        b = self.body
        b.columnconfigure((0, 1, 2), weight=1, uniform="col")
        b.rowconfigure(2, weight=1)

        # Name row
        top = ttk.Frame(b)
        top.grid(row=0, column=0, columnspan=3, sticky="ew")
        top.columnconfigure(0, weight=1)
        ttk.Label(top, text="AD NAME", style="Field.TLabel").grid(row=0, column=0, sticky="w")
        self.var_name = tk.StringVar(value=self.ad.name)
        name_entry = ttk.Entry(top, textvariable=self.var_name, width=44, font=theme.FONT_TITLE)
        name_entry.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.var_enabled = tk.BooleanVar(value=self.ad.enabled)
        ttk.Checkbutton(top, text="Include in rotation", variable=self.var_enabled).grid(row=1, column=1, sticky="e")
        ttk.Separator(b).grid(row=1, column=0, columnspan=3, sticky="ew", pady=16)

        # Search
        sf = ttk.Frame(b)
        sf.grid(row=2, column=0, sticky="nsew", padx=(0, 12))
        sf.rowconfigure(2, weight=1)
        sf.columnconfigure(0, weight=1)
        ttk.Label(sf, text="Find items", style="Title.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.var_search = tk.StringVar()
        search = ttk.Entry(sf, textvariable=self.var_search)
        search.grid(row=1, column=0, sticky="ew")
        self.var_search.trace_add("write", lambda *_: self._search())
        wrap, self.results = scrolled_tree(sf, ("name", "value"), 10)
        self.results.heading("name", text="ITEM", anchor="w")
        self.results.heading("value", text="VALUE", anchor="e")
        self.results.column("name", width=170)
        self.results.column("value", width=90, anchor="e", stretch=False)
        wrap.grid(row=2, column=0, sticky="nsew", pady=8)
        self.results.bind("<Double-1>", lambda _e: self._add("offer"))
        bf = ttk.Frame(sf)
        bf.grid(row=3, column=0, sticky="ew")
        bf.columnconfigure((0, 1), weight=1)
        ttk.Button(bf, text="Add to offer", command=lambda: self._add("offer")).grid(row=0, column=0, sticky="ew")
        ttk.Button(bf, text="Add to want", command=lambda: self._add("request")).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.search_hint = ttk.Label(sf, text="Type a name, acronym or item ID.", style="Muted.TLabel")
        self.search_hint.grid(row=4, column=0, sticky="w", pady=(8, 0))

        # Offer
        of = ttk.Frame(b)
        of.grid(row=2, column=1, sticky="nsew", padx=6)
        of.columnconfigure(0, weight=1)
        ttk.Label(of, text="You offer", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(of, text=f"Up to {MAX_OFFER_ITEMS} items", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 8))
        self.offer_tree = self._item_list(of)
        self.offer_tree.grid(row=2, column=0, sticky="ew")
        ttk.Button(of, text="Remove selected", command=lambda: self._remove("offer")).grid(row=3, column=0, sticky="ew", pady=(8, 0))

        # Request
        rf = ttk.Frame(b)
        rf.grid(row=2, column=2, sticky="nsew", padx=(12, 0))
        rf.columnconfigure((0, 1), weight=1)
        ttk.Label(rf, text="You want", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(rf, text=f"Up to {MAX_REQUEST_SLOTS} items and tags combined", style="Muted.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.request_tree = self._item_list(rf)
        self.request_tree.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Button(rf, text="Remove selected", command=lambda: self._remove("request")).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(8, 14))
        ttk.Label(rf, text="TAGS", style="Field.TLabel").grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.tag_vars: dict[str, tk.BooleanVar] = {}
        for i, tag in enumerate(VALID_TAGS):
            v = tk.BooleanVar(value=tag in self.ad.request_tags)
            self.tag_vars[tag] = v
            ttk.Checkbutton(rf, text=tag, variable=v, command=lambda t=tag: self._toggle_tag(t)).grid(
                row=5 + i // 2, column=i % 2, sticky="w")

        # Footer
        ttk.Separator(b).grid(row=3, column=0, columnspan=3, sticky="ew", pady=16)
        foot = self.footer(b, "Save ad", self._save)
        foot.grid(row=4, column=0, columnspan=3, sticky="ew")
        self.summary = ttk.Label(foot, text="", style="Muted.TLabel")
        self.summary.pack(side="left")

        self._refresh_lists()
        if not app.catalog:
            self.search_hint.config(text="Item list still loading... you can type an item ID.")
        self.show()
        search.focus_set()

    @staticmethod
    def _item_list(parent) -> ttk.Treeview:
        tree = ttk.Treeview(parent, columns=("name", "value"), show="headings", height=4, selectmode="browse")
        tree.heading("name", text="ITEM", anchor="w")
        tree.heading("value", text="VALUE", anchor="e")
        tree.column("name", width=150)
        tree.column("value", width=90, anchor="e", stretch=False)
        tree.tag_configure("odd", background=theme.STRIPE)
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
            for n, (_, _, item) in enumerate(matches[:60]):
                self.results.insert("", "end", iid=str(item.id), values=(item.label, f"{item.default_value:,}"),
                                    tags=("odd",) if n % 2 else ())
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
            for n, item_id in enumerate(ids):
                item = catalog.get(item_id) if catalog else None
                values = ((item.label, f"{item.default_value:,}") if item
                          else (f"Item {item_id}", "not found" if catalog else "?"))
                tree.insert("", "end", values=values, tags=("odd",) if n % 2 else ())
        if catalog:
            av = evaluate_ad(self.ad, catalog)
            text = f"Offer value  {av.offer_value:,}"
            if av.request_value is not None:
                text += f"      Want value  {av.request_value:,}      ({av.overpay_percent:+.0f}%)"
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
        ttk.Label(b, text="Set your Rolimons cookie", style="Title.TLabel").pack(anchor="w")
        ttk.Label(b, style="Muted.TLabel", justify="left", text=(
            "On rolimons.com (logged in and verified), press F12 > Application (or Storage) > Cookies >\n"
            "https://www.rolimons.com, then copy the _RoliVerification value (or the whole row).\n\n"
            "This is NOT your Roblox password or .ROBLOSECURITY. Never share it."
        )).pack(anchor="w", pady=(6, 14))
        ttk.Label(b, text="COOKIE", style="Field.TLabel").pack(anchor="w", pady=(0, 4))
        self.var = tk.StringVar()
        entry = ttk.Entry(b, textvariable=self.var, show="•", width=64)
        entry.pack(fill="x")
        entry.bind("<Return>", lambda _e: self._save())
        self.footer(b, "Save", self._save).pack(fill="x", pady=(18, 0))
        self.show()
        entry.focus_set()

    def _save(self) -> None:
        value = clean_cookie(self.var.get())
        if not looks_like_cookie(value):
            messagebox.showwarning("Cookie", "Couldn't find a Rolimons cookie in what you pasted.\n\n"
                                   "Copy the Value of _RoliVerification (it starts with \"eyJ\").", parent=self)
            return
        info = cookie_info(value)
        if info and info.expired:
            messagebox.showwarning("Cookie", "That cookie has already expired. Reload rolimons.com and "
                                   "copy the new value.", parent=self)
            return
        save_env_value(env_path(), COOKIE_ENV_VAR, value)
        REDACTOR.add_secret(value)
        log.info("Rolimons cookie saved%s.", f" for {info.player_name}" if info and info.player_name else "")
        if info and info.player_id:
            self.app.use_cookie_user_id(info.player_id)
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
            if row:
                ttk.Separator(b).grid(row=row, column=0, columnspan=2, sticky="ew", pady=14)
                row += 1
            ttk.Label(b, text=text, style="Title.TLabel").grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
            row += 1

        def field(label, widget):
            nonlocal row
            ttk.Label(b, text=label).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 20))
            widget.grid(row=row, column=1, sticky="w", pady=5)
            row += 1

        def check(text, var):
            nonlocal row
            ttk.Checkbutton(b, text=text, variable=var).grid(row=row, column=0, columnspan=2, sticky="w", pady=2)
            row += 1

        section("Posting")
        self.var_rotation = tk.StringVar(value=c.rotation)
        rot = ttk.Frame(b)
        ttk.Radiobutton(rot, text="In order", value="sequential", variable=self.var_rotation).pack(side="left")
        ttk.Radiobutton(rot, text="Random", value="random", variable=self.var_rotation).pack(side="left", padx=16)
        field("Ad order", rot)
        self.var_jmin = tk.StringVar(value=f"{c.jitter_seconds[0]:g}")
        self.var_jmax = tk.StringVar(value=f"{c.jitter_seconds[1]:g}")
        jit = ttk.Frame(b)
        ttk.Spinbox(jit, from_=0, to=1800, textvariable=self.var_jmin, width=6).pack(side="left")
        ttk.Label(jit, text="  to  ").pack(side="left")
        ttk.Spinbox(jit, from_=0, to=1800, textvariable=self.var_jmax, width=6).pack(side="left")
        ttk.Label(jit, text="  seconds", style="Muted.TLabel").pack(side="left")
        field("Extra random delay", jit)
        self.var_max = tk.StringVar(value=str(c.max_ads_per_24h))
        field("Max ads per 24 hours", ttk.Spinbox(b, from_=1, to=96, textvariable=self.var_max, width=6))

        section("Value checks")
        vm = c.value_mode
        self.var_value = tk.BooleanVar(value=vm.enabled)
        check("Warn me when an ad overpays", self.var_value)
        self.var_overpay = tk.StringVar(value=f"{vm.overpay_warn_percent:g}")
        op = ttk.Frame(b)
        ttk.Spinbox(op, from_=0, to=1000, textvariable=self.var_overpay, width=6).pack(side="left")
        ttk.Label(op, text="  % more value than it asks for", style="Muted.TLabel").pack(side="left")
        field("Overpay threshold", op)
        self.var_skip = tk.BooleanVar(value=vm.skip_overpaying_ads)
        check("Don't post ads that overpay", self.var_skip)
        self.var_pick = tk.BooleanVar(value=vm.strategy == "pick")
        check("Smart pick: post high-demand ads more often", self.var_pick)

        ttk.Separator(b).grid(row=row, column=0, columnspan=2, sticky="ew", pady=14)
        self.footer(b, "Save", self._save).grid(row=row + 1, column=0, columnspan=2, sticky="ew")
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
        box = ttk.Frame(self.body)
        box.pack(fill="both", expand=True)
        text = tk.Text(box, width=80, height=30, wrap="word", font=theme.FONT, padx=14, pady=12,
                       **theme.text_widget_options())
        bar = ttk.Scrollbar(box, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=bar.set)
        text.insert("1.0", HELP_TEXT)
        text.config(state="disabled")
        text.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        foot = self.footer(self.body, "Got it", self.destroy, cancel=False)
        ttk.Button(foot, text="Open GitHub page", command=lambda: webbrowser.open(REPO_URL)).pack(side="left")
        foot.pack(fill="x", pady=(16, 0))
        self.show()


# ---- main window -----------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title(APP_NAME)
        set_app_icon(self)
        theme.apply_theme(self)
        self.geometry("960x780")
        self.minsize(820, 660)

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
        theme.dark_title_bar(self)
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
        root = ttk.Frame(self, style="App.TFrame", padding=(22, 18, 22, 20))
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=3)
        root.rowconfigure(4, weight=2)

        # Header
        head = ttk.Frame(root, style="App.TFrame")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        png = resource_path("assets/icon.png")
        if png.exists():
            self._logo = tk.PhotoImage(file=str(png)).subsample(7)
            ttk.Label(head, image=self._logo, style="App.TLabel").pack(side="left", padx=(0, 12))
        titles = ttk.Frame(head, style="App.TFrame")
        titles.pack(side="left")
        ttk.Label(titles, text=APP_NAME, style="AppTitle.TLabel").pack(anchor="w")
        ttk.Label(titles, text=f"Automatic Rolimons trade ads  ·  v{__version__}", style="AppMuted.TLabel").pack(anchor="w")
        ttk.Button(head, text="Help", style="Ghost.TButton", command=lambda: HelpDialog(self)).pack(side="right")
        ttk.Button(head, text="Settings", style="Ghost.TButton", command=lambda: SettingsDialog(self)).pack(side="right", padx=(0, 4))

        # Account
        acc = card(root, "Account")
        acc.grid(row=1, column=0, sticky="ew")
        grid = ttk.Frame(acc)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        ttk.Label(grid, text="ROBLOX USER ID", style="Field.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(grid, text="ROLIMONS COOKIE", style="Field.TLabel").grid(row=0, column=1, sticky="w", padx=(32, 0))
        uid_row = ttk.Frame(grid)
        uid_row.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.var_user = tk.StringVar(value=str(self.cfg.roblox_user_id or ""))
        user = ttk.Entry(uid_row, textvariable=self.var_user, width=20)
        user.pack(side="left")
        user.bind("<FocusOut>", lambda _e: self._save_user_id())
        user.bind("<Return>", lambda _e: self._save_user_id())
        self.user_status = ttk.Label(uid_row, text="")
        self.user_status.pack(side="left", padx=(10, 0))
        cookie_row = ttk.Frame(grid)
        cookie_row.grid(row=1, column=1, sticky="ew", padx=(32, 0), pady=(4, 0))
        self.cookie_status = ttk.Label(cookie_row, text="")
        self.cookie_status.pack(side="left")
        ttk.Button(cookie_row, text="Set cookie", command=lambda: CookieDialog(self)).pack(side="right")

        # Ads
        ads = card(root, "Your ads")
        ads.grid(row=2, column=0, sticky="nsew", pady=14)
        self.ads_count = ttk.Label(ads.head, text="", style="Muted.TLabel")
        self.ads_count.pack(side="left", padx=(10, 0), pady=(3, 0))
        ttk.Button(ads.head, text="+  New ad", style="Accent.TButton", command=self._new_ad).pack(side="right")
        wrap, self.tree = scrolled_tree(ads, ("name", "on", "offer", "want"), 6)
        self.tree.heading("name", text="AD", anchor="w")
        self.tree.heading("on", text="STATUS", anchor="w")
        self.tree.heading("offer", text="OFFERING", anchor="w")
        self.tree.heading("want", text="WANTS", anchor="w")
        self.tree.column("name", width=210)
        self.tree.column("on", width=80, stretch=False)
        self.tree.column("offer", width=250)
        self.tree.column("want", width=250)
        wrap.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self._edit_ad())
        self.tree.bind("<Delete>", lambda _e: self._delete_ad())
        self.empty_hint = ttk.Label(wrap, text='No ads yet — click "+ New ad" to make one.',
                                    style="Muted.TLabel", background=theme.FIELD)
        tools = ttk.Frame(ads)
        tools.pack(fill="x", pady=(10, 0))
        for text, cmd in (("Edit", self._edit_ad), ("Turn on / off", self._toggle_ad),
                          ("Move up", lambda: self._move(-1)), ("Move down", lambda: self._move(1))):
            ttk.Button(tools, text=text, command=cmd).pack(side="left", padx=(0, 8))
        ttk.Button(tools, text="Delete", command=self._delete_ad).pack(side="right")

        # Status
        run = card(root)
        run.grid(row=3, column=0, sticky="ew")
        info = ttk.Frame(run)
        info.pack(side="left", fill="x", expand=True)
        self.status = ttk.Label(info, text="Stopped", style="Status.TLabel")
        self.status.pack(anchor="w")
        self.substatus = ttk.Label(info, text="", style="Muted.TLabel")
        self.substatus.pack(anchor="w", pady=(2, 0))
        self.btn_run = ttk.Button(run, text="Start posting", style="Big.Accent.TButton", command=self._toggle_run)
        self.btn_run.pack(side="right")

        # Activity
        logf = card(root, "Activity")
        logf.grid(row=4, column=0, sticky="nsew", pady=(14, 0))
        ttk.Button(logf.head, text="Clear", command=self._clear_log).pack(side="right")
        box = ttk.Frame(logf)
        box.pack(fill="both", expand=True)
        self.logbox = tk.Text(box, height=7, state="disabled", font=theme.FONT_MONO, wrap="word", padx=10, pady=8,
                              **theme.text_widget_options())
        bar = ttk.Scrollbar(box, orient="vertical", command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=bar.set)
        self.logbox.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.logbox.tag_config("time", foreground=theme.MUTED)
        self.logbox.tag_config("warn", foreground=C["warn"])
        self.logbox.tag_config("error", foreground=C["bad"])
        self.logbox.tag_config("ok", foreground=C["ok"])

    # ---- account -------------------------------------------------------
    def _save_user_id(self) -> None:
        text = self.var_user.get()
        uid = parse_user_id(text)
        if text.strip() and uid is None:
            self.user_status.config(text="Numbers only", foreground=C["bad"])
            return
        uid = uid or 0
        if uid != self.cfg.roblox_user_id:
            self.cfg.roblox_user_id = uid
            self.persist()
        self.var_user.set(str(uid) if uid else "")
        self._update_user_status()

    def _update_user_status(self) -> None:
        ok = self.cfg.roblox_user_id > 0
        self.user_status.config(text="✓" if ok else "Required", foreground=C["ok" if ok else "bad"])

    def update_cookie_status(self) -> None:
        try:
            cookie = get_cookie()
        except ValueError:
            cookie = None
        info = cookie_info(cookie) if cookie else None
        if not cookie:
            text, color = "Not set", "bad"
        elif info and info.expired:
            text, color = "Expired — set a new one", "bad"
        elif info and info.expires_at:
            who = f"{info.player_name}  ·  " if info.player_name else ""
            text, color = f"✓  {who}expires {time.strftime('%d %b %Y', time.localtime(info.expires_at))}", "ok"
        else:
            text, color = "✓  Saved", "ok"
        self.cookie_status.config(text=text, foreground=C[color])
        self._update_user_status()

    def use_cookie_user_id(self, player_id: int) -> None:
        """The cookie says which Roblox account it verifies; use that ID so the two can't disagree."""
        if self.cfg.roblox_user_id != player_id:
            if self.cfg.roblox_user_id:
                log.info("Roblox user ID changed from %d to %d to match your cookie.",
                         self.cfg.roblox_user_id, player_id)
            self.cfg.roblox_user_id = player_id
            self.persist()
        self.var_user.set(str(player_id))
        self._update_user_status()

    # ---- ads -----------------------------------------------------------
    def refresh_ads(self) -> None:
        selected = self._selected_index()
        self.tree.delete(*self.tree.get_children())
        for i, ad in enumerate(self.cfg.ads):
            offer = ", ".join(short_name(self.catalog, x) for x in ad.offer_item_ids)
            want = ", ".join([short_name(self.catalog, x) for x in ad.request_item_ids] + ad.request_tags)
            tags = (("odd",) if i % 2 else ()) + (() if ad.enabled else ("off",))
            self.tree.insert("", "end", iid=str(i), values=(ad.name, "● On" if ad.enabled else "○ Off", offer, want),
                             tags=tags)
        on = len(self.cfg.enabled_ads())
        self.ads_count.config(text=f"{len(self.cfg.ads)} total  ·  {on} on" if self.cfg.ads else "")
        if self.cfg.ads:
            self.empty_hint.place_forget()
            if selected is not None:
                self._select(min(selected, len(self.cfg.ads) - 1))
        else:
            self.empty_hint.place(relx=0.5, rely=0.55, anchor="center")

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
            self.status.config(text="Stopping...", foreground=C["text"])
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
        except AuthError as e:
            log.error("Rolimons rejected your cookie: %s", e)
            self.events.put(("error", f"Rolimons rejected your cookie (\"{e}\").\n\n"
                                      "It may have been reset by logging out or re-verifying on Rolimons. "
                                      "Open rolimons.com, copy the current _RoliVerification value, "
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
                            style="Big.TButton" if running else "Big.Accent.TButton")
        self.status.config(text="Starting..." if running else "Stopped", foreground=C["text"])

    def _tick(self) -> None:
        poster = self.poster
        count = f"{self.history.count_24h()} of {self.cfg.max_ads_per_24h} ads posted in the last 24 hours"
        if poster and poster.wait_until:
            remaining = max(0, poster.wait_until - time.time())
            self.status.config(text=f"Next ad in {fmt_duration(remaining)}", foreground=C["accent"])
            self.substatus.config(text=f"{poster.status_text.capitalize()}  ·  {count}")
        elif poster:
            self.status.config(text=poster.status_text, foreground=C["accent"])
            self.substatus.config(text=count)
        elif self.worker and self.worker.is_alive():
            self.status.config(text="Checking setup...", foreground=C["text"])
        else:
            self.substatus.config(text=f"Ready when you are  ·  {count}")
        self.after(500, self._tick)

    # ---- background events --------------------------------------------
    def _load_catalog(self) -> None:
        try:
            self.events.put(("catalog", fetch_catalog_with_retry(requests.Session())))
        except StartupError as e:
            log.warning("%s", e)

    def _clear_log(self) -> None:
        self.logbox.config(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.config(state="disabled")

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
                stamp, _, rest = text.partition(" | ")
                _, _, message = rest.partition(" | ")
                self.logbox.insert("end", stamp[11:] + "  ", "time")
                self.logbox.insert("end", (message or text) + "\n", tag)
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
