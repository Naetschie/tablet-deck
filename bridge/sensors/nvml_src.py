"""NVIDIA-Grafikkarte über NVML (pip-Paket nvidia-ml-py, Modul pynvml). Läuft ohne Adminrechte."""
import ctypes

from . import Adapter, Raw, Unavailable

MB = 1024 * 1024
# NVML-Fehler, die sich nicht von selbst erledigen: Karte/Treiber kennt die Abfrage nicht
PERMANENT = {"NVMLError_NotSupported", "NVMLError_InvalidArgument", "NVMLError_FunctionNotFound"}


def _permanent(e):
    """True, wenn die Abfrage dauerhaft nicht geht (nicht unterstützt). GPU_IS_LOST, Unknown, Treiber-Reset
    u. Ä. sind es nicht."""
    return isinstance(e, (LookupError, AttributeError)) or type(e).__name__ in PERMANENT


class NvmlSource(Adapter):
    name = "nvml"

    def __init__(self, nvml=None, index=0):
        self.n = nvml
        self.index = index
        self.h = None
        self._skip = set()      # Abfragen, die Karte/Treiber nicht kennen: nicht jede Sekunde neu probieren

    def start(self):
        if self.n is None:
            try:
                import pynvml
            except ImportError as e:
                raise Unavailable("pynvml fehlt (pip install nvidia-ml-py)") from e
            self.n = pynvml
        # Fehler von nvmlInit sind womöglich nur vorübergehend (Treiber beim Autostart noch nicht bereit):
        # sie gehen unverändert an den Collector, der nach einer Pause neu versucht.
        try:
            self.n.nvmlInit()
        except Exception as e:  # noqa: BLE001
            # kein NVIDIA-Treiber/keine Karte: endgültig nicht verfügbar (sonst Status "Fehler" für immer)
            gone = tuple(getattr(self.n, n) for n in ("NVMLError_LibraryNotFound", "NVMLError_DriverNotLoaded")
                         if isinstance(getattr(self.n, n, None), type))
            if gone and isinstance(e, gone):
                raise Unavailable("kein NVIDIA-Treiber") from e
            raise
        try:
            self.h = self.n.nvmlDeviceGetHandleByIndex(self.index)
        except BaseException:
            self.h = None
            try:
                self.n.nvmlShutdown()
            except Exception:  # noqa: BLE001 - der ursprüngliche Fehler zählt
                pass
            raise
        self._skip = set()

    def close(self):
        if self.h is not None:
            self.h = None
            self.n.nvmlShutdown()

    def _fan_rpm(self, i):
        """Drehzahl von Lüfter i. Die pynvml-Hülle fragt nur Lüfter 0 ab, deshalb der direkte Aufruf."""
        n = self.n
        if not hasattr(n, "_nvmlGetFunctionPointer"):       # andere pynvml-Fassung
            if i == 0:
                return n.nvmlDeviceGetFanSpeedRPM(self.h)
            raise LookupError("Drehzahl nur für Lüfter 1 verfügbar")
        info = n.c_nvmlFanSpeedInfo_t()
        info.version = n.nvmlFanSpeedInfo_v1
        info.fan = i
        fn = n._nvmlGetFunctionPointer("nvmlDeviceGetFanSpeedRPM")
        n._nvmlCheckReturn(fn(self.h, ctypes.byref(info)))
        return info.speed

    def read(self):
        n, h = self.n, self.h
        out = []
        errors = []

        def failed(key, e):
            if _permanent(e):
                self._skip.add(key)         # nicht unterstützt: künftig auslassen
            else:
                errors.append(e)            # vorübergehend: beim nächsten Mal wieder versuchen

        def add(key, name, unit, fn):
            if key in self._skip:
                return
            try:
                v = fn()
            except Exception as e:  # noqa: BLE001
                failed(key, e)
                return
            out.append(Raw(self.name, key, name, float(v), unit))

        add("gpu.temp", "GPU-Temperatur", "°C", lambda: n.nvmlDeviceGetTemperature(h, n.NVML_TEMPERATURE_GPU))
        add("gpu.clock.core", "GPU-Takt", "MHz", lambda: n.nvmlDeviceGetClockInfo(h, n.NVML_CLOCK_GRAPHICS))
        add("gpu.clock.mem", "GPU-Speichertakt", "MHz", lambda: n.nvmlDeviceGetClockInfo(h, n.NVML_CLOCK_MEM))
        add("gpu.power", "GPU-Leistung", "W", lambda: n.nvmlDeviceGetPowerUsage(h) / 1000)
        if "mem" not in self._skip:
            try:
                mem = n.nvmlDeviceGetMemoryInfo(h)
                out.append(Raw(self.name, "gpu.vram.used", "VRAM belegt", mem.used / MB, "MB"))
                out.append(Raw(self.name, "gpu.vram.total", "VRAM gesamt", mem.total / MB, "MB"))
            except Exception as e:  # noqa: BLE001
                failed("mem", e)
        if "util" not in self._skip:
            try:
                u = n.nvmlDeviceGetUtilizationRates(h)
                out.append(Raw(self.name, "gpu.load", "GPU-Last", float(u.gpu), "%"))
                out.append(Raw(self.name, "gpu.load.memctl", "GPU-Speichercontroller", float(u.memory), "%"))
            except Exception as e:  # noqa: BLE001
                failed("util", e)
        add("gpu.pcie.rx", "PCIe Rx", "KB/s", lambda: n.nvmlDeviceGetPcieThroughput(h, n.NVML_PCIE_UTIL_RX_BYTES))
        add("gpu.pcie.tx", "PCIe Tx", "KB/s", lambda: n.nvmlDeviceGetPcieThroughput(h, n.NVML_PCIE_UTIL_TX_BYTES))
        for i in (0, 1):
            add(f"gpu.fan{i + 1}", f"GPU-Lüfter {i + 1}", "RPM", lambda i=i: self._fan_rpm(i))
            add(f"gpu.fan{i + 1}.pct", f"GPU-Lüfter {i + 1} (Stufe)", "%",
                lambda i=i: n.nvmlDeviceGetFanSpeed_v2(h, i))
        if errors and not out:      # alles schlägt fehl (Karte verloren, Treiber-Reset): Collector startet neu
            raise errors[0]
        return out
