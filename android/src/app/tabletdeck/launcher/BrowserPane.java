package app.tabletdeck.launcher;

import android.annotation.SuppressLint;
import android.content.Context;
import android.graphics.Bitmap;
import android.net.Uri;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.ByteArrayInputStream;

/**
 * Web-Kachel: fremde Webseiten (vom PC geschickt oder eingetippt). Bewusst getrennt von den Hub-WebViews:
 * keine JS-Schnittstelle, kein Datei-/Content-Zugriff, nur http(s), keine Adressen auf dem Tablet selbst
 * (localhost = Hub und andere lokale Dienste). Ins Internet geht es über den Proxy der Bridge (Android
 * http_proxy -> adb reverse -> PC), der zusätzlich alle privaten Netze sperrt.
 */
public class BrowserPane extends LinearLayout {
    static final String TAG = "TabletDeck";
    final HomeActivity a;
    final EditText address;
    WebView web;
    WebView home;          // Startseite (Hub-Seite /start/: Lesezeichen, gesendet, Verlauf) - nur mit chrome
    final boolean chrome;  // false = Karten-Kachel: keine Adresszeile, keine Startseite, kein Verlauf
    String pending;
    long lastGone;   // letzter Renderer-Absturz (elapsedRealtime)

    BrowserPane(HomeActivity a) {
        this(a, true);
    }

