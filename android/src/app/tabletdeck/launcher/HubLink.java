package app.tabletdeck.launcher;

import android.content.Context;
import android.content.SharedPreferences;
import android.provider.Settings;
import android.util.Log;

import java.net.HttpURLConnection;
import java.net.Proxy;
import java.net.URL;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * Verbindungsweg zum Hub: USB (http://localhost:8765 per adb reverse) oder WLAN (https://<PC-IP>:<port>,
 * TLS mit der CA des Hubs, die er per ADB an den PairingReceiver schickt - Prüfung in HubTrust).
 *
 * Ein Hintergrund-Thread prüft alle 3 s, welcher Weg geht: USB hat Vorrang; ist USB 6 s weg, wird auf eine
 * der WLAN-Adressen gewechselt, die der Hub per USB mitgeteilt hat. Kommt USB zurück, geht es zurück.
 * Beim Wechsel wird der Android-Proxy umgestellt (USB: Bridge-Proxy fürs Internet, WLAN: direkt) - dafür
 * braucht die App WRITE_SECURE_SETTINGS (per adb erteilt, tablet/setup-launcher.ps1).
 */
class HubLink {
    static final String TAG = "TabletDeck";
    static final String USB = "http://localhost:" + HomeActivity.HUB_PORT;
    static final String USB_PROXY = "localhost:8766";

    interface Listener {
        void onSwitch(String base);

        /** Steuerkanal gerade verbunden? Dann ist der aktuelle Weg bestätigt (keine WLAN-Probe nötig). */
        boolean isConnected();
    }

    private final Context ctx;
    private final Listener listener;
    private volatile String base = USB;
    private volatile boolean running;
    /** Zeitpunkt (elapsedRealtime), zu dem der Hub zuletzt auf dem aktuellen Weg antwortete. */
    volatile long hubSeen;
    private String probeError;   // letzter Fehler von probe() (nur fürs Log)
    private Thread thread;

    HubLink(Context ctx, Listener listener) {
        this.ctx = ctx.getApplicationContext();
        this.listener = listener;
    }

    String base() {
        return base;
    }

    boolean isWlan() {
        return !USB.equals(base);
    }

    // ------------------------------------------------------------ WLAN-Adressen (vom Hub per USB)

    private SharedPreferences prefs() {
        return ctx.getSharedPreferences("deck", Context.MODE_PRIVATE);
    }

    /** Vom Hub: {"hosts":[...], "port":8767}. Nur private IPv4-Adressen werden übernommen. */
    void setHosts(List<String> hosts, int port) {
        List<String> ok = new ArrayList<>();
        for (String h : hosts) if (isPrivateIpv4(h)) ok.add(h);
        if (port < 1024 || port > 65535) return;
        prefs().edit().putString("wlan_hosts", String.join(",", ok)).putInt("wlan_port", port).apply();
    }

    List<String> wlanBases() {
        String hs = prefs().getString("wlan_hosts", "");
        int port = prefs().getInt("wlan_port", 0);
        List<String> out = new ArrayList<>();
        if (hs.isEmpty() || port == 0) return out;
        for (String h : Arrays.asList(hs.split(","))) out.add("https://" + h + ":" + port);
        return out;
    }

    /** Ist host:port eine der WLAN-Adressen des Hubs? Nur dort gilt die Hub-CA (HubTrust). */
    boolean isHubAddress(String host, int port) {
        if (host == null || !isPrivateIpv4(host)) return false;
        if (port != prefs().getInt("wlan_port", 0)) return false;
        for (String h : prefs().getString("wlan_hosts", "").split(",")) if (h.equals(host)) return true;
        return false;
    }

    static boolean isPrivateIpv4(String h) {
        String[] p = h.split("\\.");
        if (p.length != 4) return false;
        int[] n = new int[4];
        try {
            for (int i = 0; i < 4; i++) {
                n[i] = Integer.parseInt(p[i]);
                if (n[i] < 0 || n[i] > 255 || !p[i].equals(String.valueOf(n[i]))) return false;
            }
        } catch (NumberFormatException e) {
            return false;
        }
        return n[0] == 10 || (n[0] == 172 && n[1] >= 16 && n[1] <= 31) || (n[0] == 192 && n[1] == 168);
    }

