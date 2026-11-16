"""Unit-Tests für bridge/sensors (Sensor-Helfer): Adapter mit Mock-Daten, Zuordnung, PresentMon-CSV,
Token-Prüfung. Braucht keine echte Hardware, keine Adminrechte und kein Netz nach außen.

Aufruf: python -m unittest tests.test_sensors
"""
import io
import json
import re
import logging
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace as NS

from bridge.sensors import Adapter, Raw, Unavailable
from bridge.sensors.collector import Collector
from bridge.sensors.lhm_src import LhmSource
from bridge.sensors.mapping import DEFAULTS, assigned, load_mapping, merge, resolve
from bridge.sensors.nvml_src import NvmlSource
from bridge.sensors.presentmon_src import (FrameStats, PresentMonSource, SESSION, clean_target, parse_header,
                                           parse_row)
from bridge.sensors.psutil_src import PsutilSource
from bridge.sensors.server import load_or_create_token, make_server

MB = 1024 * 1024

# Kopfzeilen nach der PresentMon-Doku; die Datenzeilen sind erfundene Beispielwerte.
# 2.x (README-ConsoleApplication.md, v2.3.0)
CSV_V2 = """Application,ProcessID,SwapChainAddress,PresentRuntime,SyncInterval,PresentFlags,AllowsTearing,PresentMode,CPUStartTime,FrameTime,CPUBusy,CPUWait,GPULatency,GPUTime,GPUBusy,GPUWait,DisplayLatency,DisplayedTime,AnimationError,ClickToPhotonLatency,AllInputToPhotonLatency
Spiel.exe,4242,0x000001D2A3B4C5D0,DXGI,0,512,1,Hardware: Independent Flip,0.0000,10.0000,6.0000,4.0000,1.2000,8.1000,8.0000,0.1000,22.0000,10.0000,0.0100,NA,NA
Spiel.exe,4242,0x000001D2A3B4C5D0,DXGI,0,512,1,Hardware: Independent Flip,10.0000,10.0000,6.0000,4.0000,1.2000,8.1000,8.0000,0.1000,22.0000,NA,NA,NA,NA
Spiel.exe,4242,0x000001D2A3B4C5D0,DXGI,0,512,1,Hardware: Independent Flip,20.0000,20.0000,6.0000,14.0000,1.2000,8.1000,8.0000,0.1000,22.0000,30.0000,0.0100,NA,NA
"""
# 1.x bzw. --v1_metrics (README.md v1.9.2)
CSV_V1 = """Application,ProcessID,SwapChainAddress,Runtime,SyncInterval,PresentFlags,Dropped,TimeInSeconds,msInPresentAPI,msBetweenPresents,AllowsTearing,PresentMode,msUntilRenderComplete,msUntilDisplayed,msBetweenDisplayChange
Spiel.exe,4242,0x000001D2A3B4C5D0,DXGI,1,0,0,1.000,0.5,16.0,0,Hardware: Independent Flip,8.0,20.0,16.0
Spiel.exe,4242,0x000001D2A3B4C5D0,DXGI,1,0,1,1.016,0.5,16.0,0,Hardware: Independent Flip,8.0,0.0,0.0
"""
# aktuelle Fassung: Spalten mit „Ms“-Vorsatz, keine FrameTime-Spalte
HEAD_MS = ("Application,ProcessID,SwapChainAddress,PresentRuntime,SyncInterval,PresentFlags,AllowsTearing,"
           "PresentMode,CPUStartTime,MsCPUBusy,MsCPUWait,MsGPULatency,MsGPUTime,MsGPUBusy,MsGPUWait,"
           "DisplayLatency,DisplayedTime")


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def lhm_sensor(name, kind, path, value):
    return NS(Name=name, SensorType=kind, Identifier=path, Value=value)


class FakeHardware:
    def __init__(self, sensors=(), sub=(), broken=False):
        self.Sensors, self.SubHardware, self.broken, self.updates = list(sensors), list(sub), broken, 0

    def Update(self):
        self.updates += 1
        if self.broken:
            raise RuntimeError("Treiber hakt")


class FakeComputer:
    def __init__(self, hardware):
        self.Hardware, self.closed = hardware, False

    def Close(self):
        self.closed = True


def lhm_computer(admin=True):
    """Aufbau wie LHM ihn auf dem Ziel-PC meldet (Namen aus --list bzw. der LHM-Bibliothek)."""
    v = (lambda x: x) if admin else (lambda x: None)
    cpu = FakeHardware([
        lhm_sensor("CPU Total", "Load", "/intelcpu/0/load/0", 12.5),
        lhm_sensor("P-Core #1", "Clock", "/intelcpu/0/clock/1", v(4900.0)),
        lhm_sensor("P-Core #8", "Clock", "/intelcpu/0/clock/8", v(4700.0)),
        lhm_sensor("E-Core #1", "Clock", "/intelcpu/0/clock/9", v(3600.0)),
        lhm_sensor("E-Core #4", "Clock", "/intelcpu/0/clock/12", v(3500.0)),
        lhm_sensor("CPU Package", "Temperature", "/intelcpu/0/temperature/14", v(55.0)),
        lhm_sensor("Core Max", "Temperature", "/intelcpu/0/temperature/0", v(58.0)),
        lhm_sensor("CPU Package", "Power", "/intelcpu/0/power/0", 45.5 if admin else 0.0),
    ])
    sio = FakeHardware([
        lhm_sensor("CPU Fan", "Fan", "/lpc/nct6687d/0/fan/0", 900.0),
        lhm_sensor("System Fan #1", "Fan", "/lpc/nct6687d/0/fan/2", 700.0),
        lhm_sensor("System Fan #4", "Fan", "/lpc/nct6687d/0/fan/5", 650.0),
        lhm_sensor("+12V", "Voltage", "/lpc/nct6687d/0/voltage/0", 12.1),
        lhm_sensor("DIMM", "Voltage", "/lpc/nct6687d/0/voltage/4", 1.36),
        lhm_sensor("AVCC3", "Voltage", "/lpc/nct6687d/0/voltage/8", 3.34),
        lhm_sensor("CPU", "Temperature", "/lpc/nct6687d/0/temperature/0", 40.0),
    ])
    board = FakeHardware(sub=[sio] if admin else [])
    gpu = FakeHardware([
        lhm_sensor("GPU Core", "Temperature", "/gpu-nvidia/0/temperature/0", 44.0),
        lhm_sensor("GPU Hot Spot", "Temperature", "/gpu-nvidia/0/temperature/2", 52.0),
        lhm_sensor("GPU Core", "Load", "/gpu-nvidia/0/load/0", 30.0),
        lhm_sensor("GPU PCIe Rx", "Throughput", "/gpu-nvidia/0/throughput/0", 2048.0),
    ])
    return FakeComputer([board, cpu, gpu])


class NVMLError_NotSupported(Exception):
    pass


class NVMLError_GpuIsLost(Exception):
    pass


