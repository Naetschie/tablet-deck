package app.tabletdeck.launcher;

import android.content.SharedPreferences;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * Karten-Kachel: Ingame-Karten fremder Anbieter in voller Größe. Spiel und Anbieter kommen vom Hub
 * (games.json, Feld maps). Bedienung über ein Overlay: oben links die aktuelle Karte (öffnet die Auswahl),
 * oben rechts Neu laden und Vollbild. Die Knöpfe blenden sich ohne Bedienung aus.
 * Die Seite läuft in einer BrowserPane ohne Adresszeile - mit denselben Sperren wie die Web-Kachel.
 */
public class MapPane extends FrameLayout {
    static final long HIDE_MS = 4000;

    static class Game {
        String id, name;
        List<String[]> maps = new ArrayList<>();   // {name, url, heavy ("1" = schwere Karte, sonst "")}
    }

    final HomeActivity a;
    final BrowserPane browser;
    final LinearLayout left, right;
    final TextView pillTitle, pillSub, pillCover;
    final View scrim;
    final ScrollView drawer;
    final LinearLayout drawerBox;
    final SharedPreferences prefs;
    List<Game> games = new ArrayList<>();
    String current;          // laufendes Spiel laut Hub
    String gameId, mapUrl;   // angezeigt
    String pickGame;         // im Menü gewähltes Spiel
    boolean full;
    boolean shown = true;     // Knöpfe sichtbar
    boolean wakeOnUp;         // Geste begann bei ausgeblendeten Knöpfen: gehört ganz der Karte
    final Runnable hide = () -> setControls(false);

    // Light-Modus: Karte in geringerer Auflösung zeichnen (BrowserPane.lowDpr: die Seite sieht Pixeldichte 1, eine
    // WebGL-Fläche hat dann bei Dichte 1,5 nur ~44 % der Pixel); schwere Karten nicht von selbst wählen
    boolean light;
    // Hänger-Erkennung: Bildlücken > STALL_MS, während die Karte sichtbar ist (die WebView-Grafik blockiert dann den
    // UI-Thread) - nach STALL_COUNT in STALL_WINDOW_MS den Hinweis zeigen (einmal je Start; schaltet nichts selbst)
    static final long STALL_MS = 1500, STALL_WINDOW_MS = 60_000;
    static final int STALL_COUNT = 3;
    long lastFrame, firstStall;
    int stalls;
    boolean watching, hintShown;
    final LinearLayout hint;
    final android.view.Choreographer.FrameCallback frame = new android.view.Choreographer.FrameCallback() {
        @Override
        public void doFrame(long nanos) {
            if (!watching) return;
            long now = android.os.SystemClock.uptimeMillis();
            if (lastFrame > 0 && now - lastFrame > STALL_MS) stalled(now, now - lastFrame);
            lastFrame = now;
            android.view.Choreographer.getInstance().postFrameCallback(this);
        }
    };

