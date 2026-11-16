package app.tabletdeck.launcher;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.PixelFormat;
import android.graphics.drawable.GradientDrawable;
import android.os.IBinder;
import android.provider.Settings;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;

/**
 * Kleiner Griff am linken Bildschirmrand, solange eine andere App (z. B. spacedesk) im Vordergrund ist.
 * Antippen holt den Launcher zurück. Läuft als Vordergrunddienst, damit Android ihn nicht beendet.
 * Benötigt die Overlay-Berechtigung (per adb: appops set app.tabletdeck.launcher SYSTEM_ALERT_WINDOW allow).
 */
public class OverlayService extends Service {
    static final String CHANNEL = "overlay";
    View handle;

    @Override
    public void onCreate() {
        super.onCreate();
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Rücksprung-Griff",
                NotificationManager.IMPORTANCE_MIN));
        Notification n = new Notification.Builder(this, CHANNEL)
                .setSmallIcon(android.R.drawable.ic_menu_revert)
                .setContentTitle("Tablet Deck")
                .setContentText("Griff am linken Rand führt zurück")
                .build();
        startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);

        if (!Settings.canDrawOverlays(this)) {
            stopSelf();
            return;
        }
        handle = new View(this);
        GradientDrawable d = new GradientDrawable();
        d.setColor(0xCC4FB3FF);
        float r = dp(12);
        d.setCornerRadii(new float[]{0, 0, r, r, r, r, 0, 0});
        handle.setBackground(d);
        handle.setOnClickListener(v -> startActivity(new Intent(this, HomeActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)));
        WindowManager.LayoutParams lp = new WindowManager.LayoutParams(
                dp(28), dp(120),
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
                PixelFormat.TRANSLUCENT);
        lp.gravity = Gravity.START | Gravity.CENTER_VERTICAL;
        getSystemService(WindowManager.class).addView(handle, lp);
    }

    int dp(int v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics());
    }

    @Override
    public void onDestroy() {
        if (handle != null) getSystemService(WindowManager.class).removeView(handle);
        super.onDestroy();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_NOT_STICKY;   // nach Prozess-Kill nicht von selbst wieder einblenden
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
