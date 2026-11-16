"use strict";
(function () {
  var layout = null, ws = null, connected = false, unmapped = {};
  var active = {};        // pointerId -> { el, id, hold, timer, fired }
  var pageId = null;
  var games = [], gameId = null, panelId = null;   // aktuelles Spiel/Panel (vom Hub: /api/games)

  var $ = function (s) { return document.querySelector(s); };
  var tabsEl = $("#tabs"), pageEl = $("#page"), connEl = $("#conn"), lastEl = $("#last");
  var gameEl = $("#game"), panelsEl = $("#panels"), pickEl = $("#pick");
  function store(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function stored(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

  // ---------------- Verbindung ----------------
  function send(o) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); }

  function setConn(ok) {
    connected = ok;
    connEl.className = ok ? "" : "off";
    document.body.classList.toggle("offline", !ok);
  }

  function connect() {
    ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
    ws.onopen = function () {
      lastPong = Date.now(); setConn(true);
      if (gameId && panelId) send({ t: "panel", game: gameId, panel: panelId });   // vor allen Tasten
    };
    ws.onmessage = function (ev) {
      lastPong = Date.now();
      var m = JSON.parse(ev.data);
      if (m.t === "hello") {
        // (Neu-)Verbindung: Bridge evtl. mit geänderten Profilen neu gestartet; laufendes Spiel bevorzugen
        loadGames(m.game && m.game.panels.length ? m.game.id : null);
      } else if (m.t === "profiles") {
        loadGames(null);
      } else if (m.t === "game") {
        // Spiel gestartet: dessen Panel zeigen (Wahl von Hand gilt bis zum nächsten Spielwechsel)
        if (m.game && m.game.panels.length && m.game.id !== gameId) loadGames(m.game.id);
      } else if (m.t === "released") {
        cancelAll();   // Hub hat gehaltene Tasten freigegeben (Ansicht gewechselt); "up" ignoriert er
      }
    };
    ws.onclose = function () {
      setConn(false);
      cancelAll();
      setTimeout(connect, 1000);
    };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
  }
  // Watchdog: tote Verbindung erkennen (z. B. USB abgezogen)
  var lastPong = Date.now();
  setInterval(function () {
    if (!ws || ws.readyState !== 1) return;
    send({ t: "ping" });
    if (Date.now() - lastPong > 6000) { lastPong = Date.now(); ws.close(); }
  }, 2000);

  // ---------------- Tasten ----------------
  function btnById(id) {
    if (!layout) return null;
    for (var i = 0; i < layout.pages.length; i++) {
      var b = layout.pages[i].buttons;
      for (var j = 0; j < b.length; j++) if (b[j].id === id) return b[j];
    }
  }

  var fsTried = false;  // true nach Fehlschlag - sonst wäre danach jeder Tipp verschluckt
  var inLauncher = /TabletDeck\//.test(navigator.userAgent);  // Launcher-App ist schon Vollbild
  function needFullscreen() {
    return !inLauncher && !fsTried && !document.fullscreenElement && document.documentElement.requestFullscreen &&
      !window.matchMedia("(display-mode: fullscreen)").matches &&
      !window.matchMedia("(display-mode: standalone)").matches;
  }

  function onDown(ev) {
    // Erster Tipp schaltet nur auf Vollbild, damit sich das Layout nicht unter dem Finger verschiebt
    if (needFullscreen()) { ev.preventDefault(); fsPending = true; return; }
    var el = ev.target.closest("[data-id]");
    if (!el) return;
    var id = el.getAttribute("data-id"), b = btnById(id);
    if (!b || (!connected && !b.page)) return;   // Seiten-Links wirken nur lokal - auch ohne Verbindung
    ev.preventDefault();
    if (el.setPointerCapture) { try { el.setPointerCapture(ev.pointerId); } catch (e) {} }
    if (b.page) { ev.preventDefault(); el.classList.add("down"); setTimeout(function () { el.classList.remove("down"); showPage(b.page); }, 90); return; }
    var st = active[ev.pointerId] = { el: el, id: id, fired: false, panel: gameId + "/" + panelId };
    if (b.slider) {   // Regler: Ziehen ändert die Stufe, jede überschrittene Stufe sendet einen Tipp
      st.slider = b.slider;
      st.startX = ev.clientX; st.moved = false;   // reiner Tipp ändert nichts
      return;
    }
    el.classList.add("down");
    if (b.mode === "hold-confirm") {
      el.classList.remove("down");
      el.classList.add("arming");
      st.timer = setTimeout(function () {
        st.fired = true;
        el.classList.remove("arming");
        el.classList.add("down");
        send({ t: "down", id: id, panel: st.panel });
        showLast(b);
      }, layout.holdMs || 1000);
    } else {
      st.fired = true;
      if (b.states) {
        var ni = (statePos(id, b.states.length) + 1) % b.states.length;
        store("state:" + id, String(ni));
        showState(el, ni);
        send({ t: "down", id: id, panel: st.panel, state: ni });
      } else send({ t: "down", id: id, panel: st.panel });
      showLast(b);
      if (b.mode === "toggle") setToggle(el, id, !el.classList.contains("on"));
    }
  }

  // Mehrfach-Schalter: Tipp schaltet reihum; der neue Zustand geht mit (state: Index)
  function statePos(id, n) {
    var v = parseInt(stored("state:" + id), 10);
    return v >= 0 && v < n ? v : 0;
  }
  function showState(el, i) {
    Array.prototype.forEach.call(el.querySelectorAll(".st"), function (x, j) { x.classList.toggle("on", j === i); });
  }

  // Regler: Position (Stufe 0..steps) lokal merken, Anzeige als Füllung + Wert
  var SLIDER_STEP_MS = 115;
  var sliderMem = {}, sliderTarget = {}, sliderRaf = 0;   // Merker falls localStorage fehlt; Ziel-Stufe je Regler
  function sliderPos(id, steps) {
    var v = parseInt(stored("slider:" + id), 10);
    if (!(v >= 0)) v = sliderMem[id] >= 0 ? sliderMem[id] : 0;
    return Math.min(v, steps);   // weniger Stufen als gespeichert: begrenzen statt zurücksetzen
  }
  function showSlider(el, pos, steps) {
    var f = el.querySelector(".fill"), v = el.querySelector(".val");
    if (f) f.style.width = (pos / steps * 100) + "%";
    if (v) v.textContent = pos + " / " + steps;
  }
  function moveSlider(st, x) {
    if (!connected) return;
    if (!st.moved) {
      if (Math.abs(x - st.startX) < 8) return;
      st.moved = true;
    }
    var r = st.el.getBoundingClientRect(), steps = st.slider.steps;
    var frac = r.width > 0 ? (x - r.left) / r.width : 0;
    var target = Math.max(0, Math.min(steps, Math.round(frac * steps)));
    if (sliderTarget[st.id]) sliderTarget[st.id].target = target;   // Zeitmerker der Drosselung behalten
    else sliderTarget[st.id] = { st: st, target: target };
    if (!sliderRaf) sliderRaf = requestAnimationFrame(sliderFrame);
  }
  // höchstens eine Stufe pro Frame und Regler; Zwischenstufen werden nacheinander abgearbeitet
  function sliderFrame() {
    sliderRaf = 0;
    var again = false;
    for (var id in sliderTarget) {
      var t = sliderTarget[id], st = t.st, steps = st.slider.steps;
      if (!connected) { delete sliderTarget[id]; continue; }
      var cur = sliderPos(id, steps);
      if (cur === t.target) { delete sliderTarget[id]; continue; }
      // nicht schneller als der Hub die Impulse ausgibt (80 ms + 30 ms Pause), sonst verwirft er sie
      var now = Date.now();
      if (t.last && now - t.last < SLIDER_STEP_MS) { again = true; continue; }
      t.last = now;
      var dir = t.target > cur ? "up" : "down";
      cur += dir === "up" ? 1 : -1;
      send({ t: "down", id: id, panel: st.panel, dir: dir });
      send({ t: "up", id: id, panel: st.panel, dir: dir });
      sliderMem[id] = cur;
      store("slider:" + id, String(cur));
      showSlider(st.el, cur, steps);
      if (cur === t.target) delete sliderTarget[id]; else again = true;
    }
    if (again) sliderRaf = requestAnimationFrame(sliderFrame);
  }
  document.addEventListener("pointermove", function (ev) {
    var st = active[ev.pointerId];
    if (st && st.slider) moveSlider(st, ev.clientX);
  });

  // Schalter: merkt sich den (vermuteten) Zustand im Spiel - Star Citizen meldet nichts zurück
  function setToggle(el, id, on) {
    el.classList.toggle("on", on);
    try { localStorage.setItem("toggle:" + id, on ? "1" : ""); } catch (e) {}
  }

  function onUp(ev) {
    var st = active[ev.pointerId];
    if (!st) return;
    delete active[ev.pointerId];
    clearTimeout(st.timer);
    st.el.classList.remove("down", "arming");
    if (st.fired) send({ t: "up", id: st.id, panel: st.panel });
    // gleiche Taste noch von anderem Finger gehalten? Dann Markierung wieder setzen
    for (var k in active) if (active[k].el === st.el && active[k].fired) st.el.classList.add("down");
  }

  function cancelAll() {
    for (var k in active) onUp({ pointerId: k });
    sliderTarget = {};   // ausstehende Regler-Stufen nicht nach Seiten-/Panelwechsel weiter senden
  }

  function showLast(b) {
    var d = new Date();
    lastEl.textContent = b.label + "  " + ("0" + d.getHours()).slice(-2) + ":" +
      ("0" + d.getMinutes()).slice(-2) + ":" + ("0" + d.getSeconds()).slice(-2);
  }

  document.addEventListener("pointerdown", onDown);
  document.addEventListener("pointerup", onUp);
  document.addEventListener("pointercancel", onUp);
  document.addEventListener("contextmenu", function (e) { e.preventDefault(); });
  document.addEventListener("visibilitychange", function () { if (document.hidden) cancelAll(); });
  window.addEventListener("blur", cancelAll);

  // ---------------- Rendering ----------------
  function h(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function makeBtn(b, extra) {
    if (b.slider) return makeSlider(b, extra);
    var e = h("div", "key btn " + (b.style || "") + " " + (extra || "") + (b.wide ? " wide" : ""));
    e.setAttribute("data-id", b.id);
    e.appendChild(h("span", "lbl", b.label));
    if (b.states) {
      var row = h("span", "sub states");
      b.states.forEach(function (s) { row.appendChild(h("span", "st", s.label)); });
      e.appendChild(row);
      showState(e, statePos(b.id, b.states.length));
    } else if (b.key) e.appendChild(h("span", "sub", keyText(b.key)));
    else if (b.page) e.appendChild(h("span", "sub", "→ Seite"));
    if (b.mode === "hold-confirm") {
      e.appendChild(h("span", "hint", "HALTEN"));
      e.appendChild(h("span", "bar"));
    }
    if (b.mode === "toggle") {
      e.appendChild(h("span", "lamp"));
      var on = false;
      try { on = localStorage.getItem("toggle:" + b.id) === "1"; } catch (err) {}
      e.classList.toggle("on", on);
    }
    return e;
  }

  function makeSlider(b, extra) {
    var e = h("div", "slider btn-slider " + (b.style || "") + " " + (extra || "") + (b.wide ? " wide" : ""));
    e.setAttribute("data-id", b.id);
    e.appendChild(h("span", "fill"));
    e.appendChild(h("span", "lbl", b.label));
    e.appendChild(h("span", "val"));
    showSlider(e, sliderPos(b.id, b.slider.steps), b.slider.steps);
    return e;
  }

  // Tastenkürzel lesbar: "LALT+NUMPAD8" -> "Alt+Num8"
  var KEYNAMES = { LALT: "Alt", RALT: "AltGr", ALT: "Alt", LCTRL: "Strg", RCTRL: "Strg R", CTRL: "Strg",
    LSHIFT: "Shift", RSHIFT: "Shift R", SHIFT: "Shift", ENTER: "Enter", ESCAPE: "Esc", SPACE: "Leer",
    BACKSPACE: "Rück", TAB: "Tab", INSERT: "Einfg", DELETE: "Entf", HOME: "Pos1", END: "Ende",
    ESC: "Esc", PGUP: "Bild↑", PGDN: "Bild↓", UP: "↑", DOWN: "↓", LEFT: "←", RIGHT: "→",
    ADD: "Plus", SUBTRACT: "−", MULTIPLY: "×", DIVIDE: "÷", DECIMAL: "," };
  function keyText(k) {
    return String(k).toUpperCase().split("+").map(function (p) {
      p = p.trim();
      if (KEYNAMES[p]) return KEYNAMES[p];
      if (/^(NUMPAD|NP_|KP_)/.test(p)) {
        var r = p.replace(/^(NUMPAD|NP_|KP_)/, "");
        return "Num" + (KEYNAMES[r] || (r.length > 1 ? r.charAt(0) + r.slice(1).toLowerCase() : r));
      }
      return p.length > 1 ? p.charAt(0) + p.slice(1).toLowerCase() : p;
    }).join("+");
  }

  var SVGNS = "http://www.w3.org/2000/svg";
  function svg(tag, attrs) {
    var e = document.createElementNS(SVGNS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  function renderShield(p) {
    var root = h("div", "shield");
    var byZone = {};
    p.buttons.forEach(function (b) { byZone[b.zone] = b; });
    var W = 600, H = 400, cx = 300, cy = 200;
    var s = svg("svg", { viewBox: "0 0 " + W + " " + H, preserveAspectRatio: "xMidYMid meet" });
    var zones = {
      front: { pts: "0,0 600,0 300,200", lx: 300, ly: 45 },
      back:  { pts: "0,400 600,400 300,200", lx: 300, ly: 360 },
      left:  { pts: "0,0 0,400 300,200", lx: 70, ly: 200 },
      right: { pts: "600,0 600,400 300,200", lx: 530, ly: 200 }
    };
    Object.keys(zones).forEach(function (z) {
      var b = byZone[z]; if (!b) return;
      var poly = svg("polygon", { points: zones[z].pts, "class": "zone", "data-id": b.id });
      s.appendChild(poly);
      var t = svg("text", { x: zones[z].lx, y: zones[z].ly, "class": "zlabel" });
      t.textContent = b.label;
      s.appendChild(t);
    });
    // Schiff von oben (Spitze nach vorn)
    s.appendChild(svg("path", { "class": "ship", d:
      "M300,85 L318,140 L322,175 L395,215 L398,240 L325,232 L320,262 L345,290 L345,302 " +
      "L300,296 L255,302 L255,290 L280,262 L275,232 L202,240 L205,215 L278,175 L282,140 Z" }));
    root.appendChild(s);

    var side = h("div", "side");
    ["top", "reset", "bottom"].forEach(function (z) {
      if (byZone[z]) side.appendChild(makeBtn(byZone[z], z === "reset" ? "reset" : ""));
    });
    root.appendChild(side);
    return root;
  }

  function renderGrid(p) {
    var root = h("div");
    var groups = [], map = {};
    p.buttons.forEach(function (b) {
      var g = b.group || "";
      if (!map[g]) { map[g] = []; groups.push(g); }
      map[g].push(b);
    });
    groups.forEach(function (g) {
      var sec = h("section", "group");
      if (g) sec.appendChild(h("h2", null, g));
      var grid = h("div", "grid");
      map[g].forEach(function (b) {
        var e = makeBtn(b);
        if (b.slider) e.classList.add("wide");
        grid.appendChild(e);
      });
      sec.appendChild(grid);
      root.appendChild(sec);
    });
    return root;
  }

  // Freie Seite: Raster cols x rows, jede Taste über x, y, w, h (füllt die ganze Fläche)
  function renderFree(p) {
    var root = h("div", "free");
    root.style.gridTemplateColumns = "repeat(" + (p.cols || 12) + ", minmax(0, 1fr))";
    root.style.gridTemplateRows = "repeat(" + (p.rows || 8) + ", minmax(0, 1fr))";
    p.buttons.forEach(function (b) {
      var e = makeBtn(b);
      e.style.gridColumn = (b.x + 1) + " / span " + b.w;
      e.style.gridRow = (b.y + 1) + " / span " + b.h;
      root.appendChild(e);
    });
    return root;
  }

  function showPage(id) {
    cancelAll();
    var p = layout.pages.filter(function (x) { return x.id === id; })[0] || layout.pages[0];
    pageId = p.id;
    store("page:" + gameId + "/" + panelId, p.id);
    Array.prototype.forEach.call(tabsEl.children, function (t) {
      t.classList.toggle("on", t.getAttribute("data-page") === p.id);
    });
    pageEl.innerHTML = "";
    pageEl.classList.toggle("fill", p.type === "free" || p.type === "shield");
    pageEl.appendChild(p.type === "shield" ? renderShield(p) : p.type === "free" ? renderFree(p) : renderGrid(p));
    markUnmapped();
  }

  function markUnmapped() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-id]"), function (e) {
      e.classList.toggle("nomap", !!unmapped[e.getAttribute("data-id")]);
    });
  }

  function renderTabs() {
    tabsEl.innerHTML = "";
    layout.pages.forEach(function (p) {
      var t = h("button", null, p.title);
      t.setAttribute("data-page", p.id);
      t.addEventListener("click", function () { showPage(p.id); });
      tabsEl.appendChild(t);
    });
  }

  // ---------------- Spiele und Panels ----------------
  function gameById(id) { return games.filter(function (g) { return g.id === id; })[0]; }
  function initials(name) {
    var w = name.replace(/[^A-Za-z0-9 ]/g, " ").split(/\s+/).filter(Boolean);
    return ((w[0] || "?").charAt(0) + (w[1] || "").charAt(0)).toUpperCase();
  }

  // prefer: Spiel, das gezeigt werden soll (z. B. gerade gestartet); sonst das bisherige/gespeicherte
  function loadGames(prefer) {
    fetch("/api/games", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
      games = d.games.filter(function (g) { return g.panels.length; });
      var g = gameById(prefer) || gameById(gameId) || gameById(stored("game")) ||
        gameById((d.default || "").split("/")[0]) || games[0];
      if (!g) return;
      var keep = g.id === gameId ? panelId : stored("panel:" + g.id);
      var p = g.panels.filter(function (x) { return x.id === keep; })[0] || g.panels[0];
      selectPanel(g.id, p.id);
    }).catch(function () { setTimeout(function () { loadGames(prefer); }, 2000); });
  }

  function selectPanel(g, p) {
    gameId = g; panelId = p;
    store("game", g); store("panel:" + g, p);
    send({ t: "panel", game: g, panel: p });
    renderHead();
    loadLayout();
  }

  // Coverbild statt Initialen; bei Ladefehler zurück auf Initialen
  function setCover(el, g) {
    el.textContent = g ? initials(g.name) : "–";
    if (!g || !g.cover) return;
    var img = document.createElement("img");
    img.alt = "";
    img.style.cssText = "width:100%;height:100%;object-fit:cover;border-radius:inherit;display:block";
    img.addEventListener("error", function () { el.textContent = initials(g.name); });
    img.src = "/games/" + g.id + "/cover";
    el.textContent = "";
    el.appendChild(img);
  }

  function renderHead() {
    var g = gameById(gameId);
    setCover(gameEl.querySelector(".cv"), g);
    gameEl.querySelector(".gn").textContent = g ? g.name : "";
    gameEl.classList.toggle("multi", games.length > 1);
    panelsEl.innerHTML = "";
    (g ? g.panels : []).forEach(function (p) {
      var c = h("button", "chip" + (p.id === panelId ? " on" : ""), p.title);
      c.addEventListener("click", function () { if (p.id !== panelId) { cancelAll(); selectPanel(gameId, p.id); } });
      panelsEl.appendChild(c);
    });
    panelsEl.style.display = g && g.panels.length > 1 ? "" : "none";
  }

  // Spielwahl von Hand (nur wenn mehrere Spiele Panels haben)
  gameEl.addEventListener("click", function () {
    if (games.length < 2) return;
    pickEl.innerHTML = "";
    games.forEach(function (g) {
      var b = h("button", "chip" + (g.id === gameId ? " on" : ""));
      var cv = h("span", "cv");
      setCover(cv, g);
      b.appendChild(cv);
      b.appendChild(document.createTextNode(g.name));
      b.addEventListener("click", function () {
        pickEl.classList.remove("open");
        if (g.id === gameId) return;
        cancelAll();
        var keep = stored("panel:" + g.id);
        selectPanel(g.id, (g.panels.filter(function (x) { return x.id === keep; })[0] || g.panels[0]).id);
      });
      pickEl.appendChild(b);
    });
    pickEl.classList.add("open");
  });
  pickEl.addEventListener("click", function (e) { if (e.target === pickEl) pickEl.classList.remove("open"); });

  function loadLayout() {
    var key = gameId + "/" + panelId;
    fetch("/profiles/" + key + ".json", { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    }).then(function (l) {
      if (key !== gameId + "/" + panelId) return;   // inzwischen anderes Panel gewählt
      layout = l;
      unmapped = {};
      (l.unmapped || []).forEach(function (id) { unmapped[id] = 1; });
      document.documentElement.style.setProperty("--hold", (l.holdMs || 1000) + "ms");
      renderTabs();
      showPage(stored("page:" + key));
    }).catch(function () { setTimeout(function () { loadGames(null); }, 2000); });
  }

  // ---------------- Bildschirm an / Vollbild ----------------
  var wakeLock = null;
  function keepAwake() {
    if (navigator.wakeLock && !wakeLock) {
      navigator.wakeLock.request("screen").then(function (l) {
        wakeLock = l; l.addEventListener("release", function () { wakeLock = null; });
      }).catch(function () {});
    }
  }
  document.addEventListener("visibilitychange", function () { if (!document.hidden) keepAwake(); });
  var fsPending = false;
  document.addEventListener("pointerup", function () {
    keepAwake();
    if (fsPending) {   // Touch: Vollbild darf erst beim Loslassen angefordert werden
      fsPending = false;
      document.documentElement.requestFullscreen().catch(function () { fsTried = true; });
    }
  });

  setConn(false);
  connect();   // "hello" vom Hub lädt Spiele und Panel
})();
