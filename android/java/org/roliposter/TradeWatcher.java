package org.roliposter;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * Background trade checks for "Read my trades directly". Runs in the foreground service, so it keeps
 * going with the app closed: every few minutes it reads the inbound-trades list through RobloxApi
 * ("New trade from X"), and every other time the sent and completed lists ("X accepted your trade"),
 * passing trade IDs and names to TradeNotifier.
 */
public class TradeWatcher {
    public static volatile long lastCheck = 0;
    public static volatile int lastStatus = 0;

    private static ScheduledExecutorService executor;
    private static int skip = 0;  // checks to skip after Roblox asks us to slow down (429)
    private static int round = 0;

    public static synchronized void start(Context context, int intervalSeconds) {
        if (executor != null) return;
        final Context app = context.getApplicationContext();
        executor = Executors.newSingleThreadScheduledExecutor(runnable -> {
            Thread thread = new Thread(runnable, "roliposter-trade-watcher");
            thread.setDaemon(true);
            return thread;
        });
        executor.scheduleWithFixedDelay(() -> check(app), 3, Math.max(60, intervalSeconds), TimeUnit.SECONDS);
    }

    public static synchronized void stop() {
        if (executor != null) {
            executor.shutdownNow();
            executor = null;
        }
    }

    public static synchronized boolean isRunning() {
        return executor != null;
    }

    private static void check(Context context) {
        try {
            if (skip > 0) {
                skip--;
                return;
            }
            if (!RobloxSession.isSignedIn(context)) return;
            TradeNotifier notifier = new TradeNotifier(context);
            JSONArray inbound = list(context, notifier, "inbound");
            if (inbound == null) return;
            notifier.reportDirect(inbound.toString());
            // Every other check: did someone accept a trade you sent? (It moves from sent to completed.)
            if (round++ % 2 != 0) return;
            JSONArray outbound = list(context, notifier, "outbound");
            JSONArray completed = outbound == null ? null : list(context, notifier, "completed");
            if (completed != null) notifier.reportAccepted(outbound.toString(), completed.toString());
        } catch (Throwable e) {
            // try again next time
        }
    }

    /** [{"id", "name"}, ...] for one trade list, or null (signed out, rate limited or failed). */
    private static JSONArray list(Context context, TradeNotifier notifier, String kind) throws Exception {
        JSONObject reply = new JSONObject(RobloxApi.fetch(context, "list", kind, ""));
        lastStatus = reply.getInt("status");
        lastCheck = System.currentTimeMillis();
        if (lastStatus == 401) {
            notifier.signedOut();
            return null;
        }
        if (lastStatus == 429) {
            skip = 2;
            return null;
        }
        if (lastStatus != 200) return null;
        JSONArray data = new JSONObject(reply.getString("body")).getJSONArray("data");
        JSONArray trades = new JSONArray();
        for (int i = 0; i < data.length(); i++) {
            JSONObject t = data.getJSONObject(i);
            JSONObject user = t.optJSONObject("user");
            trades.put(new JSONObject().put("id", String.valueOf(t.optLong("id")))
                    .put("name", user == null ? "" : user.optString("name", ""))
                    .put("userId", user == null ? 0 : user.optLong("id")));
        }
        return trades;
    }
}
