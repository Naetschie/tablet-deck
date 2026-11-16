"""Master-Lautstärke des Standard-Wiedergabegeräts und Lautstärke je App (Windows Core Audio über pycaw)."""
import logging
import time
import warnings

log = logging.getLogger("audio")
REFRESH_S = 5   # Standardgerät regelmäßig neu holen (Wechsel auf Headset o. Ä.)
DEVICES_TTL_S = 5   # Geräteliste ist teuer (ca. 70 ms), Sitzungen nicht (ca. 10 ms)
MAX_NAME = 60
SYS_KEY = "sys"
SYS_NAME = "Systemklänge"
SESSION_EXPIRED = 2   # AudioSessionStateExpired


class AudioWorker:
    """Eigener Thread für den Mixer (COM im eigenen Apartment). Die Abfragen (Geräteliste ca. 70 ms) laufen so
    nicht im asyncio-Loop - sonst stockt das Touchpad kurz. Daemon-Thread statt ThreadPoolExecutor: dessen
    Threads wartet Python beim Beenden ab, ein hängender COM-Aufruf hielte dann den ganzen Hub fest."""

    def __init__(self):
        import queue
        import threading
        self._q = queue.Queue()
        threading.Thread(target=self._run, name="audio", daemon=True).start()

    def _run(self):
        import ctypes
        ctypes.windll.ole32.CoInitializeEx(None, 0x2)   # APARTMENTTHREADED; bleibt bis Thread-Ende
        while True:
            fut, fn = self._q.get()
            if not fut.set_running_or_notify_cancel():
                continue                                 # inzwischen verworfen
            try:
                fut.set_result(fn())
            except BaseException as e:  # noqa: BLE001 - an den Aufrufer weitergeben
                fut.set_exception(e)

    def submit(self, fn):
        """fn im Audio-Thread ausführen; Ergebnis als concurrent.futures.Future (cancel bis zum Start)."""
        import concurrent.futures
        fut = concurrent.futures.Future()
        self._q.put((fut, fn))
        return fut


def _file_description(path):
    """FileDescription aus der Versionsinfo einer exe (ctypes), sonst None."""
    import ctypes
    from ctypes import wintypes
    ver = ctypes.WinDLL("version", use_last_error=True)
    ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    ver.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    ver.GetFileVersionInfoW.restype = wintypes.BOOL
    ver.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
                                   ctypes.POINTER(wintypes.UINT)]
    ver.VerQueryValueW.restype = wintypes.BOOL
    size = ver.GetFileVersionInfoSizeW(path, None)
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    if not ver.GetFileVersionInfoW(path, 0, size, buf):
        return None
    langs = []
    ptr, n = ctypes.c_void_p(), wintypes.UINT()
    if ver.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(n)) and n.value >= 4:
        lang, page = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint16 * 2)).contents
        langs.append("%04x%04x" % (lang, page))
    langs += ["040904b0", "040904e4", "000004b0"]
    for lp in langs:
        if ver.VerQueryValueW(buf, "\\StringFileInfo\\%s\\FileDescription" % lp, ctypes.byref(ptr),
                              ctypes.byref(n)) and n.value > 1:
            text = ctypes.wstring_at(ptr.value, n.value - 1).strip()
            if text:
                return text
    return None


_desc_cache = {}


def file_description(path):
    """Beschreibung der exe (je Pfad gemerkt, auch Fehlschläge)."""
    if path not in _desc_cache:
        try:
            _desc_cache[path] = _file_description(path)
        except Exception:  # noqa: BLE001 – Versionsinfo ist nur Zierde
            _desc_cache[path] = None
    return _desc_cache[path]


def mixer_key(state):
    """Vergleichswert eines Mixer-Stands (Lautstärke auf 0,01 gerundet); None bleibt None."""
    if not state:
        return None
    return (tuple((x["k"], x["name"], round(x["v"], 2), bool(x["mute"])) for x in state["sessions"]),
            tuple((d["id"], d["name"]) for d in state["devices"]), state["default"], state.get("note"))


def mixer_changed(old, new):
    """True, wenn sich der Mixer-Stand merklich geändert hat (Broadcast nur bei Änderung)."""
    return mixer_key(old) != mixer_key(new)


