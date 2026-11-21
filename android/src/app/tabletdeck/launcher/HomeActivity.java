package app.tabletdeck.launcher;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.KeyguardManager;
import android.content.Intent;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * Startbildschirm des Tablets: Moduskacheln unten, darüber je Web-Modus eine WebView, die im Speicher
 * bleibt (sofortiges Umschalten).
 *
 * Sicherheit (Tablet läuft mit SELinux permissive, siehe docs/tablet-setup.md): Web-Kacheln dürfen ausschließlich ihren
 * eigenen Dienst am PC ansprechen (http://localhost:<port>, per adb reverse; Standard: der Hub 8765) -
 * jede andere Anfrage (auch iframes, POST, Unterressourcen) wird in shouldInterceptRequest blockiert.
 * Kacheln enthalten nur Port und Pfad, die URL baut die App selbst. Die JS-Schnittstelle "Deck" bekommt
 * nur die unsichtbare Steuerseite /ctl.html. Fremde Webseiten zeigt nur die Web-Kachel (BrowserPane).
 */
public class HomeActivity extends Activity {
    static final String TAG = "TabletDeck";
    static final String CTL_PATH = "/ctl.html";
    static final int HUB_PORT = 8765;
    static final Pattern PATH_OK = Pattern.compile("^/[A-Za-z0-9/._-]*(\\?[A-Za-z0-9=&._-]*)?$");
    // Farben wie web/lib/tokens.css ("Clean Dark")
    static final int BG = 0xFF0E1114, PANEL = 0xFF161A1F, S2 = 0xFF1E242B, LINE = 0xFF2B343E, TEXT = 0xFFE8ECF0,
            ACCENT = 0xFF4FB3FF, DIM = 0xFF9AA6B2, OK = 0xFF3DDC84, BAD = 0xFFE5484D;

    static HomeActivity current;   // für den PairingReceiver
    final Handler ui = new Handler(Looper.getMainLooper());
    final Map<String, WebView> webViews = new LinkedHashMap<>();
    final List<Tile> tiles = new ArrayList<>();
    FrameLayout content;
    LinearLayout bar, root, railTiles;
    View railEdge;
    MapPane maps;
    String mapsData;   // letzte Karten-Daten vom Hub (für eine später erzeugte MapPane)
    View statusDot;
    boolean everConnected, autoOffArmed;
    /** Begleit-Modus (ohne Root): normale App statt Startbildschirm, kein Ausschalten, schließt sich ohne PC. */
    boolean companion;
    static final long NO_HUB_MS = 60_000, NO_HUB_WARN_S = 10;
    View noHubBanner;
    TextView noHubText;
    boolean noHubPending;
    int noHubLeft;
    final Runnable ctlWatchdog = this::checkCtl;
    int ctlReloads, ctlKills;   // Neuladeversuche / Renderer-Beendigungen seit der letzten Verbindung

    void checkCtl() {
        if (!connected && ctlView != null && !isDestroyed()) {
            // Hub antwortet, Steuerseite bleibt trotzdem getrennt: WebView-Renderer hängt (z. B. nach Tagen
            // Laufzeit mit vollem Speicher) - Neuladen hilft dann nicht, Renderer beenden; onRenderProcessGone
            // baut die WebViews neu auf
            boolean hubUp = link != null
                    && android.os.SystemClock.elapsedRealtime() - link.hubSeen < 10_000;
            android.webkit.WebViewRenderProcess rp = ctlView.getWebViewRenderProcess();
            // höchstens 2-mal je Ausfall: bleibt die Seite aus anderem Grund getrennt (WebSocket abgelehnt), sonst
            // alle 60 s Panel, Karten und Web-Kachel mitgerissen (gemeinsamer Renderer)
            if (hubUp && rp != null && ctlKills < 2 && ++ctlReloads >= 3) {
                ctlReloads = 0;
                ctlKills++;
                Log.w(TAG, "Steuerseite trotz erreichbarem Hub getrennt - Renderer wird beendet");
                if (rp.terminate()) {
                    // onRenderProcessGone -> createCtlView() zieht den Watchdog neu auf; falls der Rückruf
                    // ausbleibt, läuft die Kette trotzdem weiter
                    ui.postDelayed(ctlWatchdog, 20000);
                    return;
                }
            }
            Log.w(TAG, "Steuerseite seit 20 s getrennt - lade neu (Hub " + (hubUp ? "erreichbar" : "weg")
                    + ", Versuch " + ctlReloads + ", Renderer " + (rp != null) + ")");
            ctlView.reload();
            ui.postDelayed(ctlWatchdog, 20000);
        }
    }
    TextView statusText;
    WebView ctlView;
    String mode;
    boolean launchedExternal;
    volatile boolean connected;
    BrowserPane browser;
    HubLink link;   // USB oder WLAN (Basisadresse des Hubs)
    boolean hubTilesSeen;   // erste Kacheln vom Hub: Startkachel anzeigen (statt der eingebauten Standards)

    static class Tile {
        String id, title, type, path, pkg, icon;
        int port;
        boolean start;

        /**
         * null, wenn ungültig. Web-Kacheln: Port eines Dienstes am PC (Standard Hub) und Pfad, keine
         * vollständige URL. browser: Web-Kachel für fremde Seiten. start: beim Start angezeigt.
         */
        static Tile of(JSONObject o) {
            Tile t = new Tile();
            t.id = o.optString("id");
            t.title = o.optString("title", t.id);
            t.type = o.optString("type", "web");
            t.path = o.optString("path", "");
            t.pkg = o.optString("pkg", "");
            t.icon = o.optString("icon", "");
            t.port = o.optInt("port", HUB_PORT);
            t.start = o.optBoolean("start", false);
            if (t.id.isEmpty()) return null;
            if (t.type.equals("web"))
                return PATH_OK.matcher(t.path).matches() && !t.path.contains("..") && t.port >= 1024
                        && t.port <= 65535 ? t : null;
            if (t.type.equals("app")) return t.pkg.matches("[A-Za-z0-9_.]+") ? t : null;
            if (t.type.equals("browser") || t.type.equals("maps")) return t;
            return null;
        }

        /**
         * Hub-Kacheln über den aktuellen Weg (USB/WLAN). Andere PC-Dienste (z. B. MoBro-Dashboard): per USB
         * über adb reverse (localhost), im WLAN direkt über die LAN-Adresse des PCs - unverschlüsselt, nur
         * Anzeige; das Kopplungs-Cookie ist im WLAN "Secure" und geht nie über diese http-Verbindung.
         */
        String url(String hub) {
            if (port == HUB_PORT) return hub + path;
            return "http://" + serviceHost(hub) + ":" + port + path;
        }
    }

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        // FLAG_KEEP_SCREEN_ON nur, solange der PC verbunden ist (setStatus). Am USB-Strom hält zusätzlich
        // "svc power stayon true" (Bridge) den Bildschirm an.
        // Panel soll ohne Entsperren bedienbar sein (Sperrbildschirm ist per locksettings ohnehin aus)
        setShowWhenLocked(true);
        // Kein setTurnScreenOn: Die Bridge legt das Tablet beim Herunterfahren des PCs schlafen - ein
        // turnScreenOn-Fenster würde es beim nächsten Sichtbarwerden sofort wieder wecken. Aufwecken
        // übernimmt die Bridge beim Verbinden (KEYCODE_WAKEUP).
        getSystemService(KeyguardManager.class).requestDismissKeyguard(this, null);

        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.HORIZONTAL);
        root.setBackgroundColor(BG);
        // Leiste links (Modi), rechts der Inhalt
        bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.VERTICAL);
        bar.setBackgroundColor(PANEL);
        bar.setPadding(dp(8), dp(14), dp(8), dp(12));
        root.addView(bar, new LinearLayout.LayoutParams(dp(96), -1));
        railEdge = new View(this);
        railEdge.setBackgroundColor(LINE);
        root.addView(railEdge, new LinearLayout.LayoutParams(1, -1));
        content = new FrameLayout(this);
        root.addView(content, new LinearLayout.LayoutParams(0, -1, 1f));
        setContentView(root);

        current = this;
        companion = getSharedPreferences("deck", MODE_PRIVATE).getBoolean("companion", false);
        applyTabletMode();
        // Wecker eines früheren Launcher-Prozesses verwerfen (sonst ginge das Tablet aus, bevor die
        // Verbindung wieder steht)
        AutoOffReceiver.disarm(this);
        link = new HubLink(this, new HubLink.Listener() {
            @Override
            public void onSwitch(String base) {
                ui.post(() -> onHubSwitch(base));
            }

            @Override
            public boolean isConnected() {
                return connected;
            }
        });
        setTiles(defaultTiles(), false);
        hideSystemBars();
        // Steuerseite erst laden, wenn das Kopplungs-Cookie sicher gesetzt ist
        applySecret(this::createCtlView);
        link.start();
        // Liegengebliebene Schlaf-/Aus-Anfrage (hardening war nicht aktiv) nicht nach dem Start ausführen
        new java.io.File(getFilesDir(), "power_request").delete();
    }

    /**
     * Schlafen/Ausschalten auf Wunsch des PCs (WLAN-Betrieb). Der Launcher hat dafür keine Rechte und
     * bekommt auch kein Root: Er legt nur eine Anfrage in seinem privaten Ordner ab, das Root-Modul
     * hardening führt sie aus (prüft alle 2 s, nur "sleep", "shutdown" oder "wake").
     */
    void requestPower(String action) {
        if (companion) {
            Log.i(TAG, "Begleit-Modus: Power-Anfrage '" + action + "' ohne Wirkung (kein Root)");
            return;
        }
        if (!"sleep".equals(action) && !"shutdown".equals(action) && !"wake".equals(action)) return;
        if (!"wake".equals(action)) getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        try (java.io.FileOutputStream f = new java.io.FileOutputStream(new java.io.File(getFilesDir(), "power_request"))) {
            f.write(action.getBytes("UTF-8"));
        } catch (java.io.IOException e) {
            Log.w(TAG, "Power-Anfrage nicht ablegbar: " + e);
        }
    }

    String hub() {
        return link == null ? HubLink.USB : link.base();
    }

    /** Weg zum Hub gewechselt (USB <-> WLAN): Cookie für den neuen Weg, Steuerseite und Hub-Seiten neu laden. */
    int switchGen;   // verwirft Rückrufe veralteter Wechsel (schnelles Hin und Her)

    void onHubSwitch(String base) {
        if (isDestroyed() || current != this) return;
        int gen = ++switchGen;
        applySecret(() -> {
            if (isDestroyed() || gen != switchGen) return;
            if (ctlView != null) {
                root.removeView(ctlView);
                ctlView.destroy();
                ctlView = null;
            }
            createCtlView();
            for (String id : new ArrayList<>(webViews.keySet())) removeWebView(id);   // alle: neue Adressen
            if (browser != null) browser.hubChanged();
            Tile cur = mode == null ? null : find(mode);
            if (cur != null && cur.type.equals("web")) showWeb(cur);
            setStatus(connected);
        });
    }

    /** Vom PairingReceiver: neues Geheimnis -> Cookie setzen und alle Verbindungen neu aufbauen. */
    void onPaired() {
        applySecret(() -> {
            if (ctlView != null) ctlView.reload();
            reloadAll();
        });
    }

    /**
     * Kopplung mit dem Hub: Das Geheimnis kommt per ADB über den PairingReceiver (nur ADB-Shell darf ihn
     * aufrufen) und liegt in den App-Einstellungen. Hier wird es als HttpOnly-Cookie für den Hub gesetzt -
     * der Hub nimmt /ws und /ctl nur damit an; Seiten-Skripte können es nicht lesen.
     * then: läuft, sobald das Cookie gesetzt ist (oder sofort, wenn noch keine Kopplung besteht).
     */
    void applySecret(Runnable then) {
        String secret = getSharedPreferences("deck", MODE_PRIVATE).getString("secret", null);
        if (secret == null) {
            then.run();
            return;
        }
        android.webkit.CookieManager cm = android.webkit.CookieManager.getInstance();
        String base = hub();
        // Über WLAN nur mit Secure (geht ausschließlich über TLS)
        String attrs = base.startsWith("https:") ? "; Path=/; Secure; HttpOnly; SameSite=Strict"
                : "; Path=/; HttpOnly; SameSite=Strict";
        cm.setCookie(base, "deck=" + secret + attrs, ok -> {
            cm.flush();
            then.run();
        });
    }

    static String defaultTiles() {
        return "[{\"id\":\"panel\",\"title\":\"Panel\",\"type\":\"web\",\"path\":\"/\"}," +
                "{\"id\":\"settings\",\"title\":\"Android\",\"type\":\"app\",\"pkg\":\"com.android.settings\"}]";
    }

    /** Unsichtbare Steuerseite: hält den WebSocket /ctl zum Hub und ruft die JS-Schnittstelle auf. */
    @SuppressLint("AddJavascriptInterface")
    void createCtlView() {
        ctlView = newHubWebView(CTL_PATH, HUB_PORT);
        ctlView.addJavascriptInterface(new DeckJs(this), "Deck");
        root.addView(ctlView, new LinearLayout.LayoutParams(1, 1));
        ctlView.loadUrl(hub() + CTL_PATH);
        // Watchdog auch beim ersten Laden (fehlt ctl.js, meldet niemand "getrennt")
        ui.removeCallbacks(ctlWatchdog);
        if (!connected) ui.postDelayed(ctlWatchdog, 20000);
    }

    // ------------------------------------------------------------------ Kacheln / Modi

    /** Kacheln neu setzen (JSON-Array). Startet nie eine App; vorhandene WebViews bleiben erhalten. */
    void setTiles(String json, boolean fromHub) {
        List<Tile> next = new ArrayList<>();
        try {
            JSONArray a = new JSONArray(json);
            for (int i = 0; i < a.length(); i++) {
                Tile t = Tile.of(a.getJSONObject(i));
                if (t == null) Log.w(TAG, "Kachel ungültig, ignoriert: " + a.get(i));
                else next.add(t);
            }
        } catch (Exception e) {
            Log.e(TAG, "Kacheln ungültig", e);
            return;
        }
        Tile firstWeb = null;
        for (Tile t : next) if (t.type.equals("web") && t.start) { firstWeb = t; break; }
        if (firstWeb == null) for (Tile t : next) if (t.type.equals("web")) { firstWeb = t; break; }
        if (firstWeb == null) return;   // ohne Web-Kachel bliebe der Bildschirm leer
        tiles.clear();
        tiles.addAll(next);
        // Ports weiterer PC-Dienste merken: die Tablet-Firewall (hardening) gibt sie im WLAN zum Hub frei.
        // Nur mit den Kacheln vom Hub (die eingebauten Standards beim Start hätten die Freigabe kurz entfernt).
        if (fromHub) {
            StringBuilder ports = new StringBuilder();
            for (Tile t : next)
                if (t.type.equals("web") && t.port != HUB_PORT) ports.append(ports.length() > 0 ? "," : "").append(t.port);
            getSharedPreferences("deck", MODE_PRIVATE).edit().putString("wlan_service_ports", ports.toString()).apply();
        }
        for (String id : new ArrayList<>(webViews.keySet())) {
            Tile t = find(id);
            if (t == null || !t.type.equals("web")) removeWebView(id);
        }
        buildBar();
        Tile cur = mode == null || !hubTilesSeen && fromHub ? null : find(mode);
        if (fromHub) hubTilesSeen = true;
        if (cur != null && cur.type.equals("browser")) showBrowser(cur);
        else if (cur != null && cur.type.equals("maps")) showMaps(cur);
        else showWeb(cur != null && cur.type.equals("web") ? cur : firstWeb);
        if (find("maps") == null && maps != null) {
            maps.leave();
            content.removeView(maps);
            maps.destroy();
            maps = null;
        }
        if (browserTile() == null && browser != null) {
            content.removeView(browser);
            browser.destroy();
            browser = null;
        }
    }

    Tile find(String id) {
        for (Tile t : tiles) if (t.id.equals(id)) return t;
        return null;
    }

    /** Ein Hintergrund-Thread für alle Cookie-Sicherungen; überlappende Aufrufe fallen zusammen. */
    private static final java.util.concurrent.ExecutorService COOKIE_IO =
            java.util.concurrent.Executors.newSingleThreadExecutor();
    private static final java.util.concurrent.atomic.AtomicBoolean cookiePending =
            new java.util.concurrent.atomic.AtomicBoolean();

    /** Cookies im Hintergrund sichern (flush blockiert und schreibt auf den langsamen Speicher). */
    static void flushCookies() {
        if (!cookiePending.compareAndSet(false, true)) return;
        COOKIE_IO.execute(() -> {
            cookiePending.set(false);
            try {
                android.webkit.CookieManager.getInstance().flush();
            } catch (RuntimeException e) {
                Log.w(TAG, "Cookies nicht gesichert: " + e);
            }
        });
    }

    /** Kachel aktivieren: Web-Kachel anzeigen oder App starten. */
    void setMode(String id) {
        Tile t = find(id);
        if (t == null) return;
        flushCookies();   // Logins (z. B. Map Genie) sofort sichern
        if (t.type.equals("app")) launchApp(t);
        else if (t.type.equals("browser")) showBrowser(t);
        else if (t.type.equals("maps")) showMaps(t);
        else showWeb(t);
    }

    /** Karten-Kachel: eigene Ansicht, bleibt beim Wechsel erhalten (Position auf der Karte). */
    void showMaps(Tile t) {
        if (maps == null) {
            maps = new MapPane(this);
            content.addView(maps, new FrameLayout.LayoutParams(-1, -1));
            if (mapsData != null) maps.setData(mapsData);
        }
        for (WebView w : webViews.values()) w.setVisibility(View.GONE);
        if (browser != null) browser.setVisibility(View.GONE);
        maps.setVisibility(View.VISIBLE);
        maps.onShown();
        mode = t.id;
        updateBar();
        ui.post(this::report);
    }

    void setMaps(String json) {
        mapsData = json;
        if (maps != null) maps.setData(json);
    }

    /** Leiste links ein-/ausblenden (Vollbild der Karte). */
    void setRailVisible(boolean on) {
        bar.setVisibility(on ? View.VISIBLE : View.GONE);
        railEdge.setVisibility(on ? View.VISIBLE : View.GONE);
    }

    void hideMaps() {
        if (maps == null) return;
        maps.leave();
        maps.setVisibility(View.GONE);
    }

    Tile browserTile() {
        for (Tile t : tiles) if (t.type.equals("browser")) return t;
        return null;
    }

    void showBrowser(Tile t) {
        if (browser == null) {
            browser = new BrowserPane(this);
            content.addView(browser, new FrameLayout.LayoutParams(-1, -1));
        }
        for (WebView w : webViews.values()) w.setVisibility(View.GONE);
        hideMaps();
        browser.setVisibility(View.VISIBLE);
        mode = t.id;
        updateBar();
        ui.post(this::report);
    }

    /** Vom PC geschickte Webseite: Web-Kachel zeigen (Launcher ggf. nach vorn holen) und laden. */
    void openUrl(String url) {
        Tile t = browserTile();
        if (t == null || url == null) return;
        showBrowser(t);
        browser.load(url);
        if (launchedExternal)
            startActivity(new Intent(this, HomeActivity.class).addFlags(
                    Intent.FLAG_ACTIVITY_REORDER_TO_FRONT | Intent.FLAG_ACTIVITY_NEW_TASK));
    }

    void showWeb(Tile t) {
        WebView w = webViews.get(t.id);
        if (w == null || !t.url(hub()).equals(w.getTag())) {
            if (w != null) removeWebView(t.id);
            w = newHubWebView(null, t.port);
            w.setTag(t.url(hub()));
            webViews.put(t.id, w);
            content.addView(w, new FrameLayout.LayoutParams(-1, -1));
            w.loadUrl(t.url(hub()));
        }
        for (Map.Entry<String, WebView> e : webViews.entrySet())
            e.getValue().setVisibility(e.getKey().equals(t.id) ? View.VISIBLE : View.GONE);
        if (browser != null) browser.setVisibility(View.GONE);
        hideMaps();
        mode = t.id;
        updateBar();
        // verzögert: nach einem Renderer-Absturz erst die übrigen Callbacks laufen lassen (tote ctlView)
        ui.post(this::report);
    }

    void removeWebView(String id) {
        WebView w = webViews.remove(id);
        if (w == null) return;
        content.removeView(w);
        w.destroy();
    }

    void launchApp(Tile t) {
        Intent i = getPackageManager().getLaunchIntentForPackage(t.pkg);
        if (i == null) {
            Log.w(TAG, "App nicht installiert: " + t.pkg);
            return;
        }
        launchedExternal = true;
        if (maps != null && maps.full) maps.setFull(false);   // Leiste nach der Rückkehr wieder da
        startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        // Hub informieren: Ansicht verlassen -> er gibt gehaltene Tasten/Maustasten frei
        reportState("app:" + t.id);
    }

    /** "app:<id>"/"app:extern", solange eine andere App vorn ist - auch nach einem Neuverbinden melden. */
    volatile String appState;

    void reportState(String state) {
        appState = state.startsWith("app:") ? state : null;
        if (ctlView != null)
            ctlView.evaluateJavascript("window.deckState && deckState(" + JSONObject.quote(state) + ")", null);
    }

    /** Web-Kachel hat eine Seite geladen: an den Hub (Verlauf auf der Startseite). */
    void reportVisited(String url, String title) {
        if (ctlView == null) return;
        ctlView.evaluateJavascript("window.deckVisited&&deckVisited(" + org.json.JSONObject.quote(url) + ","
                + org.json.JSONObject.quote(title == null ? "" : title) + ")", null);
    }

    void reloadAll() {
        for (WebView w : webViews.values()) w.reload();
        if (maps != null && maps.browser.web != null) maps.browser.web.reload();
    }

    /** Aktuellen Zustand an den Hub melden (über die Steuerseite). */
    void report() {
        if (mode != null) reportState(mode);
    }

    void setStatus(boolean ok) {
        connected = ok;
        // Bildschirm an, solange der PC verbunden ist (unabhängig von stayon/Ladezustand); ohne PC
        // (heruntergefahren, Bridge beendet) greift die normale Zeitsperre.
        // Steuerseite hängt (z. B. halb geladen): nach 20 s ohne Verbindung neu laden
        // ctl.js meldet "getrennt" bei jedem gescheiterten Versuch (jede Sekunde) - Watchdog nicht jedes Mal
        // neu aufziehen, sonst feuert er nie
        if (ok) ui.removeCallbacks(ctlWatchdog);
        else if (!ui.hasCallbacks(ctlWatchdog)) ui.postDelayed(ctlWatchdog, 20000);
        // Rückfall-Abschaltung: erst scharf, wenn seit dem Start schon einmal verbunden
        if (ok) {
            ctlReloads = 0;
            ctlKills = 0;
            everConnected = true;
            AutoOffReceiver.disarm(this);
        } else if (everConnected && !autoOffArmed && !companion) {
            AutoOffReceiver.arm(this);
        }
        autoOffArmed = !ok && everConnected && !companion;
        updateNoHub();
        if (ok) getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        if (statusDot == null) return;
        GradientDrawable d = new GradientDrawable();
        d.setShape(GradientDrawable.OVAL);
        // grün = USB, blau = WLAN, rot = getrennt
        int c = !ok ? BAD : link != null && link.isWlan() ? ACCENT : OK;
        d.setColor(c);
        statusDot.setBackground(d);
        if (statusText != null) statusText.setText(!ok ? "getrennt" : link != null && link.isWlan() ? "WLAN" : "USB");
    }

    // ------------------------------------------------------------------ Oberfläche

    /** Icon je Kachel: Feld "icon" aus launcher.json, sonst nach id; unbekannt = Raster. */
    static int iconFor(Tile t) {
        String k = t.icon.isEmpty() ? t.id : t.icon;
        switch (k) {
            case "screen": case "monitor": return R.drawable.ic_monitor;
            case "web": case "globe": return R.drawable.ic_globe;
            case "touchpad": return R.drawable.ic_touchpad;
            case "maps": case "map": return R.drawable.ic_map;
            case "pcstats": case "activity": return R.drawable.ic_activity;
            case "settings": return R.drawable.ic_settings;
            default: return R.drawable.ic_grid;
        }
    }

    void buildBar() {
        bar.removeAllViews();
        // Kacheln scrollbar (viele Kacheln), Verbindungsanzeige bleibt unten sichtbar
        android.widget.ScrollView sv = new android.widget.ScrollView(this);
        sv.setVerticalScrollBarEnabled(false);
        railTiles = new LinearLayout(this);
        railTiles.setOrientation(LinearLayout.VERTICAL);
        sv.addView(railTiles, new FrameLayout.LayoutParams(-1, -2));
        bar.addView(sv, new LinearLayout.LayoutParams(-1, 0, 1f));
        for (Tile t : tiles) {
            LinearLayout b = new LinearLayout(this);
            b.setOrientation(LinearLayout.VERTICAL);
            b.setGravity(Gravity.CENTER);
            b.setTag(t.id);
            b.setContentDescription(t.title);
            android.widget.ImageView ic = new android.widget.ImageView(this);
            ic.setImageResource(iconFor(t));
            b.addView(ic, new LinearLayout.LayoutParams(dp(24), dp(24)));
            TextView l = new TextView(this);
            l.setText(t.title);
            l.setGravity(Gravity.CENTER);
            l.setSingleLine(true);
            l.setEllipsize(android.text.TextUtils.TruncateAt.END);
            l.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
            l.setTypeface(android.graphics.Typeface.create("sans-serif-medium", android.graphics.Typeface.NORMAL));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
            lp.topMargin = dp(5);
            b.addView(l, lp);
            b.setOnClickListener(v -> setMode(t.id));
            LinearLayout.LayoutParams bp = new LinearLayout.LayoutParams(-1, dp(68));
            bp.bottomMargin = dp(4);
            railTiles.addView(b, bp);
        }
        LinearLayout st = new LinearLayout(this);
        st.setOrientation(LinearLayout.VERTICAL);
        st.setGravity(Gravity.CENTER);
        statusDot = new View(this);
        st.addView(statusDot, new LinearLayout.LayoutParams(dp(10), dp(10)));
        statusText = new TextView(this);
        statusText.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
        statusText.setTextColor(DIM);
        statusText.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(-2, -2);
        sp.topMargin = dp(6);
        st.addView(statusText, sp);
        LinearLayout.LayoutParams stp = new LinearLayout.LayoutParams(-1, -2);
        stp.topMargin = dp(8);
        bar.addView(st, stp);
        setStatus(connected);
        updateBar();
    }

    void updateBar() {
        if (railTiles == null) return;
        for (int i = 0; i < railTiles.getChildCount(); i++) {
            View v = railTiles.getChildAt(i);
            if (v.getTag() == null) continue;
            boolean on = v.getTag().equals(mode);
            int c = on ? ACCENT : DIM;
            LinearLayout b = (LinearLayout) v;
            ((android.widget.ImageView) b.getChildAt(0)).setImageTintList(android.content.res.ColorStateList.valueOf(c));
            ((TextView) b.getChildAt(1)).setTextColor(on ? TEXT : DIM);
            if (on) {
                GradientDrawable bg = new GradientDrawable();
                bg.setColor(S2);
                bg.setCornerRadius(dp(14));
                bg.setStroke(1, LINE);
                v.setBackground(bg);
            } else {
                v.setBackground(null);
            }
        }
    }

    /**
     * WebView, die nur einen Dienst am PC erreicht (localhost:port). onlyPath != null: nur genau dieser Pfad als Seite
     * (Steuerseite). Gibt der Renderer auf (Absturz/Speichermangel), wird die WebView ersetzt statt dass
     * Android den ganzen Launcher beendet.
     */
    @SuppressLint("SetJavaScriptEnabled")
    WebView newHubWebView(String onlyPath, int port) {
        WebView w = new WebView(this);
        w.setBackgroundColor(BG);
        WebSettings s = w.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setSupportZoom(false);
        s.setSupportMultipleWindows(false);
        s.setUserAgentString(s.getUserAgentString() + " TabletDeck/0.1");
        w.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if (allowed(u, port) && (onlyPath == null || onlyPath.equals(u.getPath()))) return false;
                Log.w(TAG, "Navigation blockiert: " + u);
                return true;
            }

            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
                if (allowed(req.getUrl(), port)) return null;   // normal laden
                Log.w(TAG, "Anfrage blockiert: " + req.getUrl());
                return new WebResourceResponse("text/plain", "utf-8", 403, "Forbidden",
                        null, new ByteArrayInputStream(new byte[0]));
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (!req.isForMainFrame()) {
                    // Skript/Stylesheet fehlt (z. B. USB meldet sich gerade neu an): Seite wäre halb geladen,
                    // die Steuerseite ohne ctl.js sogar dauerhaft getrennt - ganze Seite gleich neu laden
                    // nur Skripte/Stylesheets - fehlgeschlagene Datenabfragen (fetch) regeln die Seiten selbst
                    String path = req.getUrl().getPath() == null ? "" : req.getUrl().getPath();
                    if ((path.endsWith(".js") || path.endsWith(".css")) && allowed(req.getUrl(), port)
                            && view.getTag(R.id.retry_pending) == null) {
                        view.setTag(R.id.retry_pending, Boolean.TRUE);
                        ui.postDelayed(() -> {
                            view.setTag(R.id.retry_pending, null);
                            if (view == ctlView || webViews.containsValue(view)) view.reload();
                        }, 2000);
                    }
                    return;
                }
                // Hub (noch) nicht erreichbar, z. B. Bridge aus oder Kabel ab: in 2 s erneut versuchen
                Uri u = req.getUrl();
                ui.postDelayed(() -> {
                    boolean home = browser != null && view == browser.home;   // Startseite der Web-Kachel
                    if ((view == ctlView || webViews.containsValue(view) || home) && allowed(u, port))
                        view.loadUrl(u.toString());
                }, 2000);
            }

            @Override
            public void onReceivedSslError(WebView view, android.webkit.SslErrorHandler handler,
                                           android.net.http.SslError error) {
                // Die APK kennt die CA des Hubs nicht (eine APK für alle PCs). Nur für die WLAN-Adresse des Hubs
                // selbst prüfen (HubTrust: Kette bis zur per ADB übertragenen Wurzel, IP im Zertifikat);
                // alles andere bleibt abgelehnt.
                Uri u = Uri.parse(error.getUrl());
                if (link != null && "https".equals(u.getScheme()) && link.isHubAddress(u.getHost(), u.getPort())
                        && HubTrust.verify(HomeActivity.this, error.getCertificate(), u.getHost())) {
                    handler.proceed();
                } else {
                    Log.w(TAG, "TLS-Fehler, abgelehnt: " + u.getHost());
                    handler.cancel();
                }
            }

            @Override
            public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
                Log.e(TAG, "WebView-Renderer beendet (Absturz=" + detail.didCrash() + "), wird ersetzt");
                if (view == ctlView) {
                    root.removeView(ctlView);
                    ctlView.destroy();
                    createCtlView();
                } else if (browser != null && view == browser.home) {
                    browser.homeGone();
                } else {
                    for (Map.Entry<String, WebView> e : new ArrayList<>(webViews.entrySet())) {
                        if (e.getValue() != view) continue;
                        removeWebView(e.getKey());
                        Tile t = find(e.getKey());
                        if (t != null && e.getKey().equals(mode)) showWeb(t);
                    }
                }
                return true;
            }
        });
        return w;
    }

    /** Host weiterer PC-Dienste: localhost (USB) oder die LAN-Adresse des Hubs (WLAN). */
    static String serviceHost(String hub) {
        return hub.startsWith("https:") ? Uri.parse(hub).getHost() : "localhost";
    }

    /** Hub (Port 8765): genau der aktuelle Weg (USB-localhost oder WLAN-Adresse), sonst der PC-Dienst. */
    boolean allowed(Uri u, int port) {
        if (port != HUB_PORT)
            return u != null && "http".equals(u.getScheme()) && serviceHost(hub()).equals(u.getHost())
                    && u.getPort() == port && u.getUserInfo() == null;
        Uri b = Uri.parse(hub());
        return u != null && b.getScheme().equals(u.getScheme()) && b.getHost().equals(u.getHost())
                && b.getPort() == u.getPort() && u.getUserInfo() == null;
    }

    /** Genau dieser Dienst: http, Host localhost, Port. Uri kommt hier bereits von Chromium normalisiert. */
    static boolean isLocal(Uri u, int port) {
        return u != null && "http".equals(u.getScheme()) && "localhost".equals(u.getHost()) && u.getPort() == port
                && u.getUserInfo() == null;
    }

    void hideSystemBars() {
        WindowInsetsController c = getWindow().getInsetsController();
        if (c == null) return;
        c.hide(WindowInsets.Type.systemBars());
        c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
    }

    int dp(int v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics());
    }

    // ------------------------------------------------------------------ Lebenszyklus

    /** Vom Hub über den Steuerkanal (config tablet_mode): "home" (Startbildschirm) oder "companion". Gilt nur,
     *  solange der Hub die Betriebsart nicht per ADB für genau dieses Tablet festgelegt hat (mode_pinned). */
    void setTabletMode(String m) {
        boolean c = "companion".equals(m);
        if (!c && !"home".equals(m)) return;
        if (getSharedPreferences("deck", MODE_PRIVATE).getBoolean("mode_pinned", false)) return;
        getSharedPreferences("deck", MODE_PRIVATE).edit().putBoolean("companion", c).apply();
        applyTabletModeFromPrefs();
    }

    /** Betriebsart aus den Einstellungen anwenden (nach setTabletMode oder dem PairingReceiver). */
    void applyTabletModeFromPrefs() {
        companion = getSharedPreferences("deck", MODE_PRIVATE).getBoolean("companion", false);
        applyTabletMode();
        setStatus(connected);
    }

    /**
     * Begleit-Modus: HOME-Alias abschalten (Android fragt dann nicht mehr nach dem Startbildschirm), kein
     * Rücksprung-Griff, kein Rückfall-Wecker. Startbildschirm-Modus: Alias wieder an.
     */
    void applyTabletMode() {
        try {
            getPackageManager().setComponentEnabledSetting(
                    new android.content.ComponentName(this, "app.tabletdeck.launcher.HomeAlias"),
                    companion ? android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_DISABLED
                            : android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_ENABLED,
                    android.content.pm.PackageManager.DONT_KILL_APP);
        } catch (RuntimeException e) {
            Log.w(TAG, "HomeAlias nicht umschaltbar: " + e);
        }
        if (companion) {
            AutoOffReceiver.disarm(this);   // gestellten Wecker (und gemerktes stayon) löschen
            autoOffArmed = false;
            ui.removeCallbacks(showHandle);
            stopService(new Intent(this, OverlayService.class));
        } else {
            noHubOff();
        }
    }

    /** Begleit-Modus: 60 s ohne Hub-Verbindung -> Hinweis, 10 s später schließt sich die App. */
    void updateNoHub() {
        if (!companion || connected) {
            noHubOff();
            return;
        }
        if (!noHubPending && noHubBanner == null) {
            noHubPending = true;
            ui.postDelayed(noHubWarn, NO_HUB_MS);
        }
    }

    void noHubOff() {
        noHubPending = false;
        ui.removeCallbacks(noHubWarn);
        ui.removeCallbacks(noHubTick);
        if (noHubBanner != null && content != null) content.removeView(noHubBanner);
        noHubBanner = null;
    }

    final Runnable noHubWarn = () -> {
        noHubPending = false;
        if (!companion || connected || isDestroyed()) return;
        LinearLayout b = new LinearLayout(this);
        b.setOrientation(LinearLayout.VERTICAL);
        b.setGravity(Gravity.CENTER_HORIZONTAL);
        b.setPadding(dp(20), dp(16), dp(20), dp(16));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(S2);
        bg.setStroke(dp(1), BAD);
        bg.setCornerRadius(dp(14));
        b.setBackground(bg);
        noHubText = new TextView(this);
        noHubText.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        noHubText.setTextColor(TEXT);
        noHubText.setGravity(Gravity.CENTER);
        b.addView(noHubText, new LinearLayout.LayoutParams(-2, -2));
        TextView keep = new TextView(this);
        keep.setText("Offen lassen");
        keep.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        keep.setTextColor(BG);
        keep.setGravity(Gravity.CENTER);
        keep.setPadding(dp(24), dp(10), dp(24), dp(10));
        GradientDrawable kb = new GradientDrawable();
        kb.setColor(ACCENT);
        kb.setCornerRadius(dp(10));
        keep.setBackground(kb);
        keep.setOnClickListener(v -> {   // Zähler zurücksetzen
            noHubOff();
            updateNoHub();
        });
        LinearLayout.LayoutParams kp = new LinearLayout.LayoutParams(-2, -2);
        kp.topMargin = dp(12);
        b.addView(keep, kp);
        noHubBanner = b;
        content.addView(b, new FrameLayout.LayoutParams(-2, -2, Gravity.CENTER));
        noHubLeft = (int) NO_HUB_WARN_S;
        HomeActivity.this.noHubTick.run();
    };

    final Runnable noHubTick = new Runnable() {
        @Override
        public void run() {
            if (!companion || connected || isDestroyed() || noHubBanner == null) return;
            if (noHubLeft <= 0) {
                Log.i(TAG, "Begleit-Modus: keine Verbindung zum PC - App schließt sich");
                finishAndRemoveTask();
                return;
            }
            noHubText.setText("Keine Verbindung zum PC \u2013 die App schließt sich in " + noHubLeft + " s");
            noHubLeft--;
            ui.postDelayed(this, 1000);
        }
    };

    /** Vom Hub (config tablet_rotation): merken und sofort anwenden. */
    void setRotation(int r) {
        if (r < -1 || r > 3) return;
        getSharedPreferences("deck", MODE_PRIVATE).edit().putInt("rotation", r).apply();
        holdRotation();
    }

    /**
     * Feste Ausrichtung wiederherstellen. spacedesk schaltet beim Start die automatische Drehung mit
     * Hochformat ein (accelerometer_rotation=1, user_rotation=0); liegt das Tablet flach, bliebe es danach
     * im Hochformat, bis man es anhebt. Der Hub prüft das nur alle 30 s per adb - der Launcher sofort,
     * sobald er wieder vorn ist (auch im WLAN). Vorgabe 1 (Querformat), bis der Hub etwas anderes sagt.
     */
    void holdRotation() {
        int r = getSharedPreferences("deck", MODE_PRIVATE).getInt("rotation", 1);
        if (r < 0) return;
        android.content.ContentResolver cr = getContentResolver();
        try {
            int auto = android.provider.Settings.System.getInt(cr,
                    android.provider.Settings.System.ACCELEROMETER_ROTATION, 0);
            int user = android.provider.Settings.System.getInt(cr, android.provider.Settings.System.USER_ROTATION, 0);
            if (auto == 0 && user == r) return;
            android.provider.Settings.System.putInt(cr, android.provider.Settings.System.ACCELEROMETER_ROTATION, 0);
            android.provider.Settings.System.putInt(cr, android.provider.Settings.System.USER_ROTATION, r);
            Log.i(TAG, "Ausrichtung wiederhergestellt (auto=" + auto + ", user=" + user + " -> " + r + ")");
        } catch (SecurityException | IllegalArgumentException e) {
            // läuft bei jedem onResume/Fokuswechsel - nur einmal pro Prozess melden
            if (!rotationWarned) Log.w(TAG, "Ausrichtung nicht setzbar (WRITE_SETTINGS fehlt - setup-launcher.ps1): " + e);
            rotationWarned = true;
        }
    }

    static boolean rotationWarned;

    @Override
    protected void onResume() {
        super.onResume();
        hideSystemBars();
        holdRotation();
        paused = false;
        ui.removeCallbacks(showHandle);   // noch nicht gestarteten Griff verwerfen
        stopService(new Intent(this, OverlayService.class));
        appState = null;
        if (launchedExternal) report();   // zurück aus einer App: wieder die eigene Ansicht melden
        launchedExternal = false;
    }

    @Override
    protected void onPause() {
        super.onPause();
        // Cookies sofort sichern (auch Bildschirm aus): sonst schreibt WebView nur alle ~30 s, ein
        // Ausschalten des Tablets verliert dann frische Logins.
        android.webkit.CookieManager.getInstance().flush();
        // Andere App im Vordergrund - über die Kachel ODER von selbst (z. B. spacedesk beim Anstecken
        // per USB-Zubehör): Rücksprung-Griff einblenden und dem Hub melden, damit er gehaltene Tasten
        // freigibt. Die WebViews laufen bewusst weiter (WebSocket bleibt verbunden).
        if (!launchedExternal) reportState("app:extern");
        launchedExternal = true;   // onResume meldet dann wieder den eigenen Modus
        // Verzögert: Bei schnellem Pause/Resume (Systemdialog, kurz Bildschirm aus) würde ein gestarteter
        // Vordergrunddienst sonst gestoppt, bevor er startForeground ruft -> Absturz des Launchers.
        paused = true;
        ui.postDelayed(showHandle, 500);
        if (screenOnReceiver == null) {
            // Kam die fremde App bei ausgeschaltetem Bildschirm nach vorn (spacedesk beim Anstecken),
            // bricht showHandle ab - beim Einschalten nachholen, solange der Launcher pausiert ist.
            screenOnReceiver = new android.content.BroadcastReceiver() {
                @Override
                public void onReceive(android.content.Context c, Intent i) {
                    if (paused) ui.postDelayed(showHandle, 1000);   // länger: der Launcher selbst kommt sonst zuerst
                }
            };
            registerReceiver(screenOnReceiver, new android.content.IntentFilter(Intent.ACTION_SCREEN_ON),
                    RECEIVER_NOT_EXPORTED);
        }
    }

    boolean paused;
    android.content.BroadcastReceiver screenOnReceiver;

    final Runnable showHandle = () -> {
        boolean screenOn = getSystemService(android.os.PowerManager.class).isInteractive();
        if (companion || !screenOn || !android.provider.Settings.canDrawOverlays(this)) return;
        try {
            startForegroundService(new Intent(this, OverlayService.class));
        } catch (Exception e) {
            Log.w(TAG, "Overlay nicht startbar", e);
        }
    };

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            hideSystemBars();
            holdRotation();   // auch nach Dialogen/Overlays, die keinen onResume auslösen
        }
    }

    @Override
    @SuppressWarnings("MissingSuperCall")
    public void onBackPressed() {
        // Zurück-Taste ohne Wirkung: der Launcher ist der Startbildschirm
    }

    @Override
    protected void onDestroy() {
        if (current == this) current = null;
        if (link != null) link.stop();
        ui.removeCallbacksAndMessages(null);
        if (screenOnReceiver != null) unregisterReceiver(screenOnReceiver);
        for (String id : new ArrayList<>(webViews.keySet())) removeWebView(id);
        if (browser != null) browser.destroy();
        if (ctlView != null) {
            root.removeView(ctlView);
            ctlView.destroy();
            ctlView = null;
        }
        super.onDestroy();
    }
}
