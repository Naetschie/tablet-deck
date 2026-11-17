"""Belegungsdateien öffnen: Text (UTF-8/16), gepackt (gzip/zlib), Unreal-Spielstand (GVAS), sonst binär/verschlüsselt.

open_bytes(data) -> (art, inhalt):
  ("text", str)        lesbarer Text (JSON, XML, INI, Konfiguration)
  ("gvas", bytes)      Unreal-Engine-Spielstand (offenes Format, Strings darin lesbar)
  ("encrypted", None)  hohe Entropie ohne bekanntes Packformat - praktisch sicher verschlüsselt
  ("binary", bytes)    binär, aber nicht verschlüsselt (unbekanntes Format)
"""
import math
import zlib
from collections import Counter

MAX_UNPACKED = 8 * 1024 * 1024
ENCRYPTED_BITS = 7.2   # Bits je Byte; Text ~4-5, Binärdaten ~5-6, Verschlüsseltes/Gepacktes ~7.9


def entropy(data):
    if not data:
        return 0.0
    c, n = Counter(data), len(data)
    return -sum(v / n * math.log2(v / n) for v in c.values())


def _text(data):
    if data[:3] == b"\xef\xbb\xbf":
        data = data[3:]
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            return None
    if b"\x00" in data[:4096]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        # nur ein abgeschnittenes Zeichen am Ende ist kein Grund für „binär“
        if e.start >= len(data) - 3:
            return data[:e.start].decode("utf-8")
        bad = data.decode("utf-8", errors="replace").count("�")
        return data.decode("utf-8", errors="replace") if bad <= max(3, len(data) // 1000) else None


def _unpack(data):
    try:
        if data[:2] == b"\x1f\x8b":
            out = zlib.decompressobj(31).decompress(data, MAX_UNPACKED)   # gzip, begrenzt (keine Bombe)
        elif data[:1] == b"\x78" and data[1:2] in (b"\x01", b"\x5e", b"\x9c", b"\xda"):
            d = zlib.decompressobj()
            out = d.decompress(data, MAX_UNPACKED)
        else:
            return None
    except (OSError, zlib.error, EOFError):
        return None
    return out[:MAX_UNPACKED]


def open_bytes(data, depth=0):
    if not data:
        return "binary", data
    if data[:4] == b"GVAS":
        return "gvas", data
    t = _text(data)
    if t is not None:
        return "text", t
    if depth < 2:
        u = _unpack(data)
        if u is not None:
            return open_bytes(u, depth + 1)
    if entropy(data[:65536]) >= ENCRYPTED_BITS:
        return "encrypted", None
    return "binary", data