class FakeNvml:
    NVML_TEMPERATURE_GPU = 0
    NVML_CLOCK_GRAPHICS = 0
    NVML_CLOCK_MEM = 2
    NVML_PCIE_UTIL_TX_BYTES = 0
    NVML_PCIE_UTIL_RX_BYTES = 1

    def __init__(self):
        self.calls = {}
        self.down = False

    def _count(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1

    def nvmlInit(self):
        self._count("init")

    def nvmlShutdown(self):
        self.down = True

    def nvmlDeviceGetHandleByIndex(self, i):
        return "karte"

    def nvmlDeviceGetTemperature(self, h, kind):
        return 61

    def nvmlDeviceGetClockInfo(self, h, kind):
        return 7001 if kind == self.NVML_CLOCK_MEM else 2100

    def nvmlDeviceGetPowerUsage(self, h):
        return 123456               # mW

    def nvmlDeviceGetMemoryInfo(self, h):
        return NS(used=4096 * MB, total=16384 * MB)

    def nvmlDeviceGetUtilizationRates(self, h):
        return NS(gpu=87, memory=33)

    def nvmlDeviceGetPcieThroughput(self, h, kind):
        self._count("pcie")
        raise NVMLError_NotSupported("Not Supported")

    def nvmlDeviceGetFanSpeedRPM(self, h):
        return 1500

    def nvmlDeviceGetFanSpeed_v2(self, h, i):
        return (40, 45)[i]


class PsutilTest(unittest.TestCase):
    def test_values_and_rates(self):
        clock = Clock()
        net = {"Ethernet": NS(bytes_recv=10 * MB, bytes_sent=2 * MB),
               "Loopback Pseudo-Interface 1": NS(bytes_recv=999 * MB, bytes_sent=999 * MB),
               "WLAN": NS(bytes_recv=500 * MB, bytes_sent=500 * MB)}       # nicht verbunden
        ps = NS(cpu_percent=lambda interval: 37.5,
                virtual_memory=lambda: NS(total=32768 * MB, available=24576 * MB),
                net_io_counters=lambda pernic: net,
                net_if_stats=lambda: {"Ethernet": NS(isup=True), "WLAN": NS(isup=False),
                                      "Loopback Pseudo-Interface 1": NS(isup=True)})
        src = PsutilSource(ps, clock)
        src.start()
        first = {r.path: r.value for r in src.read()}
        self.assertEqual(first["cpu.load"], 37.5)
        self.assertEqual((first["ram.used"], first["ram.total"]), (8192, 32768))
        self.assertEqual(first["net.total_down"], 0)        # Summe der Deltas seit Start
        self.assertNotIn("net.down", first)                 # Rate erst mit Bezugspunkt
        clock.t += 2
        net["Ethernet"] = NS(bytes_recv=12 * MB, bytes_sent=2 * MB + 4096)
        second = {r.path: r.value for r in src.read()}
        self.assertEqual(second["net.down"], 1024)          # 2 MB in 2 s = 1024 KB/s
        self.assertEqual(second["net.up"], 2)
        self.assertEqual((second["net.total_down"], second["net.total_up"]), (2, 4096 / MB))
        clock.t += 1
        net["Ethernet"] = NS(bytes_recv=0, bytes_sent=0)    # Zähler zurückgesetzt
        third = {r.path: r.value for r in src.read()}
        self.assertEqual(third["net.down"], 0)
        self.assertEqual(third["net.total_down"], 2)        # monoton, springt nicht zurück

    def test_interface_change_gives_no_spike(self):
        clock = Clock()
        net = {"Ethernet": NS(bytes_recv=10 * MB, bytes_sent=0)}
        stats = {"Ethernet": NS(isup=True), "WLAN": NS(isup=True)}
        ps = NS(cpu_percent=lambda interval: 1.0,
                virtual_memory=lambda: NS(total=MB, available=MB),
                net_io_counters=lambda pernic: net, net_if_stats=lambda: stats)
        src = PsutilSource(ps, clock)
        src.start()
        src.read()
        clock.t += 1
        net["WLAN"] = NS(bytes_recv=900 * MB, bytes_sent=900 * MB)      # neue Schnittstelle taucht auf
        net["Ethernet"] = NS(bytes_recv=11 * MB, bytes_sent=0)
        r = {x.path: x.value for x in src.read()}
        self.assertEqual((r["net.down"], r["net.up"]), (1024, 0))       # nur Ethernet zählt, WLAN erst ab jetzt
        clock.t += 1
        del net["Ethernet"]                                             # Schnittstelle verschwindet
        net["WLAN"] = NS(bytes_recv=901 * MB, bytes_sent=900 * MB)
        r = {x.path: x.value for x in src.read()}
        self.assertEqual(r["net.down"], 1024)
        self.assertEqual(r["net.total_down"], 2)


class NvmlTest(unittest.TestCase):
    def test_values_units_and_unsupported(self):
        n = FakeNvml()
        src = NvmlSource(n)
        src.start()
        v = {r.path: r for r in src.read()}
        self.assertEqual(v["gpu.temp"].value, 61)
        self.assertEqual((v["gpu.clock.core"].value, v["gpu.clock.mem"].value), (2100, 7001))
        self.assertAlmostEqual(v["gpu.power"].value, 123.456)
        self.assertEqual((v["gpu.vram.used"].value, v["gpu.vram.total"].value, v["gpu.vram.used"].unit),
                         (4096, 16384, "MB"))
        self.assertEqual((v["gpu.load"].value, v["gpu.load.memctl"].value), (87, 33))
        self.assertEqual((v["gpu.fan1"].value, v["gpu.fan1.pct"].value, v["gpu.fan2.pct"].value), (1500, 40, 45))
        self.assertNotIn("gpu.fan2", v)                     # diese Hülle kennt nur die Drehzahl von Lüfter 1
        self.assertNotIn("gpu.pcie.rx", v)
        src.read()
        self.assertEqual(n.calls["pcie"], 2)                # rx + tx je einmal, danach nicht mehr probiert
        src.close()
        self.assertTrue(n.down)

    def test_init_error_is_transient(self):
        n = FakeNvml()
        n.nvmlInit = lambda: (_ for _ in ()).throw(RuntimeError("Driver Not Loaded"))
        with self.assertRaises(RuntimeError):               # kein Unavailable: später neu versuchen
            NvmlSource(n).start()
        c = Collector([NvmlSource(n)], DEFAULTS, clock=Clock())
        with self.assertLogs("sensors", logging.WARNING):
            c.sample()
        self.assertEqual(c.snapshot()["sources"], {"nvml": "Fehler: RuntimeError"})
        self.assertFalse(c.states[0].dead)

    def test_shutdown_after_failed_start(self):
        n = FakeNvml()
        n.nvmlDeviceGetHandleByIndex = lambda i: (_ for _ in ()).throw(NVMLError_GpuIsLost("lost"))
        with self.assertRaises(NVMLError_GpuIsLost):
            NvmlSource(n).start()
        self.assertTrue(n.down)

    def test_transient_error_is_not_skipped_forever(self):
        n = FakeNvml()
        src = NvmlSource(n)
        src.start()
        good = n.nvmlDeviceGetTemperature
        n.nvmlDeviceGetTemperature = lambda h, k: (_ for _ in ()).throw(NVMLError_GpuIsLost("lost"))
        v = {r.path for r in src.read()}
        self.assertNotIn("gpu.temp", v)                     # Teilausfall: übrige Werte kommen
        self.assertIn("gpu.load", v)
        n.nvmlDeviceGetTemperature = good
        self.assertIn("gpu.temp", {r.path for r in src.read()})     # nicht dauerhaft übersprungen

    def test_total_failure_raises(self):
        n = FakeNvml()
        src = NvmlSource(n)
        src.start()
        src.read()                                          # dauerhaft Nicht-Unterstütztes ist jetzt übersprungen

        def lost(*a):
            raise NVMLError_GpuIsLost("lost")
        for f in ("nvmlDeviceGetTemperature", "nvmlDeviceGetClockInfo", "nvmlDeviceGetPowerUsage",
                  "nvmlDeviceGetMemoryInfo", "nvmlDeviceGetUtilizationRates", "nvmlDeviceGetFanSpeedRPM",
                  "nvmlDeviceGetFanSpeed_v2"):
            setattr(n, f, lost)
        with self.assertRaises(NVMLError_GpuIsLost):
            src.read()


class LhmTest(unittest.TestCase):
    def test_admin_reads_all_levels(self):
        pc = lhm_computer()
        src = LhmSource(lambda: pc, admin=True)
        src.start()
        raws = src.read()
        self.assertEqual(src.status, "ok")
        byp = {r.path: r for r in raws}
        self.assertEqual((byp["/lpc/nct6687d/0/fan/2"].value, byp["/lpc/nct6687d/0/fan/2"].unit), (700, "RPM"))
        self.assertEqual((byp["/intelcpu/0/clock/1"].kind, byp["/intelcpu/0/clock/1"].unit), ("Clock", "MHz"))
        self.assertEqual(byp["/intelcpu/0/power/0"].value, 45.5)
        src.close()
        self.assertTrue(pc.closed)

    def test_without_admin_reports_and_keeps_rest(self):
        src = LhmSource(lambda: lhm_computer(admin=False), admin=False)
        src.start()
        paths = {r.path for r in src.read()}
        self.assertEqual(src.status, "kein Admin")
        self.assertIn("/gpu-nvidia/0/temperature/0", paths)     # GPU geht auch ohne Admin
        self.assertNotIn("/intelcpu/0/clock/1", paths)          # leer -> ausgelassen
        self.assertNotIn("/intelcpu/0/power/0", paths)          # 0 W ohne Admin wäre ein falscher Wert

    def test_failed_open_closes_computer(self):
        import sys
        import types
        pc = lhm_computer()

        def bad_open():
            raise OSError("Treiber")
        pc.Open = bad_open
        mod = types.ModuleType("HardwareMonitor")
        hw = types.ModuleType("HardwareMonitor.Hardware")
        hw.Computer = lambda: pc
        mod.Hardware = hw
        saved = {k: sys.modules.get(k) for k in ("HardwareMonitor", "HardwareMonitor.Hardware")}
        sys.modules["HardwareMonitor"], sys.modules["HardwareMonitor.Hardware"] = mod, hw
        try:
            from bridge.sensors.lhm_src import _open_computer
            with self.assertRaises(OSError):
                _open_computer()
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        self.assertTrue(pc.closed)

    def test_broken_hardware_does_not_stop_others(self):
        pc = lhm_computer()
        pc.Hardware[1].broken = True
        src = LhmSource(lambda: pc, admin=True)
        src.start()
        self.assertIn("/gpu-nvidia/0/load/0", {r.path for r in src.read()})


class MappingTest(unittest.TestCase):
    def setUp(self):
        src = LhmSource(lambda: lhm_computer(), admin=True)
        src.start()
        self.raws = src.read()

    def values(self, mapping=None, raws=None):
        return {v["id"]: v for v in resolve(mapping or DEFAULTS, self.raws if raws is None else raws)}

    def test_builtin_lhm_ids(self):
        v = self.values()
        self.assertEqual((v["cpu.clock.p0"]["value"], v["cpu.clock.p7"]["value"]), (4900, 4700))
        self.assertEqual((v["cpu.clock.e8"]["value"], v["cpu.clock.e11"]["value"]), (3600, 3500))
        self.assertEqual((v["cpu.temp.package"]["value"], v["cpu.temp.core_max"]["value"]), (55, 58))
        self.assertEqual(v["cpu.power.package"]["value"], 45.5)     # gleicher Name wie die Temperatur, anderer Typ
        self.assertEqual((v["fan.cpu"]["value"], v["fan.sys1"]["value"]), (900, 700))
        self.assertEqual((v["volt.12v"]["value"], v["volt.dram"]["value"]), (12.1, 1.36))
        self.assertEqual(v["gpu.temp.hotspot"]["value"], 52)
        self.assertNotIn("cpu.clock.p3", v)                         # kein Rohsensor -> ID fehlt
        self.assertNotIn("volt.3v3", v)                             # AVCC3 wird nicht geraten
        self.assertNotIn("fan.sys2", v)
        self.assertEqual(set(v["fan.cpu"]), {"id", "name", "value", "unit", "min", "max"})

    def test_first_source_wins_and_factor(self):
        v = self.values()
        self.assertEqual(v["gpu.temp"]["value"], 44)                # NVML fehlt -> LHM
        self.assertEqual((v["gpu.pcie.rx"]["value"], v["gpu.pcie.rx"]["unit"]), (2, "KB/s"))   # B/s -> KB/s
        v = self.values(raws=self.raws + [Raw("nvml", "gpu.temp", "GPU-Temperatur", 46.0, "°C")])
        self.assertEqual(v["gpu.temp"]["value"], 46)

    def test_max_from_other_id(self):
        raws = [Raw("psutil", "ram.used", "", 8192.0, "MB"), Raw("psutil", "ram.total", "", 32768.0, "MB")]
        v = self.values(raws=raws)
        self.assertEqual((v["ram.used"]["min"], v["ram.used"]["max"]), (0, 32768))

    def test_override_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sensors.json"
            p.write_text(json.dumps({
                "_hinweis": "Kommentar",
                "fan.sys2": {"source": "lhm", "path": "/lpc/nct6687d/0/fan/5"},
                "volt.3v3": {"source": "lhm", "sensor": "avcc3", "type": "Voltage", "hardware": "/lpc", "factor": 2},
                "board.temp": {"source": "lhm", "sensor": "CPU", "type": "Temperature", "hardware": "/lpc",
                               "label": "Board", "unit": "°C", "max": 90},
                "fan.cpu": None,
                "kaputt": {"source": "lhm"},
                "auch kaputt": 5,
            }), encoding="utf-8")
            with self.assertLogs("sensors", logging.WARNING) as logs:
                m = load_mapping(p)
            self.assertEqual(len(logs.output), 2)
            v = self.values(m)
            self.assertEqual((v["fan.sys2"]["value"], v["fan.sys2"]["name"]), (650, "Systemlüfter 2"))
            self.assertEqual(v["volt.3v3"]["value"], 6.68)
            self.assertEqual((v["board.temp"]["value"], v["board.temp"]["name"], v["board.temp"]["max"]),
                             (40, "Board", 90))
            self.assertNotIn("fan.cpu", v)
            self.assertNotIn("kaputt", m)
            self.assertIn("fan.cpu", DEFAULTS)                      # Standards bleiben unverändert
            self.assertEqual(assigned(m, self.raws)[("lhm", "/lpc/nct6687d/0/fan/5")], ["fan.sys2"])
            p.write_text("{kaputt", encoding="utf-8")
            with self.assertLogs("sensors", logging.WARNING):
                self.assertEqual(set(load_mapping(p)), set(DEFAULTS))
            self.assertEqual(set(load_mapping(Path(d) / "fehlt.json")), set(DEFAULTS))

    def test_invalid_types_are_dropped_with_one_log(self):
        base = {"cpu.load": dict(DEFAULTS["cpu.load"])}
        bad = {"cpu.load": {"label": 5, "max": "100"},
               "x.a": {"source": "psutil", "path": "cpu.load", "factor": "2"},
               "x.b": {"source": "psutil", "path": "cpu.load", "min": True},
               "x.c": {"source": "psutil", "path": "cpu.load", "max": float("nan")},
               "x.ok": {"source": "psutil", "path": "cpu.load", "label": "gut", "min": None, "max": 5}}
        with self.assertLogs("sensors", logging.WARNING) as logs:
            out = merge(base, bad)
        self.assertEqual(len(logs.output), 4)
        self.assertEqual(out["cpu.load"], base["cpu.load"])             # unverändert, nicht halb überschrieben
        self.assertEqual(set(out), {"cpu.load", "x.ok"})

    def test_non_finite_values_are_dropped(self):
        nan, inf = float("nan"), float("inf")
        raws = [Raw("psutil", "cpu.load", "x", nan, "%"), Raw("psutil", "ram.total", "x", inf, "MB"),
                Raw("psutil", "ram.used", "x", 5.0, "MB")]
        ids = [v["id"] for v in resolve(DEFAULTS, raws)]
        self.assertEqual(ids, ["ram.used"])
        m = {"a": {"label": "a", "unit": "", "min": None, "max": nan,
                   "from": [{"source": "psutil", "path": "ram.used"}]}}
        self.assertIsNone(resolve(m, raws)[0]["max"])

    def test_example_file_is_valid_and_changes_nothing(self):
        example = json.loads((Path(__file__).resolve().parent.parent / "sensors.example.json")
                             .read_text(encoding="utf-8"))
        self.assertEqual(merge(DEFAULTS, example), merge(DEFAULTS, {}))


def lraw(path, name, kind, value, unit=""):
    return Raw("lhm", path, name, float(value), unit, kind)


def vals(raws, mapping=None):
    return {v["id"]: v for v in resolve(mapping or DEFAULTS, raws)}


class DynamicMappingTest(unittest.TestCase):
    """Sensoren anderer PCs: Kerne, Lüfter, Spannungen, GPU - aus Mock-Rohdaten (Namen laut LHM-Quelltext)."""

    def test_intel_hybrid_cores_are_numbered_p_first_and_old_ids_stay(self):
        raws = [lraw(f"/intelcpu/0/clock/{n}", f"E-Core #{n}", "Clock", 3000 + n) for n in (1, 2)] + \
               [lraw(f"/intelcpu/0/clock/{n + 2}", f"P-Core #{n}", "Clock", 4000 + n) for n in (1, 2, 3)] + \
               [lraw("/intelcpu/0/clock/0", "Bus Speed", "Clock", 100)]
        v = vals(raws)
        self.assertEqual([v[f"cpu.clock.{i}"]["value"] for i in range(5)], [4001, 4002, 4003, 3001, 3002])
        self.assertEqual([v[f"cpu.clock.{i}"]["name"] for i in range(5)],
                         ["P-Kern 0", "P-Kern 1", "P-Kern 2", "E-Kern 3", "E-Kern 4"])
        self.assertNotIn("cpu.clock.5", v)
        self.assertEqual((v["cpu.clock.p0"]["value"], v["cpu.clock.e8"]["value"]), (4001, 3001))    # Alias bleibt
        self.assertEqual(v["cpu.clock.0"]["unit"], "MHz")
        self.assertEqual(v["cpu.clock.0"]["min"], 0)

    def test_intel_classic_cores(self):
        raws = [lraw(f"/intelcpu/0/clock/{n}", f"Core #{n}", "Clock", 3500 + n) for n in (3, 1, 2, 4)]
        v = vals(raws)
        self.assertEqual([v[f"cpu.clock.{i}"]["value"] for i in range(4)], [3501, 3502, 3503, 3504])    # nach Nummer
        self.assertEqual(v["cpu.clock.2"]["name"], "Kern 2")
        self.assertNotIn("cpu.clock.p0", v)

    def test_amd_cores_temperature_and_power(self):
        raws = [lraw(f"/amdcpu/0/clock/{n}", f"Core #{n}", "Clock", 4400 + n) for n in range(1, 7)] + [
            lraw("/amdcpu/0/clock/9", "Core #1 (Effective)", "Clock", 1),      # kein Kerntakt im Sinn des Rasters
            lraw("/amdcpu/0/clock/0", "Bus Speed", "Clock", 100),
            lraw("/amdcpu/0/clock/10", "Cores (Average)", "Clock", 4000),
            lraw("/amdcpu/0/temperature/0", "Core (Tctl/Tdie)", "Temperature", 61.5),
            lraw("/amdcpu/0/temperature/3", "CCDs Max (Tdie)", "Temperature", 58),
            lraw("/amdcpu/0/temperature/5", "Core #1", "Temperature", 50),      # Temperatur, kein Takt
            lraw("/amdcpu/0/power/0", "Package", "Power", 88.25),
            lraw("/amdcpu/0/power/1", "Core #1 (SMU)", "Power", 5)]
        v = vals(raws)
        self.assertEqual(sorted(i for i in v if i.startswith("cpu.clock.")), [f"cpu.clock.{i}" for i in range(6)])
        self.assertEqual(v["cpu.clock.0"]["value"], 4401)
        self.assertEqual((v["cpu.temp.package"]["value"], v["cpu.temp.core_max"]["value"]), (61.5, 58))
        self.assertEqual(v["cpu.power.package"]["value"], 88.25)
        raws = [lraw("/amdcpu/0/temperature/0", "Core (Tdie)", "Temperature", 55),
                lraw("/amdcpu/0/temperature/1", "Core (Tctl)", "Temperature", 65)]
        self.assertEqual(vals(raws)["cpu.temp.package"]["value"], 55)           # Tdie vor Tctl (Offset)

    def test_cpu_name_must_be_a_cpu(self):
        raws = [lraw("/gpu-nvidia/0/clock/0", "Core #1", "Clock", 1500),
                lraw("/lpc/nct6687d/0/clock/0", "Core #1", "Clock", 1)]
        self.assertFalse([i for i in vals(raws) if i.startswith("cpu.clock.")])

    def test_fans_are_added_when_running_and_fixed_ids_win(self):
        base = "/lpc/it8688e/0/fan/"
        raws = [lraw(base + "0", "CPU Fan", "Fan", 1100), lraw(base + "1", "Chassis Fan #1", "Fan", 800),
                lraw(base + "2", "Chassis Fan #2", "Fan", 0),                   # steht: erscheint nicht
                lraw(base + "3", "Pump Fan", "Fan", 2400),
                lraw("/gpu-nvidia/0/fan/0", "GPU Fan 1", "Fan", 1500),           # nicht Mainboard
                lraw("/lpc/it8688e/0/temperature/0", "CPU Fan", "Temperature", 30)]
        v = vals(raws)
        self.assertEqual(v["fan.cpu"]["value"], 1100)
        self.assertEqual(v["fan.it8688e_0_1"]["name"], "Chassis Fan #1")
        self.assertEqual(v["fan.it8688e_0_3"]["value"], 2400)
        self.assertEqual(v["fan.it8688e_0_1"]["unit"], "RPM")
        self.assertEqual(sorted(i for i in v if i.startswith("fan.")),
                         ["fan.cpu", "fan.it8688e_0_1", "fan.it8688e_0_3"])       # kein doppeltes fan.cpu
        self.assertEqual(list(v).index("fan.cpu") < list(v).index("fan.it8688e_0_1"), True)
        raws[2] = lraw(base + "2", "Chassis Fan #2", "Fan", 650)
        self.assertEqual(vals(raws)["fan.it8688e_0_2"]["value"], 650)            # gleiche ID, sobald er läuft

    def test_fan_taken_by_override_is_not_listed_twice(self):
        raws = [lraw("/lpc/nct6687d/0/fan/5", "System Fan #4", "Fan", 650)]
        m = merge(DEFAULTS, {"fan.sys9": {"source": "lhm", "path": "/lpc/nct6687d/0/fan/5", "label": "Pumpe"}})
        v = vals(raws, m)
        self.assertEqual(v["fan.sys9"]["name"], "Pumpe")
        self.assertEqual([i for i in v if i.startswith("fan.")], ["fan.sys9"])
        self.assertEqual(assigned(m, raws)[("lhm", "/lpc/nct6687d/0/fan/5")], ["fan.sys9"])

    def test_generated_ids_can_be_renamed_and_overridden(self):
        raws = [lraw("/lpc/it8688e/0/fan/1", "Chassis Fan #1", "Fan", 800),
                lraw("/intelcpu/0/clock/1", "P-Core #1", "Clock", 4900)]
        with self.assertNoLogs("sensors", logging.WARNING):
            m = merge(DEFAULTS, {"fan.it8688e_0_1": {"label": "Gehäuse vorn"}, "cpu.clock.0": {"label": "Haupt"}})
        v = vals(raws, m)
        self.assertEqual((v["fan.it8688e_0_1"]["name"], v["fan.it8688e_0_1"]["value"]), ("Gehäuse vorn", 800))
        self.assertEqual((v["cpu.clock.0"]["name"], v["cpu.clock.0"]["min"], v["cpu.clock.0"]["unit"]),
                         ("Haupt", 0, "MHz"))
        # ohne den Rohsensor bleibt es still (kein Wert, keine Fehlermeldung)
        self.assertNotIn("fan.it8688e_0_1", vals([], m))
        # eigener Eintrag mit Quelle gewinnt gegen die erzeugte Zuordnung
        m = merge(DEFAULTS, {"cpu.clock.0": {"source": "lhm", "path": "/intelcpu/0/clock/1", "factor": 0.001}})
        self.assertEqual(vals(raws, m)["cpu.clock.0"]["value"], 4.9)
        # beliebige unbekannte ID ohne Quelle bleibt ein Fehler
        with self.assertLogs("sensors", logging.WARNING):
            merge(DEFAULTS, {"fan.gibtsnicht": {"label": "x"}})

    def test_voltages_use_unambiguous_names_only(self):
        raws = [lraw("/lpc/it8688e/0/voltage/0", "+12V", "Voltage", 12.05),
                lraw("/lpc/it8688e/0/voltage/1", "+5V", "Voltage", 5.02),
                lraw("/lpc/it8688e/0/voltage/2", "+3.3V (AVCC)", "Voltage", 3.31),
                lraw("/lpc/it8688e/0/voltage/3", "VDIMM", "Voltage", 1.35),
                lraw("/lpc/it8688e/0/voltage/4", "Voltage #5", "Voltage", 1.0),
                lraw("/lpc/it8688e/0/voltage/5", "AVCC3", "Voltage", 3.4)]
        v = vals(raws)
        self.assertEqual([v[i]["value"] for i in ("volt.12v", "volt.5v", "volt.3v3", "volt.dram")],
                         [12.05, 5.02, 3.31, 1.35])
        v = vals(raws[4:])
        self.assertFalse([i for i in v if i.startswith("volt.")])               # AVCC3 / Voltage #n nicht geraten

    def test_gpu_amd_and_intel_through_lhm(self):
        amd = [lraw("/gpu-amd/0/temperature/0", "GPU Core", "Temperature", 66),
               lraw("/gpu-amd/0/temperature/7", "GPU Hot Spot", "Temperature", 80),
               lraw("/gpu-amd/0/clock/0", "GPU Core", "Clock", 2400), lraw("/gpu-amd/0/clock/2", "GPU Memory", "Clock", 1000),
               lraw("/gpu-amd/0/load/0", "GPU Core", "Load", 97), lraw("/gpu-amd/0/fan/0", "GPU Fan", "Fan", 1700),
               lraw("/gpu-amd/0/control/0", "GPU Fan", "Control", 45),
               lraw("/gpu-amd/0/power/3", "GPU Package", "Power", 210), lraw("/gpu-amd/0/voltage/0", "GPU Core", "Voltage", 1.1)]
        v = vals(amd)
        self.assertEqual([v[i]["value"] for i in ("gpu.temp", "gpu.temp.hotspot", "gpu.clock.core", "gpu.clock.mem",
                                                  "gpu.load", "gpu.fan1", "gpu.fan1.pct", "gpu.power",
                                                  "gpu.volt.core")], [66, 80, 2400, 1000, 97, 1700, 45, 210, 1.1])
        intel = [lraw("/gpu-intel/0/temperature/0", "GPU Core", "Temperature", 50),
                 lraw("/gpu-intel/0/power/0", "GPU Package", "Power", 80),
                 lraw("/gpu-intel-integrated/0/temperature/0", "GPU Core", "Temperature", 45),
                 lraw("/gpu-intel-integrated/0/power/0", "GPU Power", "Power", 9)]
        v = vals(intel)
        self.assertEqual((v["gpu.temp"]["value"], v["gpu.power"]["value"]), (50, 80))      # erste Karte gewinnt
        v = vals(intel[2:])
        self.assertEqual((v["gpu.temp"]["value"], v["gpu.power"]["value"]), (45, 9))
        # NVIDIA bleibt vorn, auch wenn daneben eine AMD-/Intel-iGPU liegt
        v = vals(amd[:1] + [lraw("/gpu-nvidia/0/temperature/0", "GPU Core", "Temperature", 40)])
        self.assertEqual(v["gpu.temp"]["value"], 40)

    def test_limits_and_long_fan_paths(self):
        from bridge.sensors import mapping as mp
        # sehr viele Kerne: höchstens MAX_CORES IDs, Nummern stabil aus der LHM-Nummer
        many = [lraw(f"/amdcpu/0/clock/{n}", f"Core #{n}", "Clock", 3000 + n) for n in range(1, 129)]
        v = vals(many)
        cores = [i for i in v if re.fullmatch(r"cpu\.clock\.\d+", i)]
        self.assertEqual(len(cores), mp.MAX_CORES)
        self.assertEqual(v["cpu.clock.5"]["value"], 3006)                  # Core #6 -> 5, egal was davor fehlt
        self.assertEqual(vals(many[6:])["cpu.clock.6"]["value"], 3007)
        # langer Pfad: ID gekürzt, eindeutig, gilt weiter als erzeugt; Lüfter erscheint
        path = "/lpc/" + "sehr-langer-baustein-name-" * 4 + "/0/fan/3"
        ident = mp._fan_id(path)
        self.assertTrue(mp.is_derived_id(ident), ident)
        self.assertLessEqual(len(ident), 64)
        self.assertIn(ident, vals([lraw(path, "Fan #3", "Fan", 1200)]))
        # feste IDs und Fantasienamen sind keine erzeugten IDs
        for fixed in ("fan.sys1", "fan.gibtsnicht"):
            self.assertFalse(mp.is_derived_id(fixed), fixed)

    def test_this_pc_is_unchanged(self):
        """lhm_computer() bildet diesen PC ab: dieselben festen IDs wie bisher, dazu die neuen Kerne."""
        src = LhmSource(lambda: lhm_computer(), admin=True)
        src.start()
        raws = src.read()
        v = vals(raws)
        # Nummer aus der LHM-Nummer: P-Core #8 -> 7, E-Core #1 -> 8 (hinter dem höchsten P-Kern) - wie die alten IDs
        for old, new in (("p0", 0), ("p7", 7), ("e8", 8), ("e11", 11)):
            self.assertEqual(v[f"cpu.clock.{old}"]["value"], v[f"cpu.clock.{new}"]["value"])
        self.assertEqual((v["fan.cpu"]["value"], v["fan.sys1"]["value"]), (900, 700))
        extra = [i for i in v if i.startswith("fan.") and i not in ("fan.cpu", "fan.sys1")]
        self.assertEqual(extra, ["fan.nct6687d_0_5"])                            # "System Fan #4" (fan/5): neu sichtbar
        self.assertEqual(v["fan.nct6687d_0_5"]["name"], "System Fan #4")
        self.assertNotIn("volt.3v3", v)


class PresentMonCsvTest(unittest.TestCase):
    def rows(self, text):
        lines = text.splitlines()
        cols = parse_header(lines[0])
        return cols, [parse_row(cols, line) for line in lines[1:]]

    def test_v2_columns(self):
        cols, rows = self.rows(CSV_V2)
        self.assertEqual(rows, [(10.0, 10.0), (10.0, None), (20.0, 30.0)])     # „NA“ = nicht angezeigt
        self.assertEqual(parse_row(cols, "Hinweis ohne Kommas"), None)
        self.assertEqual(parse_row(cols, ""), None)
        self.assertIsNone(parse_row(cols, CSV_V2.splitlines()[0]))             # wiederholte Kopfzeile

    def test_v1_columns(self):
        _, rows = self.rows(CSV_V1)
        self.assertEqual(rows, [(16.0, 16.0), (16.0, None)])                   # Dropped=1 zählt nicht als angezeigt

    def test_ms_prefixed_columns_are_summed(self):
        cols = parse_header("\ufeff" + HEAD_MS)
        row = "Spiel.exe,1,0x0,DXGI,0,0,1,Composed: Flip,0.5,5.5,0.0,1,2,2,0,20,8.25"
        self.assertEqual(parse_row(cols, row), (5.5, 8.25))                    # CPUWait 0 ist erlaubt

    def test_no_header(self):
        self.assertIsNone(parse_header("warning: PresentMon requires elevated privilege"))
        self.assertIsNone(parse_header(""))
        self.assertIsNone(parse_header("Application,ProcessID,SwapChainAddress"))

    def test_moving_average(self):
        clock = Clock()
        st = FrameStats(1000.0, clock)
        self.assertEqual(st.values(), (None, None))
        for _ in range(200):
            st.add(20.0, 20.0)                  # 50 FPS - fällt gleich aus dem Fenster
        for _ in range(100):
            st.add(10.0, 10.0)                  # 1 s mit 100 FPS
        fps, ft = st.values()
        self.assertAlmostEqual(fps, 100.0)
        self.assertAlmostEqual(ft, 10.0)
        self.assertLessEqual(len(st.frames), 101)
        for _ in range(50):
            st.add(10.0, None)                  # jeder zweite Frame nicht angezeigt …
            st.add(10.0, 20.0)                  # … der andere doppelt so lang
        fps, ft = st.values()
        self.assertAlmostEqual(fps, 50.0)
        self.assertAlmostEqual(ft, 10.0)
        clock.t += 5                            # keine Frames mehr: kein alter Wert
        self.assertEqual(st.values(), (None, None))

    def test_target_check(self):
        self.assertEqual(clean_target({"pid": 4242}), ("pid", 4242))
        self.assertEqual(clean_target({"exe": "Stalker2-Win64-Shipping.exe"}), ("exe", "Stalker2-Win64-Shipping.exe"))
        self.assertIsNone(clean_target({}))
        for bad in ({"pid": "1"}, {"pid": 0}, {"pid": True}, {"pid": 1.5}, {"exe": "a.exe --output_file x"},
                    {"exe": "..\\a.exe"}, {"exe": "C:/a.exe"}, {"exe": "a.bat"}, {"exe": 5}, {"exe": '"a".exe'}, []):
            with self.assertRaises(ValueError, msg=bad):
                clean_target(bad)


class FakeProc:
    def __init__(self, cmd, text):
        self.cmd, self.stdout, self.returncode, self.ended = cmd, io.StringIO(text), None, None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.returncode, self.ended = 1, "terminate"

    def kill(self):
        self.returncode, self.ended = 1, "kill"


class PresentMonProcessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.exe = Path(self.tmp.name) / "PresentMon.exe"
        self.exe.write_bytes(b"")
        self.procs, self.runs, self.graceful = [], [], True
        self.clock = Clock()

    def tearDown(self):
        self.tmp.cleanup()

    def fake_popen(self, cmd, **kw):
        self.procs.append(FakeProc(cmd, CSV_V2))
        return self.procs[-1]

    def fake_run(self, cmd, **kw):
        self.runs.append(cmd)
        if self.graceful:
            self.procs[-1].returncode, self.procs[-1].ended = 0, "sitzung beendet"

    def source(self):
        src = PresentMonSource(self.exe, popen=self.fake_popen, run=self.fake_run, clock=self.clock)
        src.start()
        return src

    def read_values(self, src):
        for _ in range(200):                    # der Lese-Thread braucht einen Moment
            v = {r.path: r.value for r in src.read()}
            if v:
                return v
            time.sleep(0.01)
        return {}

    def test_not_installed(self):
        src = PresentMonSource(Path(self.tmp.name) / "fehlt.exe", popen=self.fake_popen, run=self.fake_run)
        src.start()
        src.set_target(("pid", 1))
        self.assertEqual((src.read(), src.status, self.procs), ([], "nicht installiert", []))

    def test_no_target_no_process(self):
        src = self.source()
        self.assertEqual((src.read(), src.status, self.procs), ([], "kein Ziel", []))

    def test_start_values_switch_and_close(self):
        src = self.source()
        src.set_target(("pid", 4242))
        v = self.read_values(src)
        self.assertAlmostEqual(v["fps.displayed"], 50.0)        # 2 angezeigte Frames in 40 ms
        self.assertAlmostEqual(v["fps.frametime"], 40 / 3)
        cmd = self.procs[0].cmd
        self.assertEqual(cmd[:3], [str(self.exe), "--process_id", "4242"])
        for opt in ("--output_stdout", "--no_console_stats", "--stop_existing_session", "--terminate_on_proc_exit"):
            self.assertIn(opt, cmd)
        self.assertEqual(cmd[cmd.index("--session_name") + 1], SESSION)
        self.assertEqual(src.status, "ok")

        src.set_target(("exe", "Spiel.exe"))                    # Zielwechsel: alter Prozess geordnet beendet
        src.read()
        self.assertEqual(self.procs[0].ended, "sitzung beendet")
        self.assertEqual(self.runs[0], [str(self.exe), "--session_name", SESSION, "--terminate_existing_session"])
        self.assertEqual(self.procs[1].cmd[1:3], ["--process_name", "Spiel.exe"])
        self.assertNotIn("--terminate_on_proc_exit", self.procs[1].cmd)

        self.graceful = False                                   # reagiert nicht: hart beenden
        src.close()
        self.assertEqual(self.procs[1].ended, "terminate")
        self.assertIsNone(src.proc)

        src.set_target(None)
        self.assertEqual((src.read(), src.status, len(self.procs)), ([], "kein Ziel", 2))

    def test_game_exit_clears_pid_target(self):
        src = self.source()
        src.set_target(("pid", 4242))
        src.read()
        self.procs[0].returncode = 0                            # --terminate_on_proc_exit hat gegriffen
        self.assertEqual((src.read(), src.status, len(self.procs)), ([], "kein Ziel", 1))

    def test_crash_is_reported_and_retried_later(self):
        src = self.source()
        src.set_target(("exe", "Spiel.exe"))
        src.read()
        self.procs[0].returncode = 5
        with self.assertLogs("sensors", logging.WARNING):
            self.assertEqual(src.read(), [])
        self.assertIn("beendet (Code 5)", src.status)
        src.read()
        self.assertEqual(len(self.procs), 1)                    # nicht sofort wieder starten
        self.clock.t += 60
        src.read()
        self.assertEqual((len(self.procs), src.status), (2, "ok"))
        src.close()


class FixedSource(Adapter):
    name = "fest"

    def __init__(self):
        self.closed = False

    def read(self):
        return [Raw("psutil", "cpu.load", "CPU-Last", 42.0, "%")]

    def close(self):
        self.closed = True


class BrokenSource(Adapter):
    name = "kaputt"

    def __init__(self, on_start=None):
        self.on_start, self.reads, self.closed = on_start, 0, 0

    def start(self):
        if self.on_start:
            raise self.on_start

    def read(self):
        self.reads += 1
        raise RuntimeError("Sensor weg")

    def close(self):
        self.closed += 1


class CollectorTest(unittest.TestCase):
    def test_broken_adapter_leaves_others_running(self):
        clock = Clock()
        ok, bad, gone = FixedSource(), BrokenSource(), BrokenSource(Unavailable("nicht installiert"))
        gone.name = "fehlt"
        c = Collector([bad, gone, ok], DEFAULTS, clock=clock)
        with self.assertLogs("sensors", logging.WARNING) as logs:
            for _ in range(8):
                c.sample()
        snap = c.snapshot()
        self.assertEqual(snap["sources"], {"kaputt": "Fehler: RuntimeError", "fehlt": "nicht installiert", "fest": "ok"})
        self.assertEqual([(v["id"], v["value"]) for v in snap["values"]], [("cpu.load", 42.0)])
        self.assertEqual(len(logs.output), 2)                   # je Quelle einmal, nicht bei jeder Abtastung
        self.assertEqual((bad.reads, bad.closed, gone.reads), (5, 1, 0))    # nach 5 Fehlern Pause bis zum Neustart
        clock.t += 120
        c.sample()
        self.assertEqual(bad.reads, 6)
        self.assertGreater(snap["time"], 0)
        c.close()
        self.assertTrue(ok.closed)

    def test_start_error_is_retried(self):
        clock = Clock()
        bad = BrokenSource(OSError("Treiber fehlt"))
        c = Collector([bad], DEFAULTS, clock=clock)
        with self.assertLogs("sensors", logging.WARNING):
            c.sample()
        self.assertEqual(c.snapshot()["sources"], {"kaputt": "Fehler: OSError"})
        bad.on_start = None
        c.sample()
        self.assertEqual(bad.reads, 0)                          # Wartezeit läuft noch
        clock.t += 120
        with self.assertLogs("sensors", logging.WARNING):       # Start klappt jetzt, das Lesen nicht
            c.sample()
        self.assertEqual(bad.reads, 1)

    def test_thread_survives_exception_and_logs_once(self):
        ok = FixedSource()
        c = Collector([ok], DEFAULTS, interval=0.05)
        real = c.sample
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) < 4:
                raise ValueError("kaputt")
            return real()
        c.sample = flaky
        with self.assertLogs("sensors", logging.ERROR) as logs:
            c.start()
            for _ in range(300):
                if c.snapshot()["values"]:
                    break
                time.sleep(0.01)
            c.stop()
        self.assertEqual(c.snapshot()["values"][0]["id"], "cpu.load")
        self.assertGreater(c.snapshot()["time"], 0)
        self.assertEqual(len(logs.output), 1)

    def test_mapping_failure_logged_once(self):
        c = Collector([FixedSource()], {})
        c.mapping = {"x": 5}                                    # kaputt: resolve wirft
        with self.assertLogs("sensors", logging.ERROR) as logs:
            for _ in range(3):
                c.sample()
        self.assertEqual(len(logs.output), 1)
        self.assertEqual(c.snapshot()["values"], [])

    def test_background_thread(self):
        ok = FixedSource()
        c = Collector([ok], DEFAULTS, interval=0.05)
        c.start()
        for _ in range(200):
            if c.snapshot()["values"]:
                break
            time.sleep(0.01)
        c.stop()
        self.assertEqual(c.snapshot()["values"][0]["id"], "cpu.load")
        self.assertTrue(ok.closed)


