"""Zuordnung stabile ID -> Rohsensor.

Ein Eintrag: {"label", "unit", "min", "max", "max_from", "factor", "from": [Kandidat, …]}
Ein Kandidat: {"source": "psutil|nvml|lhm|presentmon", dazu entweder
                 "path":   genauer Pfad des Rohsensors (Spalte „Pfad“ in --list), oder
                 "sensor": Name des Rohsensors, optional eingegrenzt mit "type" (LHM-Sensortyp) und
                           "hardware" (Anfang des Pfads, z. B. "/lpc"),
               optional "factor" (Wert wird multipliziert)}
Der erste Kandidat mit Wert gewinnt (z. B. NVML zuerst, sonst LHM).

sensors.json (nicht im Git) überschreibt oder ergänzt die eingebauten Standards, siehe sensors.example.json.
min/max sind die Skalengrenzen für Anzeigen (Balken, Zeiger), nicht gemessene Extremwerte.
"""
import json
import logging
import math
import re

log = logging.getLogger("sensors")

ENTRY_KEYS = ("label", "unit", "min", "max", "max_from", "factor")


def _own(source, ident):
    return [{"source": source, "path": ident}]


def _lhm(sensor, kind, hardware, factor=None):
    c = {"source": "lhm", "sensor": sensor, "type": kind, "hardware": hardware}
    if factor is not None:
        c["factor"] = factor
    return c


