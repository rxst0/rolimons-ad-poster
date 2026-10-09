"""Rolimons Ad Poster - simple desktop app."""
import copy
import logging
import queue
import re
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

import requests

from roliposter import __version__, autostart
from roliposter import theme
from roliposter.config import (MAX_OFFER_ITEMS, MAX_REQUEST_SLOTS, VALID_TAGS, Ad, Config, ConfigError,
                               load_config, save_config, validate_config)
from roliposter.cookie import (COOKIE_ENV_VAR, clean_cookie, cookie_info, get_cookie, load_env_file,
                               looks_like_cookie, save_env_value)
from roliposter.inventory import Inventory, fetch_inventory, missing_offer_items
from roliposter.items import ItemCatalog
from roliposter.logsetup import REDACTOR, setup_logging
from roliposter.paths import cache_dir, config_path, env_path, log_dir, resource_path, state_path
from roliposter.poster import AuthError, Poster, fmt_duration
from roliposter.startup import StartupError, fetch_catalog_with_retry, prepare
from roliposter.state import PostHistory
from roliposter.thumbs import ThumbnailCache
from roliposter.tray import Tray
from roliposter.updates import check_for_update
from roliposter.values import evaluate_ad

log = logging.getLogger("roliposter.gui")

APP_NAME = "Rolimons Ad Poster"
REPO_URL = "https://github.com/rxst0/rolimons-ad-poster"
C = theme.COLORS
THUMB_PX = 24
INVENTORY_REFRESH_MS = 10 * 60 * 1000
COOKIE_WARN_DAYS = 3

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
   Ads offering items you no longer own are skipped automatically.

