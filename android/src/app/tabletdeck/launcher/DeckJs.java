package app.tabletdeck.launcher;

import android.webkit.JavascriptInterface;

/**
 * JS-Schnittstelle "Deck" - ausschließlich für die unsichtbare Steuerseite /ctl.html (HomeActivity.ctlView,
 * die nur genau diese Hub-Seite laden kann). Aufrufe kommen auf einem Binder-Thread an und werden auf den
 * UI-Thread umgeleitet.
 */
public class DeckJs {
    private final HomeActivity a;

    DeckJs(HomeActivity a) {
        this.a = a;
    }

    @JavascriptInterface
    public void setMode(String id) {
        a.ui.post(() -> a.setMode(id));
    }

    @JavascriptInterface
    public void setTiles(String json) {
        a.ui.post(() -> a.setTiles(json, true));
    }

    @JavascriptInterface
    public void setStatus(boolean ok) {
        a.ui.post(() -> a.setStatus(ok));
    }

    /** Spiele mit Kartenanbietern und laufendes Spiel (Hub: games.json, Spielerkennung). */
    @JavascriptInterface
    public void setMaps(String json) {
        a.ui.post(() -> a.setMaps(json));
    }

    /** Editor am PC: Karte eines Spiels in der Karten-Kachel zeigen (nur Karten aus der Liste des Hubs). */
    @JavascriptInterface
    public void showMap(String game, String url) {
        a.ui.post(() -> a.showMap(game, url));
    }

    @JavascriptInterface
    public void openUrl(String url) {
        a.ui.post(() -> a.openUrl(url));
    }

    /** Feste Ausrichtung (0..3 wie user_rotation, -1 = nicht anfassen), aus config.json des Hubs. */
    @JavascriptInterface
    public void setRotation(int r) {
        a.ui.post(() -> a.setRotation(r));
    }

    /** Betriebsart aus config.json des Hubs: "home" (Startbildschirm) oder "companion" (normale App). */
    @JavascriptInterface
    public void setTabletMode(String m) {
        a.ui.post(() -> a.setTabletMode(m));
    }

    /** WLAN-Adressen des Hubs (kommt nur über USB, siehe Bridge ctl_handler). */
    @JavascriptInterface
    public void setWlan(String json) {
        try {
            org.json.JSONObject o = new org.json.JSONObject(json);
            org.json.JSONArray a = o.getJSONArray("hosts");
            java.util.List<String> hosts = new java.util.ArrayList<>();
            for (int i = 0; i < a.length(); i++) hosts.add(a.getString(i));
            if (a.length() > 0) this.a.link.setHosts(hosts, o.getInt("port"));
        } catch (Exception e) {
            android.util.Log.w(HomeActivity.TAG, "WLAN-Adressen ungültig: " + e);
        }
    }

    /** PC fährt herunter / schläft (nur im WLAN, per USB erledigt das adb). */
    @JavascriptInterface
    public void power(String action) {
        a.ui.post(() -> a.requestPower(action));
    }

    @JavascriptInterface
    public void reload() {
        a.ui.post(a::reloadAll);
    }

    @JavascriptInterface
    public void home() {
        a.ui.post(() -> a.startActivity(new android.content.Intent(a, HomeActivity.class)
                .addFlags(android.content.Intent.FLAG_ACTIVITY_REORDER_TO_FRONT
                        | android.content.Intent.FLAG_ACTIVITY_NEW_TASK)));
    }

    @JavascriptInterface
    public String getMode() {
        String app = a.appState;   // andere App vorn (z. B. spacedesk) - auch nach Neuverbinden melden
        return app != null ? app : a.mode == null ? "" : a.mode;
    }
}
