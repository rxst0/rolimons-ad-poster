"""View-only Roblox trades: the rules for the "Received trades" tab.

The tab shows Roblox's own trades page (roblox.com/trades) in an embedded Microsoft Edge WebView2 browser
(see webview_embed.py). You sign in to Roblox inside it, exactly as in a browser.

Security model:
- This app never reads, copies or stores your Roblox login. The session lives in WebView2's own browser
  profile (cookies encrypted by Windows, like Edge), in the "roblox-session" folder next to the app.
- View only: every request that would change a trade (accept, decline, counter, send, cancel) is
  blocked inside the window before it leaves your PC, and those buttons are hidden. To act on a trade,
  use roblox.com or the Roblox app.

"""
import logging
import shutil
from urllib.parse import urlsplit

from .paths import app_dir, resource_path

TRADES_URL = "https://www.roblox.com/trades"
# Only URLs containing "trade" are checked (keeps every other page request out of Python).
GUARD_FILTER = "*trade*"
READ_METHODS = {"GET", "HEAD", "OPTIONS"}
BLOCK_STATUS = 403
BLOCK_REASON = "Blocked: Rolimons Ad Poster is view-only for trades"

log = logging.getLogger("roliposter.trades")

# Hides trade action buttons and shows a view-only banner. Cosmetic only: the request blocking above is
# what actually makes the window read-only.
VIEW_ONLY_JS = r"""
(() => {
  if (window.__roliViewOnly) return;
  window.__roliViewOnly = true;
  // Roblox's own buttons, plus RoValra's "Decline losing trades" bulk action.
  const ACTIONS = /^(accept|decline|counter|make offer|send|send trade|cancel|confirm|ok, accept|ok, decline|decline losing trades)$/i;
  const hide = () => {
    document.querySelectorAll('button, a.btn, a[role="button"], input[type="button"], input[type="submit"]')
      .forEach(el => {
        const label = (el.innerText || el.value || '').trim();
        if (ACTIONS.test(label)) { el.style.display = 'none'; el.disabled = true; }
      });
  };
  const banner = document.createElement('div');
  banner.textContent = 'View only — accepting, declining and countering are turned off in Rolimons Ad Poster. Use roblox.com to respond to trades.';
  banner.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:2147483647;padding:10px 16px;' +
    'background:#1e3a8a;color:#fff;font:600 13px Inter,Segoe UI,sans-serif;text-align:center;';
  const start = () => {
    document.body.appendChild(banner);
    document.body.style.paddingBottom = '40px';
    hide();
    new MutationObserver(hide).observe(document.body, {childList: true, subtree: true});
  };
  // Injected before the page exists, so wait for the body.
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
})();
"""


def is_roblox_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    return host == "roblox.com" or host.endswith(".roblox.com")


def is_blocked(method: str, url: str) -> bool:
    """True for any request that could change a trade: a non-read request to a Roblox trade endpoint."""
    if method.upper() in READ_METHODS:
        return False
    parts = urlsplit(url)
    return is_roblox_host(parts.hostname or "") and "trade" in parts.path.lower()


def session_dir():
    return app_dir() / "roblox-session"


def forget_login() -> bool:
    """Deletes the viewer's browser profile (signs out of Roblox in the app). Viewer must be closed."""
    folder = session_dir()
    if not folder.exists():
        return False
    shutil.rmtree(folder, ignore_errors=True)
    return not folder.exists()


def view_only_guard(method: str, url: str) -> str | None:
    """Request guard for the embedded browser: a reason to block, or None to allow."""
    return BLOCK_REASON if is_blocked(method, url) else None


def rovalra_dir():
    """The bundled RoValra extension, copied to a fixed folder next to the app (its settings are tied to
    that path), or None if this build doesn't include it. See tools/fetch_rovalra.py."""
    source = resource_path("vendor/rovalra")
    if not (source / "manifest.json").exists():
        return None
    target = app_dir() / "extensions" / "rovalra"
    marker = "BUNDLE_VERSION"
    current = (target / marker).read_text(encoding="utf-8") if (target / marker).exists() else ""
    if current != (source / marker).read_text(encoding="utf-8"):
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source, target)
    return target
