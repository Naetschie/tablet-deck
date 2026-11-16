"use strict";
// Panel-Editor (am PC im Browser). Zugang nur mit Token aus dem Taskleisten-Symbol (#k=…).
(function () {
  var token = (location.hash.match(/k=([A-Za-z0-9_-]+)/) || [])[1];
  var ws = null, layout = null, saved = "", pendingSave = null, keyNames = [], mediaNames = [];
  var pageIdx = 0, btnIdx = -1;
  var games = [], cur = { game: null, panel: null };   // Spiel/Panel im Editor
  var isNew = false;   // aktuelles Panel ist ein noch nie gespeicherter Entwurf
  var $ = function (id) { return document.getElementById(id); };

  // ---------------------------------------------------------------- Verbindung
  function status(text, cls) { var s = $("status"); s.textContent = text; s.className = cls || ""; }

  function connect() {
    if (!token) { status("Kein Zugangstoken – Editor über das Taskleisten-Symbol öffnen.", "err"); return; }
    ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/edit");
    ws.onopen = function () { ws.send(JSON.stringify({ t: "auth", k: token })); ws.send(JSON.stringify({ t: "games" })); };
    ws.onmessage = function (ev) {
      var m = JSON.parse(ev.data);
      if (m.t === "games") {
        games = m.games;
        if (!cur.game) {
          var g = games.filter(function (x) { return x.id === m.current && x.panels.length; })[0] ||
            games.filter(function (x) { return x.panels.length; })[0];
          if (g) cur = { game: g.id, panel: g.panels[0].id };
        }
        renderSelects();
        get();
      } else if (m.t === "layout") {
        keyNames = m.keys; mediaNames = m.media;
        var dl = $("keyNames"); dl.innerHTML = "";
        keyNames.forEach(function (k) { var o = document.createElement("option"); o.value = k; dl.appendChild(o); });
        var other = m.game !== cur.game || m.panel !== cur.panel;
        if (other && isDirty()) { status("Panel nicht gefunden – Änderungen bleiben erhalten, Speichern legt es neu an", "err"); return; }
        if (!layout || !isDirty() || other) {
          cur = { game: m.game, panel: m.panel }; isNew = false;
          layout = m.layout; saved = JSON.stringify(layout); pageIdx = 0; btnIdx = -1;
          renderSelects(); render(); status("Geladen", "ok");
        }
      } else if (m.t === "created" || m.t === "deleted") {
        games = m.games;
        if (m.t === "created") cur = { game: m.game, panel: m.panel };
        else { var g2 = games.filter(function (x) { return x.id === cur.game; })[0]; cur.panel = g2 && g2.panels[0] ? g2.panels[0].id : null; }
        layout = null; saved = ""; clearView(); renderSelects();
        if (cur.panel) get(); else status("Noch kein Panel – mit „+ Panel“ anlegen", "");
      } else if (m.t === "templates") {
        genTemplates(m);
      } else if (m.t === "draft") {
        genDraft(m);
      } else if (m.t === "saved") {
        saved = pendingSave; pendingSave = null;
        if (isNew) { isNew = false; send({ t: "games" }); }   // neues Panel in der Auswahl zeigen
        if (isDirty()) changed(); else status("Gespeichert – Tablet aktualisiert sich", "ok");
      } else if (m.t === "error" && (m.req === "generate" || m.req === "templates" || m.req === "ai")) {
        if (m.req === "ai") $("genAiRun").disabled = false;
        $("genReport").textContent = "Fehler: " + m.msg;
      } else if (m.t === "error") {
        pendingSave = null;
        if (m.req === "save" && isNew && m.code === "exists") {
          // Name belegt (z. B. ungültige Datei gleichen Namens): freie id wählen, Entwurf bleibt erhalten
          var taken = {}; taken[cur.panel] = 1;
          (curGame() ? curGame().panels : []).forEach(function (p) { taken[p.id] = 1; });
          cur.panel = uniqueId(cur.panel.slice(0, 36), function (x) { return taken[x]; }).replace(/_/g, "-");
          renderSelects();
          status("Name war schon vergeben – als „" + cur.panel + "“ neu benannt. Bitte erneut speichern.", "dirty");
        } else {
          status("Nicht gespeichert: " + m.msg, "err");
        }
      }
    };
    ws.onclose = function (ev) {
      // laufende KI-Anfrage: Antwort geht verloren - Knopf wieder freigeben
      if ($("genAiRun").disabled) { $("genAiRun").disabled = false; $("genReport").textContent = "Verbindung unterbrochen – KI-Ergebnis verloren, bitte erneut erzeugen."; }
      if (ev.code === 4001) { status("Zugangstoken ungültig (Bridge neu gestartet?) – Editor neu über das Taskleisten-Symbol öffnen.", "err"); return; }
      status("Verbindung zur Bridge getrennt – neuer Versuch …", "err");
      setTimeout(connect, 2000);
    };
  }
  function isDirty() { return layout && JSON.stringify(layout) !== saved; }
  function changed() { if (isDirty()) status("Ungespeicherte Änderungen", "dirty"); else status("Gespeichert", "ok"); }
  window.addEventListener("beforeunload", function (e) { if (isDirty()) { e.preventDefault(); e.returnValue = ""; } });

  $("save").onclick = function () {
    if (!layout) return;
    if (!ws || ws.readyState !== 1) { status("Keine Verbindung zur Bridge – nicht gespeichert", "err"); return; }
    pendingSave = JSON.stringify(layout);   // dieser Stand gilt nach der Bestätigung als gespeichert
    ws.send(JSON.stringify({ t: "save", game: cur.game, panel: cur.panel, layout: layout, new: isNew }));
    status("Speichere …", "");
  };
  $("revert").onclick = function () { if (!layout || !saved) return; layout = JSON.parse(saved); pageIdx = Math.min(pageIdx, layout.pages.length - 1); btnIdx = -1; render(); changed(); };
  $("holdMs").onchange = function () { if (!layout) return; layout.holdMs = parseInt(this.value, 10) || 1000; changed(); };
  $("panelTitle").oninput = function () { if (!layout) return; layout.title = this.value; changed(); };

  // ---------------------------------------------------------------- Spiele und Panels
  function send(o) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); }
  function get() { if (cur.game && cur.panel) send({ t: "get", game: cur.game, panel: cur.panel }); }
  function curGame() { return games.filter(function (g) { return g.id === cur.game; })[0]; }
  function leaveOk() { return !isDirty() || confirm("Ungespeicherte Änderungen verwerfen?"); }
  function renderSelects() {
    var gs = $("gameSel"), ps = $("panelSel");
    gs.innerHTML = ""; ps.innerHTML = "";
    games.forEach(function (g) {
      gs.appendChild(el("option", { value: g.id, text: g.name + (g.panels.length ? "" : " (noch keine Panels)") }));
    });
    gs.value = cur.game || "";
    var g = curGame();
    (g ? g.panels : []).forEach(function (p) { ps.appendChild(el("option", { value: p.id, text: p.title })); });
    if (cur.panel && !(g && g.panels.some(function (p) { return p.id === cur.panel; })))
      ps.appendChild(el("option", { value: cur.panel, text: (layout && layout.title || cur.panel) + " (neu, ungespeichert)" }));
    ps.value = cur.panel || "";
    $("dupPanel").disabled = $("delPanel").disabled = !cur.panel;
  }
  $("gameSel").onchange = function () {
    var v = this.value;
    if (!leaveOk()) { this.value = cur.game; return; }
    var g = games.filter(function (x) { return x.id === v; })[0];
    cur = { game: v, panel: g && g.panels[0] ? g.panels[0].id : null };
    layout = null; saved = ""; clearView(); renderSelects();
    if (cur.panel) get(); else { clearView(); status("Noch kein Panel – mit „+ Panel“ anlegen", ""); }
  };
  $("panelSel").onchange = function () {
    if (!leaveOk()) { this.value = cur.panel; return; }
    cur.panel = this.value; layout = null; get();
  };
  function slug(t) {
    return t.toLowerCase().replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss")
      .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 36) || "panel";
  }
  function newPanel(copy) {
    if (!cur.game || (copy && !layout) || !leaveOk()) return;
    var title = prompt(copy ? "Titel der Kopie:" : "Titel des neuen Panels (z. B. Bergbau):", copy ? layout.title + " (Kopie)" : "");
    if (!title) return;
    var taken = {}; (curGame() ? curGame().panels : []).forEach(function (p) { taken[p.id] = 1; });
    send({ t: "create", game: cur.game, panel: uniqueId(slug(title), function (x) { return taken[x]; }).replace(/_/g, "-"),
      title: title.slice(0, 40), copy: copy ? cur.game + "/" + cur.panel : null });
  }
  $("newPanel").onclick = function () { newPanel(false); };
  $("dupPanel").onclick = function () { newPanel(true); };
  $("delPanel").onclick = function () {
    if (!cur.panel || !confirm("Panel „" + (layout && layout.title || cur.panel) + "“ löschen? (landet in profiles/.papierkorb)")) return;
    send({ t: "delete", game: cur.game, panel: cur.panel });
  };
  // ---------------------------------------------------------------- Automatisch erzeugen
  var genLast = null, genList = [];
  $("genPanel").onclick = function () {
    if (!cur.game) return;
    $("genReport").innerHTML = ""; $("genTake").disabled = true; genLast = null;
    $("genSource").textContent = "Vorlagen werden geladen …";
    send({ t: "templates", game: cur.game });
    $("genDlg").showModal();
  };
  $("genClose").onclick = function () { $("genDlg").close(); };
  function genTemplates(m) {
    genList = m.templates;
    var sel = $("genTpl"); sel.innerHTML = "";
    $("genRun").disabled = !genList.length;
    $("genAi").open = !genList.length;
    if (!genList.length) {
      $("genSource").textContent = "Für dieses Spiel gibt es noch keine Vorlage – unten mit KI erstellen.";
      renderGenPages(); return;
    }
    $("genSource").textContent = m.bindings ? "Tasten kommen aus deiner Belegung im Spiel, sonst aus der Vorlage."
      : "Keine Belegungsquelle für dieses Spiel – Tasten kommen aus der Vorlage (Standardbelegung des Spiels).";
    genList.forEach(function (t) { sel.appendChild(el("option", { value: t.id, text: t.title })); });
    renderGenPages();
  }
  function renderGenPages() {
    var box = $("genPages"); box.innerHTML = "";
    var t = genList.filter(function (x) { return x.id === $("genTpl").value; })[0];
    (t ? t.pages : []).forEach(function (p) {
      var c = el("input", { type: "checkbox", value: p.id }); c.checked = true;
      box.appendChild(el("label", { cls: "check" }, [c, document.createTextNode(p.title)]));
    });
  }
  $("genTpl").onchange = function () { renderGenPages(); $("genReport").innerHTML = ""; $("genTake").disabled = true; };
  $("genAiRun").onclick = function () {
    if (!cur.game) return;
    if (!ws || ws.readyState !== 1) { $("genReport").textContent = "Keine Verbindung zum Hub – bitte erneut versuchen."; return; }
    $("genAiRun").disabled = true;   // kostenpflichtig: nicht doppelt auslösen
    send({ t: "ai", game: cur.game, hint: $("genHint").value });
    $("genReport").textContent = "KI erstellt die Vorlage … (dauert meist unter einer Minute)";
    $("genTake").disabled = true;
  };
  $("genRun").onclick = function () {
    var tid = $("genTpl").value; if (!tid) return;
    var pages = Array.prototype.filter.call($("genPages").querySelectorAll("input"), function (c) { return c.checked; })
      .map(function (c) { return c.value; });
    if (!pages.length) { $("genReport").textContent = "Mindestens eine Seite wählen."; return; }
    send({ t: "generate", game: cur.game, template: tid, pages: pages });
    $("genReport").textContent = "Erzeuge …";
  };
  function genDraft(m) {
    if (m.template === "ki") $("genAiRun").disabled = false;
    if (m.game !== cur.game || (m.template !== "ki" && m.template !== $("genTpl").value)) return;   // inzwischen andere Vorlage gewählt
    var lay = m.layout, rows = m.report;   // der Hub hat die gewählten Seiten schon gefiltert
    genLast = { layout: lay, template: m.template };
    var ok = rows.filter(function (r) { return r.source === "Belegung"; }).length;
    var miss = rows.filter(function (r) { return r.source === "fehlt"; }).length;
    var box = $("genReport"); box.innerHTML = "";
    box.appendChild(el("p", { cls: "gen-sum", text: "Quelle: " + m.source + " · " + rows.length + " Tasten: " + ok +
      " aus deiner Belegung, " + (rows.length - ok - miss) + " aus der Vorlage, " + miss + " ohne Taste" }));
    var tb = el("tbody");
    rows.forEach(function (r) {
      var note = r.note || "";
      if (r.source === "fehlt" && r.suggest) note += (note ? " – " : "") + "Vorschlag: im Spiel auf " + r.suggest + " legen";
      tb.appendChild(el("tr", { cls: r.source === "fehlt" ? "fehlt" : "" }, [
        el("td", { text: r.page }), el("td", { text: r.label }), el("td", { cls: "k", text: r.key || "–" }),
        el("td", { text: r.source }), el("td", { text: note })]));
    });
    var head = el("tr", {}, ["Seite", "Taste", "Kürzel", "Quelle", "Hinweis"].map(function (h) { return el("th", { text: h }); }));
    box.appendChild(el("table", { cls: "rep" }, [el("thead", {}, [head]), tb]));
    $("genTake").disabled = !lay.pages.length;
  }
  $("genTake").onclick = function () {
    if (!genLast || !leaveOk()) return;
    var panels = curGame() ? curGame().panels : [], taken = {}, titles = {};
    panels.forEach(function (p) { taken[p.id] = 1; titles[p.title] = 1; });
    var base = (genLast.layout.title || (genLast.template === "ki" ? "KI-Panel" : genLast.template)).slice(0, 36);
    var id = uniqueId(slug(base), function (x) { return taken[x]; }).replace(/_/g, "-");
    var t = base, n = 2;
    while (titles[t]) t = base + " " + (n++);
    genLast.layout.title = t;
    cur.panel = id; layout = genLast.layout; saved = ""; pageIdx = 0; btnIdx = -1; isNew = true;
    $("genDlg").close();
    renderSelects(); render();
    status("Entwurf „" + t + "“ – noch nicht gespeichert. Anpassen, dann Speichern legt das Panel an.", "dirty");
  };

  function clearView() { ["pages", "buttons", "pageProps"].forEach(function (id) { $(id).innerHTML = ""; });
    $("buttonProps").innerHTML = ""; $("panelTitle").value = ""; }

  // ---------------------------------------------------------------- Hilfen
  function el(tag, props, children) {
    var e = document.createElement(tag);
    for (var k in props || {}) {
      if (k === "text") e.textContent = props[k];
      else if (k === "cls") e.className = props[k];
      else if (k.slice(0, 2) === "on") e.addEventListener(k.slice(2), props[k]);
      else e.setAttribute(k, props[k]);
    }
    (children || []).forEach(function (c) { if (c) e.appendChild(c); });
    return e;
  }
  function field(label, input, hint) {
    return el("label", {}, [document.createTextNode(label), input, hint ? el("span", { cls: "hint", text: hint }) : null]);
  }
  function input(value, onchange, attrs) {
    var i = el("input", attrs || {});
    i.value = value == null ? "" : value;
    i.addEventListener("input", function () { onchange(i.value); });
    return i;
  }
  function select(value, options, onchange) {
    var s = el("select");
    options.forEach(function (o) { var op = el("option", { value: o[0], text: o[1] }); if (o[0] === (value || "")) op.selected = true; s.appendChild(op); });
    s.addEventListener("change", function () { onchange(s.value); });
    return s;
  }
  function uniqueId(base, taken) { var i = 1, id = base; while (taken(id)) id = base + "_" + (++i); return id; }
  function allButtonIds() { var ids = {}; layout.pages.forEach(function (p) { p.buttons.forEach(function (b) { ids[b.id] = 1; }); }); return ids; }
  function move(arr, from, to) { if (to < 0 || to >= arr.length) return; arr.splice(to, 0, arr.splice(from, 1)[0]); }
  function page() { return layout.pages[pageIdx]; }

  // ---------------------------------------------------------------- Seiten
  function renderPages() {
    renderPageList();
    renderPageProps();
  }
  // nur die Liste: beim Tippen im Titelfeld bleibt das Feld (und sein Fokus) erhalten
  function renderPageList() {
    var ul = $("pages"); ul.innerHTML = "";
    layout.pages.forEach(function (p, i) {
      ul.appendChild(el("li", { cls: i === pageIdx ? "sel" : "", onclick: function () { pageIdx = i; btnIdx = -1; render(); } }, [
        el("span", { cls: "name", text: p.title }),
        el("span", { cls: "meta", text: p.type === "shield" ? "Schild" : p.buttons.length }),
        el("button", { cls: "ghost small", text: "↑", title: "nach oben", onclick: function (e) { e.stopPropagation(); move(layout.pages, i, i - 1); pageIdx = Math.max(0, i - 1); render(); changed(); } }),
        el("button", { cls: "ghost small", text: "↓", title: "nach unten", onclick: function (e) { e.stopPropagation(); move(layout.pages, i, i + 1); pageIdx = Math.min(layout.pages.length - 1, i + 1); render(); changed(); } })
      ]));
    });
  }
  function renderPageProps() {
    var p = page(), box = $("pageProps"); box.innerHTML = "";
    if (!p) return;
    box.appendChild(field("Titel (Reiter)", input(p.title, function (v) { p.title = v; renderPageList(); $("pageHint").textContent = "– " + v; changed(); })));
    box.appendChild(field("Typ", select(p.type || "grid", [["grid", "Automatisch (nach Gruppen)"], ["free", "Frei (Raster)"],
      ["shield", "Schild (Zonen)"]], function (v) { setPageType(p, v); render(); changed(); }),
      p.type === "shield" ? "Schild: Tasten brauchen eine Zone." :
      p.type === "free" ? "Tasten in der Vorschau ziehen, Ecke unten rechts = Größe, Doppelklick auf eine freie Zelle = neue Taste." : null));
    if (p.type === "free") {
      var dims = el("div", { cls: "row" }, [
        field("Spalten", input(p.cols || 12, function (v) { setGrid(p, parseInt(v, 10), p.rows || 8); }, { type: "number", min: 2, max: 16 })),
        field("Zeilen", input(p.rows || 8, function (v) { setGrid(p, p.cols || 12, parseInt(v, 10)); }, { type: "number", min: 2, max: 12 }))]);
      box.appendChild(dims);
      box.appendChild(el("button", { cls: "ghost", text: "Neu anordnen (nach Gruppen)", onclick: function () {
        if (!confirm("Alle Tasten dieser Seite neu anordnen?")) return;
        if (!arrange(p)) return alert("Zu viele Tasten für das Raster.");
        render(); changed(); } }));
    }
    box.appendChild(el("button", { cls: "del", text: "Seite löschen", onclick: function () {
      if (layout.pages.length < 2) return alert("Mindestens eine Seite muss bleiben.");
      if (!confirm("Seite „" + p.title + "“ mit " + p.buttons.length + " Tasten löschen?")) return;
      var gone = p.id;
      layout.pages.splice(pageIdx, 1); pageIdx = Math.max(0, pageIdx - 1); btnIdx = -1;
      layout.pages.forEach(function (x) { x.buttons.forEach(function (b) { if (b.page === gone) { delete b.page; } }); });
      render(); changed();
    } }));
  }
  // ---------------------------------------------------------------- Freie Seiten (Raster)
  function setPageType(p, v) {
    if (v === "free" && p.type !== "free") {
      var copy = JSON.parse(JSON.stringify(p));
      if (!arrange(copy)) {
        alert("Zu viele Tasten für ein Raster (höchstens " + (copy.cols || 12) + " × 12) – Seite teilen oder Tasten entfernen.");
        return;
      }
      p.type = "free"; p.cols = copy.cols; p.rows = copy.rows;
      p.buttons.forEach(function (b, i) { var c = copy.buttons[i]; b.x = c.x; b.y = c.y; b.w = c.w; b.h = c.h; });
      return;
    }
    if (v !== "free" && p.type === "free") {
      p.buttons.forEach(function (b) { delete b.x; delete b.y; delete b.w; delete b.h; });
      delete p.cols; delete p.rows;
    }
    p.type = v;
    if (v === "shield") p.buttons.forEach(function (b) { if (!b.zone) b.zone = "front"; });
  }
  // Tasten nach Gruppen in Reihen legen (jede Gruppe beginnt eine neue Reihe); passt es nicht: schmaler, dann ohne
  // Gruppenumbruch. Gibt false zurück, wenn es auch so nicht in 12 Zeilen passt (Seite bleibt dann unverändert).
  function arrange(p) {
    var cols = p.cols || 12, rows = p.rows || 8;
    var tries = [[2, true], [1, true], [1, false]];
    for (var t = 0; t < tries.length; t++) {
      var w = tries[t][0], breakGroups = tries[t][1], x = 0, y = 0, last = null, pos = [];
      p.buttons.forEach(function (b) {
        var bw = b.wide && breakGroups ? cols : w;
        if (breakGroups && last !== null && (b.group || "") !== last && x > 0) { x = 0; y++; }
        if (x + bw > cols) { x = 0; y++; }
        pos.push([x, y, bw]); x += bw; last = b.group || "";
        if (x >= cols) { x = 0; y++; }
      });
      var used = pos.length ? Math.max.apply(null, pos.map(function (q) { return q[1] + 1; })) : 1;
      if (used <= 12) {
        p.buttons.forEach(function (b, i) { b.x = pos[i][0]; b.y = pos[i][1]; b.w = pos[i][2]; b.h = 1; });
        p.rows = Math.min(12, Math.max(rows, used)); p.cols = cols;
        return true;
      }
    }
    return false;
  }
  function overlaps(p) {
    var hit = {};
    p.buttons.forEach(function (a, i) {
      p.buttons.forEach(function (b, j) {
        if (i < j && a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h) { hit[i] = 1; hit[j] = 1; }
      });
    });
    return hit;
  }
  function setGrid(p, cols, rows) {
    if (!(cols >= 2 && cols <= 16 && rows >= 2 && rows <= 12)) return;
    p.cols = cols; p.rows = rows;
    p.buttons.forEach(function (b) {    // Tasten ins neue Raster holen
      b.w = Math.min(b.w || 1, cols); b.h = Math.min(b.h || 1, rows);
      b.x = Math.min(b.x || 0, cols - b.w); b.y = Math.min(b.y || 0, rows - b.h);
    });
    renderButtons(); changed();
  }
  function freeSpot(p, w, h) {
    var cols = p.cols || 12, rows = p.rows || 8;
    for (var y = 0; y + h <= rows; y++) for (var x = 0; x + w <= cols; x++) {
      var hit = p.buttons.some(function (b) { return x < b.x + b.w && b.x < x + w && y < b.y + b.h && b.y < y + h; });
      if (!hit) return { x: x, y: y };
    }
    return { x: 0, y: 0 };
  }

  function renderCanvas() {
    var box = $("canvasBox"); box.innerHTML = "";
    var p = page();
    if (!p || p.type !== "free") return;
    var cols = p.cols || 12, rows = p.rows || 8;
    var cv = el("div", { cls: "canvas" });
    var grid = el("div", { cls: "cell-grid" });
    grid.style.backgroundImage = "linear-gradient(var(--line) 1px, transparent 1px), linear-gradient(90deg, var(--line) 1px, transparent 1px)";
    grid.style.backgroundSize = (100 / cols) + "% " + (100 / rows) + "%";
    grid.style.opacity = ".5";
    cv.appendChild(grid);
    function place(e, b) {
      e.style.left = (b.x / cols * 100) + "%"; e.style.top = (b.y / rows * 100) + "%";
      e.style.width = "calc(" + (b.w / cols * 100) + "% - 4px)"; e.style.height = "calc(" + (b.h / rows * 100) + "% - 4px)";
      e.style.margin = "2px";
    }
    function cellAt(ev) {
      var r = cv.getBoundingClientRect();
      return { x: Math.max(0, Math.min(cols - 1, Math.floor((ev.clientX - r.left) / r.width * cols))),
        y: Math.max(0, Math.min(rows - 1, Math.floor((ev.clientY - r.top) / r.height * rows))) };
    }
    var over = overlaps(p), nOver = Object.keys(over).length;
    p.buttons.forEach(function (b, i) {
      var cls = ["blk", i === btnIdx ? "sel" : "", b.style || "", (b.key || b.macro || b.open || b.page || b.slider || b.states) ? "" : "nomap",
        over[i] ? "overlap" : ""].join(" ");
      var e = el("div", { cls: cls }, [document.createTextNode(b.label || "(ohne Text)"),
        el("small", { text: b.page ? "→ Seite" : b.slider ? "Regler" : b.states ? "Mehrfach (" + b.states.length + ")" : (b.key || (b.macro ? "Makro" : b.open ? "öffnen" : "")) }), el("span", { cls: "rs" })]);
      place(e, b);
      e.addEventListener("pointerdown", function (ev) {
        ev.preventDefault();
        if (btnIdx !== i) { btnIdx = i; renderProps(); Array.prototype.forEach.call(cv.querySelectorAll(".blk"), function (x) { x.classList.remove("sel"); }); e.classList.add("sel"); }
        var resize = ev.target.classList.contains("rs"), start = cellAt(ev), orig = { x: b.x, y: b.y, w: b.w, h: b.h }, moved = false;
        e.setPointerCapture(ev.pointerId);
        function mv(m) {
          var c = cellAt(m), dx = c.x - start.x, dy = c.y - start.y;
          if (resize) {
            b.w = Math.max(1, Math.min(cols - orig.x, orig.w + dx)); b.h = Math.max(1, Math.min(rows - orig.y, orig.h + dy));
          } else {
            b.x = Math.max(0, Math.min(cols - orig.w, orig.x + dx)); b.y = Math.max(0, Math.min(rows - orig.h, orig.y + dy));
          }
          if (b.x !== orig.x || b.y !== orig.y || b.w !== orig.w || b.h !== orig.h) moved = true;
          place(e, b);
        }
        function up() {
          e.removeEventListener("pointermove", mv); e.removeEventListener("pointerup", up); e.removeEventListener("pointercancel", up);
          if (moved) { renderCanvas(); renderProps(); changed(); }
        }
        e.addEventListener("pointermove", mv); e.addEventListener("pointerup", up); e.addEventListener("pointercancel", up);
      });
      cv.appendChild(e);
    });
    cv.addEventListener("dblclick", function (ev) {
      if (ev.target !== cv && ev.target !== grid) return;
      var c = cellAt(ev), ids = allButtonIds();
      var b = { id: uniqueId(p.id + "_taste", function (x) { return ids[x]; }), label: "NEU", mode: "tap",
        x: Math.min(c.x, cols - 2 < 0 ? 0 : cols - 2), y: c.y, w: Math.min(2, cols), h: 1 };
      p.buttons.push(b); btnIdx = p.buttons.length - 1; render(); changed();
    });
    box.appendChild(cv);
    box.appendChild(el("p", { cls: "hint canvas-hint", text: cols + " × " + rows + " Zellen · so verteilt erscheint die Seite am Tablet" }));
    if (nOver) box.appendChild(el("p", { cls: "err-box", text: nOver + " Tasten überlappen (rot) – am Tablet verdeckt eine die andere." }));
  }

  $("addPage").onclick = function () {
    if (!layout) return;
    var ids = {}; layout.pages.forEach(function (p) { ids[p.id] = 1; });
    layout.pages.push({ id: uniqueId("seite", function (x) { return ids[x]; }), title: "Neue Seite", type: "grid", buttons: [] });
    pageIdx = layout.pages.length - 1; btnIdx = -1; render(); changed();
  };

  // ---------------------------------------------------------------- Tasten
  var dragFrom = -1;
  function renderButtons() {
    var ul = $("buttons"); ul.innerHTML = "";
    var p = page(); if (!p) { $("canvasBox").innerHTML = ""; return; }
    $("pageHint").textContent = "– " + p.title;
    renderCanvas();
    p.buttons.forEach(function (b, i) {
      var cls = [i === btnIdx ? "sel" : "", b.style || "", (b.key || b.macro || b.open || b.page || b.slider || b.states) ? "" : "nomap"].join(" ");
      var meta = b.macro ? "Makro (" + b.macro.length + ")" : b.open ? "öffnet " + b.open : b.page ? "→ Seite" : b.slider ? "Regler (" + b.slider.steps + " Stufen)" : b.states ? "Mehrfach: " + b.states.map(function (x) { return x.label; }).join("/") : (b.key || "");
      if (b.mode === "hold-confirm") meta += " · halten"; if (b.mode === "toggle") meta += " · Schalter";
      if (b.group) meta = b.group + " · " + meta;
      var li = el("li", { cls: cls, draggable: "true", onclick: function () { btnIdx = i; render(); } }, [
        el("span", { cls: "name", text: b.label || "(ohne Text)" }), el("span", { cls: "meta", text: meta })
      ]);
      li.addEventListener("dragstart", function () { dragFrom = i; });
      li.addEventListener("dragover", function (e) { e.preventDefault(); li.classList.add("dragover"); });
      li.addEventListener("dragleave", function () { li.classList.remove("dragover"); });
      li.addEventListener("drop", function (e) {
        e.preventDefault(); if (dragFrom < 0 || dragFrom === i) return;
        move(p.buttons, dragFrom, i); btnIdx = i; dragFrom = -1; render(); changed();
      });
      ul.appendChild(li);
    });
  }
  $("addButton").onclick = function () {
    if (!layout) return;
    var p = page(), ids = allButtonIds();
    var b = { id: uniqueId(p.id + "_taste", function (x) { return ids[x]; }), label: "NEU", mode: "tap" };
    if (p.type === "shield") b.zone = "front";
    if (p.type === "free") { var s = freeSpot(p, Math.min(2, p.cols || 12), 1); b.x = s.x; b.y = s.y; b.w = Math.min(2, p.cols || 12); b.h = 1; }
    p.buttons.push(b); btnIdx = p.buttons.length - 1; render(); changed();
  };

  // ---------------------------------------------------------------- Eigenschaften
  var CODE = { Escape: "ESC", Enter: "ENTER", Tab: "TAB", Space: "SPACE", Backspace: "BACKSPACE", Delete: "DELETE",
    Insert: "INSERT", Home: "HOME", End: "END", PageUp: "PGUP", PageDown: "PGDN", ArrowUp: "UP", ArrowDown: "DOWN",
    ArrowLeft: "LEFT", ArrowRight: "RIGHT", ShiftLeft: "LSHIFT", ShiftRight: "RSHIFT", ControlLeft: "LCTRL",
    ControlRight: "RCTRL", AltLeft: "LALT", AltRight: "RALT", Minus: "MINUS", Equal: "EQUALS", BracketLeft: "LBRACKET",
    BracketRight: "RBRACKET", Semicolon: "SEMICOLON", Quote: "APOSTROPHE", Backquote: "GRAVE", Backslash: "BACKSLASH",
    Comma: "COMMA", Period: "PERIOD", Slash: "SLASH", CapsLock: "CAPSLOCK", ScrollLock: "SCROLLLOCK",
    NumpadAdd: "NUMPADADD", NumpadSubtract: "NUMPADSUBTRACT", NumpadMultiply: "NUMPADMULTIPLY",
    NumpadDivide: "NUMPADDIVIDE", NumpadDecimal: "NUMPADDECIMAL", NumpadEnter: "NUMPADENTER" };
  var MODS = ["LCTRL", "RCTRL", "LSHIFT", "RSHIFT", "LALT", "RALT"];
  function codeName(code) {
    if (CODE[code]) return CODE[code];
    var m = code.match(/^Key([A-Z])$/) || code.match(/^Digit([0-9])$/) || code.match(/^(F[0-9]{1,2})$/);
    if (m) return m[1];
    m = code.match(/^Numpad([0-9])$/); if (m) return "NUMPAD" + m[1];
    return null;
  }

  // Tastenaufnahme: höchstens eine aktiv; wird bei jedem Neuaufbau der Eigenschaften beendet
  var capture = null;
  function stopCapture() { if (capture) { capture(); capture = null; } }
  window.addEventListener("blur", stopCapture);

  function keyField(b) {
    var inp = input(b.key, function (v) { b.key = v.toUpperCase().replace(/\s+/g, ""); if (!b.key) delete b.key; renderButtons(); changed(); },
      { list: "keyNames", placeholder: "z. B. LALT+F oder NUMPAD8" });
    var rec = el("button", { cls: "ghost", text: "Aufnehmen" });
    var mods = {};
    function onUp(e) { var n = codeName(e.code); if (n) delete mods[n]; }
    function onKey(e) {
      e.preventDefault(); e.stopPropagation();
      var n = codeName(e.code); if (!n) return;
      if (MODS.indexOf(n) >= 0) { mods[n] = 1; return; }
      var combo = MODS.filter(function (x) { return mods[x]; }).concat([n]).join("+");
      inp.value = combo; b.key = combo; stopCapture(); renderButtons(); changed();
    }
    rec.onclick = function () {
      if (capture) return stopCapture();
      mods = {}; inp.classList.add("capture"); rec.textContent = "Taste drücken …";
      document.addEventListener("keydown", onKey, true); document.addEventListener("keyup", onUp, true);
      capture = function () {
        inp.classList.remove("capture"); rec.textContent = "Aufnehmen";
        document.removeEventListener("keydown", onKey, true); document.removeEventListener("keyup", onUp, true);
      };
    };
    var bad = b.key && b.key.split("+").some(function (k) { return keyNames.indexOf(k) < 0; });
    return field("Taste / Kombination", el("div", { cls: "row" }, [inp, rec]),
      bad ? "Unbekannter Tastenname – Speichern würde abgelehnt." : "Wird in Star Citizen o. Ä. als Tastendruck gesendet. Aufnehmen: Kombination auf der PC-Tastatur drücken.");
  }

  function macroToText(m) {
    return (m || []).map(function (s) { var k = Object.keys(s)[0]; return k + " " + s[k]; }).join("\n");
  }
  function textToMacro(t) {
    var out = [], errs = [];
    t.split("\n").forEach(function (raw, i) {
      var line = raw.replace(/^\s+/, "").replace(/\r$/, "");
      if (!line.trim() || line[0] === "#") return;
      if (line.slice(0, 5) !== "text ") line = line.trim();   // bei text Leerzeichen am Ende behalten
      var sp = line.indexOf(" "), k = sp < 0 ? line : line.slice(0, sp), v = sp < 0 ? "" : line.slice(sp + 1);
      if (k === "wait") { var n = parseInt(v, 10); if (isNaN(n)) errs.push("Zeile " + (i + 1) + ": wait braucht Millisekunden"); else out.push({ wait: n }); }
      else if (k === "key") out.push({ key: v.toUpperCase().replace(/\s+/g, "") });
      else if (k === "text") out.push({ text: v });
      else if (k === "media") { if (mediaNames.indexOf(v) < 0) errs.push("Zeile " + (i + 1) + ": media " + mediaNames.join("/")); out.push({ media: v }); }
      else errs.push("Zeile " + (i + 1) + ": unbekannt „" + k + "“ (key/text/wait/media)");
    });
    return { macro: out, errs: errs };
  }

  function statesToText(st) {
    return (st || []).map(function (x) { return x.key ? x.label + " = " + x.key : x.label; }).join("\n");
  }
  function textToStates(t) {
    var out = [], errs = [];
    t.split("\n").forEach(function (raw, i) {
      var line = raw.replace(/\r$/, "").trim();
      if (!line) return;
      var eq = line.indexOf("="), label = (eq < 0 ? line : line.slice(0, eq)).trim();
      var key = eq < 0 ? "" : line.slice(eq + 1).toUpperCase().replace(/\s+/g, "");
      if (!label || label.length > 20) errs.push("Zeile " + (i + 1) + ": Bezeichnung 1–20 Zeichen");
      if (key && key.split("+").some(function (k) { return keyNames.indexOf(k) < 0; })) errs.push("Zeile " + (i + 1) + ": unbekannte Taste");
      var o = { label: label }; if (key) o.key = key; out.push(o);
    });
    if (out.length < 2 || out.length > 6) errs.push("2–6 Zustände nötig (jetzt " + out.length + ").");
    return { states: out, errs: errs };
  }

  function renderProps() {
    stopCapture();
    var box = $("buttonProps"); box.innerHTML = "";
    var p = page(), b = p && p.buttons[btnIdx];
    if (!b) { box.appendChild(el("p", { cls: "dim", text: "Taste auswählen oder „+ Taste“." })); return; }
    box.appendChild(field("Beschriftung", input(b.label, function (v) { b.label = v; renderButtons(); changed(); })));
    box.appendChild(field("ID (eindeutig)", input(b.id, function (v) { b.id = v.trim(); renderButtons(); changed(); }),
      "Für Spiel-Belegungen und Automatik. Nur ändern, wenn nötig."));
    box.appendChild(field("Spielaktion (Star Citizen)", input(b.sc, function (v) { if (v.trim()) b.sc = v.trim(); else delete b.sc; changed(); },
      { placeholder: "z. B. v_target_cycle_hostile_fwd" }),
      "Optional. scripts/sc_bindings.py --write trägt dann die Taste aus der Spielbelegung ein."));
    if (p.type === "shield") {
      box.appendChild(field("Zone", select(b.zone, [["front", "Vorn"], ["back", "Hinten"], ["left", "Links"], ["right", "Rechts"],
        ["top", "Oben (Seite)"], ["bottom", "Unten (Seite)"], ["reset", "Reset (Seite)"]], function (v) { b.zone = v; changed(); })));
    } else {
      box.appendChild(field("Gruppe (Überschrift)", input(b.group, function (v) { if (v) b.group = v; else delete b.group; renderButtons(); changed(); })));
    }
    if (!b.page && !b.slider && !b.states) box.appendChild(field("Verhalten", select(b.mode || "tap", [["tap", "Drücken (gedrückt halten = Taste gehalten)"],
      ["hold-confirm", "Erst nach Halten auslösen (gefährlich)"], ["toggle", "Schalter (merkt An/Aus)"]],
      function (v) { b.mode = v; renderButtons(); changed(); })));
    box.appendChild(field("Farbe", select(b.style || "", [["", "Normal"], ["accent", "Blau"], ["danger", "Orange (Gefahr)"]],
      function (v) { if (v) b.style = v; else delete b.style; renderButtons(); changed(); })));
    var hold = el("input", { type: "checkbox" }); hold.checked = !!b.hold;
    hold.onchange = function () { if (hold.checked) b.hold = true; else delete b.hold; changed(); };
    if (!b.page && !b.slider) box.appendChild(field("", el("label", { cls: "check" }, [hold, document.createTextNode("Taste halten, solange der Finger liegt")]),
      "Aus = kurzer Impuls (80 ms) – nötig für die meisten Spielaktionen. An z. B. für Ping oder Hupe."));
    if (p.type === "free") {
      var cols = p.cols || 12, rows = p.rows || 8;
      function num(key, max) {
        var inp = input(b[key], function (v) {
          var n = parseInt(v, 10); if (isNaN(n)) return;
          b[key] = n;
          b.w = Math.max(1, Math.min(b.w, cols)); b.h = Math.max(1, Math.min(b.h, rows));
          b.x = Math.max(0, Math.min(b.x, cols - b.w)); b.y = Math.max(0, Math.min(b.y, rows - b.h));
          if (String(b[key]) !== inp.value) inp.value = b[key];   // begrenzten Wert anzeigen
          renderCanvas(); changed();
        }, { type: "number", min: 0, max: max });
        return inp;
      }
      box.appendChild(el("div", { cls: "row" }, [field("X", num("x", cols - 1)), field("Y", num("y", rows - 1)),
        field("Breite", num("w", cols)), field("Höhe", num("h", rows))]));
    }
    if (p.type === "grid" || !p.type) {
      var wide = el("input", { type: "checkbox" }); wide.checked = !!b.wide;
      wide.onchange = function () { if (wide.checked) b.wide = true; else delete b.wide; changed(); };
      box.appendChild(el("label", { cls: "check" }, [wide, document.createTextNode("Ganze Breite")]));
    }
    // Aktion: Taste, Makro oder Programm/URL am PC öffnen
    var kind = b.slider ? "slider" : b.states ? "states" : b.macro ? "macro" : b.open !== undefined ? "open" : b.page !== undefined ? "page" : "key";
    box.appendChild(field("Aktion", select(kind, [["key", "Taste / Kombination"], ["macro", "Makro (mehrere Schritte)"],
                                                  ["open", "Programm / URL am PC öffnen"], ["page", "Seiten-Link (am Tablet)"],
                                                  ["states", "Mehrfach-Schalter (2–6 Zustände)"], ["slider", "Regler (mehr / weniger)"]], function (v) {
      var firstKey = b.key || (b.macro && b.macro[0] && b.macro[0].key);
      delete b.macro; delete b.open; delete b.key; delete b.page; delete b.states; delete b.slider;
      if (v === "macro") b.macro = [{ key: firstKey || "SPACE" }];
      else if (v === "open") b.open = "https://";
      else if (v === "page") { b.page = (layout.pages.filter(function (x) { return x !== p; })[0] || p).id; delete b.mode; delete b.hold; }
      else if (v === "states") { b.mode = "tap"; if (firstKey) b.key = firstKey; b.states = [{ label: "AUS" }, { label: "AN" }]; }
      else if (v === "slider") { b.mode = "tap"; delete b.hold; b.slider = { steps: 10 }; }
      else if (firstKey) b.key = firstKey;
      renderButtons(); renderProps(); changed();
    })));
    if (kind === "page") {
      box.appendChild(field("Ziel-Seite", select(b.page, layout.pages.map(function (x) { return [x.id, x.title]; }),
        function (v) { b.page = v; renderButtons(); changed(); }), "Wechselt am Tablet auf diese Seite, sendet nichts an den PC."));
    } else if (kind === "key") box.appendChild(keyField(b));
    else if (kind === "states") {
      var sta = el("textarea"); sta.value = statesToText(b.states);
      var serr = el("div", { cls: "err-box" });
      sta.addEventListener("input", function () {
        var r = textToStates(sta.value);
        serr.textContent = r.errs.join("\n");
        if (!r.errs.length) { b.states = r.states; renderButtons(); changed(); }   // Textfeld bleibt unberührt
      });
      box.appendChild(field("Zustände – eine Zeile pro Zustand", sta,
        "BEZEICHNUNG = TASTE (Taste optional), 2–6 Zeilen, Bezeichnung bis 20 Zeichen. Jeder Tipp schaltet reihum weiter."));
      box.appendChild(serr);
      box.appendChild(keyField(b));
      box.appendChild(el("span", { cls: "hint", text: "Taste oben ist der Ersatz für Zustände ohne eigene Taste. Mindestens eine Quelle nötig." }));
    } else if (kind === "slider") {
      var sl = b.slider;
      function slKey(prop, label, ph) {
        var warn = el("span", { cls: "hint", text: "" });
        function chk() {
          var bad = sl[prop] && sl[prop].split("+").some(function (k) { return keyNames.indexOf(k) < 0; });
          warn.textContent = bad ? "Unbekannter Tastenname – Speichern würde abgelehnt." : "";
        }
        var lab = field(label, input(sl[prop], function (v) {
          v = v.toUpperCase().replace(/\s+/g, "");
          if (v) sl[prop] = v; else delete sl[prop];   // leer = Feld weglassen, bis gültig
          chk(); changed();
        }, { list: "keyNames", placeholder: ph }));
        lab.appendChild(warn); chk();
        return lab;
      }
      box.appendChild(slKey("up", "Taste „mehr“", "z. B. LALT+PGUP"));
      box.appendChild(slKey("down", "Taste „weniger“", "z. B. LALT+PGDN"));
      box.appendChild(field("Stufen (2–20)", input(sl.steps, function (v) {
        var n = parseInt(v, 10); if (n >= 2 && n <= 20) { sl.steps = n; renderButtons(); changed(); }
      }, { type: "number", min: 2, max: 20 }), "Jede überschrittene Stufe beim Ziehen sendet einen Tastendruck."));
    }
    else if (kind === "open") {
      var inp = el("input", { type: "text" }); inp.value = b.open || "";
      var oerr = el("div", { cls: "err-box" });
      inp.addEventListener("input", function () {
        var v = inp.value.trim();
        var ok = /^https?:\/\/\S+$/i.test(v) || /^[A-Za-z]:\\[^<>"|?*]+$/.test(v);
        oerr.textContent = ok ? "" : "http(s)-URL oder absoluter Pfad wie C:\\Programme\\App\\app.exe";
        if (ok) { b.open = v; renderButtons(); changed(); }
      });
      box.appendChild(field("Öffnen am PC", inp, "URL öffnet im Standardbrowser, ein Pfad startet Programm/Datei/Ordner."));
      box.appendChild(oerr);
    } else {
      var ta = el("textarea"); ta.value = macroToText(b.macro);
      var errBox = el("div", { cls: "err-box" });
      ta.addEventListener("input", function () {
        var r = textToMacro(ta.value);
        if (!r.macro.length && !r.errs.length) r.errs.push("Makro ist leer – mindestens ein Schritt nötig (alter Stand bleibt).");
        errBox.textContent = r.errs.join("\n");
        if (!r.errs.length && r.macro.length) { b.macro = r.macro; renderButtons(); changed(); }
      });
      box.appendChild(field("Makro – eine Zeile pro Schritt", ta,
        "key LALT+1 · text o7 · wait 200 (ms) · media playpause. Läuft beim Drücken einmal ab."));
      box.appendChild(errBox);
    }
    box.appendChild(el("div", { cls: "row" }, [
      el("button", { cls: "ghost", text: "Duplizieren", onclick: function () {
        var c = JSON.parse(JSON.stringify(b)), ids = allButtonIds(); c.id = uniqueId(b.id, function (x) { return ids[x]; });
        if (p.type === "free") { var s = freeSpot(p, b.w, b.h); c.x = s.x; c.y = s.y; }
        p.buttons.splice(btnIdx + 1, 0, c); btnIdx++; render(); changed();
      } }),
      el("button", { cls: "del", text: "Löschen", onclick: function () { p.buttons.splice(btnIdx, 1); btnIdx = -1; render(); changed(); } })
    ]));
  }

  function render() {
    if (!layout) return;
    $("holdMs").value = layout.holdMs || 1000;
    $("panelTitle").value = layout.title || "";
    renderPages(); renderButtons(); renderProps();
  }

  // Strg+S speichert
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); $("save").click(); }
  });
  connect();
})();