class MainTest(unittest.TestCase):
    def test_list_refuses_when_helper_runs(self):
        import socket
        from contextlib import redirect_stdout
        from bridge.sensors import __main__ as m
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.json"
            cfg.write_text(json.dumps({"sensors_port": srv.getsockname()[1]}), encoding="utf-8")
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    rc = m.main(["--list", "--config", str(cfg)])
            finally:
                srv.close()
        self.assertEqual(rc, 1)
        self.assertIn("Helfer läuft", buf.getvalue())

    def test_startup_error_is_logged(self):
        from bridge.sensors import __main__ as m
        orig = m._main
        m._main = lambda argv=None: 1 / 0
        try:
            with self.assertLogs("sensors", logging.ERROR) as logs:
                self.assertEqual(m.main([]), 1)
        finally:
            m._main = orig
        self.assertIn("ZeroDivisionError", "\n".join(logs.output))

    def test_installed_ignores_presentmon_from_config(self):
        from bridge.sensors import __main__ as m
        with tempfile.TemporaryDirectory() as d:
            fixed = Path(d) / "pf" / "PresentMon.exe"
            _, pm = m.build({"presentmon_exe": "C:/Nutzer/boese.exe"}, Path(d), fixed)
            self.assertEqual(pm.exe, fixed)
            _, pm = m.build({"presentmon_exe": "x/PM.exe"}, Path(d))           # Betrieb von Hand
            self.assertEqual(pm.exe, Path(d) / "x" / "PM.exe")

    def test_installed_needs_fixed_paths(self):
        from bridge.sensors import __main__ as m
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            m._main(["--installed", "--data", "."])

    def test_installed_reads_token_only(self):
        from bridge.sensors import __main__ as m
        root = logging.getLogger()
        before = list(root.handlers)
        with tempfile.TemporaryDirectory() as d:
            data, log_file = Path(d) / "repo", Path(d) / "pf" / "sensors.log"
            data.mkdir()
            log_file.parent.mkdir()
            try:
                rc = m.main(["--installed", "--data", str(data), "--presentmon", str(Path(d) / "pf" / "PM.exe"),
                             "--log", str(log_file)])
            finally:
                for h in list(root.handlers):      # Logdatei schließen (sonst bleibt der Ordner unter Windows)
                    if h not in before:
                        h.close()
                        root.removeHandler(h)
                for h in before:
                    if h not in root.handlers:
                        root.addHandler(h)
            self.assertEqual(rc, 1)
            self.assertFalse((data / "secrets").exists())          # nichts in den Nutzerordner geschrieben
            self.assertIn("Kein Token", log_file.read_text(encoding="utf-8"))


