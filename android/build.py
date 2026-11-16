"""Baut die Launcher-APK ohne Gradle: aapt2 -> javac -> d8 -> zipalign -> apksigner.

Aufruf: python android/build.py            (Ausgabe: android/build/tablet-deck.apk)
Benötigt tools/jdk/*, tools/android-sdk/{platforms/android-36,build-tools/36.0.0}.
Signatur: lokaler Schlüssel android/debug.keystore (wird beim ersten Lauf erzeugt, nicht im Git).
Die APK enthält nichts PC-Eigenes: die WLAN-CA schickt der Hub beim Anstecken per ADB (HubTrust.java).
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SDK = ROOT / "tools" / "android-sdk"
BT = SDK / "build-tools" / "36.0.0"
ANDROID_JAR = SDK / "platforms" / "android-36" / "android.jar"
JDK = next((ROOT / "tools" / "jdk").glob("jdk-17*"), None)
OUT = HERE / "build"
KEYSTORE = HERE / "debug.keystore"


def run(*cmd):
    print(">", " ".join(str(c) for c in cmd[:3]), "...")
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"FEHLER ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r.stdout


def main():
    if JDK is None or not ANDROID_JAR.exists() or not BT.exists():
        sys.exit("JDK 17 oder Android-SDK fehlt in tools/ (siehe docs/tablet-setup.md)")
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "gen").mkdir(parents=True)
    (OUT / "classes").mkdir()
    (OUT / "dex").mkdir()

    # 1) Ressourcen (ohne PC-eigene Daten: die WLAN-CA schickt der Hub per ADB, siehe HubTrust.java)
    res = OUT / "res"
    shutil.copytree(HERE / "res", res)
    run(BT / "aapt2.exe", "compile", "--dir", res, "-o", OUT / "res.zip")
    run(BT / "aapt2.exe", "link", "-I", ANDROID_JAR, "--manifest", HERE / "AndroidManifest.xml",
        "--java", OUT / "gen", "-o", OUT / "base.apk", OUT / "res.zip")

    # 2) Java -> class
    sources = [str(p) for p in (HERE / "src").rglob("*.java")] + [str(p) for p in (OUT / "gen").rglob("*.java")]
    # --release 8: nur die Java-8-API (die Android weitgehend abdeckt) statt der vollen JDK-17-API;
    # Lambdas entzuckert d8. android.jar liefert die android.*-Klassen.
    run(JDK / "bin" / "javac.exe", "--release", "8", "-encoding", "UTF-8", "-Xlint:-options",
        "-classpath", ANDROID_JAR, "-d", OUT / "classes", *sources)

    # 3) class -> dex
    classes = [str(p) for p in (OUT / "classes").rglob("*.class")]
    run(BT / "d8.bat", "--release", "--min-api", "30", "--lib", ANDROID_JAR, "--output", OUT / "dex", *classes)

    # 4) dex ins APK
    with zipfile.ZipFile(OUT / "base.apk", "a", zipfile.ZIP_DEFLATED) as z:
        z.write(OUT / "dex" / "classes.dex", "classes.dex")

    # 5) ausrichten und signieren
    run(BT / "zipalign.exe", "-p", "-f", "4", OUT / "base.apk", OUT / "aligned.apk")
    if not KEYSTORE.exists():
        run(JDK / "bin" / "keytool.exe", "-genkeypair", "-keystore", KEYSTORE, "-storepass", "android",
            "-keypass", "android", "-alias", "deck", "-keyalg", "RSA", "-keysize", "2048",
            "-validity", "10000", "-dname", "CN=Tablet Deck")
    apk = OUT / "tablet-deck.apk"
    run(BT / "apksigner.bat", "sign", "--ks", KEYSTORE, "--ks-pass", "pass:android",
        "--out", apk, OUT / "aligned.apk")
    run(BT / "apksigner.bat", "verify", apk)
    print(f"OK: {apk} ({apk.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    import os
    if JDK:
        os.environ["JAVA_HOME"] = str(JDK)
        os.environ["PATH"] = str(JDK / "bin") + os.pathsep + os.environ["PATH"]
    main()
