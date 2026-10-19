package org.roliposter;

import android.app.Notification;
import android.app.NotificationManager;
import android.content.Context;
import android.service.notification.StatusBarNotification;

/** Changes the text of the running service's status-bar notification (posting vs. checking for trades). */
public class ForegroundText {
    public static void update(Context context, String text) {
        try {
            NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
            if (manager == null) return;
            for (StatusBarNotification sbn : manager.getActiveNotifications()) {
                Notification n = sbn.getNotification();
                if ((n.flags & Notification.FLAG_FOREGROUND_SERVICE) == 0) continue;
                Notification updated = Notification.Builder.recoverBuilder(context, n).setContentText(text).build();
                manager.notify(sbn.getTag(), sbn.getId(), updated);
            }
        } catch (Exception e) {
            // cosmetic only
        }
    }
}
