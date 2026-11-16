"use strict";
// Reine Logik des Panel-Baukastens (ohne DOM): Bausteine, Spielaktionen aus der Palette, Einfügen an Zellen,
// freie Zellen finden, automatische Seite -> freie Seite, Ausrichten in Zellen, gemeinsame Felder bei Mehrfachauswahl.
// Panel-Tasten haben ein Feld `group` (= Überschrift auf automatischen Seiten), KEINE Editor-Gruppe: darum
// rechnet der Kern (core.js) hier nur mit Elementen {id, x, y, w, h} ohne group (toItems/applyItems).
// Browser: window.PanelLib, Node: module.exports (Tests: tests/js/panellib.test.js).
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./core.js"));
  else root.PanelLib = factory(root.EditorCore);
})(typeof self !== "undefined" ? self : this, function (Core) {
  var MAX_COLS = 16, MAX_ROWS = 12, DEF_COLS = 12, DEF_ROWS = 8;
  var ZONES = ["front", "back", "left", "right", "top", "bottom", "reset"];
  // Platzhaltertasten der Bausteine (gültig nach layout.py, im Spiel kaum belegt) - der Nutzer trägt die echte ein
  var PLACEHOLDER = { states: "SCROLLLOCK", up: "PGUP", down: "PGDN", open: "https://example.org/" };

  var BLOCKS = [
    { kind: "key", label: "Taste", hint: "Drücken sendet eine Taste", w: 2, h: 1 },
    { kind: "states", label: "Mehrfach-Schalter", hint: "Jeder Tipp schaltet weiter (2–6 Zustände)", w: 2, h: 1 },
    { kind: "slider", label: "Regler", hint: "Ziehen sendet mehr / weniger", w: 4, h: 1 },
    { kind: "page", label: "Seiten-Link", hint: "Wechselt am Tablet die Seite", w: 2, h: 1 },
    { kind: "macro", label: "Makro-Taste", hint: "Mehrere Schritte nacheinander", w: 2, h: 1 }
  ];

  function copy(o) { return JSON.parse(JSON.stringify(o)); }
  function cols(p) { return p.cols || DEF_COLS; }
  function rows(p) { return p.rows || DEF_ROWS; }

  // ---------------------------------------------------------------- IDs
  function allIds(layout) {
    var ids = Object.create(null);
    layout.pages.forEach(function (p) { p.buttons.forEach(function (b) { ids[b.id] = true; }); });
    return ids;
  }
  function uniqueId(base, taken) {
    var id = base, i = 1;
    while (taken[id]) id = base + "_" + (++i);
    return id;
  }
  function uniquePageId(layout, base) {
    var t = Object.create(null);
    layout.pages.forEach(function (p) { t[p.id] = true; });
    return uniqueId(base || "seite", t);
  }

  // ---------------------------------------------------------------- Bausteine und Aktionen
  function blockSize(kind, page) {
    var b = BLOCKS.filter(function (x) { return x.kind === kind; })[0] || BLOCKS[0];
    return { w: Math.min(b.w, cols(page || {})), h: b.h };
  }

  // Neuer Baustein als gültige Taste (nach layout.py). Lage setzt addButton.
  function newBlock(kind, layout, page) {
    var id = uniqueId((page ? page.id : "seite") + "_" + (kind === "key" ? "taste" : kind), allIds(layout));
    var b = { id: id, label: "NEU", mode: "tap" };
    if (kind === "states") { b.label = "SCHALTER"; b.key = PLACEHOLDER.states; b.states = [{ label: "AUS" }, { label: "AN" }]; }
    else if (kind === "slider") { b.label = "REGLER"; b.slider = { up: PLACEHOLDER.up, down: PLACEHOLDER.down, steps: 10 }; }
    else if (kind === "page") {
      var other = layout.pages.filter(function (x) { return x !== page; })[0] || page;
      b = { id: id, label: "SEITE", page: other ? other.id : "" };
    } else if (kind === "macro") { b.label = "MAKRO"; b.macro = [{ wait: 200 }]; }
    return b;
  }

  // Taste mit Platzhaltertaste (Baustein noch nicht fertig belegt)
  function hasPlaceholder(b) {
    if (b.open === PLACEHOLDER.open) return true;
    if (b.slider) return b.slider.up === PLACEHOLDER.up && b.slider.down === PLACEHOLDER.down;
    return !!b.states && b.key === PLACEHOLDER.states;
  }

  // Palette-Eintrag (Hub: actions) -> neue Taste mit eindeutiger ID, ohne Lagefelder
  function buttonFromAction(entry, layout, page) {
    var b = copy(entry.button || {});
    ["x", "y", "w", "h", "zone", "wide"].forEach(function (k) { delete b[k]; });
    if (page && page.type === "shield") delete b.group;
    else if (entry.group && !b.group) b.group = entry.group;
    b.id = uniqueId(b.id || "taste", allIds(layout));
    return b;
  }
  function actionName(b) { return b.sc || b.action || ""; }

  // Welche Aktionen/IDs hat das Panel schon? (für die Kennzeichnung in der Palette)
  function presentSet(layout) {
    var s = { actions: Object.create(null), ids: allIds(layout) };
    layout.pages.forEach(function (p) { p.buttons.forEach(function (b) { if (actionName(b)) s.actions[actionName(b)] = true; }); });
    return s;
  }
  function isPresent(entry, present) {
    var a = entry.action || actionName(entry.button || {});
    return a ? !!present.actions[a] : !!present.ids[(entry.button || {}).id];
  }

  // Palette filtern: Suchtext in Beschriftung, Aktion, Taste, Überschrift, Seite. Leere Seiten/Vorlagen entfallen.
  function filterActions(templates, query) {
    var q = String(query || "").trim().toLowerCase();
    if (!q) return templates;
    var out = [];
    templates.forEach(function (t) {
      var pages = [];
      t.pages.forEach(function (p) {
        var acts = p.actions.filter(function (a) {
          return [a.button.label, a.action, a.key, a.group, p.title, t.title].join("\n").toLowerCase().indexOf(q) >= 0;
        });
        if (acts.length) pages.push({ id: p.id, title: p.title, actions: acts });
      });
      if (pages.length) out.push({ id: t.id, title: t.title, pages: pages });
    });
    return out;
  }

  // ---------------------------------------------------------------- Zellen
  function hits(a, x, y, w, h) { return x < a.x + a.w && a.x < x + w && y < a.y + a.h && a.y < y + h; }

  function overlapSet(page) {
    var s = Object.create(null);
    page.buttons.forEach(function (a, i) {
      page.buttons.forEach(function (b, j) { if (i < j && hits(a, b.x, b.y, b.w, b.h)) { s[a.id] = true; s[b.id] = true; } });
    });
    return s;
  }

  // Erste freie Stelle (zeilenweise) für w x h; null, wenn nichts frei ist. ignore: ID, die nicht zählt.
  function freeSpot(page, w, h, ignore) {
    var c = cols(page), r = rows(page);
    for (var y = 0; y + h <= r; y++) for (var x = 0; x + w <= c; x++) {
      if (!page.buttons.some(function (b) { return b.id !== ignore && hits(b, x, y, w, h); })) return { x: x, y: y };
    }
    return null;
  }

  // Freie Stelle, die der Zielzelle am nächsten liegt; null, wenn nichts frei ist.
  function nearestFree(page, w, h, tx, ty, ignore) {
    var c = cols(page), r = rows(page), best = null, bd = Infinity;
    for (var y = 0; y + h <= r; y++) for (var x = 0; x + w <= c; x++) {
      var d = (x - tx) * (x - tx) + (y - ty) * (y - ty);
      if (d >= bd) continue;
      if (!page.buttons.some(function (b) { return b.id !== ignore && hits(b, x, y, w, h); })) { best = { x: x, y: y }; bd = d; }
    }
    return best;
  }

  // Zelle unter einem Punkt. box = {left, top, width, height} der Rasterfläche, gap = Abstand der Zellen (px).
  function cellAt(box, gap, c, r, px, py) {
    var cw = (box.width - gap * (c - 1)) / c + gap, ch = (box.height - gap * (r - 1)) / r + gap;
    return {
      x: Math.max(0, Math.min(c - 1, Math.floor((px - box.left) / cw))),
      y: Math.max(0, Math.min(r - 1, Math.floor((py - box.top) / ch))),
      fx: (px - box.left) / cw, fy: (py - box.top) / ch   // in Zellen, nicht begrenzt (Rahmenauswahl)
    };
  }
  // Zellenbreite/-höhe samt Abstand (Pixel pro Zellschritt)
  function cellStep(box, gap, c, r) {
    return { x: (box.width - gap * (c - 1)) / c + gap, y: (box.height - gap * (r - 1)) / r + gap };
  }

  // ---------------------------------------------------------------- Einfügen
  function unusedZone(page) {
    var used = Object.create(null);
    page.buttons.forEach(function (b) { used[b.zone] = true; });
    return ZONES.filter(function (z) { return !used[z]; })[0] || "front";
  }

  // Taste auf freier Seite platzieren: Zielzelle at {x,y} (nächste freie Stelle) bzw. erste freie Stelle; ist nichts
  // frei, wachsen die Zeilen (bis 12), zuletzt wird überlappend gesetzt. Ergebnis {overlap: bool}.
  function placeFree(page, b, at) {
    var w = Math.max(1, Math.min(b.w || 2, cols(page))), h = Math.max(1, Math.min(b.h || 1, rows(page)));
    var spot = null;
    for (;;) {
      spot = at ? nearestFree(page, w, h, at.x, at.y) : freeSpot(page, w, h);
      if (spot || rows(page) >= MAX_ROWS) break;
      page.rows = rows(page) + 1; page.cols = cols(page);
    }
    var overlap = !spot;
    if (!spot) spot = at ? { x: Math.max(0, Math.min(at.x, cols(page) - w)), y: Math.max(0, Math.min(at.y, rows(page) - h)) } : { x: 0, y: 0 };
    b.x = spot.x; b.y = spot.y; b.w = w; b.h = h;
    return { overlap: overlap };
  }

  // Taste in eine Seite einfügen. opts: at {x,y} (freie Seite), index (automatische Seite: davor einfügen),
  // group (automatische Seite: Überschrift setzen; "" = ohne), zone (Schild). Gibt {overlap} zurück.
  function addButton(page, b, opts) {
    opts = opts || {};
    var res = { overlap: false };
    if (page.type === "free") {
      var s = BLOCKS.filter(function (x) { return !b.w && x.kind === opts.kind; })[0];
      if (s) { b.w = s.w; b.h = s.h; }
      res = placeFree(page, b, opts.at);
      page.buttons.push(b);
    } else {
      if (page.type === "shield") b.zone = opts.zone || unusedZone(page);
      else if (typeof opts.group === "string") { if (opts.group) b.group = opts.group; else delete b.group; }
      var i = typeof opts.index === "number" && opts.index >= 0 && opts.index <= page.buttons.length ? opts.index : page.buttons.length;
      page.buttons.splice(i, 0, b);
    }
    return res;
  }

  // ---------------------------------------------------------------- Seitentyp
  // Tasten nach Gruppen in Reihen legen (jede Gruppe beginnt eine neue Reihe); passt es nicht: schmaler, dann ohne
  // Gruppenumbruch. false, wenn es auch so nicht in 12 Zeilen passt (Seite bleibt dann unverändert).
  function arrange(p) {
    var c = cols(p), r = rows(p);
    var tries = [[2, true], [1, true], [1, false]];
    for (var t = 0; t < tries.length; t++) {
      var w = tries[t][0], breakGroups = tries[t][1], x = 0, y = 0, last = null, pos = [];
      p.buttons.forEach(function (b) {
        var bw = (b.wide || b.slider) && breakGroups ? c : w;
        if (breakGroups && last !== null && (b.group || "") !== last && x > 0) { x = 0; y++; }
        if (x + bw > c) { x = 0; y++; }
        pos.push([x, y, bw]); x += bw; last = b.group || "";
        if (x >= c) { x = 0; y++; }
      });
      var used = pos.length ? Math.max.apply(null, pos.map(function (q) { return q[1] + 1; })) : 1;
      if (used <= MAX_ROWS) {
        p.buttons.forEach(function (b, i) { b.x = pos[i][0]; b.y = pos[i][1]; b.w = pos[i][2]; b.h = 1; });
        p.rows = Math.min(MAX_ROWS, Math.max(r, used)); p.cols = c;
        return true;
      }
    }
    return false;
  }

  // Automatische (oder Schild-)Seite -> freie Seite, Positionen aus der automatischen Anordnung. Neue Seite oder null.
  function toFree(page) {
    if (page.type === "free") return page;
    var c = copy(page);
    if (!arrange(c)) return null;
    c.type = "free";
    c.buttons.forEach(function (b) { delete b.zone; });
    return c;
  }

  // Seitentyp wechseln (verändert die Seite). Gibt false zurück, wenn es nicht geht (zu viele Tasten).
  function setPageType(p, v) {
    if (v === "free" && p.type !== "free") {
      var f = toFree(p);
      if (!f) return false;
      p.type = "free"; p.cols = f.cols; p.rows = f.rows;
      p.buttons.forEach(function (b, i) { var q = f.buttons[i]; b.x = q.x; b.y = q.y; b.w = q.w; b.h = q.h; delete b.zone; });
      return true;
    }
    if (v !== "free" && p.type === "free") {
      p.buttons.forEach(function (b) { delete b.x; delete b.y; delete b.w; delete b.h; });
      delete p.cols; delete p.rows;
    }
    p.type = v;
    if (v === "shield") p.buttons.forEach(function (b) { if (ZONES.indexOf(b.zone) < 0) b.zone = "front"; });
    return true;
  }

  // Zeilen/Spalten ändern; Tasten werden ins neue Raster geholt.
  function setGrid(p, c, r) {
    if (!(c >= 2 && c <= MAX_COLS && r >= 2 && r <= MAX_ROWS)) return false;
    p.cols = c; p.rows = r;
    p.buttons.forEach(function (b) {
      b.w = Math.min(b.w || 1, c); b.h = Math.min(b.h || 1, r);
      b.x = Math.min(b.x || 0, c - b.w); b.y = Math.min(b.y || 0, r - b.h);
    });
    return true;
  }

  // ---------------------------------------------------------------- Kern-Anbindung (Zellen)
  function toItems(page) {
    return page.buttons.map(function (b) { return { id: b.id, x: b.x, y: b.y, w: b.w, h: b.h }; });
  }
  function applyItems(page, items) {
    var m = Object.create(null);
    items.forEach(function (i) { m[i.id] = i; });
    page.buttons.forEach(function (b) { var i = m[b.id]; if (i) { b.x = i.x; b.y = i.y; b.w = i.w; b.h = i.h; } });
  }
  function area(page) { return { w: cols(page), h: rows(page) }; }

  // ganze Zellen, innerhalb des Rasters
  function toCells(items, ids, a) {
    var s = Object.create(null);
    ids.forEach(function (i) { s[i] = true; });
    return items.map(function (it) {
      if (!s[it.id]) return it;
      var c = { id: it.id };
      c.w = Math.max(1, Math.min(a.w, Math.round(it.w)));
      c.h = Math.max(1, Math.min(a.h, Math.round(it.h)));
      c.x = Math.max(0, Math.min(a.w - c.w, Math.round(it.x)));
      c.y = Math.max(0, Math.min(a.h - c.h, Math.round(it.y)));
      return c;
    });
  }

  // Was geht bei n gewählten Tasten? (ausrichten ab 1 = am Raster, verteilen ab 3, gleiche Größe ab 2)
  function arrangeState(n) { return { align: n >= 1, distribute: n >= 3, sameSize: n >= 2 }; }

  // Aktionen auf einer freien Seite: ändern die Seite und geben true zurück, wenn etwas möglich war.
  function moveBy(page, ids, dx, dy) {
    var a = area(page);
    applyItems(page, Core.move(toItems(page), ids, dx, dy, a, true));
  }
  function alignCells(page, ids, mode) {
    if (!ids.length) return false;
    var a = area(page);
    applyItems(page, toCells(Core.alignUnits(toItems(page), ids, mode, a, true), ids, a));
    return true;
  }
  function distributeCells(page, ids, axis) {
    if (ids.length < 3) return false;
    var a = area(page);
    applyItems(page, toCells(Core.distribute(toItems(page), ids, axis), ids, a));
    return true;
  }
  function sameSizeCells(page, ids, dim) {
    if (ids.length < 2) return false;
    var a = area(page);
    applyItems(page, toCells(Core.sameSize(toItems(page), ids, dim), ids, a));
    return true;
  }
  function resizeCells(page, id, handle, dx, dy) {
    var it = toItems(page).filter(function (x) { return x.id === id; })[0];
    if (!it) return;
    var r = Core.resize(it, handle, dx, dy, { w: 1, h: 1 }, area(page));
    applyItems(page, [r]);
  }
  function selectInRect(page, rect) { return Core.selectInRect(toItems(page), rect); }

  // Duplizieren: Kopien mit neuen IDs an freien Stellen (freie Seite) bzw. hinter dem Original. Gibt die neuen IDs.
  function duplicate(layout, page, ids) {
    var taken = allIds(layout), made = [], sel = Object.create(null);
    ids.forEach(function (i) { sel[i] = true; });
    page.buttons.filter(function (b) { return sel[b.id]; }).forEach(function (b) {
      var c = copy(b);
      c.id = uniqueId(b.id, taken); taken[c.id] = true;
      if (page.type === "free") placeFree(page, c, { x: Math.min(b.x + 1, cols(page) - 1), y: Math.min(b.y + 1, rows(page) - 1) });
      var at = page.type === "free" ? page.buttons.length : page.buttons.indexOf(b) + 1 + made.length;
      page.buttons.splice(at, 0, c);
      made.push(c.id);
    });
    return made;
  }

  // ---------------------------------------------------------------- Art der Taste (Aktion nach Art zuordnen)
  var ARTS = [
    { id: "press", label: "Taste drücken", hint: "Kurzer Impuls (80 ms) – richtig für die meisten Spielaktionen." },
    { id: "hold", label: "Taste halten", hint: "Die Taste bleibt gedrückt, solange der Finger liegt (z. B. Ping, Hupe)." },
    { id: "toggle", label: "Umschalten", hint: "Die Tablet-Taste merkt An/Aus und zeigt es an." },
    { id: "states", label: "Mehrfach-Schalter", hint: "Jeder Tipp schaltet weiter (2–6 Zustände)." },
    { id: "slider", label: "Regler", hint: "Ziehen sendet je Stufe einen Tastendruck für mehr / weniger." },
    { id: "page", label: "Seite wechseln", hint: "Wechselt am Tablet die Seite, sendet nichts an den PC." },
    { id: "open", label: "Programm öffnen", hint: "Öffnet am PC eine URL, ein Programm, eine Datei oder einen Ordner." },
    { id: "macro", label: "Makro", hint: "Mehrere Schritte nacheinander (Taste, Text, Warten, Medien)." },
    { id: "media", label: "Medien", hint: "Wiedergabe, Lautstärke, nächster/voriger Titel." }
  ];
  var MEDIA_DEFAULT = "playpause";

  // Art aus den vorhandenen Feldern ableiten (Rangfolge: slider, states, page, open, macro, sonst Taste)
  function artOf(b) {
    if (b.slider) return "slider";
    if (b.states) return "states";
    if (b.page !== undefined) return "page";
    if (b.open !== undefined) return "open";
    if (b.macro) return b.macro.length === 1 && b.macro[0] && b.macro[0].media !== undefined ? "media" : "macro";
    if (b.mode === "toggle") return "toggle";
    return b.hold ? "hold" : "press";
  }
  // Alle Tasten, die die Taste kennt (für die Übernahme beim Wechsel der Art)
  function carryKeys(b) {
    var out = [];
    function add(k) { if (typeof k === "string" && k && out.indexOf(k) < 0) out.push(k); }
    add(b.key);
    if (b.states) b.states.forEach(function (s) { add(s && s.key); });
    if (b.slider) { add(b.slider.up); add(b.slider.down); }
    if (b.macro) b.macro.forEach(function (s) { add(s && s.key); });
    return out;
  }
  // Taste auf eine andere Art umbauen (verändert die Taste, gibt sie zurück). Danach gibt es nur Felder dieser Art;
  // id, label, group, style und Lage (zone/x/y/w/h/wide) bleiben. ctx: {page: aktuelle Seite, pages: alle Seiten}.
  // „Erst nach Halten auslösen“ (mode hold-confirm) bleibt bei Arten, bei denen layout.py es erlaubt.
  function convertArt(b, art, ctx) {
    ctx = ctx || {};
    var cur = artOf(b);
    if (cur === art) return b;
    var keys = carryKeys(b), confirm = b.mode === "hold-confirm";
    var media = cur === "media" ? b.macro[0].media : MEDIA_DEFAULT;
    var oldStates = b.states, oldMacro = b.macro, sc = b.sc;
    ["key", "macro", "open", "page", "states", "slider", "hold", "mode", "sc"].forEach(function (k) { delete b[k]; });
    // sc (Spielaktion für scripts/sc_bindings.py) bleibt, solange es eine Einzeltaste bleibt
    if (sc !== undefined && (art === "press" || art === "hold" || art === "toggle")) b.sc = sc;
    var mode = confirm ? "hold-confirm" : "tap";
    if (art === "press" || art === "hold" || art === "toggle") {
      if (keys[0]) b.key = keys[0];
      if (art === "toggle") b.mode = "toggle";
      else { b.mode = mode; if (art === "hold") b.hold = true; }
    } else if (art === "states") {
      b.mode = "tap";
      b.key = keys[0] || PLACEHOLDER.states;
      b.states = oldStates || [{ label: "AUS" }, { label: "AN" }];
    } else if (art === "slider") {
      var up = keys[0] || PLACEHOLDER.up, down = keys[1] || PLACEHOLDER.down;
      if (down === up) down = up === PLACEHOLDER.down ? PLACEHOLDER.up : PLACEHOLDER.down;
      b.mode = "tap";
      b.slider = { up: up, down: down, steps: 10 };
    } else if (art === "page") {
      var pages = ctx.pages || [], other = pages.filter(function (x) { return x !== ctx.page; })[0] || ctx.page || pages[0];
      b.page = other ? other.id : "";
    } else if (art === "open") {
      b.mode = mode;
      b.open = PLACEHOLDER.open;
    } else if (art === "macro") {
      b.mode = mode;
      b.macro = cur === "media" ? oldMacro.concat([{ wait: 200 }]) : [keys[0] ? { key: keys[0] } : { wait: 200 }];   // ein Medien-Schritt allein wäre wieder „Medien“
    } else if (art === "media") {
      b.mode = mode;
      b.macro = [{ media: media }];
    }
    if (b.mode === "tap") delete b.mode;
    return b;
  }

  // ---------------------------------------------------------------- Tasten aufnehmen (KeyboardEvent.code -> Schreibweise von keys.py)
  var CODE = { Escape: "ESC", Enter: "ENTER", Tab: "TAB", Space: "SPACE", Backspace: "BACKSPACE", Delete: "DELETE",
    Insert: "INSERT", Home: "HOME", End: "END", PageUp: "PGUP", PageDown: "PGDN", ArrowUp: "UP", ArrowDown: "DOWN",
    ArrowLeft: "LEFT", ArrowRight: "RIGHT", ShiftLeft: "LSHIFT", ShiftRight: "RSHIFT", ControlLeft: "LCTRL",
    ControlRight: "RCTRL", AltLeft: "LALT", AltRight: "RALT", Minus: "MINUS", Equal: "EQUALS", BracketLeft: "LBRACKET",
    BracketRight: "RBRACKET", Semicolon: "SEMICOLON", Quote: "APOSTROPHE", Backquote: "GRAVE", Backslash: "BACKSLASH",
    Comma: "COMMA", Period: "PERIOD", Slash: "SLASH", CapsLock: "CAPSLOCK", ScrollLock: "SCROLLLOCK",
    NumpadAdd: "NUMPADADD", NumpadSubtract: "NUMPADSUBTRACT", NumpadMultiply: "NUMPADMULTIPLY",
    NumpadDivide: "NUMPADDIVIDE", NumpadDecimal: "NUMPADDECIMAL", NumpadEnter: "NUMPADENTER" };
  var MODS = ["LCTRL", "RCTRL", "LSHIFT", "RSHIFT", "LALT", "RALT"];
  var MEDIA_CODES = { AudioVolumeUp: 1, AudioVolumeDown: 1, AudioVolumeMute: 1, MediaPlayPause: 1, MediaTrackNext: 1,
    MediaTrackPrevious: 1, MediaStop: 1 };
  // KeyboardEvent.code -> Tastenname (keys.py) oder null
  function codeName(code) {
    code = String(code || "");
    if (Object.prototype.hasOwnProperty.call(CODE, code)) return CODE[code];
    var m = code.match(/^Key([A-Z])$/) || code.match(/^Digit([0-9])$/) || code.match(/^(F(?:[1-9]|1[0-2]))$/);
    if (m) return m[1];
    m = code.match(/^Numpad([0-9])$/);
    return m ? "NUMPAD" + m[1] : null;
  }
  function isMod(n) { return MODS.indexOf(n) >= 0; }
  function comboOf(mods, main) {
    return MODS.filter(function (x) { return mods[x]; }).concat(main ? [main] : []).join("+");
  }
  // Zustand einer Aufnahme (rein; die Ereignisse liefert die Oberfläche). ev: {type: "down"|"up", code, altGraph}.
  // Ergebnis: null (weiter warten) | {done: "LALT+F"} | {cancel: true} | {hint: "Text"}.
  // AltGr meldet Windows als Strg-links + Alt-rechts: dann bleibt nur RALT (altGraph = getModifierState("AltGraph")).
  // Esc ohne Zusatztaste bricht ab. Nur Zusatztasten gedrückt und losgelassen: die Zusatztasten allein ("LSHIFT").
  // keyNames (optional): gültige Namen des Hubs; andere Tasten gelten als nicht abbildbar.
  function newCapture() { return { mods: Object.create(null), main: false }; }
  function captureEvent(st, ev, keyNames) {
    var code = ev.code, n = codeName(code);
    if (ev.type === "up") {
      if (n && isMod(n) && !st.main && MODS.some(function (x) { return st.mods[x]; })) {
        var c = comboOf(st.mods);
        st.mods = Object.create(null);
        return { done: c };
      }
      if (n && isMod(n)) delete st.mods[n];
      return null;
    }
    if (/^Meta(Left|Right)$/.test(code) || code === "OSLeft" || code === "OSRight") {
      return { hint: "Die Windows-Taste kann nicht gesendet werden." };
    }
    if (MEDIA_CODES[code]) return { hint: "Medientasten bitte über die Art „Medien“ (oder den Makro-Schritt media) einstellen." };
    if (n === "ESC" && !MODS.some(function (x) { return st.mods[x]; })) return { cancel: true };
    if (!n || (keyNames && keyNames.length && keyNames.indexOf(n) < 0)) {
      return { hint: "Diese Taste (" + (code || "?") + ") kann der Hub nicht senden." };
    }
    if (ev.altGraph && (n === "RALT" || st.mods.RALT)) delete st.mods.LCTRL;
    if (isMod(n)) { st.mods[n] = true; return null; }
    st.main = true;
    return { done: comboOf(st.mods, n) };
  }

  // ---------------------------------------------------------------- Doppelbelegung
  var ALIAS = { CTRL: "LCTRL", SHIFT: "LSHIFT", ALT: "LALT", RETURN: "ENTER", NP_ENTER: "NUMPADENTER" };
  for (var ai = 0; ai < 10; ai++) { ALIAS["NP_" + ai] = "NUMPAD" + ai; ALIAS["KP_" + ai] = "NUMPAD" + ai; }
  // Tastenkombination vergleichbar machen: Großschreibung, Aliase (CTRL, NP_9 ...), Zusatztasten in fester Reihenfolge
  function normKey(text) {
    if (typeof text !== "string" || !text.trim()) return "";
    var parts = text.toUpperCase().replace(/\s+/g, "").split("+").map(function (p) { return ALIAS[p] || p; });
    var mods = parts.filter(isMod).filter(function (p, i, a) { return a.indexOf(p) === i; });
    mods.sort(function (a, b) { return MODS.indexOf(a) - MODS.indexOf(b); });
    return mods.concat(parts.filter(function (p) { return !isMod(p); })).join("+");
  }
  // Tasten, die eine Panel-Taste am PC drückt (Makros zählen nicht: eine Abfolge ist keine Einzeltaste;
  // Platzhalter zählen nicht: noch nicht belegt)
  function sentKeys(b) {
    if (b.page !== undefined || b.open !== undefined || b.macro || hasPlaceholder(b)) return [];
    var out = [];
    function add(k) { var n = normKey(k); if (n && out.indexOf(n) < 0) out.push(n); }
    if (b.slider) { add(b.slider.up); add(b.slider.down); return out; }
    if (b.states) { b.states.forEach(function (s) { add((s && s.key) || b.key); }); return out; }
    add(b.key);
    return out;
  }
  // Doppelbelegung im ganzen Panel (auch über Seiten hinweg: am PC ist es dieselbe Taste).
  // -> {groups: [{key, items: [{id, label, page, pageTitle}]}], byId: {id: [{key, others: [item]}]}, count: Tasten, keys: Kombinationen}
  function duplicates(layout) {
    var map = Object.create(null), order = [];
    layout.pages.forEach(function (p) {
      p.buttons.forEach(function (b) {
        sentKeys(b).forEach(function (k) {
          if (!map[k]) { map[k] = []; order.push(k); }
          map[k].push({ id: b.id, label: b.label || b.id, page: p.id, pageTitle: p.title });
        });
      });
    });
    var groups = [], byId = Object.create(null);
    order.forEach(function (k) {
      var items = map[k];
      if (items.length < 2) return;
      groups.push({ key: k, items: items });
      items.forEach(function (it) {
        (byId[it.id] = byId[it.id] || []).push({ key: k, others: items.filter(function (o) { return o.id !== it.id; }) });
      });
    });
    return { groups: groups, byId: byId, count: Object.keys(byId).length, keys: groups.length };
  }

  // ---------------------------------------------------------------- Beschreibung
  function kindOf(b) {
    return b.slider ? "slider" : b.states ? "states" : b.macro ? "macro" : b.open !== undefined ? "open" : b.page !== undefined ? "page" : "key";
  }
  function isMapped(b) { return !!(b.key || b.macro || b.open || b.page || b.slider || b.states); }
  function metaText(b) {
    var m = b.macro ? "Makro (" + b.macro.length + ")" : b.open ? "öffnet " + b.open : b.page ? "→ Seite" :
      b.slider ? "Regler (" + b.slider.steps + " Stufen)" :
      b.states ? "Mehrfach: " + b.states.map(function (x) { return x.label; }).join("/") : (b.key || "");
    if (b.mode === "hold-confirm") m += " · halten";
    if (b.mode === "toggle") m += " · Schalter";
    if (b.group) m = b.group + " · " + m;
    return m;
  }

  // ---------------------------------------------------------------- Gemeinsame Felder (Mehrfachauswahl)
  // Wirkt das Feld bei dieser Taste? (mode/hold nur, wo layout.py sie erlaubt; group nicht auf Schild-Seiten)
  function applies(b, key, pageType) {
    if (key === "style") return true;
    if (key === "mode") return !b.page && !b.slider && !b.states;
    if (key === "hold") return !b.page && !b.slider;
    if (key === "group") return pageType !== "shield";
    if (key === "zone") return pageType === "shield";
    return false;
  }
  function valueOf(b, key) {
    if (key === "style") return b.style || "";
    if (key === "mode") return b.mode || "tap";
    if (key === "hold") return b.hold ? "1" : "0";
    return b[key] || "";
  }
  // [{key, value, mixed, count}] für Felder, die mindestens eine gewählte Taste hat
  function commonFields(buttons, pageType) {
    var out = [];
    ["style", "mode", "hold", "group", "zone"].forEach(function (key) {
      var list = buttons.filter(function (b) { return applies(b, key, pageType); });
      if (!list.length) return;
      var v = valueOf(list[0], key), mixed = list.some(function (b) { return valueOf(b, key) !== v; });
      out.push({ key: key, value: mixed ? "" : v, mixed: mixed, count: list.length });
    });
    return out;
  }
  // Feld bei allen gewählten Tasten setzen, bei denen es gilt (verändert die Tasten). hold: "1"/"0"/true/false.
  function setShared(buttons, key, value, pageType) {
    buttons.forEach(function (b) {
      if (!applies(b, key, pageType)) return;
      if (key === "hold") { if (value === true || value === "1") b.hold = true; else delete b.hold; }
      else if (key === "mode") b.mode = value || "tap";
      else if (value) b[key] = value;
      else delete b[key];
    });
  }

  return {
    BLOCKS: BLOCKS, ZONES: ZONES, PLACEHOLDER: PLACEHOLDER, MAX_ROWS: MAX_ROWS,
    allIds: allIds, uniqueId: uniqueId, uniquePageId: uniquePageId,
    blockSize: blockSize, newBlock: newBlock, hasPlaceholder: hasPlaceholder, buttonFromAction: buttonFromAction,
    actionName: actionName, presentSet: presentSet, isPresent: isPresent, filterActions: filterActions,
    overlapSet: overlapSet, freeSpot: freeSpot, nearestFree: nearestFree, cellAt: cellAt, cellStep: cellStep,
    unusedZone: unusedZone, placeFree: placeFree, addButton: addButton,
    arrange: arrange, toFree: toFree, setPageType: setPageType, setGrid: setGrid,
    toItems: toItems, applyItems: applyItems, area: area, arrangeState: arrangeState,
    moveBy: moveBy, alignCells: alignCells, distributeCells: distributeCells, sameSizeCells: sameSizeCells,
    resizeCells: resizeCells, selectInRect: selectInRect, duplicate: duplicate,
    ARTS: ARTS, artOf: artOf, convertArt: convertArt, carryKeys: carryKeys, codeName: codeName,
    newCapture: newCapture, captureEvent: captureEvent, normKey: normKey, sentKeys: sentKeys, duplicates: duplicates,
    kindOf: kindOf, isMapped: isMapped, metaText: metaText,
    applies: applies, commonFields: commonFields, setShared: setShared
  };
});
