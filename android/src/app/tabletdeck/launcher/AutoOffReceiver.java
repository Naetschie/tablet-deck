package app.tabletdeck.launcher;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.PowerManager;
import android.os.SystemClock;
import android.util.Log;

/**
 * Rückfall, falls der PC das Tablet beim Herunterfahren nicht ausschalten konnte: War das Tablet mit dem Hub
 * verbunden und ist dann AUTO_OFF_MS lang weder per USB noch per WLAN verbunden und der Bildschirm aus
 * (nicht in Benutzung), fährt es herunter
 * (über die Power-Anfrage an das Root-Modul hardening). Ein Wecker statt eines Handlers, damit das auch im
 * Schlaf des Tablets greift. Wieder verbunden -> Wecker gelöscht.
 */
public class AutoOffReceiver extends BroadcastReceiver {
    static final long AUTO_OFF_MS = 5 * 60_000;

    static PendingIntent intent(Context c) {
        return PendingIntent.getBroadcast(c, 0, new Intent(c, AutoOffReceiver.class),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    static void arm(Context c) {
        c.getSystemService(AlarmManager.class).setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP,
                SystemClock.elapsedRealtime() + AUTO_OFF_MS, intent(c));
        // "Wach bleiben beim Laden" aus: liefert der PC nach dem Herunterfahren weiter USB-Strom, bliebe der
        // Bildschirm sonst an und das Tablet gälte nie als unbenutzt. Alter Wert wird gemerkt.
        android.content.SharedPreferences p = c.getSharedPreferences("deck", Context.MODE_PRIVATE);
        try {
            int v = android.provider.Settings.Global.getInt(c.getContentResolver(),
                    android.provider.Settings.Global.STAY_ON_WHILE_PLUGGED_IN, 0);
            // schon 0 (z. B. vom PC beim Herunterfahren abgeschaltet): nichts merken - beim Wiederverbinden
            // setzt die Bridge den Wert selbst, ein gemerktes 0 würde ihn sonst überschreiben
            if (!p.contains("stayon_saved") && v != 0) p.edit().putInt("stayon_saved", v).apply();
            android.provider.Settings.Global.putInt(c.getContentResolver(),
                    android.provider.Settings.Global.STAY_ON_WHILE_PLUGGED_IN, 0);
        } catch (SecurityException e) {
            Log.w(HomeActivity.TAG, "stayon nicht änderbar: " + e);
        }
    }

    static void disarm(Context c) {
        c.getSystemService(AlarmManager.class).cancel(intent(c));
        android.content.SharedPreferences p = c.getSharedPreferences("deck", Context.MODE_PRIVATE);
        if (p.contains("stayon_saved")) {
            try {
                // nur zurücksetzen, wenn noch unser 0 gilt (nicht inzwischen von der Bridge gesetzt)
                if (android.provider.Settings.Global.getInt(c.getContentResolver(),
                        android.provider.Settings.Global.STAY_ON_WHILE_PLUGGED_IN, 0) == 0)
                    android.provider.Settings.Global.putInt(c.getContentResolver(),
                            android.provider.Settings.Global.STAY_ON_WHILE_PLUGGED_IN, p.getInt("stayon_saved", 0));
            } catch (SecurityException e) {
                Log.w(HomeActivity.TAG, "stayon nicht wiederherstellbar: " + e);
            }
            p.edit().remove("stayon_saved").apply();
        }
    }

    @Override
    public void onReceive(Context c, Intent i) {
        HomeActivity a = HomeActivity.current;
        if (a == null || a.connected || a.companion) return;
        // wird das Tablet gerade benutzt (Bildschirm an), nicht abschalten - später erneut prüfen
        if (c.getSystemService(PowerManager.class).isInteractive()) {
            arm(c);
            return;
        }
        Log.w(HomeActivity.TAG, "Seit 5 min keine Verbindung zum PC - Tablet fährt herunter");
        // kurz wach halten, bis das Root-Modul (prüft alle 2 s) die Anfrage ausgeführt hat
        PowerManager.WakeLock wl = c.getSystemService(PowerManager.class)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "tabletdeck:autooff");
        wl.acquire(15_000);
        a.requestPower("shutdown");
    }
}
