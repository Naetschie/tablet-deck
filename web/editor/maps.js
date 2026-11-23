"use strict";
// Reiter „Karten“ des Editors: Kartenliste je Spiel bearbeiten (Name, Adresse, „schwer“, Reihenfolge), bei Map Genie
// suchen, auf dem Tablet zeigen. Gespeichert wird im Hub in maps.json (eigene Liste ersetzt die Standardliste aus
// games.json bzw. Map Genie; „Standard“ entfernt sie wieder). Läuft im Editor-Kanal /edit (Nachrichten maps_*,
// Token-Anmeldung macht editor.js). Inhalte nur über textContent/value - nie innerHTML.
(function () {
  var api = null;              // { send(obj), status(text, cls), isOpen() } von editor.js
  var games = [], current = null, sel = null;
  var rows = [], savedJson = "[]", found = null, active = false, loaded = false;
  var $ = function (id) { return document.getElementById(id); };

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
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function copy(maps) { return (maps || []).map(function (m) { return { name: m.name, url: m.url, heavy: !!m.heavy }; }); }
  function clean(list) {
    return list.map(function (m) {
      var o = { name: m.name.trim(), url: m.url.trim() };
      if (m.heavy) o.heavy = true;
      return o;
    });
  }
  function game() { return games.filter(function (g) { return g.id === sel; })[0] || null; }
  function isDirty() { return !!sel && JSON.stringify(clean(rows)) !== savedJson; }
  function host(u) { try { return new URL(u).host.replace(/^www\./, ""); } catch (e) { return ""; } }
  var VALID_URL = /^https:\/\/[a-z0-9.-]+(:[0-9]{1,5})?([/?#][^\s\\\x00-\x1f\x7f]*)?$/i;   // wie MAP_URL (bridge/profiles.py)
  function validUrl(u) { return VALID_URL.test(u.trim()); }

  // ---------------------------------------------------------------- Spieleliste
  function renderList() {
    var ul = $("mapsGames"); clear(ul);
    games.forEach(function (g) {
      var meta = g.maps.length ? g.maps.length + (g.maps.length === 1 ? " Karte" : " Karten") : "keine Karten";
      var li = h("li", { cls: g.id === sel ? "sel" : "", title: g.name, tabindex: "0", role: "button" }, [
        h("span", { cls: "name", text: g.name }),
        g.id === current ? h("span", { cls: "badge", text: "läuft" }) : null,
        g.custom ? h("span", { cls: "badge own", text: "eigen" }) : null,
        h("span", { cls: "meta", text: meta })]);
      li.onclick = function () { pick(g.id); };
      li.onkeydown = function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(g.id); } };
      ul.appendChild(li);
    });
    if (!games.length) ul.appendChild(h("li", { cls: "dim", text: loaded ? "Keine Spiele gefunden" : "Wird geladen …" }));
  }

  function pick(id) {
    if (id === sel) return;
    if (isDirty() && !confirm("Ungespeicherte Änderungen an den Karten verwerfen?")) return;
    sel = id; found = null;
    var g = game();
    rows = copy(g ? g.maps : []);
    savedJson = JSON.stringify(clean(rows));
    renderList(); renderEditor();
  }

  // ---------------------------------------------------------------- Kartenliste eines Spiels
  function renderEditor() {
    var g = game(), box = $("mapsRows");
    clear(box);
    $("mapsEdit").hidden = !g; $("mapsEmpty").hidden = !!g;
    if (!g) return;
    $("mapsName").textContent = g.name;
    $("mapsInfo").textContent = g.custom
      ? "Eigene Liste (maps.json) – „Standard“ stellt die mitgelieferte bzw. gefundene Liste wieder her."
      : g.source === "games" ? "Standardliste aus games.json – Änderungen werden als eigene Liste gespeichert."
        : "Gefunden bei Map Genie (installiertes Spiel) – Änderungen werden als eigene Liste gespeichert.";
    $("mapsReset").disabled = !g.custom;
    rows.forEach(function (m, i) {
      var name = h("input", { maxlength: "60", spellcheck: "false", "aria-label": "Name der Karte", placeholder: "Name" });
      name.value = m.name;
      name.oninput = function () { m.name = name.value; mark(name, !!name.value.trim()); dirty(); };
      var url = h("input", { maxlength: "1024", spellcheck: "false", "aria-label": "Adresse", placeholder: "https://…", cls: "url" });
      url.value = m.url;
      url.oninput = function () { m.url = url.value; mark(url, validUrl(url.value)); dirty(); };
      var heavy = h("input", { type: "checkbox" });
      heavy.checked = !!m.heavy;
      heavy.onchange = function () { m.heavy = heavy.checked; dirty(); };
      var row = h("div", { cls: "maprow" + (i === 0 ? " first" : "") }, [
        h("span", { cls: "num", text: i === 0 ? "Standard" : String(i + 1), title: i === 0 ? "Erste Karte: wird zuerst gezeigt" : "" }),
        name, url,
        h("label", { cls: "inline heavy", title: "Schwere 3D-Karte: im Light-Modus nicht automatisch gewählt" }, [heavy, document.createTextNode(" schwer")]),
        h("button", { cls: "ghost small", title: "Nach oben", "aria-label": "Nach oben", text: "↑", onclick: function () { move(i, -1); } }),
        h("button", { cls: "ghost small", title: "Nach unten", "aria-label": "Nach unten", text: "↓", onclick: function () { move(i, 1); } }),
        h("button", { cls: "ghost small", title: "In der Karten-Kachel am Tablet öffnen (gespeicherte Karte)", text: "Zeigen",
          onclick: function () { show(m); } }),
        h("button", { cls: "ghost small del", title: "Entfernen", "aria-label": "Entfernen", text: "✕", onclick: function () { rows.splice(i, 1); renderEditor(); dirty(); } })]);
      row.children[2].title = host(m.url);
      box.appendChild(row);
      mark(name, !!m.name.trim()); mark(url, validUrl(m.url));
    });
    if (!rows.length) box.appendChild(h("p", { cls: "hint", text: "Keine Karten – mit „+ Karte“ hinzufügen oder bei Map Genie suchen." }));
    renderFound();
    dirty();
  }
  function mark(input, ok) { input.className = (input.className.replace(/\bbad\b/g, "").trim() + (ok ? "" : " bad")).trim(); }
  function move(i, d) {
    var j = i + d;
    if (j < 0 || j >= rows.length) return;
    var t = rows[i]; rows[i] = rows[j]; rows[j] = t;
    renderEditor();
  }
  var wasDirty = false;
  function dirty() {
    var d = isDirty();
    $("mapsSave").disabled = !d; $("mapsRevert").disabled = !d;
    // nur beim Wechsel melden - sonst löschte das Neuzeichnen „Gespeichert“ bzw. Fehlermeldungen
    if (active && d !== wasDirty) api.status(d ? "Ungespeicherte Änderungen" : "", "");
    wasDirty = d;
  }

  function renderFound() {
    var box = $("mapsFound"); clear(box);
    if (!found) return;
    if (!found.length) { box.appendChild(h("p", { cls: "hint", text: "Map Genie hat für dieses Spiel keine Karten." })); return; }
    var have = {}; rows.forEach(function (m) { have[m.url.trim()] = true; });
    var add = found.filter(function (m) { return !have[m.url]; });
    box.appendChild(h("p", { cls: "hint", text: "Bei Map Genie gefunden: " + found.map(function (m) { return m.name; }).join(", ") +
      (add.length ? "" : " – schon alle in der Liste.") }));
    if (add.length) box.appendChild(h("button", { cls: "small", text: add.length === 1 ? "Übernehmen" : "Alle " + add.length + " übernehmen",
      onclick: function () { add.forEach(function (m) { rows.push({ name: m.name, url: m.url, heavy: false }); }); found = null; renderEditor(); } }));
  }

  function show(m) {
    if (isDirty()) { api.status("Erst speichern, dann am Tablet zeigen", "err"); return; }
    api.send({ t: "maps_show", game: sel, url: m.url.trim() });
  }

  function save() {
    if (!sel || !isDirty()) return;
    var list = clean(rows);
    if (list.length > 30) { api.status("Höchstens 30 Karten je Spiel", "err"); return; }
    var seen = {};
    for (var i = 0; i < list.length; i++) {
      if (!list[i].name || !validUrl(list[i].url)) { api.status("Jede Karte braucht einen Namen und eine https-Adresse", "err"); return; }
      if (seen[list[i].url]) { api.status("Adresse doppelt: " + list[i].url, "err"); return; }
      seen[list[i].url] = true;
    }
    var g = game();
    // Gleich der Standardliste: keine eigene Liste anlegen (bzw. die eigene entfernen)
    if (JSON.stringify(list) === JSON.stringify(clean(copy(g.default)))) api.send({ t: "maps_reset", game: sel });
    else api.send({ t: "maps_save", game: sel, maps: list });
    api.status("Speichere …", "");
  }

  // ---------------------------------------------------------------- Kanal
  function onMessage(m) {
    if (m.t === "maps_list") {
      games = m.games || []; current = m.current || null; loaded = true;
      var g = game();
      if (m.saved && m.saved === sel) {
        rows = copy(g ? g.maps : []); savedJson = JSON.stringify(clean(rows));
        renderList(); renderEditor();
        api.status("Gespeichert – Tablet aktualisiert sich", "ok");
        return true;
      } else if (!sel || !g) {
        var first = games.filter(function (x) { return x.id === current; })[0] || games.filter(function (x) { return x.maps.length; })[0] || games[0];
        sel = null; if (first) { sel = first.id; rows = copy(first.maps); savedJson = JSON.stringify(clean(rows)); }
      } else if (!isDirty()) {
        rows = copy(g.maps); savedJson = JSON.stringify(clean(rows));
      }
      renderList(); renderEditor();
      return true;
    }
    if (m.t === "maps_found") {
      $("mapsLookup").disabled = false;
      if (m.game === sel) { found = m.maps || []; renderFound(); api.status("", ""); }
      return true;
    }
    if (m.t === "maps_shown") { api.status("Karte am Tablet geöffnet", "ok"); return true; }
    if (m.t === "error" && typeof m.req === "string" && m.req.indexOf("maps_") === 0) {
      $("mapsLookup").disabled = false;
      api.status(m.req === "maps_lookup" ? "Map Genie nicht erreichbar: " + m.msg : m.msg, "err");
      return true;
    }
    return false;
  }

  function init(a) {
    api = a;
    $("mapsAdd").onclick = function () { rows.push({ name: "", url: "", heavy: false }); renderEditor(); var ins = $("mapsRows").querySelectorAll("input"); if (ins.length >= 3) ins[ins.length - 3].focus(); };
    $("mapsLookup").onclick = function () {
      if (!sel) return;
      $("mapsLookup").disabled = true; found = null; renderFound();
      api.status("Suche bei Map Genie …", ""); api.send({ t: "maps_lookup", game: sel });
    };
    $("mapsSave").onclick = save;
    $("mapsRevert").onclick = function () { var g = game(); rows = copy(g ? g.maps : []); found = null; renderEditor(); };
    $("mapsReset").onclick = function () {
      var g = game();
      if (!g || !g.custom || !confirm("Eigene Kartenliste für „" + g.name + "“ entfernen und die Standardliste nutzen?")) return;
      api.send({ t: "maps_reset", game: sel });
    };
    renderList();
  }
  function onOpen() { $("mapsLookup").disabled = false; if (active) api.send({ t: "maps_list" }); else loaded = false; }
  function activate() { active = true; wasDirty = false; if (api.isOpen()) api.send({ t: "maps_list" }); dirty(); }
  function deactivate() { active = false; }
  // Reiterwechsel: bei ungespeicherten Änderungen nachfragen (sie bleiben hier erhalten, wie bei den Dashboards)
  function canLeave() {
    return !isDirty() || confirm("Die Karten haben ungespeicherte Änderungen.\nTrotzdem den Reiter wechseln? (Die Änderungen bleiben hier erhalten.)");
  }

  window.MapsEditor = { init: init, onOpen: onOpen, onMessage: onMessage, activate: activate, deactivate: deactivate,
    canLeave: canLeave, isDirty: isDirty, save: save };
})();
