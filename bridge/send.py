"""Webseite ans Tablet schicken:  python -m bridge.send <url>

Spricht den laufenden Hub über ws://127.0.0.1:<port>/send an und meldet sich mit secret.key an.
"""
import asyncio
import json
import sys
from pathlib import Path

from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parent.parent


async def send(url):
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    key = (ROOT / "secret.key").read_text(encoding="utf-8").strip()
    async with connect(f"ws://127.0.0.1:{int(cfg.get('port', 8765))}/send") as ws:
        await ws.send(json.dumps({"t": "auth", "k": key}))
        await ws.send(json.dumps({"t": "open", "url": url}))
        return json.loads(await asyncio.wait_for(ws.recv(), 5))


def main():
    if len(sys.argv) != 2:
        sys.exit("Aufruf: python -m bridge.send <url>")
    r = asyncio.run(send(sys.argv[1]))
    if r.get("t") != "ok":
        sys.exit(f"nicht gesendet: {r.get('msg')}")
    print("gesendet")


if __name__ == "__main__":
    main()