def _defaults():
    d = {}

    def add(ident, label, unit, src, lo=None, hi=None, **extra):
        d[ident] = {"label": label, "unit": unit, "min": lo, "max": hi, "from": src, **extra}

    # psutil - ohne Admin
    add("cpu.load", "CPU-Last", "%", _own("psutil", "cpu.load"), 0, 100)
    add("ram.used", "RAM belegt", "MB", _own("psutil", "ram.used"), 0, max_from="ram.total")
    add("ram.total", "RAM gesamt", "MB", _own("psutil", "ram.total"))
    add("net.down", "Download", "KB/s", _own("psutil", "net.down"), 0)
    add("net.up", "Upload", "KB/s", _own("psutil", "net.up"), 0)
    add("net.total_down", "Download gesamt", "MB", _own("psutil", "net.total_down"))
    add("net.total_up", "Upload gesamt", "MB", _own("psutil", "net.total_up"))

    # Grafikkarte: NVML zuerst, sonst der gleichnamige LHM-Sensor (LHM liest die Karte über NVAPI). Danach die
    # LHM-Namen von AMD (/gpu-amd) und Intel (/gpu-intel Arc, /gpu-intel-integrated) - Namen aus dem LHM-Quelltext
    # (AmdGpu.cs, IntelDiscreteGpu.cs, IntelIntegratedGpu.cs). Der Pfadanfang "/gpu-intel" erfasst beide
    # Intel-Arten. VRAM und PCIe gibt es nur bei NVIDIA (AMD/Intel melden den Speicher in unklarer Einheit).
    gpu = "/gpu-nvidia"
    others = ("/gpu-amd", "/gpu-intel")

    def both(ident, lhm, *more):
        return _own("nvml", ident) + [lhm, *more]

    def more(sensor, kind):
        return [_lhm(sensor, kind, hw) for hw in others]

    add("gpu.temp", "GPU-Temperatur", "°C", both("gpu.temp", _lhm("GPU Core", "Temperature", gpu), *more("GPU Core", "Temperature")), 0, 100)
    add("gpu.clock.core", "GPU-Takt", "MHz", both("gpu.clock.core", _lhm("GPU Core", "Clock", gpu), *more("GPU Core", "Clock")), 0)
    add("gpu.clock.mem", "GPU-Speichertakt", "MHz", both("gpu.clock.mem", _lhm("GPU Memory", "Clock", gpu), *more("GPU Memory", "Clock")), 0)
    # AMD/Intel: ein einzelner Lüfter heißt "GPU Fan" (ohne Nummer), mehrere "GPU Fan <n>"
    add("gpu.fan1", "GPU-Lüfter 1", "RPM",
        both("gpu.fan1", _lhm("GPU Fan 1", "Fan", gpu), *more("GPU Fan 1", "Fan"), *more("GPU Fan", "Fan")), 0)
    add("gpu.fan2", "GPU-Lüfter 2", "RPM",
        both("gpu.fan2", _lhm("GPU Fan 2", "Fan", gpu), *more("GPU Fan 2", "Fan")), 0)
    add("gpu.fan1.pct", "GPU-Lüfter 1 (Stufe)", "%",
        both("gpu.fan1.pct", _lhm("GPU Fan 1", "Control", gpu), *more("GPU Fan 1", "Control"),
             *more("GPU Fan", "Control")), 0, 100)
    add("gpu.fan2.pct", "GPU-Lüfter 2 (Stufe)", "%",
        both("gpu.fan2.pct", _lhm("GPU Fan 2", "Control", gpu), *more("GPU Fan 2", "Control")), 0, 100)
    add("gpu.power", "GPU-Leistung", "W",
        both("gpu.power", _lhm("GPU Package", "Power", gpu), *more("GPU Package", "Power"),
             _lhm("GPU Power", "Power", "/gpu-intel")), 0)
    add("gpu.vram.used", "VRAM belegt", "MB", both("gpu.vram.used", _lhm("GPU Memory Used", "SmallData", gpu)),
        0, max_from="gpu.vram.total")
    add("gpu.vram.total", "VRAM gesamt", "MB", both("gpu.vram.total", _lhm("GPU Memory Total", "SmallData", gpu)))
    add("gpu.load", "GPU-Last", "%", both("gpu.load", _lhm("GPU Core", "Load", gpu), *more("GPU Core", "Load")), 0, 100)
    add("gpu.load.memctl", "GPU-Speichercontroller", "%",
        both("gpu.load.memctl", _lhm("GPU Memory Controller", "Load", gpu)), 0, 100)
    add("gpu.pcie.rx", "PCIe Rx", "KB/s", both("gpu.pcie.rx", _lhm("GPU PCIe Rx", "Throughput", gpu, 1 / 1024)), 0)
    add("gpu.pcie.tx", "PCIe Tx", "KB/s", both("gpu.pcie.tx", _lhm("GPU PCIe Tx", "Throughput", gpu, 1 / 1024)), 0)
    # nur über LHM
    add("gpu.temp.hotspot", "GPU Hot Spot", "°C", [_lhm("GPU Hot Spot", "Temperature", gpu), *more("GPU Hot Spot", "Temperature")], 0, 110)
    add("gpu.temp.mem", "GPU-Speicher (Junction)", "°C", [_lhm("GPU Memory Junction", "Temperature", gpu)], 0, 110)
    add("gpu.volt.core", "GPU-Kernspannung", "V", [_lhm("GPU Core Voltage", "Voltage", gpu), *more("GPU Core", "Voltage")])
    add("gpu.load.video", "GPU Video Engine", "%", [_lhm("GPU Video Engine", "Load", gpu)], 0, 100)

    # CPU über LHM (Admin). Die Kerntakte cpu.clock.<n> entstehen je nach CPU in derive(); die festen IDs für die
    # 8 P-Kerne (P0-P7) und 4 E-Kerne (E8-E11) des i7-12700K bleiben als Alias erhalten (LHM zählt jeweils ab #1).
    # Namen laut LHM-Quelltext: IntelCpu.cs ("CPU Package", "Core Max"), Amd17Cpu.cs ("Core (Tctl/Tdie)",
    # "CCDs Max (Tdie)", Leistung "Package"), Amd10Cpu.cs ("CPU Cores").
    cpu = "/intelcpu"
    amd = "/amdcpu"
    for i in range(8):
        add(f"cpu.clock.p{i}", f"P-Kern {i}", "MHz", [_lhm(f"P-Core #{i + 1}", "Clock", cpu)], 0)
    for i in range(4):
        add(f"cpu.clock.e{i + 8}", f"E-Kern {i + 8}", "MHz", [_lhm(f"E-Core #{i + 1}", "Clock", cpu)], 0)
    add("cpu.temp.package", "CPU-Package", "°C",
        [_lhm("CPU Package", "Temperature", cpu), _lhm("Core (Tctl/Tdie)", "Temperature", amd),
         _lhm("Core (Tdie)", "Temperature", amd), _lhm("Core (Tctl)", "Temperature", amd),
         _lhm("CPU Cores", "Temperature", amd)], 0, 100)
    add("cpu.temp.core_max", "CPU-Kern (max.)", "°C",
        [_lhm("Core Max", "Temperature", cpu), _lhm("CCDs Max (Tdie)", "Temperature", amd)], 0, 100)
    add("cpu.power.package", "CPU-Package-Leistung", "W",
        [_lhm("CPU Package", "Power", cpu), _lhm("Package", "Power", amd)], 0)

    # Mainboard über LHM (Admin, Super-I/O). Nur Namen, die LHM selbst vergibt (SuperIOHardware.cs): beim NCT6687D
    # dieses PCs "CPU Fan", "System Fan #n", "+12V", "+5V", "DIMM". Weitere Lüfter anderer Boards ergänzt derive()
    # (fan.<Baustein>_<Nr>_<Kanal>). Weicht die Verdrahtung ab oder fehlt ein Wert: in sensors.json zuordnen.
    lpc = "/lpc"
    add("fan.cpu", "CPU-Lüfter", "RPM", [_lhm("CPU Fan", "Fan", lpc)], 0)
    for i in (1, 2, 3):
        add(f"fan.sys{i}", f"Systemlüfter {i}", "RPM", [_lhm(f"System Fan #{i}", "Fan", lpc)], 0)
    # Spannungen: nur Namen, die eindeutig die Schiene meinen. Mehrdeutiges (AVCC3, "Voltage #n", "DIMM A/B")
    # bleibt "-" und wird bei Bedarf in sensors.json zugeordnet.
    add("volt.12v", "+12 V", "V", [_lhm("+12V", "Voltage", lpc)], 0)
    add("volt.5v", "+5 V", "V", [_lhm("+5V", "Voltage", lpc)], 0)
    add("volt.3v3", "+3,3 V", "V", [_lhm("+3.3V", "Voltage", lpc), _lhm("+3.3V (AVCC)", "Voltage", lpc),
                                    _lhm("+3.3V (3VCC)", "Voltage", lpc), _lhm("3VCC", "Voltage", lpc),
                                    _lhm("VCC3V", "Voltage", lpc)], 0)
    add("volt.dram", "DRAM", "V", [_lhm("DIMM", "Voltage", lpc), _lhm("VDIMM", "Voltage", lpc),
                                   _lhm("DRAM", "Voltage", lpc)], 0)

    # PresentMon (Admin bzw. Gruppe Leistungsprotokollbenutzer)
    add("fps.displayed", "FPS (angezeigt)", "FPS", _own("presentmon", "fps.displayed"), 0)
    add("fps.frametime", "Frametime", "ms", _own("presentmon", "fps.frametime"), 0)
    return d


