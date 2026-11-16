"""Internet für die Web-Ansicht des Tablets: kleiner HTTP-Proxy, erreichbar über `adb reverse`.

Das Tablet hat kein WLAN, nur das USB-Kabel zum PC. Der Launcher-Browser nutzt diesen Proxy (Android
global http_proxy = localhost:<port>, per adb reverse auf den PC weitergeleitet).

Erlaubt ist nur das öffentliche Internet:
- HTTPS über CONNECT (Port 443) und einfache HTTP-Anfragen (Port 80),
- Ziele werden am PC aufgelöst; private, Loopback-, Link-Local-, Multicast- und reservierte Adressen sind
  gesperrt (kein Zugriff aufs Heimnetz, auf den Router oder auf Dienste des PCs, z. B. den Hub selbst),
- verbunden wird mit der geprüften IP, nicht erneut mit dem Namen (kein DNS-Rebinding).
Der Proxy lauscht nur auf 127.0.0.1.
"""
import asyncio
import ipaddress
import logging
import socket

log = logging.getLogger("proxy")
ALLOWED_PORTS = {80, 443}
HEAD_LIMIT = 64 * 1024
IDLE_S = 300          # Leerlauf beider Richtungen zusammen (Downloads/Videos laufen weiter)
MAX_CONN = 64
_slots = None


class Blocked(Exception):
    pass


def public_ip(ip):
    a = ipaddress.ip_address(ip)
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a.is_global and not a.is_multicast


async def resolve(host, port):
    if port not in ALLOWED_PORTS:
        raise Blocked(f"Port {port}")
    host = host.strip("[]")
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips = [i[4][0] for i in infos]
    if not ips or not all(public_ip(ip) for ip in ips):   # ein privater Eintrag reicht zum Sperren
        raise Blocked(f"{host} -> nicht öffentlich")
    # geprüfte IPs, IPv4 zuerst (IPv6 ohne Route hängt sonst bis zum Timeout)
    return sorted(dict.fromkeys(ips), key=lambda ip: ":" in ip)


async def connect_any(ips, port):
    """Geprüfte IPs nacheinander (z. B. IPv6 zuerst, PC ohne IPv6 -> IPv4)."""
    last = None
    for ip in ips:
        try:
            return await asyncio.wait_for(asyncio.open_connection(ip, port), 6)
        except (OSError, asyncio.TimeoutError) as e:
            last = e
    raise last or OSError("keine Adresse")


def split_hostport(s, default):
    if s.startswith("["):   # [v6]:port
        h, _, rest = s[1:].partition("]")
        return h, int(rest[1:]) if rest.startswith(":") else default
    h, sep, p = s.rpartition(":")
    return (h, int(p)) if sep and p.isdigit() else (s, default)


async def relay(a_reader, a_writer, b_reader, b_writer):
    """Beide Richtungen weiterreichen. Ein gemeinsamer Leerlauf-Timer: Aktivität in einer Richtung hält
    die Verbindung offen. EOF einer Seite wird als Halbschluss weitergegeben (write_eof)."""
    loop = asyncio.get_running_loop()
    last = [loop.time()]

    async def one(r, w):
        try:
            while True:
                data = await r.read(65536)
                if not data:
                    break
                last[0] = loop.time()
                w.write(data)
                await w.drain()
            if w.can_write_eof():
                w.write_eof()
        except (ConnectionError, OSError):
            pass

    # a_reader -> a_writer (Client -> Ziel), b_reader -> b_writer (Ziel -> Client)
    tasks = [asyncio.create_task(one(a_reader, a_writer)), asyncio.create_task(one(b_reader, b_writer))]
    try:
        while not all(t.done() for t in tasks):
            await asyncio.wait(tasks, timeout=10)
            if loop.time() - last[0] > IDLE_S:
                break
    finally:
        for t in tasks:
            t.cancel()


async def handle(creader, cwriter):
    if _slots.locked():
        await _deny(cwriter, 503)
        cwriter.close()
        return
    async with _slots:
        await _handle(creader, cwriter)


async def _handle(creader, cwriter):
    upstream = None
    try:
        head = await asyncio.wait_for(creader.readuntil(b"\r\n\r\n"), 30)
        if len(head) > HEAD_LIMIT:
            raise Blocked("Kopf zu groß")
        lines = head.decode("latin-1").split("\r\n")
        method, target, version = lines[0].split(" ", 2)
        if method == "CONNECT":
            host, port = split_hostport(target, 443)
            ureader, uwriter = await connect_any(await resolve(host, port), port)
            upstream = uwriter
            cwriter.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await cwriter.drain()
        else:
            if not target.lower().startswith("http://"):
                raise Blocked("nur absolute http-URLs")
            rest = target[7:]
            hostport, slash, path = rest.partition("/")
            host, port = split_hostport(hostport, 80)
            ureader, uwriter = await connect_any(await resolve(host, port), port)
            upstream = uwriter
            # Anfrage an den Zielserver: relativer Pfad, Proxy-Kopfzeilen weg, nach der Antwort schließen
            # (sonst könnte der Browser dieselbe Verbindung für einen anderen Host weiterverwenden)
            out = [f"{method} /{path if slash else ''} {version}"]
            for ln in lines[1:]:
                name = ln.split(":", 1)[0].strip().lower()
                if ln and name not in ("proxy-connection", "proxy-authorization", "connection", "keep-alive"):
                    out.append(ln)
            out.append("Connection: close")
            uwriter.write(("\r\n".join(out) + "\r\n\r\n").encode("latin-1"))
            await uwriter.drain()
        await relay(creader, uwriter, ureader, cwriter)
    except Blocked as e:
        log.info("Proxy gesperrt: %s", e)
        await _deny(cwriter, 403)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError):
        await _deny(cwriter, 400)
    except (asyncio.TimeoutError, OSError) as e:
        log.debug("Proxy: %s", e)
        await _deny(cwriter, 502)
    finally:
        for w in (cwriter, upstream):
            if w is not None:
                try:
                    w.close()
                except Exception:  # noqa: BLE001
                    pass


async def _deny(w, code):
    try:
        w.write(f"HTTP/1.1 {code} Blocked\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
        await w.drain()
    except Exception:  # noqa: BLE001
        pass


async def serve(port):
    global _slots
    _slots = asyncio.Semaphore(MAX_CONN)
    server = await asyncio.start_server(handle, "127.0.0.1", port, limit=HEAD_LIMIT)
    log.info("Web-Proxy fürs Tablet auf 127.0.0.1:%d", port)
    async with server:
        await server.serve_forever()
