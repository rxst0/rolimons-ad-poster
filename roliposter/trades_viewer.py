"""View-only Roblox trades window.

Shows Roblox's own trades page (roblox.com/trades) in an embedded Microsoft Edge WebView2 window.
You sign in to Roblox inside that window, exactly as in a browser.

Security model:
- This app never reads, copies or stores your Roblox login. The session lives in WebView2's own browser
  profile (cookies encrypted by Windows, like Edge), in the "roblox-session" folder next to the app.
- View only: every request that would change a trade (accept, decline, counter, send, cancel) is
  blocked inside the window before it leaves your PC, and those buttons are hidden. To act on a trade,
  use roblox.com or the Roblox app.

Run it with:  RoliAdPoster.exe --trades   (or: python -m roliposter.trades_viewer)
"""
import logging
import shutil
from urllib.parse import urlsplit

from .paths import app_dir

TRADES_URL = "https://www.roblox.com/trades"
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
  const ACTIONS = /^(accept|decline|counter|make offer|send|send trade|cancel|confirm|ok, accept|ok, decline)$/i;
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
  document.documentElement.appendChild(banner);
  hide();
  new MutationObserver(hide).observe(document.documentElement, {childList: true, subtree: true});
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


def _install_request_guard() -> None:
    """Wraps pywebview's WebView2 request handler so blocked requests get a local 403 and never go out."""
    from webview.platforms import edgechromium

    original = edgechromium.EdgeChrome.on_web_resource_request
    if getattr(original, "_roli_guard", False):
        return

    def guarded(self, sender, args):
        method, url = str(args.Request.Method), str(args.Request.Uri)
        if is_blocked(method, url):
            log.warning("Blocked %s %s (view-only)", method, url)
            origin = ""
            if args.Request.Headers.Contains("Origin"):
                origin = str(args.Request.Headers.GetHeader("Origin"))
            # CORS headers let Roblox's page see a clean 403 instead of a generic network error.
            headers = (f"Access-Control-Allow-Origin: {origin}\nAccess-Control-Allow-Credentials: true"
                       if origin else "")
            args.Response = sender.Environment.CreateWebResourceResponse(None, BLOCK_STATUS, BLOCK_REASON, headers)
            return
        original(self, sender, args)

    guarded._roli_guard = True
    edgechromium.EdgeChrome.on_web_resource_request = guarded


def create_window(url: str = TRADES_URL, hidden: bool = False):
    import webview

    _install_request_guard()
    window = webview.create_window("Roblox trades (view only)", url, width=1200, height=860,
                                   min_size=(760, 560), hidden=hidden, background_color="#15181d")
    window.events.loaded += lambda: window.evaluate_js(VIEW_ONLY_JS)
    return window


def run(func=None, url: str = TRADES_URL, hidden: bool = False) -> None:
    import webview

    window = create_window(url, hidden)
    folder = session_dir()
    folder.mkdir(parents=True, exist_ok=True)
    webview.start(func, window, gui="edgechromium", private_mode=False, storage_path=str(folder))


if __name__ == "__main__":
    run()
