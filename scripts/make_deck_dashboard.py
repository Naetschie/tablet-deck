"""Erzeugt dashboards/deck.json: PC-Werte im Stil des Tablet Deck (Clean Dark, Tokens aus web/lib/tokens.css).

Gleiche Werte wie der MoBro-Nachbau (dashboards/mobro.json), aber eigenes Layout: Karten für CPU, GPU, FPS,
Speicher/Netz und Mainboard. Fläche 1152×800 = Tablet (1280×800) ohne Leiste.

Aufruf: python scripts/make_deck_dashboard.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W, H = 1152, 800
M, G = 16, 16                     # Rand, Abstand zwischen Karten

BG, CARD, LINE, TRACK = "#0E1114", "#161A1F", "#2B343E", "#28313B"
TX, DIM = "#E8ECF0", "#9AA6B2"
BLUE, GREEN, ORANGE, RED = "#4FB3FF", "#3DDC84", "#F0923A", "#E5484D"
TEMP_ZONES = [{"from": 0.6, "color": ORANGE}, {"from": 0.85, "color": RED}]

widgets = []


def add(**w):
    widgets.append(w)


def card(x, y, w, h, title):
    add(type="rect", x=x, y=y, w=w, h=h, fill=CARD, stroke=LINE, stroke_width=1, radius=18)
    add(type="text", x=x + 20, y=y + 14, w=w - 40, h=24, text=title, color=DIM, size=13, weight=600, font="sans")


def label(x, y, w, text, align="start"):
    add(type="text", x=x, y=y, w=w, h=18, text=text, color=DIM, size=13, font="sans", align=align)


def value(x, y, w, sensor, size=20, unit=None, decimals=0, scale=None, align="start", color=TX, h=None):
    v = dict(type="value", x=x, y=y, w=w, h=h or size + 8, sensor=sensor, size=size, color=color,
             decimals=decimals, align=align, font="head", weight=600, small_unit=True, label_color=DIM)
    if unit is not None:
        v["unit"] = unit
    if scale is not None:
        v["scale"] = scale
    add(**v)


def stat(x, y, w, text, sensor, **kw):
    """Kleine Kennzahl: Beschriftung oben, Wert darunter."""
    label(x, y, w, text)
    value(x, y + 20, w, sensor, **kw)


def gauge(x, y, size, sensor, color, lo, hi, caption):
    add(type="gauge", x=x, y=y, w=size, h=size, sensor=sensor, min=lo, max=hi, color=color, track=TRACK,
        thickness=14, ring=False, zones=TEMP_ZONES)
    value(x, y + size / 2 - 22, size, sensor, size=30, unit="°C", align="center", h=40)
    label(x, y + size / 2 + 20, size, caption, align="center")


def history(x, y, w, h, sensor, color, area, lo=None, hi=None):
    l = dict(type="line", x=x, y=y, w=w, h=h, sensor=sensor, color=color, area=area, thickness=2,
             axis=False, seconds=60)
    if lo is not None:
        l.update(min=lo, max=hi)
    add(**l)


# --- Kopf ---
add(type="text", x=M + 4, y=M, w=400, h=48, text="PC-Werte", color=TX, size=24, weight=600, font="head")
add(type="date", x=W - M - 360, y=M, w=200, h=48, format="DD.MM.YYYY", color=DIM, size=15, align="end", font="sans")
add(type="clock", x=W - M - 150, y=M, w=150, h=48, format="HH:mm", color=TX, size=34, align="end", font="head")

TOP, TOP_H = 80, 408
BOT = TOP + TOP_H + G
BOT_H = H - M - BOT
HALF = (W - 2 * M - G) // 2

# --- CPU ---
x0, y0 = M, TOP
card(x0, y0, HALF, TOP_H, "CPU")
value(x0 + 20, y0 + 40, 200, "cpu.load", size=40, unit="%", h=52)
history(x0 + 20, y0 + 100, 300, 92, "cpu.load", BLUE, "rgba(79,179,255,0.14)", 0, 100)
gauge(x0 + HALF - 200, y0 + 24, 176, "cpu.temp.package", BLUE, 20, 100, "Package")
stat(x0 + 20, y0 + 208, 150, "Kern max", "cpu.temp.core_max", unit="°C")
stat(x0 + 180, y0 + 208, 150, "Leistung", "cpu.power.package", unit="W")
label(x0 + 20, y0 + 268, 300, "Kerntakte (GHz)")
# Alle vorhandenen Kerne (cpu.clock.<n>, je PC verschieden): 6 Spalten, bei vielen Kernen mehr Spalten.
# Hier 12 Kerne = 2 Zeilen zu 6 (Zeile 296 bis 348+31 = 379 < Kartenende 408).
add(type="cores", x=x0 + 20, y=y0 + 296, w=HALF - 40, h=TOP_H - 296 - 16, columns=6, size=15, label_size=12,
    scale=0.001, decimals=1, min=0, max=5500, color=BLUE, color_e="#8AC9FF", track=TRACK, label_color=DIM,
    text_color=TX, weight=600)

# --- GPU ---
x0 = M + HALF + G
card(x0, y0, HALF, TOP_H, "GPU")
value(x0 + 20, y0 + 40, 200, "gpu.load", size=40, unit="%", h=52)
history(x0 + 20, y0 + 100, 300, 92, "gpu.load", GREEN, "rgba(61,220,132,0.14)", 0, 100)
gauge(x0 + HALF - 200, y0 + 24, 176, "gpu.temp", GREEN, 20, 95, "Kern")
qw = (HALF - 40) / 4
for i, (t, s, kw) in enumerate([
        ("Takt", "gpu.clock.core", dict(unit="MHz")),
        ("Speichertakt", "gpu.clock.mem", dict(unit="MHz")),
        ("Leistung", "gpu.power", dict(unit="W")),
        ("Speicher-Temp.", "gpu.temp.mem", dict(unit="°C"))]):
    stat(x0 + 20 + i * qw, y0 + 208, qw - 8, t, s, **kw)
label(x0 + 20, y0 + 268, 200, "VRAM")
value(x0 + 20, y0 + 266, HALF - 40, "gpu.vram.used", size=15, unit="GB", decimals=1, scale=1 / 1024, align="end",
      h=22)
add(type="bar", x=x0 + 20, y=y0 + 296, w=HALF - 40, h=8, sensor="gpu.vram.used", color=GREEN, track=TRACK, radius=4)
for i, (t, s, kw) in enumerate([
        ("Speichercontroller", "gpu.load.memctl", dict(unit="%")),
        ("PCIe Rx", "gpu.pcie.rx", dict(unit="MB/s", scale=1 / 1024, decimals=1)),
        ("Lüfter 1", "gpu.fan1", dict(unit="U/min")),
        ("Lüfter 2", "gpu.fan2", dict(unit="U/min"))]):
    stat(x0 + 20 + i * qw, y0 + 328, qw - 8, t, s, **kw)

# --- FPS ---
x0, y0 = M, BOT
FW = 272
card(x0, y0, FW, BOT_H, "FPS (Spiel)")
value(x0 + 20, y0 + 40, FW - 40, "fps.displayed", size=48, unit="fps", h=60)
stat(x0 + 20, y0 + 106, FW - 40, "Frametime", "fps.frametime", unit="ms", decimals=1)
history(x0 + 20, y0 + 172, FW - 40, BOT_H - 192, "fps.displayed", ORANGE, "rgba(240,146,58,0.14)")

# --- Speicher und Netz ---
x0 = M + FW + G
SW = 384
card(x0, y0, SW, BOT_H, "Arbeitsspeicher und Netz")
value(x0 + 20, y0 + 40, 200, "ram.used", size=28, unit="GB", decimals=1, scale=1 / 1024, h=38)
add(type="value", x=x0 + 20, y=y0 + 46, w=SW - 40, h=26, sensor="ram.total", label="von ", size=15, color=DIM,
    unit="GB", decimals=0, scale=1 / 1024, align="end", font="sans", weight=500)
add(type="bar", x=x0 + 20, y=y0 + 84, w=SW - 40, h=8, sensor="ram.used", color=BLUE, track=TRACK, radius=4)
nw = (SW - 40) / 3
stat(x0 + 20, y0 + 110, nw - 8, "Download", "net.down", unit="MB/s", decimals=1, scale=1 / 1024)
stat(x0 + 20 + nw, y0 + 110, nw - 8, "Upload", "net.up", unit="MB/s", decimals=1, scale=1 / 1024)
stat(x0 + 20 + 2 * nw, y0 + 110, nw - 8, "Empfangen", "net.total_down", unit="GB", decimals=1, scale=1 / 1024)
history(x0 + 20, y0 + 172, SW - 40, BOT_H - 192, "net.down", GREEN, "rgba(61,220,132,0.14)")

# --- Mainboard ---
x0 = M + FW + G + SW + G
BW = W - M - x0
card(x0, y0, BW, BOT_H, "Mainboard")
col = (BW - 40 - 24) / 2
# Alle vorhandenen Lüfter (fan.*, Namen aus dem Sensor-Helfer); Platz für 4 Zeilen, bei mehr rücken sie zusammen
add(type="fans", x=x0 + 20, y=y0 + 48, w=col, h=BOT_H - 48 - 16, size=18, label_size=13, row_h=48, color=TX,
    label_color=DIM, separator=LINE, weight=600)
for i, (t, s) in enumerate([("+12 V", "volt.12v"), ("+5 V", "volt.5v"), ("+3,3 V", "volt.3v3"),
                            ("DRAM", "volt.dram")]):
    xx, yy = x0 + 20 + col + 24, y0 + 48 + i * 48
    label(xx, yy + 4, col, t)
    value(xx, yy, col, s, size=18, unit="V", decimals=2 if s != "volt.dram" else 3, align="end", h=26)
    if i < 3:
        add(type="hline", x=xx, y=yy + 34, w=col, h=2, thickness=1, color=LINE)

dash = {"title": "PC-Werte (Deck)", "width": W, "height": H, "background": BG, "widgets": widgets}
out = ROOT / "dashboards" / "deck.json"
out.write_text(json.dumps(dash, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
print(f"{out}: {len(widgets)} Widgets")