class RunScriptTest(unittest.TestCase):
    """scripts/sensors-run.py (run.py im Programmverzeichnis): feste Umgebung für den Admin-Prozess."""

    def test_clean_environ(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "sensors_run", Path(__file__).resolve().parent.parent / "scripts" / "sensors-run.py")
        run = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(run)          # ohne __main__: ändert nichts
        user = {"SystemRoot": r"C:\Windows", "PATH": r"C:\Users\x\bin;C:\Windows", "TEMP": r"C:\Users\x\Temp",
                "COR_ENABLE_PROFILING": "1", "COR_PROFILER": "{x}", "CORECLR_PROFILER_PATH": "a.dll",
                "DOTNET_STARTUP_HOOKS": "b", "COMPlus_EnableDiagnostics": "1", "PYTHONPATH": "c",
                "APPDATA": r"C:\Users\x\AppData\Roaming", "ProgramData": r"C:\ProgramData", "pathext": ".EXE"}
        env, tmp = run.clean_environ(user, r"C:\PF\sensors", r"C:\Python313")
        self.assertEqual(env["PATH"], r"C:\Windows\System32;C:\Windows;C:\Python313")
        self.assertEqual(env["TEMP"], r"C:\PF\sensors\logs\tmp")
        self.assertEqual(env["TMP"], tmp)
        for k in ("COR_ENABLE_PROFILING", "COR_PROFILER", "CORECLR_PROFILER_PATH", "DOTNET_STARTUP_HOOKS",
                  "COMPlus_EnableDiagnostics", "PYTHONPATH", "APPDATA"):
            self.assertNotIn(k, env)
        self.assertEqual(env["ProgramData"], r"C:\ProgramData")
        self.assertEqual(env["pathext"], ".EXE")
        # os.environ unter Windows: Schlüssel in Großbuchstaben, Windows evtl. auf einem anderen Laufwerk
        env, _ = run.clean_environ({"SYSTEMROOT": r"D:\Windows", "PATH": "x"}, r"C:\PF", r"C:\Py")
        self.assertEqual(env["PATH"], r"D:\Windows\System32;D:\Windows;C:\Py")

    def test_exe_name_not_an_option(self):
        from bridge.sensors.presentmon_src import EXE_NAME
        self.assertIsNone(EXE_NAME.fullmatch("-terminate.exe"))
        self.assertTrue(EXE_NAME.fullmatch("Stalker2-Win64-Shipping.exe"))


