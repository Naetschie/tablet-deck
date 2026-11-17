"""Rauchtest gegen eine laufende Bridge (python -m bridge).

Sendet nur Tasten OHNE Tastatur-Belegung (z. B. mfd_prev), damit am PC nichts getippt wird.
Aufruf:  python tests/smoke_bridge.py
"""
import asyncio
import json
import socket
import sys
import urllib.error
import urllib.request

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

BASE = "127.0.0.1:8765"
SECRET = (__import__("pathlib").Path(__file__).resolve().parent.parent / "secret.key").read_text().strip()
AUTH = {"Cookie": f"deck={SECRET}"}
ok = True


def check(name, cond):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL ") + name)


def http_status(path):
    try:
        return urllib.request.urlopen(f"http://{BASE}{path}").status
    except urllib.error.HTTPError as e:
        return e.code


def raw_status(path):
    """Roher Request ohne Pfad-Normalisierung des Clients (z. B. Backslashes)."""
    s = socket.create_connection(BASE.split(":"))
    s.sendall(f"GET {path} HTTP/1.1\r\nHost: {BASE}\r\n\r\n".encode())
    line = s.recv(200).split(b"\r\n", 1)[0].decode()
    s.close()
    return int(line.split()[1])


async def ws_tests():
    # ohne Kopplungs-Cookie muss abgelehnt werden (auch mit richtiger Herkunft)
    for path in ("/ws", "/ctl"):
        try:
            async with connect(f"ws://{BASE}{path}", origin=f"http://localhost:{BASE.split(':')[1]}"):
                check(f"{path} ohne Kopplung abgelehnt", False)
        except InvalidStatus as e:
            check(f"{path} ohne Kopplung abgelehnt", e.response.status_code == 401)
    # fremde Herkunft muss abgelehnt werden
    try:
        async with connect(f"ws://{BASE}/ws", origin="http://evil.example", additional_headers=AUTH):
            check("fremder Origin abgelehnt", False)
    except InvalidStatus as e:
        check("fremder Origin abgelehnt", e.response.status_code == 403)
    # eigene Herkunft ok
    async with connect(f"ws://{BASE}/ws", origin=f"http://localhost:{BASE.split(':')[1]}",
                       additional_headers=AUTH) as ws:
        hello = json.loads(await ws.recv())
        check("hello empfangen", hello.get("t") == "hello")
        games = json.loads(urllib.request.urlopen(f"http://{BASE}/api/games").read())
        key = games["default"]
        await ws.send(json.dumps({"t": "panel", "game": key.split("/")[0], "panel": key.split("/")[1]}))
        unmapped = json.loads(urllib.request.urlopen(f"http://{BASE}/profiles/{key}.json").read()).get("unmapped", [])
        if unmapped:
            test_id = unmapped[0]   # nur unbelegte Tasten, damit am PC nichts ausgelöst wird
            # zwei Finger auf derselben (unbelegten) Taste, dann Abbruch mit gehaltener Taste
            for t in ("down", "down", "up"):
                await ws.send(json.dumps({"t": t, "id": test_id}))
        else:
            print("SKIP Mehrfinger-Test: alle Tasten belegt (würde echte Tasten senden)")
        await ws.send(json.dumps({"t": "down", "id": 123}))  # ungültige ID darf nichts kaputt machen
        await ws.send(json.dumps({"t": "ping"}))
        got = None
        for _ in range(10):   # andere Nachrichten (z. B. Lautstärke) überspringen
            got = json.loads(await asyncio.wait_for(ws.recv(), 3)).get("t")
            if got == "pong":
                break
        check("pong nach ungültiger ID", got == "pong")
        # Touchpad-Nachrichten mit Unsinn dürfen die Verbindung nicht beenden (bewegt die Maus nicht)
        for m in ({"t": "move", "dx": "x"}, {"t": "btn", "b": "evil", "down": True},
                  {"t": "key", "k": "GIBTSNICHT"}, {"t": "volume", "v": "laut"}, ["liste"]):
            await ws.send(json.dumps(m))
        await ws.send(json.dumps({"t": "ping"}))
        for _ in range(10):
            got = json.loads(await asyncio.wait_for(ws.recv(), 3)).get("t")
            if got == "pong":
                break
        check("Verbindung übersteht ungültige Eingaben", got == "pong")


check("Startseite 200", http_status("/") == 200)
check("/api/games 200", http_status("/api/games") == 200)
check("Profil 200", http_status("/profiles/star-citizen/std--cockpit.json") == 200)
check("Profil-Traversal", raw_status("/profiles/../config.json") == 404)
check("Profil unbekannt 404", http_status("/profiles/x/y.json") == 404)
check("Traversal ..", raw_status("/../config.json") == 404)
check("UNC-Pfad", raw_status("/\\\\evil\\share\\x") == 404)
check("Laufwerkspfad", raw_status("/C:/Windows/win.ini") == 404)
asyncio.run(ws_tests())
print("Im Bridge-Log prüfen: die unbelegte Testtaste genau EIN DOWN und EIN UP (beim Trennen).")
sys.exit(0 if ok else 1)
