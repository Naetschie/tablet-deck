"use strict";
// Editor am PC im Browser: Verbindung, Spiel-/Panelwahl, Speichern, Dialog „Automatisch erzeugen“ und Reiter.
// Zugang nur mit Token aus dem Taskleisten-Symbol (#k=…). Der Panel-Baukasten selbst liegt in panel.js,
// der Reiter „Dashboards“ in dash.js.
(function () {
  var token = (location.hash.match(/k=([A-Za-z0-9_-]+)/) || [])[1];
  var ws = null, layout = null, saved = "", pendingSave = null, keyNames = [];
  var games = [], cur = { game: null, panel: null };   // Spiel/Panel im Editor
  var isNew = false;   // aktuelles Panel ist ein noch nie gespeicherter Entwurf
  var actionsFor = null;   // Spiel, für das die Palette (Spielaktionen) geladen wurde
  var $ = function (id) { return document.getElementById(id); };

  // ---------------------------------------------------------------- Verbindung
  function status(text, cls) { var s = $("status"); s.textContent = text; s.className = cls || ""; }
  function send(o) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); }
  // Das Layout gehört dem Baukasten (er ändert es an Ort und Stelle); hier wird nur getauscht
  function setLayout(l) {
    layout = l;
    if (l) PanelEditor.load(l); else PanelEditor.clear();
  }

  function connect() {
    if (!token) { status("Kein Zugangstoken – Editor über das Taskleisten-Symbol öffnen.", "err"); return; }
    ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/edit");
    ws.onopen = function () {
      actionsFor = null;
      ws.send(JSON.stringify({ t: "auth", k: token })); ws.send(JSON.stringify({ t: "games" }));
      DashEditor.onOpen();
    };
    ws.onmessage = function (ev) {
      var m = JSON.parse(ev.data);
      if (DashEditor.onMessage(m)) return;      // dash_* und deren Fehler: Reiter „Dashboards“ (dash.js)
      if (PanelEditor.onMessage(m)) return;     // actions und dessen Fehler: Palette (panel.js)
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
        keyNames = m.keys;
        PanelEditor.setKeys(m.keys, m.media);
        var dl = $("keyNames"); dl.innerHTML = "";
        keyNames.forEach(function (k) { var o = document.createElement("option"); o.value = k; dl.appendChild(o); });
        var other = m.game !== cur.game || m.panel !== cur.panel;
        if (other && isDirty()) { status("Panel nicht gefunden – Änderungen bleiben erhalten, Speichern legt es neu an", "err"); return; }
        if (!layout || !isDirty() || other) {
          cur = { game: m.game, panel: m.panel }; isNew = false;
          saved = JSON.stringify(m.layout);
          setLayout(m.layout);
          renderSelects(); syncFields(); status("Geladen", "ok");
        }
      } else if (m.t === "created" || m.t === "deleted") {
        games = m.games;
        if (m.t === "created") cur = { game: m.game, panel: m.panel };
        else { var g2 = games.filter(function (x) { return x.id === cur.game; })[0]; cur.panel = g2 && g2.panels[0] ? g2.panels[0].id : null; }
        saved = ""; setLayout(null); syncFields(); renderSelects();
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
      DashEditor.onClose();
      // laufende KI-Anfrage: Antwort geht verloren - Knopf wieder freigeben
      if ($("genAiRun").disabled) { $("genAiRun").disabled = false; $("genReport").textContent = "Verbindung unterbrochen – KI-Ergebnis verloren, bitte erneut erzeugen."; }
      if (ev.code === 4001) { status("Zugangstoken ungültig (Bridge neu gestartet?) – Editor neu über das Taskleisten-Symbol öffnen.", "err"); return; }
      status("Verbindung zur Bridge getrennt – neuer Versuch …", "err");
      setTimeout(connect, 2000);
    };
  }
  function isDirty() { return layout && JSON.stringify(layout) !== saved; }
  function changed() {
    if (document.activeElement !== $("holdMs")) syncFields();
    if (isDirty()) status("Ungespeicherte Änderungen", "dirty"); else status("Gespeichert", "ok");
  }
  // Titel und Haltezeit in der Kopfleiste (nach Laden, Rückgängig usw.)
  function syncFields() {
    $("holdMs").value = layout ? layout.holdMs || 1000 : "";
    if (document.activeElement !== $("panelTitle")) $("panelTitle").value = layout ? layout.title || "" : "";
  }
  window.addEventListener("beforeunload", function (e) { if (isDirty() || DashEditor.isDirty()) { e.preventDefault(); e.returnValue = ""; } });

  $("save").onclick = function () {
    if (!layout) return;
    if (!ws || ws.readyState !== 1) { status("Keine Verbindung zur Bridge – nicht gespeichert", "err"); return; }
    var ph = 0;
    layout.pages.forEach(function (pg) { pg.buttons.forEach(function (b) { if (PanelLib.hasPlaceholder(b)) ph++; }); });
    if (ph && !confirm(ph + " Taste(n) haben noch Platzhalter-Tasten (Rollen bzw. Bild↑/Bild↓) und senden diese am "
      + "Tablet wirklich an den PC. Trotzdem speichern?")) return;
    pendingSave = JSON.stringify(layout);   // dieser Stand gilt nach der Bestätigung als gespeichert
    ws.send(JSON.stringify({ t: "save", game: cur.game, panel: cur.panel, layout: layout, new: isNew }));
    status("Speichere …", "");
  };
  $("revert").onclick = function () {
    if (!layout || !saved) return;
    if (isDirty() && !confirm("Alle ungespeicherten Änderungen verwerfen?")) return;
    setLayout(JSON.parse(saved)); syncFields(); changed();
  };
  $("holdMs").onchange = function () { if (!layout) return; layout.holdMs = parseInt(this.value, 10) || 1000; PanelEditor.checkpoint(); changed(); };
  $("panelTitle").oninput = function () { if (!layout) return; layout.title = this.value; changed(); };
  $("panelTitle").onchange = function () { PanelEditor.checkpoint(); };

  // ---------------------------------------------------------------- Spiele und Panels
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
    var panels = (g ? g.panels : []).map(function (p) { return { id: p.id, title: p.title }; });
    if (cur.panel && !(g && g.panels.some(function (p) { return p.id === cur.panel; }))) {
      var t = (layout && layout.title || cur.panel) + " (neu, ungespeichert)";
      ps.appendChild(el("option", { value: cur.panel, text: t }));
      panels.push({ id: cur.panel, title: layout && layout.title || cur.panel });
    }
    ps.value = cur.panel || "";
    $("dupPanel").disabled = $("delPanel").disabled = !cur.panel;
    PanelEditor.setInfo({ game: g ? g.name : "", panels: panels, panel: cur.panel });
    if (cur.game && cur.game !== actionsFor && ws && ws.readyState === 1) { actionsFor = cur.game; PanelEditor.requestActions(cur.game); }
  }
  $("gameSel").onchange = function () {
    var v = this.value;
    if (!leaveOk()) { this.value = cur.game; return; }
    var g = games.filter(function (x) { return x.id === v; })[0];
    cur = { game: v, panel: g && g.panels[0] ? g.panels[0].id : null };
    saved = ""; setLayout(null); syncFields(); renderSelects();
    if (cur.panel) get(); else status("Noch kein Panel – mit „+ Panel“ anlegen", "");
  };
  $("panelSel").onchange = function () {
    if (!leaveOk()) { this.value = cur.panel; return; }
    cur.panel = this.value; saved = ""; setLayout(null); syncFields(); get();
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
    cur.panel = id; saved = ""; isNew = true;
    setLayout(genLast.layout);      // der Entwurf öffnet sich im Baukasten
    $("genDlg").close();
    renderSelects(); syncFields();
    status("Entwurf „" + t + "“ – noch nicht gespeichert. Anpassen, dann Speichern legt das Panel an.", "dirty");
  };

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
  function uniqueId(base, taken) { var i = 1, id = base; while (taken(id)) id = base + "_" + (++i); return id; }

  // ---------------------------------------------------------------- Reiter Panels / Dashboards
  // Der Panel-Editor bleibt beim Wechsel unverändert (nur ausgeblendet)
  var dashTab = false;
  function showTab(name) {
    var dash = name === "dash";
    if (dashTab && !dash && !DashEditor.canLeave()) return;     // ungespeicherte Dashboard-Änderungen: nachfragen
    dashTab = dash;
    $("viewPanels").hidden = dash; $("toolbar").hidden = dash; $("panelTools").hidden = dash;
    $("viewDash").hidden = !dash; $("dashToolbar").hidden = !dash;
    $("tabBtnPanels").className = dash ? "" : "on"; $("tabBtnDash").className = dash ? "on" : "";
    try { sessionStorage.setItem("editorTab", name); } catch (e) { /* ohne Speicher: Panels */ }
    if (dash) { PanelEditor.deactivate(); DashEditor.activate(); }
    else { DashEditor.deactivate(); PanelEditor.activate(); if (layout) changed(); else status("", ""); }
  }
  Array.prototype.forEach.call($("mainTabs").querySelectorAll("button"), function (bt) {
    bt.onclick = function () { PanelEditor.stopCapture(); showTab(bt.getAttribute("data-tab")); };
  });

  // Strg+S speichert
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); if (dashTab) DashEditor.save(); else $("save").click(); }
  });
  PanelEditor.init({ send: send, status: status, changed: changed });
  DashEditor.init({ send: send, status: status, isOpen: function () { return !!ws && ws.readyState === 1; } });
  PanelEditor.activate();
  connect();
  try { if (sessionStorage.getItem("editorTab") === "dash") showTab("dash"); } catch (e) { /* egal */ }
})();