    /** chrome=false: ohne Adresszeile (Karten-Kachel bringt eigene Bedienung mit). */
    @SuppressLint("SetTextI18n")
    BrowserPane(HomeActivity a, boolean chrome) {
        super(a);
        this.a = a;
        this.chrome = chrome;
        // Service Worker fremder Seiten laufen nicht durch den WebViewClient - dieselbe Sperre setzen.
        // (Die Hub-Seiten nutzen keine Service Worker.)
        android.webkit.ServiceWorkerController.getInstance().setServiceWorkerClient(
                new android.webkit.ServiceWorkerClient() {
                    @Override
                    public WebResourceResponse shouldInterceptRequest(WebResourceRequest req) {
                        return allowed(req.getUrl()) ? null : new WebResourceResponse("text/plain", "utf-8",
                                403, "Forbidden", null, new ByteArrayInputStream(new byte[0]));
                    }
                });
        setOrientation(VERTICAL);
        setBackgroundColor(HomeActivity.BG);

        LinearLayout bar = new LinearLayout(a);
        bar.setOrientation(HORIZONTAL);
        bar.setBackgroundColor(HomeActivity.PANEL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.addView(button("‹", v -> { if (!homeShown() && web != null && web.canGoBack()) web.goBack(); }),
                new LayoutParams(a.dp(56), -1));
        bar.addView(button("⟳", v -> reloadFromBar()), new LayoutParams(a.dp(56), -1));
        bar.addView(button("⌂", v -> showHome()), new LayoutParams(a.dp(56), -1));
        address = new EditText(a);
        address.setSingleLine(true);
        address.setHint("Adresse eingeben oder vom PC senden");
        address.setTextColor(0xFFE6E9EC);
        address.setHintTextColor(HomeActivity.DIM);
        address.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        address.setInputType(android.text.InputType.TYPE_TEXT_VARIATION_URI);
        address.setImeOptions(EditorInfo.IME_ACTION_GO);
        address.setSelectAllOnFocus(true);
        address.setOnEditorActionListener((v, id, ev) -> {
            if (id == EditorInfo.IME_ACTION_GO || (ev != null && ev.getKeyCode() == KeyEvent.KEYCODE_ENTER)) {
                String t = address.getText().toString().trim();
                if (!t.matches("(?i)^https?://.*")) t = "https://" + t;
                load(t);
                a.getSystemService(InputMethodManager.class).hideSoftInputFromWindow(address.getWindowToken(), 0);
                return true;
            }
            return false;
        });
        bar.addView(address, new LayoutParams(0, -1, 1f));
        bar.addView(button("✕", v -> clear()), new LayoutParams(a.dp(56), -1));
        if (chrome) addView(bar, new LayoutParams(-1, a.dp(48)));
        createWeb();
        if (chrome) showHome();
    }

    TextView button(String label, View.OnClickListener l) {
        TextView b = new TextView(a);
        b.setText(label);
        b.setGravity(Gravity.CENTER);
        b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        b.setTextColor(HomeActivity.ACCENT);
        b.setOnClickListener(l);
        return b;
    }

    /** Nur http(s), keine Ziele auf dem Tablet selbst. */
    static boolean allowed(Uri u) {
        if (u == null) return false;
        String s = u.getScheme(), h = u.getHost();
        if (!"http".equals(s) && !"https".equals(s)) return false;
        if (h == null || u.getUserInfo() != null) return false;
        h = h.toLowerCase().replaceAll("[.]+$", "");   // "localhost." zählt wie "localhost"
        String bare = h.replace("[", "").replace("]", "");
        // keine Geräte im Heimnetz (Router, NAS, der PC selbst) - im WLAN sperrt das zusätzlich iptables
        boolean v6 = bare.contains(":");   // IPv6-Literal (Domains enthalten keinen Doppelpunkt)
        if (HubLink.isPrivateIpv4(bare) || bare.startsWith("169.254.")
                || v6 && (bare.startsWith("fe80:") || bare.startsWith("fc") || bare.startsWith("fd"))) return false;
        return !(h.equals("localhost") || h.endsWith(".localhost") || h.startsWith("127.") || h.equals("0.0.0.0")
                || h.equals("0") || bare.equals("::1") || bare.equals("::") || bare.startsWith("::ffff:127.")
                || bare.startsWith("::ffff:7f") || bare.startsWith("::ffff:0:"));
    }

    /** Werbe- und Mess-Hosts (samt Unterdomains), die die Karten-Kachel nicht lädt. Nur reine Werbe-/Messdienste,
     *  keine CDNs oder Einwilligungs-Dialoge - die Kartenseiten sollen unverändert funktionieren. */
    static final String[] AD_HOSTS = {
            "doubleclick.net", "googlesyndication.com", "googleadservices.com", "googletagservices.com",
            "adservice.google.com", "scorecardresearch.com", "amazon-adsystem.com", "adnxs.com", "pubmatic.com",
            "rubiconproject.com", "openx.net", "criteo.com", "criteo.net", "casalemedia.com", "indexww.com",
            "moatads.com", "adsafeprotected.com", "doubleverify.com", "3lift.com", "sharethrough.com",
            "smartadserver.com", "yieldmo.com", "teads.tv", "gumgum.com", "taboola.com", "outbrain.com",
            "outbrainimg.com", "media.net", "lijit.com", "quantserve.com", "quantcount.com", "clarity.ms",
            "intergient.com", "nitropay.com", "playwire.com", "adthrive.com", "ezoic.net", "connatix.com",
            "primis.tech", "vdo.ai", "aniview.com", "33across.com", "sonobi.com", "bidswitch.net", "adform.net",
            "zdbb.net"};

    static boolean isAdHost(String host) {
        if (host == null) return false;
        String h = host.toLowerCase(java.util.Locale.ROOT).replaceAll("[.]+$", "");
        for (String d : AD_HOSTS) if (h.equals(d) || h.endsWith("." + d)) return true;
        return false;
    }

    void load(String url) {
        Uri u = Uri.parse(url);
        if (!allowed(u)) {
            Log.w(TAG, "Web: Adresse abgelehnt: " + u.getScheme() + "://" + u.getHost());
            return;
        }
        address.setText(url);
        if (web == null) createWeb();
        if (home != null) home.setVisibility(GONE);
        web.setVisibility(VISIBLE);
        web.loadUrl(url);
    }

    /** Neu laden; nach einem Renderer-Absturz ist die WebView leer - dann fallback laden. */
    void reload(String fallback) {
        if (web != null && web.getUrl() != null && !web.getUrl().equals("about:blank")) web.reload();
        else if (fallback != null && !fallback.isEmpty()) load(fallback);
    }

    boolean homeShown() {
        return home != null && home.getVisibility() == VISIBLE;
    }

    /** Renderer der Startseite beendet: ersetzen (sichtbar) bzw. verwerfen. */
    void homeGone() {
        boolean shown = homeShown();
        removeView(home);
        home.destroy();
        home = null;
        if (shown) showHome();
    }

    void reloadFromBar() {
        if (homeShown()) {   // auf der Startseite: diese neu laden, nicht die verdeckte Seite
            home.reload();
            return;
        }
        String t = address.getText().toString().trim();
        if (!t.isEmpty() && !t.matches("(?i)^https?://.*")) t = "https://" + t;
        reload(t);
    }

    boolean empty() {
        return web == null || web.getUrl() == null || web.getUrl().equals("about:blank");
    }

    void clear() {
        if (web != null) {
            web.loadUrl("about:blank");
            web.clearHistory();
        }
        address.setText("");
        if (chrome) showHome();
    }

    /** Startseite zeigen (Hub-WebView, getrennt von fremden Seiten; neu bei geändertem Hub-Weg USB/WLAN). */
    void showHome() {
        String u = a.hub() + "/start/";
        if (home == null || !u.equals(home.getTag())) {
            if (home != null) {
                removeView(home);
                home.destroy();
            }
            home = a.newHubWebView(null, HomeActivity.HUB_PORT);
            home.setTag(u);
            addView(home, new LayoutParams(-1, 0, 1f));
            home.loadUrl(u);
        }
        if (web != null) web.setVisibility(GONE);
        home.setVisibility(VISIBLE);
        if (!address.hasFocus()) address.setText("");
    }

    /** Weg zum Hub gewechselt: sichtbare Startseite neu laden, verdeckte verwerfen (wird bei Bedarf neu gebaut). */
    void hubChanged() {
        if (home == null) return;
        if (home.getVisibility() == VISIBLE) {
            showHome();
        } else {
            removeView(home);
            home.destroy();
            home = null;
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    void createWeb() {
        web = new WebView(a);
        web.setBackgroundColor(0xFFFFFFFF);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);          // ohne JS funktionieren die meisten Seiten nicht
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setGeolocationEnabled(false);
        s.setSupportMultipleWindows(false);    // target=_blank öffnet in derselben Ansicht
        s.setJavaScriptCanOpenWindowsAutomatically(false);
        s.setBuiltInZoomControls(true);
        s.setDisplayZoomControls(false);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                if (allowed(req.getUrl())) return false;
                Log.w(TAG, "Web: Navigation blockiert: " + req.getUrl().getScheme());
                return true;   // intent:, market:, file:, localhost ...
            }

            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                String s = u.getScheme();
                // Karten-Kachel: Werbung und Messdienste weglassen (Speicher, Rechenzeit auf schwachen Geräten)
                if (!chrome && isAdHost(u.getHost())) return new WebResourceResponse("text/plain", "utf-8", 403,
                        "Forbidden", null, new ByteArrayInputStream(new byte[0]));
                if (allowed(u) || "data".equals(s) || "blob".equals(s)) return null;
                return new WebResourceResponse("text/plain", "utf-8", 403, "Forbidden", null,
                        new ByteArrayInputStream(new byte[0]));
            }

            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                if (!address.hasFocus() && url != null && !url.equals("about:blank")) address.setText(url);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                HomeActivity.flushCookies();   // frischer Login übersteht auch ein sofortiges Ausschalten
                // Verlauf (am PC): nur echte Seiten der Web-Kachel, nicht die Karten-Kachel
                // nicht melden, wenn inzwischen die Startseite gezeigt wird (⌂ während des Ladens)
                if (chrome && !homeShown() && url != null && allowed(Uri.parse(url))) a.reportVisited(url, view.getTitle());
            }

            @Override
            public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
                Log.e(TAG, "Web: Renderer beendet, wird ersetzt");
                String last = view.getUrl();
                removeView(view);
                view.destroy();
                web = null;
                createWeb();
                long now = android.os.SystemClock.elapsedRealtime();
                boolean again = now - lastGone < 60_000;
                lastGone = now;
                // zweiter Absturz innerhalb einer Minute (z. B. Speichermangel durch eine schwere Karte):
                // nicht automatisch neu laden, sonst reißt eine Schleife auch Panel und Touchpad mit
                if (last != null && allowed(Uri.parse(last))) {
                    if (again) {
                        address.setText(last);
                        Log.w(TAG, "Web: erneuter Absturz - nicht automatisch neu geladen");
                    } else web.loadUrl(last);
                }
                return true;
            }
        });
        // keine WebChromeClient-Berechtigungen: Kamera/Mikrofon/Standort werden abgelehnt (Standard)
        addView(web, new LayoutParams(-1, 0, 1f));
    }

    void destroy() {
        if (home != null) {
            removeView(home);
            home.destroy();
            home = null;
        }
        if (web != null) {
            removeView(web);
            web.destroy();
            web = null;
        }
    }
}
