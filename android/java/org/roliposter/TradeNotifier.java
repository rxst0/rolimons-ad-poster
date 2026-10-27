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
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * "New trade from X" and "X accepted your trade" notifications. New trades come from one of two places:
 * - the view-only trades WebView polls Roblox's inbound-trades list (a read-only request made by the
 *   page itself) and calls report(); this only runs while the app is open or recently used;
 * - with "Read my trades directly" on, TradeWatcher checks from the background service and calls
 *   reportDirect().
 * Both processes share the "seen" list, so a trade never notifies twice.
 */
public class TradeNotifier {
    public static final String CHANNEL = "trades";
    public static final String OPEN_TAB_EXTRA = "roliposter_open_tab";
    public static final String TRADES_LIST_EXTRA = "roliposter_trades_list";
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

    /**
     * Called by TradeWatcher with the sent (outbound) and completed lists, as [{"id", "name"}, ...].
     * A trade you sent that later shows up as completed was accepted: "X accepted your trade".
     * Sent trades are remembered between checks; the first check only remembers them.
     */
    public synchronized void reportAccepted(String outboundJson, String completedJson) {
        List<String[]> outbound = parse(outboundJson);
        List<String[]> completed = parse(completedJson);
        if (outbound == null || completed == null) return;
        SharedPreferences prefs = prefs();
        Map<String, String> sent = new LinkedHashMap<>();
        for (String entry : prefs.getStringSet("sent", new HashSet<String>())) {
            String[] parts = entry.split("\\|", 2);
            if (parts.length == 2) sent.put(parts[0], parts[1]);
        }
        Set<String> done = new HashSet<>();
        for (String[] t : completed) done.add(t[0]);
        int shown = 0;
        for (Iterator<Map.Entry<String, String>> it = sent.entrySet().iterator(); it.hasNext(); ) {
            Map.Entry<String, String> t = it.next();
            if (!done.contains(t.getKey())) continue;  // still waiting, or declined/expired (never completes)
            it.remove();
            if (shown++ < MAX_PER_REPORT && show(6000 + (int) (Long.parseLong(t.getKey()) % 100000),
                    t.getValue() + " accepted your trade", "Tap to see it in Completed.", "completed", 102)) {
                notifiedCount++;
            }
        }
        for (String[] t : outbound) sent.put(t[0], t[1]);
        if (sent.size() > MAX_SEEN) {  // mostly old declined trades: keep only what's still pending
            sent.clear();
            for (String[] t : outbound) sent.put(t[0], t[1]);
        }
        Set<String> store = new HashSet<>();
        for (Map.Entry<String, String> t : sent.entrySet()) store.add(t.getKey() + "|" + t.getValue());
        prefs.edit().putStringSet("sent", store).commit();
    }

    /** [{"id", "name"}, ...] JSON as checked [id, name] pairs, or null if it isn't a trade list. */
    private static List<String[]> parse(String json) {
        if (json == null || json.length() > 20000) return null;
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
            return null;
        }
        return trades;
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
        List<String[]> trades = parse(json);
        if (trades == null) return;
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
        if (show(4000 + (int) (Long.parseLong(id) % 100000), "New trade from " + name, "Tap to view it (view only).",
                "inbound", 101))
            notifiedCount++;
    }

    private boolean show(int notificationId, String title, String text) {
        return show(notificationId, title, text, "inbound", 101);
    }

    /** Tapping opens the Trades tab on `list` (inbound/completed); each list has its own requestCode. */
    private boolean show(int notificationId, String title, String text, String list, int requestCode) {
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) return false;
        manager.createNotificationChannel(
                new NotificationChannel(CHANNEL, "New trades", NotificationManager.IMPORTANCE_HIGH));
        Intent launch = context.getPackageManager().getLaunchIntentForPackage(context.getPackageName());
        if (launch == null) return false;
        launch.putExtra(OPEN_TAB_EXTRA, "trades");
        launch.putExtra(TRADES_LIST_EXTRA, list);
        PendingIntent pending = PendingIntent.getActivity(context, requestCode, launch,
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