DEFAULTS = _defaults()


def _clean_candidate(c):
    if not isinstance(c, dict) or not isinstance(c.get("source"), str):
        return None
    if not isinstance(c.get("path"), str) and not isinstance(c.get("sensor"), str):
        return None
    out = {k: c[k] for k in ("source", "path", "sensor", "type", "hardware") if isinstance(c.get(k), str)}
    f = c.get("factor")
    if isinstance(f, (int, float)) and not isinstance(f, bool):
        out["factor"] = f
    return out


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


_VALID = {
    "label": lambda v: isinstance(v, str),
    "unit": lambda v: isinstance(v, str),
    "min": lambda v: v is None or _num(v),
    "max": lambda v: v is None or _num(v),
    "max_from": lambda v: isinstance(v, str),
    "factor": _num,
}


def merge(defaults, override):
    """Standards + Inhalt von sensors.json. Unbrauchbare Einträge werden gemeldet und übergangen."""
    out = {k: dict(v) for k, v in defaults.items()}
    if not isinstance(override, dict):
        log.warning("sensors.json: Objekt erwartet - Standardzuordnung bleibt")
        return out
    for ident, e in override.items():
        if not isinstance(ident, str) or ident.startswith("_"):     # "_hinweis" o. Ä. = Kommentar
            continue
        if e is None:                                               # ID abschalten
            out.pop(ident, None)
            continue
        if not isinstance(e, dict):
            log.warning("sensors.json: %s übergangen (Objekt erwartet)", ident)
            continue
        bad = [k for k in ENTRY_KEYS if k in e and not _VALID[k](e[k])]
        if bad:
            log.warning("sensors.json: %s übergangen (ungültiger Typ bei %s)", ident, ", ".join(bad))
            continue
        entry = dict(out.get(ident, {"label": ident, "unit": "", "min": None, "max": None, "from": []}))
        cands = e["from"] if isinstance(e.get("from"), list) else ([e] if "source" in e else None)
        if cands is None and not entry["from"] and is_derived_id(ident):
            # nur umbenennen bzw. Grenzen ändern: erzeugte ID (derive) - der Eintrag wartet auf den Rohsensor
            entry["label"] = ""
            entry.update({k: e[k] for k in ENTRY_KEYS if k in e})
            out[ident] = entry
            continue
        if cands is not None:
            clean = [c for c in map(_clean_candidate, cands) if c]
            if len(clean) != len(cands) or not clean:
                log.warning("sensors.json: %s übergangen (source und path oder sensor nötig)", ident)
                continue
            entry["from"] = clean
        for k in ENTRY_KEYS:
            if k in e and not (k == "factor" and cands is not None and "from" not in e):
                entry[k] = e[k]
        if not entry["from"]:
            log.warning("sensors.json: %s übergangen (keine Quelle)", ident)
            continue
        out[ident] = entry
    return out