    MapPane(HomeActivity a) {
        super(a);
        this.a = a;
        prefs = a.getSharedPreferences("maps", HomeActivity.MODE_PRIVATE);
        setBackgroundColor(HomeActivity.BG);
        browser = new BrowserPane(a, false);
        addView(browser, new LayoutParams(-1, -1));

        // oben links: aktuelle Karte
        left = new LinearLayout(a);
        left.setOrientation(LinearLayout.HORIZONTAL);
        left.setGravity(Gravity.CENTER_VERTICAL);
        left.setPadding(a.dp(8), a.dp(6), a.dp(14), a.dp(6));
        left.setBackground(glass(18));
        pillCover = cover(40);
        left.addView(pillCover, new LinearLayout.LayoutParams(a.dp(40), a.dp(40)));
        LinearLayout t = new LinearLayout(a);
        t.setOrientation(LinearLayout.VERTICAL);
        t.setPadding(a.dp(10), 0, a.dp(6), 0);
        pillTitle = text(15, HomeActivity.TEXT, true);
        pillSub = text(12, HomeActivity.DIM, false);
        t.addView(pillTitle);
        t.addView(pillSub);
        left.addView(t);
        TextView chev = text(14, HomeActivity.DIM, false);
        chev.setText("▾");
        left.addView(chev);
        left.setOnClickListener(v -> openMenu());
        LayoutParams lp = new LayoutParams(-2, a.dp(56), Gravity.TOP | Gravity.START);
        lp.setMargins(a.dp(16), a.dp(16), 0, 0);
        addView(left, lp);

        // oben rechts: Neu laden, Vollbild
        right = new LinearLayout(a);
        right.setOrientation(LinearLayout.HORIZONTAL);
        right.addView(iconButton(R.drawable.ic_refresh, "Neu laden", v -> browser.reload(mapUrl)));
        right.addView(iconButton(R.drawable.ic_fullscreen, "Vollbild", v -> setFull(!full)));
        LayoutParams rp = new LayoutParams(-2, -2, Gravity.TOP | Gravity.END);
        rp.setMargins(0, a.dp(16), a.dp(16), 0);
        addView(right, rp);

        // Auswahl-Menü (Overlay)
        scrim = new View(a);
        scrim.setBackgroundColor(0x66000000);
        scrim.setVisibility(GONE);
        scrim.setOnClickListener(v -> closeMenu());
        addView(scrim, new LayoutParams(-1, -1));
        drawer = new ScrollView(a);
        drawer.setBackground(glass(18));
        drawer.setVisibility(GONE);
        drawerBox = new LinearLayout(a);
        drawerBox.setOrientation(LinearLayout.VERTICAL);
        drawerBox.setPadding(a.dp(16), a.dp(16), a.dp(16), a.dp(16));
        drawer.addView(drawerBox);
        LayoutParams dp = new LayoutParams(a.dp(380), -1, Gravity.START);
        dp.setMargins(a.dp(16), a.dp(16), 0, a.dp(16));
        addView(drawer, dp);

        // Hinweis bei Hängern (unten mittig)
        hint = new LinearLayout(a);
        hint.setOrientation(LinearLayout.VERTICAL);
        hint.setPadding(a.dp(18), a.dp(14), a.dp(18), a.dp(14));
        hint.setBackground(glass(18));
        hint.setVisibility(GONE);
        hint.setClickable(true);   // Berührungen nicht an die Karte durchreichen
        TextView ht = text(15, HomeActivity.TEXT, true);
        ht.setSingleLine(false);
        ht.setText("Die Karte bremst dieses Gerät.");
        hint.addView(ht);
        TextView hs = text(13, HomeActivity.DIM, false);
        hs.setSingleLine(false);
        hs.setText("Der Light-Modus zeichnet Karten in geringerer Auflösung und gibt verdeckte Seiten frei.");
        hs.setPadding(0, a.dp(4), 0, a.dp(10));
        hint.addView(hs);
        LinearLayout hb = new LinearLayout(a);
        hb.setGravity(Gravity.END);
        TextView no = text(14, HomeActivity.DIM, true);
        no.setText("Nicht jetzt");
        no.setPadding(a.dp(14), a.dp(10), a.dp(14), a.dp(10));
        no.setOnClickListener(v -> hint.setVisibility(GONE));
        TextView yes = text(14, HomeActivity.ACCENT, true);
        yes.setText("Light-Modus einschalten");
        yes.setPadding(a.dp(14), a.dp(10), a.dp(14), a.dp(10));
        yes.setOnClickListener(v -> {
            hint.setVisibility(GONE);
            a.requestLight(true);
        });
        hb.addView(no);
        hb.addView(yes);
        hint.addView(hb);
        LayoutParams hp = new LayoutParams(Math.min(a.dp(440), a.getResources().getDisplayMetrics().widthPixels - a.dp(32)),
                -2, Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL);
        hp.bottomMargin = a.dp(24);
        addView(hint, hp);

        light = a.light;
        browser.setLowDpr(light);
        render();
    }

    // ------------------------------------------------------------------ Daten vom Hub

    /** {"games":[{id,name,maps:[{name,url}]}], "current": id|null} */
    void setData(String json) {
        try {
            JSONObject o = new JSONObject(json);
            List<Game> next = new ArrayList<>();
            JSONArray ga = o.getJSONArray("games");
            for (int i = 0; i < ga.length(); i++) {
                JSONObject g = ga.getJSONObject(i);
                Game x = new Game();
                x.id = g.getString("id");
                x.name = g.optString("name", x.id);
                JSONArray m = g.optJSONArray("maps");
                for (int j = 0; m != null && j < m.length(); j++) {
                    JSONObject e = m.getJSONObject(j);
                    x.maps.add(new String[]{e.getString("name"), e.getString("url"), e.optBoolean("heavy") ? "1" : ""});
                }
                next.add(x);
            }
            String cur = o.isNull("current") ? null : o.optString("current", null);
            boolean changed = cur != null && !cur.equals(current);
            games = next;
            current = cur;
            // Spiel gestartet: dessen Karte zeigen (zuletzt genutzter Anbieter); sonst die bisherige behalten
            if (changed && find(cur) != null && !find(cur).maps.isEmpty()) select(cur, null);
            else if (gameId == null) restore();
            render();
        } catch (Exception e) {
            android.util.Log.w(HomeActivity.TAG, "Karten-Daten ungültig: " + e);
        }
    }

