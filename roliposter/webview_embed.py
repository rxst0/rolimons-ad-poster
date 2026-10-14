"""Embeds a Microsoft Edge WebView2 browser inside a Tkinter frame (Windows only).

WebView2's WinForms control runs on its own STA thread with a WinForms message loop; its borderless host
form is re-parented into the Tk frame's window, so it looks and behaves like part of the app. Windows
links the two threads' input queues, so mouse and keyboard work normally.
"""
import ctypes
import logging
import threading
from pathlib import Path
from typing import Callable

log = logging.getLogger("roliposter.webview")

_user32 = ctypes.windll.user32
GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_CLIPCHILDREN = 0x02000000


class EmbeddedWebView:
    """A WebView2 browser shown inside a Tk widget.

    request_guard(method, url) -> str | None: return a reason to block a request locally (it gets a 403 and
    never leaves the PC), or None to let it through. Only URLs matching guard_filter reach the guard.
    """

    def __init__(self, parent_hwnd: int, url: str, profile_dir: Path, *, background: str = "#15181d",
                 document_script: str = "", guard_filter: str = "*",
                 request_guard: Callable[[str, str], str | None] | None = None,
                 on_error: Callable[[str], None] | None = None, extensions: tuple[Path, ...] = (),
                 on_extension: Callable[[str], None] | None = None):
        self.parent_hwnd = parent_hwnd
        self.url = url
        self.profile_dir = profile_dir
        self.background = background
        self.document_script = document_script
        self.guard_filter = guard_filter
        self.request_guard = request_guard
        self.on_error = on_error or (lambda message: log.error("%s", message))
        self.extensions = tuple(extensions)  # unpacked browser extension folders to install
        self.on_extension = on_extension or (lambda message: log.info("%s", message))
        self.hwnd = 0
        self._form = None
        self._view = None
        self._size = (800, 600)
        self._ready = threading.Event()
        self._thread = None

    # ---- lifecycle (called from the Tk thread) ---------------------------------
    def start(self, width: int, height: int) -> None:
        self._size = (max(width, 1), max(height, 1))
        _load_clr()
        from System.Threading import ApartmentState, Thread, ThreadStart
        self._thread = Thread(ThreadStart(self._run))
        self._thread.SetApartmentState(ApartmentState.STA)
        self._thread.IsBackground = True
        self._thread.Start()

    def resize(self, width: int, height: int) -> None:
        self._size = (max(width, 1), max(height, 1))
        if self.hwnd:
            _user32.MoveWindow(self.hwnd, 0, 0, self._size[0], self._size[1], True)

    def navigate(self, url: str) -> None:
        self._invoke(lambda: self._view.CoreWebView2.Navigate(url))

    def reload(self) -> None:
        self._invoke(lambda: self._view.CoreWebView2.Reload())

    def run_script(self, script: str) -> None:
        self._invoke(lambda: self._view.CoreWebView2.ExecuteScriptAsync(script))

    def clear_browsing_data(self, done: Callable[[], None] | None = None) -> None:
        """Signs out of every site in this profile (cookies, storage, cache)."""
        def clear():
            task = self._view.CoreWebView2.Profile.ClearBrowsingDataAsync()
            if done:
                from System import Action
                task.GetAwaiter().OnCompleted(Action(done))
        self._invoke(clear)

    def close(self) -> None:
        if self._form is not None:
            from System import Action
            try:
                self._form.BeginInvoke(Action(self._form.Close))
            except Exception:
                pass

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    # ---- WinForms thread --------------------------------------------------------
    def _invoke(self, func) -> None:
        if not self._ready.is_set():
            return
        from System import Action
        self._form.BeginInvoke(Action(func))

    def _run(self) -> None:
        try:
            import System.Windows.Forms as WinForms
            from Microsoft.Web.WebView2.Core import CoreWebView2Environment, CoreWebView2EnvironmentOptions
            from Microsoft.Web.WebView2.WinForms import WebView2
            from System import Action, EventHandler
            from System.Drawing import Color

            color = Color.FromArgb(*(int(self.background[i:i + 2], 16) for i in (1, 3, 5)))
            form = WinForms.Form()
            form.FormBorderStyle = getattr(WinForms.FormBorderStyle, "None")
            form.ShowInTaskbar = False
            form.BackColor = color
            view = WebView2()
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            view.DefaultBackgroundColor = color
            view.Dock = WinForms.DockStyle.Fill
            view.CoreWebView2InitializationCompleted += self._on_initialized
            form.Controls.Add(view)
            self._form, self._view = form, view

            # Re-parent the borderless form into the Tk frame and make it a child window.
            self.hwnd = form.Handle.ToInt64()
            style = _user32.GetWindowLongW(self.hwnd, GWL_STYLE)
            _user32.SetWindowLongW(self.hwnd, GWL_STYLE, (style | WS_CHILD | WS_CLIPCHILDREN) & ~0x80000000)
            _user32.SetParent(self.hwnd, self.parent_hwnd)
            _user32.MoveWindow(self.hwnd, 0, 0, self._size[0], self._size[1], True)
            def create_environment(_sender, _args):
                # Our own environment (not CreationProperties), so browser extensions can be enabled.
                options = CoreWebView2EnvironmentOptions()
                options.AreBrowserExtensionsEnabled = bool(self.extensions)
                awaiter = CoreWebView2Environment.CreateAsync(None, str(self.profile_dir), options).GetAwaiter()

                def created():
                    try:
                        view.EnsureCoreWebView2Async(awaiter.GetResult())
                    except Exception as e:
                        self.on_error(f"The built-in browser couldn't start: {e}")
                awaiter.OnCompleted(Action(created))
            form.Shown += EventHandler(create_environment)
            WinForms.Application.Run(form)
        except Exception as e:
            log.exception("WebView2 failed to start")
            self.on_error(f"The built-in browser couldn't start: {e}")
        finally:
            self._ready.clear()

    def _on_initialized(self, sender, args) -> None:
        if not args.IsSuccess:
            self.on_error(f"The built-in browser couldn't start: {args.InitializationException}")
            return
        from Microsoft.Web.WebView2.Core import (CoreWebView2WebResourceContext,
                                                 CoreWebView2WebResourceRequestSourceKinds)
        core = self._view.CoreWebView2
        settings = core.Settings
        settings.AreDevToolsEnabled = False
        settings.IsStatusBarEnabled = False
        settings.AreDefaultContextMenusEnabled = True
        if self.request_guard is not None:
            # Every request source WebView2 can report: pages, shared workers and service workers.
            core.AddWebResourceRequestedFilter(self.guard_filter, CoreWebView2WebResourceContext.All,
                                               CoreWebView2WebResourceRequestSourceKinds.All)
            core.WebResourceRequested += self._on_request
        if self.document_script:
            core.AddScriptToExecuteOnDocumentCreatedAsync(self.document_script)
        core.NewWindowRequested += self._on_new_window
        self._ready.set()
        self._install_extensions(core, list(self.extensions))

    def _install_extensions(self, core, remaining: list) -> None:
        """Installs extensions one at a time, then opens the page (so their scripts apply to it)."""
        if not remaining:
            core.Navigate(self.url)
            return
        from System import Action
        folder = remaining.pop(0)
        awaiter = core.Profile.AddBrowserExtensionAsync(str(folder)).GetAwaiter()

        def done():
            try:
                ext = awaiter.GetResult()
                self.on_extension(f"Extension loaded: {ext.Name} ({'on' if ext.IsEnabled else 'off'})")
            except Exception as e:
                self.on_extension(f"Couldn't load the extension in {folder.name}: {e}")
            self._install_extensions(core, remaining)
        awaiter.OnCompleted(Action(done))

    def _on_new_window(self, sender, args) -> None:
        # Keep pop-ups (e.g. "open trade in new tab") inside this view.
        args.Handled = True
        sender.Navigate(args.Uri)

    def _on_request(self, sender, args) -> None:
        method, url = str(args.Request.Method), str(args.Request.Uri)
        try:
            reason = self.request_guard(method, url)
        except Exception:
            log.exception("Request guard failed; blocking to be safe")
            reason = "Blocked"
        if not reason:
            return
        log.warning("Blocked %s %s", method, url)
        headers = ""
        if args.Request.Headers.Contains("Origin"):
            origin = str(args.Request.Headers.GetHeader("Origin"))
            headers = f"Access-Control-Allow-Origin: {origin}\nAccess-Control-Allow-Credentials: true"
        args.Response = sender.Environment.CreateWebResourceResponse(None, 403, reason, headers)


_clr_loaded = False


def _load_clr() -> None:
    """Loads .NET and the WebView2 assemblies (shipped with pywebview) once per process."""
    global _clr_loaded
    if _clr_loaded:
        return
    import os
    try:
        import clr
    except Exception:
        os.environ["PYTHONNET_RUNTIME"] = "coreclr"
        import clr
    from webview.util import interop_dll_path
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Threading")
    clr.AddReference(interop_dll_path("Microsoft.Web.WebView2.Core.dll"))
    clr.AddReference(interop_dll_path("Microsoft.Web.WebView2.WinForms.dll"))
    for platform in ("win-arm64", "win-x64", "win-x86"):
        os.environ["Path"] += ";" + interop_dll_path(platform)
    _clr_loaded = True
