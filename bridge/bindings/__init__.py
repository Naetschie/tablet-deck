"""Tastenbelegungen der Spiele lesen (Engine-Adapter).

Jeder Adapter liefert ein Result: bindings {aktion: Binding(key, hold, note)}, freie Kombinationen für
Vorschläge und eine Beschreibung der Quelle. key=None heißt: Aktion bekannt, aber ohne nutzbare
Tastaturbelegung (note sagt warum).
"""
from collections import namedtuple

# min_ms: Spiel wertet den Druck erst nach dieser Haltezeit (z. B. Star Citizen "delayed_press"); 0 = sofort
Binding = namedtuple("Binding", "key hold note min_ms", defaults=(0,))
Result = namedtuple("Result", "bindings free source")


def _cryengine(cfg, root):
    from . import cryengine
    return cryengine.read(cfg, root)


ADAPTERS = {"cryengine": _cryengine}


def resolve_cfg(cfg, root, entries=None):
    """(cfg mit gefundenen Pfaden, [Quelldateien]) ohne die Bibliothek neu zu scannen; für Änderungserkennung."""
    if cfg.get("adapter") == "cryengine":
        from . import cryengine
        return cryengine.resolve_cfg(cfg, root, entries)
    return dict(cfg), []


def apply_sc(layout, result):
    """Kopie des Layouts, in der Tasten mit Feld "sc" die echte Belegung des Spielers tragen (key, bei Halte-
    Aktionen hold=true). Aktionen ohne Tastaturbelegung oder unbekannte Aktionen behalten, was in der Datei steht.
    Für mitgelieferte Panels: dort stehen nur Aktionsnamen (und höchstens eine Standardtaste als Rückfall).
    Gibt (Layout, Anzahl geänderter Tasten) zurück; das übergebene Layout bleibt unverändert."""
    import copy
    out, n = copy.deepcopy(layout), 0
    for page in out.get("pages", []):
        for b in page.get("buttons", []):
            act = b.get("sc")
            bd = result.bindings.get(act) if isinstance(act, str) and result else None
            if bd is None or not bd.key:
                continue
            if b.get("key") != bd.key:
                b["key"] = bd.key
                n += 1
            if bd.hold and not b.get("hold"):
                b["hold"] = True
                n += 1
            if bd.min_ms and b.get("press_ms") != bd.min_ms:
                b["press_ms"] = bd.min_ms   # Taste mindestens so lange halten, sonst löst das Spiel nicht aus
                n += 1
    return out, n


def read(cfg, root):
    """cfg aus games.json ("bindings"); wirft ValueError/OSError, wenn nicht lesbar."""
    adapter = ADAPTERS.get(cfg.get("adapter"))
    if not adapter:
        raise ValueError(f"unbekannter Belegungs-Adapter {cfg.get('adapter')!r}")
    return adapter(cfg, root)