3. Start
   Click "Start posting". One ad is posted roughly every 15 minutes
   (Rolimons' cooldown) plus a small random delay, cycling through your ads.
   "Skip" jumps to the following ad. Click "Stop" any time.

RUNNING IN THE BACKGROUND
- While posting, closing the window keeps the app running in the system
  tray (bottom-right, near the clock). Right-click the tray icon to open,
  stop, skip or quit.
- Settings > App: start with Windows, start posting automatically,
  notifications and update checks.
- Settings > Schedule: only post during certain hours.

SAFETY
- This app only posts Rolimons trade ads. It never sends Roblox trades and
  never asks for your .ROBLOSECURITY cookie. Anyone who asks for that is
  trying to steal your account.
- Your cookie is saved in a ".env" file next to the app. Don't share that file.

FILES (next to the app)
  config.json  your ads and settings
  .env         your Rolimons cookie
  state.json   post times and history
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


def scrolled_tree(parent: tk.Misc, columns: tuple[str, ...], height: int,
                  show: str = "headings") -> tuple[ttk.Frame, ttk.Treeview]:
    wrap = ttk.Frame(parent)
    wrap.columnconfigure(0, weight=1)
    wrap.rowconfigure(0, weight=1)
    tree = ttk.Treeview(wrap, columns=columns, show=show, height=height, selectmode="browse")
    bar = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    tree.grid(row=0, column=0, sticky="nsew")
    bar.grid(row=0, column=1, sticky="ns")
    tree.tag_configure("odd", background=theme.STRIPE)
    tree.tag_configure("off", foreground=theme.MUTED)
    tree.tag_configure("warn", foreground=theme.WARN)
    tree.tag_configure("ok", foreground=theme.OK)
    tree.tag_configure("bad", foreground=theme.BAD)
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
        self._search_job = None
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
        self.var_search.trace_add("write", lambda *_: self._schedule_search())
        wrap, self.results = scrolled_tree(sf, ("value",), 10, show="tree headings")
        self._setup_item_columns(self.results)
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
        self.owned_hint = ttk.Label(of, text="", style="Warn.TLabel", wraplength=280, justify="left")
        self.owned_hint.grid(row=4, column=0, sticky="w", pady=(10, 0))

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

        app.thumb_listeners.append(self._on_thumbs)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._refresh_lists()
        app.request_thumbs(self.ad.all_item_ids())
        if not app.catalog:
            self.search_hint.config(text="Item list still loading... you can type an item ID.")
        self.show()
        search.focus_set()

    def _on_destroy(self, event) -> None:
        if event.widget is self and self._on_thumbs in self.app.thumb_listeners:
            self.app.thumb_listeners.remove(self._on_thumbs)

    @staticmethod
    def _setup_item_columns(tree: ttk.Treeview) -> None:
        tree.heading("#0", text="ITEM", anchor="w")
        tree.heading("value", text="VALUE", anchor="e")
        tree.column("#0", width=180)
        tree.column("value", width=90, anchor="e", stretch=False)

    def _item_list(self, parent) -> ttk.Treeview:
        tree = ttk.Treeview(parent, columns=("value",), show="tree headings", height=4, selectmode="browse")
        self._setup_item_columns(tree)
        tree.tag_configure("odd", background=theme.STRIPE)
        tree.tag_configure("warn", foreground=theme.WARN)
        return tree

    def _insert_item(self, tree: ttk.Treeview, item_id: int, index: int, iid: str | None = None,
                     warn: bool = False) -> None:
        catalog = self.app.catalog
        item = catalog.get(item_id) if catalog else None
        text = item.label if item else f"Item {item_id}"
        value = f"{item.default_value:,}" if item else ("not found" if catalog else "?")
        tags = (("odd",) if index % 2 else ()) + (("warn",) if warn else ())
        image = self.app.thumb(item_id) or self.app.blank_thumb
        tree.insert("", "end", iid=iid, text=f"  {text}", values=(value,), tags=tags, image=image)

    def _on_thumbs(self) -> None:
        self._refresh_lists()
        self._search()

    def _schedule_search(self) -> None:
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(250, self._search)

    def _search(self) -> None:
        self._search_job = None
        selected = self.results.selection()
        self.results.delete(*self.results.get_children())
        q = self.var_search.get().strip().lower()
        if not q:
            return
        catalog = self.app.catalog
        ids = []
        if catalog:
            matches = []
            for item in catalog.items.values():
                if q == str(item.id) or q in item.name.lower() or q == item.acronym.lower():
                    rank = 0 if q in (item.acronym.lower(), str(item.id)) else 1 if item.name.lower().startswith(q) else 2
                    matches.append((rank, -item.default_value, item))
            matches.sort(key=lambda m: (m[0], m[1]))
            ids = [item.id for _, _, item in matches[:60]]
        elif q.isdigit():
            ids = [int(q)]
        for n, item_id in enumerate(ids):
            self._insert_item(self.results, item_id, n, iid=str(item_id))
        if selected and self.results.exists(selected[0]):
            self.results.selection_set(selected[0])
        self.app.request_thumbs(ids)

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
        missing = set(missing_offer_items(self.ad, self.app.inventory))
        for tree, ids, check in ((self.offer_tree, self.ad.offer_item_ids, True),
                                 (self.request_tree, self.ad.request_item_ids, False)):
            tree.delete(*tree.get_children())
            for n, item_id in enumerate(ids):
                self._insert_item(tree, item_id, n, warn=check and item_id in missing)
        self.owned_hint.config(text="⚠ Highlighted items aren't in your Rolimons inventory, so this ad "
                                    "will be skipped." if missing else "")
        if self.app.catalog:
            av = evaluate_ad(self.ad, self.app.catalog)
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
        cols = ttk.Frame(self.body)
        cols.pack(fill="both", expand=True)
        left, right = ttk.Frame(cols), ttk.Frame(cols)
        left.pack(side="left", fill="both", expand=True, anchor="n")
        ttk.Separator(cols, orient="vertical").pack(side="left", fill="y", padx=22)
        right.pack(side="left", fill="both", expand=True, anchor="n")
        rows = {left: 0, right: 0}

        def section(col, text):
            if rows[col]:
                ttk.Frame(col, height=14).grid(row=rows[col], column=0)
                rows[col] += 1
            ttk.Label(col, text=text, style="Title.TLabel").grid(row=rows[col], column=0, columnspan=2, sticky="w", pady=(0, 8))
            rows[col] += 1

        def field(col, label, widget):
            ttk.Label(col, text=label).grid(row=rows[col], column=0, sticky="w", pady=5, padx=(0, 18))
            widget.grid(row=rows[col], column=1, sticky="w", pady=5)
            rows[col] += 1

        def check(col, text, value):
            var = tk.BooleanVar(value=value)
            ttk.Checkbutton(col, text=text, variable=var).grid(row=rows[col], column=0, columnspan=2, sticky="w", pady=2)
            rows[col] += 1
            return var

        # Left column: posting behaviour
        section(left, "Posting")
        self.var_rotation = tk.StringVar(value=c.rotation)
        rot = ttk.Frame(left)
        ttk.Radiobutton(rot, text="In order", value="sequential", variable=self.var_rotation).pack(side="left")
        ttk.Radiobutton(rot, text="Random", value="random", variable=self.var_rotation).pack(side="left", padx=16)
        field(left, "Ad order", rot)
        self.var_jmin = tk.StringVar(value=f"{c.jitter_seconds[0]:g}")
        self.var_jmax = tk.StringVar(value=f"{c.jitter_seconds[1]:g}")
        jit = ttk.Frame(left)
        ttk.Spinbox(jit, from_=0, to=1800, textvariable=self.var_jmin, width=5).pack(side="left")
        ttk.Label(jit, text="  to  ").pack(side="left")
        ttk.Spinbox(jit, from_=0, to=1800, textvariable=self.var_jmax, width=5).pack(side="left")
        ttk.Label(jit, text="  sec", style="Muted.TLabel").pack(side="left")
        field(left, "Extra random delay", jit)
        self.var_max = tk.StringVar(value=str(c.max_ads_per_24h))
        field(left, "Max ads per 24 hours", ttk.Spinbox(left, from_=1, to=96, textvariable=self.var_max, width=5))
        self.var_unowned = check(left, "Skip ads offering items I don't own", c.skip_unowned_items)

        section(left, "Schedule")
        ph = c.posting_hours
        self.var_hours = check(left, "Only post during these hours", ph.enabled)
        hrs = ttk.Frame(left)
        self.var_hstart, self.var_hend = tk.StringVar(value=ph.start), tk.StringVar(value=ph.end)
        ttk.Entry(hrs, textvariable=self.var_hstart, width=6).pack(side="left")
        ttk.Label(hrs, text="  to  ").pack(side="left")
        ttk.Entry(hrs, textvariable=self.var_hend, width=6).pack(side="left")
        ttk.Label(hrs, text="  24-hour, e.g. 09:00", style="Muted.TLabel").pack(side="left")
        field(left, "Between", hrs)

        section(left, "Value checks")
        vm = c.value_mode
        self.var_value = check(left, "Warn me when an ad overpays", vm.enabled)
        self.var_overpay = tk.StringVar(value=f"{vm.overpay_warn_percent:g}")
        op = ttk.Frame(left)
        ttk.Spinbox(op, from_=0, to=1000, textvariable=self.var_overpay, width=5).pack(side="left")
        ttk.Label(op, text="  % more than it asks for", style="Muted.TLabel").pack(side="left")
        field(left, "Overpay threshold", op)
        self.var_skip = check(left, "Don't post ads that overpay", vm.skip_overpaying_ads)
        self.var_pick = check(left, "Smart pick: post high-demand ads more often", vm.strategy == "pick")

        # Right column: app behaviour
        section(right, "App")
        a = c.app
        self.var_tray = check(right, "Keep posting in the tray when I close the window", a.close_to_tray)
        self.var_boot = check(right, "Start with Windows", autostart.is_enabled())
        self.var_auto = check(right, "Start posting automatically when the app opens", a.auto_start_posting)
        self.var_notify = check(right, "Show notifications", a.notifications)
        self.var_updates = check(right, "Check for updates", a.check_updates)
        ttk.Label(right, style="Muted.TLabel", justify="left", wraplength=300, text=(
            "Tip: turn on \"Start with Windows\" and \"Start posting automatically\" to keep "
            "ads going without opening the app.")).grid(row=rows[right], column=0, columnspan=2, sticky="w", pady=(10, 0))

        ttk.Separator(self.body).pack(fill="x", pady=16)
        self.footer(self.body, "Save", self._save).pack(fill="x")
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
        c = copy.deepcopy(self.app.cfg)
        c.rotation = self.var_rotation.get()
        c.jitter_seconds = [jmin, jmax]
        c.max_ads_per_24h = max_ads
        c.skip_unowned_items = self.var_unowned.get()
        c.posting_hours.enabled = self.var_hours.get()
        c.posting_hours.start = self.var_hstart.get().strip()
        c.posting_hours.end = self.var_hend.get().strip()
        c.value_mode.enabled = self.var_value.get() or self.var_skip.get() or self.var_pick.get()
        c.value_mode.overpay_warn_percent = overpay
        c.value_mode.skip_overpaying_ads = self.var_skip.get()
        c.value_mode.strategy = "pick" if self.var_pick.get() else "warn"
        c.app.close_to_tray = self.var_tray.get()
        c.app.auto_start_posting = self.var_auto.get()
        c.app.notifications = self.var_notify.get()
        c.app.check_updates = self.var_updates.get()
        hour_errors = [e for e in validate_config(c) if "posting_hours" in e]
        if hour_errors:
            messagebox.showwarning("Settings", "\n".join(hour_errors), parent=self)
            return
        try:
            if self.var_boot.get() != autostart.is_enabled():
                autostart.set_enabled(self.var_boot.get())
        except OSError as e:
            messagebox.showwarning("Settings", f"Couldn't change \"Start with Windows\": {e}", parent=self)
            return
        self.app.cfg = c
        self.app.persist()
        self.destroy()


class HistoryDialog(Dialog):
    RESULT_TAGS = {"SUCCESS": "ok", "COOLDOWN": "warn", "RATE_LIMITED": "warn", "AUTH_ERROR": "bad",
                   "REJECTED": "bad", "NETWORK_ERROR": "warn", "SERVER_ERROR": "warn"}

    def __init__(self, app: "App"):
        super().__init__(app, "Post history")
        self.minsize(820, 460)
        b = self.body
        attempts = list(reversed(PostHistory(state_path()).attempts))
        posted = sum(1 for a in attempts if a["result"] == "SUCCESS")
        head = ttk.Frame(b)
        head.pack(fill="x", pady=(0, 10))
        ttk.Label(head, text="Post history", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text=f"{len(attempts)} attempts  ·  {posted} posted", style="Muted.TLabel").pack(
            side="left", padx=(10, 0), pady=(3, 0))
        wrap, tree = scrolled_tree(b, ("when", "ad", "result", "message"), 14)
        for col, text, width in (("when", "WHEN", 150), ("ad", "AD", 190), ("result", "RESULT", 120),
                                 ("message", "DETAILS", 320)):
            tree.heading(col, text=text, anchor="w")
            tree.column(col, width=width, stretch=col == "message")
        for n, a in enumerate(attempts):
            when = time.strftime("%d %b  %H:%M:%S", time.localtime(a["t"]))
            result = a["result"].replace("_", " ").title()
            tags = (("odd",) if n % 2 else ()) + (self.RESULT_TAGS.get(a["result"], ""),)
            tree.insert("", "end", values=(when, a["ad"], result, a.get("message", "")), tags=tags)
        wrap.pack(fill="both", expand=True)
        if not attempts:
            ttk.Label(wrap, text="Nothing posted yet.", style="Muted.TLabel", background=theme.FIELD).place(
                relx=0.5, rely=0.5, anchor="center")
        foot = self.footer(b, "Close", self.destroy, cancel=False)
        foot.pack(fill="x", pady=(16, 0))
        self.show()


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
    def __init__(self, start_minimized: bool = False):
        super().__init__()
        self.withdraw()
        self.title(APP_NAME)
        set_app_icon(self)
        theme.apply_theme(self)
        self.geometry("960x800")
        self.minsize(840, 680)

        self.log_queue: queue.Queue = queue.Queue()
        self.events: queue.Queue = queue.Queue()
        setup_logging(log_dir(), (QueueLogHandler(self.log_queue),))
        load_env_file(env_path())

        self.cfg_path = config_path()
        self.cfg = self._load_cfg()
        self.catalog: ItemCatalog | None = None
        self.inventory: Inventory | None = None
        self.poster: Poster | None = None
        self.worker: threading.Thread | None = None
        self.stop_event: threading.Event | None = None
        self.history = PostHistory(state_path())
        self.thumbs = ThumbnailCache(cache_dir() / "thumbs")
        self.thumb_listeners: list = []
        self._thumb_images: dict[int, tk.PhotoImage] = {}
        self.blank_thumb = tk.PhotoImage(master=self, width=THUMB_PX, height=THUMB_PX)  # keeps rows aligned
        self._thumb_pending: set[int] = set()
        self._notified: set[str] = set()
        self._user_stopped = False
        self._hidden_hint_shown = False

        self._build()
        self.refresh_ads()
        self.update_cookie_status()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.tray = Tray(APP_NAME, resource_path("assets/icon.png"),
                         lambda action: self.events.put(("tray", action)), self._is_running)
        self.tray.start()
        threading.Thread(target=self._load_catalog, daemon=True).start()
        if self.cfg.app.check_updates:
            threading.Thread(target=self._check_updates, daemon=True).start()
        self.after(100, self._poll)
        self.after(500, self._tick)
        self.after(3000, self._check_cookie_expiry)
        theme.dark_title_bar(self)
        if not (start_minimized and self.tray.available):
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

    def _is_running(self) -> bool:
        return bool(self.worker and self.worker.is_alive())

    def notify(self, key: str | None, title: str, message: str) -> None:
        """Windows notification (once per key per session when a key is given)."""
        tray = getattr(self, "tray", None)
        if tray is None or not self.cfg.app.notifications or (key and key in self._notified):
            return
        if key:
            self._notified.add(key)
        tray.notify(title, message)

    # ---- layout --------------------------------------------------------
    def _build(self) -> None:
        root = ttk.Frame(self, style="App.TFrame", padding=(22, 18, 22, 20))
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=3)
        root.rowconfigure(5, weight=2)

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
        ttk.Button(head, text="History", style="Ghost.TButton", command=lambda: HistoryDialog(self)).pack(side="right", padx=(0, 4))

        # Update banner (hidden until an update is found)
        self.banner = ttk.Frame(root, style="Banner.TFrame", padding=(18, 10))
        self.banner_text = ttk.Label(self.banner, text="", style="Banner.TLabel")
        self.banner_text.pack(side="left")
        ttk.Label(self.banner, text="Your ads and cookie are kept when you update.",
                  style="BannerMuted.TLabel").pack(side="left", padx=(12, 0))
        ttk.Button(self.banner, text="Dismiss", command=self.banner.grid_remove).pack(side="right")
        self.banner_btn = ttk.Button(self.banner, text="Download", style="Accent.TButton")
        self.banner_btn.pack(side="right", padx=(0, 8))

        # Account
        acc = card(root, "Account")
        acc.grid(row=2, column=0, sticky="ew")
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
        ads.grid(row=3, column=0, sticky="nsew", pady=14)
        self.ads_count = ttk.Label(ads.head, text="", style="Muted.TLabel")
        self.ads_count.pack(side="left", padx=(10, 0), pady=(3, 0))
        ttk.Button(ads.head, text="+  New ad", style="Accent.TButton", command=self._new_ad).pack(side="right")
        wrap, self.tree = scrolled_tree(ads, ("name", "on", "offer", "want"), 6)
        self.tree.heading("name", text="AD", anchor="w")
        self.tree.heading("on", text="STATUS", anchor="w")
        self.tree.heading("offer", text="OFFERING", anchor="w")
        self.tree.heading("want", text="WANTS", anchor="w")
        self.tree.column("name", width=200)
        self.tree.column("on", width=130, stretch=False)
        self.tree.column("offer", width=230)
        self.tree.column("want", width=230)
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
        run.grid(row=4, column=0, sticky="ew")
        info = ttk.Frame(run)
        info.pack(side="left", fill="x", expand=True)
        self.status = ttk.Label(info, text="Stopped", style="Status.TLabel")
        self.status.pack(anchor="w")
        self.substatus = ttk.Label(info, text="", style="Muted.TLabel")
        self.substatus.pack(anchor="w", pady=(2, 0))
        self.btn_run = ttk.Button(run, text="Start posting", style="Big.Accent.TButton", command=self._toggle_run)
        self.btn_run.pack(side="right")
        self.btn_skip = ttk.Button(run, text="Skip", style="Big.TButton", command=self._skip)

        # Activity
        logf = card(root, "Activity")
        logf.grid(row=5, column=0, sticky="nsew", pady=(14, 0))
        ttk.Button(logf.head, text="Clear", command=self._clear_log).pack(side="right")
        box = ttk.Frame(logf)
        box.pack(fill="both", expand=True)
        self.logbox = tk.Text(box, height=6, state="disabled", font=theme.FONT_MONO, wrap="word", padx=10, pady=8,
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
            self.inventory = None
            self.persist()
            self._refresh_inventory()
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
            soon = info.expires_at - time.time() < COOKIE_WARN_DAYS * 86400
            text = f"{'⚠' if soon else '✓'}  {who}expires {time.strftime('%d %b %Y', time.localtime(info.expires_at))}"
            color = "warn" if soon else "ok"
        else:
            text, color = "✓  Saved", "ok"
        self.cookie_status.config(text=text, foreground=C[color])
        self._update_user_status()

    def _check_cookie_expiry(self) -> None:
        try:
            cookie = get_cookie()
        except ValueError:
            cookie = None
        info = cookie_info(cookie) if cookie else None
        if info and info.expires_at and not info.expired:
            days = (info.expires_at - time.time()) / 86400
            if days < COOKIE_WARN_DAYS:
                self.notify("cookie-expiry", "Rolimons cookie expiring soon",
                            f"Your cookie expires in {max(1, round(days * 24))} hours. Set a fresh one to keep posting.")
        self.update_cookie_status()
        self.after(6 * 3600 * 1000, self._check_cookie_expiry)

    def use_cookie_user_id(self, player_id: int) -> None:
        """The cookie says which Roblox account it verifies; use that ID so the two can't disagree."""
        if self.cfg.roblox_user_id != player_id:
            if self.cfg.roblox_user_id:
                log.info("Roblox user ID changed from %d to %d to match your cookie.",
                         self.cfg.roblox_user_id, player_id)
            self.cfg.roblox_user_id = player_id
            self.inventory = None
            self.persist()
            self._refresh_inventory()
        self.var_user.set(str(player_id))
        self._update_user_status()

    # ---- items: inventory + thumbnails --------------------------------
    def _refresh_inventory(self) -> None:
        uid = self.cfg.roblox_user_id
        if uid <= 0:
            return

        def work():
            try:
                self.events.put(("inventory", (uid, fetch_inventory(requests.Session(), uid))))
            except (requests.RequestException, ValueError) as e:
                log.warning("Couldn't load your inventory from Rolimons (%s).", type(e).__name__)
        threading.Thread(target=work, daemon=True).start()

    def _inventory_loop(self) -> None:
        if not self._is_running():
            self._refresh_inventory()
        self.after(INVENTORY_REFRESH_MS, self._inventory_loop)

    def thumb(self, item_id: int) -> tk.PhotoImage | None:
        image = self._thumb_images.get(item_id)
        if image is None and self.thumbs.cached(item_id):
            try:
                from PIL import Image, ImageTk
                with Image.open(self.thumbs.path(item_id)) as img:
                    image = ImageTk.PhotoImage(img.convert("RGBA").resize((THUMB_PX, THUMB_PX), Image.LANCZOS),
                                               master=self)
                self._thumb_images[item_id] = image
            except Exception:
                return None
        return image

    def request_thumbs(self, item_ids: list[int]) -> None:
        wanted = [i for i in item_ids if not self.thumbs.cached(i) and i not in self._thumb_pending]
        if not wanted:
            return
        self._thumb_pending.update(wanted)

        def work():
            try:
                self.thumbs.fetch(requests.Session(), wanted)
            except (requests.RequestException, OSError, ValueError) as e:
                log.debug("Thumbnail download failed: %s", e)
            finally:
                self.events.put(("thumbs", wanted))
        threading.Thread(target=work, daemon=True).start()

    # ---- ads -----------------------------------------------------------
    def _unavailable(self) -> dict[str, list[int]]:
        if self.poster is not None:
            return self.poster.unavailable
        if not self.cfg.skip_unowned_items:
            return {}
        return {a.name: m for a in self.cfg.ads if (m := missing_offer_items(a, self.inventory))}

    def refresh_ads(self) -> None:
        selected = self._selected_index()
        unavailable = self._unavailable()
        self.tree.delete(*self.tree.get_children())
        for i, ad in enumerate(self.cfg.ads):
            offer = ", ".join(short_name(self.catalog, x) for x in ad.offer_item_ids)
            want = ", ".join([short_name(self.catalog, x) for x in ad.request_item_ids] + ad.request_tags)
            tags = ("odd",) if i % 2 else ()
            if not ad.enabled:
                status, tags = "○ Off", tags + ("off",)
            elif ad.name in unavailable:
                status, tags = "⚠ Item not owned", tags + ("warn",)
            else:
                status = "● On"
            self.tree.insert("", "end", iid=str(i), values=(ad.name, status, offer, want), tags=tags)
        on = len(self.cfg.enabled_ads())
        self.ads_count.config(text=f"{len(self.cfg.ads)} total  ·  {on} on" if self.cfg.ads else "")
        if self.cfg.ads:
            self.empty_hint.place_forget()
            if selected is not None:
                self._select(min(selected, len(self.cfg.ads) - 1))
        else:
            self.empty_hint.place(relx=0.5, rely=0.55, anchor="center")
        for name in unavailable:
            self.notify(f"unowned:{name}", "Ad skipped", f"'{name}' offers an item you no longer own, so it's being skipped.")

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
    def _can_start(self, quiet: bool = False) -> bool:
        self._save_user_id()
        try:
            has_cookie = bool(get_cookie())
        except ValueError:
            has_cookie = False
        problems = [] if has_cookie else ["Set your Rolimons cookie first (click \"Set cookie\")."]
        problems += validate_config(self.cfg)
        if problems and not quiet:
            messagebox.showwarning(APP_NAME, "Fix these first:\n\n• " + "\n• ".join(problems))
        elif problems:
            log.warning("Not starting automatically: %s", " ".join(problems))
        return not problems

    def _start(self, quiet: bool = False) -> None:
        if self._is_running() or not self._can_start(quiet):
            return
        self._user_stopped = False
        self.stop_event = threading.Event()
        self.worker = threading.Thread(target=self._run_worker, args=(self.stop_event,), daemon=True)
        self.worker.start()
        self._set_running(True)

    def _stop(self) -> None:
        if self._is_running() and self.stop_event:
            self._user_stopped = True
            self.stop_event.set()
            self.btn_run.config(state="disabled")
            self.status.config(text="Stopping...", foreground=C["text"])

    def _toggle_run(self) -> None:
        if self._is_running():
            self._stop()
        else:
            self._start()

    def _skip(self) -> None:
        if self.poster is not None:
            self.poster.skip_next()

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
            if self.poster is not None:
                self.inventory = self.poster.inventory or self.inventory
            self.poster = None
            self.events.put(("stopped", None))

    def _set_running(self, running: bool) -> None:
        self.btn_run.config(text="Stop" if running else "Start posting", state="normal",
                            style="Big.TButton" if running else "Big.Accent.TButton")
        if running:
            self.btn_skip.pack(side="right", padx=(0, 10))
        else:
            self.btn_skip.pack_forget()
        self.status.config(text="Starting..." if running else "Stopped", foreground=C["text"])
        self.tray.refresh()

    def _tick(self) -> None:
        poster = self.poster
        count = f"{self.history.count_24h()} of {self.cfg.max_ads_per_24h} posted in the last 24h"
        tooltip = APP_NAME
        if poster:
            nxt = f"Next: {poster.next_ad.name}  ·  " if poster.next_ad else ""
            if poster.wait_until:
                remaining = fmt_duration(max(0, poster.wait_until - time.time()))
                self.status.config(text=f"Next ad in {remaining}", foreground=C["accent"])
                self.substatus.config(text=f"{nxt}{poster.status_text.capitalize()}  ·  {count}")
                tooltip = f"{APP_NAME} — next ad in {remaining}"
            else:
                self.status.config(text=poster.status_text, foreground=C["accent"])
                self.substatus.config(text=f"{nxt}{count}")
                tooltip = f"{APP_NAME} — {poster.status_text}"
            self.btn_skip.config(state="normal" if poster.next_ad else "disabled")
            if poster.unavailable.keys() != getattr(self, "_shown_unavailable", {}).keys():
                self._shown_unavailable = dict(poster.unavailable)
                self.refresh_ads()
        elif self._is_running():
            self.status.config(text="Checking setup...", foreground=C["text"])
        else:
            self.substatus.config(text=f"Ready when you are  ·  {count}")
        self.tray.set_tooltip(tooltip)
        self.after(500, self._tick)

    # ---- background events --------------------------------------------
    def _load_catalog(self) -> None:
        try:
            self.events.put(("catalog", fetch_catalog_with_retry(requests.Session())))
        except StartupError as e:
            log.warning("%s", e)
            self.events.put(("catalog", None))

    def _check_updates(self) -> None:
        try:
            found = check_for_update(requests.Session())
        except (requests.RequestException, ValueError):
            return
        if found:
            self.events.put(("update", found))

    def _show_update(self, version: str, url: str) -> None:
        self.banner_text.config(text=f"Version {version} is available")
        self.banner_btn.config(command=lambda: webbrowser.open(url or REPO_URL + "/releases/latest"))
        self.banner.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        log.info("Update available: v%s (you have v%s).", version, __version__)
        self.notify("update", "Update available", f"Rolimons Ad Poster {version} is available on GitHub.")

    def _clear_log(self) -> None:
        self.logbox.config(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.config(state="disabled")

    def _handle_tray(self, action: str) -> None:
        if action == "show":
            self.deiconify()
            self.lift()
            self.focus_force()
        elif action == "toggle":
            self._toggle_run()
        elif action == "skip":
            self._skip()
        elif action == "quit":
            self._quit()

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
                if not self._user_stopped:
                    self.notify(None, "Posting stopped", "Rolimons Ad Poster stopped posting. Open it to see why.")
                self.refresh_ads()
            elif kind == "error":
                self.notify(None, "Rolimons Ad Poster", payload.split("\n")[0])
                messagebox.showerror(APP_NAME, payload)
            elif kind == "catalog":
                first = self.catalog is None
                if payload is not None:
                    self.catalog = payload
                    self.refresh_ads()
                if first:
                    self._inventory_loop()
                    if self.cfg.app.auto_start_posting:
                        log.info("Starting automatically (Settings > App).")
                        self._start(quiet=True)
            elif kind == "inventory":
                uid, inventory = payload
                if uid == self.cfg.roblox_user_id:
                    self.inventory = inventory
                    self.refresh_ads()
                    for listener in list(self.thumb_listeners):
                        listener()
            elif kind == "thumbs":
                self._thumb_pending.difference_update(payload)
                for listener in list(self.thumb_listeners):
                    listener()
            elif kind == "update":
                self._show_update(*payload)
            elif kind == "tray":
                self._handle_tray(payload)
        self.after(100, self._poll)

    def _on_close(self) -> None:
        if self._is_running() and self.cfg.app.close_to_tray and self.tray.available:
            self.withdraw()
            if not self._hidden_hint_shown:
                self._hidden_hint_shown = True
                self.tray.notify(APP_NAME, "Still posting in the background. Right-click the tray icon to quit.")
            return
        if self._is_running() and not messagebox.askyesno(APP_NAME, "Posting is running. Stop and quit?"):
            return
        self._quit()

    def _quit(self) -> None:
        if self._is_running() and self.stop_event:
            self._user_stopped = True
            self.stop_event.set()
            self.worker.join(timeout=3)
        self.tray.stop()
        self.destroy()


if __name__ == "__main__":
    App(start_minimized="--minimized" in sys.argv[1:]).mainloop()
