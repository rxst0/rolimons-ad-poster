package org.roliposter;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;

/**
 * Win/loss summary for a new-trade alert ("You give 10,000 · You get 12,400"), from your side of the trade.
 * Same rules as roliposter/roblox_trades.py: Rolimons value (RAP when it has none), robux you get counts
 * 70% (Roblox's fee). Item values come from Rolimons' public item list (no sign-in), cached for an hour;
 * the trade's items from RobloxApi ("trade" request, read-only).
 */
public class TradeValue {
    private static final String ITEM_DETAILS_URL = "https://www.rolimons.com/itemapi/itemdetails";
    private static final long CACHE_MS = 60 * 60 * 1000;
    private static final double ROBUX_AFTER_TAX = 0.7;

    private static Map<Long, long[]> values;  // asset ID -> {value (or RAP), projected 0/1}
    private static long loadedAt = 0;

    /** Gain, percent and text for a trade, or null when it can't be worked out (no sign-in, network, ...). */
    public static class Summary {
        public final long give, get;
        public final boolean projected;

        Summary(long give, long get, boolean projected) {
            this.give = give;
            this.get = get;
            this.projected = projected;
        }

        public String percentText() {
            if (give <= 0) return "";
            long pct = Math.round((get - give) * 100.0 / give);
            return (pct > 0 ? "+" : "") + pct + "%";
        }

        public String text() {
            String text = String.format("You give %,d · You get %,d", give, get);
            String pct = percentText();
            if (!pct.isEmpty()) text += " (" + pct + ")";
            if (projected) text += " · includes a projected item";
            return text;
        }
    }

    /** partnerId: the other person's Roblox user ID (their offer is what you get). */
    static Summary describe(Context context, String tradeId, long partnerId) {
        try {
            Map<Long, long[]> known = values();
            if (known == null) return null;
            JSONObject reply = new JSONObject(RobloxApi.fetch(context, "trade", tradeId, ""));
            if (reply.getInt("status") != 200) return null;
            JSONObject trade = new JSONObject(reply.getString("body"));
            JSONObject a = trade.optJSONObject("participantAOffer");
            JSONObject b = trade.optJSONObject("participantBOffer");
            if (a == null || b == null) return null;
            JSONObject aUser = a.optJSONObject("user");
            boolean aIsPartner = aUser != null && partnerId != 0 && aUser.optLong("id") == partnerId;
            JSONObject mine = aIsPartner ? b : a, theirs = aIsPartner ? a : b;
            long[] give = side(mine, known), get = side(theirs, known);
            long getRobux = Math.round(theirs.optLong("robux") * ROBUX_AFTER_TAX);
            return new Summary(give[0] + mine.optLong("robux"), get[0] + getRobux, get[1] > 0);
        } catch (Throwable e) {
            return null;
        }
    }

    /** {total value, projected items} for one side's items. */
    private static long[] side(JSONObject offer, Map<Long, long[]> known) {
        long total = 0, projected = 0;
        JSONArray items = offer.optJSONArray("items");
        for (int i = 0; items != null && i < items.length(); i++) {
            JSONObject item = items.optJSONObject(i);
            if (item == null) continue;
            JSONObject target = item.optJSONObject("itemTarget");
            long id = target == null ? 0 : target.optLong("targetId");
            long[] info = known.get(id);
            total += info != null ? info[0] : item.optLong("recentAveragePrice");
            if (info != null) projected += info[1];
        }
        return new long[]{total, projected};
    }

    private static synchronized Map<Long, long[]> values() {
        if (values != null && System.currentTimeMillis() - loadedAt < CACHE_MS) return values;
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(ITEM_DETAILS_URL).openConnection();
            conn.setConnectTimeout(15000);
            conn.setReadTimeout(20000);
            String agent = System.getProperty("http.agent");
            if (agent != null) conn.setRequestProperty("User-Agent", agent);
            if (conn.getResponseCode() != 200) return values;
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            try (InputStream in = conn.getInputStream()) {
                byte[] buffer = new byte[16384];
                int n;
                while ((n = in.read(buffer)) != -1) out.write(buffer, 0, n);
            }
            // {"success": true, "items": {"<id>": [name, acronym, rap, value, default_value, demand, trend,
            //  projected, hyped, rare]}}
            JSONObject items = new JSONObject(new String(out.toByteArray(), StandardCharsets.UTF_8))
                    .getJSONObject("items");
            Map<Long, long[]> parsed = new HashMap<>();
            for (Iterator<String> it = items.keys(); it.hasNext(); ) {
                String key = it.next();
                JSONArray row = items.optJSONArray(key);
                if (row == null || row.length() < 8) continue;
                parsed.put(Long.parseLong(key), new long[]{row.optLong(4), row.optInt(7) == 1 ? 1 : 0});
            }
            values = parsed;
            loadedAt = System.currentTimeMillis();
        } catch (Throwable e) {
            // keep the old list (or none) and try again next time
        } finally {
            if (conn != null) conn.disconnect();
        }
        return values;
    }
}
