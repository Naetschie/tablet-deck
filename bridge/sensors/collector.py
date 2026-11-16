"""Abtastung aller Quellen in einem Hintergrund-Thread; Anfragen bekommen den letzten Stand.

Jeder Fehler einer Quelle wird hier abgefangen, einmal geloggt und in „sources“ gemeldet; die anderen
Quellen laufen weiter. Start, Lesen und Schließen einer Quelle geschehen immer im selben Thread
(LHM/.NET und der PresentMon-Unterprozess verlassen sich darauf).
"""
import logging
import threading
import time

from . import Unavailable
from .mapping import resolve

log = logging.getLogger("sensors")

RESTART_AFTER = 5       # Lesefehler in Folge, dann Quelle schließen und neu starten
RETRY = 60.0            # s bis zum nächsten Startversuch nach einem Fehler


class _State:
    def __init__(self, adapter):
        self.adapter = adapter
        self.started = False
        self.dead = False           # dauerhaft nicht nutzbar
        self.next_try = 0.0
        self.fails = 0
        self.status = "startet"
        self.logged = None          # zuletzt geloggte Meldung - jede nur einmal, nicht jede Sekunde


class Collector:
    def __init__(self, adapters, mapping, interval=1.0, clock=time.monotonic):
        self.states = [_State(a) for a in adapters]
        self.mapping = mapping
        self.interval = interval
        self.clock = clock
        self.lock = threading.Lock()
        self._snapshot = {"time": 0, "values": [], "sources": {s.adapter.name: s.status for s in self.states}}
        self._stop = threading.Event()
        self._thread = None
        self._logged = None     # letzte geloggte Meldung der Zuordnung bzw. des Threads (nicht jede Sekunde)

    def _problem(self, st, text, exc=None):
        st.status = text
        if st.logged != text:
            st.logged = text
            if exc is None:
                log.warning("Quelle %s: %s", st.adapter.name, text)
            else:
                log.warning("Quelle %s: %s (%s)", st.adapter.name, text, exc)

    def _read(self, st):
        a = st.adapter
        if st.dead:
            return []
        if not st.started:
            if self.clock() < st.next_try:
                return []
            try:
                a.start()
            except Unavailable as e:
                st.dead = True
                self._problem(st, str(e))
                return []
            except Exception as e:  # noqa: BLE001 - eine Quelle darf die anderen nicht mitreißen
                st.next_try = self.clock() + RETRY
                self._problem(st, f"Fehler: {type(e).__name__}", e)
                self._close(st)
                return []
            st.started = True
            st.fails = 0
        try:
            raws = list(a.read())
        except Exception as e:  # noqa: BLE001
            st.fails += 1
            self._problem(st, f"Fehler: {type(e).__name__}", e)
            if st.fails >= RESTART_AFTER:
                self._close(st)
                st.next_try = self.clock() + RETRY
            return []
        if st.fails or st.logged:
            log.info("Quelle %s: läuft wieder", a.name)
        st.fails = 0
        st.logged = None
        st.status = a.status
        return raws

    def _close(self, st):
        st.started = False
        try:
            st.adapter.close()
        except Exception as e:  # noqa: BLE001
            log.warning("Quelle %s: Schließen fehlgeschlagen (%s)", st.adapter.name, e)

    def sample(self):
        """Eine Abtastung aller Quellen. Ergebnis: Liste der Rohsensoren."""
        raws = []
        for st in self.states:
            raws.extend(self._read(st))
        try:
            values = resolve(self.mapping, raws)
        except Exception as e:  # noqa: BLE001 - kaputte Zuordnung darf den Dienst nicht beenden
            if self._logged != repr(e):
                self._logged = repr(e)
                log.error("Zuordnung fehlgeschlagen: %r", e)
            values = []
        snap = {"time": round(time.time(), 3), "values": values,
                "sources": {s.adapter.name: s.status for s in self.states}}
        with self.lock:
            self._snapshot = snap
        return raws

    def snapshot(self):
        with self.lock:
            return self._snapshot

    def close(self):
        for st in self.states:
            if st.started:
                self._close(st)

    # --- Hintergrund-Thread ---

    def _run(self):
        try:
            while not self._stop.is_set():
                t = self.clock()
                try:
                    self.sample()
                except Exception as e:  # noqa: BLE001 - der Thread darf nicht still sterben
                    if self._logged != "run:" + repr(e):
                        self._logged = "run:" + repr(e)
                        log.exception("Abtastung fehlgeschlagen")
                self._stop.wait(max(0.05, self.interval - (self.clock() - t)))
        finally:
            self.close()

    def start(self):
        self._thread = threading.Thread(target=self._run, name="sensors", daemon=True)
        self._thread.start()

    def stop(self, timeout=15):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
