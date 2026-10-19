package org.roliposter;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * Background "New trade from X" checks for "Read my trades directly". Runs in the foreground service,
 * so it keeps going with the app closed: every few minutes it reads the inbound-trades list through
 * RobloxApi and passes trade IDs and sender names to TradeNotifier.
 */
public class TradeWatcher {
    public static volatile long lastCheck = 0;
    public static volatile int lastStatus = 0;

    private static ScheduledExecutorService executor;
    private static int skip = 0;  // checks to skip after Roblox asks us to slow down (429)

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
            JSONObject reply = new JSONObject(RobloxApi.fetch(context, "list", "inbound", ""));
            lastStatus = reply.getInt("status");
            lastCheck = System.currentTimeMillis();
            TradeNotifier notifier = new TradeNotifier(context);
            if (lastStatus == 401) {
                notifier.signedOut();
                return;
            }
            if (lastStatus == 429) {
                skip = 2;
                return;
            }
            if (lastStatus != 200) return;
            JSONArray data = new JSONObject(reply.getString("body")).getJSONArray("data");
            JSONArray trades = new JSONArray();
            for (int i = 0; i < data.length(); i++) {
                JSONObject t = data.getJSONObject(i);
                JSONObject user = t.optJSONObject("user");
                trades.put(new JSONObject().put("id", String.valueOf(t.optLong("id")))
                        .put("name", user == null ? "" : user.optString("name", "")));
            }
            notifier.reportDirect(trades.toString());
        } catch (Throwable e) {
            // try again next time
        }
    }
}
