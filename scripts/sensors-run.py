"""Startpunkt des Sensor-Helfers im Programmverzeichnis.

scripts/install-sensors.ps1 kopiert diese Datei als run.py nach %ProgramFiles%\\TabletDeck\\sensors; die geplante
Aufgabe "Tablet Deck Sensors" startet sie mit höchsten Rechten:
    pythonw.exe -I run.py --data <Projektordner>
-I: keine site-packages des Nutzers, keine PYTHON*-Umgebungsvariablen, weder Skript- noch Arbeitsordner im
Suchpfad. Code kommt so nur aus Python selbst (nur Admin beschreibbar) und aus diesem Ordner (app\\, lib\\).
PresentMon und Log liegen fest hier - der vom Nutzer beschreibbare Projektordner liefert nur Daten.

Die Aufgabe erbt die Umgebung des Nutzers (auch HKCU\\Environment, von ihm änderbar). Deshalb wird sie vor
allen Importen auf eine feste Liste gesetzt: sonst könnten z. B. COR_PROFILER/COR_ENABLE_PROFILING oder
DOTNET_STARTUP_HOOKS eine DLL bzw. Assembly in die .NET-Laufzeit von LibreHardwareMonitor laden, oder ein
Ordner des Nutzers im PATH DLLs liefern.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Systemwerte, die Windows-Komponenten brauchen; alles andere (PATH, TEMP, APPDATA, COR_*, DOTNET_*, …) neu
KEEP = ("SystemRoot", "windir", "SystemDrive", "ComSpec", "PATHEXT", "OS", "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "PROCESSOR_LEVEL", "PROCESSOR_REVISION",
        "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData", "ALLUSERSPROFILE",
        "CommonProgramFiles", "CommonProgramFiles(x86)", "CommonProgramW6432", "COMPUTERNAME",
        "USERNAME", "USERDOMAIN")


def clean_environ(environ, here, python_dir):
    """Feste Umgebung für den Admin-Prozess (reine Funktion, getestet)."""
    keep = {k.lower() for k in KEEP}
    env = {k: v for k, v in environ.items() if k.lower() in keep}
    low = {k.lower(): v for k, v in env.items()}      # os.environ hat unter Windows GROSSE Schlüssel
    root = low.get("systemroot") or low.get("windir") or r"C:\Windows"
    env["PATH"] = os.pathsep.join([os.path.join(root, "System32"), root, python_dir])
    tmp = os.path.join(here, "logs", "tmp")       # nur Admin beschreibbar (statt %TEMP% des Nutzers)
    env["TEMP"] = env["TMP"] = tmp
    return env, tmp


if __name__ == "__main__":
    env, tmp = clean_environ(os.environ, HERE, os.path.dirname(sys.executable))
    os.environ.clear()
    os.environ.update(env)
    os.makedirs(tmp, exist_ok=True)

    sys.path[:0] = [os.path.join(HERE, "app"), os.path.join(HERE, "lib")]
    from bridge.sensors.__main__ import main  # noqa: E402

    # feste Angaben zuletzt: sie gelten auch dann, wenn die Aufgabe dieselben Optionen schon nennt
    sys.exit(main(sys.argv[1:] + ["--installed",
                                  "--presentmon", os.path.join(HERE, "PresentMon.exe"),
                                  "--log", os.path.join(HERE, "logs", "sensors.log")]))
