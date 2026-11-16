"use strict";
// PC-Werte-Seite: lädt ein Dashboard (GET /api/dashboards/<name>, Format: docs/sensors.md) und füllt es mit den
// Werten, die der Hub über /ws schickt ({"t":"stats", values, meta, sources}). Zeichnen: render.js (StatsView).
(function () {
  if (typeof Hub === "undefined") return;       // z. B. in einer Testumgebung ohne Hub
  var stage = document.getElementById("stage"), msgEl = document.getElementById("msg");
  var name = (/[?&]d=([a-z0-9_-]+)/.exec(location.search) || [0, "default"])[1];   // "default": Standard-Dashboard des Hubs
  var view = null, state = StatsView.createState();

  function say(text) { msgEl.textContent = text || ""; msgEl.hidden = !text; }

  function render() { StatsView.draw(view, state); }

  function onStats(m) {
    StatsView.ingest(state, view, m.values, m.meta);
    render();
  }

  Hub.on(function (m) { if (m && m.t === "stats") onStats(m); });
  function subscribe() { Hub.send({ t: "stats_sub" }); }
  Hub.onStatus(function (ok) { if (ok) subscribe(); });
  if (Hub.connected) subscribe();
  setInterval(render, 1000);                     // Uhr und "veraltet" auch ohne neue Werte
  document.addEventListener("visibilitychange", function () {
    Hub.send({ t: document.hidden ? "stats_unsub" : "stats_sub" });
  });

  // Hub evtl. gerade im Neustart: alle 3 s erneut versuchen (404 = Datei fehlt -> aufgeben)
  function load() {
    fetch("/api/dashboards/" + encodeURIComponent(name), { cache: "no-store" })
      .then(function (r) {
        if (r.status === 404) throw new Error("fehlt");
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (dash) {
        view = StatsView.mount(dash, stage, state).view;
        say("");
      })
      .catch(function (e) {
        if (e && e.message === "fehlt") { say("Dashboard „" + name + "“ nicht gefunden"); return; }
        say("Dashboard „" + name + "“ wird geladen …");
        setTimeout(load, 3000);
      });
  }
  load();
})();
