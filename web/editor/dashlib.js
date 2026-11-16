"use strict";
// Reine Hilfen des Dashboard-Editors (ohne DOM): Felder aus dash_schema prüfen/umwandeln, Skalierung,
// neue Widgets, Einrasten beim Ziehen. Baut auf EditorCore (core.js) auf.
// Browser: window.DashLib, Node: module.exports (Tests: tests/js/dashlib.test.js).
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./core.js"));
  else root.DashLib = factory(root.EditorCore);
})(typeof self !== "undefined" ? self : this, function (Core) {
  function num(v) { return typeof v === "number" && isFinite(v); }
  function round2(v) { return Math.round(v * 100) / 100; }

  // ---------------------------------------------------------------- Beschriftungen
  var TYPE_LABELS = {
    value: "Wert", gauge: "Rundanzeige", bar: "Balken", line: "Verlauf", text: "Text", clock: "Uhr", date: "Datum",
    rect: "Rechteck", hline: "Linie", cores: "CPU-Kerne", fans: "Lüfter"
  };
  var FIELD_LABELS = {
    x: "X", y: "Y", w: "Breite", h: "Höhe", group: "Gruppe", sensor: "Sensor", label: "Beschriftung", unit: "Einheit",
    text: "Text", format: "Format", color: "Farbe", fill: "Füllung", stroke: "Rahmenfarbe", track: "Hintergrund (Spur)",
    label_color: "Farbe der Beschriftung", min: "Minimum", max: "Maximum", scale: "Faktor", gap: "Abstand",
    size: "Schriftgröße", thickness: "Dicke", stroke_width: "Rahmenbreite", seconds: "Zeitfenster (s)",
    decimals: "Nachkommastellen", font: "Schrift", align: "Ausrichtung", small_unit: "Einheit klein",
    zones: "Farbzonen", radius: "Rundung", area: "Fläche unter der Linie", ring: "Außenring", axis: "Achsenwerte",
    color_e: "Farbe E-Kerne", text_color: "Textfarbe", separator: "Trennlinie", label_size: "Größe der Beschriftung",
    columns: "Spalten", row_h: "Zeilenhöhe", weight: "Schriftstärke"
  };
  var ENUM_LABELS = {
    sans: "Sans (Text)", mono: "Mono (Zahlen)", head: "Überschrift",
    start: "Links", center: "Mitte", end: "Rechts"
  };
  var FIELD_HINTS = {
    group: "Elemente mit gleichem Namen bewegen sich gemeinsam",
    format: "z. B. HH:mm:ss, DD.MM.YYYY",
    scale: "Messwert × Faktor (z. B. 0,001 für MB -> GB)",
    min: "leer = Bereich des Sensors", max: "leer = Bereich des Sensors",
    weight: "100 bis 900", seconds: "5 bis 600"
  };

  // Standardgrößen und -inhalte neuer Widgets (Pixel im Dashboard)
  var TYPE_DEFAULTS = {
    value: { w: 200, h: 48, sensor: "cpu.load", label: "CPU", size: 24, color: "#E8ECF0", label_color: "#9AA6B2" },
    gauge: { w: 200, h: 200, sensor: "cpu.load", color: "#4FB3FF" },
    bar: { w: 300, h: 16, sensor: "cpu.load", color: "#4FB3FF", track: "#28313B" },
    line: { w: 360, h: 140, sensor: "cpu.load", seconds: 60, color: "#4FB3FF" },
    text: { w: 240, h: 40, text: "Text", size: 20, color: "#E8ECF0" },
    clock: { w: 160, h: 48, format: "HH:mm", size: 34, color: "#E8ECF0", align: "end" },
    date: { w: 200, h: 32, format: "DD.MM.YYYY", size: 15, color: "#9AA6B2", align: "end" },
    rect: { w: 240, h: 120, fill: "#1E242B", radius: 12 },
    hline: { w: 300, h: 8, color: "#2B343E", thickness: 2 },
    cores: { w: 560, h: 200 },
    fans: { w: 240, h: 240 }
  };

  // ---------------------------------------------------------------- Skalierung
  // Faktor, mit dem ein Dashboard (w x h) in die verfügbare Fläche passt (nie über max vergrößert).
  function fitScale(availW, availH, w, h, max) {
    if (!(availW > 0 && availH > 0 && w > 0 && h > 0)) return 1;
    return Math.min(availW / w, availH / h, max > 0 ? max : 2);
  }

  // ---------------------------------------------------------------- Dokument <-> Datei
  // Widgets bekommen im Editor eigene IDs (w1, w2, …); in der Datei gibt es keine.
  function toEditable(dash) {
    var d = JSON.parse(JSON.stringify(dash)), n = 0;
    d.widgets = (d.widgets || []).map(function (w) { w.id = "w" + (++n); return w; });
    return d;
  }
  function toSave(doc) {
    var d = JSON.parse(JSON.stringify(doc));
    d.widgets = d.widgets.map(function (w) {
      delete w.id;
      ["x", "y", "w", "h"].forEach(function (k) { if (num(w[k])) w[k] = round2(w[k]); });
      return w;
    });
    return d;
  }
  function nextId(widgets) {
    var n = 0;
    widgets.forEach(function (w) { var m = /^w(\d+)$/.exec(w.id); if (m) n = Math.max(n, parseInt(m[1], 10)); });
    return "w" + (n + 1);
  }

  // Neues Widget der Art type, mittig im Dashboard (aufs Raster gerastet). schema optional (für Pflichtfelder).
  function newWidget(type, canvas, step, widgets) {
    var def = TYPE_DEFAULTS[type] || { w: 200, h: 80 }, w = {}, k;
    for (k in def) w[k] = def[k];
    w.type = type;
    w.w = Math.min(w.w, canvas.width); w.h = Math.min(w.h, canvas.height);
    w.x = Math.max(0, Math.min(canvas.width - w.w, Core.snap((canvas.width - w.w) / 2, step)));
    w.y = Math.max(0, Math.min(canvas.height - w.h, Core.snap((canvas.height - w.h) / 2, step)));
    w.id = nextId(widgets || []);
    return w;
  }

  // Oberstes Widget, das den Punkt enthält (Array-Ende = vorn); null, wenn keins.
  function hitTest(widgets, x, y) {
    for (var i = widgets.length - 1; i >= 0; i--) {
      var w = widgets[i];
      if (x >= w.x && x <= w.x + w.w && y >= w.y && y <= w.y + w.h) return w;
    }
    return null;
  }

  function describe(w) {
    var d = w.label || w.text || w.sensor || w.format || "";
    return (TYPE_LABELS[w.type] || w.type) + (d ? " · " + String(d).slice(0, 28) : "");
  }

  // ---------------------------------------------------------------- Felder prüfen (spiegelt bridge/dashboard.py)
  function fullRe(src) { return new RegExp("^(?:" + src + ")$"); }

  function numberError(sp, v) {
    if (!num(v)) return "Zahl erwartet";
    if (sp.kind === "int" && Math.floor(v) !== v) return "ganze Zahl erwartet";
    if (sp.integral && Math.floor(v) !== v) return "ganze Zahl erwartet";
    if (sp.min != null && v < sp.min) return "mindestens " + sp.min;
    if (sp.max != null && v > sp.max) return "höchstens " + sp.max;
    if (sp.gt != null && v <= sp.gt) return "größer als " + sp.gt;
    if (sp.nonzero && v === 0) return "nicht 0";
    return null;
  }

  // Fehlertext oder null. schema = dash_schema.schema (für Sensor-/Farbmuster).
  function fieldError(sp, v, schema) {
    switch (sp.kind) {
      case "number": case "int": return numberError(sp, v);
      case "text":
        if (typeof v !== "string") return "Text erwartet";
        if (v.length > (sp.max_len || 200)) return "höchstens " + (sp.max_len || 200) + " Zeichen";
        if (sp.pattern && !fullRe(sp.pattern).test(v)) return "nur a-z, 0-9, _ und -";
        return null;
      case "sensor":
        return typeof v === "string" && fullRe(schema && schema.sensor_pattern || "[a-z0-9][a-z0-9_.]{0,63}").test(v)
          ? null : "ungültige Sensor-ID";
      case "color":
        return typeof v === "string" && v.length <= 60 && fullRe(schema && schema.color_pattern || "#[0-9a-fA-F]{6}").test(v)
          ? null : "Farbe wie #4FB3FF oder rgba(…)";
      case "bool": return typeof v === "boolean" ? null : "Ja oder Nein";
      case "enum": return sp.values.indexOf(v) >= 0 ? null : "ungültige Auswahl";
      case "zones":
        if (!Array.isArray(v) || v.length > (sp.max_items || 8)) return "höchstens " + (sp.max_items || 8) + " Zonen";
        for (var i = 0; i < v.length; i++) {
          var z = v[i];
          if (!z || !num(z.from) || z.from < 0 || z.from > 1) return "Zone " + (i + 1) + ": ab muss 0 bis 1 sein";
          if (fieldError({ kind: "color" }, z.color, schema)) return "Zone " + (i + 1) + ": ungültige Farbe";
          if (i && v[i - 1].from > z.from) return "Zonen müssen aufsteigend sein";
        }
        return null;
    }
    return null;
  }

  // Eingabetext -> {value} | {remove: true} (Feld leer, optional) | {error}
  function parseInput(sp, text, schema, required) {
    var t = String(text == null ? "" : text);
    var empty = sp.kind === "text" ? t === "" : t.trim() === "";
    if (empty) return required ? { error: "Pflichtfeld" } : { remove: true };
    var v = t;
    if (sp.kind === "number" || sp.kind === "int") {
      v = Number(t.trim().replace(",", "."));
      if (!isFinite(v)) return { error: "Zahl erwartet" };
    } else if (sp.kind !== "text") {
      v = t.trim();
    }
    var err = fieldError(sp, v, schema);
    return err ? { error: err } : { value: v };
  }

  // ---------------------------------------------------------------- Farbwähler
  // <input type=color> kennt nur #rrggbb.
  function colorToPicker(v) {
    var m = /^#([0-9a-fA-F]{3})[0-9a-fA-F]?$/.exec(v || "");
    if (m) return "#" + m[1].split("").map(function (c) { return c + c; }).join("").toLowerCase();
    m = /^#([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?$/.exec(v || "");
    return m ? "#" + m[1].toLowerCase() : "#000000";
  }
  // Gewählte Farbe; ein vorhandener Alpha-Wert (#rrggbbaa) bleibt erhalten.
  function pickerToColor(hex, prev) {
    var a = /^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})$/.exec(prev || "");
    return hex.toUpperCase() + (a ? a[1] : "");
  }

  // ---------------------------------------------------------------- Sensor-Auswahl
  // Alle Suchwörter müssen in ID oder Name vorkommen (ohne Groß-/Kleinschreibung).
  function filterSensors(list, query, limit) {
    var words = String(query || "").toLowerCase().split(/\s+/).filter(Boolean);
    var out = list.filter(function (s) {
      var hay = (s.id + " " + (s.name || "")).toLowerCase();
      return words.every(function (w) { return hay.indexOf(w) >= 0; });
    });
    return limit > 0 ? out.slice(0, limit) : out;
  }
  // Sensoren für die Auswahl gruppieren (nach dem ID-Präfix), damit niemand die IDs kennen muss.
  // Ergebnis: [{label, items:[…]}] in fester Reihenfolge, leere Gruppen fehlen, innerhalb nach Name sortiert
  // (Kerntakte nach Kernnummer).
  var SENSOR_GROUPS = [
    ["cpu.clock.", "Prozessor – Kerntakte"], ["cpu.", "Prozessor"], ["gpu.", "Grafikkarte"],
    ["ram.", "Arbeitsspeicher"], ["net.", "Netzwerk"], ["disk.", "Laufwerke"], ["fan.", "Lüfter (Mainboard)"],
    ["volt.", "Spannungen"], ["fps.", "Spiel (FPS)"], ["bridge.", "Spiel (FPS)"]
  ];
  var GROUP_ORDER = ["Prozessor", "Prozessor – Kerntakte", "Grafikkarte", "Arbeitsspeicher", "Netzwerk", "Laufwerke",
    "Lüfter (Mainboard)", "Spannungen", "Spiel (FPS)", "Sonstiges"];
  function sensorGroup(id) {
    if (isRaw(id)) return "Alle Werte";
    for (var i = 0; i < SENSOR_GROUPS.length; i++) if (String(id).indexOf(SENSOR_GROUPS[i][0]) === 0) return SENSOR_GROUPS[i][1];
    return "Sonstiges";
  }
  function coreKey(id) {   // cpu.clock.p7 / e11 / 3 -> sortierbar (P-Kerne vor E-Kernen, dann Nummer)
    var m = /^cpu\.clock\.([a-z]?)(\d+)$/.exec(id);
    return m ? [m[1] === "e" ? 1 : 0, +m[2]] : null;
  }
  // Rohwerte (lhm.*): eigene Gruppen „Alle Werte · <Bauteil>“ hinter den festen Gruppen, in Bauteil-Reihenfolge
  function isRaw(id) { return String(id).indexOf("lhm.") === 0; }
  function groupSensors(list) {
    var by = Object.create(null), rawOrder = [];
    (list || []).forEach(function (s) {
      var g = isRaw(s.id) ? "Alle Werte · " + (s.group || "LibreHardwareMonitor") : sensorGroup(s.id);
      if (isRaw(s.id) && !by[g]) rawOrder.push(g);
      (by[g] = by[g] || []).push(s);
    });
    return GROUP_ORDER.concat(rawOrder).filter(function (g) { return by[g]; }).map(function (g) {
      var items = by[g].slice().sort(function (a, b) {
        var ka = coreKey(a.id), kb = coreKey(b.id);
        if (ka && kb) return ka[0] - kb[0] || ka[1] - kb[1];
        if (isRaw(a.id)) return a.id.localeCompare(b.id, "en", { numeric: true });   // Rohwerte: nach Typ und Nummer
        return String(a.name || a.id).localeCompare(String(b.name || b.id), "de", { numeric: true });
      });
      return { label: g, items: items };
    });
  }
  function formatSensorValue(s) {
    if (!s || !num(s.value)) return "–";
    var d = Math.abs(s.value) >= 100 ? 0 : 1;
    return s.value.toLocaleString("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d, useGrouping: false }) +
      (s.unit ? " " + s.unit : "");
  }

  // ---------------------------------------------------------------- Ziehen mit Einrasten
  function snapEdge(v, step, targets, thr) {
    var best = null;
    targets.forEach(function (t) { var d = t - v; if (Math.abs(d) <= thr + 1e-6 && (best === null || Math.abs(d) < Math.abs(best))) best = d; });
    return best === null ? { v: Core.snap(v, step), guide: null } : { v: v + best, guide: v + best };
  }

  // Auswahl (auf Gruppen erweitert) um dx/dy verschieben; das Umgebende rastet an Raster und anderen Widgets ein.
  // Ergebnis {items, guides, dx, dy}.
  // exact = true: Gruppen nicht erweitern (Einzelelement in einer Gruppe).
  function snapMove(items, ids, dx, dy, step, thr, bounds, exact) {
    var sel = exact ? ids : Core.expandSelection(items, ids), mark = {};
    sel.forEach(function (i) { mark[i] = true; });
    var moving = items.filter(function (it) { return mark[it.id]; });
    if (!moving.length) return { items: items.slice(), guides: [], dx: 0, dy: 0 };
    var b = Core.boundsOf(moving);
    var r = Core.snapRect({ id: "__sel", x: b.x + dx, y: b.y + dy, w: b.w, h: b.h }, step,
      items.filter(function (it) { return !mark[it.id]; }), thr);
    var sx = r.rect.x - b.x, sy = r.rect.y - b.y;
    return { items: Core.move(items, ids, sx, sy, bounds, exact), guides: r.guides, dx: sx, dy: sy };
  }

  // Größe eines Widgets am Griff ändern (n, s, e, w, ne, …); bewegte Kanten rasten ein. Ergebnis {rect, guides}.
  function snapResize(item, handle, dx, dy, step, others, thr, min, bounds) {
    var h = String(handle), guides = [], l = item.x, t = item.y, r = item.x + item.w, b = item.y + item.h;
    var xs = [], ys = [];
    others.forEach(function (o) {
      if (o.id === item.id) return;
      xs.push(o.x, o.x + o.w / 2, o.x + o.w); ys.push(o.y, o.y + o.h / 2, o.y + o.h);
    });
    function edge(v, d, targets, axis) {
      var s = snapEdge(v + d, step, targets, thr);
      if (s.guide !== null) guides.push({ axis: axis, pos: s.guide });
      return s.v - v;
    }
    if (h.indexOf("w") >= 0) dx = edge(l, dx, xs, "x"); else if (h.indexOf("e") >= 0) dx = edge(r, dx, xs, "x");
    if (h.indexOf("n") >= 0) dy = edge(t, dy, ys, "y"); else if (h.indexOf("s") >= 0) dy = edge(b, dy, ys, "y");
    return { rect: Core.resize(item, h, dx, dy, min || { w: 2, h: 2 }, bounds), guides: guides };
  }

  // ---------------------------------------------------------------- Mehrfachauswahl
  // Feldnamen einer Widget-Art in Anzeigereihenfolge (aus dash_schema.types[art]); ältere Hubs ohne "sensor" in
  // der Feldliste bekommen ihn ergänzt, wenn er Pflicht ist.
  function fieldKeys(spec) {
    var keys = spec ? spec.fields.slice() : [], req = spec ? spec.required : [];
    if (req.indexOf("sensor") >= 0 && keys.indexOf("sensor") < 0) keys.splice(Math.min(keys.length, 5), 0, "sensor");
    return keys;
  }
  // Arten, die sich in der Mehrfachbearbeitung setzen lassen (Sensor und Zonen nur einzeln).
  var MULTI_KINDS = ["number", "int", "text", "color", "bool", "enum"];
  var NO_MULTI = ["x", "y", "w", "h", "group"];

  // Gemeinsame Felder der Widgets: [{key, required, mixed, value}] - nur Felder, die jede gewählte Art hat (und die
  // sich mehrfach setzen lassen). mixed = Werte unterscheiden sich (value dann undefined); Fehlen zählt als Wert.
  function commonFields(widgets, schema) {
    if (!widgets.length || !schema) return [];
    var specs = widgets.map(function (w) { return schema.types[w.type]; });
    if (specs.some(function (sp) { return !sp; })) return [];
    var keys = fieldKeys(specs[0]).filter(function (k) {
      if (NO_MULTI.indexOf(k) >= 0) return false;
      var f = schema.fields[k];
      if (!f || MULTI_KINDS.indexOf(f.kind) < 0) return false;
      return specs.every(function (sp) { return fieldKeys(sp).indexOf(k) >= 0; });
    });
    return keys.map(function (k) {
      var first = widgets[0][k], same = widgets.every(function (w) { return JSON.stringify(w[k]) === JSON.stringify(first); });
      return { key: k, required: specs.every(function (sp) { return sp.required.indexOf(k) >= 0; }),
        mixed: !same, value: same ? first : undefined };
    });
  }
  // Setzt ein Feld bei den Widgets mit den IDs (value undefined: Feld entfernen). Neue Liste.
  function setField(widgets, ids, key, value) {
    var m = {};
    ids.forEach(function (i) { m[i] = true; });
    return widgets.map(function (w) {
      var c = {}, k;
      for (k in w) c[k] = w[k];
      if (m[w.id]) { if (value === undefined) delete c[key]; else c[key] = value; }
      return c;
    });
  }

  // Welche Anordnen-Werkzeuge sinnvoll sind. solo = ein Einzelelement innerhalb einer Gruppe.
  function arrangeState(items, ids, solo) {
    var sel = solo ? ids.slice() : Core.expandSelection(items, ids), mark = {};
    sel.forEach(function (i) { mark[i] = true; });
    var chosen = items.filter(function (it) { return mark[it.id]; });
    var us = Core.units(items, sel, solo);
    var groups = Object.create(null), grouped = 0;
    chosen.forEach(function (it) { if (it.group) { groups[it.group] = true; grouped++; } });
    return {
      align: us.length >= 1,                                       // eine Einheit: an der Fläche
      distribute: us.length >= 3,
      sameSize: chosen.length >= 2 && grouped === 0,               // Gruppen werden nicht skaliert
      group: !solo && chosen.length >= 2 && !(Object.keys(groups).length === 1 && grouped === chosen.length),
      ungroup: grouped > 0
    };
  }

  // Zeilen der Elementliste (oben nach unten): vor dem ersten Mitglied einer Gruppe eine Kopfzeile, danach alle
  // Mitglieder (eingerückt). [{kind: "group", group, count} | {kind: "item", w, grouped}]
  function listRows(widgets) {
    var rows = [], done = Object.create(null);
    for (var i = widgets.length - 1; i >= 0; i--) {
      var w = widgets[i];
      if (!w.group) { rows.push({ kind: "item", w: w, grouped: false }); continue; }
      if (done[w.group]) continue;
      done[w.group] = true;
      var mem = widgets.filter(function (x) { return x.group === w.group; }).reverse();
      rows.push({ kind: "group", group: w.group, count: mem.length });
      mem.forEach(function (x) { rows.push({ kind: "item", w: x, grouped: true }); });
    }
    return rows;
  }

  return {
    fieldKeys: fieldKeys, commonFields: commonFields, setField: setField, arrangeState: arrangeState, listRows: listRows,
    TYPE_LABELS: TYPE_LABELS, FIELD_LABELS: FIELD_LABELS, ENUM_LABELS: ENUM_LABELS, FIELD_HINTS: FIELD_HINTS,
    TYPE_DEFAULTS: TYPE_DEFAULTS, fitScale: fitScale, toEditable: toEditable, toSave: toSave, nextId: nextId,
    newWidget: newWidget, hitTest: hitTest, describe: describe, fieldError: fieldError, parseInput: parseInput,
    colorToPicker: colorToPicker, pickerToColor: pickerToColor, filterSensors: filterSensors, groupSensors: groupSensors, sensorGroup: sensorGroup,
    formatSensorValue: formatSensorValue, snapMove: snapMove, snapResize: snapResize
  };
});
