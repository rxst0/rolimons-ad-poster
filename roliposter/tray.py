"""System tray icon + Windows notifications (pystray). Menu clicks are forwarded to a callback."""
import logging
from pathlib import Path
from typing import Callable

log = logging.getLogger("roliposter.tray")


class Tray:
    """on_action receives "show", "toggle", "skip" or "quit" (called on the tray thread)."""

    def __init__(self, title: str, icon_path: Path, on_action: Callable[[str], None],
                 is_running: Callable[[], bool]):
        self.title = title
        self.icon_path = icon_path
        self.on_action = on_action
        self.is_running = is_running
        self._icon = None

    @property
    def available(self) -> bool:
        return self._icon is not None

    def start(self) -> bool:
        try:
            import pystray
            from PIL import Image
        except ImportError:
            log.warning("Tray icon unavailable (pystray/Pillow not installed).")
            return False
        item = pystray.MenuItem
        menu = pystray.Menu(
            item("Open", lambda: self.on_action("show"), default=True),
            item(lambda _i: "Stop posting" if self.is_running() else "Start posting",
                 lambda: self.on_action("toggle")),
            item("Skip to next ad", lambda: self.on_action("skip"), visible=lambda _i: self.is_running()),
            pystray.Menu.SEPARATOR,
            item("Quit", lambda: self.on_action("quit")),
        )
        try:
            self._icon = pystray.Icon("RolimonsAdPoster", Image.open(self.icon_path), self.title, menu)
            self._icon.run_detached()
            return True
        except Exception as e:  # tray support depends on the desktop shell
            log.warning("Tray icon unavailable (%s).", e)
            self._icon = None
            return False

    def refresh(self) -> None:
        if self._icon:
            self._icon.update_menu()

    def set_tooltip(self, text: str) -> None:
        if self._icon:
            self._icon.title = text[:120]

    def notify(self, title: str, message: str) -> None:
        if self._icon:
            try:
                self._icon.notify(message, title)
            except Exception as e:
                log.debug("Notification failed: %s", e)

    def stop(self) -> None:
        if self._icon:
            self._icon.stop()
            self._icon = None