class ServerTest(unittest.TestCase):
    TOKEN = "t" * 43

    def setUp(self):
        import threading
        self.collector = Collector([FixedSource()], DEFAULTS)
        self.collector.sample()
        self.targets = []
        self.server = make_server(self.collector, self.TOKEN, 0, NS(set_target=self.targets.append))
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def call(self, path, token=None, data=None):
        req = urllib.request.Request(self.url + path, data=data)
        if token is not None:
            req.add_header("Authorization", token)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # nie über einen Proxy
        try:
            with opener.open(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_binds_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_token_required(self):
        for token in (None, "", "Bearer falsch", "Bearer " + self.TOKEN + "x", self.TOKEN, "Basic " + self.TOKEN,
                      "Bearer " + self.TOKEN[:-1], "Bearer ü"):
            for path, data in (("/values", None), ("/target", b'{"pid":1}'), ("/gibtsnicht", None)):
                status, body = self.call(path, token, data)
                self.assertEqual(status, 401, (token, path))
                self.assertNotIn("values", body)
        self.assertEqual(self.targets, [])

    def test_values(self):
        status, body = self.call("/values", "Bearer " + self.TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"time", "values", "sources"})
        self.assertEqual(body["values"], [{"id": "cpu.load", "name": "CPU-Last", "value": 42.0, "unit": "%",
                                           "min": 0, "max": 100}])
        self.assertEqual(body["sources"], {"fest": "ok"})
        self.assertEqual(self.call("/anderes", "Bearer " + self.TOKEN)[0], 404)

    def test_target(self):
        auth = "Bearer " + self.TOKEN
        self.assertEqual(self.call("/target", auth, b'{"pid": 4242}'), (200, {"ok": True, "target": {"pid": 4242}}))
        self.assertEqual(self.call("/target", auth, b'{"exe": "Spiel.exe"}')[0], 200)
        self.assertEqual(self.call("/target", auth, b"{}"), (200, {"ok": True, "target": None}))
        self.assertEqual(self.targets, [("pid", 4242), ("exe", "Spiel.exe"), None])
        for bad in (b'{"exe": "a.exe --x"}', b"kein json", b"[1]", b'{"pid": -1}', b"x" * 5000):
            self.assertEqual(self.call("/target", auth, bad)[0], 400, bad)
        self.assertEqual(len(self.targets), 3)

    def test_token_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "secrets" / "sensors.key"
            with self.assertLogs("sensors", logging.INFO) as logs:
                token = load_or_create_token(p)
            self.assertGreaterEqual(len(token), 32)
            self.assertNotIn(token, "".join(logs.output))       # das Token selbst steht nie im Log
            self.assertEqual(load_or_create_token(p), token)    # bleibt über Neustarts gleich


