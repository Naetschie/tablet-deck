"use strict";
// Gemeinsame Hub-Verbindung für Tablet-Seiten: WebSocket /ws mit Neuverbinden und Totmann-Erkennung.
// Hub.send(obj), Hub.on(fn(msg)), Hub.onStatus(fn(ok)), Hub.connected
window.Hub = (function () {
  var ws = null, handlers = [], statusFns = [], lastPong = 0, api = { connected: false };

  function setStatus(ok) {
    api.connected = ok;
    document.documentElement.classList.toggle("offline", !ok);
    statusFns.forEach(function (f) { f(ok); });
  }

  function connect() {
    ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
    ws.onopen = function () { lastPong = Date.now(); setStatus(true); };
    ws.onmessage = function (ev) {
      lastPong = Date.now();
      var m;
      try { m = JSON.parse(ev.data); } catch (e) { return; }
      handlers.forEach(function (f) { f(m); });
    };
    ws.onclose = function () { setStatus(false); setTimeout(connect, 1000); };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
  }
  setInterval(function () {
    if (!ws || ws.readyState !== 1) return;
    api.send({ t: "ping" });
    if (Date.now() - lastPong > 6000) ws.close();
  }, 2000);

  api.send = function (o) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); };
  api.on = function (f) { handlers.push(f); };
  api.onStatus = function (f) { statusFns.push(f); };
  setStatus(false);
  connect();
  return api;
})();
