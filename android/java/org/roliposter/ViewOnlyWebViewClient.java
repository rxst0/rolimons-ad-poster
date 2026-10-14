package org.roliposter;

import android.net.Uri;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.io.ByteArrayInputStream;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/**
 * Keeps the Received trades tab view-only: every request that could change a Roblox trade (accept,
 * decline, counter, send, cancel) gets an immediate local 403 and never leaves the phone. Same rule as
 * roliposter/trades_viewer.py on the PC. Also re-applies the view-only banner script after each page.
 */
public class ViewOnlyWebViewClient extends WebViewClient {
    public static final String REASON = "Blocked: Rolimons Ad Poster is view-only for trades";
    public static volatile int blockedCount = 0;

    private final String pageScript;

    public ViewOnlyWebViewClient(String pageScript) {
        this.pageScript = pageScript;
    }

    public static boolean isTradeWrite(String method, Uri url) {
        if (method == null || url == null) return false;
        String m = method.toUpperCase(Locale.ROOT);
        if (m.equals("GET") || m.equals("HEAD") || m.equals("OPTIONS")) return false;
        String host = url.getHost() == null ? "" : url.getHost().toLowerCase(Locale.ROOT);
        boolean roblox = host.equals("roblox.com") || host.endsWith(".roblox.com");
        String path = url.getPath() == null ? "" : url.getPath().toLowerCase(Locale.ROOT);
        return roblox && path.contains("trade");
    }

    @Override
    public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
        if (!isTradeWrite(request.getMethod(), request.getUrl())) return null;
        blockedCount++;
        Map<String, String> headers = new HashMap<>();
        String origin = request.getRequestHeaders().get("Origin");
        if (origin != null) {
            headers.put("Access-Control-Allow-Origin", origin);
            headers.put("Access-Control-Allow-Credentials", "true");
        }
        return new WebResourceResponse("text/plain", "utf-8", 403, REASON, headers,
                new ByteArrayInputStream(new byte[0]));
    }

    @Override
    public void onPageFinished(WebView view, String url) {
        if (pageScript != null && !pageScript.isEmpty()) view.evaluateJavascript(pageScript, null);
    }
}
