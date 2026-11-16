"use strict";
(function () {
  var Deck = window.Deck, ws = null, lastPong = 0;
  if (!Deck) { document.body.textContent = "Nur im Tablet-Launcher sinnvoll."; return; }

  function send(o) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); }

  // vom Launcher aufgerufen, wenn sich der Modus ändert
  window.deckState = function (mode) { send({ t: "state", mode: mode }); };
  // vom Launcher: Web-Kachel hat eine Seite geladen (Verlauf am PC)
  window.deckVisited = function (url, title) { send({ t: "visited", url: String(url), title: String(title || "") }); };

  function connect() {
    ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ctl");
    ws.onopen = function () { lastPong = Date.now(); Deck.setStatus(true); send({ t: "state", mode: Deck.getMode() }); };
    ws.onmessage = function (ev) {
      lastPong = Date.now();
      var m;
      try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m.t === "tiles" && Array.isArray(m.tiles)) Deck.setTiles(JSON.stringify(m.tiles));
      else if (m.t === "mode" && typeof m.mode === "string") Deck.setMode(m.mode);
      else if (m.t === "open" && typeof m.url === "string") Deck.openUrl(m.url);
      else if (m.t === "maps" && Array.isArray(m.games) && Deck.setMaps) Deck.setMaps(JSON.stringify(m));
      else if (m.t === "wlan" && Array.isArray(m.hosts)) Deck.setWlan(JSON.stringify(m));
      else if (m.t === "power" && typeof m.action === "string") Deck.power(m.action);
      else if (m.t === "tablet_mode" && typeof m.mode === "string" && Deck.setTabletMode) Deck.setTabletMode(m.mode);
      else if (m.t === "rotation" && typeof m.r === "number" && Deck.setRotation) Deck.setRotation(m.r);
      else if (m.t === "reload") Deck.reload();
      else if (m.t === "home") Deck.home();
    };
    ws.onclose = function () { Deck.setStatus(false); setTimeout(connect, 1000); };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
  }
  // tote Verbindung erkennen (Kabel ab, Bridge weg)
  setInterval(function () {
    if (!ws || ws.readyState !== 1) return;
    send({ t: "ping" });
    if (Date.now() - lastPong > 6000) ws.close();
  }, 2000);
  connect();
})();