def load_mapping(path):
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError:
        return merge(DEFAULTS, {})
    try:
        return merge(DEFAULTS, json.loads(raw))
    except ValueError as e:
        log.warning("sensors.json unlesbar (%s) - Standardzuordnung bleibt", e)
        return merge(DEFAULTS, {})


def _matches(cand, raw):
    if raw.source != cand["source"]:
        return False
    if "path" in cand:
        return raw.path == cand["path"]
    if raw.name.lower() != cand["sensor"].lower():
        return False
    if "type" in cand and raw.kind.lower() != cand["type"].lower():
        return False
    return "hardware" not in cand or raw.path.lower().startswith(cand["hardware"].lower())


# ---------- Erzeugte Zuordnungen (je nach PC) ----------
_CORE = re.compile(r"(P-Core|E-Core|Core) #(\d+)")
_DERIVED_ID = re.compile(r"cpu\.clock\.\d+|fan\.(?!sys\d+$)[a-z0-9_]{0,59}\d")   # erzeugt: endet auf eine Ziffer
_CORE_HARDWARE = ("/intelcpu", "/amdcpu")
_CORE_LABEL = {"P-Core": "P-Kern", "E-Core": "E-Kern", "Core": "Kern"}


def is_derived_id(ident):
    """IDs, die derive() aus den Rohsensoren erzeugt (hier darf sensors.json nur umbenennen)."""
    return bool(_DERIVED_ID.fullmatch(ident))


def _lhm_raw(raw, kind, hardware):
    return raw.source == "lhm" and raw.kind.lower() == kind and raw.path.lower().startswith(hardware)


_p_max_seen = 0
MAX_CORES = 64     # mehr Takte übertragen wir nicht (das Raster zeigt ohnehin höchstens 32)
MAX_FANS = 32


