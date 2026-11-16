"use strict";
(function () {
  var pad = document.getElementById("pad");
  var BASE = 1.6, ACCEL = 1.2, VMAX = 3;     // Gewinn = BASE * (1 + ACCEL * min(v, VMAX)), v in px/ms
  var SCROLL = 5;                            // Rad-Einheiten pro Pixel (120 = eine Raste)
  var TAP_MS = 220, TAP_MOVE = 10, DBL_MS = 280;

  var pts = {};                 // pointerId -> {x, y, t}
  var g = null;                 // laufende Geste
  var accX = 0, accY = 0, accW = 0, accH = 0, frame = 0;
  var lastTap = { t: 0, x: 0, y: 0 };

  function count() { return Object.keys(pts).length; }

  function flush() {
    frame = 0;
    var dx = Math.trunc(accX), dy = Math.trunc(accY);
    if (dx || dy) { Hub.send({ t: "move", dx: dx, dy: dy }); accX -= dx; accY -= dy; }
    var w = Math.trunc(accW), h = Math.trunc(accH);
    if (w || h) { Hub.send({ t: "wheel", dy: w, dx: h }); accW -= w; accH -= h; }
  }
  function schedule() { if (!frame) frame = requestAnimationFrame(flush); }

  pad.addEventListener("pointerdown", function (e) {
    e.preventDefault();
    pad.setPointerCapture(e.pointerId);
    pts[e.pointerId] = { x: e.clientX, y: e.clientY, t: e.timeStamp };
    if (!g) {
      g = { t0: e.timeStamp, maxN: 1, moved: 0, drag: false };
      // Doppeltippen + halten = Linke Taste gedrückt halten (Ziehen)
      if (e.timeStamp - lastTap.t < DBL_MS && Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) < 40) {
        g.drag = true;
        Hub.send({ t: "btn", b: "left", down: true });
      }
    }
    g.maxN = Math.max(g.maxN, count());
  });

  pad.addEventListener("pointermove", function (e) {
    var p = pts[e.pointerId];
    if (!p || !g) return;
    var dx = e.clientX - p.x, dy = e.clientY - p.y, dt = Math.max(1, e.timeStamp - p.t);
    p.x = e.clientX; p.y = e.clientY; p.t = e.timeStamp;
    g.moved += Math.abs(dx) + Math.abs(dy);
    var n = count();
    if (n === 1 && g.maxN === 1) {
      var v = Math.hypot(dx, dy) / dt, gain = BASE * (1 + ACCEL * Math.min(v, VMAX));
      accX += dx * gain; accY += dy * gain;
    } else if (n === 2) {
      // Scrollen (natürlich: Inhalt folgt den Fingern); jeder Finger trägt die Hälfte bei
      accW += dy * SCROLL / 2; accH -= dx * SCROLL / 2;
    }
    schedule();
  });

  function up(e) {
    if (!pts[e.pointerId]) return;
    delete pts[e.pointerId];
    if (count() > 0 || !g) return;
    var dur = e.timeStamp - g.t0;
    if (g.drag) {
      Hub.send({ t: "btn", b: "left", down: false });
    } else if (dur < TAP_MS && g.moved < TAP_MOVE) {
      var b = g.maxN === 1 ? "left" : g.maxN === 2 ? "right" : "middle";
      Hub.send({ t: "btn", b: b, down: true });
      Hub.send({ t: "btn", b: b, down: false });
      if (g.maxN === 1) lastTap = { t: e.timeStamp, x: e.clientX, y: e.clientY };
    }
    g = null;
  }
  pad.addEventListener("pointerup", up);
  pad.addEventListener("pointercancel", up);

  // Maustasten zum Halten
  var sideButtons = [];
  document.querySelectorAll("[data-btn]").forEach(function (el) {
    var sb = { b: el.getAttribute("data-btn"), held: 0, el: el };
    sideButtons.push(sb);
    el.addEventListener("pointerdown", function (e) {
      e.preventDefault(); el.setPointerCapture(e.pointerId);
      if (sb.held++ === 0) { el.classList.add("down"); Hub.send({ t: "btn", b: sb.b, down: true }); }
    });
    function rel() {
      if (sb.held > 0 && --sb.held === 0) { el.classList.remove("down"); Hub.send({ t: "btn", b: sb.b, down: false }); }
    }
    el.addEventListener("pointerup", rel);
    el.addEventListener("pointercancel", rel);
  });

  // Sondertasten
  document.querySelectorAll("[data-key]").forEach(function (el) {
    el.addEventListener("pointerdown", function (e) {
      e.preventDefault();
      el.classList.add("down");
      Hub.send({ t: "key", k: el.getAttribute("data-key") });
      setTimeout(function () { el.classList.remove("down"); }, 120);
    });
  });

  // Texteingabe: Differenz zum vorherigen Feldinhalt senden (robust gegen Wortvorschläge/Komposition)
  var txt = document.getElementById("txt"), prev = "";
  txt.addEventListener("input", function () {
    var cur = txt.value, p = 0;
    while (p < prev.length && p < cur.length && prev[p] === cur[p]) p++;
    for (var i = prev.length; i > p; i--) Hub.send({ t: "key", k: "BACKSPACE" });
    if (cur.length > p) Hub.send({ t: "text", s: cur.slice(p) });
    prev = cur;
    if (cur.length > 200) { txt.value = ""; prev = ""; }   // nur die Verfolgung zurücksetzen
  });
  txt.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); Hub.send({ t: "key", k: "ENTER" }); txt.value = ""; prev = ""; }
  });

  // Alles loslassen und zurücksetzen (Seite verdeckt, Fokus weg). Der Hub gibt Maustasten zusätzlich
  // frei, wenn der Launcher die Touchpad-Ansicht verlässt oder die Verbindung abbricht.
  function releaseAll(send) {
    if (send && g && g.drag) Hub.send({ t: "btn", b: "left", down: false });
    sideButtons.forEach(function (sb) {
      if (sb.held > 0 && send) Hub.send({ t: "btn", b: sb.b, down: false });
      sb.held = 0; sb.el.classList.remove("down");
    });
    pts = {}; g = null; accX = accY = accW = accH = 0;
  }
  Hub.onStatus(function (ok) { if (!ok) releaseAll(false); });
  // Hub hat alles freigegeben (Ansicht gewechselt): lokalen Zustand ohne erneutes Senden zurücksetzen
  Hub.on(function (m) { if (m.t === "released") releaseAll(false); });
  document.addEventListener("visibilitychange", function () { if (document.hidden) releaseAll(true); });
  window.addEventListener("pagehide", function () { releaseAll(true); });
  window.addEventListener("blur", function () { releaseAll(true); });
})();
