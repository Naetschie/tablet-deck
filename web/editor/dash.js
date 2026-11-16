"use strict";
// Dashboard-Editor (Reiter „Dashboards“ des Editors): Liste, Vorschau mit dem echten Renderer (stats/render.js) und
// Live-Werten, Bearbeitungsebene (Auswählen, Ziehen, Größe ändern, Einrasten), Palette, Eigenschaften, Speichern.
// Läuft im Editor-Kanal /edit (Nachrichten dash_*, Token-Anmeldung macht editor.js). Alle Inhalte nur über
// textContent/value/setAttribute - nie innerHTML. Reine Hilfen: dashlib.js, Kern: core.js.
(function () {
  var Core = EditorCore, Lib = DashLib, SV = StatsView;
  var NS = "http://www.w3.org/2000/svg";
  var BUNDLED = "mitgeliefert";
  var SNAP_PX = 6;            // Einrast-Abstand auf dem Bildschirm
  var DRAG_PX = 3;            // ab so vielen Bildschirm-Pixeln gilt es als Ziehen
  var POLL_MS = 2000;         // Sensorwerte über den Editor-Kanal (der Tablet-Kanal /ws braucht die Kopplung)
  var api = null;             // { send(obj), status(text, cls), isOpen() } von editor.js

  var schema = null, list = [], defaultName = null;
  var cur = { name: null, origin: null };
  var doc = null, savedJson = "", hist = null, sel = [], primary = null;
  var solo = false;           // genau ein Element innerhalb einer Gruppe gewählt (Doppelklick): Gruppe wird nicht erweitert
  var marquee = null, lastDown = null;
  var grid = 8, active = false, wantName = null, pendingSave = null, loading = false;
  var sensors = [], sources = {}, sensorsAt = 0;
  var vstate = SV.createState(), mounted = null, scale = 1, drag = null, guides = [];
  var propsInputs = {}, sensorPick = null, rafPending = false;
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
  function s(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function lockIcon() {
    var svg = s("svg", { viewBox: "0 0 24 24", width: 14, height: 14, "aria-label": "mitgeliefert, schreibgeschützt", "class": "lock" });
    s("rect", { x: 5, y: 11, width: 14, height: 10, rx: 2 }, svg);
    s("path", { d: "M8 11V7a4 4 0 0 1 8 0v4" }, svg);
    return svg;
  }

  // ---------------------------------------------------------------- Zustand
  function readOnly() { return !!doc && cur.origin === BUNDLED; }
  function snapshot() { return doc; }
  function saveText() { return JSON.stringify(Lib.toSave(doc)); }
  function isDirty() { return !!doc && !readOnly() && saveText() !== savedJson; }
  function widgetById(id) { for (var i = 0; i < doc.widgets.length; i++) if (doc.widgets[i].id === id) return doc.widgets[i]; return null; }
  function primaryWidget() { return primary && sel.indexOf(primary) >= 0 ? widgetById(primary) : (sel.length ? widgetById(sel[0]) : null); }
  function canvas() { return { w: doc.width, h: doc.height }; }

  function leaveOk() { return !isDirty() || confirm("Ungespeicherte Änderungen im Dashboard verwerfen?"); }
  // Mitgelieferte Dashboards sind nur ansehbar: jede Bearbeitung fragt zuerst nach einer Kopie.
  function ensureEditable() {
    if (!doc) return false;
    if (!readOnly()) return true;
    if (confirm("„" + doc.title + "“ ist mitgeliefert und schreibgeschützt.\nEine eigene Kopie anlegen und dort weiterarbeiten?")) copyCurrent();
    return false;
  }

  function setDoc(name, origin, dashboard) {
    cur = { name: name, origin: origin };
    doc = Lib.toEditable(dashboard);
    savedJson = saveText();
    hist = new Core.History(200); hist.push(snapshot());
    sel = []; primary = null; solo = false; guides = []; pendingSave = null; loading = false;
    try { sessionStorage.setItem("dashName", name); } catch (e) { /* ohne Speicher: Standard */ }
    $("dashErr").textContent = "";
    renderAll();
  }
  function restore(text) {
    doc = JSON.parse(text);
    sel = sel.filter(function (id) { return !!widgetById(id); });
    if (primary && sel.indexOf(primary) < 0) primary = null;
    if (sel.length !== 1) solo = false;
  }
  // Änderung abschließen: Verlauf, Anzeige, Status
  function commit() {
    hist.push(snapshot());
    renderAll();
  }
  function setSel(ids, prim) {
    solo = false;
    sel = Core.expandSelection(doc.widgets, ids);
    primary = prim && sel.indexOf(prim) >= 0 ? prim : (sel[0] || null);
  }
  // Ein einzelnes Element innerhalb seiner Gruppe wählen (Eigenschaften, Größe, Verschieben nur dieses Elements)
  function setSolo(id) {
    sel = [id]; primary = id; solo = true;
  }
  function refreshSel() { renderOverlay(); renderElems(); renderProps(); renderToolbar(); }

  // ---------------------------------------------------------------- Nachrichten vom Hub
  function send(o) { api.send(o); }
  function onOpen() {
    if (!doc) loading = false;
    pendingSave = null; updateStatus();      // Speichern über die alte Verbindung ist verloren
    send({ t: "dash_schema" }); send({ t: "dash_list" });
    if (active) poll();
  }
  function applyOverview(m) {
    if (m.dashboards) list = m.dashboards;
    if ("default" in m) defaultName = m.default;
    renderList();
  }
  function pickInitial() {
    if (cur.name || loading || !list.length) return;
    var want = null;
    try { want = sessionStorage.getItem("dashName"); } catch (e) { /* egal */ }
    var names = list.map(function (d) { return d.name; });
    load(names.indexOf(want) >= 0 ? want : (names.indexOf(defaultName) >= 0 ? defaultName : names[0]));
  }
  function load(name) { wantName = name; loading = true; send({ t: "dash_get", name: name }); }

  function onMessage(m) {
    var t = m.t;
    if (t === "error" && m.req === "dash_sensors") return true;     // Live-Werte: Fehler alle 2 s still ignorieren
    if (t === "error" && typeof m.req === "string" && m.req.indexOf("dash_") === 0) { onError(m); return true; }
    if (typeof t !== "string" || t.indexOf("dash_") !== 0) return false;
    if (t === "dash_schema") { schema = m.schema; renderPalette(); renderProps(); }
    else if (t === "dash_list") { applyOverview(m); if (active) pickInitial(); }
    else if (t === "dash_get") { if (m.name === wantName) setDoc(m.name, m.origin, m.dashboard); }
    else if (t === "dash_saved") {
      if (pendingSave !== null && m.name === cur.name) { savedJson = pendingSave; pendingSave = null; }
      $("dashErr").textContent = "";
      send({ t: "dash_list" });             // Titel in der Liste
      updateStatus(true);
    } else if (t === "dash_created") {
      applyOverview(m); wantName = m.name;
      setDoc(m.name, m.origin, m.dashboard);
      api.status("Neues Dashboard „" + m.name + "“ angelegt", "ok");
    } else if (t === "dash_renamed") {
      applyOverview(m);
      if (cur.name === renaming) { cur.name = m.name; wantName = m.name; try { sessionStorage.setItem("dashName", m.name); } catch (e) { /* egal */ } }
      renaming = null; renderList(); updateStatus(true);
    } else if (t === "dash_deleted") {
      applyOverview(m);
      if (m.name === cur.name) { cur = { name: null, origin: null }; doc = null; savedJson = ""; renderAll(); pickInitial(); }
    } else if (t === "dash_default") { applyOverview(m); api.status("Standard für die Kachel „PC-Werte“ gesetzt", "ok"); }
    else if (t === "dash_sensors") onSensors(m);
    return true;
  }
  var renaming = null;

  function onError(m) {
    var wasSave = m.req === "dash_save";
    if (wasSave) pendingSave = null;
    if (m.req === "dash_get") loading = false;
    renaming = null;
    $("dashErr").textContent = m.msg;
    var at = /widgets\[(\d+)\]/.exec(m.msg || "");
    if (wasSave && at && doc && doc.widgets[+at[1]]) { setSel([doc.widgets[+at[1]].id]); renderAll(); }   // fehlerhaftes Element wählen
    api.status((wasSave ? "Nicht gespeichert: " : "Fehler: ") + m.msg, "err");
  }

  // ---------------------------------------------------------------- Live-Werte
  function poll() { if (active && api.isOpen() && !document.hidden) send({ t: "dash_sensors" }); }
  function onSensors(m) {
    sensors = Array.isArray(m.sensors) ? m.sensors : [];
    sources = m.sources || {};
    sensorsAt = Date.now();
    var values = {}, meta = {};
    sensors.forEach(function (x) {
      values[x.id] = x.value;
      meta[x.id] = { name: x.name, unit: x.unit, min: typeof x.min === "number" ? x.min : null, max: typeof x.max === "number" ? x.max : null };
    });
    SV.ingest(vstate, mounted && mounted.view, values, meta);
    if (mounted) SV.draw(mounted.view, vstate);
    renderSensorList();
    renderHint();
  }
  setInterval(poll, POLL_MS);
  setInterval(function () { if (active && mounted) SV.draw(mounted.view, vstate); }, 1000);   // Uhr, „veraltet“

  // ---------------------------------------------------------------- Gesamtanzeige
  function renderAll() {
    renderList(); renderToolbar(); layoutStage(); renderPreview(); renderOverlay(); renderElems(); renderProps();
    renderBanner(); renderHint(); updateStatus();
  }
  // nach Änderungen während der Eingabe (Eigenschaftenfelder bleiben unangetastet)
  function renderLight() {
    renderPreview(); renderOverlay(); renderElems(); renderToolbar(); updateStatus();
  }
  function updateStatus(force) {
    if (!active && !force) return;
    if (!doc) { api.status("", ""); return; }
    if (pendingSave !== null) api.status("Speichere …", "");
    else if (readOnly()) api.status("Mitgeliefert – schreibgeschützt", "");
    else if (isDirty()) api.status("Ungespeicherte Änderungen", "dirty");
    else api.status("Gespeichert", "ok");
  }

  // ---------------------------------------------------------------- Liste links
  function renderList() {
    var ul = $("dashList"); clear(ul);
    list.forEach(function (d) {
      var li = h("li", { cls: d.name === cur.name ? "sel" : "", title: d.name + " (" + d.origin + ")" }, [
        d.origin === BUNDLED ? lockIcon() : null,
        h("span", { cls: "name", text: d.title }),
        d.name === defaultName ? h("span", { cls: "chip on", text: "Standard" }) : null
      ]);
      li.addEventListener("click", function () { if (d.name !== cur.name && leaveOk()) load(d.name); });
      ul.appendChild(li);
    });
    if (!list.length) ul.appendChild(h("li", { cls: "dim", text: "Keine Dashboards" }));
    var isB = cur.origin === BUNDLED, has = !!doc;
    $("dashCopy").textContent = isB ? "Kopie bearbeiten" : "Duplizieren";
    $("dashCopy").disabled = !has;
    $("dashRename").disabled = !has || isB;
    $("dashDelete").disabled = !has || isB;
    $("dashDefault").disabled = !has || cur.name === defaultName;
  }

  function copyCurrent() {
    if (!doc || !leaveOk()) return;
    send({ t: "dash_create", from: cur.name });
  }

  // ---------------------------------------------------------------- Palette und Elementliste
  function renderPalette() {
    var box = $("dashPalette"); clear(box);
    if (!schema) return;
    Object.keys(schema.types).forEach(function (type) {
      box.appendChild(h("button", { cls: "ghost small", text: Lib.TYPE_LABELS[type] || type, title: "Neues Element „" + (Lib.TYPE_LABELS[type] || type) + "“ mittig einfügen",
        onclick: function () { addWidget(type); } }));
    });
  }
  function addWidget(type) {
    if (!schema || !schema.types[type] || !ensureEditable()) return;
    if (doc.widgets.length >= schema.max_widgets) { api.status("Höchstens " + schema.max_widgets + " Elemente", "err"); return; }
    var w = Lib.newWidget(type, { width: doc.width, height: doc.height }, grid, doc.widgets);
    doc.widgets.push(w);
    setSel([w.id], w.id);
    commit();
  }

  function renderElems() {
    var ul = $("dashElems"); clear(ul);
    if (!doc) return;
    Lib.listRows(doc.widgets).forEach(function (row) {
      if (row.kind === "group") {
        var gm = doc.widgets.filter(function (x) { return x.group === row.group; }).map(function (x) { return x.id; });
        var gsel = gm.length && gm.every(function (i) { return sel.indexOf(i) >= 0; }) && !solo;
        var gl = h("li", { cls: "grp" + (gsel ? " sel" : ""), title: "Gruppe wählen" }, [
          h("span", { cls: "name", text: "Gruppe " + row.group }), h("span", { cls: "meta", text: row.count + " Elemente" })
        ]);
        gl.addEventListener("click", function () { setSel(gm, gm[0]); refreshSel(); });
        ul.appendChild(gl);
        return;
      }
      var w = row.w;
      var li = h("li", { cls: (sel.indexOf(w.id) >= 0 ? "sel" : "") + (row.grouped ? " ingroup" : "") }, [
        h("span", { cls: "name", text: Lib.describe(w) })
      ]);
      // Mitglied einer Gruppe: Klick wählt die Gruppe, Doppelklick das einzelne Element
      li.addEventListener("click", function (e) {
        if (e.detail >= 2 && w.group) setSolo(w.id); else setSel([w.id], w.id);
        refreshSel();
      });
      ul.appendChild(li);
    });
  }

  // ---------------------------------------------------------------- Werkzeugleiste
  // Anordnen-Knöpfe: [Knopf-ID, Zustandsfeld von Lib.arrangeState]
  var ARRANGE = [["dAlL", "align"], ["dAlC", "align"], ["dAlR", "align"], ["dAlT", "align"], ["dAlM", "align"], ["dAlB", "align"],
    ["dDistH", "distribute"], ["dDistV", "distribute"], ["dSameW", "sameSize"], ["dSameH", "sameSize"],
    ["dGroup", "group"], ["dUngroup", "ungroup"]];
  function renderToolbar() {
    var ro = readOnly(), has = !!doc, some = sel.length > 0;
    $("dUndo").disabled = !hist || !hist.canUndo() || ro;
    $("dRedo").disabled = !hist || !hist.canRedo() || ro;
    ["dDup", "dDel", "dFront", "dFwd", "dBack", "dBackAll"].forEach(function (id) { $(id).disabled = !has || !some || ro; });
    var st = has && !ro ? Lib.arrangeState(doc.widgets, sel, solo) : {};
    ARRANGE.forEach(function (a) { $(a[0]).disabled = !st[a[1]]; });
    $("dSave").disabled = !has || ro;
    $("dRevert").disabled = !has || ro;
    $("dGrid").value = String(grid);
    $("dName").textContent = doc ? doc.title + (ro ? " (mitgeliefert)" : "") : "";
  }
  function renderBanner() {
    $("dashBanner").hidden = !readOnly();
  }
  function renderHint() {
    var p = $("dashHint");
    if (!doc) { p.textContent = ""; return; }
    var src = Object.keys(sources).map(function (k) { return k + ": " + sources[k]; }).join(" · ");
    var live = sensorsAt ? sensors.length + " Sensoren live" + (src ? " (" + src + ")" : "") : "Live-Werte werden geladen …";
    p.textContent = doc.width + " × " + doc.height + " px · Raster " + (grid || "aus") + " · " + live +
      " · Alt beim Ziehen: ohne Einrasten · Umschalt/Strg-Klick oder Rahmen: mehrere wählen";
  }

  // ---------------------------------------------------------------- Vorschau und Bearbeitungsebene
  function layoutStage() {
    var box = $("dashStageBox"), st = $("dashStage");
    if (!doc) { st.style.display = "none"; return; }
    st.style.display = "";
    var cs = getComputedStyle(box);
    var aw = box.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    var ah = box.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    scale = Lib.fitScale(aw, ah, doc.width, doc.height, 2);
    st.style.width = Math.floor(doc.width * scale) + "px";
    st.style.height = Math.floor(doc.height * scale) + "px";
  }
  if (typeof ResizeObserver === "function") new ResizeObserver(function () { if (active && doc) { layoutStage(); renderOverlay(); } }).observe($("dashStageBox"));
  window.addEventListener("resize", function () { if (active && doc) { layoutStage(); renderOverlay(); } });

  function renderPreview() {
    var holder = $("dashPrev"); clear(holder); mounted = null;
    if (!doc) return;
    try {
      mounted = SV.mount(doc, holder, vstate);
    } catch (e) {
      $("dashErr").textContent = "Vorschau nicht darstellbar: " + (e && e.message || e);
    }
  }
  function scheduleLight() {
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(function () { rafPending = false; renderPreview(); renderOverlay(); syncPos(); });
  }

  var HANDLES = { nw: [0, 0, "nwse-resize"], n: [.5, 0, "ns-resize"], ne: [1, 0, "nesw-resize"], e: [1, .5, "ew-resize"],
    se: [1, 1, "nwse-resize"], s: [.5, 1, "ns-resize"], sw: [0, 1, "nesw-resize"], w: [0, .5, "ew-resize"] };

  function renderOverlay() {
    var ov = $("dashOv"); clear(ov);
    if (!doc) return;
    ov.setAttribute("viewBox", "0 0 " + doc.width + " " + doc.height);
    var picked = sel.map(widgetById).filter(Boolean);
    picked.forEach(function (w) { s("rect", { x: w.x, y: w.y, width: w.w, height: w.h, "class": "ov-frame" }, ov); });
    if (picked.length > 1) {      // Rahmen um die ganze Auswahl (ohne Größen-Griffe)
      var b = Core.boundsOf(picked);
      s("rect", { x: b.x, y: b.y, width: b.w, height: b.h, "class": "ov-group" }, ov);
    }
    if (marquee) s("rect", { x: Math.min(marquee.x, marquee.x + marquee.w), y: Math.min(marquee.y, marquee.y + marquee.h),
      width: Math.abs(marquee.w), height: Math.abs(marquee.h), "class": "ov-marquee" }, ov);
    guides.forEach(function (g) {
      if (g.axis === "x") s("line", { x1: g.pos, x2: g.pos, y1: 0, y2: doc.height, "class": "ov-guide" }, ov);
      else s("line", { y1: g.pos, y2: g.pos, x1: 0, x2: doc.width, "class": "ov-guide" }, ov);
    });
    if (picked.length === 1 && !readOnly()) {
      var w = picked[0], hs = 10 / scale;
      for (var k in HANDLES) {
        var hd = HANDLES[k];
        s("rect", { x: w.x + w.w * hd[0] - hs / 2, y: w.y + w.h * hd[1] - hs / 2, width: hs, height: hs, "class": "ov-handle",
          "data-h": k, style: "cursor:" + hd[2] }, ov);
      }
    }
  }

  function toDash(e) {
    var r = $("dashOv").getBoundingClientRect();
    return { x: (e.clientX - r.left) * doc.width / r.width, y: (e.clientY - r.top) * doc.height / r.height };
  }
  function others(items, ids) {
    var m = {}; ids.forEach(function (i) { m[i] = true; });
    return items.filter(function (it) { return !m[it.id]; });
  }

  function onDown(e) {
    if (!doc || e.button !== 0) return;
    var ae = document.activeElement;
    if (ae && ae !== document.body && ae.blur && /^(INPUT|SELECT|TEXTAREA)$/.test(ae.tagName)) ae.blur();
    e.preventDefault();
    var p = toDash(e), hd = e.target.getAttribute && e.target.getAttribute("data-h");
    var start = JSON.parse(JSON.stringify(doc.widgets));
    var extra = e.shiftKey || e.ctrlKey || e.metaKey;
    drag = null;
    if (hd && sel.length === 1) {
      drag = { mode: "resize", handle: hd, p: p, cx: e.clientX, cy: e.clientY, start: start, id: sel[0], moved: false };
    } else {
      var hit = Lib.hitTest(doc.widgets, p.x, p.y);
      if (!hit) {          // freie Fläche: Rahmen aufziehen (mit Umschalt/Strg zur Auswahl hinzufügen)
        drag = { mode: "marquee", p: p, cx: e.clientX, cy: e.clientY, base: extra ? sel.slice() : [], extra: extra, moved: false };
      } else if (extra) {  // Umschalt-/Strg-Klick: Element samt Gruppe hinzufügen bzw. abwählen
        sel = Core.toggleSelection(doc.widgets, solo ? [] : sel, [hit.id]); solo = false;
        primary = sel.indexOf(hit.id) >= 0 ? hit.id : (sel[0] || null);
        refreshSel(); lastDown = null; return;
      } else {
        var now = Date.now();
        var dbl = lastDown && lastDown.id === hit.id && now - lastDown.t < 450 && Math.hypot(e.clientX - lastDown.x, e.clientY - lastDown.y) < 6;
        lastDown = { id: hit.id, t: now, x: e.clientX, y: e.clientY };
        if (dbl && hit.group) { setSolo(hit.id); lastDown = null; }     // Doppelklick: Einzelelement der Gruppe
        else if (sel.indexOf(hit.id) < 0 || (solo && sel[0] !== hit.id)) setSel([hit.id], hit.id);
        else primary = hit.id;
        refreshSel();
        drag = { mode: "move", p: p, cx: e.clientX, cy: e.clientY, start: start, ids: sel.slice(), solo: solo, moved: false };
      }
    }
    try { $("dashOv").setPointerCapture(e.pointerId); } catch (x) { /* egal */ }
  }
  function onMove(e) {
    if (!doc) return;
    if (!drag) {
      var q = toDash(e), over = e.target.getAttribute && e.target.getAttribute("data-h");
      $("dashOv").style.cursor = over ? "" : (Lib.hitTest(doc.widgets, q.x, q.y) ? "move" : "crosshair");
      return;
    }
    if (!drag.moved) {
      if (Math.hypot(e.clientX - drag.cx, e.clientY - drag.cy) < DRAG_PX) return;
      if (readOnly() && drag.mode !== "marquee") { drag = null; ensureEditable(); return; }
      drag.moved = true;
    }
    var p = toDash(e), dx = p.x - drag.p.x, dy = p.y - drag.p.y;
    if (drag.mode === "marquee") {
      marquee = { x: drag.p.x, y: drag.p.y, w: dx, h: dy };
      var hits = Core.selectInRect(doc.widgets, marquee);
      var ids = drag.extra ? Core.expandSelection(doc.widgets, drag.base.concat(hits)) : hits;
      solo = false; sel = ids; primary = sel[0] || null;
      renderOverlay();
      return;
    }
    var step = e.altKey ? 0 : grid, thr = e.altKey ? 0 : SNAP_PX / scale, bounds = { w: doc.width, h: doc.height };
    if (drag.mode === "move") {
      var r = Lib.snapMove(drag.start, drag.ids, dx, dy, step, thr, bounds, drag.solo);
      doc.widgets = r.items; guides = r.guides;
    } else {
      var item = drag.start.filter(function (w) { return w.id === drag.id; })[0];
      var rr = Lib.snapResize(item, drag.handle, dx, dy, step, others(drag.start, [drag.id]), thr, { w: 2, h: 2 }, bounds);
      doc.widgets = drag.start.map(function (w) { return w.id === drag.id ? rr.rect : w; });
      guides = rr.guides;
    }
    scheduleLight();
  }
  function onUp() {
    if (!drag) return;
    var d = drag, moved = d.moved; drag = null; guides = []; marquee = null;
    if (d.mode === "marquee") {
      if (!moved && !d.extra && sel.length) { setSel([]); }      // Klick ins Leere hebt die Auswahl auf
      refreshSel();
    } else if (moved) commit(); else renderOverlay();
  }

  // x/y/w/h der Auswahl in den Feldern nachführen (während des Ziehens)
  function syncPos() {
    var w = primaryWidget();
    if (!w) return;
    ["x", "y", "w", "h"].forEach(function (k) {
      var i = propsInputs[k];
      if (i && document.activeElement !== i) i.value = fmt(w[k]);
    });
    updateStatus(); renderElems();
  }
  function fmt(v) { return typeof v === "number" ? String(Math.round(v * 100) / 100).replace(".", ",") : ""; }

  // ---------------------------------------------------------------- Eigenschaften rechts
  function renderProps() {
    var box = $("dashPropsBody"); clear(box); propsInputs = {}; sensorPick = null;
    if (!doc) { box.appendChild(h("p", { cls: "dim", text: "Dashboard wählen." })); return; }
    if (!schema) { box.appendChild(h("p", { cls: "dim", text: "Feldbeschreibung wird geladen …" })); return; }
    var ro = readOnly(), w = primaryWidget();
    if (!w) { renderDashProps(box, ro); return; }
    if (sel.length > 1) { renderMultiProps(box, ro); return; }
    var spec = schema.types[w.type];
    var head = Lib.TYPE_LABELS[w.type] || w.type;
    box.appendChild(h("h2", { text: head }));
    if (solo) box.appendChild(h("p", { cls: "hint", text: "Einzelnes Element der Gruppe " + w.group + " (Esc oder Klick daneben: Auswahl aufheben)." }));
    var req = spec ? spec.required : [];
    var keys = Lib.fieldKeys(spec);
    keys.forEach(function (key) {
      var row = fieldRow(w, key, req.indexOf(key) >= 0, ro);
      if (row) box.appendChild(row);
    });
  }

  // Mehrfachauswahl: nur Felder, die alle gewählten Elemente haben; Ändern setzt den Wert bei allen.
  // Das Proxy-Objekt leitet Lesen/Setzen/Entfernen an alle gewählten Widgets weiter (gleiche Feldbausteine wie einzeln).
  function renderMultiProps(box, ro) {
    var ws = sel.map(widgetById).filter(Boolean);
    box.appendChild(h("h2", { text: sel.length + " Elemente ausgewählt" }));
    var common = Lib.commonFields(ws, schema);
    if (!common.length) {
      box.appendChild(h("p", { cls: "hint", text: sel.length + " Elemente ausgewählt - die Arten haben keine gemeinsamen Felder. Verschieben, Ausrichten und Gruppieren gehen trotzdem." }));
      return;
    }
    box.appendChild(h("p", { cls: "hint", text: "Gemeinsame Felder; eine Änderung gilt für alle " + sel.length + " Elemente. „verschieden“ = die Werte unterscheiden sich." }));
    var ids = sel.slice();
    var proxy = new Proxy({}, {
      get: function (t, k) { var f = Lib.commonFields(ids.map(widgetById).filter(Boolean), schema).filter(function (c) { return c.key === k; })[0]; return f ? f.value : undefined; },
      set: function (t, k, v) { doc.widgets = Lib.setField(doc.widgets, ids, k, v); return true; },
      deleteProperty: function (t, k) { doc.widgets = Lib.setField(doc.widgets, ids, k, undefined); return true; }
    });
    common.forEach(function (c) {
      var row = fieldRow(proxy, c.key, c.required, ro, c.mixed);
      if (row) box.appendChild(row);
    });
  }

  function renderDashProps(box, ro) {
    box.appendChild(h("h2", { text: "Dashboard" }));
    var wrap = h("div", { cls: "props" });
    wrap.appendChild(simpleField("Titel", doc, "title", { kind: "text", max_len: schema.title_max }, true, ro));
    wrap.appendChild(h("div", { cls: "row" }, [
      simpleField("Breite (px)", doc, "width", { kind: "number", min: schema.canvas.min, max: schema.canvas.max }, true, ro, afterSize),
      simpleField("Höhe (px)", doc, "height", { kind: "number", min: schema.canvas.min, max: schema.canvas.max }, true, ro, afterSize)
    ]));
    wrap.appendChild(colorField("Hintergrund", doc, "background", { kind: "color" }, true, ro));
    wrap.appendChild(h("p", { cls: "hint", text: doc.widgets.length + " von höchstens " + schema.max_widgets + " Elementen. " +
      "Element anklicken oder aus der Palette einfügen; die Größe der Fläche ändert die Elemente nicht." }));
    box.appendChild(wrap);
  }
  function afterSize() { layoutStage(); renderHint(); }

  function liveChange(after) { if (after) after(); renderLight(); }
  function commitField() { hist.push(snapshot()); renderToolbar(); updateStatus(); }

  function mark(inp, err) {
    inp.classList.toggle("bad", !!err);
    if (err) inp.setAttribute("title", err); else inp.removeAttribute("title");
  }
  // composite: mehrere Bedienelemente in einem Feld (kein <label>, damit Klicks nicht aufs erste Feld umgelenkt werden)
  function labelled(label, key, req, control, hint, composite) {
    return h(composite ? "div" : "label", { cls: "dfield" }, [
      composite ? h("span", { cls: "cap", text: label + (req ? " *" : "") }) : document.createTextNode(label + (req ? " *" : "")),
      control,
      (hint || Lib.FIELD_HINTS[key]) ? h("span", { cls: "hint", text: hint || Lib.FIELD_HINTS[key] }) : null
    ]);
  }

  // Text-/Zahl-Feld für ein Objekt (Widget oder Dashboard)
  function simpleField(label, obj, key, sp, req, ro, after, mixed) {
    var inp = h("input", { type: "text", autocomplete: "off", spellcheck: "false" });
    if (mixed) inp.setAttribute("placeholder", "verschieden");
    if (sp.kind === "text" && sp.max_len) inp.setAttribute("maxlength", sp.max_len);
    inp.value = sp.kind === "number" || sp.kind === "int" ? fmt(obj[key]) : (obj[key] == null ? "" : obj[key]);
    inp.disabled = ro;
    if (sp.kind !== "text" && sp.kind !== "sensor") inp.setAttribute("inputmode", "decimal");
    function reflect() {
      inp.value = sp.kind === "number" || sp.kind === "int" ? fmt(obj[key]) : (obj[key] == null ? "" : obj[key]);
      mark(inp, null);
    }
    inp.addEventListener("input", function () {
      var res = Lib.parseInput(sp, inp.value, schema, req);
      mark(inp, res.error);
      if (res.error) return;
      if (res.remove) delete obj[key]; else obj[key] = res.value;
      liveChange(after);
    });
    inp.addEventListener("change", function () {
      var res = Lib.parseInput(sp, inp.value, schema, req);
      if (res.error) reflect(); else if (!res.remove) inp.value = sp.kind === "number" || sp.kind === "int" ? fmt(res.value) : inp.value;
      commitField();
    });
    propsInputs[key] = inp;
    return labelled(label, key, req, inp, null);
  }

  function colorField(label, obj, key, sp, req, ro, mixed) {
    var txt = h("input", { type: "text", autocomplete: "off", spellcheck: "false", cls: "ctext" });
    if (mixed) txt.setAttribute("placeholder", "verschieden");
    var pick = h("input", { type: "color", cls: "cpick" });
    txt.value = obj[key] == null ? "" : obj[key];
    pick.value = Lib.colorToPicker(obj[key]);
    txt.disabled = pick.disabled = ro;
    txt.addEventListener("input", function () {
      var res = Lib.parseInput(sp, txt.value, schema, req);
      mark(txt, res.error);
      if (res.error) return;
      if (res.remove) delete obj[key]; else { obj[key] = res.value; pick.value = Lib.colorToPicker(res.value); }
      liveChange();
    });
    txt.addEventListener("change", function () {
      var res = Lib.parseInput(sp, txt.value, schema, req);
      if (res.error) { txt.value = obj[key] == null ? "" : obj[key]; mark(txt, null); }
      commitField();
    });
    pick.addEventListener("input", function () {
      obj[key] = Lib.pickerToColor(pick.value, obj[key]);
      txt.value = obj[key]; mark(txt, null); liveChange();
    });
    pick.addEventListener("change", commitField);
    return labelled(label, key, req, h("span", { cls: "crow" }, [pick, txt]), null, true);
  }

  function selectField(label, w, key, sp, req, ro, options, mixed) {
    var sel1 = h("select");
    if (mixed) sel1.appendChild(h("option", { value: "__mixed", text: "(verschieden)" }));
    else if (!req) sel1.appendChild(h("option", { value: "", text: "(Standard)" }));
    options.forEach(function (o) { sel1.appendChild(h("option", { value: o[0], text: o[1] })); });
    var curv = w[key];
    sel1.value = mixed ? "__mixed" : (curv === undefined ? "" : (typeof curv === "boolean" ? (curv ? "1" : "0") : String(curv)));
    sel1.disabled = ro;
    sel1.addEventListener("change", function () {
      var v = sel1.value;
      if (v === "__mixed") return;
      if (v === "") delete w[key];
      else if (sp.kind === "bool") w[key] = v === "1";
      else w[key] = v;
      renderLight(); commitField();
    });
    return labelled(label, key, req, sel1, null);
  }

  function zonesField(label, w, key, sp, ro) {
    var wrap = h("div", { cls: "zones" }), err = h("span", { cls: "err-box" });
    var zs = JSON.parse(JSON.stringify(w[key] || []));
    function apply(finalize) {
      var e = Lib.fieldError(sp, zs, schema);
      err.textContent = e || "";
      if (e) return;
      if (zs.length) w[key] = JSON.parse(JSON.stringify(zs)); else delete w[key];
      renderLight();
      if (finalize) commitField();
    }
    function rows() {
      clear(wrap);
      zs.forEach(function (z, i) {
        var from = h("input", { type: "text", inputmode: "decimal", cls: "zfrom", title: "ab (0 bis 1 der Skala)" });
        from.value = fmt(z.from);
        var col = h("input", { type: "text", cls: "ctext", title: "Farbe" });
        col.value = z.color == null ? "" : z.color;
        var pick = h("input", { type: "color", cls: "cpick" });
        pick.value = Lib.colorToPicker(z.color);
        from.disabled = col.disabled = pick.disabled = ro;
        from.addEventListener("input", function () { var v = Number(from.value.replace(",", ".")); zs[i].from = isFinite(v) && from.value.trim() !== "" ? v : NaN; mark(from, !isFinite(zs[i].from) ? "Zahl" : null); apply(false); });
        from.addEventListener("change", function () { apply(true); });
        col.addEventListener("input", function () { zs[i].color = col.value.trim(); pick.value = Lib.colorToPicker(zs[i].color); apply(false); });
        col.addEventListener("change", function () { apply(true); });
        pick.addEventListener("input", function () { zs[i].color = Lib.pickerToColor(pick.value, zs[i].color); col.value = zs[i].color; apply(false); });
        pick.addEventListener("change", function () { apply(true); });
        var del = h("button", { cls: "ghost small del", text: "×", title: "Zone entfernen", onclick: function () { zs.splice(i, 1); rows(); apply(true); } });
        del.disabled = ro;
        wrap.appendChild(h("div", { cls: "zrow" }, [from, pick, col, del]));
      });
      var add = h("button", { cls: "ghost small", text: "+ Zone", onclick: function () {
        var last = zs.length ? zs[zs.length - 1].from : 0.5;
        zs.push({ from: Math.min(1, Math.round((last + 0.2) * 100) / 100), color: "#F0923A" });
        rows(); apply(true);
      } });
      add.disabled = ro || zs.length >= (sp.max_items || 8);
      wrap.appendChild(add); wrap.appendChild(err);
    }
    rows();
    return labelled(label, key, false, wrap, "ab = Anteil der Skala (0 bis 1), aufsteigend", true);
  }

  // Sensor: ID-Feld plus durchsuchbare Liste aus den Live-Werten (ID, Name, aktueller Wert, Einheit)
  function sensorField(label, w, key, sp, req, ro) {
    var inp = h("input", { type: "text", autocomplete: "off", spellcheck: "false" });
    inp.value = w[key] || ""; inp.disabled = ro;
    var q = h("input", { type: "search", placeholder: "Suchen (ID oder Name) …", autocomplete: "off" });
    q.disabled = ro;
    var ul = h("ul", { cls: "sens" });
    function pick(id) {
      w[key] = id; inp.value = id; mark(inp, null); renderLight(); commitField(); renderSensorList();
    }
    inp.addEventListener("input", function () {
      var res = Lib.parseInput(sp, inp.value, schema, req);
      mark(inp, res.error);
      if (res.error) return;
      w[key] = res.value; renderLight(); renderSensorList();
    });
    inp.addEventListener("change", function () {
      var res = Lib.parseInput(sp, inp.value, schema, req);
      if (res.error) { inp.value = w[key] || ""; mark(inp, null); }
      commitField();
    });
    q.addEventListener("input", renderSensorList);
    sensorPick = { ul: ul, q: q, w: w, key: key, pick: pick, ro: ro };
    renderSensorList();
    propsInputs[key] = inp;
    var box = h("div", { cls: "sensbox" }, [inp, q, ul]);
    return labelled(label, key, req, box, null, true);
  }
  // Die Liste wird nur neu aufgebaut, wenn sich Suchtext, Auswahl oder die Menge der Treffer ändert; sonst werden
  // nur die Werte nachgeführt (Scrollposition und Klicks bleiben erhalten).
  function renderSensorList() {
    if (!sensorPick) return;
    var sp = sensorPick, ul = sp.ul;
    if (!sensorsAt) { if (sp.sig !== "wait") { clear(ul); ul.appendChild(h("li", { cls: "dim", text: "Werte werden geladen …" })); sp.sig = "wait"; } return; }
    var found = Lib.filterSensors(sensors, sp.q.value, 80);
    var sig = sp.q.value + "|" + sp.w[sp.key] + "|" + sp.ro + "|" + found.map(function (x) { return x.id + "/" + x.name; }).join(";");
    if (sig === sp.sig && sp.vals) {
      found.forEach(function (x) { var el = sp.vals[x.id]; var t = Lib.formatSensorValue(x); if (el && el.textContent !== t) el.textContent = t; });
      return;
    }
    sp.sig = sig; sp.vals = {}; clear(ul);
    found.forEach(function (x) {
      var val = h("span", { cls: "val", text: Lib.formatSensorValue(x) });
      sp.vals[x.id] = val;
      var li = h("li", { cls: x.id === sp.w[sp.key] ? "sel" : "", title: x.id }, [
        h("span", { cls: "name", text: x.name !== x.id ? x.name : x.id }),
        h("span", { cls: "meta", text: x.name !== x.id ? x.id : "" }),
        val
      ]);
      if (!sp.ro) li.addEventListener("click", function () { sp.pick(x.id); });
      ul.appendChild(li);
    });
    if (!found.length) ul.appendChild(h("li", { cls: "dim", text: sensors.length ? "Kein Treffer" : "Keine Sensoren verfügbar" }));
  }

  function fieldRow(w, key, req, ro, mixed) {
    var sp = schema.fields[key];
    if (!sp) return null;
    var label = Lib.FIELD_LABELS[key] || key;
    switch (sp.kind) {
      case "number": case "int": case "text": return simpleField(label, w, key, sp, req, ro, null, mixed);
      case "color": return colorField(label, w, key, sp, req, ro, mixed);
      case "sensor": return sensorField(label, w, key, sp, req, ro);
      case "bool": return selectField(label, w, key, sp, req, ro, [["1", "Ja"], ["0", "Nein"]], mixed);
      case "enum": return selectField(label, w, key, sp, req, ro, sp.values.map(function (v) { return [v, Lib.ENUM_LABELS[v] || v]; }), mixed);
      case "zones": return zonesField(label, w, key, sp, ro);
    }
    return null;
  }

  // ---------------------------------------------------------------- Bearbeiten (Tastatur, Werkzeugleiste)
  function nudge(dx, dy) {
    if (!sel.length || !ensureEditable()) return;
    doc.widgets = Core.move(doc.widgets, sel, dx, dy, { w: doc.width, h: doc.height }, solo);
    commit();
  }
  function removeSel() {
    if (!sel.length || !ensureEditable()) return;
    var gone = {}; (solo ? sel : Core.expandSelection(doc.widgets, sel)).forEach(function (i) { gone[i] = true; });
    doc.widgets = doc.widgets.filter(function (w) { return !gone[w.id]; });
    sel = []; primary = null;
    commit();
  }
  function duplicateSel() {
    if (!sel.length || !ensureEditable()) return;
    if (doc.widgets.length + sel.length > schema.max_widgets) { api.status("Höchstens " + schema.max_widgets + " Elemente", "err"); return; }
    var off = grid > 0 ? grid : 8;
    var src = doc.widgets;
    if (solo) src = Lib.setField(src, sel, "group", undefined);       // Einzelelement: Kopie ohne die Gruppe
    var r = Core.duplicate(src, sel, { x: off, y: off }, function (it, all) { return Lib.nextId(all); });
    var orig = {}; doc.widgets.forEach(function (w) { orig[w.id] = w; });
    r.items = r.items.map(function (w) { return orig[w.id] || w; });  // Originale unverändert (mit Gruppe)
    doc.widgets = Core.move(r.items, r.ids, 0, 0, { w: doc.width, h: doc.height });
    setSel(r.ids, r.ids[r.ids.length - 1]);
    commit();
  }
  function layer(fn) {
    if (!sel.length || !ensureEditable()) return;
    doc.widgets = fn(doc.widgets, sel);
    commit();
  }
  // Anordnen: fn(items) -> neue Liste; ein Verlaufsschritt je Aktion
  function arrange(fn, key) {
    if (!doc || !sel.length || !ensureEditable()) return false;
    if (!Lib.arrangeState(doc.widgets, sel, solo)[key]) return false;
    doc.widgets = fn(doc.widgets);
    commit();
    return true;
  }
  function alignSel(mode) { arrange(function (it) { return Core.alignUnits(it, sel, mode, canvas(), solo); }, "align"); }
  function distSel(axis) { arrange(function (it) { return Core.distributeUnits(it, sel, axis, solo); }, "distribute"); }
  function sameSel(dim) { arrange(function (it) { return Core.sameSize(it, sel, dim); }, "sameSize"); }
  function groupSel() {
    if (arrange(function (it) { return Core.group(it, sel); }, "group")) { setSel(sel, primary); refreshSel(); }
  }
  function ungroupSel() {
    arrange(function (it) {
      return solo ? Lib.setField(it, sel, "group", undefined) : Core.ungroup(it, sel);
    }, "ungroup");
  }
  function undo(redo) {
    if (!hist || readOnly()) return;
    var st = redo ? hist.redo() : hist.undo();
    if (!st) return;
    restore(JSON.stringify(st));
    renderAll();
  }
  function save() {
    if (!doc) return;
    if (readOnly()) { ensureEditable(); return; }
    if (!api.isOpen()) { api.status("Keine Verbindung zur Bridge – nicht gespeichert", "err"); return; }
    pendingSave = saveText();            // dieser Stand gilt nach der Bestätigung als gespeichert
    send({ t: "dash_save", name: cur.name, dashboard: Lib.toSave(doc) });
    updateStatus();
  }
  function revert() {
    if (!doc || readOnly() || !isDirty()) return;
    if (!confirm("Alle ungespeicherten Änderungen verwerfen?")) return;
    var keep = sel;
    doc = Lib.toEditable(JSON.parse(savedJson));
    hist = new Core.History(200); hist.push(snapshot());
    sel = keep.filter(function (id) { return !!widgetById(id); }); primary = sel[0] || null;
    $("dashErr").textContent = "";
    renderAll();
  }

  function onKey(e) {
    if (!active || !doc) return;
    var t = e.target, tag = t && t.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    var ctrl = e.ctrlKey || e.metaKey, k = e.key, handled = true;
    if (ctrl) {
      if (k === "z" || k === "Z") undo(e.shiftKey);
      else if (k === "y" || k === "Y") undo(true);
      else if (k === "d" || k === "D") duplicateSel();
      else if (k === "a" || k === "A") { setSel(doc.widgets.map(function (w) { return w.id; })); refreshSel(); }
      else if (k === "g" || k === "G") { if (e.shiftKey) ungroupSel(); else groupSel(); }
      else if (k === "]") layer(e.shiftKey ? Core.toFront : Core.bringForward);
      else if (k === "[") layer(e.shiftKey ? Core.toBack : Core.sendBackward);
      else handled = false;
    } else if (k === "Delete") removeSel();
    else if (k === "Escape") { if (sel.length) { setSel([]); refreshSel(); } }
    else if (k.indexOf("Arrow") === 0) {
      var d = e.shiftKey ? 10 : 1;
      nudge(k === "ArrowLeft" ? -d : k === "ArrowRight" ? d : 0, k === "ArrowUp" ? -d : k === "ArrowDown" ? d : 0);
    } else handled = false;
    if (handled) e.preventDefault();
  }

  // ---------------------------------------------------------------- Verdrahtung
  function newDashboard() {
    if (!leaveOk()) return;
    var title = prompt("Titel des neuen Dashboards:", "Neues Dashboard");
    if (!title || !title.trim()) return;
    send({ t: "dash_create", title: title.trim().slice(0, schema ? schema.title_max : 80) });
  }
  function renameDashboard() {
    if (!doc || readOnly()) return;
    var to = prompt("Neuer Name (Dateiname: a-z, 0-9, _ und -; der Titel steht unter „Dashboard“ ohne Auswahl):", cur.name);
    if (!to || to === cur.name) return;
    if (schema && !new RegExp("^(?:" + schema.name_pattern + ")$").test(to)) { api.status("Name: 1 bis 40 Zeichen aus a-z, 0-9, _ und -", "err"); return; }
    renaming = cur.name;
    send({ t: "dash_rename", name: cur.name, to: to });
  }
  function deleteDashboard() {
    if (!doc || readOnly()) return;
    if (!confirm("Dashboard „" + doc.title + "“ löschen?\nEs wird in den Papierkorb verschoben (dashboards/eigene/.papierkorb).")) return;
    send({ t: "dash_delete", name: cur.name });
  }

  function init(a) {
    api = a;
    $("dashNew").onclick = newDashboard;
    $("dashCopy").onclick = copyCurrent;
    $("dashRename").onclick = renameDashboard;
    $("dashDelete").onclick = deleteDashboard;
    $("dashDefault").onclick = function () { if (doc) send({ t: "dash_default", name: cur.name }); };
    $("dashBannerCopy").onclick = copyCurrent;
    $("dUndo").onclick = function () { undo(false); };
    $("dRedo").onclick = function () { undo(true); };
    $("dDup").onclick = duplicateSel;
    $("dDel").onclick = removeSel;
    $("dFront").onclick = function () { layer(Core.toFront); };
    $("dFwd").onclick = function () { layer(Core.bringForward); };
    $("dBack").onclick = function () { layer(Core.sendBackward); };
    $("dBackAll").onclick = function () { layer(Core.toBack); };
    var AR = { dAlL: ["a", "left"], dAlC: ["a", "hcenter"], dAlR: ["a", "right"], dAlT: ["a", "top"], dAlM: ["a", "vcenter"],
      dAlB: ["a", "bottom"], dDistH: ["d", "x"], dDistV: ["d", "y"], dSameW: ["s", "w"], dSameH: ["s", "h"] };
    Object.keys(AR).forEach(function (id) {
      var a = AR[id];
      $(id).onclick = function () { if (a[0] === "a") alignSel(a[1]); else if (a[0] === "d") distSel(a[1]); else sameSel(a[1]); };
    });
    $("dGroup").onclick = groupSel;
    $("dUngroup").onclick = ungroupSel;
    $("dSave").onclick = save;
    $("dRevert").onclick = revert;
    $("dGrid").onchange = function () { grid = parseInt(this.value, 10) || 0; renderHint(); };
    var ov = $("dashOv");
    ov.addEventListener("pointerdown", onDown);
    ov.addEventListener("pointermove", onMove);
    ov.addEventListener("pointerup", onUp);
    ov.addEventListener("pointercancel", onUp);
    document.addEventListener("keydown", onKey);
    renderPalette(); renderAll();
  }

  function activate() {
    active = true;
    if (api.isOpen()) { if (!schema) send({ t: "dash_schema" }); if (!list.length) send({ t: "dash_list" }); }
    layoutStage(); renderOverlay(); renderPreview();
    pickInitial(); poll(); updateStatus();
  }
  function deactivate() { active = false; }
  // Reiterwechsel: bei ungespeicherten Änderungen nachfragen (sie bleiben im Editor erhalten)
  function canLeave() {
    return !isDirty() || confirm("Das Dashboard hat ungespeicherte Änderungen.\nTrotzdem den Reiter wechseln? (Die Änderungen bleiben hier erhalten.)");
  }

  function onClose() { pendingSave = null; updateStatus(); }

  window.DashEditor = { init: init, onOpen: onOpen, onClose: onClose, onMessage: onMessage, activate: activate, deactivate: deactivate,
    canLeave: canLeave, isDirty: isDirty, save: save };
})();