def _derive_cores(raws):
    """Kerntakte cpu.clock.<i>: P-Kerne zuerst, dann E-Kerne, dann klassische "Core #n" (Intel und AMD), je nach
    LHM-Nummer sortiert und ab 0 durchnummeriert. LHM-Namen: IntelCpu.cs ("P-Core #n", "E-Core #n", "Core #n"),
    Amd17Cpu.cs ("Core #n", daneben "Core #n (Effective)" - passt nicht auf das Muster)."""
    found = []
    for raw in raws:
        m = _CORE.fullmatch(raw.name)
        if m and any(_lhm_raw(raw, "clock", h) for h in _CORE_HARDWARE):
            found.append((("P-Core", "E-Core", "Core").index(m.group(1)), int(m.group(2)), raw.path, m.group(1)))
    # Nummer aus der LHM-Nummer statt aus der Position: fehlt ein Takt kurz, verschieben sich die anderen nicht.
    # E-Kerne zählen hinter dem höchsten P-Kern weiter (wie LHM/HWiNFO: P0-P7, E8-E11).
    # höchster je gesehener P-Kern: fehlt ausgerechnet er kurz, rutschten die E-Kerne sonst um eins
    global _p_max_seen
    _p_max_seen = max([_p_max_seen] + [n for rank, n, _, _ in found if rank == 0])
    p_max = _p_max_seen
    out = {}
    for rank, n, path, kind in sorted(found):
        i = (p_max + n - 1) if rank == 1 else (n - 1)
        ident = f"cpu.clock.{i}"
        if i < 0 or i >= MAX_CORES or ident in out:
            continue
        out[ident] = {"label": f"{_CORE_LABEL[kind]} {i}", "unit": "MHz", "min": 0, "max": None,
                      "from": [{"source": "lhm", "path": path}]}
    return out


def _fan_id(path):
    parts = [p for p in path.lower().strip("/").split("/") if p not in ("lpc", "fan")]
    slug = re.sub(r"[^a-z0-9]+", "_", "_".join(parts)).strip("_") or "x"
    if len(slug) > 50:          # kürzen, aber eindeutig und mit dem Ende (Nummern) bleiben
        import hashlib
        slug = slug[:30].rstrip("_") + "_" + hashlib.sha1(slug.encode()).hexdigest()[:8] + "_" + slug[-10:].lstrip("_")
    if not slug[-1].isdigit():   # erzeugte IDs enden auf eine Ziffer (_DERIVED_ID)
        slug += "_0"
    return "fan." + slug


def _derive_fans(raws, taken):
    """Alle Mainboard-Lüfter (LHM-Typ Fan unter /lpc) mit Drehzahl > 0, die keine feste ID (fan.cpu, fan.sys<n>)
    belegt. Name aus LHM; die ID folgt dem Pfad und bleibt stabil, auch wenn ein Lüfter zwischendurch steht."""
    out = {}
    for raw in raws:
        if (raw.source, raw.path) in taken or not _lhm_raw(raw, "fan", "/lpc"):
            continue
        ident = _fan_id(raw.path)
        if raw.value > 0 and is_derived_id(ident) and ident not in out and len(out) < MAX_FANS:
            out[ident] = {"label": "", "unit": "RPM", "min": 0, "max": None,
                          "from": [{"source": "lhm", "path": raw.path}]}
    return out


def extend(mapping, raws):
    """Zuordnung + je nach Rohsensoren erzeugte IDs (Kerntakte cpu.clock.<n>, weitere Lüfter fan.<…>).
    Eigene Einträge (sensors.json) gewinnen; ein Eintrag ohne Quelle gibt nur Namen/Grenzen vor."""
    taken = {(raw.source, raw.path) for e in mapping.values() for _, raw in [_find(e, raws)] if raw is not None}
    derived = {**_derive_cores(raws), **_derive_fans(raws, taken)}
    if not derived and not any(not e["from"] for e in mapping.values()):
        return mapping
    out = dict(mapping)
    for ident, e in derived.items():
        cur = out.get(ident)
        if cur is None:
            out[ident] = e
        elif not cur["from"]:
            out[ident] = {**e, **{k: cur[k] for k in ENTRY_KEYS if cur.get(k) not in ("", None)}}
    return out


def _find(entry, raws):
    for cand in entry["from"]:
        for raw in raws:
            if _matches(cand, raw):
                return cand, raw
    return None, None


def _number(v):
    return v if _num(v) else None