    Game find(String id) {
        for (Game g : games) if (g.id.equals(id)) return g;
        return null;
    }

    void restore() {
        String g = prefs.getString("game", null);
        if (g == null || find(g) == null) g = current;
        if (g == null || find(g) == null) for (Game x : games) if (!x.maps.isEmpty()) { g = x.id; break; }
        if (g != null && find(g) != null && !find(g).maps.isEmpty()) select(g, null);
    }

    /** Karte eines Spiels laden (url null = zuletzt genutzter bzw. erster Anbieter). */
    /**
     * url != null: ausdrückliche Wahl (Menü, Editor „Zeigen“) - wird als "pick:<spiel>" gemerkt und gilt immer, auch
     * für schwere Karten. url == null: von selbst - gemerkte Wahl, sonst zuletzt gezeigte Karte, sonst die erste;
     * im Light-Modus ohne gemerkte Wahl nur leichte Karten (zuletzt gezeigt zählt dann nur, wenn sie leicht ist).
     */
    void select(String gid, String url) {
        Game g = find(gid);
        if (g == null || g.maps.isEmpty()) return;
        String[] pick = url != null ? byUrl(g, url) : byUrl(g, prefs.getString("pick:" + gid, null));
        if (pick == null) {
            String[] last = byUrl(g, prefs.getString("url:" + gid, null));
            if (light && (last == null || "1".equals(last[2]))) {
                for (String[] m : g.maps) if (!"1".equals(m[2])) { last = m; break; }
            }
            pick = last != null ? last : g.maps.get(0);
        }
        gameId = gid;
        if (!pick[1].equals(mapUrl) || browser.empty()) {   // leer z. B. nach einem Renderer-Absturz
            mapUrl = pick[1];
            browser.load(mapUrl);
        }
        SharedPreferences.Editor ed = prefs.edit().putString("game", gid).putString("url:" + gid, mapUrl);
        if (url != null && url.equals(mapUrl)) ed.putString("pick:" + gid, mapUrl);
        ed.apply();
        render();
    }

    static String[] byUrl(Game g, String url) {
        if (url != null) for (String[] m : g.maps) if (m[1].equals(url)) return m;
        return null;
    }

    // ------------------------------------------------------------------ Oberfläche

    void render() {
        Game g = find(gameId);
        String name = "Keine Karte";
        if (g != null) for (String[] m : g.maps) if (m[1].equals(mapUrl)) name = m[0];
        pillTitle.setText(name);
        pillSub.setText(g != null ? g.name : games.isEmpty() ? "Warte auf den PC …" : "Spiel wählen");
        pillCover.setText(initials(g != null ? g.name : "?"));
        if (drawer.getVisibility() == VISIBLE) renderMenu();
    }

    void openMenu() {
        pickGame = gameId != null ? gameId : current;
        if (find(pickGame) == null || find(pickGame).maps.isEmpty()) {
            pickGame = null;
            for (Game g : games) if (!g.maps.isEmpty()) { pickGame = g.id; break; }
        }
        renderMenu();
        scrim.setVisibility(VISIBLE);
        drawer.setVisibility(VISIBLE);
        setControls(true);
        removeCallbacks(hide);
    }

    void closeMenu() {
        scrim.setVisibility(GONE);
        drawer.setVisibility(GONE);
        poke();
    }

