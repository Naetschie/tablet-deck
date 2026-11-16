package app.tabletdeck.launcher;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

/**
 * Nimmt das Kopplungsgeheimnis des Hubs entgegen. Im Manifest mit android.permission.DUMP geschützt:
 * Diese Berechtigung hat die ADB-Shell (Setup am PC per Kabel), normale Apps nicht. So kann keine andere
 * App auf dem Tablet die Kopplung überschreiben.
 *   adb shell am broadcast -n app.tabletdeck.launcher/.PairingReceiver --es deck_secret <geheimnis>
 * Betriebsart dieses Tablets (Hub: tablet_modes pro Seriennummer, bei jedem Anstecken):
 *   adb shell am broadcast -n app.tabletdeck.launcher/.PairingReceiver --es tablet_mode home|companion
 * Außerdem die WLAN-CA des Hubs (öffentliche Zertifikate, schickt der Hub bei jedem Anstecken):
 *   adb shell am broadcast -n app.tabletdeck.launcher/.PairingReceiver --es hub_ca <Base64 des PEM-Bündels>
 */
public class PairingReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context ctx, Intent intent) {
        String mode = intent.getStringExtra("tablet_mode");
        if (mode != null) {
            boolean ok = "home".equals(mode) || "companion".equals(mode);
            if (ok) {
                // fest: der Steuerkanal (gleicher Wert für alle Tablets) überschreibt das nicht mehr
                ctx.getSharedPreferences("deck", Context.MODE_PRIVATE).edit()
                        .putBoolean("companion", "companion".equals(mode)).putBoolean("mode_pinned", true).commit();
                Log.i(HomeActivity.TAG, "Kopplung: Betriebsart " + mode);
                HomeActivity a = HomeActivity.current;
                if (a != null) a.ui.post(() -> a.applyTabletModeFromPrefs());
            }
            setResultCode(ok ? 1 : 2);
            return;
        }
        String ca = intent.getStringExtra("hub_ca");
        if (ca != null) {
            boolean ok = HubTrust.store(ctx, ca);
            Log.i(HomeActivity.TAG, ok ? "Kopplung: WLAN-CA übernommen" : "Kopplung: WLAN-CA ungültig, ignoriert");
            setResultCode(ok ? 1 : 2);
            return;
        }
        String s = intent.getStringExtra("deck_secret");
        if (s == null || !s.matches("[A-Za-z0-9_-]{32,128}")) {
            Log.w(HomeActivity.TAG, "Kopplung: ungültiges Geheimnis ignoriert");
            setResultCode(2);
            return;
        }
        ctx.getSharedPreferences("deck", Context.MODE_PRIVATE).edit().putString("secret", s).commit();
        Log.i(HomeActivity.TAG, "Kopplung: Geheimnis übernommen");
        HomeActivity a = HomeActivity.current;
        if (a != null) a.ui.post(a::onPaired);
        setResultCode(1);
    }
}