def resolve(mapping, raws):
    """Rohsensoren -> Werteliste [{id, name, value, unit, min, max}] in der Reihenfolge der Zuordnung.
    IDs ohne aktuellen Wert fehlen."""
    found = {}
    mapping = extend(mapping, raws)
    for ident, entry in mapping.items():
        cand, raw = _find(entry, raws)
        if raw is None:
            continue
        f = _number(cand.get("factor"))
        g = _number(entry.get("factor"))
        value = raw.value * (1 if f is None else f) * (1 if g is None else g)
        if not math.isfinite(value):        # NaN/Inf aus der Quelle wären kein gültiges JSON und kein Messwert
            continue
        found[ident] = {"id": ident, "name": entry.get("label") or raw.name, "value": round(value, 3),
                        "unit": entry.get("unit") or raw.unit, "min": _number(entry.get("min")),
                        "max": _number(entry.get("max"))}
    for ident, item in found.items():
        ref = mapping[ident].get("max_from")
        if item["max"] is None and ref in found:        # z. B. RAM belegt: Obergrenze = RAM gesamt
            item["max"] = found[ref]["value"]
    return list(found.values())


# ---------------------------------------------------------------- alle Rohwerte (Auswahl „Alle Werte“ im Editor)
# Neben den festen IDs (cpu.load, gpu.temp, …) gibt der Helfer jeden LHM-Rohsensor unter einer aus seinem Pfad
# gebildeten ID weiter, z. B. /intelcpu/0/temperature/3 -> lhm.intelcpu.0.temperature.3. Der Pfad ist in LHM
# stabil (Bauteil/Index/Typ/Nummer); so kann man im Dashboard jeden Wert anzeigen, den LHM kennt.
RAW_SOURCES = ("lhm",)
RAW_MAX = 600              # Obergrenze (Antwortgröße); ein PC hat typisch 150-400 LHM-Werte
_RAW_BAD = re.compile(r"[^a-z0-9_]+")
_RAW_ID_MAX = 64           # wie SENSOR_ID in bridge/dashboard.py
_raw_warned = {}           # Meldungen nur einmal


def raw_id(source, path, force_hash=False):
    """Stabile ID [a-z0-9_.] (höchstens 64 Zeichen) aus Quelle und Pfad; zu lange Pfade (oder bei einer Kollision,
    force_hash) bekommen eine Prüfsumme des Originalpfads."""
    segs = [s for s in (_RAW_BAD.sub("_", p.lower()).strip("_") for p in str(path).split("/")) if s]
    ident = ".".join([source] + segs)
    if force_hash or len(ident) > _RAW_ID_MAX:
        import hashlib
        h = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:8]
        ident = ident[:_RAW_ID_MAX - 9].rstrip("._") + "." + h
    return ident


def raw_items(raws):
    """Alle Rohwerte der Quellen in RAW_SOURCES als Werteliste [{id, name, value, unit, group}] (Pfadreihenfolge)."""
    out, seen = [], set()
    for r in raws:
        if r.source not in RAW_SOURCES:
            continue
        if len(out) >= RAW_MAX:
            if not _raw_warned.get("cap"):
                _raw_warned["cap"] = True
                log.warning("Mehr als %d Rohwerte - der Rest wird nicht weitergegeben", RAW_MAX)
            break
        try:
            value = float(r.value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        ident = raw_id(r.source, r.path)
        if ident in seen:                       # zwei Pfade ergeben dieselbe ID: zweiter mit Prüfsumme
            ident = raw_id(r.source, r.path, force_hash=True)
            if ident in seen:
                continue
            if not _raw_warned.get(ident):
                _raw_warned[ident] = True
                log.info("Rohwert %s: ID-Kollision, eindeutige ID %s", r.path, ident)
        seen.add(ident)
        out.append({"id": ident, "name": str(r.name)[:80] or ident, "value": round(value, 3), "unit": r.unit or "",
                    "min": None, "max": None, "group": (getattr(r, "hw", "") or r.source)[:80]})
    return out


def assigned(mapping, raws):
    """{(Quelle, Pfad): [ID, …]} - welche Rohsensoren gerade welcher ID dienen (für --list)."""
    out = {}
    for ident, entry in extend(mapping, raws).items():
        _, raw = _find(entry, raws)
        if raw is not None:
            out.setdefault((raw.source, raw.path), []).append(ident)
    return out
