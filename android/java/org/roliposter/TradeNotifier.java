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
 * "New trade from X" notifications. The view-only trades WebView polls Roblox's inbound-trades list
 * (a read-only request made by the page itself; the app never sees the Roblox login) and passes the
 * trade IDs and sender names here. This runs in Java so it keeps working while the Python/Kivy side
 * is paused in the background.
 */
public class TradeNotifier {
    public static final String CHANNEL = "trades";
    public static final String OPEN_TAB_EXTRA = "roliposter_open_tab";
    private static final String PREFS = "roliposter_trades";
    private static final int MAX_SEEN = 300;
    private static final int MAX_PER_REPORT = 5;  // never a flood of notifications
    private static final Pattern TRADE_ID = Pattern.compile("^[0-9]{1,18}$");
    private static final Pattern SAFE_NAME = Pattern.compile("^[A-Za-z0-9_ .]{1,40}$");

    public static volatile int notifiedCount = 0;

    private final Context context;
    private final SharedPreferences prefs;

    public TradeNotifier(Context context) {
        this.context = context.getApplicationContext();
        this.prefs = this.context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    @JavascriptInterface
    public boolean isSeeded() {
        return prefs.getBoolean("seeded", false);
    }

    public void setEnabled(boolean enabled) {
        prefs.edit().putBoolean("enabled", enabled).apply();
    }

    @JavascriptInterface
    public boolean isEnabled() {
        return prefs.getBoolean("enabled", true);
    }

    /** Called by the page with JSON: [{"id": "123", "name": "Builderman"}, ...] newest first. */
    @JavascriptInterface
    public synchronized void report(String json) {
        if (!isEnabled() || json == null || json.length() > 20000) return;
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
        prefs.edit().putStringSet("seen", seen).putBoolean("seeded", true).apply();
    }

    private void notifyTrade(String id, String name) {
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) return;
        manager.createNotificationChannel(
                new NotificationChannel(CHANNEL, "New trades", NotificationManager.IMPORTANCE_HIGH));
        Intent launch = context.getPackageManager().getLaunchIntentForPackage(context.getPackageName());
        if (launch == null) return;
        launch.putExtra(OPEN_TAB_EXTRA, "trades");
        PendingIntent pending = PendingIntent.getActivity(context, 101, launch,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification notification = new Notification.Builder(context, CHANNEL)
                .setContentTitle("New trade from " + name)
                .setContentText("Tap to view it (view only).")
                .setSmallIcon(context.getApplicationInfo().icon)
                .setContentIntent(pending)
                .setAutoCancel(true)
                .build();
        manager.notify(4000 + (int) (Long.parseLong(id) % 100000), notification);
        notifiedCount++;
    }
}
