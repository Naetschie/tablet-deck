"""Tastenbelegungen der Spiele lesen (Engine-Adapter).

Jeder Adapter liefert ein Result: bindings {aktion: Binding(key, hold, note)}, freie Kombinationen für
Vorschläge und eine Beschreibung der Quelle. key=None heißt: Aktion bekannt, aber ohne nutzbare
Tastaturbelegung (note sagt warum).
"""
from collections import namedtuple

Binding = namedtuple("Binding", "key hold note")
Result = namedtuple("Result", "bindings free source")


def _cryengine(cfg, root):
    from . import cryengine
    return cryengine.read(cfg, root)


ADAPTERS = {"cryengine": _cryengine}


def read(cfg, root):
    """cfg aus games.json ("bindings"); wirft ValueError/OSError, wenn nicht lesbar."""
    adapter = ADAPTERS.get(cfg.get("adapter"))
    if not adapter:
        raise ValueError(f"unbekannter Belegungs-Adapter {cfg.get('adapter')!r}")
    return adapter(cfg, root)