    // ------------------------------------------------------------ Prüfen und Umschalten

    void start() {
        if (running) return;
        running = true;
        thread = new Thread(this::loop, "hublink");
        thread.setDaemon(true);
        thread.start();
    }

    void stop() {
        running = false;
        if (thread != null) thread.interrupt();
    }

    private void loop() {
        int usbFails = 0;
        while (running) {
            try {
                boolean usbOk = probe(USB);
                if (!usbOk && usbFails == 0) Log.i(TAG, "HubLink: USB-Probe fehlgeschlagen (" + probeError + ")");
                if (usbOk) {
                    usbFails = 0;
                    hubSeen = android.os.SystemClock.elapsedRealtime();
                    if (isWlan()) switchTo(USB);
                } else {
                    usbFails++;
                    // Im WLAN: verbundener Steuerkanal bestätigt den Weg - keine TLS-Probe alle 3 s (Akku,
                    // WLAN-Energiesparen, Verbindungslimit des Hubs)
                    boolean wlanOk = isWlan() && (listener.isConnected() || probe(base));
                    if (wlanOk) hubSeen = android.os.SystemClock.elapsedRealtime();
                    // erst nach 9 s ohne USB wechseln (kurze Aussetzer, z. B. USB-Neuanmeldung für spacedesk)
                    if (!wlanOk && usbFails >= 3) {
                        for (String b : wlanBases()) {
                            if (probe(b)) {
                                if (!b.equals(base)) switchTo(b);
                                break;
                            }
                        }
                    }
                }
                Thread.sleep(3000);
            } catch (InterruptedException e) {
                return;
            } catch (Exception e) {
                Log.w(TAG, "HubLink: " + e);
            }
        }
    }

    /** Erreichbar und wirklich der Hub (Steuerseite liefert 200)? Ohne Proxy, kurze Zeitlimits. WLAN: TLS nur
     *  mit der Hub-CA (HubTrust), Hostname-Prüfung der Verbindung bleibt (IP im Server-Zertifikat). */
    boolean probe(String b) {
        HttpURLConnection c = null;
        try {
            // USB: 127.0.0.1 statt "localhost" - der Android-Resolver scheitert zeitweise an "localhost"
            // (UnknownHostException), der WebView (Chromium) löst es immer selbst auf Loopback auf
            String u = USB.equals(b) ? "http://127.0.0.1:" + HomeActivity.HUB_PORT : b;
            c = (HttpURLConnection) new URL(u + HomeActivity.CTL_PATH).openConnection(Proxy.NO_PROXY);
            if (c instanceof javax.net.ssl.HttpsURLConnection) {
                javax.net.ssl.SSLSocketFactory f = HubTrust.socketFactory(ctx);
                if (f == null) return false;      // noch keine CA vom Hub (Tablet einmal per USB anstecken)
                ((javax.net.ssl.HttpsURLConnection) c).setSSLSocketFactory(f);
            }
            c.setConnectTimeout(1500);
            c.setReadTimeout(1500);
            c.setUseCaches(false);
            int code = c.getResponseCode();
            probeError = "HTTP " + code;
            return code == 200;
        } catch (Exception e) {
            probeError = e.toString();
            return false;   // nicht erreichbar oder Zertifikat passt nicht
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private void switchTo(String b) {
        if (!running) return;   // Activity schon beendet
        // Proxy zuerst: im WLAN direkt ins Internet (der Bridge-Proxy ist nur per USB erreichbar)
        setProxy(USB.equals(b) ? USB_PROXY : ":0");
        base = b;
        Log.i(TAG, "Hub-Verbindung: " + (USB.equals(b) ? "USB" : "WLAN " + b));
        listener.onSwitch(b);
    }

    private void setProxy(String value) {
        try {
            Settings.Global.putString(ctx.getContentResolver(), "http_proxy", value);
        } catch (SecurityException e) {
            Log.w(TAG, "Proxy nicht umstellbar (WRITE_SECURE_SETTINGS fehlt - setup-launcher.ps1)");
        }
    }
}
