"""Shared look for the PC (Tkinter) and Android (Kivy) apps: one palette, one font, one icon.

Pure constants only, so both UI toolkits (and tools/make_icon.py) can import it.
"""
BG = "#15181d"          # window / screen background
SURFACE = "#1d2127"     # cards, dialogs, top bars
RAISED = "#262b33"      # secondary buttons, table headings
FIELD = "#22272e"       # inputs, lists, tables
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
WARN_BG = "#3a2f12"
BAD = "#f87171"

# App icon: blue gradient tile with two white trade arrows.
ICON_GRADIENT_TOP = "#38bdf8"
ICON_GRADIENT_BOTTOM = "#2563eb"

# Typography: Inter (SIL Open Font License, bundled in assets/fonts).
FONT_FAMILY = "Inter"
FONT_FILES = {"regular": "assets/fonts/Inter-Regular.ttf", "bold": "assets/fonts/Inter-Bold.ttf"}
