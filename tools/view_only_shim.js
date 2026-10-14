// Added by Rolimons Ad Poster (tools/fetch_rovalra.py): keeps Roblox trades view-only.
// Requests from an extension's background worker don't pass through the app's own network block,
// so this refuses every request that could change a trade (accept, decline, counter, send, cancel)
// before it is sent. Reading trades is unaffected.
(() => {
  const READ = new Set(["GET", "HEAD", "OPTIONS"]);
  const REASON = "Blocked: Rolimons Ad Poster is view-only for trades";
  const isTradeWrite = (url, method) => {
    if (READ.has(String(method || "GET").toUpperCase())) return false;
    try {
      const u = new URL(String(url), self.location ? self.location.href : undefined);
      const host = u.hostname.toLowerCase();
      return (host === "roblox.com" || host.endsWith(".roblox.com")) && /trade/i.test(u.pathname);
    } catch (e) {
      return true; // unparseable URL with a write method: refuse to be safe
    }
  };
  const realFetch = self.fetch.bind(self);
  self.fetch = (input, init) => {
    const url = input && typeof input === "object" && "url" in input ? input.url : input;
    const method = (init && init.method) || (input && typeof input === "object" && input.method) || "GET";
    if (isTradeWrite(url, method)) {
      console.warn("[view-only]", REASON, method, url);
      return Promise.resolve(new Response("", { status: 403, statusText: REASON }));
    }
    return realFetch(input, init);
  };
  if (typeof XMLHttpRequest !== "undefined") {
    const open = XMLHttpRequest.prototype.open;
    const send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url, ...rest) {
      this.__roliBlocked = isTradeWrite(url, method);
      return open.call(this, method, url, ...rest);
    };
    XMLHttpRequest.prototype.send = function (...args) {
      if (this.__roliBlocked) {
        console.warn("[view-only]", REASON);
        this.abort();
        return;
      }
      return send.apply(this, args);
    };
  }
})();
