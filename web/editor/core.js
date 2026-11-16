"use strict";
// Gemeinsamer Editor-Kern (Panel- und Dashboard-Editor): reine Funktionen ohne DOM.
// Elemente sind Rechtecke {id, x, y, w, h, group?}. Die Einheit ist egal (Pixel beim Dashboard, Zellen beim
// Panel). Die Reihenfolge im Array ist die Zeichenreihenfolge (hinten -> vorn).
// Alle Funktionen geben neue Arrays/Objekte zurück und verändern ihre Eingaben nicht.
// Browser: window.EditorCore, Node: module.exports (Tests: tests/js/editor_core.test.js).
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.EditorCore = factory();
})(typeof self !== "undefined" ? self : this, function () {
  var EPS = 1e-6;

  function copy(o) { var c = {}; for (var k in o) c[k] = o[k]; return c; }
  function toSet(ids) { var s = Object.create(null); (ids || []).forEach(function (i) { s[i] = true; }); return s; }
  function num(v, d) { return typeof v === "number" && isFinite(v) ? v : d; }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  // ---------------------------------------------------------------- Raster und Einrasten
  // Rundet auf das nächste Vielfache von step (step <= 0 oder ungültig: unverändert).
  function snap(value, step) {
    if (!(step > 0)) return value;
    return Math.round(value / step) * step;
  }

  // Rastet ein Rechteck ein: pro Achse zuerst an Kanten/Mitten der anderen Rechtecke (Abstand <= threshold,
  // der nächste gewinnt), sonst ans Raster (Ecke links/oben). Liefert {rect, guides}; ein Hilfslinien-Eintrag
  // {axis: "x"|"y", pos} ist eine senkrechte (x) bzw. waagrechte (y) Linie an der Position pos.
  function snapRect(rect, step, others, threshold) {
    var r = copy(rect), thr = num(threshold, 0), guides = [];
    var list = (others || []).filter(function (o) { return o.id !== rect.id; });
    [["x", "x", "w"], ["y", "y", "h"]].forEach(function (a) {
      var axis = a[0], pos = a[1], size = a[2];
      var mine = [0, r[size] / 2, r[size]];            // links/Mitte/rechts relativ zur Position
      var targets = [];
      list.forEach(function (o) { targets.push(o[pos], o[pos] + o[size] / 2, o[pos] + o[size]); });
      var best = null;
      mine.forEach(function (off) {
        targets.forEach(function (t) {
          var d = t - (r[pos] + off);
          if (Math.abs(d) <= thr + EPS && (best === null || Math.abs(d) < Math.abs(best))) best = d;
        });
      });
      if (best !== null) r[pos] += best; else r[pos] = snap(r[pos], step);
      // Hilfslinien: alles, was nach dem Einrasten genau fluchtet
      mine.forEach(function (off) {
        targets.forEach(function (t) {
          if (Math.abs(t - (r[pos] + off)) < EPS && !guides.some(function (g) { return g.axis === axis && Math.abs(g.pos - t) < EPS; }))
            guides.push({ axis: axis, pos: t });
        });
      });
    });
    return { rect: r, guides: guides };
  }

  // ---------------------------------------------------------------- Gruppen
  function groupId(items) {
    var n = 0;
    items.forEach(function (it) {
      var m = typeof it.group === "string" && /^g(\d+)$/.exec(it.group);
      if (m) n = Math.max(n, parseInt(m[1], 10));
    });
    return "g" + (n + 1);
  }

  // Auswahl eines Mitglieds = ganze Gruppe. Ergebnis in Array-Reihenfolge, ohne Doppelte.
  function expandSelection(items, ids) {
    var sel = toSet(ids), groups = {};
    items.forEach(function (it) { if (sel[it.id] && it.group) groups[it.group] = true; });
    return items.filter(function (it) { return sel[it.id] || (it.group && groups[it.group]); })
      .map(function (it) { return it.id; });
  }

  // Fasst die (auf Gruppen erweiterte) Auswahl zu einer neuen Gruppe zusammen; weniger als 2 Elemente: unverändert.
  function group(items, ids) {
    var sel = toSet(expandSelection(items, ids));
    if (Object.keys(sel).length < 2) return items.map(copy);
    var g = groupId(items);
    return items.map(function (it) { var c = copy(it); if (sel[it.id]) c.group = g; return c; });
  }

  function ungroup(items, ids) {
    var sel = toSet(expandSelection(items, ids));
    return items.map(function (it) { var c = copy(it); if (sel[it.id]) delete c.group; return c; });
  }

  // ---------------------------------------------------------------- Maße
  // Umgebendes Rechteck {x, y, w, h} der Elemente (leer: null).
  function boundsOf(items) {
    if (!items.length) return null;
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    items.forEach(function (it) {
      x0 = Math.min(x0, it.x); y0 = Math.min(y0, it.y);
      x1 = Math.max(x1, it.x + it.w); y1 = Math.max(y1, it.y + it.h);
    });
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }

  // ---------------------------------------------------------------- Bewegen und Größe
  // Verschiebt die Auswahl (Gruppen gemeinsam) um dx/dy. bounds {w,h} (optional): die Auswahl bleibt als Ganzes
  // innerhalb der Fläche; die Verschiebung wird dafür begrenzt, die Anordnung untereinander bleibt erhalten.
  function move(items, ids, dx, dy, bounds) {
    var sel = toSet(expandSelection(items, ids)), moving = items.filter(function (it) { return sel[it.id]; });
    if (!moving.length) return items.map(copy);
    dx = num(dx, 0); dy = num(dy, 0);
    if (bounds) {
      var b = boundsOf(moving);
      dx = clamp(dx, -b.x, Math.max(-b.x, bounds.w - b.x - b.w));
      dy = clamp(dy, -b.y, Math.max(-b.y, bounds.h - b.y - b.h));
    }
    return items.map(function (it) {
      var c = copy(it);
      if (sel[it.id]) { c.x = it.x + dx; c.y = it.y + dy; }
      return c;
    });
  }

  // Größe ändern an einem Griff: n, s, e, w, ne, nw, se, sw. min {w,h} (Standard 1×1), bounds {w,h} optional.
  function resize(item, handle, dx, dy, min, bounds) {
    var mw = num(min && min.w, 1), mh = num(min && min.h, 1);
    var loX = bounds ? 0 : -Infinity, hiX = bounds ? bounds.w : Infinity;
    var loY = bounds ? 0 : -Infinity, hiY = bounds ? bounds.h : Infinity;
    var l = item.x, t = item.y, r = item.x + item.w, b = item.y + item.h;
    var h = String(handle || "");
    dx = num(dx, 0); dy = num(dy, 0);
    if (h.indexOf("w") >= 0) l = clamp(l + dx, loX, Math.max(loX, r - mw));
    if (h.indexOf("e") >= 0) r = clamp(r + dx, Math.min(hiX, l + mw), hiX);
    if (h.indexOf("n") >= 0) t = clamp(t + dy, loY, Math.max(loY, b - mh));
    if (h.indexOf("s") >= 0) b = clamp(b + dy, Math.min(hiY, t + mh), hiY);
    var c = copy(item);
    c.x = l; c.y = t; c.w = r - l; c.h = b - t;
    return c;
  }

  // ---------------------------------------------------------------- Ausrichten, Verteilen, gleiche Größe
  // Hier wirkt genau die übergebene Auswahl (nicht auf Gruppen erweitert); der Aufrufer erweitert bei Bedarf.
  function pick(items, ids) { var s = toSet(ids); return items.filter(function (it) { return s[it.id]; }); }

  // mode: left | hcenter | right | top | vcenter | bottom - Bezug ist das Umgebende der Auswahl.
  function align(items, ids, mode) {
    var sel = pick(items, ids);
    if (sel.length < 2) return items.map(copy);
    var b = boundsOf(sel), s = toSet(ids);
    return items.map(function (it) {
      var c = copy(it);
      if (!s[it.id]) return c;
      if (mode === "left") c.x = b.x;
      else if (mode === "hcenter") c.x = b.x + (b.w - it.w) / 2;
      else if (mode === "right") c.x = b.x + b.w - it.w;
      else if (mode === "top") c.y = b.y;
      else if (mode === "vcenter") c.y = b.y + (b.h - it.h) / 2;
      else if (mode === "bottom") c.y = b.y + b.h - it.h;
      return c;
    });
  }

  // Gleiche Lücken zwischen den Elementen innerhalb ihrer gemeinsamen Ausdehnung (vom linkesten Anfang bis zum
  // rechtesten Ende). Ab 3 Elementen.
  // axis: "x"/"h" (waagrecht) oder "y"/"v" (senkrecht).
  function distribute(items, ids, axis) {
    var sel = pick(items, ids);
    if (sel.length < 3) return items.map(copy);
    var horiz = axis === "x" || axis === "h", pos = horiz ? "x" : "y", size = horiz ? "w" : "h";
    var order = sel.slice().sort(function (a, b) { return (a[pos] - b[pos]) || (a[size] - b[size]); });
    var start = Infinity, end = -Infinity, used = 0;
    order.forEach(function (it) {
      start = Math.min(start, it[pos]); end = Math.max(end, it[pos] + it[size]); used += it[size];
    });
    var gap = (end - start - used) / (order.length - 1), at = start, np = Object.create(null);
    order.forEach(function (it) { np[it.id] = at; at += it[size] + gap; });
    return items.map(function (it) {
      var c = copy(it);
      if (it.id in np) c[pos] = np[it.id];
      return c;
    });
  }

  // Alle auf die Breite/Höhe des ersten gewählten Elements (Array-Reihenfolge). dim: "w" | "h" | "both".
  function sameSize(items, ids, dim) {
    var sel = pick(items, ids);
    if (sel.length < 2) return items.map(copy);
    var ref = sel[0], s = toSet(ids);
    return items.map(function (it) {
      var c = copy(it);
      if (s[it.id]) {
        if (dim === "w" || dim === "both") c.w = ref.w;
        if (dim === "h" || dim === "both") c.h = ref.h;
      }
      return c;
    });
  }

  // ---------------------------------------------------------------- Ebenen (Reihenfolge im Array)
  // Die Auswahl wird auf Gruppen erweitert, ihre Reihenfolge untereinander bleibt erhalten.
  function layerSet(items, ids) { return toSet(expandSelection(items, ids)); }

  function bringForward(items, ids) {
    var s = layerSet(items, ids), out = items.map(copy);
    for (var i = out.length - 2; i >= 0; i--)
      if (s[out[i].id] && !s[out[i + 1].id]) { var t = out[i]; out[i] = out[i + 1]; out[i + 1] = t; }
    return out;
  }
  function sendBackward(items, ids) {
    var s = layerSet(items, ids), out = items.map(copy);
    for (var i = 1; i < out.length; i++)
      if (s[out[i].id] && !s[out[i - 1].id]) { var t = out[i]; out[i] = out[i - 1]; out[i - 1] = t; }
    return out;
  }
  function toFront(items, ids) {
    var s = layerSet(items, ids);
    return items.filter(function (it) { return !s[it.id]; }).concat(items.filter(function (it) { return s[it.id]; })).map(copy);
  }
  function toBack(items, ids) {
    var s = layerSet(items, ids);
    return items.filter(function (it) { return s[it.id]; }).concat(items.filter(function (it) { return !s[it.id]; })).map(copy);
  }

  // ---------------------------------------------------------------- Rahmenauswahl
  // IDs aller Elemente, die den Rahmen {x,y,w,h} berühren (mit Fläche überlappen), auf Gruppen erweitert.
  function selectInRect(items, rect) {
    if (!rect) return [];
    var x0 = Math.min(rect.x, rect.x + rect.w), x1 = Math.max(rect.x, rect.x + rect.w);
    var y0 = Math.min(rect.y, rect.y + rect.h), y1 = Math.max(rect.y, rect.y + rect.h);
    var hit = items.filter(function (it) {
      return it.x < x1 && x0 < it.x + it.w && it.y < y1 && y0 < it.y + it.h;
    }).map(function (it) { return it.id; });
    return expandSelection(items, hit);
  }

  // ---------------------------------------------------------------- Rückgängig / Wiederholen
  // push(zustand) legt den neuen Zustand ab (JSON-serialisierbar, wird als Text tief kopiert). Der erste push ist
  // der Ausgangszustand. undo()/redo() liefern den Zustand (frische Kopie) oder null, wenn es nicht geht.
  function History(limit) {
    this.limit = limit > 1 ? Math.floor(limit) : 100;
    this.stack = []; this.idx = -1;
  }
  History.prototype.push = function (snapshot) {
    var s = JSON.stringify(snapshot);
    if (this.idx >= 0 && this.stack[this.idx] === s) return false;   // keine Änderung
    this.stack.length = this.idx + 1;                                  // Wiederholen-Zweig verwerfen
    this.stack.push(s);
    if (this.stack.length > this.limit) this.stack.shift();
    this.idx = this.stack.length - 1;
    return true;
  };
  History.prototype.canUndo = function () { return this.idx > 0; };
  History.prototype.canRedo = function () { return this.idx >= 0 && this.idx < this.stack.length - 1; };
  History.prototype.undo = function () { return this.canUndo() ? JSON.parse(this.stack[--this.idx]) : null; };
  History.prototype.redo = function () { return this.canRedo() ? JSON.parse(this.stack[++this.idx]) : null; };
  History.prototype.clear = function () { this.stack = []; this.idx = -1; };

  // ---------------------------------------------------------------- Kopieren / Duplizieren
  // Kopiert die (auf Gruppen erweiterte) Auswahl, versetzt um offset {x,y}, mit neuen IDs. newId(item, items)
  // liefert eine freie ID (items = Liste inkl. bereits erzeugter Kopien). Gruppen bleiben als neue Gruppen erhalten.
  // Ergebnis {items, ids}: items mit den Kopien oben drauf (am Ende), ids = die neuen IDs.
  function freeId(base, list) {
    var used = Object.create(null);
    list.forEach(function (it) { used[it.id] = true; });
    if (!used[base]) return base;
    for (var n = 2; ; n++) if (!used[base + "_" + n]) return base + "_" + n;
  }

  function duplicate(items, ids, offset, newId) {
    var sel = toSet(expandSelection(items, ids)), src = items.filter(function (it) { return sel[it.id]; });
    if (!src.length) return { items: items.map(copy), ids: [] };
    var ox = num(offset && offset.x, 0), oy = num(offset && offset.y, 0);
    var out = items.map(copy), newIds = [], gmap = Object.create(null);   // Gruppe "constructor" o. Ä.
    src.forEach(function (it) {
      var c = copy(it), id = typeof newId === "function" ? newId(it, out) : freeId(it.id + "_kopie", out);
      c.id = id; c.x = it.x + ox; c.y = it.y + oy;
      if (it.group) {
        // groupId(out) sieht die bereits eingefügten Kopien: zwei Gruppen im selben Duplikat bekommen
        // verschiedene neue IDs, weil out.push(c) vor der nächsten Abfrage passiert
        if (!gmap[it.group]) { gmap[it.group] = groupId(out); }
        c.group = gmap[it.group];
      }
      out.push(c); newIds.push(id);
    });
    return { items: out, ids: newIds };
  }

  return {
    snap: snap, snapRect: snapRect, boundsOf: boundsOf, move: move, resize: resize,
    align: align, distribute: distribute, sameSize: sameSize,
    group: group, ungroup: ungroup, expandSelection: expandSelection,
    bringForward: bringForward, sendBackward: sendBackward, toFront: toFront, toBack: toBack,
    selectInRect: selectInRect, History: History, duplicate: duplicate
  };
});
