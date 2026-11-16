"""Hängt Parameter an die Kernel-Kommandozeile eines Android-boot.img (Header v0–v2) an.

Nur das 512-Byte-Feld `cmdline` (Offset 64) wird geändert; Kernel, Ramdisk und alle übrigen
Bytes bleiben gleich. Die `id`-Prüfsumme deckt die cmdline nicht ab, LK prüft sie ohnehin nicht.

Aufruf: python scripts/patch_boot_cmdline.py <boot.img> <ausgabe.img> "androidboot.selinux=permissive"
"""
import struct
import sys

src, dst, extra = sys.argv[1], sys.argv[2], sys.argv[3]
data = bytearray(open(src, "rb").read())
assert data[:8] == b"ANDROID!", "kein boot.img"
ver = struct.unpack("<I", data[40:44])[0]
# Achtung: bei alten Qualcomm-v0-Images steht an Offset 40 dt_size statt der Version
assert ver <= 2, f"Header-Version/dt_size {ver} an Offset 40 - nicht unterstützt"
old = bytes(data[64:576]).rstrip(b"\0").decode()
if extra in old.split():
    sys.exit(f"bereits enthalten: {extra}")
# gleichen Schlüssel ersetzen statt doppelt anhängen (welcher Wert gewinnt, wäre sonst unklar)
key = extra.split("=", 1)[0] + "="
parts = [p for p in old.split() if not p.startswith(key)]
new = " ".join(parts + [extra]).encode()
assert len(new) < 512, f"cmdline zu lang ({len(new)})"
data[64:576] = new.ljust(512, b"\0")
open(dst, "wb").write(data)
print(f"Header v{ver}, cmdline jetzt:\n{new.decode()}")