    void renderMenu() {
        drawerBox.removeAllViews();
        LinearLayout head = new LinearLayout(a);
        head.setGravity(Gravity.CENTER_VERTICAL);
        TextView h = label("SPIEL");
        head.addView(h, new LinearLayout.LayoutParams(0, -2, 1f));
        head.addView(iconButton(R.drawable.ic_close, "Schließen", v -> closeMenu()));
        drawerBox.addView(head);
        for (Game g : games) {
            if (g.maps.isEmpty()) continue;   // z. B. Strategiespiele: keine Karten, nicht anbieten
            boolean on = g.id.equals(pickGame);
            LinearLayout row = chip(on);
            TextView c = cover(32);
            c.setText(initials(g.name));
            row.addView(c, new LinearLayout.LayoutParams(a.dp(32), a.dp(32)));
            TextView n = text(14, on ? HomeActivity.TEXT : HomeActivity.DIM, true);
            n.setText(g.name + (g.id.equals(current) ? "  · läuft" : ""));
            n.setPadding(a.dp(10), 0, 0, 0);
            row.addView(n, new LinearLayout.LayoutParams(0, -2, 1f));
            row.setOnClickListener(v -> { pickGame = g.id; renderMenu(); });
            drawerBox.addView(row, gap(new LinearLayout.LayoutParams(-1, a.dp(52))));
        }
        TextView ph = label("ANBIETER");
        ph.setPadding(0, a.dp(14), 0, a.dp(6));
        drawerBox.addView(ph);
        Game g = find(pickGame);
        if (g == null || g.maps.isEmpty()) {
            TextView e = text(13, HomeActivity.DIM, false);
            e.setText(g == null ? "Noch kein Spiel mit Karten - Kartenanbieter stehen in games.json am PC (Feld maps)."
                    : "Für dieses Spiel ist noch kein Kartenanbieter hinterlegt (games.json am PC, Feld maps).");
            e.setPadding(a.dp(14), a.dp(14), a.dp(14), a.dp(14));
            e.setBackground(box(HomeActivity.BG, true));
            drawerBox.addView(e);
            return;
        }
        for (String[] m : g.maps) {
            boolean on = g.id.equals(gameId) && m[1].equals(mapUrl);
            LinearLayout row = chip(on);
            row.setOrientation(LinearLayout.VERTICAL);
            row.setGravity(Gravity.CENTER_VERTICAL | Gravity.START);
            TextView n = text(15, HomeActivity.TEXT, true);
            n.setText(m[0]);
            TextView u = text(12, HomeActivity.DIM, false);
            u.setText(host(m[1]));
            row.addView(n);
            row.addView(u);
            row.setOnClickListener(v -> { select(g.id, m[1]); closeMenu(); });
            drawerBox.addView(row, gap(new LinearLayout.LayoutParams(-1, a.dp(64))));
        }
    }

    void setFull(boolean on) {
        full = on;
        a.setRailVisible(!on);
        poke();
    }

    /** Beim Verlassen der Kachel: Vollbild beenden (die Leiste wird sonst nicht mehr erreichbar). */
    void leave() {
        if (full) setFull(false);
        scrim.setVisibility(GONE);
        drawer.setVisibility(GONE);
        hint.setVisibility(GONE);
        onHidden();
    }

    // Jede Berührung zeigt die Knöpfe wieder, danach blenden sie sich aus. Waren sie ausgeblendet, gehört die
    // ganze Geste der Karte; die Knöpfe erscheinen erst beim Loslassen (sonst löst der Tipp einen Knopf aus).
    @Override
    public boolean dispatchTouchEvent(MotionEvent ev) {
        int act = ev.getActionMasked();
        // Hinweis (Hänger) sichtbar: normal verteilen, damit seine Knöpfe ankommen
        if (drawer.getVisibility() != VISIBLE && hint.getVisibility() != VISIBLE) {
            if (act == MotionEvent.ACTION_DOWN) {
                if (shown) poke();
                else wakeOnUp = true;
            }
            if (wakeOnUp) {
                // direkt an die Karte - auch während der Ausblend-Animation, wenn die Knöpfe noch sichtbar sind
                boolean r = browser.dispatchTouchEvent(ev);
                if (act == MotionEvent.ACTION_UP || act == MotionEvent.ACTION_CANCEL) {
                    wakeOnUp = false;
                    poke();
                }
                return r;
            }
        }
        return super.dispatchTouchEvent(ev);
    }

    void poke() {
        setControls(true);
        removeCallbacks(hide);
        postDelayed(hide, HIDE_MS);
    }

    /** Ausgeblendet = INVISIBLE (nicht nur durchsichtig): dann nehmen die Knöpfe keine Berührungen an. */
    void setControls(boolean on) {
        shown = on;
        for (View v : new View[]{left, right}) {
            v.animate().cancel();
            if (on) {
                v.setVisibility(VISIBLE);
                v.animate().alpha(1f).setDuration(180).start();
            } else {
                v.animate().alpha(0f).setDuration(180).withEndAction(() -> { if (!shown) v.setVisibility(INVISIBLE); })
                        .start();
            }
        }
    }

    /** Kachel sichtbar/verdeckt: Karte im Hintergrund anhalten (JS, Timer, WebGL). */
    void onShown() {
        if (browser.web != null) browser.web.onResume();
        poke();
        if (!a.paused) watch(true);   // pausiert (andere App vorn): erst onResume misst
    }

    void onHidden() {
        if (browser.web != null) browser.web.onPause();
        removeCallbacks(hide);
        watch(false);
    }