class RawItemsTest(unittest.TestCase):
    """Alle LHM-Rohwerte als lhm.*-IDs (Auswahl „Alle Werte“ im Dashboard-Editor)."""

    def test_ids_gueltig_und_stabil(self):
        from bridge.sensors.mapping import raw_id
        from bridge.dashboard import SENSOR_ID
        self.assertEqual(raw_id("lhm", "/intelcpu/0/temperature/3"), "lhm.intelcpu.0.temperature.3")
        self.assertEqual(raw_id("lhm", "/gpu-nvidia/0/load/0"), "lhm.gpu_nvidia.0.load.0")
        long = "/nic/%7B5A2E7F11-AAAA-BBBB-CCCC-0123456789AB%7D/throughput/7"
        a = raw_id("lhm", long)
        self.assertEqual(a, raw_id("lhm", long))                       # stabil
        self.assertNotEqual(a, raw_id("lhm", long.replace("/7", "/8")))
        for p in ("/intelcpu/0/clock/1", long, "/ÄÖÜ/ß/0", "/" + "x" * 200):
            self.assertTrue(SENSOR_ID.fullmatch(raw_id("lhm", p)), p)

    def test_alle_lhm_werte_mit_bauteil(self):
        from bridge.sensors.mapping import raw_items
        cpu = FakeHardware([lhm_sensor("Core #1", "Temperature", "/intelcpu/0/temperature/1", 50.0)])
        cpu.Name = "Intel Core i7-12700K"
        src = LhmSource(lambda: FakeComputer([cpu]), admin=True)
        src.start()
        raws = src.read() + [Raw("psutil", "cpu.load", "CPU", 3.0, "%"), Raw("lhm", "/x/0/load/0", "NaN", float("nan"))]
        items = raw_items(raws)
        self.assertEqual(items, [{"id": "lhm.intelcpu.0.temperature.1", "name": "Core #1", "value": 50.0, "unit": "°C",
                                  "min": None, "max": None, "group": "Intel Core i7-12700K"}])

    def test_kollision_und_obergrenze(self):
        from bridge.sensors import mapping
        raws = [Raw("lhm", "/a-b/0/load/0", "A", 1.0, "%"), Raw("lhm", "/a_b/0/load/0", "B", 2.0, "%")]
        items = mapping.raw_items(raws)
        self.assertEqual(items[0]["id"], "lhm.a_b.0.load.0")
        self.assertTrue(items[1]["id"].startswith("lhm.a_b.0.load.0."))          # zweiter mit Prüfsumme
        self.assertEqual([i["value"] for i in items], [1.0, 2.0])
        many = [Raw("lhm", f"/x/0/load/{i}", "x", 1.0) for i in range(mapping.RAW_MAX + 5)]
        mapping._raw_warned.pop("cap", None)
        with self.assertLogs("sensors", "WARNING"):
            self.assertEqual(len(mapping.raw_items(many)), mapping.RAW_MAX)

    def test_collector_liefert_feste_und_rohwerte(self):
        clock = Clock()
        c = Collector([LhmSource(lambda: lhm_computer(), admin=True)], DEFAULTS, clock=clock)
        c.sample()
        ids = [v["id"] for v in c.snapshot()["values"]]
        self.assertIn("cpu.temp.package", ids)
        self.assertIn("lhm.intelcpu.0.temperature.14", ids)
        self.assertLess(ids.index("cpu.temp.package"), ids.index("lhm.intelcpu.0.temperature.14"))   # feste zuerst
        c.close()


if __name__ == "__main__":
    unittest.main()
