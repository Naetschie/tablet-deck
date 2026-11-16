"""LibreHardwareMonitor über das pip-Paket „HardwareMonitor“ (pythonnet, bringt LibreHardwareMonitorLib.dll mit).

Liefert Kerntakte, CPU-Temperaturen und -Leistung (Intel MSR/RAPL), Lüfter und Spannungen des Mainboards
(Super-I/O) sowie GPU-Werte über NVAPI. Die CPU- und Mainboard-Werte brauchen Adminrechte und den
PawnIO-Treiber. Ohne Admin bleiben sie leer; die Quelle meldet dann „kein Admin“ und liefert nur, was LHM
trotzdem lesen kann (z. B. GPU-Werte).
"""
from . import Adapter, Raw, Unavailable, is_admin

# LHM-Sensortyp -> Einheit (wie LibreHardwareMonitor selbst anzeigt)
UNITS = {
    "Voltage": "V", "Current": "A", "Power": "W", "Clock": "MHz", "Temperature": "°C", "Load": "%",
    "Frequency": "Hz", "Fan": "RPM", "Flow": "L/h", "Control": "%", "Level": "%", "Factor": "",
    "Data": "GB", "SmallData": "MB", "Throughput": "B/s", "Energy": "mWh", "Noise": "dBA",
    "Conductivity": "µS/cm", "Humidity": "%", "TimeSpan": "s",
}


def _open_computer():
    try:
        from HardwareMonitor.Hardware import Computer
    except ImportError as e:
        raise Unavailable("HardwareMonitor fehlt (pip install HardwareMonitor)") from e
    # andere Ladefehler (.NET, Treiber) können vorübergehend sein: der Collector versucht es später erneut
    c = Computer()
    try:
        c.IsCpuEnabled = True
        c.IsGpuEnabled = True
        c.IsMotherboardEnabled = True
        c.Open()
    except BaseException:
        try:
            c.Close()
        except Exception:  # noqa: BLE001 - der ursprüngliche Fehler zählt
            pass
        raise
    return c


class LhmSource(Adapter):
    name = "lhm"

    def __init__(self, open_computer=_open_computer, admin=None):
        self._open = open_computer
        self._admin = admin
        self.computer = None
        self.admin = False

    def start(self):
        self.admin = is_admin() if self._admin is None else self._admin
        self.computer = self._open()
        self.status = "ok" if self.admin else "kein Admin"

    def close(self):
        c, self.computer = self.computer, None
        if c is not None:
            c.Close()

    def read(self):
        out = []
        for hw in self.computer.Hardware:
            self._walk(hw, out)
        return out

    def _walk(self, hw, out):
        hw_name = str(getattr(hw, "Name", "") or "")
        try:
            hw.Update()
        except Exception:  # noqa: BLE001 - ein Baustein hakt: die übrigen trotzdem lesen
            pass
        for s in hw.Sensors:
            v = s.Value
            if v is None:           # ohne Admin bleiben z. B. Kerntakte und CPU-Temperaturen leer
                continue
            kind = str(s.SensorType)
            ident = str(s.Identifier)
            # CPU-Leistung (RAPL) meldet LHM ohne Admin als 0 W statt leer: lieber kein Wert als ein falscher
            if not self.admin and kind == "Power" and "cpu" in ident.split("/power/")[0].lower():
                continue
            out.append(Raw(self.name, ident, str(s.Name), float(v), UNITS.get(kind, ""), kind, hw_name))
        for sub in hw.SubHardware:
            self._walk(sub, out)
