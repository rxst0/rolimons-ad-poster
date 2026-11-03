package org.roliposter;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;

/**
 * Auto-accept for new received trades that pass the user's rules (Settings > Auto-accept). Off by default.
 *
 * Test mode only reports what it would do. Live mode accepts through RobloxApi.accept(), which is
 * package-private: nothing outside this package (not the Python side, not the trades page) can accept.
 * Built-in safety, not configurable: every item you'd get must be on Rolimons; a price rule needs a
 * realistic price for every item; the trade must still be open; at most maxPerDay accepts a day.
 */
public class AutoAccept {
    private static final String RULES_FILE = "auto_accept_rules.json";
    private static final String LOG_FILE = "auto_accept_log.json";
    private static final String COUNT_FILE = "auto_accept_count.json";
    private static final int LOG_SIZE = 50;

    /** Outcome for the new-trade notification. */
    static class Decision {
        final boolean pass, accepted;
        final String line;  // shown in the notification, e.g. "Would auto-accept (test mode)"

        Decision(boolean pass, boolean accepted, String line) {
            this.pass = pass;
            this.accepted = accepted;
            this.line = line;
        }
    }

    /** Called by the app with the rules from config.json (see roliposter.config.AutoAcceptSettings). */
    public static synchronized void setRules(Context context, String json) {
        try {
            JSONObject rules = new JSONObject(json);  // must parse; stored as-is
            write(context, RULES_FILE, rules.toString());
        } catch (Exception e) {
            new File(context.getApplicationContext().getFilesDir(), RULES_FILE).delete();  // bad rules: off
        }
    }

    /** The latest decisions, newest first, as a JSON array (for the Settings screen). */
    public static synchronized String recentLog(Context context) {
        String text = read(context, LOG_FILE);
        return text == null ? "[]" : text;
    }

    static JSONObject rules(Context context) {
        try {
            String text = read(context, RULES_FILE);
            return text == null ? null : new JSONObject(text);
        } catch (Exception e) {
            return null;
        }
    }

    static boolean enabled(Context context) {
        JSONObject r = rules(context);
        return r != null && r.optBoolean("enabled", false);
    }

    /** Checks a new trade against the rules and, in live mode, accepts it. Null when auto-accept is off. */
    static synchronized Decision handle(Context context, String tradeId, String partner, TradeValue.Summary s) {
        JSONObject r = rules(context);
        if (r == null || !r.optBoolean("enabled", false)) return null;
        boolean live = "live".equals(r.optString("mode", "test"));
        List<String> fails = new ArrayList<>();
        if (s == null) {
            fails.add("couldn't read the trade's items");
        } else {
            if (!"Open".equalsIgnoreCase(s.status) && !s.status.isEmpty()) fails.add("trade is no longer open");
            if (s.unknown > 0) fails.add(s.unknown + " item(s) you'd get aren't on Rolimons");
            if (r.optBoolean("block_projected", true) && s.projected > 0) fails.add("includes a projected item");
            check(fails, r, "min_value_gain", "value", TradeValue.Summary.gain(s.giveValue, s.getValue));
            check(fails, r, "min_rap_gain", "RAP", TradeValue.Summary.gain(s.giveRap, s.getRap));
            check(fails, r, "min_price_gain", "price", TradeValue.Summary.gain(s.givePrice, s.getPrice));
        }
        boolean pass = fails.isEmpty();
        boolean accepted = false;
        String line;
        if (!pass) {
            line = "Not auto-accepted: " + String.join("; ", fails) + ".";
        } else if (!live) {
            line = "Would auto-accept (test mode, nothing was accepted).";
        } else if (acceptsToday(context) >= Math.max(0, r.optInt("max_per_day", 5))) {
            line = "Passed your rules, but today's auto-accept limit is reached. Accept it on Roblox if you want it.";
        } else {
            int status = RobloxApi.accept(context, tradeId);
            accepted = status == 200;
            if (accepted) {
                countAccept(context);
                line = "Auto-accepted.";
            } else if (status == RobloxApi.NEEDS_VERIFICATION) {
                line = "Passed your rules, but Roblox wants 2-step verification to accept it. Accept it on Roblox.";
            } else {
                line = "Passed your rules, but accepting failed (" + status + "). Accept it on Roblox if you want it.";
            }
        }
        log(context, tradeId, partner, s, live, pass, accepted, line);
        return new Decision(pass, accepted, line);
    }

    private static void check(List<String> fails, JSONObject r, String key, String label, Double gain) {
        if (!r.has(key) || r.isNull(key)) return;  // rule not set
        double min = r.optDouble(key);
        if (gain == null) {
            fails.add(label + " unknown for some items");
        } else if (gain < min) {
            fails.add(String.format("%s gain %+.0f%% is below %+.0f%%", label, gain, min));
        }
    }

    // ---- daily limit and log -----------------------------------------------------------------
    private static String today() {
        return String.valueOf(System.currentTimeMillis() / 86_400_000L);
    }

    private static int acceptsToday(Context context) {
        try {
            JSONObject c = new JSONObject(read(context, COUNT_FILE));
            return today().equals(c.optString("day")) ? c.optInt("count") : 0;
        } catch (Exception e) {
            return 0;
        }
    }

    private static void countAccept(Context context) {
        try {
            write(context, COUNT_FILE, new JSONObject().put("day", today()).put("count", acceptsToday(context) + 1).toString());
        } catch (Exception ignored) {
        }
    }

    private static void log(Context context, String tradeId, String partner, TradeValue.Summary s, boolean live,
                            boolean pass, boolean accepted, String line) {
        try {
            JSONArray old = new JSONArray(recentLog(context));
            JSONArray fresh = new JSONArray();
            JSONObject entry = new JSONObject().put("t", System.currentTimeMillis() / 1000).put("trade", tradeId)
                    .put("partner", partner).put("live", live).put("pass", pass).put("accepted", accepted)
                    .put("result", line);
            if (s != null) entry.put("give", s.giveValue).put("get", s.getValue).put("pct", s.percentText());
            fresh.put(entry);
            for (int i = 0; i < old.length() && fresh.length() < LOG_SIZE; i++) fresh.put(old.get(i));
            write(context, LOG_FILE, fresh.toString());
        } catch (Exception ignored) {
        }
    }

    private static String read(Context context, String name) {
        File f = new File(context.getApplicationContext().getFilesDir(), name);
        try {
            return f.exists() ? new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8) : null;
        } catch (Exception e) {
            return null;
        }
    }

    private static void write(Context context, String name, String text) throws Exception {
        File target = new File(context.getApplicationContext().getFilesDir(), name);
        File tmp = new File(target.getPath() + ".tmp");
        try (FileOutputStream out = new FileOutputStream(tmp)) {
            out.write(text.getBytes(StandardCharsets.UTF_8));
        }
        if (!tmp.renameTo(target)) {
            target.delete();
            tmp.renameTo(target);
        }
    }
}