class Audio:
    def __init__(self):
        self._ev = None
        self._fetched = 0.0
        self._warned = False
        self._guard_warned = False
        self._mix_warned = set()
        self._dev_cache = (-1e9, None)
        self._last_sessions = None
        # Geräte, die Windows nicht als Standard-Ausgabe annimmt (z. B. der Chat-Kanal eines Headsets:
        # "Kopfhörer (… Communication Audio)" -> E_FAIL): bis zum Neustart des Hubs nicht mehr anbieten
        self._refused = set()
        self._note = None          # (bis, Text) - kurzer Hinweis für das Tablet

    def _endpoint(self):
        if self._ev is None or time.monotonic() - self._fetched > REFRESH_S:
            from pycaw.pycaw import AudioUtilities
            self._ev = AudioUtilities.GetSpeakers().EndpointVolume
            self._fetched = time.monotonic()
        return self._ev

    def _call(self, fn):
        for attempt in (1, 2):
            try:
                result = fn(self._endpoint())
                self._warned = False
                return result
            except Exception as e:  # noqa: BLE001 – Gerät weg/gewechselt: einmal neu holen
                self._ev = None
                if attempt == 2 and not self._warned:
                    log.warning("Lautstärke nicht verfügbar: %s", e)
                    self._warned = True
        return None

    def get(self):
        """(lautstärke 0..1, stumm) oder None."""
        return self._call(lambda ev: (round(ev.GetMasterVolumeLevelScalar(), 3), bool(ev.GetMute())))

    def set_volume(self, v):
        v = min(1.0, max(0.0, float(v)))
        self._call(lambda ev: ev.SetMasterVolumeLevelScalar(v, None))

    def set_mute(self, mute):
        self._call(lambda ev: ev.SetMute(1 if mute else 0, None))

    def guard_default(self, avoid, prefer):
        """Ist ein Gerät mit `avoid` im Namen Standard-Ausgabe (spacedesk schaltet beim Verbinden auf
        seinen virtuellen Lautsprecher), auf das aktive Gerät mit `prefer` im Namen zurückstellen.
        Eigene Wechsel (z. B. aufs Headset) bleiben unberührt. Gibt den neuen Gerätenamen zurück."""
        import warnings
        from pycaw.pycaw import AudioUtilities
        from pycaw.constants import DEVICE_STATE, EDataFlow, ERole
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")   # pycaw warnt bei unlesbaren Geräte-Eigenschaften
            cur = AudioUtilities.GetSpeakers()
            if avoid.lower() not in (cur.FriendlyName or "").lower():
                return None
            # nur aktive Wiedergabegeräte - sonst träfe "Realtek USB Audio" auch das Mikrofon
            for dev in AudioUtilities.GetAllDevices(EDataFlow.eRender.value, DEVICE_STATE.ACTIVE.value):
                name = dev.FriendlyName or ""
                if prefer.lower() in name.lower() and avoid.lower() not in name.lower():
                    AudioUtilities.SetDefaultDevice(dev.id, [ERole.eConsole, ERole.eMultimedia])
                    self._ev = None   # Lautstärke-Regler auf das neue Gerät umhängen
                    return name
        if not self._guard_warned:
            log.warning("Audio-Ausgabe '%s' nicht gefunden, bleibe bei %s", prefer, cur.FriendlyName)
            self._guard_warned = True
        return None

    # ---------------- Lautstärke je App ----------------
    def _try(self, what, fn):
        """fn() einmal wiederholen; Warnung je Art nur einmal loggen. Bei Fehler None."""
        for attempt in (1, 2):
            try:
                result = fn()
                self._mix_warned.discard(what)
                return result
            except Exception as e:  # noqa: BLE001 – COM-Fehler (Gerät weg, Prozess beendet)
                if attempt == 2 and what not in self._mix_warned:
                    log.warning("%s nicht verfügbar: %s", what, e)
                    self._mix_warned.add(what)
        return None

    @staticmethod
    def _util():
        from pycaw.pycaw import AudioUtilities
        return AudioUtilities

    _no_exe = set()          # (PID, exe-Name) ohne lesbaren Pfad

    @classmethod
    def _display_name(cls, proc, name_for):
        """Anzeigename: name_for(exe-Name) > FileDescription der exe > exe-Name ohne .exe."""
        try:
            exe_name = proc.name()
        except Exception:  # noqa: BLE001
            return "?"
        name = None
        if name_for:
            try:
                name = name_for(exe_name)
            except Exception:  # noqa: BLE001
                name = None
        key = (getattr(proc, "pid", None), exe_name)
        if not name and key not in cls._no_exe:
            try:
                name = file_description(proc.exe())
            except Exception:  # noqa: BLE001 – Zugriff verweigert (geschützter Prozess)
                if len(cls._no_exe) > 500:
                    cls._no_exe.clear()
                cls._no_exe.add(key)
                name = None
        if not name:
            name = exe_name[:-4] if exe_name.lower().endswith(".exe") else exe_name
        return name[:MAX_NAME]

    def _groups(self):
        """{Schlüssel: (Prozess oder None, [Sitzungen])} der nicht abgelaufenen Audio-Sitzungen."""
        groups = {}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")   # pycaw warnt bei unlesbaren Eigenschaften
            for s in self._util().GetAllSessions():
                try:
                    if s.State == SESSION_EXPIRED:
                        continue
                    pid = s.ProcessId
                    proc = s.Process if pid else None
                except Exception:  # noqa: BLE001 – Sitzung verschwunden
                    continue
                if pid and proc is None:
                    continue          # Prozess beendet/unzugänglich: nicht unter "Systemklänge" mitsteuern
                k = str(pid) if pid else SYS_KEY
                groups.setdefault(k, (proc, []))[1].append(s)
        return groups

    def sessions(self, name_for=None):
        """Audio-Sitzungen je Prozess zusammengefasst: [{"k","name","v","mute"}], nach Name sortiert, oder None
        bei Fehler. v = lauteste Sitzung, mute nur wenn alle stumm. Schlüssel: PID, Systemklänge "sys"."""
        def work():
            out = []
            for k, (proc, sess) in self._groups().items():
                vols, mutes = [], []
                for s in sess:
                    try:
                        sv = s.SimpleAudioVolume
                        vols.append(sv.GetMasterVolume())
                        mutes.append(bool(sv.GetMute()))
                    except Exception:  # noqa: BLE001 – Sitzung inzwischen weg
                        continue
                if not vols:
                    continue
                name = SYS_NAME if k == SYS_KEY else self._display_name(proc, name_for)
                out.append({"k": k, "name": name, "v": round(max(vols), 3), "mute": all(mutes)})
            out.sort(key=lambda x: (x["name"].lower(), x["k"]))
            return out
        return self._try("App-Lautstärke", work)

    def set_session(self, k, v=None, mute=None):
        """Lautstärke und/oder Stumm für alle Sitzungen des Schlüssels k (nur aus der aktuellen Liste).
        True, wenn der Schlüssel gefunden wurde."""
        def work():
            found = self._groups().get(k)
            if not found:
                return False
            for s in found[1]:
                try:
                    sv = s.SimpleAudioVolume
                    if v is not None:
                        sv.SetMasterVolume(min(1.0, max(0.0, float(v))), None)
                    if mute is not None:
                        sv.SetMute(1 if mute else 0, None)
                except Exception as e:  # noqa: BLE001
                    log.info("App-Lautstärke %s: %s", k, e)
            return True
        return bool(self._try("App-Lautstärke", work))

    def devices(self):
        """(aktive Wiedergabegeräte [{"id","name"}], ID des Standardgeräts) oder None bei Fehler."""
        def work():
            from pycaw.constants import DEVICE_STATE, EDataFlow
            util = self._util()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                devs = [{"id": d.id, "name": (d.FriendlyName or d.id)[:MAX_NAME]}
                        for d in util.GetAllDevices(EDataFlow.eRender.value, DEVICE_STATE.ACTIVE.value)
                        if d.id not in self._refused]
                cur = util.GetSpeakers()
                default = cur.id if cur is not None else None
            devs.sort(key=lambda d: (d["name"].lower(), d["id"]))
            return devs, default
        return self._try("Ausgabegeräte", work)

    def set_default(self, dev_id):
        """Standard-Ausgabe wechseln - nur auf ein aktives Wiedergabegerät aus devices(). True bei Erfolg."""
        got = self.devices()
        if not got or dev_id not in {d["id"] for d in got[0]}:
            return False
        if dev_id == got[1]:
            return True        # schon Standard: nichts tun (ein Fehler hier blendete das aktive Gerät aus)
        name = next(d["name"] for d in got[0] if d["id"] == dev_id)
        try:
            from pycaw.constants import ERole
            self._util().SetDefaultDevice(dev_id, [ERole.eConsole, ERole.eMultimedia])
        except Exception as e:  # noqa: BLE001
            if not (e.args and e.args[0] in (-2147467259, 0x80004005)):   # nur E_FAIL heißt "Treiber lehnt ab"
                log.error("Ausgabegerät '%s' wechseln fehlgeschlagen: %s", name, e)
                return None
            log.warning("Ausgabegerät '%s' nicht wählbar (%s) - wird nicht mehr angeboten", name, e)
            self._refused.add(dev_id)
            self._note = (time.monotonic() + 8, f"„{name}“ lässt sich nicht als Ausgabe wählen")
            self._dev_cache = (-1e9, self._dev_cache[1])   # Liste ohne das Gerät neu lesen
            return None
        self._ev = None   # Master-Regler auf das neue Gerät umhängen
        self._dev_cache = (-1e9, self._dev_cache[1])   # Standardgerät geändert: beim nächsten Mal neu lesen
        return True

    def mixer(self, name_for=None):
        """Gesamtstand für das Tablet: {"sessions","devices","default"} oder None, wenn nichts lesbar war."""
        ses = self.sessions(name_for)
        now = time.monotonic()
        if now - self._dev_cache[0] > DEVICES_TTL_S:   # auch nach einem Fehler erst nach der Pause neu
            got = self.devices()
            self._dev_cache = (now, got if got is not None else self._dev_cache[1])
        dev = self._dev_cache[1]
        if ses is None:
            ses = self._last_sessions          # Lesefehler: Liste am Tablet nicht kurz leeren
        else:
            self._last_sessions = ses
        if ses is None and dev is None:
            return None
        state = {"sessions": ses or [], "devices": dev[0] if dev else [], "default": dev[1] if dev else None}
        if self._note and now < self._note[0]:
            state["note"] = self._note[1]
        return state
