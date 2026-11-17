"use strict";
// Panel-Baukasten (Reiter „Panels“ des Editors): Palette (Bausteine, Spielaktionen), Vorschau im Stil des Tablets mit
// Seitenreitern, Auswahl/Ziehen/Ausrichten über den Editor-Kern (core.js) in Zellen, Eigenschaften, Verlauf je Aktion.
// Spiel-/Panelwahl, Verbindung, Speichern und der Dialog „Automatisch erzeugen“ liegen in editor.js.
// Schnittstelle zu editor.js: init({send, changed, status}), load(layout), clear(), setInfo, setKeys, onMessage, requestActions.
// Alle Inhalte nur über textContent/value/setAttribute - nie innerHTML. Reine Logik: panellib.js.
(function () {
  var Core = EditorCore, PL = PanelLib;
  var VW = 1152, VH = 800;          // Fläche des Tablets (1280 x 800 ohne Leiste), Vorschau wird darauf skaliert
  var GAP = 8;                      // Abstand der Zellen auf freien Seiten (--sp-2 im Tablet)
  var DRAG_PX = 4;
  var api = null;                   // { send(obj), changed(), status(text, cls) } von editor.js
  var layout = null, hist = null, pageIdx = 0, sel = [], primary = null, active = false;
  var keyNames = [], mediaNames = [], info = { game: "", panels: [], panel: "" };
  var actionsData = null, actionsGame = null, actionsError = "", actionsQuery = "", openKeys = {};
  var dups = { groups: [], byId: Object.create(null), count: 0, keys: 0 }, dupHintEl = null;
  var scale = 1, drag = null, dragPayload = null, listDrag = -1, dropMark = null, marquee = null, toastTimer = 0;
  var $ = function (id) { return document.getElementById(id); };

  // ---------------------------------------------------------------- DOM-Hilfen
  function h(tag, props, children) {
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
  var SVGNS = "http://www.w3.org/2000/svg";
  function svg(tag, attrs) {
    var e = document.createElementNS(SVGNS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function field(label, inp, hint) {
    return h("label", {}, [document.createTextNode(label), inp, hint ? h("span", { cls: "hint", text: hint }) : null]);
  }
  function input(value, onchange, attrs) {
    var i = h("input", attrs || {});
    i.value = value == null ? "" : value;
    i.addEventListener("input", function () { onchange(i.value); });
    return i;
  }
  function select(value, options, onchange) {
    var s = h("select");
    options.forEach(function (o) { var op = h("option", { value: o[0], text: o[1] }); if (o[0] === (value || "")) op.selected = true; s.appendChild(op); });
    s.addEventListener("change", function () { onchange(s.value); });
    return s;
  }
  function page() { return layout && layout.pages[pageIdx]; }
  function isFree(p) { return !!p && p.type === "free"; }
  function btnById(id) { var p = page(); return p ? p.buttons.filter(function (b) { return b.id === id; })[0] : null; }
  // Doppelbelegung neu berechnen (billig); Treffer tragen die Klasse „dup“ in Vorschau und Liste
  function calcDups() { dups = layout ? PL.duplicates(layout) : { groups: [], byId: Object.create(null), count: 0, keys: 0 }; }
  function dupText(b, p) {
    var l = dups.byId[b.id];
    if (!l) return "";
    return l.map(function (d) {
      return keyText(d.key) + " auch bei: " + d.others.map(function (o) { return o.label + (o.page !== p.id ? " (" + o.pageTitle + ")" : ""); }).join(", ");
    }).join(" · ");
  }
  function updateDupHint() {
    var p = page(), b = sel.length === 1 ? btnById(sel[0]) : null;
    if (dupHintEl) { var t = p && b ? dupText(b, p) : ""; dupHintEl.textContent = t ? "Gleiche Taste wie: " + t : ""; dupHintEl.hidden = !t; }
    var n = $("dupNote");
    if (n) {
      n.hidden = !dups.count;
      n.textContent = dups.count ? "Doppelbelegung: " + dups.count + " Tasten teilen sich " + dups.keys + " Tastenkombination" + (dups.keys === 1 ? "" : "en") +
        " (gelb markiert; auch seitenübergreifend – am PC ist es dieselbe Taste). Nur ein Hinweis, Speichern geht." : "";
    }
  }
  function selButtons() { return sel.map(btnById).filter(Boolean); }

  // ---------------------------------------------------------------- Zustand und Verlauf
  function snap() { return layout; }
  function touch() { if (api) api.changed(); }
  // Aktion abschließen: Verlauf (ein Schritt je Aktion), Anzeige, Status
  function commit() {
    hist.push(snap());
    renderAll();
    touch();
  }
  function setSel(ids, prim) {
    sel = ids.slice();
    primary = prim && sel.indexOf(prim) >= 0 ? prim : (sel[0] || null);
  }
  function restore(text) {
    var st = JSON.parse(text);
    Object.keys(layout).forEach(function (k) { delete layout[k]; });
    Object.keys(st).forEach(function (k) { layout[k] = st[k]; });
    pageIdx = Math.max(0, Math.min(pageIdx, layout.pages.length - 1));
    sel = sel.filter(function (id) { return !!btnById(id); });
    primary = sel.indexOf(primary) >= 0 ? primary : (sel[0] || null);
  }
  function undo(redo) {
    if (!hist) return;
    var st = redo ? hist.redo() : hist.undo();
    if (!st) return;
    restore(JSON.stringify(st));
    renderAll(); touch();
  }

  // ---------------------------------------------------------------- Palette: Bausteine
  function renderBlocks() {
    var box = $("blocks"); clear(box);
    PL.BLOCKS.forEach(function (blk) {
      var t = h("div", { cls: "ptile", draggable: "true", title: blk.hint + " – ziehen oder anklicken" }, [
        h("strong", { text: blk.label }), h("span", { cls: "hint", text: blk.hint })]);
      t.addEventListener("click", function () { addPayload({ kind: "block", block: blk.kind }, null); });
      t.addEventListener("dragstart", function (e) { startPayload(e, { kind: "block", block: blk.kind }); });
      t.addEventListener("dragend", endPayload);
      box.appendChild(t);
    });
  }
  function startPayload(e, p) {
    if (!layout) { e.preventDefault(); return; }
    dragPayload = p;
    try { e.dataTransfer.setData("text/plain", "baustein"); e.dataTransfer.effectAllowed = "copy"; } catch (x) { /* egal */ }
  }
  function endPayload() { dragPayload = null; dropMark = null; renderOverlay(); }

  // ---------------------------------------------------------------- Palette: Spielaktionen
  function onMessage(m) {
    if (m.t === "actions") {
      if (m.game !== actionsGame) return true;
      actionsData = m; actionsError = ""; renderActions(); return true;
    }
    if (m.t === "error" && m.req === "actions") { actionsError = m.msg || "Fehler"; renderActions(); return true; }
    return false;
  }
  function requestActions(game) {
    actionsGame = game; actionsData = null; actionsError = "";
    renderActions();
    if (game && api) api.send({ t: "actions", game: game });
  }
  function renderActions() {
    var box = $("actList"), inf = $("actInfo");
    clear(box);
    if (!actionsGame) { inf.textContent = ""; return; }
    if (actionsError) { inf.textContent = "Aktionen nicht ladbar: " + actionsError; return; }
    if (!actionsData) { inf.textContent = "Aktionen werden geladen …"; return; }
    var tpls = actionsData.templates || [];
    var total = 0;
    tpls.forEach(function (t) { t.pages.forEach(function (p) { total += p.actions.length; }); });
    if (!tpls.length) {
      inf.textContent = "Für dieses Spiel gibt es noch keine Vorlage – Bausteine nutzen oder „Automatisch …“ (mit KI).";
      return;
    }
    var shown = PL.filterActions(tpls, actionsQuery);
    var present = layout ? PL.presentSet(layout) : PL.presentSet({ pages: [] });
    var n = 0;
    shown.forEach(function (t) { t.pages.forEach(function (p) { n += p.actions.length; }); });
    inf.textContent = (actionsQuery ? n + " von " + total : total) + " Aktionen · " + (actionsData.bindings
      ? "Tasten aus deiner Belegung, sonst aus der Vorlage" : "Tasten aus der Vorlage (keine Belegungsquelle)");
    var searching = !!actionsQuery.trim();
    shown.forEach(function (t, ti) {
      if (shown.length > 1) box.appendChild(h("div", { cls: "atpl", text: t.title }));
      t.pages.forEach(function (p, pi) {
        var key = t.id + "/" + p.id;
        var det = h("details", { cls: "apage" });
        det.open = searching || (key in openKeys ? openKeys[key] : (ti === 0 && pi === 0));
        det.addEventListener("toggle", function () { if (!searching) openKeys[key] = det.open; });
        det.appendChild(h("summary", {}, [h("span", { text: p.title }), h("span", { cls: "meta", text: String(p.actions.length) })]));
        var last = null;
        p.actions.forEach(function (a) {
          if ((a.group || "") !== last) { last = a.group || ""; if (last) det.appendChild(h("div", { cls: "agroup", text: last })); }
          var there = PL.isPresent(a, present);
          var row = h("div", { cls: "arow" + (there ? " there" : "") + (a.source === "fehlt" ? " missing" : ""), draggable: "true",
            title: (a.action ? a.action + "\n" : "") + (a.note || (a.source ? "Quelle: " + a.source : "")) + (there ? "\nSchon im Panel" : "") }, [
            h("span", { cls: "name", text: a.button.label }),
            h("span", { cls: "meta key", text: a.key || (a.source === "Makro" ? "Makro" : "–") }),
            there ? h("span", { cls: "badge", text: "im Panel" }) : null]);
          row.addEventListener("click", function () { addPayload({ kind: "action", entry: a }, null); });
          row.addEventListener("dragstart", function (e) { startPayload(e, { kind: "action", entry: a }); });
          row.addEventListener("dragend", endPayload);
          det.appendChild(row);
        });
        box.appendChild(det);
      });
    });
    if (!shown.length) box.appendChild(h("p", { cls: "hint", text: "Keine Aktion gefunden." }));
  }

  // ---------------------------------------------------------------- Einfügen
  // drop: null (Klick: erste freie Stelle / anhängen) oder { at: {x,y}, index, group, zone }
  function addPayload(pl, drop) {
    var p = page();
    if (!layout || !p) return;
    var blk = pl.kind === "block" ? PL.BLOCKS.filter(function (x) { return x.kind === pl.block; })[0] : null;
    if (blk && blk.free && !isFree(p)) { api.status(blk.label + " gibt es nur auf freien Seiten (Raster).", "err"); return; }
    var b = pl.kind === "block" ? PL.newBlock(pl.block, layout, p) : PL.buttonFromAction(pl.entry, layout, p);
    var opts = { kind: pl.kind === "block" ? pl.block : PL.kindOf(b) };
    if (drop) { opts.at = drop.at; opts.index = drop.index; opts.zone = drop.zone; if (typeof drop.group === "string") opts.group = drop.group; }
    var res = PL.addButton(p, b, opts);
    setSel([b.id], b.id);
    commit();
    if (res.overlap) api.status("Kein freier Platz im Raster – die neue Taste überlappt (rot).", "err");
    var el = findEl(b.id);
    if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
  }

  // ---------------------------------------------------------------- Vorschau im Stil des Tablets
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
  function div(cls, text) { var e = document.createElement("div"); e.className = cls; if (text != null) e.textContent = text; return e; }
  function span(cls, text) { var e = document.createElement("span"); e.className = cls; if (text != null) e.textContent = text; return e; }

  function makeBtn(b, extra) {
    var mapped = PL.isMapped(b);
    if (b.slider) {
      var s = div("slider btn-slider " + (b.style || "") + " " + (extra || "") + (b.wide ? " wide" : "") + (mapped ? "" : " nomap") + (dups.byId[b.id] ? " dup" : ""));
      s.setAttribute("data-id", b.id);
      if (dups.byId[b.id]) s.title = "Gleiche Taste wie: " + dupText(b, page());
      s.appendChild(span("fill")); s.appendChild(span("lbl", b.label)); s.appendChild(span("val", "0 / " + b.slider.steps));
      return s;
    }
    var guarded = b.style === "danger" && (b.mode === "hold-confirm" || b.mode === "double");
    var e = div("key btn " + (b.style || "") + " " + (extra || "") + (b.wide ? " wide" : "") + (mapped ? "" : " nomap") +
      (dups.byId[b.id] ? " dup" : "") + (b.look ? " look-" + b.look : "") + (guarded ? " guarded" : ""));
    e.setAttribute("data-id", b.id);
    if (dups.byId[b.id]) e.title = "Gleiche Taste wie: " + dupText(b, page());
    if (b.look === "arrow") e.appendChild(span("arrow", ARROWS[b.dir] || "▲"));
    e.appendChild(span("lbl", b.label));
    if (b.states) {
      var row = span("sub states");
      b.states.forEach(function (st, i) { row.appendChild(span("st" + (i === 0 ? " on" : ""), st.label)); });
      e.appendChild(row);
    } else if (b.key) e.appendChild(span("sub", keyText(b.key)));
    else if (b.page) e.appendChild(span("sub", "→ Seite"));
    else if (b.macro) e.appendChild(span("sub", PL.artOf(b) === "media" ? "Medien" : "Makro"));
    else if (b.open) e.appendChild(span("sub", "öffnen"));
    if (b.mode === "hold-confirm") { e.appendChild(span("hint", "HALTEN")); e.appendChild(span("bar")); }
    if (b.mode === "double") e.appendChild(span("hint", "2× TIPPEN"));
    if (b.mode === "toggle") e.appendChild(span("lamp"));
    if (PL.hasPlaceholder(b)) e.title = "Platzhalter – echten Wert eintragen";
    return e;
  }

  function renderGrid(p) {
    var root = div("grid-page"), groups = [], map = Object.create(null);
    p.buttons.forEach(function (b) {
      var g = b.group || "";
      if (!map[g]) { map[g] = []; groups.push(g); }
      map[g].push(b);
    });
    groups.forEach(function (g) {
      var sec = h("section", { cls: "group" });
      sec.setAttribute("data-group", g);
      if (g) sec.appendChild(h("h2", { text: g }));
      var grid = div("grid");
      map[g].forEach(function (b) {
        var e = makeBtn(b);
        if (b.slider) e.classList.add("wide");
        grid.appendChild(e);
      });
      sec.appendChild(grid);
      root.appendChild(sec);
    });
    if (!p.buttons.length) root.appendChild(div("tv-empty", "Leere Seite – Bausteine und Spielaktionen von links hierher ziehen oder anklicken."));
    return root;
  }

  var ARROWS = { up: "▲", down: "▼", left: "◀", right: "▶", up2: "⏶⏶", down2: "⏷⏷" };
  var SHIP_PATH = "M300,85 L318,140 L322,175 L395,215 L398,240 L325,232 L320,262 L345,290 L345,302 " +
    "L300,296 L255,302 L255,290 L280,262 L275,232 L202,240 L205,215 L278,175 L282,140 Z";

  // Schiffsansicht eines freien Seite (kind shield): Zonen-Tasten der Seite als Dreiecke, Reset auf dem Schiff
  function makeShieldEl(sh, p) {
    var e = div("fshield"), byZone = {};
    e.setAttribute("data-id", sh.id);
    p.buttons.forEach(function (b) { if (b.zone && !PL.isPlaced(b)) byZone[b.zone] = b; });
    var s = svg("svg", { viewBox: "0 0 600 400", preserveAspectRatio: "xMidYMid meet" });
    var zones = { front: ["0,0 600,0 300,200", 300, 34], back: ["0,400 600,400 300,200", 300, 368],
      left: ["0,0 0,400 300,200", 64, 200], right: ["600,0 600,400 300,200", 536, 200] };
    Object.keys(zones).forEach(function (z) {
      var b = byZone[z], poly = svg("polygon", { points: zones[z][0], "class": "zone" + (b ? "" : " empty") });
      if (b) poly.setAttribute("data-id", b.id);
      s.appendChild(poly);
      if (b) { var t = svg("text", { x: zones[z][1], y: zones[z][2], "class": "zlabel" }); t.textContent = b.label; s.appendChild(t); }
    });
    var ship = svg("path", { "class": "ship" + (byZone.reset ? " hit" : ""), d: SHIP_PATH,
      transform: "translate(300 200) scale(1.3) translate(-300 -193)" });
    if (byZone.reset) ship.setAttribute("data-id", byZone.reset.id);
    s.appendChild(ship);
    if (byZone.reset) { var rl = svg("text", { x: 300, y: 224, "class": "zlabel slabel" }); rl.textContent = byZone.reset.label; s.appendChild(rl); }
    e.appendChild(s);
    return e;
  }

  var freeEl = null;
  function renderFree(p) {
    var c = p.cols || 12, r = p.rows || 8;
    var root = div("free");
    root.style.gridTemplateColumns = "repeat(" + c + ", minmax(0, 1fr))";
    root.style.gridTemplateRows = "repeat(" + r + ", minmax(0, 1fr))";
    var cells = div("cells");
    for (var i = 0; i < c * r; i++) cells.appendChild(div("cell"));
    root.appendChild(cells);
    var over = PL.overlapSet(p);
    function place(e, b) {
      e.style.gridColumn = (b.x + 1) + " / span " + b.w;
      e.style.gridRow = (b.y + 1) + " / span " + b.h;
      root.appendChild(e);
    }
    // Reihenfolge wie am Tablet: Rahmen hinten, dann Schiff und Text, dann Tasten
    p.buttons.forEach(function (b) {
      if (b.kind !== "frame") return;
      var f = div("frame");
      f.setAttribute("data-id", b.id);
      if (b.label) f.appendChild(span("ftitle", b.label));
      place(f, b);
    });
    p.buttons.forEach(function (b) {
      if (b.kind === "shield") place(makeShieldEl(b, p), b);
      else if (b.kind === "text") {
        var t = div("ftext s-" + (b.size || "m") + " a-" + (b.align || "left") + (over[b.id] ? " overlap" : ""));
        t.setAttribute("data-id", b.id);
        t.appendChild(span(null, b.label));
        place(t, b);
      }
    });
    p.buttons.forEach(function (b) {
      if (!b.kind && PL.isPlaced(b)) place(makeBtn(b, over[b.id] ? "overlap" : ""), b);
    });
    freeEl = root;
    return root;
  }

  function renderShield(p) {
    var root = div("shield"), byZone = {};
    p.buttons.forEach(function (b) { byZone[b.zone] = b; });
    var s = svg("svg", { viewBox: "0 0 600 400", preserveAspectRatio: "xMidYMid meet" });
    var zones = {
      front: { pts: "0,0 600,0 300,200", lx: 300, ly: 45 }, back: { pts: "0,400 600,400 300,200", lx: 300, ly: 360 },
      left: { pts: "0,0 0,400 300,200", lx: 70, ly: 200 }, right: { pts: "600,0 600,400 300,200", lx: 530, ly: 200 }
    };
    Object.keys(zones).forEach(function (z) {
      var b = byZone[z];
      var poly = svg("polygon", { points: zones[z].pts, "class": "zone" + (b ? "" : " empty"), "data-zone": z });
      if (b) poly.setAttribute("data-id", b.id);
      s.appendChild(poly);
      if (b) { var t = svg("text", { x: zones[z].lx, y: zones[z].ly, "class": "zlabel" }); t.textContent = b.label; s.appendChild(t); }
    });
    s.appendChild(svg("path", { "class": "ship", d: "M300,85 L318,140 L322,175 L395,215 L398,240 L325,232 L320,262 L345,290 L345,302 " +
      "L300,296 L255,302 L255,290 L280,262 L275,232 L202,240 L205,215 L278,175 L282,140 Z" }));
    root.appendChild(s);
    var side = div("side");
    ["top", "reset", "bottom"].forEach(function (z) {
      var b = byZone[z], e;
      if (b) e = makeBtn(b, z === "reset" ? "reset" : "");
      else { e = div("key btn emptyzone", "(" + z + ")"); }
      e.setAttribute("data-zone", z);
      side.appendChild(e);
    });
    root.appendChild(side);
    return root;
  }

  function renderTabs() {
    var nav = $("tvTabs"); clear(nav);
    if (!layout) return;
    layout.pages.forEach(function (p, i) {
      var t = h("button", { text: p.title, cls: i === pageIdx ? "on" : "", title: "Seite " + p.id });
      t.addEventListener("click", function () { if (i !== pageIdx) { pageIdx = i; setSel([]); renderAll(); } });
      nav.appendChild(t);
    });
    nav.appendChild(h("button", { cls: "addtab", text: "+", title: "Neue Seite", onclick: addPage }));
  }
  function renderHead() {
    var row = $("tvHead"); clear(row);
    var cv = div("cv", (info.game || "?").replace(/[^A-Za-z0-9 ]/g, " ").split(/\s+/).filter(Boolean).slice(0, 2)
      .map(function (w) { return w.charAt(0); }).join("").toUpperCase() || "?");
    row.appendChild(h("div", { cls: "tv-game" }, [cv, span("gn", info.game || "")]));
    var chips = h("div", { cls: "tv-panels" });
    (info.panels || []).forEach(function (pn) { chips.appendChild(span("chip" + (pn.id === info.panel ? " on" : ""), pn.title)); });
    row.appendChild(chips);
  }

  function renderPage() {
    calcDups(); updateDupHint();
    var p = page(), box = $("tvPage"); clear(box); freeEl = null;
    var main = $("tvMain");
    main.classList.toggle("fill", !!p && p.type !== "grid" && !!p.type);
    if (!p) return;
    box.appendChild(p.type === "shield" ? renderShield(p) : p.type === "free" ? renderFree(p) : renderGrid(p));
    markSel();
    var n = p.buttons.length;
    $("pageHint").textContent = "– " + p.title;
    $("previewNote").textContent = p.type === "free"
      ? (p.cols || 12) + " × " + (p.rows || 8) + " Zellen · Ziehen: verschieben · Griffe: Größe · Rahmen/Umschalt-Klick: mehrere · Doppelklick auf freie Zelle: neue Taste"
      : p.type === "shield"
        ? "Schild-Seite: Zone in den Eigenschaften wählen, oder Baustein/Aktion auf eine Zone ziehen."
        : "Automatische Anordnung nach Überschriften (" + n + " Tasten). Eine Taste ziehen macht die Seite frei (Raster) – Positionen bleiben.";
  }
  function findEl(id) {
    var list = $("tvPage").querySelectorAll("[data-id]");
    for (var i = 0; i < list.length; i++) if (list[i].getAttribute("data-id") === id) return list[i];
    return null;
  }
  function markSel() {
    var list = $("tvPage").querySelectorAll("[data-id]");
    for (var i = 0; i < list.length; i++) list[i].classList.toggle("sel", sel.indexOf(list[i].getAttribute("data-id")) >= 0);
  }

  // Größe der Vorschau: passt in die Mitte, nie größer als 1,25
  function layoutStage() {
    var box = $("tvBox"), wrap = $("tvWrap"), tv = $("tv");
    var cs = getComputedStyle(box);
    var aw = box.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    var ah = box.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    if (!(aw > 0 && ah > 0)) return;
    scale = Math.max(0.2, Math.min(aw / VW, ah / VH, 1.25));
    wrap.style.width = Math.floor(VW * scale) + "px";
    wrap.style.height = Math.floor(VH * scale) + "px";
    tv.style.transform = "scale(" + scale + ")";
  }
  if (typeof ResizeObserver === "function") new ResizeObserver(function () { if (active) { layoutStage(); renderOverlay(); } }).observe($("tvBox"));
  window.addEventListener("resize", function () { if (active) { layoutStage(); renderOverlay(); } });

  // Auswahlrahmen, Größen-Griffe, Rahmenauswahl und Ablagemarke über der Vorschau (nur Editor, nicht am Tablet)
  var HANDLES = { nw: [0, 0, "nwse-resize"], n: [.5, 0, "ns-resize"], ne: [1, 0, "nesw-resize"], e: [1, .5, "ew-resize"],
    se: [1, 1, "nwse-resize"], s: [.5, 1, "ns-resize"], sw: [0, 1, "nesw-resize"], w: [0, .5, "ew-resize"] };
  function relRect(r, base) { return { x: (r.left - base.left) / scale, y: (r.top - base.top) / scale, w: r.width / scale, h: r.height / scale }; }
  function box(cls, r) {
    var e = div(cls);
    e.style.left = r.x + "px"; e.style.top = r.y + "px"; e.style.width = r.w + "px"; e.style.height = r.h + "px";
    return e;
  }
  function renderOverlay() {
    var ov = $("tvOv"); clear(ov);
    var p = page();
    if (!p || !layout) return;
    var base = $("tv").getBoundingClientRect();
    sel.forEach(function (id) {
      var el = findEl(id);
      if (el) ov.appendChild(box("ov-frame", relRect(el.getBoundingClientRect(), base)));
    });
    var only = sel.length === 1 ? btnById(sel[0]) : null;
    if (only && isFree(p) && PL.isPlaced(only)) {
      var el1 = findEl(sel[0]);
      if (el1) {
        var r = relRect(el1.getBoundingClientRect(), base), hs = 11 / scale;
        for (var k in HANDLES) {
          var hd = HANDLES[k], g = div("ov-handle");
          g.setAttribute("data-h", k);
          g.style.cssText = "left:" + (r.x + r.w * hd[0] - hs / 2) + "px;top:" + (r.y + r.h * hd[1] - hs / 2) + "px;width:" + hs +
            "px;height:" + hs + "px;cursor:" + hd[2];
          ov.appendChild(g);
        }
      }
    }
    if (marquee) {
      var q = marquee;
      ov.appendChild(box("ov-marquee", { x: (Math.min(q.x0, q.x1) - base.left) / scale, y: (Math.min(q.y0, q.y1) - base.top) / scale,
        w: Math.abs(q.x1 - q.x0) / scale, h: Math.abs(q.y1 - q.y0) / scale }));
    }
    if (dropMark && freeEl) {
      var step = PL.cellStep(freeEl.getBoundingClientRect(), GAP * scale, p.cols || 12, p.rows || 8), fr = freeEl.getBoundingClientRect();
      var m = { x: (fr.left - base.left + dropMark.x * step.x) / scale, y: (fr.top - base.top + dropMark.y * step.y) / scale,
        w: (dropMark.w * step.x - GAP * scale) / scale, h: (dropMark.h * step.y - GAP * scale) / scale };
      ov.appendChild(box("ov-drop" + (dropMark.bad ? " bad" : ""), m));
    }
  }

  // ---------------------------------------------------------------- Zeiger auf der Vorschau
  function cellInfo(ev) {
    var p = page(), r = freeEl.getBoundingClientRect();
    return PL.cellAt(r, GAP * scale, p.cols || 12, p.rows || 8, ev.clientX, ev.clientY);
  }
  function setPos(el, b) {
    el.style.gridColumn = (b.x + 1) + " / span " + b.w;
    el.style.gridRow = (b.y + 1) + " / span " + b.h;
  }
  // während des Ziehens: nur Stile der vorhandenen Elemente nachführen
  function syncFree() {
    var p = page(), over = PL.overlapSet(p);
    p.buttons.forEach(function (b) {
      var el = findEl(b.id);
      if (el && PL.isPlaced(b)) { setPos(el, b); el.classList.toggle("overlap", !!over[b.id]); }
    });
    renderOverlay();
  }

  function onDown(e) {
    var p = page();
    if (!layout || !p || e.button !== 0) return;
    if (e.target.closest && e.target.closest(".tv-head, .tabs")) return;
    var ae = document.activeElement;
    if (ae && ae !== document.body && ae.blur && /^(INPUT|SELECT|TEXTAREA)$/.test(ae.tagName)) ae.blur();
    var hd = e.target.getAttribute && e.target.getAttribute("data-h");
    var el = e.target.closest ? e.target.closest("[data-id]") : null;
    var extra = e.shiftKey || e.ctrlKey || e.metaKey;
    drag = null;
    e.preventDefault();
    if (hd && sel.length === 1 && isFree(p)) {
      var b0 = btnById(sel[0]);
      drag = { mode: "resize", handle: hd, id: sel[0], cx: e.clientX, cy: e.clientY, start: ci(e), item: { id: b0.id, x: b0.x, y: b0.y, w: b0.w, h: b0.h }, moved: false };
    } else if (el) {
      var id = el.getAttribute("data-id");
      if (extra) {
        var i = sel.indexOf(id);
        if (i >= 0) sel.splice(i, 1); else sel.push(id);
        primary = sel.indexOf(id) >= 0 ? id : (sel[0] || null);
        refreshSel(); return;
      }
      if (sel.indexOf(id) < 0) setSel([id], id); else primary = id;
      refreshSel();
      var b1 = btnById(id);
      var movable = p.type !== "shield" && !(isFree(p) && b1 && !PL.isPlaced(b1));   // Zonen der Schiffsansicht: nur wählen
      var ids = sel.filter(function (i) { var x = btnById(i); return !isFree(p) || (x && PL.isPlaced(x)); });
      if (isFree(p)) sel.forEach(function (i) {   // Rahmen verschieben: was ganz darin liegt, wandert mit
        var x = btnById(i);
        if (x && x.kind === "frame") PL.insideFrame(p, x).forEach(function (j) { if (ids.indexOf(j) < 0) ids.push(j); });
      });
      if (movable) drag = { mode: "move", cx: e.clientX, cy: e.clientY, ids: ids, start: isFree(p) ? ci(e) : null, items: null, moved: false };
    } else if (isFree(p) && freeEl && freeEl.contains(e.target)) {
      drag = { mode: "marquee", cx: e.clientX, cy: e.clientY, extra: extra, base: extra ? sel.slice() : [], moved: false };
    } else {
      if (sel.length && !extra) { setSel([]); refreshSel(); }
      return;
    }
    try { $("tv").setPointerCapture(e.pointerId); } catch (x) { /* egal */ }
  }
  function ci(ev) { return isFree(page()) && freeEl ? cellInfo(ev) : null; }

  // Automatische Seite wird beim Ziehen zur freien Seite (Positionen aus der Anordnung), ein Verlaufsschritt
  function gridToFreeForDrag() {
    var p = page();
    if (!PL.setPageType(p, "free")) { alert("Zu viele Tasten für ein Raster (höchstens 24 × 16) – Seite teilen oder Tasten entfernen."); return false; }
    renderPage(); renderProps(); renderToolbar();   // kein eigener Verlaufsschritt: onUp committet (touch() kommt aus onMove)
    toast("Diese Seite ist jetzt frei (Raster) – die Positionen bleiben wie zuvor.", true);
    return true;
  }

  function onMove(e) {
    var p = page();
    if (!layout || !p) return;
    if (!drag) {
      if (isFree(p) && !dragPayload && e.target.getAttribute) {
        var over = e.target.getAttribute("data-h");
        $("tv").style.cursor = over ? "" : (e.target.closest && e.target.closest("[data-id]") ? "move" : "");
      }
      return;
    }
    if (!drag.moved) {
      if (Math.hypot(e.clientX - drag.cx, e.clientY - drag.cy) < DRAG_PX) return;
      drag.moved = true;
      if (drag.mode === "move" && !isFree(p)) {          // automatische Seite: wird frei, Ziehen geht gleich weiter
        if (!gridToFreeForDrag()) { drag = null; return; }
        p = page();
        drag.start = cellInfo({ clientX: drag.cx, clientY: drag.cy });
      }
      if (drag.mode === "move") drag.items = PL.toItems(p);
    }
    if (drag.mode === "marquee") {
      var c0 = cellInfo({ clientX: drag.cx, clientY: drag.cy }), c1 = cellInfo(e);
      marquee = { x0: drag.cx, y0: drag.cy, x1: e.clientX, y1: e.clientY };
      var hits = PL.selectInRect(p, { x: c0.fx, y: c0.fy, w: c1.fx - c0.fx, h: c1.fy - c0.fy });
      var ids = drag.extra ? drag.base.concat(hits.filter(function (i) { return drag.base.indexOf(i) < 0; })) : hits;
      sel = ids; primary = sel[0] || null;
      markSel(); renderOverlay();
      return;
    }
    var cur = cellInfo(e), dx = cur.x - drag.start.x, dy = cur.y - drag.start.y;
    if (drag.mode === "move") {
      PL.applyItems(p, drag.items);
      PL.moveBy(p, drag.ids, dx, dy);
    } else {
      PL.applyItems(p, [drag.item]);
      PL.resizeCells(p, drag.id, drag.handle, dx, dy);
    }
    syncFree(); syncPosFields();
    touch();
  }
  function onUp() {
    if (!drag) return;
    var d = drag; drag = null; marquee = null;
    if (d.mode === "marquee") {
      if (!d.moved && !d.extra) setSel([]);   // Klick ins Leere hebt die Auswahl auf
      refreshSel(); return;
    }
    if (d.moved) commit(); else renderOverlay();
  }

  function refreshSel() { markSel(); renderOverlay(); renderList(); renderProps(); renderToolbar(); }

  // Doppelklick auf eine freie Zelle: neue Taste dort
  function onDbl(e) {
    var p = page();
    if (!isFree(p) || !freeEl || (e.target.closest && e.target.closest("[data-id]")) || !freeEl.contains(e.target)) return;
    var c = cellInfo(e);
    addPayload({ kind: "block", block: "key" }, { at: { x: c.x, y: c.y } });
  }

  // ---------------------------------------------------------------- Ablegen aus der Palette
  function dropTarget(e) {
    var p = page(), t = e.target;
    if (isFree(p)) {
      if (!freeEl) return null;
      var c = cellInfo(e);
      return { at: { x: c.x, y: c.y } };
    }
    if (p.type === "shield") {
      var z = t.closest && t.closest("[data-zone]");
      return z ? { zone: z.getAttribute("data-zone") } : {};
    }
    var el = t.closest && t.closest("[data-id]"), sec = t.closest && t.closest("[data-group]");
    var d = {};
    if (el) { var b = btnById(el.getAttribute("data-id")); d.index = p.buttons.indexOf(b); }
    if (sec) d.group = sec.getAttribute("data-group");
    return d;
  }
  function onDragOver(e) {
    if (!dragPayload || !layout) return;
    e.preventDefault();
    var p = page();
    if (isFree(p) && freeEl) {
      var c = cellInfo(e);
      var kind = dragPayload.kind === "block" ? dragPayload.block : PL.kindOf(dragPayload.entry.button);
      var sz = PL.blockSize(kind, p), x = Math.min(c.x, (p.cols || 12) - sz.w), y = Math.min(c.y, (p.rows || 8) - sz.h);
      var free = PL.nearestFree(p, sz.w, sz.h, x, y);
      dropMark = free ? { x: free.x, y: free.y, w: sz.w, h: sz.h } : { x: x, y: y, w: sz.w, h: sz.h, bad: true };
      renderOverlay();
    }
  }
  function onDrop(e) {
    if (!dragPayload || !layout) return;
    e.preventDefault();
    var pl = dragPayload, drop = dropTarget(e);
    dragPayload = null; dropMark = null;
    addPayload(pl, drop);
  }
  function onDragLeave(e) {
    if (dropMark && !$("tv").contains(e.relatedTarget)) { dropMark = null; renderOverlay(); }
  }

  // ---------------------------------------------------------------- Hinweis mit „Rückgängig“
  function toast(text, withUndo) {
    var t = $("toast"); clear(t);
    t.appendChild(h("span", { text: text }));
    if (withUndo) t.appendChild(h("button", { cls: "ghost small", text: "Rückgängig", onclick: function () { undo(false); t.hidden = true; } }));
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.hidden = true; }, 9000);
  }

  // ---------------------------------------------------------------- Seiten
  function addPage() {
    if (!layout) return;
    layout.pages.push({ id: PL.uniquePageId(layout, "seite"), title: "Neue Seite", type: "grid", buttons: [] });
    pageIdx = layout.pages.length - 1; setSel([]);
    commit();
  }
  function renderPageProps() {
    var p = page(), box = $("pageProps"); clear(box);
    if (!p) return;
    box.appendChild(field("Titel (Reiter)", input(p.title, function (v) { p.title = v; renderTabs(); $("pageHint").textContent = "– " + v; touch(); })));
    box.appendChild(field("Typ", select(p.type || "grid", [["grid", "Automatisch (nach Gruppen)"], ["free", "Frei (Raster)"], ["shield", "Schild (Zonen)"]],
      function (v) {
        if (!PL.setPageType(p, v)) { alert("Zu viele Tasten für ein Raster (höchstens 12 × 12) – Seite teilen oder Tasten entfernen."); renderPageProps(); return; }
        commit();
      }),
      p.type === "shield" ? "Schild: Tasten brauchen eine Zone." :
      p.type === "free" ? "Tasten ziehen, Griffe ändern die Größe, Doppelklick auf eine freie Zelle = neue Taste." :
      "Tasten fließen nach Überschriften. Ziehen in der Vorschau macht die Seite frei."));
    if (isFree(p)) {
      box.appendChild(h("div", { cls: "row" }, [
        field("Spalten", input(p.cols || 12, function (v) { var n = parseInt(v, 10); if (PL.setGrid(p, n, p.rows || 8)) { renderPage(); renderOverlay(); touch(); } }, { type: "number", min: 2, max: 16 })),
        field("Zeilen", input(p.rows || 8, function (v) { var n = parseInt(v, 10); if (PL.setGrid(p, p.cols || 12, n)) { renderPage(); renderOverlay(); touch(); } }, { type: "number", min: 2, max: 12 }))]));
      box.appendChild(h("button", { cls: "ghost", text: "Neu anordnen (nach Gruppen)", onclick: function () {
        if (!confirm("Alle Tasten dieser Seite neu anordnen?")) return;
        if (!PL.arrange(p)) return alert("Zu viele Tasten für das Raster.");
        commit(); } }));
    }
    box.appendChild(h("div", { cls: "row" }, [
      h("button", { cls: "ghost", text: "← Reiter", title: "Seite nach links", onclick: function () { movePage(-1); } }),
      h("button", { cls: "ghost", text: "Reiter →", title: "Seite nach rechts", onclick: function () { movePage(1); } }),
      h("button", { cls: "del", text: "Seite löschen", onclick: delPage })]));
  }
  function movePage(d) {
    var to = pageIdx + d;
    if (!layout || to < 0 || to >= layout.pages.length) return;
    layout.pages.splice(to, 0, layout.pages.splice(pageIdx, 1)[0]);
    pageIdx = to; commit();
  }
  function delPage() {
    var p = page();
    if (layout.pages.length < 2) return alert("Mindestens eine Seite muss bleiben.");
    if (!confirm("Seite „" + p.title + "“ mit " + p.buttons.length + " Tasten löschen?")) return;
    var gone = p.id;
    layout.pages.splice(pageIdx, 1); pageIdx = Math.max(0, pageIdx - 1); setSel([]);
    layout.pages.forEach(function (x) { x.buttons.forEach(function (b) { if (b.page === gone) delete b.page; }); });
    commit();
  }

  // ---------------------------------------------------------------- Tastenliste
  function renderList() {
    var ul = $("buttons"); clear(ul);
    var p = page();
    if (!p) return;
    calcDups();
    p.buttons.forEach(function (b, i) {
      var li = h("li", { cls: (sel.indexOf(b.id) >= 0 ? "sel " : "") + (b.style || "") + (PL.isMapped(b) ? "" : " nomap") + (dups.byId[b.id] ? " dup" : ""),
        draggable: "true", title: dups.byId[b.id] ? "Gleiche Taste wie: " + dupText(b, p) : "" }, [
        h("span", { cls: "name", text: b.label || "(ohne Text)" }), h("span", { cls: "meta", text: PL.metaText(b) })]);
      li.addEventListener("click", function (e) {
        if (e.shiftKey || e.ctrlKey || e.metaKey) {
          var k = sel.indexOf(b.id);
          if (k >= 0) sel.splice(k, 1); else sel.push(b.id);
          primary = sel.indexOf(b.id) >= 0 ? b.id : (sel[0] || null);
        } else setSel([b.id], b.id);
        refreshSel();
      });
      li.addEventListener("dragstart", function (e) { listDrag = i; try { e.dataTransfer.setData("text/plain", "taste"); } catch (x) { /* egal */ } });
      li.addEventListener("dragover", function (e) { if (listDrag >= 0) { e.preventDefault(); li.classList.add("dragover"); } });
      li.addEventListener("dragleave", function () { li.classList.remove("dragover"); });
      li.addEventListener("drop", function (e) {
        e.preventDefault();
        if (listDrag < 0 || listDrag === i) return;
        p.buttons.splice(i, 0, p.buttons.splice(listDrag, 1)[0]); listDrag = -1;
        commit();
      });
      li.addEventListener("dragend", function () { listDrag = -1; });
      ul.appendChild(li);
    });
    if (!p.buttons.length) ul.appendChild(h("li", { cls: "dim", text: "Noch keine Tasten" }));
  }

  // ---------------------------------------------------------------- Werkzeugleiste und Tastatur
  var TOOLS = { pAlL: ["a", "left"], pAlC: ["a", "hcenter"], pAlR: ["a", "right"], pAlT: ["a", "top"], pAlM: ["a", "vcenter"],
    pAlB: ["a", "bottom"], pDistH: ["d", "x"], pDistV: ["d", "y"], pSameW: ["s", "w"], pSameH: ["s", "h"] };
  function renderToolbar() {
    var p = page(), has = !!layout, some = sel.length > 0, free = isFree(p);
    $("pUndo").disabled = !hist || !hist.canUndo();
    $("pRedo").disabled = !hist || !hist.canRedo();
    $("pDup").disabled = !has || !some;
    $("pDel").disabled = !has || !some;
    var st = PL.arrangeState(sel.length);
    Object.keys(TOOLS).forEach(function (id) {
      var k = TOOLS[id][0] === "a" ? "align" : TOOLS[id][0] === "d" ? "distribute" : "sameSize";
      $(id).disabled = !has || !free || !st[k];
    });
  }
  function tool(fn) {
    var p = page();
    if (!isFree(p) || !sel.length) return;
    if (fn(p) !== false) commit();
  }
  function removeSel() {
    var p = page();
    if (!p || !sel.length) return;
    var gone = {}; sel.forEach(function (i) { gone[i] = true; });
    // Schiffsansicht weg: ihre Zonen-Tasten auch (ohne Schiff keine gültige Lage)
    if (p.buttons.some(function (b) { return gone[b.id] && b.kind === "shield"; }))
      p.buttons.forEach(function (b) { if (b.zone && !PL.isPlaced(b)) gone[b.id] = true; });
    p.buttons = p.buttons.filter(function (b) { return !gone[b.id]; });
    setSel([]); commit();
  }
  function duplicateSel() {
    var p = page();
    if (!p || !sel.length) return;
    var ids = PL.duplicate(layout, p, sel);
    setSel(ids, ids[ids.length - 1]); commit();
  }
  function onKey(e) {
    if (!active || !layout || document.querySelector("dialog[open]")) return;
    var tg = e.target && e.target.tagName;
    if (tg === "INPUT" || tg === "TEXTAREA" || tg === "SELECT") return;
    var ctrl = e.ctrlKey || e.metaKey, k = e.key, handled = true, p = page();
    if (ctrl) {
      if (k === "z" || k === "Z") undo(e.shiftKey);
      else if (k === "y" || k === "Y") undo(true);
      else if (k === "d" || k === "D") duplicateSel();
      else if (k === "a" || k === "A") { setSel(p.buttons.map(function (b) { return b.id; })); refreshSel(); }
      else handled = false;
    } else if (k === "Delete") removeSel();
    else if (k === "Escape") { if (sel.length) { setSel([]); refreshSel(); } else handled = false; }
    else if (k.indexOf("Arrow") === 0 && isFree(p) && sel.length) {
      PL.moveBy(p, sel, k === "ArrowLeft" ? -1 : k === "ArrowRight" ? 1 : 0, k === "ArrowUp" ? -1 : k === "ArrowDown" ? 1 : 0);
      commit();
    } else handled = false;
    if (handled) e.preventDefault();
  }

  // ---------------------------------------------------------------- Eigenschaften
  // Tastenaufnahme: höchstens eine aktiv; wird bei jedem Neuaufbau der Eigenschaften beendet
  var capture = null;
  function stopCapture() { if (capture) { capture(); capture = null; } }
  window.addEventListener("blur", stopCapture);

  // Ansicht nach Änderungen an einer Taste (Eingabefelder bleiben unangetastet)
  function refresh() { renderPage(); renderOverlay(); renderList(); renderActions(); updateDupHint(); touch(); }

  // Tastenfeld mit „Aufnehmen“: get/set lesen und schreiben den Wert an der Taste (set("") = entfernen).
  // Die Übersetzung KeyboardEvent.code -> Name (Zusatztasten, AltGr, Esc = Abbruch) liegt in panellib.js.
  // opts.live (Makro-Schritte): geprüft wird der getippte Text; ungültige Eingaben werden nicht übernommen (set nur bei gültig).
  function keyInput(label, get, set, ph, hintText, opts) {
    opts = opts || {};
    var warn = h("span", { cls: "hint", text: "" });
    function chk() {
      var v = opts.live ? inp.value.toUpperCase().replace(/\s+/g, "") : get();
      var bad = opts.live ? !!PL.stepError({ key: v }, keyNames, null)
        : v && v.split("+").some(function (k) { return keyNames.indexOf(PL.normKey(k)) < 0 && keyNames.indexOf(k) < 0; });
      warn.textContent = bad ? (opts.live ? "Ungültig – nicht übernommen (bleibt " + get() + ")." : "Unbekannter Tastenname – Speichern würde abgelehnt.") : "";
      warn.classList.toggle("warn", !!bad);
      inp.classList.toggle("bad", !!bad && !!opts.live);
    }
    var inp = input(get(), function (v) {
      v = v.toUpperCase().replace(/\s+/g, "");
      if (!opts.live || !PL.stepError({ key: v }, keyNames, null)) { set(v); refresh(); }
      chk();
    },
      { list: "keyNames", placeholder: ph || "z. B. LALT+F oder NUMPAD8" });
    var rec = h("button", { cls: "ghost", text: "Aufnehmen", title: "Taste oder Kombination auf der PC-Tastatur drücken (Esc bricht ab)" });
    function onEv(type) {
      return function (e) {
        e.preventDefault(); e.stopPropagation();
        if (type === "down" && e.repeat) return;
        var r = PL.captureEvent(cap, { type: type, code: e.code, altGraph: !!(e.getModifierState && e.getModifierState("AltGraph")) }, keyNames);
        if (!r) return;
        if (r.hint) { warn.textContent = r.hint; warn.classList.add("warn"); return; }
        stopCapture();
        if (r.done) { set(r.done); inp.value = r.done; refresh(); hist.push(snap()); renderToolbar(); }
        chk();
      };
    }
    var cap = null, down = onEv("down"), up = onEv("up");
    rec.onclick = function () {
      if (capture) return stopCapture();
      cap = PL.newCapture(); inp.classList.add("capture"); rec.textContent = "Taste drücken …";
      warn.textContent = "Jetzt die Taste oder Kombination drücken – Esc bricht ab."; warn.classList.remove("warn");
      document.addEventListener("keydown", down, true); document.addEventListener("keyup", up, true);
      capture = function () {
        inp.classList.remove("capture"); rec.textContent = "Aufnehmen";
        document.removeEventListener("keydown", down, true); document.removeEventListener("keyup", up, true);
        chk();
      };
    };
    chk();
    if (opts.compact) return h("div", { cls: "kin" }, [h("div", { cls: "row" }, [inp, rec]), warn]);
    var f = field(label, h("div", { cls: "row" }, [inp, rec]), hintText);
    f.appendChild(warn);
    return f;
  }
  function keyField(b, label) {
    return keyInput(label || "Taste / Kombination", function () { return b.key || ""; },
      function (v) { if (v) b.key = v; else delete b.key; }, null,
      "Wird als Tastendruck gesendet. Aufnehmen: Kombination auf der PC-Tastatur drücken (Strg/Alt/Umschalt links und rechts werden unterschieden).");
  }

  function macroToText(m) { return (m || []).map(function (s) { var k = Object.keys(s)[0]; return k + " " + s[k]; }).join("\n"); }
  function textToMacro(t) {
    var out = [], errs = [];
    t.split("\n").forEach(function (raw, i) {
      var line = raw.replace(/^\s+/, "").replace(/\r$/, "");
      if (!line.trim() || line[0] === "#") return;
      if (line.slice(0, 5) !== "text ") line = line.trim();
      var sp = line.indexOf(" "), k = sp < 0 ? line : line.slice(0, sp), v = sp < 0 ? "" : line.slice(sp + 1);
      if (k === "wait") { var n = parseInt(v, 10); if (isNaN(n)) errs.push("Zeile " + (i + 1) + ": wait braucht Millisekunden"); else out.push({ wait: n }); }
      else if (k === "key") out.push({ key: v.toUpperCase().replace(/\s+/g, "") });
      else if (k === "text") out.push({ text: v });
      else if (k === "media") { if (mediaNames.indexOf(v) < 0) errs.push("Zeile " + (i + 1) + ": media " + mediaNames.join("/")); out.push({ media: v }); }
      else errs.push("Zeile " + (i + 1) + ": unbekannt „" + k + "“ (key/text/wait/media)");
    });
    return { macro: out, errs: errs };
  }
  function statesToText(st) { return (st || []).map(function (x) { return x.key ? x.label + " = " + x.key : x.label; }).join("\n"); }
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

  var propsInputs = {};
  function syncPosFields() {
    var b = sel.length === 1 ? btnById(sel[0]) : null;
    if (!b) return;
    ["x", "y", "w", "h"].forEach(function (k) {
      var i = propsInputs[k];
      if (i && document.activeElement !== i) i.value = b[k];
    });
  }

  function renderProps() {
    stopCapture(); dupHintEl = null; calcDups();
    renderPageProps();
    var box = $("buttonProps"); clear(box); propsInputs = {};
    var p = page();
    if (!p) return;
    if (sel.length > 1) { renderMultiProps(box, p); return; }
    var b = sel.length === 1 ? btnById(sel[0]) : null;
    if (!b) { box.appendChild(h("p", { cls: "dim", text: "Taste in der Vorschau wählen (mehrere: Umschalt/Strg-Klick oder Rahmen) oder links einen Baustein einfügen." })); return; }
    if (b.kind) { renderDecorProps(box, p, b); return; }
    var idBad = h("span", { cls: "hint", text: "" });
    var idIn = input(b.id, function (v) {
      v = v.trim();
      var taken = PL.allIds(layout); delete taken[b.id];
      idIn.classList.toggle("bad", !v || !!taken[v]);
      idBad.textContent = !v ? "ID darf nicht leer sein." : taken[v] ? "ID ist schon vergeben." : "";
      if (!v || taken[v]) return;
      b.id = v; sel = [v]; primary = v; refresh();
    });
    box.appendChild(field("Beschriftung", input(b.label, function (v) { b.label = v; refresh(); })));
    var idLab = field("ID (eindeutig)", idIn, "Für Spiel-Belegungen und Automatik. Nur ändern, wenn nötig.");
    idLab.appendChild(idBad);
    box.appendChild(idLab);
    box.appendChild(field("Spielaktion (sc)", input(b.sc, function (v) { if (v.trim()) b.sc = v.trim(); else delete b.sc; renderActions(); touch(); },
      { placeholder: "z. B. v_target_cycle_hostile_fwd" }),
      "Optional. scripts/sc_bindings.py --write trägt dann die Taste aus der Spielbelegung ein."));
    if (p.type === "shield") {
      box.appendChild(field("Zone", select(b.zone, PL.ZONES.map(function (z) { return [z, ZONE_LABELS[z]]; }), function (v) { b.zone = v; refresh(); })));
    } else if (isFree(p) && !PL.isPlaced(b)) {
      box.appendChild(h("p", { cls: "hint", text: "Zone der Schiffsansicht: " + (ZONE_LABELS[b.zone] || b.zone) +
        ". Lage und Größe bestimmt das Schiff-Element." }));
    } else {
      box.appendChild(field("Gruppe (Überschrift)", input(b.group, function (v) { if (v) b.group = v; else delete b.group; refresh(); })));
    }
    box.appendChild(field("Farbe", select(b.style || "", STYLE_OPTIONS, function (v) { if (v) b.style = v; else delete b.style; refresh(); })));
    if (!b.slider && !b.states && !b.segment) {
      box.appendChild(field("Aussehen", select(b.look || "", LOOK_OPTIONS, function (v) {
        if (v) b.look = v; else delete b.look;
        if (v === "arrow" && !b.dir) b.dir = "up";
        if (v !== "arrow") delete b.dir;
        refresh(); renderProps();
      })));
      if (b.look === "arrow") box.appendChild(field("Pfeil", select(b.dir || "up", DIR_OPTIONS, function (v) { b.dir = v; refresh(); })));
    }
    if (b.press_ms) box.appendChild(h("p", { cls: "hint", text: "Das Spiel wertet erst einen langen Druck: der Hub hält die Taste " +
      b.press_ms + " ms (ein Tipp genügt)." }));
    if (isFree(p) && PL.isPlaced(b)) {
      var cols = p.cols || 12, rows = p.rows || 8;
      var num = function (key, max) {
        var inp = input(b[key], function (v) {
          var n = parseInt(v, 10); if (isNaN(n)) return;
          b[key] = n;
          b.w = Math.max(1, Math.min(b.w, cols)); b.h = Math.max(1, Math.min(b.h, rows));
          b.x = Math.max(0, Math.min(b.x, cols - b.w)); b.y = Math.max(0, Math.min(b.y, rows - b.h));
          if (String(b[key]) !== inp.value) inp.value = b[key];
          syncFree(); touch();
        }, { type: "number", min: 0, max: max });
        propsInputs[key] = inp;
        return inp;
      };
      box.appendChild(h("div", { cls: "row" }, [field("X", num("x", cols - 1)), field("Y", num("y", rows - 1)),
        field("Breite", num("w", cols)), field("Höhe", num("h", rows))]));
    }
    if (p.type === "grid" || !p.type) {
      var wide = h("input", { type: "checkbox" }); wide.checked = !!b.wide;
      wide.onchange = function () { if (wide.checked) b.wide = true; else delete b.wide; touch(); };
      box.appendChild(h("label", { cls: "check" }, [wide, document.createTextNode("Ganze Breite")]));
    }
    renderAction(box, p, b);
    if (PL.hasPlaceholder(b)) box.appendChild(h("p", { cls: "hint warn", text: b.open ? "Platzhalter-Adresse – bitte die echte URL oder den Pfad eintragen." :
      "Platzhalter-Taste (" + (b.slider ? "Bild↑/Bild↓" : "Rollen") + ") – bitte die echte Taste eintragen." }));
    var art = PL.artOf(b);
    if ((art === "press" || art === "hold" || art === "toggle") && !b.key)
      box.appendChild(h("p", { cls: "hint warn", text: "Keine Taste eingetragen – diese Taste tut am Tablet nichts." }));
    dupHintEl = h("p", { cls: "hint dup-hint", hidden: "" });
    box.appendChild(dupHintEl); updateDupHint();
    box.appendChild(h("div", { cls: "row" }, [
      h("button", { cls: "ghost", text: "Duplizieren", onclick: duplicateSel }),
      h("button", { cls: "del", text: "Löschen", onclick: removeSel })]));
  }
  var LOOK_OPTIONS = [["", "Normale Kachel"], ["big", "Großer Hauptknopf"], ["arrow", "Pfeil"], ["pill", "Schmale Leiste"]];
  var DIR_OPTIONS = [["up", "▲ oben"], ["down", "▼ unten"], ["left", "◀ links"], ["right", "▶ rechts"], ["up2", "▲▲ maximal"], ["down2", "▼▼ minimal"]];

  // Rahmen, Beschriftung, Schiffsansicht: nur Text/Ausrichtung und Lage
  function renderDecorProps(box, p, b) {
    var names = { frame: "Bereich (Rahmen)", text: "Beschriftung", shield: "Schiffsansicht" };
    box.appendChild(h("p", { cls: "hint", text: names[b.kind] + " – ohne Funktion am PC." +
      (b.kind === "frame" ? " Verschieben nimmt alles mit, was ganz im Rahmen liegt." : "") +
      (b.kind === "shield" ? " Die Zonen (Vorn, Hinten, Links, Rechts, Reset) sind Tasten in der Liste." : "") }));
    if (b.kind !== "shield") box.appendChild(field(b.kind === "frame" ? "Titel" : "Text", input(b.label, function (v) {
      if (b.kind === "frame" && !v) delete b.label; else b.label = v; refresh(); })));
    if (b.kind === "text") {
      box.appendChild(h("div", { cls: "row" }, [
        field("Ausrichtung", select(b.align || "left", [["left", "links"], ["center", "Mitte"], ["right", "rechts"]], function (v) { b.align = v; refresh(); })),
        field("Größe", select(b.size || "m", [["s", "klein"], ["m", "mittel"], ["l", "groß"]], function (v) { b.size = v; refresh(); }))]));
    }
    var cols = p.cols || 12, rows = p.rows || 8;
    var num = function (key, max) {
      var inp = input(b[key], function (v) {
        var n = parseInt(v, 10); if (isNaN(n)) return;
        b[key] = n;
        b.w = Math.max(1, Math.min(b.w, cols)); b.h = Math.max(1, Math.min(b.h, rows));
        b.x = Math.max(0, Math.min(b.x, cols - b.w)); b.y = Math.max(0, Math.min(b.y, rows - b.h));
        if (String(b[key]) !== inp.value) inp.value = b[key];
        syncFree(); touch();
      }, { type: "number", min: 0, max: max });
      propsInputs[key] = inp;
      return inp;
    };
    box.appendChild(h("div", { cls: "row" }, [field("X", num("x", cols - 1)), field("Y", num("y", rows - 1)),
      field("Breite", num("w", cols)), field("Höhe", num("h", rows))]));
    box.appendChild(h("div", { cls: "row" }, [
      h("button", { cls: "ghost", text: "Duplizieren", onclick: duplicateSel }),
      h("button", { cls: "del", text: "Löschen", onclick: removeSel })]));
  }

  var ZONE_LABELS = { front: "Vorn", back: "Hinten", left: "Links", right: "Rechts", top: "Oben (Seite)", bottom: "Unten (Seite)", reset: "Reset (Seite)" };
  var MODE_OPTIONS = [["tap", "Drücken (gedrückt halten = Taste gehalten)"], ["hold-confirm", "Erst nach Halten auslösen (gefährlich)"],
    ["double", "Erst beim zweiten Tipp auslösen (gefährlich)"], ["toggle", "Schalter (merkt An/Aus)"]];
  var STYLE_OPTIONS = [["", "Normal"], ["accent", "Blau"], ["danger", "Orange (Gefahr)"]];

  var MEDIA_LABELS = { playpause: "Wiedergabe / Pause", next: "Nächster Titel", prev: "Voriger Titel", stop: "Stopp",
    mute: "Stumm", voldown: "Leiser", volup: "Lauter" };
  var CONFIRM_ARTS = { press: 1, hold: 1, open: 1, macro: 1, media: 1 };

  // Art der Taste (Taste drücken/halten, Umschalten, Mehrfach-Schalter, Regler, Seite, Programm, Makro, Medien):
  // der Wechsel baut die Felder um (PL.convertArt), danach gibt es nur noch die passenden. Ein Verlaufsschritt.
  function renderAction(box, p, b) {
    var art = PL.artOf(b), kind = art === "press" || art === "hold" || art === "toggle" ? "key" : art === "media" ? "media" : art;
    var def = PL.ARTS.filter(function (x) { return x.id === art; })[0];
    box.appendChild(field("Art", select(art, PL.ARTS.map(function (x) { return [x.id, x.label]; }), function (v) {
      PL.convertArt(b, v, { page: p, pages: layout.pages });
      refresh(); renderProps();
    }), def ? def.hint : ""));
    if (CONFIRM_ARTS[art]) {
      var cur0 = b.mode === "hold-confirm" || b.mode === "double" ? b.mode : "";
      box.appendChild(field("Sicherung", select(cur0, [["", "Keine – Tipp löst aus"], ["hold-confirm", "Erst nach längerem Halten"],
        ["double", "Erst beim zweiten Tipp"]], function (v) { if (v) b.mode = v; else delete b.mode; refresh(); }),
        "Schutz gegen versehentliches Tippen (gefährliche Aktionen, z. B. Selbstzerstörung). Mit Farbe Orange zeigt das " +
        "Tablet Warnstreifen und Schloss."));
    }
    if (kind === "media") {
      var cur = b.macro[0].media, opts = (mediaNames.length ? mediaNames : Object.keys(MEDIA_LABELS));
      if (opts.indexOf(cur) < 0) opts = opts.concat([cur]);
      box.appendChild(field("Funktion", select(cur, opts.map(function (m) { return [m, MEDIA_LABELS[m] || m]; }),
        function (v) { b.macro = [{ media: v }]; refresh(); })));
    } else if (kind === "key") box.appendChild(keyField(b));
    else if (kind === "page") {
      box.appendChild(field("Ziel-Seite", select(b.page, layout.pages.map(function (x) { return [x.id, x.title]; }),
        function (v) { b.page = v; refresh(); }), "Wechselt am Tablet auf diese Seite, sendet nichts an den PC."));
    } else if (kind === "states") {
      var sta = h("textarea"); sta.value = statesToText(b.states);
      var serr = h("div", { cls: "err-box" });
      sta.addEventListener("input", function () {
        var r = textToStates(sta.value);
        serr.textContent = r.errs.join("\n");
        if (!r.errs.length) { b.states = r.states; refresh(); }
      });
      box.appendChild(field("Zustände – eine Zeile pro Zustand", sta,
        "BEZEICHNUNG = TASTE (Taste optional), 2–6 Zeilen, Bezeichnung bis 20 Zeichen. Jeder Tipp schaltet reihum weiter."));
      box.appendChild(serr);
      box.appendChild(keyField(b, "Ersatz-Taste (für Zustände ohne eigene)"));
      box.appendChild(h("span", { cls: "hint", text: "Taste oben ist der Ersatz für Zustände ohne eigene Taste. Mindestens eine Quelle nötig." }));
    } else if (kind === "slider") {
      var sl = b.slider;
      var slKey = function (prop, label, ph) {
        return keyInput(label, function () { return sl[prop] || ""; }, function (v) { if (v) sl[prop] = v; else delete sl[prop]; }, ph);
      };
      box.appendChild(slKey("up", "Taste „mehr“", "z. B. LALT+PGUP"));
      box.appendChild(slKey("down", "Taste „weniger“", "z. B. LALT+PGDN"));
      box.appendChild(field("Stufen (2–20)", input(sl.steps, function (v) {
        var n = parseInt(v, 10); if (n >= 2 && n <= 20) { sl.steps = n; refresh(); }
      }, { type: "number", min: 2, max: 20 }), "Jede überschrittene Stufe beim Ziehen sendet einen Tastendruck."));
    } else if (kind === "open") {
      var inp = h("input", { type: "text" }); inp.value = b.open || "";
      var oerr = h("div", { cls: "err-box" });
      inp.addEventListener("input", function () {
        var v = inp.value.trim();
        var ok = /^https?:\/\/\S+$/i.test(v) || /^[A-Za-z]:\\[^<>"|?*]+$/.test(v);
        oerr.textContent = ok ? "" : "http(s)-URL oder absoluter Pfad wie C:\\Programme\\App\\app.exe";
        if (ok) { b.open = v; refresh(); }
      });
      box.appendChild(field("Öffnen am PC", inp, "URL öffnet im Standardbrowser, ein Pfad startet Programm/Datei/Ordner."));
      box.appendChild(oerr);
    } else {
      macroBuilder(box, b);
    }
  }

  // ---------------------------------------------------------------- Makro-Baukasten (Art „Makro“)
  // Schrittliste (Taste / Text tippen / Warten / Medien) oder Textansicht; Logik und Grenzen in panellib.js
  // (wie bridge/layout.py validate_macro). Ungültige Eingaben werden rot markiert und nicht übernommen.
  var macroView = "list", macroSel = -1, macroSelFor = "", macroMsg = "", macroDrag = -1;
  function mediaList() { return mediaNames.length ? mediaNames : Object.keys(MEDIA_LABELS); }
  // Ergebnis einer Operation übernehmen: ein Verlaufsschritt, bei Ablehnung nur der Hinweis
  function macroApply(b, r) {
    if (r.err) { macroMsg = r.err; renderProps(); return; }
    macroMsg = ""; b.macro = r.macro; macroSel = r.index; commit();
  }
  function macroStepValue(b, i) {
    var st = b.macro[i], kind = PL.stepKind(st), box;
    if (kind === "key") {
      return keyInput("", function () { return st.key || ""; }, function (v) { st.key = v; }, "z. B. LALT+1", null, { compact: true, live: true });
    }
    var err = h("span", { cls: "hint warn", text: "" });
    function mark(inp, step, shown) {
      var e = PL.stepError(step, keyNames, mediaNames);
      err.textContent = e ? e + " – nicht übernommen (bleibt " + shown + ")." : "";
      inp.classList.toggle("bad", !!e);
      return !e;
    }
    if (kind === "text") {
      var ti = input(st.text, function (v) { if (mark(ti, { text: v }, JSON.stringify(st.text))) { st.text = v; refresh(); } }, { placeholder: "Text, der getippt wird" });
      box = h("div", { cls: "kin" }, [ti, err]);
    } else if (kind === "wait") {
      var wi = input(st.wait, function (v) {
        var n = v.trim() === "" ? NaN : Number(v);
        if (mark(wi, { wait: n }, st.wait + " ms")) { st.wait = n; refresh(); }
      }, { type: "number", min: 0, max: PL.MACRO_WAIT_MAX, step: 10, title: "Pause in Millisekunden (0–" + PL.MACRO_WAIT_MAX + ")" });
      box = h("div", { cls: "kin" }, [h("div", { cls: "row" }, [wi, h("span", { cls: "hint", text: "ms" })]), err]);
    } else {
      var opts = mediaList(); if (opts.indexOf(st.media) < 0) opts = opts.concat([st.media]);
      box = select(st.media, opts.map(function (m) { return [m, MEDIA_LABELS[m] || m]; }), function (v) { st.media = v; refresh(); });
    }
    return box;
  }
  function macroRow(b, i) {
    var st = b.macro[i], kind = PL.stepKind(st), m = b.macro;
    var def = PL.STEP_KINDS.filter(function (k) { return k.kind === kind; })[0] || { icon: "?", label: "?" };
    var row = h("div", { cls: "mstep" + (i === macroSel ? " sel" : "") });
    function sel1() {
      if (macroSel === i) return;
      macroSel = i;
      Array.prototype.forEach.call(row.parentNode.children, function (c, j) { c.classList.toggle("sel", j === i); });
    }
    row.addEventListener("focusin", sel1);
    row.addEventListener("mousedown", sel1);
    var handle = h("span", { cls: "mh", text: "⠿", title: "Ziehen zum Umsortieren" });
    handle.addEventListener("mousedown", function () { row.draggable = true; });
    handle.addEventListener("mouseup", function () { row.draggable = false; });   // Klick ohne Ziehen
    row.addEventListener("dragstart", function (e) {
      if (!row.draggable) return;
      macroDrag = i; try { e.dataTransfer.setData("text/plain", "schritt"); } catch (x) { /* egal */ }
    });
    row.addEventListener("dragover", function (e) { if (macroDrag >= 0) { e.preventDefault(); row.classList.add("dragover"); } });
    row.addEventListener("dragleave", function () { row.classList.remove("dragover"); });
    row.addEventListener("drop", function (e) {
      e.preventDefault(); row.classList.remove("dragover");
      var from = macroDrag; macroDrag = -1;
      if (from >= 0 && from !== i) macroApply(b, PL.macroMove(b.macro, from, i));
    });
    row.addEventListener("dragend", function () { macroDrag = -1; row.draggable = false; });
    var kindSel = select(kind, PL.STEP_KINDS.map(function (k) { return [k.kind, k.label]; }), function (v) {
      macroApply(b, PL.macroSetKind(b.macro, i, v, mediaList()));
    });
    function btn(txt, title, fn, off) {
      var x = h("button", { cls: "ghost small", text: txt, title: title, type: "button" });
      x.disabled = !!off; x.onclick = function () { fn(); }; return x;
    }
    var full = m.length >= PL.MACRO_MAX;
    row.appendChild(h("div", { cls: "mhead" }, [handle, h("span", { cls: "mi", text: def.icon, title: def.label }), kindSel,
      btn("↑", "Nach oben", function () { macroApply(b, PL.macroMove(b.macro, i, i - 1)); }, i === 0),
      btn("↓", "Nach unten", function () { macroApply(b, PL.macroMove(b.macro, i, i + 1)); }, i === m.length - 1),
      btn("⧉", full ? "Höchstzahl erreicht" : "Schritt duplizieren", function () { macroApply(b, PL.macroDuplicate(b.macro, i)); }, full),
      btn("✕", "Schritt löschen", function () { macroApply(b, PL.macroRemove(b.macro, i)); })]));
    row.appendChild(macroStepValue(b, i));
    return row;
  }
  // Abfolge aufnehmen: Tasten/Kombinationen nacheinander drücken, Pausen werden zu Warten-Schritten, Esc beendet.
  // Läuft über dieselbe Variable capture wie das Tastenfeld: jedes Neuzeichnen der Eigenschaften bricht sie ab.
  function macroRecordBar(b, msgEl) {
    var rec = h("button", { cls: "ghost", type: "button", text: "Abfolge aufnehmen",
      title: "Nacheinander Tasten oder Kombinationen auf der PC-Tastatur drücken, Pausen dazwischen werden als Warten übernommen. Esc beendet." });
    var events = [], cap = null, t0 = 0, running = false, finishing = false;
    function evOf(e, type) {
      e.preventDefault(); e.stopPropagation();
      return { type: type, code: e.code, altGraph: !!(e.getModifierState && e.getModifierState("AltGraph")) };
    }
    function onDown(e) { var ev = evOf(e, "down"); if (!e.repeat) handle(PL.captureEvent(cap, ev, keyNames)); }
    function onUp(e) { handle(PL.captureEvent(cap, evOf(e, "up"), keyNames)); }
    function handle(r) {
      if (!r) return;
      if (r.hint) { msgEl.textContent = r.hint; msgEl.classList.add("warn"); return; }
      if (r.cancel) return finish();
      if (r.done) {
        events.push({ t: performance.now() - t0, key: r.done }); cap = PL.newCapture();
        msgEl.classList.remove("warn"); msgEl.textContent = "Aufgenommen: " + events.length + " – weiter drücken, Esc beendet.";
      }
    }
    function stop() {
      // von außen abgebrochen (Fokuswechsel, anderes Aufnehmen, Neuzeichnen): sagen, was verworfen wurde
      if (running && !finishing) {
        macroMsg = events.length ? "Aufnahme abgebrochen – " + events.length + " aufgenommene Taste(n) verworfen." : "Aufnahme abgebrochen.";
        msgEl.textContent = macroMsg; msgEl.classList.add("warn");
      }
      running = false;
      document.removeEventListener("keydown", onDown, true); document.removeEventListener("keyup", onUp, true);
      rec.textContent = "Abfolge aufnehmen"; rec.classList.remove("recording");
    }
    function finish() {
      finishing = true;
      stopCapture();
      var res = PL.recordToSteps(events, PL.MACRO_MAX - b.macro.length);
      var r = PL.macroInsertMany(b.macro, res.steps, macroSel >= 0 ? macroSel : undefined);
      if (r.err) { macroMsg = events.length && !res.steps.length ? "Kein Platz mehr (höchstens " + PL.MACRO_MAX + " Schritte)." : r.err; renderProps(); return; }
      macroApply(b, r);
      if (res.cut) { macroMsg = "Aufnahme bei " + PL.MACRO_MAX + " Schritten abgeschnitten."; renderProps(); }
    }
    rec.onclick = function () {
      if (running) return finish();
      stopCapture();
      if (b.macro.length >= PL.MACRO_MAX) { msgEl.textContent = "Höchstens " + PL.MACRO_MAX + " Schritte."; msgEl.classList.add("warn"); return; }
      events = []; cap = PL.newCapture(); t0 = performance.now(); running = true; finishing = false;
      rec.textContent = "Aufnahme läuft – Esc beendet"; rec.classList.add("recording");
      msgEl.classList.remove("warn"); msgEl.textContent = "Tasten nacheinander drücken (Pausen werden mit aufgenommen). Esc beendet.";
      document.addEventListener("keydown", onDown, true); document.addEventListener("keyup", onUp, true);
      capture = stop;
    };
    return rec;
  }
  function macroText(box, b) {
    var ta = h("textarea"); ta.value = macroToText(b.macro);
    var errBox = h("div", { cls: "err-box" });
    ta.addEventListener("input", function () {
      var r = textToMacro(ta.value);
      if (!r.macro.length && !r.errs.length) r.errs.push("Makro ist leer – mindestens ein Schritt nötig (alter Stand bleibt).");
      if (!r.errs.length) r.errs = PL.macroErrors(r.macro, keyNames, mediaNames).map(function (x) { return (x.index >= 0 ? "Schritt " + (x.index + 1) + ": " : "") + x.text; });
      if (!r.errs.length && PL.isSoloMedia(r.macro)) r.errs.push(PL.SOLO_HINT);
      errBox.textContent = r.errs.join("\n");
      if (!r.errs.length && r.macro.length) { b.macro = r.macro; refresh(); }
    });
    box.appendChild(field("Makro – eine Zeile pro Schritt", ta,
      "key LALT+1 · text o7 · wait 200 (ms) · media playpause. Läuft beim Drücken einmal ab."));
    box.appendChild(errBox);
  }
  function macroBuilder(box, b) {
    if (macroSelFor !== b.id) { macroSelFor = b.id; macroSel = -1; macroMsg = ""; }
    if (macroSel >= b.macro.length) macroSel = b.macro.length - 1;
    var tabs = h("div", { cls: "row mview" }, ["list", "text"].map(function (v) {
      return h("button", { cls: macroView === v ? "" : "ghost", type: "button", text: v === "list" ? "Schritte" : "Text",
        onclick: function () { macroView = v; macroMsg = ""; renderProps(); } });
    }));
    box.appendChild(field("Makro – läuft beim Drücken einmal ab", tabs));
    if (macroView === "text") return macroText(box, b);
    var list = h("div", { cls: "msteps" });
    b.macro.forEach(function (_, i) { list.appendChild(macroRow(b, i)); });
    box.appendChild(list);
    var full = b.macro.length >= PL.MACRO_MAX;
    box.appendChild(h("div", { cls: "madd" }, PL.STEP_KINDS.map(function (k) {
      var x = h("button", { cls: "ghost small", type: "button", text: k.add, title: full ? "Höchstzahl erreicht" : k.hint });
      x.disabled = full;
      x.onclick = function () { macroApply(b, PL.macroInsert(b.macro, PL.newStep(k.kind, mediaList()), macroSel >= 0 ? macroSel : undefined)); };
      return x;
    })));
    var msg = h("span", { cls: "hint" + (macroMsg ? " warn" : ""), text: macroMsg });
    box.appendChild(h("div", { cls: "row" }, [macroRecordBar(b, msg)]));
    box.appendChild(msg);
    box.appendChild(h("span", { cls: "hint", text: b.macro.length + " von " + PL.MACRO_MAX + " Schritten. Neue Schritte kommen hinter den gewählten (sonst ans Ende). Der letzte Schritt und ein einzelner Medien-Schritt (= Art „Medien“) sind geschützt." }));
  }

  // Mehrfachauswahl: gemeinsame Felder (nur wo sie bei der Taste gelten), „verschieden“ bei Unterschieden
  function renderMultiProps(box, p) {
    var bs = selButtons();
    box.appendChild(h("p", { cls: "hint", text: bs.length + " Tasten gewählt – eine Änderung gilt für alle, bei denen das Feld möglich ist. Verschieben, Ausrichten und Duplizieren geht über die Werkzeugleiste." }));
    var fields = PL.commonFields(bs, p.type);
    var mixedOpt = function (f, opts) { return f.mixed ? [["__mixed", "(verschieden)"]].concat(opts) : opts; };
    fields.forEach(function (f) {
      var apply = function (v) { if (v === "__mixed") return; PL.setShared(bs, f.key, v, p.type); refresh(); };
      var partial = f.count < bs.length ? " (" + f.count + " von " + bs.length + ")" : "";
      if (f.key === "style") box.appendChild(field("Farbe" + partial, selMixed(f, mixedOpt(f, STYLE_OPTIONS), apply)));
      else if (f.key === "mode") box.appendChild(field("Verhalten" + partial, selMixed(f, mixedOpt(f, MODE_OPTIONS), apply)));
      else if (f.key === "hold") box.appendChild(field("Taste halten, solange der Finger liegt" + partial, selMixed(f, mixedOpt(f, [["0", "Nein (kurzer Impuls)"], ["1", "Ja"]]), apply)));
      else if (f.key === "zone") box.appendChild(field("Zone" + partial, selMixed(f, mixedOpt(f, PL.ZONES.map(function (z) { return [z, ZONE_LABELS[z]]; })), apply)));
      else if (f.key === "group") {
        var gi = input(f.mixed ? "" : f.value, function (v) { PL.setShared(bs, "group", v, p.type); refresh(); });
        if (f.mixed) gi.setAttribute("placeholder", "verschieden");
        box.appendChild(field("Gruppe (Überschrift)" + partial, gi, "Leer = Überschrift entfernen."));
      }
    });
  }
  function selMixed(f, opts, onchange) {
    var s = select(f.mixed ? "__mixed" : f.value, opts, onchange);
    return s;
  }

  // ---------------------------------------------------------------- Gesamtanzeige und Schnittstelle
  function renderAll() {
    renderHead(); renderTabs(); renderPage(); layoutStage(); renderOverlay(); renderList(); renderProps(); renderToolbar(); renderActions();
    $("tv").style.visibility = layout ? "" : "hidden";
    $("previewNone").hidden = !!layout;
  }

  function load(l) {
    layout = l; pageIdx = 0; setSel([]); drag = null; marquee = null; dropMark = null;
    hist = new Core.History(200); hist.push(snap());
    $("toast").hidden = true;
    renderAll();
  }
  function clearAll() {
    layout = null; hist = null; pageIdx = 0; setSel([]);
    renderAll();
  }
  function setInfo(i) { info = i; renderHead(); }
  function setKeys(keys, media) { keyNames = keys; mediaNames = media; }
  function activate() { active = true; layoutStage(); renderOverlay(); }
  function deactivate() { active = false; stopCapture(); }

  function init(a) {
    api = a;
    renderBlocks();
    var tv = $("tv");
    tv.addEventListener("pointerdown", onDown);
    tv.addEventListener("pointermove", onMove);
    tv.addEventListener("pointerup", onUp);
    tv.addEventListener("pointercancel", onUp);
    tv.addEventListener("dblclick", onDbl);
    tv.addEventListener("dragover", onDragOver);
    tv.addEventListener("dragleave", onDragLeave);
    tv.addEventListener("drop", onDrop);
    $("tvMain").addEventListener("scroll", renderOverlay);
    document.addEventListener("keydown", onKey);
    $("actQuery").addEventListener("input", function () { actionsQuery = this.value; renderActions(); });
    // Eingabefelder rechts: ein Verlaufsschritt je abgeschlossener Eingabe (change)
    $("buttonProps").addEventListener("change", function () { if (hist) { hist.push(snap()); renderToolbar(); } });
    $("pageProps").addEventListener("change", function () { if (hist) { hist.push(snap()); renderToolbar(); } });
    $("pUndo").onclick = function () { undo(false); };
    $("pRedo").onclick = function () { undo(true); };
    $("pDup").onclick = duplicateSel;
    $("pDel").onclick = removeSel;
    Object.keys(TOOLS).forEach(function (id) {
      var t = TOOLS[id];
      $(id).onclick = function () {
        tool(function (p) {
          return t[0] === "a" ? PL.alignCells(p, sel, t[1]) : t[0] === "d" ? PL.distributeCells(p, sel, t[1]) : PL.sameSizeCells(p, sel, t[1]);
        });
      };
    });
    renderAll();
  }

  window.PanelEditor = { init: init, load: load, clear: clearAll, setInfo: setInfo, setKeys: setKeys, onMessage: onMessage,
    requestActions: requestActions, activate: activate, deactivate: deactivate, stopCapture: stopCapture,
    checkpoint: function () { if (hist) { hist.push(snap()); renderToolbar(); } } };
})();
