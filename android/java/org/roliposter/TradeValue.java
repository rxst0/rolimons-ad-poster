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
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Win/loss for a new trade, from your side: value, RAP and current price of what you give and get.
 * Same rules as roliposter/roblox_trades.py and portfolio.py: Rolimons value (RAP when it has none),
 * robux you get count 70% (Roblox's fee), a price only counts when it's at most 3x the item's value.
 * Item values come from Rolimons' public item list and prices from its deals page (no sign-in), cached
 * for an hour; the trade's items from RobloxApi ("trade" request, read-only).
 */
public class TradeValue {
    private static final String ITEM_DETAILS_URL = "https://www.rolimons.com/itemapi/itemdetails";
    private static final String DEALS_URL = "https://www.rolimons.com/deals";
    private static final Pattern DEALS = Pattern.compile("var\\s+item_details\\s*=\\s*(\\{.*?\\})\\s*;", Pattern.DOTALL);
    private static final long CACHE_MS = 60 * 60 * 1000;
    private static final double ROBUX_AFTER_TAX = 0.7;
    private static final int MAX_PRICE_RATIO = 3;

    private static Map<Long, long[]> items;   // asset ID -> {value (or RAP), rap, projected 0/1}
    private static Map<Long, Long> prices;    // asset ID -> cheapest listing now
    private static long itemsAt = 0, pricesAt = 0;

    /** Totals for one trade. price is -1 when some item on that side has no realistic price. */
    public static class Summary {
        public final String status;
        public final long giveValue, getValue, giveRap, getRap, givePrice, getPrice;
        public final int projected, unknown;  // items you'd get that are projected / not on Rolimons

        Summary(String status, long[] give, long[] get, long giveRobux, long getRobux, int projected, int unknown) {
            this.status = status;
            long got = Math.round(getRobux * ROBUX_AFTER_TAX);
            giveValue = give[0] + giveRobux;
            getValue = get[0] + got;
            giveRap = give[1] + giveRobux;
            getRap = get[1] + got;
            givePrice = give[2] < 0 ? -1 : give[2] + giveRobux;
            getPrice = get[2] < 0 ? -1 : get[2] + got;
            this.projected = projected;
            this.unknown = unknown;
        }

        /** Percent gain, or null when it can't be worked out (nothing given, or a price is unknown). */
        static Double gain(long give, long get) {
            if (give <= 0 || get < 0) return null;
            return (get - give) * 100.0 / give;
        }

        public String percentText() {
            Double pct = gain(giveValue, getValue);
            if (pct == null) return "";
            long rounded = Math.round(pct);
            return (rounded > 0 ? "+" : "") + rounded + "%";
        }

        public String text() {
            String text = String.format("You give %,d · You get %,d", giveValue, getValue);
            String pct = percentText();
            if (!pct.isEmpty()) text += " (" + pct + ")";
            if (projected > 0) text += " · includes a projected item";
            return text;
        }
    }

    /** partnerId: the other person's Roblox user ID (their offer is what you get). Null on any failure. */
    static Summary describe(Context context, String tradeId, long partnerId) {
        try {
            Map<Long, long[]> known = items();
            if (known == null) return null;
            Map<Long, Long> listed = prices();
            JSONObject reply = new JSONObject(RobloxApi.fetch(context, "trade", tradeId, ""));
            if (reply.getInt("status") != 200) return null;
            JSONObject trade = new JSONObject(reply.getString("body"));
            JSONObject a = trade.optJSONObject("participantAOffer");
            JSONObject b = trade.optJSONObject("participantBOffer");
            if (a == null || b == null) return null;
            JSONObject aUser = a.optJSONObject("user");
            boolean aIsPartner = aUser != null && partnerId != 0 && aUser.optLong("id") == partnerId;
            JSONObject mine = aIsPartner ? b : a, theirs = aIsPartner ? a : b;
            long[] give = side(mine, known, listed), get = side(theirs, known, listed);
            return new Summary(trade.optString("status", ""), give, get, mine.optLong("robux"), theirs.optLong("robux"),
                    (int) get[3], (int) get[4]);
        } catch (Throwable e) {
            return null;
        }
    }

    /** {value, rap, price (-1 if any item has no realistic price), projected items, unknown items}. */
    private static long[] side(JSONObject offer, Map<Long, long[]> known, Map<Long, Long> listed) {
        long value = 0, rap = 0, price = 0, projected = 0, unknown = 0;
        JSONArray list = offer.optJSONArray("items");
        for (int i = 0; list != null && i < list.length(); i++) {
            JSONObject item = list.optJSONObject(i);
            if (item == null) continue;
            JSONObject target = item.optJSONObject("itemTarget");
            long id = target == null ? 0 : target.optLong("targetId");
            long[] info = known.get(id);
            if (info == null) {
                unknown++;
                long fallback = item.optLong("recentAveragePrice");
                value += fallback;
                rap += fallback;
                price = -1;
                continue;
            }
            value += info[0];
            rap += info[1];
            projected += info[2];
            Long p = listed == null ? null : listed.get(id);
            long reference = Math.max(info[0], info[1]);
            if (p == null || p <= 0 || reference <= 0 || p > reference * MAX_PRICE_RATIO) price = -1;
            else if (price >= 0) price += p;
        }
        return new long[]{value, rap, price, projected, unknown};
    }

    private static synchronized Map<Long, long[]> items() {
        if (items != null && System.currentTimeMillis() - itemsAt < CACHE_MS) return items;
        try {
            // {"success": true, "items": {"<id>": [name, acronym, rap, value, default_value, demand, trend,
            //  projected, hyped, rare]}}
            JSONObject all = new JSONObject(download(ITEM_DETAILS_URL)).getJSONObject("items");
            Map<Long, long[]> parsed = new HashMap<>();
            for (Iterator<String> it = all.keys(); it.hasNext(); ) {
                String key = it.next();
                JSONArray row = all.optJSONArray(key);
                if (row == null || row.length() < 8) continue;
                parsed.put(Long.parseLong(key), new long[]{row.optLong(4), row.optLong(2), row.optInt(7) == 1 ? 1 : 0});
            }
            items = parsed;
            itemsAt = System.currentTimeMillis();
        } catch (Throwable e) {
            // keep the old list (or none) and try again next time
        }
        return items;
    }

    private static synchronized Map<Long, Long> prices() {
        if (prices != null && System.currentTimeMillis() - pricesAt < CACHE_MS) return prices;
        try {
            // The deals page embeds {"1:<asset id>": [name, best price, rap, ...], ...}
            Matcher m = DEALS.matcher(download(DEALS_URL));
            if (!m.find()) return prices;
            JSONObject all = new JSONObject(m.group(1));
            Map<Long, Long> parsed = new HashMap<>();
            for (Iterator<String> it = all.keys(); it.hasNext(); ) {
                String key = it.next();
                if (!key.startsWith("1:")) continue;
                JSONArray row = all.optJSONArray(key);
                if (row == null || row.length() < 2 || row.isNull(1)) continue;
                long best = row.optLong(1);
                if (best > 0) parsed.put(Long.parseLong(key.substring(2)), best);
            }
            prices = parsed;
            pricesAt = System.currentTimeMillis();
        } catch (Throwable e) {
            // keep the old prices (or none)
        }
        return prices;
    }

    private static String download(String address) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(address).openConnection();
        try {
            conn.setConnectTimeout(15000);
            conn.setReadTimeout(25000);
            String agent = System.getProperty("http.agent");
            if (agent != null) conn.setRequestProperty("User-Agent", agent);
            if (conn.getResponseCode() != 200) throw new Exception("HTTP " + conn.getResponseCode());
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            try (InputStream in = conn.getInputStream()) {
                byte[] buffer = new byte[16384];
                int n;
                while ((n = in.read(buffer)) != -1) out.write(buffer, 0, n);
            }
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        } finally {
            conn.disconnect();
        }
    }
}
