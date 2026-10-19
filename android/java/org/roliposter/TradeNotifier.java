package org.roliposter;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.webkit.JavascriptInterface;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * "New trade from X" notifications. Trade IDs and sender names come from one of two places:
 * - the view-only trades WebView polls Roblox's inbound-trades list (a read-only request made by the
 *   page itself) and calls report(); this only runs while the app is open or recently used;
 * - with "Read my trades directly" on, TradeWatcher checks from the background service and calls
 *   reportDirect().
 * Both processes share the "seen" list, so a trade never notifies twice.
 */
public class TradeNotifier {
    public static final String CHANNEL = "trades";
    public static final String OPEN_TAB_EXTRA = "roliposter_open_tab";
    private static final String PREFS = "roliposter_trades";
    private static final int MAX_SEEN = 300;
    private static final int MAX_PER_REPORT = 5;  // never a flood of notifications
    private static final int SIGNED_OUT_ID = 3999;
    private static final Pattern TRADE_ID = Pattern.compile("^[0-9]{1,18}$");
    private static final Pattern SAFE_NAME = Pattern.compile("^[A-Za-z0-9_ .]{1,40}$");

    public static volatile int notifiedCount = 0;

    private final Context context;

    public TradeNotifier(Context context) {
        this.context = context.getApplicationContext();
    }

    @SuppressWarnings("deprecation")
    private SharedPreferences prefs() {
        // Re-read from disk each time: the app and the background service both write this file.
        return context.getSharedPreferences(PREFS, Context.MODE_MULTI_PROCESS);
    }

    @JavascriptInterface
    public boolean isSeeded() {
        return prefs().getBoolean("seeded", false);
    }

    /** Whether the trades page's own check runs (off when the background service checks instead). */
    public void setEnabled(boolean enabled) {
        prefs().edit().putBoolean("enabled", enabled).commit();
    }

    @JavascriptInterface
    public boolean isEnabled() {
        return prefs().getBoolean("enabled", true);
    }

    /** Called by the page with JSON: [{"id": "123", "name": "Builderman"}, ...] newest first. */
    @JavascriptInterface
    public void report(String json) {
        if (isEnabled()) handle(json);
    }

    /** Called by TradeWatcher (background service), which is only running when it should notify. */
    public void reportDirect(String json) {
        handle(json);
        prefs().edit().putBoolean("signed_out_notified", false).commit();
    }

    /** The stored Roblox sign-in stopped working: say so once, until a check works again. */
    public void signedOut() {
        SharedPreferences prefs = prefs();
        if (prefs.getBoolean("signed_out_notified", false)) return;
        prefs.edit().putBoolean("signed_out_notified", true).commit();
        show(SIGNED_OUT_ID, "Signed out of Roblox",
                "New-trade alerts are paused. Open the Trades tab and sign in to Roblox again.");
    }

    private synchronized void handle(String json) {
        if (json == null || json.length() > 20000) return;
        List<String[]> trades = new ArrayList<>();
        try {
            JSONArray list = new JSONArray(json);
            for (int i = 0; i < Math.min(list.length(), 25); i++) {
                JSONObject t = list.getJSONObject(i);
                String id = t.optString("id", "");
                String name = t.optString("name", "");
                if (!TRADE_ID.matcher(id).matches()) continue;  // ignore anything that isn't a trade
                if (!SAFE_NAME.matcher(name).matches()) name = "someone";
                trades.add(new String[]{id, name});
            }
        } catch (Exception e) {
            return;
        }
        SharedPreferences prefs = prefs();
        Set<String> seen = new HashSet<>(prefs.getStringSet("seen", new HashSet<String>()));
        boolean firstRun = !prefs.getBoolean("seeded", false);
        int shown = 0;
        for (String[] t : trades) {
            if (seen.contains(t[0])) continue;
            seen.add(t[0]);
            if (!firstRun && shown++ < MAX_PER_REPORT) notifyTrade(t[0], t[1]);  // first run: remember existing trades, don't notify
        }
        if (seen.size() > MAX_SEEN) {
            List<String> keep = new ArrayList<>();
            for (String[] t : trades) keep.add(t[0]);
            seen = new HashSet<>(keep);
        }
        prefs.edit().putStringSet("seen", seen).putBoolean("seeded", true).commit();
    }

    private void notifyTrade(String id, String name) {
        if (show(4000 + (int) (Long.parseLong(id) % 100000), "New trade from " + name, "Tap to view it (view only)."))
            notifiedCount++;
    }

    private boolean show(int notificationId, String title, String text) {
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) return false;
        manager.createNotificationChannel(
                new NotificationChannel(CHANNEL, "New trades", NotificationManager.IMPORTANCE_HIGH));
        Intent launch = context.getPackageManager().getLaunchIntentForPackage(context.getPackageName());
        if (launch == null) return false;
        launch.putExtra(OPEN_TAB_EXTRA, "trades");
        PendingIntent pending = PendingIntent.getActivity(context, 101, launch,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification notification = new Notification.Builder(context, CHANNEL)
                .setContentTitle(title)
                .setContentText(text)
                .setSmallIcon(context.getApplicationInfo().icon)
                .setContentIntent(pending)
                .setAutoCancel(true)
                .build();
        manager.notify(notificationId, notification);
        return true;
    }
}