    // ------------------------------------------------------------------ Light-Modus und Hänger

    void setLight(boolean on) {
        if (on == light) return;
        light = on;
        if (on) hint.setVisibility(GONE);
        browser.setLowDpr(on);
    }

    void watch(boolean on) {
        if (on == watching) return;
        watching = on;
        lastFrame = 0;
        if (on) android.view.Choreographer.getInstance().postFrameCallback(frame);
        else android.view.Choreographer.getInstance().removeFrameCallback(frame);
    }

    void stalled(long now, long gap) {
        if (now - firstStall > STALL_WINDOW_MS) {
            firstStall = now;
            stalls = 0;
        }
        stalls++;
        android.util.Log.w(HomeActivity.TAG, "Karte: Bild hing " + gap + " ms (" + stalls + ". in "
                + (STALL_WINDOW_MS / 1000) + " s)" + (light ? ", Light-Modus an" : ""));
        if (stalls >= STALL_COUNT && !light && !hintShown) {
            hintShown = true;
            if (wakeOnUp) {   // laufende Geste der Karte sauber beenden, sie geht nicht weiter direkt dorthin
                long t = android.os.SystemClock.uptimeMillis();
                MotionEvent c = MotionEvent.obtain(t, t, MotionEvent.ACTION_CANCEL, 0, 0, 0);
                browser.dispatchTouchEvent(c);
                c.recycle();
                wakeOnUp = false;
            }
            hint.setVisibility(VISIBLE);
            hint.bringToFront();
        }
    }

    // ------------------------------------------------------------------ Bausteine

    GradientDrawable glass(int radiusDp) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(0xE6161A1F);
        d.setCornerRadius(a.dp(radiusDp));
        d.setStroke(1, HomeActivity.LINE);
        return d;
    }

    GradientDrawable box(int color, boolean dashed) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(color);
        d.setCornerRadius(a.dp(14));
        if (dashed) d.setStroke(1, HomeActivity.LINE, a.dp(6), a.dp(4));
        else d.setStroke(1, HomeActivity.LINE);
        return d;
    }

    LinearLayout chip(boolean on) {
        LinearLayout row = new LinearLayout(a);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(a.dp(10), a.dp(6), a.dp(12), a.dp(6));
        GradientDrawable d = box(on ? 0x244FB3FF : HomeActivity.S2, false);
        if (on) d.setStroke(1, HomeActivity.ACCENT);
        row.setBackground(d);
        return row;
    }

    LinearLayout.LayoutParams gap(LinearLayout.LayoutParams p) {
        p.topMargin = a.dp(8);
        return p;
    }

    TextView text(int sp, int color, boolean bold) {
        TextView t = new TextView(a);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        t.setSingleLine(true);
        t.setEllipsize(TextUtils.TruncateAt.END);
        if (bold) t.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        return t;
    }

    TextView label(String s) {
        TextView t = text(12, HomeActivity.DIM, true);
        t.setText(s);
        t.setLetterSpacing(0.1f);
        return t;
    }

    TextView cover(int sizeDp) {
        TextView c = text(sizeDp > 36 ? 13 : 12, HomeActivity.ACCENT, true);
        c.setGravity(Gravity.CENTER);
        GradientDrawable d = new GradientDrawable();
        d.setColor(0xFF28313B);
        d.setCornerRadius(a.dp(10));
        c.setBackground(d);
        return c;
    }

    View iconButton(int res, String desc, View.OnClickListener l) {
        ImageView b = new ImageView(a);
        b.setImageResource(res);
        b.setImageTintList(android.content.res.ColorStateList.valueOf(HomeActivity.TEXT));
        b.setScaleType(ImageView.ScaleType.CENTER);
        b.setContentDescription(desc);
        b.setBackground(glass(18));
        b.setOnClickListener(l);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(a.dp(56), a.dp(56));
        p.leftMargin = a.dp(8);
        b.setLayoutParams(p);
        return b;
    }

    static String initials(String name) {
        String[] w = name.replaceAll("[^A-Za-z0-9 ]", " ").trim().split("\\s+");
        String s = (w.length > 0 && !w[0].isEmpty() ? w[0].substring(0, 1) : "?")
                + (w.length > 1 ? w[1].substring(0, 1) : "");
        return s.toUpperCase();
    }

    static String host(String url) {
        String h = android.net.Uri.parse(url).getHost();
        return h == null ? url : h.replaceFirst("^www\\.", "");
    }

    void destroy() {
        removeCallbacks(hide);
        watch(false);
        browser.destroy();
    }
}
