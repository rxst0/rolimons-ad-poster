"""Flat dark-grey + blue ttk theme (built on 'clam') for the desktop app."""
import tkinter as tk
from tkinter import ttk

BG = "#15181d"          # window background
SURFACE = "#1d2127"     # cards and dialogs
RAISED = "#262b33"      # buttons, headings
FIELD = "#22272e"       # inputs, tables
STRIPE = "#262b33"      # alternate table rows
BORDER = "#323843"
HOVER = "#2e3540"
TEXT = "#e6e9ee"
MUTED = "#8b94a3"
ACCENT = "#3b82f6"
ACCENT_HOVER = "#5592f7"
ACCENT_PRESSED = "#2563eb"
SELECT = "#2a5bd7"
BANNER = "#1e3a8a"
OK = "#4ade80"
WARN = "#fbbf24"
BAD = "#f87171"

FONT = ("Segoe UI", 10)
FONT_SEMIBOLD = ("Segoe UI", 10, "bold")
FONT_SMALL = ("Segoe UI", 9)
FONT_TITLE = ("Segoe UI", 12, "bold")
FONT_HEADER = ("Segoe UI", 17, "bold")
FONT_STATUS = ("Segoe UI", 16, "bold")
FONT_MONO = ("Consolas", 9)

COLORS = {"ok": OK, "warn": WARN, "bad": BAD, "muted": MUTED, "accent": ACCENT, "text": TEXT}


def _flat(style: ttk.Style, name: str, color: str, **extra) -> None:
    """Paints a widget's 3D border pieces one color so it renders flat."""
    style.configure(name, background=color, bordercolor=color, lightcolor=color, darkcolor=color, **extra)


