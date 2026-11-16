"use strict";
// PC-Werte: zeichnet ein Dashboard (GET /api/dashboards/<name>, Format: docs/sensors.md) als SVG und füllt es
// mit den Werten, die der Hub über /ws schickt ({"t":"stats", values, meta, sources}).
// Die Zeichen- und Rechenfunktionen hängen nicht am Netz (window.StatsView), damit sie einzeln prüfbar sind.
window.StatsView = (function () {
  var NS = "http://www.w3.org/2000/svg";
  var FONTS = { sans: "var(--fb)", mono: "var(--fm)", head: "var(--fh)" };
  var STALE_MS = 4000;                 // länger keine Werte: Anzeige "–"
  var SWEEP = 240;                     // Zeigerbogen in Grad (wie MoBro: von links unten über oben nach rechts unten)
  var DASH = "–";

  // ---------- Rechnen und Formatieren (rein) ----------
  function num(v) { return typeof v === "number" && isFinite(v); }

  function formatNumber(v, decimals) {
    if (decimals == null) decimals = Math.abs(v) >= 100 ? 0 : 1;
    return v.toLocaleString("de-DE", { minimumFractionDigits: decimals, maximumFractionDigits: decimals, useGrouping: false });
  }

  // Anzeigewert eines Widgets: {text, unit, raw} oder null (fehlt/veraltet)
  function reading(w, values, meta) {
    var v = values ? values[w.sensor] : undefined;
    if (!num(v)) return null;
    var shown = v * (num(w.scale) ? w.scale : 1);
    var unit = w.unit != null ? w.unit : ((meta && meta[w.sensor] && meta[w.sensor].unit) || "");
    return { text: formatNumber(shown, w.decimals), unit: unit, raw: v };
  }

  // Bereich eines Widgets: eigene Angabe, sonst die des Sensors (meta), sonst 0..100
  function range(w, meta) {
    var m = (meta && meta[w.sensor]) || {};
    var lo = num(w.min) ? w.min : (num(m.min) ? m.min : 0);
    var hi = num(w.max) ? w.max : (num(m.max) ? m.max : 100);
    return hi > lo ? [lo, hi] : [lo, lo + 1];
  }

  function fraction(v, lo, hi) { return Math.max(0, Math.min(1, (v - lo) / (hi - lo))); }

  function pad2(n) { return (n < 10 ? "0" : "") + n; }
  function formatTime(fmt, d) {
    return fmt.replace(/YYYY|MM|DD|HH|mm|ss/g, function (t) {
      switch (t) {
        case "YYYY": return String(d.getFullYear());
        case "MM": return pad2(d.getMonth() + 1);
        case "DD": return pad2(d.getDate());
        case "HH": return pad2(d.getHours());
        case "mm": return pad2(d.getMinutes());
        default: return pad2(d.getSeconds());
      }
    });
  }

  // Punkt auf dem Kreis; Winkel in Grad, 0 = oben, im Uhrzeigersinn
  function polar(cx, cy, r, deg) {
    var a = deg * Math.PI / 180;
    return [cx + r * Math.sin(a), cy - r * Math.cos(a)];
  }
  // Bogen von Anteil f0 bis f1 (0..1 des Zeigerbogens) als SVG-Pfad; leer, wenn es nichts zu zeichnen gibt
  function arcPath(cx, cy, r, f0, f1) {
    if (!(f1 > f0)) return "";
    var a0 = -SWEEP / 2 + SWEEP * f0, a1 = -SWEEP / 2 + SWEEP * f1;
    var p0 = polar(cx, cy, r, a0), p1 = polar(cx, cy, r, a1);
    return "M" + p0[0].toFixed(2) + " " + p0[1].toFixed(2) + " A" + r.toFixed(2) + " " + r.toFixed(2) + " 0 " +
      (a1 - a0 > 180 ? 1 : 0) + " 1 " + p1[0].toFixed(2) + " " + p1[1].toFixed(2);
  }

  // Linienverlauf: points = [[t, v], …] (t in ms); Fenster = letzte `seconds` bis `now`
  function linePoints(points, now, seconds, box, lo, hi) {
    var t0 = now - seconds * 1000, out = [];
    for (var i = 0; i < points.length; i++) {
      var p = points[i];
      if (p[0] < t0) continue;
      var x = box.x + box.w * (p[0] - t0) / (seconds * 1000);
      var y = box.y + box.h * (1 - fraction(p[1], lo, hi));
      out.push(x.toFixed(1) + "," + y.toFixed(1));
    }
    return out.join(" ");
  }

  // ---------- Zeichnen ----------
  function el(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function textEl(parent, w, extra) {
    var size = num(w.size) ? w.size : 16;
    var align = w.align || "start";
    var x = align === "center" ? w.x + w.w / 2 : align === "end" ? w.x + w.w : w.x;
    var t = el("text", {
      x: x, y: w.y + w.h / 2, "dominant-baseline": "central", fill: w.color || "#fff", "font-size": size,
      "text-anchor": align === "center" ? "middle" : align === "end" ? "end" : "start",
      style: "font-family:" + (FONTS[w.font] || FONTS.sans)
    }, parent);
    for (var k in extra) t.setAttribute(k, extra[k]);
    return t;
  }

  // Jedes Widget liefert ein Objekt { update(ctx) } (ctx: values, meta, hist, now, stale) oder nur statische Teile.
  var builders = {
    rect: function (w, g) {
      var sw = num(w.stroke_width) ? w.stroke_width : 0;
      el("rect", { x: w.x + sw / 2, y: w.y + sw / 2, width: Math.max(0, w.w - sw), height: Math.max(0, w.h - sw),
        rx: num(w.radius) ? w.radius : null,
        fill: w.fill || "none", stroke: sw ? (w.stroke || "none") : "none", "stroke-width": sw }, g);
    },
    hline: function (w, g) {
      var th = num(w.thickness) ? w.thickness : 2;
      el("rect", { x: w.x, y: w.y + (w.h - th) / 2, width: w.w, height: th, fill: w.color || "#fff" }, g);
    },
    text: function (w, g) {
      textEl(g, w, num(w.weight) ? { "font-weight": w.weight } : {}).textContent = w.text;
    },
    clock: function (w, g) {
      var t = textEl(g, Object.assign({ align: "center" }, w), { "font-weight": 700 });
      return { tick: function (now) { t.textContent = formatTime(w.format || "HH:mm:ss", new Date(now)); } };
    },
    date: function (w, g) {
      var t = textEl(g, Object.assign({ align: "center" }, w), {});
      return { tick: function (now) { t.textContent = formatTime(w.format || "DD-MM-YYYY", new Date(now)); } };
    },
    value: function (w, g) {
      var t = textEl(g, w, {});
      var size = num(w.size) ? w.size : 16;
      var label = null;
      var weight = num(w.weight) ? w.weight : 700;
      if (w.label) {
        label = el("tspan", { fill: w.label_color || null }, t);
        label.textContent = w.label;
      }
      var val = el("tspan", { "font-weight": weight }, t);
      if (label && num(w.gap)) val.setAttribute("dx", w.gap);
      var unit = el("tspan", { "font-weight": weight }, t);
      if (w.small_unit) {
        unit.setAttribute("font-size", Math.round(size * 0.6));
        unit.setAttribute("font-weight", 500);
        if (w.label_color) unit.setAttribute("fill", w.label_color);
        unit.setAttribute("dx", Math.round(size * 0.12));
      }
      return {
        update: function (c) {
          var r = c.stale ? null : reading(w, c.values, c.meta);
          val.textContent = r ? r.text : DASH;
          unit.textContent = r ? r.unit : "";
        }
      };
    },
    bar: function (w, g) {
      var br = num(w.radius) ? w.radius : 2;
      el("rect", { x: w.x, y: w.y, width: w.w, height: w.h, rx: br, fill: w.track || "#1d1e22" }, g);
      var fill = el("rect", { x: w.x, y: w.y, width: 0, height: w.h, rx: br, fill: w.color || "#00c0bc" }, g);
      return {
        update: function (c) {
          var r = c.stale ? null : reading(w, c.values, c.meta);
          var rg = range(w, c.meta);
          fill.setAttribute("width", r ? (w.w * fraction(r.raw, rg[0], rg[1])).toFixed(1) : 0);
        }
      };
    },
    gauge: function (w, g) {
      var cx = w.x + w.w / 2, cy = w.y + w.h / 2;
      var th = num(w.thickness) ? w.thickness : Math.min(w.w, w.h) * 0.09;
      var rOuter = Math.min(w.w, w.h) / 2 - 3;
      var rMain = rOuter - th * 0.5 - 7;
      var zones = Array.isArray(w.zones) ? w.zones : [];
      var base = w.color || "#00c0bc";
      // dünner Außenring: Grundfarbe, ab den Zonen deren Farben (sofern die Skala feste Grenzen hat)
      var stops = [0].concat(zones.map(function (z) { return z.from; })).concat([1]);
      var cols = [base].concat(zones.map(function (z) { return z.color; }));
      var ring = w.ring !== false;
      if (!ring) rMain = Math.min(w.w, w.h) / 2 - th / 2 - 2;
      for (var i = 0; ring && i < cols.length; i++) {
        el("path", { d: arcPath(cx, cy, rOuter, stops[i], stops[i + 1]), fill: "none", stroke: cols[i], "stroke-width": 3 }, g);
      }
      el("path", { d: arcPath(cx, cy, rMain, 0, 1), fill: "none", stroke: w.track || "#1d1e22", "stroke-width": th,
        "stroke-linecap": "round" }, g);
      var arc = el("path", { d: "", fill: "none", stroke: base, "stroke-width": th, "stroke-linecap": "round" }, g);
      return {
        update: function (c) {
          var r = c.stale ? null : reading(w, c.values, c.meta);
          var rg = range(w, c.meta);
          var f = r ? fraction(r.raw, rg[0], rg[1]) : 0;
          arc.setAttribute("d", r ? arcPath(cx, cy, rMain, 0, f) : "");
          if (!ring) {          // ohne Außenring zeigt der Bogen selbst die Zone des aktuellen Werts
            var col = base;
            zones.forEach(function (z) { if (f >= z.from) col = z.color; });
            arc.setAttribute("stroke", col);
          }
        }
      };
    },
    // Kerntakte: Raster aller vorhandenen cpu.clock.<n>. Die Zahl der Kerne ist je PC verschieden, darum werden
    // die Zellen erst beim ersten Wert gebaut und neu, sobald sich die ID-Liste ändert.
    cores: function (w, g) {
      var grp = el("g", {}, g), key = null, cells = [];
      var size = num(w.size) ? w.size : 15, lsize = num(w.label_size) ? w.label_size : 12;
      var th = Math.round(size * 1.33), barY = th + 6, barH = 5, gap = num(w.gap) ? w.gap : 10;
      var rowH = num(w.row_h) ? w.row_h : 52, extent = barY + barH;
      var lo = num(w.min) ? w.min : 0, hi = num(w.max) && w.max > lo ? w.max : 5500;
      function ids(values) {
        var keys = Object.keys(values || {});
        var gen = keys.filter(function (k) { return /^cpu\.clock\.\d+$/.test(k); });
        if (!gen.length) {
          // älterer Sensor-Helfer: nur die festen IDs cpu.clock.p0…/e8… (P-Kerne vor E-Kernen)
          gen = keys.filter(function (k) { return /^cpu\.clock\.[pe]\d+$/.test(k); });
          return gen.sort(function (a, b) {
            return (a.charAt(10) === b.charAt(10)) ? Number(a.slice(11)) - Number(b.slice(11)) : (a.charAt(10) === "p" ? -1 : 1);
          });
        }
        return gen.sort(function (a, b) { return Number(a.slice(10)) - Number(b.slice(10)); });
      }
      function short(name, id) {      // "P-Kern 3" -> "P3", "E-Kern 8" -> "E8", "Kern 0" -> "K0"
        var m = /^([PE])-Kern (\d+)$/.exec(name || "") || /^(K)ern (\d+)$/.exec(name || "");
        if (m) return m[1] + m[2];
        var f = /^cpu\.clock\.([pe])(\d+)$/.exec(id);              // feste ID: p0 -> P0, e8 -> E8
        return f ? f[1].toUpperCase() + f[2] : (name || id.slice(10));
      }
      function layout(list) {
        while (grp.firstChild) grp.removeChild(grp.firstChild);
        cells = [];
        var n = list.length, cols = Math.max(1, Math.min(16, Math.floor(num(w.columns) ? w.columns : 6)));
        while (cols < 16 && cols < n && (Math.ceil(n / cols) - 1) * rowH + extent > w.h) cols++;
        var cw = Math.max(1, (w.w - (cols - 1) * gap) / cols);
        var rows = Math.max(1, Math.floor((w.h - extent) / rowH) + 1);
        list.slice(0, cols * rows).forEach(function (id, i) {
          var cx = w.x + (i % cols) * (cw + gap), cy = w.y + Math.floor(i / cols) * rowH;
          var lab = textEl(grp, { x: cx, y: cy, w: cw, h: th, size: lsize, color: w.label_color || "#9aa6b2",
            font: "sans" }, {});
          var val = textEl(grp, { x: cx, y: cy, w: cw, h: th, size: size, color: w.text_color || "#fff", font: "head",
            align: "end" }, { "font-weight": num(w.weight) ? w.weight : 600 });
          el("rect", { x: cx, y: cy + barY, width: cw, height: barH, rx: barH / 2, fill: w.track || "#28313b" }, grp);
          var fill = el("rect", { x: cx, y: cy + barY, width: 0, height: barH, rx: barH / 2,
            fill: w.color || "#4fb3ff" }, grp);
          cells.push({ id: id, lab: lab, val: val, fill: fill, cw: cw });
        });
      }
      return {
        update: function (c) {
          var list = ids(c.values), k = list.join(",");
          if (k !== key) { key = k; layout(list); }
          cells.forEach(function (cell) {
            var nm = c.meta && c.meta[cell.id] && c.meta[cell.id].name;
            var rd = c.stale ? null : reading({ sensor: cell.id, scale: w.scale, decimals: w.decimals,
              unit: w.unit == null ? "" : w.unit }, c.values, c.meta);
            cell.lab.textContent = short(nm, cell.id);
            cell.val.textContent = rd ? rd.text + (rd.unit ? " " + rd.unit : "") : DASH;
            cell.fill.setAttribute("width", rd ? (cell.cw * fraction(rd.raw, lo, hi)).toFixed(1) : 0);
            cell.fill.setAttribute("fill", /^E-/.test(nm || "") && w.color_e ? w.color_e : (w.color || "#4fb3ff"));
          });
        }
      };
    },
    // Lüfter: Liste aller vorhandenen fan.* (Name aus meta), dünne Trennlinie zwischen den Zeilen
    fans: function (w, g) {
      var grp = el("g", {}, g), key = null, rows = [];
      var size = num(w.size) ? w.size : 18, lsize = num(w.label_size) ? w.label_size : 13;
      var vh = size + 8, base = num(w.row_h) ? w.row_h : 48, unit = w.unit == null ? "U/min" : w.unit;
      function ids(values) {
        return Object.keys(values || {}).filter(function (k) { return /^fan\.[a-z0-9_]+$/.test(k); });
      }
      function layout(list) {
        while (grp.firstChild) grp.removeChild(grp.firstChild);
        rows = [];
        var rowH = base;
        if (list.length * rowH > w.h + 1) rowH = Math.max(vh + 4, w.h / list.length);   // viele Lüfter: enger
        var cap = Math.max(1, Math.floor((w.h + 1) / rowH));
        list.slice(0, cap).forEach(function (id, i, part) {
          var ry = w.y + i * rowH;
          var lab = textEl(grp, { x: w.x, y: ry + 4, w: w.w, h: 18, size: lsize, color: w.label_color || "#9aa6b2",
            font: "sans" }, {});
          var val = textEl(grp, { x: w.x, y: ry, w: w.w, h: vh, size: size, color: w.color || "#fff", font: "head",
            align: "end" }, { "font-weight": num(w.weight) ? w.weight : 600 });
          var vt = el("tspan", {}, val);
          var ut = el("tspan", { "font-size": Math.round(size * 0.6), "font-weight": 500,
            dx: Math.round(size * 0.12), fill: w.label_color || "#9aa6b2" }, val);
          if (i < part.length - 1) {
            el("rect", { x: w.x, y: ry + vh + 8.5, width: w.w, height: 1, fill: w.separator || "#2b343e" }, grp);
          }
          rows.push({ id: id, lab: lab, vt: vt, ut: ut });
        });
      }
      return {
        update: function (c) {
          var list = ids(c.values), k = list.join(",");
          if (k !== key) { key = k; layout(list); }
          rows.forEach(function (r) {
            var nm = c.meta && c.meta[r.id] && c.meta[r.id].name;
            var rd = c.stale ? null : reading({ sensor: r.id, scale: w.scale,
              decimals: w.decimals == null ? 0 : w.decimals, unit: unit }, c.values, c.meta);
            r.lab.textContent = nm || r.id;
            r.vt.textContent = rd ? rd.text : DASH;
            r.ut.textContent = rd ? rd.unit : "";
          });
        }
      };
    },
    line: function (w, g) {
      var size = num(w.size) ? w.size : 16;
      var axis = w.axis !== false;
      var lw = axis ? size * 2.6 : 0;   // links Platz für die Achsenwerte
      var box = { x: w.x + lw, y: w.y + size / 2, w: Math.max(1, w.w - lw), h: Math.max(1, w.h - size) };
      var seconds = num(w.seconds) ? w.seconds : 60;
      var lc = w.label_color || w.color || "#fff";
      var area = w.area ? el("polygon", { points: "", fill: w.area, stroke: "none" }, g) : null;
      var line = el("polyline", { points: "", fill: "none", stroke: w.color || "#00c0bc",
        "stroke-width": num(w.thickness) ? w.thickness : 3, "stroke-linejoin": "round", "stroke-linecap": "round" }, g);
      function lab(y) {
        return el("text", { x: w.x, y: y, "dominant-baseline": "central", fill: lc, "font-size": size,
          style: "font-family:" + FONTS.sans }, g);
      }
      var top = axis ? lab(box.y) : null, bottom = axis ? lab(box.y + box.h) : null;
      return {
        seconds: seconds,
        update: function (c) {
          var pts = c.stale ? [] : ((c.hist && c.hist[w.sensor]) || []);
          var lo, hi;
          if (num(w.min) && num(w.max)) { lo = w.min; hi = w.max; }
          else {
            var inWin = pts.filter(function (p) { return p[0] >= c.now - seconds * 1000; });
            if (!inWin.length) { lo = 0; hi = 1; }
            else {
              lo = Math.min.apply(null, inWin.map(function (p) { return p[1]; }));
              hi = Math.max.apply(null, inWin.map(function (p) { return p[1]; }));
              if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
            }
          }
          var lp = pts.length > 1 ? linePoints(pts, c.now, seconds, box, lo, hi) : "";
          line.setAttribute("points", lp);
          if (area) {
            var first = lp ? lp.split(" ")[0].split(",")[0] : null, last = lp ? lp.split(" ").pop().split(",")[0] : null;
            var base = (box.y + box.h).toFixed(1);
            area.setAttribute("points", lp && lp.indexOf(" ") > 0 ? lp + " " + last + "," + base + " " + first + "," + base : "");
          }
          if (!axis) return;
          var unit = w.unit != null ? w.unit : ((c.meta && c.meta[w.sensor] && c.meta[w.sensor].unit) || "");
          var have = pts.length > 0;
          top.textContent = have ? formatNumber(hi, w.decimals == null ? 0 : w.decimals) + " " + unit : "";
          bottom.textContent = have ? formatNumber(lo, w.decimals == null ? 0 : w.decimals) + " " + unit : "";
        }
      };
    }
  };

  // Baut das SVG; Ergebnis { svg, updaters, ticks, lineSensors: {id: maxSeconds} }
  function build(dash) {
    var svg = el("svg", { viewBox: "0 0 " + dash.width + " " + dash.height, preserveAspectRatio: "xMidYMid meet",
      role: "img" });
    el("rect", { x: 0, y: 0, width: dash.width, height: dash.height, fill: dash.background }, svg);
    var clip = el("clipPath", { id: "canvas" }, el("defs", {}, svg));
    el("rect", { x: 0, y: 0, width: dash.width, height: dash.height }, clip);
    var g = el("g", { "clip-path": "url(#canvas)" }, svg);
    var res = { svg: svg, updaters: [], ticks: [], lineSensors: {} };
    dash.widgets.forEach(function (w) {
      var b = builders[w.type];
      if (!b) return;
      var o = b(w, g);
      if (!o) return;
      if (o.update) res.updaters.push(o.update);
      if (o.tick) res.ticks.push(o.tick);
      if (w.type === "line") res.lineSensors[w.sensor] = Math.max(res.lineSensors[w.sensor] || 0, o.seconds);
    });
    return res;
  }

  return { build: build, reading: reading, range: range, fraction: fraction, formatNumber: formatNumber,
    formatTime: formatTime, arcPath: arcPath, linePoints: linePoints, STALE_MS: STALE_MS };
})();

// ---------- Seite: Dashboard laden, Hub abonnieren ----------
(function () {
  if (typeof Hub === "undefined") return;       // z. B. in einer Testumgebung ohne Hub
  var stage = document.getElementById("stage"), msgEl = document.getElementById("msg");
  var name = (/[?&]d=([a-z0-9_-]+)/.exec(location.search) || [0, "deck"])[1];
  var view = null, values = {}, meta = {}, hist = {}, lastStats = 0;

  function say(text) { msgEl.textContent = text || ""; msgEl.hidden = !text; }

  function render() {
    if (!view) return;
    var now = Date.now();
    var ctx = { values: values, meta: meta, hist: hist, now: now, stale: now - lastStats > StatsView.STALE_MS };
    view.ticks.forEach(function (f) { f(now); });
    view.updaters.forEach(function (f) { f(ctx); });
  }

  function onStats(m) {
    var now = Date.now();
    values = m.values || {};
    if (m.meta) meta = Object.assign({}, meta, m.meta);
    lastStats = now;
    for (var id in view ? view.lineSensors : {}) {
      var v = values[id];
      if (typeof v !== "number") continue;
      var h = hist[id] || (hist[id] = []);
      h.push([now, v]);
      var cut = now - (view.lineSensors[id] + 5) * 1000;
      while (h.length && h[0][0] < cut) h.shift();
    }
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
        view = StatsView.build(dash);
        stage.appendChild(view.svg);
        say("");
        render();
      })
      .catch(function (e) {
        if (e && e.message === "fehlt") { say("Dashboard „" + name + "“ nicht gefunden"); return; }
        say("Dashboard „" + name + "“ wird geladen …");
        setTimeout(load, 3000);
      });
  }
  load();
})();
