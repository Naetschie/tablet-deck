package app.tabletdeck.launcher;

import android.graphics.Outline;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.view.ViewOutlineProvider;
import android.webkit.WebView;
import android.widget.FrameLayout;

/**
 * Ton-Feld (Lautstärke, Mixer, Wiedergabe, Ausgabe): klappt über der aktuellen Ansicht auf - quer neben der Leiste,
 * hochkant als Blatt von unten. Inhalt ist die Hub-Seite /ton/. Es ist kein Moduswechsel: Der Hub erfährt nichts
 * davon, am Panel gehaltene Tasten bleiben gehalten. Ein Tipp daneben schließt das Feld und kommt nie bei der Ansicht
 * darunter an. Die WebView bekommt keinen Fokus, sonst meldet das Panel "blur" und löst Gehaltenes.
 */
class SoundPane extends FrameLayout {
    static final String PATH = "/ton/";
    static final int W = 360, H = 540, GAP = 8;

    final HomeActivity a;
    final FrameLayout box;
    WebView web;
    long openedAt;

    SoundPane(HomeActivity a) {
        super(a);
        this.a = a;
        setBackgroundColor(0x66000000);
        setContentDescription("Ton schließen");
        setOnClickListener(v -> a.closeSound());   // erst beim Loslassen: die Geste bleibt ganz bei diesem Feld
        box = new FrameLayout(a);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(HomeActivity.PANEL);
        bg.setStroke(1, HomeActivity.LINE);
        bg.setCornerRadius(a.dp(16));
        box.setBackground(bg);
        box.setPadding(1, 1, 1, 1);
        box.setClickable(true);   // Lücken neben der Seite schließen nicht
        box.setOutlineProvider(new ViewOutlineProvider() {
            @Override
            public void getOutline(View v, Outline o) {
                o.setRoundRect(0, 0, v.getWidth(), v.getHeight(), a.dp(16));
            }
        });
        box.setClipToOutline(true);
        addView(box);
    }

    /** Größe und Lage des Felds bei jedem Messen neu (Drehen, geänderte Bildschirmgröße bei offenem Feld). */
    @Override
    protected void onMeasure(int ws, int hs) {
        boolean sheet = a.bottomBar;
        int gap = a.dp(GAP), w = MeasureSpec.getSize(ws) - 2 * gap, h = MeasureSpec.getSize(hs) - 2 * gap;
        LayoutParams lp = (LayoutParams) box.getLayoutParams();
        lp.width = Math.max(1, sheet ? w : Math.min(a.dp(W), w));
        lp.height = Math.max(1, Math.min(a.dp(H), h));
        lp.gravity = Gravity.BOTTOM | (sheet ? Gravity.CENTER_HORIZONTAL : Gravity.START);
        lp.setMargins(gap, gap, gap, gap);
        super.onMeasure(ws, hs);
    }

    boolean isOpen() {
        return getVisibility() == VISIBLE;
    }

    void open() {
        openedAt = android.os.SystemClock.uptimeMillis();
        ensureWeb();
        setAlpha(a.light ? 1f : 0f);
        if (a.light) return;
        animate().alpha(1f).setDuration(150).start();
    }

    void ensureWeb() {
        if (web != null) return;
        web = a.newHubWebView(null, HomeActivity.HUB_PORT);
        web.setBackgroundColor(HomeActivity.PANEL);
        web.setFocusable(false);
        web.setFocusableInTouchMode(false);
        box.addView(web, new LayoutParams(-1, -1));
        web.loadUrl(a.hub() + PATH);
    }

    /** Seite verwerfen (Renderer weg, Hub-Wechsel, Speicher); ensureWeb lädt sie neu. */
    void drop() {
        if (web == null) return;
        box.removeView(web);
        web.destroy();
        web = null;
    }
}
