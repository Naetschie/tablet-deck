"""Erzeugt Magisk-sepolicy-Regeln aus gesammelten AVC-Ablehnungen (vereinfachtes audit2allow).

Aufruf: python scripts/avc2rule.py [--exclude <datei>] <ausgabe/sepolicy.rule> <avc-log> [<avc-log> ...]
--exclude: Regex-Muster (eins pro Zeile, # = Kommentar) auf "quelle ziel klasse"; Treffer entfallen.
Achtung: Magisk-Regeln umgehen neverallow-Prüfungen - die Ausgabe immer von Hand durchsehen.
Jede Zeile "avc:  denied { perms } ... scontext=u:r:S:s0 tcontext=u:object_r:T:s0 tclass=C"
wird zu "allow S T C { perms }" (gleiche S/T/C werden zusammengefasst).
Hinweis: Das erlaubt genau das, was im permissive-Betrieb beobachtet wurde - nicht mehr.
"""
import re
import sys
from collections import defaultdict

PAT = re.compile(r"avc:\s+denied\s+\{([^}]+)\}.*?scontext=u:r:([\w.]+):s0\S*\s+"
                 r"tcontext=u:(?:object_)?r:([\w.]+):s0\S*\s+tclass=(\w+)")
args = sys.argv[1:]
excludes = []
if args[:1] == ["--exclude"]:
    for ln in open(args[1], encoding="utf-8"):
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            excludes.append(re.compile(ln))
    args = args[2:]
out_path, logs = args[0], args[1:]

rules = defaultdict(set)
skipped = set()
for path in logs:
    for line in open(path, encoding="utf-8", errors="replace"):
        m = PAT.search(line)
        if m:
            perms, s, t, c = m.group(1).split(), m.group(2), m.group(3), m.group(4)
            if any(x.search(f"{s} {t} {c}") for x in excludes):
                skipped.add((s, t, c))
                continue
            rules[(s, t, c)].update(perms)

out = [f"allow {s} {t} {c} {{ {' '.join(sorted(p))} }}" for (s, t, c), p in sorted(rules.items())]
with open(out_path, "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(out) + "\n")
print(f"{len(out)} Regeln -> {out_path}, {len(skipped)} ausgeschlossen:")
for s, t, c in sorted(skipped):
    print(f"  - {s} {t} {c}")