def apply_theme(root: tk.Tk) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(bg=BG)
    root.option_add("*TCombobox*Listbox.background", FIELD)

    style.configure(".", background=SURFACE, foreground=TEXT, fieldbackground=FIELD, bordercolor=BORDER,
                    lightcolor=SURFACE, darkcolor=SURFACE, troughcolor=SURFACE, focuscolor=ACCENT,
                    selectbackground=SELECT, selectforeground="#ffffff", insertcolor=TEXT,
                    arrowcolor=MUTED, font=FONT)

    # Containers and text
    style.configure("TFrame", background=SURFACE)
    style.configure("App.TFrame", background=BG)
    style.configure("Card.TFrame", background=SURFACE, bordercolor=BORDER, lightcolor=BORDER,
                    darkcolor=BORDER, relief="solid", borderwidth=1)
    style.configure("TLabel", background=SURFACE, foreground=TEXT)
    style.configure("Muted.TLabel", foreground=MUTED, font=FONT_SMALL)
    style.configure("Field.TLabel", foreground=MUTED, font=FONT_SMALL)
    style.configure("Title.TLabel", font=FONT_TITLE)
    style.configure("Status.TLabel", font=FONT_STATUS)
    style.configure("App.TLabel", background=BG)
    style.configure("AppTitle.TLabel", background=BG, font=FONT_HEADER)
    style.configure("AppMuted.TLabel", background=BG, foreground=MUTED, font=FONT_SMALL)
    style.configure("TSeparator", background=BORDER)
    style.configure("Warn.TLabel", foreground=WARN, font=FONT_SMALL)
    style.configure("Banner.TFrame", background=BANNER)
    style.configure("Banner.TLabel", background=BANNER, foreground="#ffffff", font=FONT_SEMIBOLD)
    style.configure("BannerMuted.TLabel", background=BANNER, foreground="#c7d7fe", font=FONT_SMALL)

    # Buttons
    _flat(style, "TButton", RAISED, foreground=TEXT, padding=(14, 7), relief="flat", focusthickness=0)
    style.map("TButton",
              background=[("disabled", SURFACE), ("pressed", BORDER), ("active", HOVER)],
              bordercolor=[("disabled", SURFACE), ("pressed", BORDER), ("active", HOVER)],
              lightcolor=[("disabled", SURFACE), ("pressed", BORDER), ("active", HOVER)],
              darkcolor=[("disabled", SURFACE), ("pressed", BORDER), ("active", HOVER)],
              foreground=[("disabled", MUTED)])
    _flat(style, "Accent.TButton", ACCENT, foreground="#ffffff", font=FONT_SEMIBOLD)
    accent_states = [("disabled", RAISED), ("pressed", ACCENT_PRESSED), ("active", ACCENT_HOVER)]
    style.map("Accent.TButton", background=accent_states, bordercolor=accent_states,
              lightcolor=accent_states, darkcolor=accent_states, foreground=[("disabled", MUTED)])
    style.configure("Big.Accent.TButton", padding=(30, 12), font=("Segoe UI", 11, "bold"))
    style.configure("Big.TButton", padding=(30, 12), font=("Segoe UI", 11, "bold"))
    _flat(style, "Ghost.TButton", BG, foreground=TEXT, padding=(12, 6))
    ghost_states = [("pressed", BORDER), ("active", RAISED)]
    style.map("Ghost.TButton", background=ghost_states, bordercolor=ghost_states,
              lightcolor=ghost_states, darkcolor=ghost_states)

    # Inputs
    for name in ("TEntry", "TSpinbox"):
        style.configure(name, fieldbackground=FIELD, foreground=TEXT, bordercolor=BORDER,
                        lightcolor=FIELD, darkcolor=FIELD, insertcolor=TEXT, padding=(8, 6))
        style.map(name, bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
                  fieldbackground=[("disabled", SURFACE)])
    style.configure("TSpinbox", background=RAISED, arrowcolor=MUTED, arrowsize=12)
    style.map("TSpinbox", arrowcolor=[("active", TEXT)], background=[("active", HOVER)])

    _indicators(root, style)
    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, background=SURFACE, foreground=TEXT, padding=(0, 3), focusthickness=0)
        style.map(name, background=[("active", SURFACE)], foreground=[("disabled", MUTED)])

    # Tables
    style.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=TEXT, rowheight=30,
                    bordercolor=BORDER, lightcolor=FIELD, darkcolor=FIELD, borderwidth=1, relief="flat")
    style.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", "#ffffff")])
    _flat(style, "Treeview.Heading", RAISED, foreground=MUTED, font=("Segoe UI", 9, "bold"),
          padding=(8, 6), relief="flat")
    style.map("Treeview.Heading", background=[("active", HOVER)], lightcolor=[("active", HOVER)],
              darkcolor=[("active", HOVER)], bordercolor=[("active", HOVER)])

    # Thin arrowless scrollbars
    for orient in ("Vertical", "Horizontal"):
        name = f"{orient}.TScrollbar"
        style.layout(name, [(f"{orient}.Scrollbar.trough", {
            "sticky": "ns" if orient == "Vertical" else "ew",
            "children": [(f"{orient}.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        _flat(style, name, RAISED, troughcolor=FIELD, arrowsize=10, gripcount=0)
        style.map(name, background=[("pressed", MUTED), ("active", HOVER)],
                  lightcolor=[("active", HOVER)], darkcolor=[("active", HOVER)], bordercolor=[("active", HOVER)])


def _seg_dist(px: float, py: float, a: tuple, b: tuple) -> float:
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5


def _paint(root: tk.Misc, size: int, pixel) -> tk.PhotoImage:
    """Builds a small image from pixel(x, y) -> '#rrggbb' or None (transparent).
    The image is 8px wider than tall so the label gets a gap after the indicator."""
    img = tk.PhotoImage(master=root, width=size + 8, height=size)
    clear = []
    rows = []
    for y in range(size):
        row = []
        for x in range(size + 8):
            color = pixel(x + 0.5, y + 0.5) if x < size else None
            row.append(color or SURFACE)
            if color is None:
                clear.append((x, y))
        rows.append("{" + " ".join(row) + "}")
    img.put(" ".join(rows))
    for x, y in clear:
        img.transparency_set(x, y, True)
    return img


def _indicators(root: tk.Misc, style: ttk.Style) -> None:
    """Rounded blue checkboxes with a real checkmark, and matching radio buttons."""
    n = 18
    radius, inner = 4.0, n - 2 * 4.0

    def box(px, py):  # signed distance to the rounded square (negative = inside)
        qx, qy = abs(px - n / 2) - inner / 2, abs(py - n / 2) - inner / 2
        return (max(qx, 0) ** 2 + max(qy, 0) ** 2) ** 0.5 + min(max(qx, qy), 0) - radius

    def checkbox(fill, edge, tick):
        def pixel(px, py):
            d = box(px, py)
            if d > 0:
                return None
            if tick and min(_seg_dist(px, py, (4.5, 9.5), (7.5, 12.5)),
                            _seg_dist(px, py, (7.5, 12.5), (13.5, 5.5))) < 1.2:
                return "#ffffff"
            return edge if d > -1.2 else fill
        return _paint(root, n, pixel)

    def radio(fill, edge, dot):
        def pixel(px, py):
            d = ((px - n / 2) ** 2 + (py - n / 2) ** 2) ** 0.5
            if d > n / 2:
                return None
            if dot and d < 3.6:
                return "#ffffff"
            return edge if d > n / 2 - 1.2 else fill
        return _paint(root, n, pixel)

    imgs = {
        "cb_off": checkbox(FIELD, BORDER, False), "cb_hover": checkbox(FIELD, ACCENT, False),
        "cb_on": checkbox(ACCENT, ACCENT, True), "cb_on_hover": checkbox(ACCENT_HOVER, ACCENT_HOVER, True),
        "rb_off": radio(FIELD, BORDER, False), "rb_hover": radio(FIELD, ACCENT, False),
        "rb_on": radio(ACCENT, ACCENT, True), "rb_on_hover": radio(ACCENT_HOVER, ACCENT_HOVER, True),
    }
    root._theme_images = imgs  # keep references alive
    for kind, prefix in (("Checkbutton", "cb"), ("Radiobutton", "rb")):
        element = f"Flat.{kind}.indicator"
        style.element_create(element, "image", imgs[f"{prefix}_off"],
                             ("selected", "active", imgs[f"{prefix}_on_hover"]),
                             ("selected", imgs[f"{prefix}_on"]),
                             ("active", imgs[f"{prefix}_hover"]))
        style.layout(f"T{kind}", [(f"{kind}.padding", {"sticky": "nswe", "children": [
            (element, {"side": "left", "sticky": ""}),
            (f"{kind}.label", {"side": "left", "sticky": "nswe"})]})])


def text_widget_options() -> dict:
    """Colors for plain tk.Text widgets so they match the theme."""
    return {"bg": FIELD, "fg": TEXT, "insertbackground": TEXT, "selectbackground": SELECT,
            "selectforeground": "#ffffff", "relief": "flat", "highlightthickness": 0, "borderwidth": 0}


def dark_title_bar(window: tk.Misc) -> None:
    """Asks Windows to draw this window's title bar dark (and grey on Windows 11)."""
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))  # immersive dark mode
        r, g, b = int(SURFACE[1:3], 16), int(SURFACE[3:5], 16), int(SURFACE[5:7], 16)
        caption = ctypes.c_int(r | (g << 8) | (b << 16))  # COLORREF is 0x00BBGGRR
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption))  # caption color
    except (ImportError, AttributeError, OSError):
        pass
