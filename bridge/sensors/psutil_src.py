"""Grundwerte ohne Adminrechte: CPU-Last, Arbeitsspeicher, Netzwerk."""
import time

from . import Adapter, Raw, Unavailable

MB = 1024 * 1024


class PsutilSource(Adapter):
    """CPU, RAM, Netz. Netzraten und -summen entstehen aus Deltas je Schnittstelle (nur Schnittstellen, die in
    beiden Messungen vorkommen, je Schnittstelle mindestens 0). net.total_* ist die Summe dieser Deltas seit
    dem Start des Helfers und damit monoton - kein Zählerstand seit Systemstart; der erste Wert ist 0."""
    name = "psutil"

    def __init__(self, ps=None, clock=time.monotonic):
        self.ps = ps
        self.clock = clock
        self._last = None       # (Zeit, {Schnittstelle: (empfangen, gesendet)})
        self._total = [0, 0]    # aufsummierte Deltas (Bytes)

    def start(self):
        if self.ps is None:
            try:
                import psutil
            except ImportError as e:
                raise Unavailable("psutil fehlt") from e
            self.ps = psutil
        self.ps.cpu_percent(None)       # erster Aufruf setzt nur den Bezugspunkt
        self._last = None
        self._total = [0, 0]

    def _net(self):
        """{Schnittstelle: (Bytes empfangen, gesendet)} aller aktiven Schnittstellen ohne Loopback."""
        try:
            up = {n for n, s in self.ps.net_if_stats().items() if s.isup}
        except Exception:  # noqa: BLE001 - dann eben alle Schnittstellen
            up = None
        out = {}
        for nic, c in self.ps.net_io_counters(pernic=True).items():
            if "loopback" in nic.lower() or (up is not None and nic not in up):
                continue
            out[nic] = (c.bytes_recv, c.bytes_sent)
        return out

    def read(self):
        mem = self.ps.virtual_memory()
        out = [
            Raw(self.name, "cpu.load", "CPU-Last", float(self.ps.cpu_percent(None)), "%"),
            Raw(self.name, "ram.used", "RAM belegt", (mem.total - mem.available) / MB, "MB"),
            Raw(self.name, "ram.total", "RAM gesamt", mem.total / MB, "MB"),
        ]
        now = self.clock()
        cur = self._net()
        if self._last is not None:
            before = self._last[1]
            # je Schnittstelle: Zähler können zurückspringen (Adapter neu): dann 0 statt negativer Rate
            drx = sum(max(0, cur[n][0] - before[n][0]) for n in cur if n in before)
            dtx = sum(max(0, cur[n][1] - before[n][1]) for n in cur if n in before)
            self._total[0] += drx
            self._total[1] += dtx
            dt = now - self._last[0]
            if dt > 0:
                out.append(Raw(self.name, "net.down", "Download", drx / dt / 1024, "KB/s"))
                out.append(Raw(self.name, "net.up", "Upload", dtx / dt / 1024, "KB/s"))
        self._last = (now, cur)
        out.append(Raw(self.name, "net.total_down", "Download gesamt", self._total[0] / MB, "MB"))
        out.append(Raw(self.name, "net.total_up", "Upload gesamt", self._total[1] / MB, "MB"))
        return out
