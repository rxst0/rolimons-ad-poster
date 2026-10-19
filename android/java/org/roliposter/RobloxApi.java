package org.roliposter;

import android.content.Context;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * Read-only Roblox requests made with the stored sign-in (see RobloxSession). Only a fixed set of GET
 * requests can be made: there is no way to ask for any other URL, method or body, so nothing here can
 * accept, decline, send or change a trade, or touch anything else on the account.
 *
 * Callers get {"status": <HTTP status>, "body": "<reply text>"}; status is 0 when there's no stored
 * sign-in, -1 for a network error and -2 for a request that isn't allowed. Never call on the UI thread.
 */
public class RobloxApi {
    private static final Pattern LIST_KIND = Pattern.compile("^(inbound|outbound|completed|inactive)$");
    private static final Pattern TRADE_ID = Pattern.compile("^[0-9]{1,20}$");
    private static final Pattern CURSOR = Pattern.compile("^[A-Za-z0-9_=-]{0,500}$");
    private static final int MAX_BODY = 2 * 1024 * 1024;

    /** kind "list" (arg: inbound/outbound/completed/inactive, optional cursor) or "trade" (arg: trade ID). */
    public static String fetch(Context context, String kind, String arg, String cursor) {
        String url = allowedUrl(kind, arg, cursor);
        if (url == null) return result(-2, "");
        return get(context, url);
    }

    static String allowedUrl(String kind, String arg, String cursor) {
        if (arg == null) return null;
        if (cursor == null) cursor = "";
        if ("list".equals(kind) && LIST_KIND.matcher(arg).matches() && CURSOR.matcher(cursor).matches()) {
            return "https://trades.roblox.com/v1/trades/" + arg + "?limit=25&sortOrder=Desc"
                    + (cursor.isEmpty() ? "" : "&cursor=" + cursor);
        }
        if ("trade".equals(kind) && TRADE_ID.matcher(arg).matches()) {
            return "https://trades.roblox.com/v2/trades/" + arg;
        }
        return null;
    }

    static String get(Context context, String url) {
        String cookie = RobloxSession.get(context);
        if (cookie == null) return result(0, "");
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(url).openConnection();
            conn.setRequestMethod("GET");
            conn.setInstanceFollowRedirects(false);
            conn.setConnectTimeout(15000);
            conn.setReadTimeout(20000);
            conn.setRequestProperty("Cookie", RobloxSession.COOKIE + "=" + cookie);
            conn.setRequestProperty("Accept", "application/json");
            // Not WebSettings.getDefaultUserAgent: that starts a WebView, which the service process mustn't.
            String agent = System.getProperty("http.agent");
            if (agent != null) conn.setRequestProperty("User-Agent", agent);
            int status = conn.getResponseCode();
            for (Map.Entry<String, List<String>> header : conn.getHeaderFields().entrySet()) {
                if (header.getKey() == null || !header.getKey().equalsIgnoreCase("Set-Cookie")) continue;
                for (String value : header.getValue()) {
                    if (value.trim().startsWith(RobloxSession.COOKIE + "=")) RobloxSession.rotated(context, value.trim());
                }
            }
            InputStream in = status >= 400 ? conn.getErrorStream() : conn.getInputStream();
            return result(status, in == null ? "" : readBody(in));
        } catch (Exception e) {
            return result(-1, "");
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private static String readBody(InputStream in) throws Exception {
        try (InputStream stream = in) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[16384];
            int n;
            while ((n = stream.read(buffer)) != -1) {
                if (out.size() + n > MAX_BODY) break;
                out.write(buffer, 0, n);
            }
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private static String result(int status, String body) {
        try {
            return new JSONObject().put("status", status).put("body", body).toString();
        } catch (Exception e) {
            return "{\"status\": -1, \"body\": \"\"}";
        }
    }
}
