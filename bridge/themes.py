"""Farbschemas fürs Tablet: Fläche x Akzent, beides feste Auswahl (kein freier Farbwähler).

Warnung, Gefahr und OK (Orange, Rot, Grün) gehören nicht dazu: gesicherte Tasten und Zustände sehen in jedem Schema
gleich aus. Deshalb gibt es auch keinen Akzent in deren Nähe (Bernstein, Grün, Rot). Jede Kombination wird in
tests/test_themes.py auf Kontrast geprüft. "standard" + "blau" entspricht web/lib/tokens.css.

Gespeichert pro Gerät in devices.json ("theme": {"surface": "schwarz", "accent": "violett"}), Vorgabe für alle in
config.json ("tablet_theme"). Die Seiten bekommen /lib/theme.css (nur mit Gerätekennung, der Editor am PC bleibt beim
Standard), der Launcher die Farben über /ctl.
"""

SURFACES = {
    "standard": ("Standard", {"bg": "#0E1114", "s1": "#161A1F", "s2": "#1E242B", "s3": "#28313B", "line": "#2B343E",
                              "tx": "#E8ECF0", "dim": "#9AA6B2"}),
    "schwarz": ("Schwarz", {"bg": "#000000", "s1": "#0A0C0F", "s2": "#14181D", "s3": "#20272F", "line": "#262E37",
                            "tx": "#E8ECF0", "dim": "#9AA6B2"}),
    "kontrast": ("Hoher Kontrast", {"bg": "#000000", "s1": "#0A0C0F", "s2": "#14181D", "s3": "#20272F",
                                    "line": "#566473", "tx": "#FFFFFF", "dim": "#C9D2DB"}),
}
ACCENTS = {
    "blau": ("Blau", "#4FB3FF"),
    "cyan": ("Cyan", "#2FD3D8"),
    "violett": ("Violett", "#A99BFF"),
    "pink": ("Pink", "#F28BCB"),
    "weiss": ("Weiß", "#D5DCE3"),
}
AC_TEXT = "#04121D"   # Text auf dem Akzent
DEFAULT = {"surface": "standard", "accent": "blau"}


def valid(t):
    return (isinstance(t, dict) and set(t) == {"surface", "accent"}
            and isinstance(t["surface"], str) and t["surface"] in SURFACES
            and isinstance(t["accent"], str) and t["accent"] in ACCENTS)


def rgb(hex_):
    return tuple(int(hex_[i:i + 2], 16) for i in (1, 3, 5))


def _rgba(hex_, a):
    return "rgba(%d, %d, %d, %s)" % (*rgb(hex_), a)


def mix(a, b, p):
    """Anteil p von a über b."""
    return "#%02X%02X%02X" % tuple(round(p * x + (1 - p) * y) for x, y in zip(rgb(a), rgb(b)))


def colors(theme):
    """Alle Rollen eines Schemas: {"bg": "#0E1114", …, "acSoft": "rgba(…)"}. Schlüssel = CSS-Token ohne "--"."""
    t = theme if valid(theme) else DEFAULT
    c = dict(SURFACES[t["surface"]][1])
    c["ac"] = ACCENTS[t["accent"]][1]
    c["acTx"] = AC_TEXT
    c["acSoft"] = _rgba(c["ac"], ".14")
    c["s1Veil"] = _rgba(c["s1"], ".5")
    c["bgVeil"] = _rgba(c["bg"], ".85")
    return c


def css(theme):
    """Überschreibt die Farb-Tokens aus tokens.css (leer beim Standard)."""
    if not valid(theme) or theme == DEFAULT:
        return "/* Standard: web/lib/tokens.css */\n"
    return ":root { " + " ".join(f"--{k}: {v};" for k, v in colors(theme).items()) + " }\n"


def recolor(text, theme):
    """Mitgeliefertes Dashboard (JSON-Text, nutzt die Standardfarben als Hex-Werte) ins Schema übersetzen."""
    if not valid(theme) or theme == DEFAULT:
        return text
    old, new = colors(DEFAULT), colors(theme)
    table = {old[k].upper(): new[k] for k in ("bg", "s1", "s2", "s3", "line", "tx", "dim", "ac")}
    table["#8AC9FF"] = mix(new["ac"], "#FFFFFF", .67)   # hellere Stufe des Akzents (E-Kerne)
    import re
    return re.sub(r'"(#[0-9A-Fa-f]{6})"', lambda m: '"%s"' % table.get(m.group(1).upper(), m.group(1)), text)


def choices():
    """Auswahl für den Editor."""
    return {"surfaces": [{"id": k, "label": v[0], "bg": v[1]["bg"], "s2": v[1]["s2"], "line": v[1]["line"],
                          "tx": v[1]["tx"]} for k, v in SURFACES.items()],
            "accents": [{"id": k, "label": v[0], "color": v[1]} for k, v in ACCENTS.items()]}
