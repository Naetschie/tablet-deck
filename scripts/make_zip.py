"""Weitergabe-Paket bauen:  python scripts/make_zip.py [--out DATEI] [--root ORDNER]

Inhalt: alle von git verwalteten Dateien (git ls-files) plus android/build/tablet-deck.apk, falls vorhanden
(sonst Warnung). Nie dabei: Geheimnisse, Schlüssel, Logs, Caches, persönliche Daten, PC-gebundene Einstellungen
(config.json, launcher.json - das Paket bringt config.example.json / launcher.example.json mit), tools/, dist/.

Eine Prüfliste bricht den Build ab (Exit-Code 1), wenn trotzdem etwas Geheimnisverdächtiges ins Paket käme
(Dateiname wie *.key / *.pem / .env oder Inhalt wie ein privater Schlüssel bzw. ein Anthropic-API-Schlüssel).
Die Funde werden ohne Inhalt gemeldet (nur Dateiname und Art). Ergebnis: dist/TabletDeck-<git describe oder Datum>.zip
"""
import argparse
import datetime
import fnmatch
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFIX = "TabletDeck"
APK = "android/build/tablet-deck.apk"

# Ordner (an beliebiger Stelle im Pfad), die nie ins Paket gehören
EXCLUDE_DIRS = {"secrets", "tls", "tools", "dist", "__pycache__", ".git", ".gradle", ".idea", ".vscode",
                ".papierkorb", "graphify-out",
                "eigene"}   # dashboards/eigene/: eigene Dashboards bleiben beim Nutzer
# Dateinamen-Muster (ohne Ordner, Groß-/Kleinschreibung egal)
EXCLUDE_NAMES = ["*.key", "*.keystore", "*.log", "*.log.*", "*.pyc", "*.tmp", "bookmarks.json", "web_history.json",
                 "mapgenie_cache*", "bindings_learned*", "ai_settings.json", "web-*.json", "sensors.json", "config.json", "launcher.json", "maps.json", "thumbs.db",
                 # interne Entwicklungsnotizen (Arbeitsweise, Stand, Details zum eigenen PC) - nicht weitergeben
                 "claude.md", "plan.md", "handoff-*.md", "weiter.md", "review.md"]

# Prüfliste: verdächtige Namen (nach dem Ausschließen darf nichts mehr passen) ...
SUSPECT_NAMES = ["*.key", "*.pem", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.ppk", ".env", ".env.*", "id_rsa*",
                 "id_ed25519*", "secret*.json", "*.secret", "*credentials*", "*token*.txt"]
# ... und verdächtige Inhalte (als Bytes; Muster so geschrieben, dass sie dieses Skript nicht selbst treffen)
SUSPECT_CONTENT = [
    ("privater Schlüssel (PEM)", re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("Anthropic-API-Schlüssel", re.compile(rb"sk-ant-[A-Za-z0-9_\-]{16,}")),
    ("GitHub-Token", re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("AWS-Zugangsschlüssel", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("Slack-Token", re.compile(rb"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("Bearer-Token", re.compile(rb"Bearer [A-Za-z0-9._~+/-]{24,}=*")),
    # langer Zufallswert direkt hinter key/token/secret/passwort (z. B. "secret": "…", token=…)
    ("Schlüssel/Token-Wert", re.compile(
        rb"(?i)(?:api[_-]?key|token|secret|passw(?:or)?d|kennwort)[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-+/]{32,}")),
]
MAX_SCAN = 64 * 1024 * 1024


def excluded(rel):
    """True, wenn die Datei (Pfad mit /) nicht ins Paket soll."""
    parts = rel.split("/")
    if any(p.lower() in EXCLUDE_DIRS for p in parts[:-1]):
        return True
    name = parts[-1].lower()
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_NAMES)


def git_files(root):
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True).stdout
    return [p.decode("utf-8") for p in out.split(b"\0") if p]


def select(root, tracked):
    """(Dateiliste fürs Paket, fehlende getrackte Dateien). APK wird extra angefügt."""
    root, files, missing = Path(root), [], []
    for rel in tracked:
        if excluded(rel):
            continue
        p = root / rel
        if p.is_symlink():
            # Verknüpfung: z.write packte den Inhalt des Ziels ein - auch außerhalb des Projekts
            missing.append(rel + " (Verknüpfung, ausgelassen)")
        elif p.is_file():
            files.append(rel)
        else:
            missing.append(rel)
    return sorted(set(files)), missing


def check_secrets(root, files):
    """Liste von Fundstellen "Datei: Grund" (ohne Inhalt). Leer = sauber."""
    root, found = Path(root), []
    for rel in files:
        name = rel.split("/")[-1].lower()
        for pat in SUSPECT_NAMES:
            if fnmatch.fnmatch(name, pat):
                found.append(f"{rel}: verdächtiger Dateiname ({pat})")
                break
        p = root / rel
        try:
            if p.stat().st_size > MAX_SCAN:
                found.append(f"{rel}: zu groß zum Prüfen (> {MAX_SCAN // (1024 * 1024)} MB)")
                continue
            data = p.read_bytes()
        except OSError as e:
            found.append(f"{rel}: nicht lesbar ({e.__class__.__name__})")
            continue
        for what, rx in SUSPECT_CONTENT:
            if rx.search(data):
                found.append(f"{rel}: Inhalt sieht nach {what} aus")
    return found


def version(root):
    try:
        out = subprocess.run(["git", "-C", str(root), "describe", "--tags", "--always", "--dirty"],
                             capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        out = ""
    out = re.sub(r"[^A-Za-z0-9._-]", "_", out)
    return out or datetime.date.today().isoformat()


def build(root, out=None, tracked=None):
    """Paket schreiben. Gibt (Zip-Pfad, Anzahl Dateien, Warnungen) zurück; wirft SystemExit bei Funden."""
    root = Path(root)
    tracked = git_files(root) if tracked is None else tracked
    files, missing = select(root, tracked)
    warnings = [f"getrackte Datei fehlt im Arbeitsordner, übersprungen: {m}" for m in missing]
    if (root / APK).is_file():
        files.append(APK)
    else:
        warnings.append(f"{APK} fehlt - Paket ohne APK (vorher: python android/build.py)")
    found = check_secrets(root, files)
    if found:
        raise SystemExit("Abbruch, geheimnisverdächtig:\n  " + "\n  ".join(found))
    out = Path(out) if out else root / "dist" / f"{PREFIX}-{version(root)}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for rel in files:
                z.write(root / rel, f"{PREFIX}/{rel}")
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink()
    return out, len(files), warnings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, default=ROOT, help="Projektordner (Standard: dieses Repo)")
    ap.add_argument("--out", type=Path, help="Ziel-Zip (Standard: dist/TabletDeck-<Version>.zip)")
    args = ap.parse_args(argv)
    out, n, warnings = build(args.root, args.out)
    for w in warnings:
        print("Warnung:", w, file=sys.stderr)
    print(f"{out}  ({n} Dateien, {out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
