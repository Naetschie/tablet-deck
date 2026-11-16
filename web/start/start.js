"use strict";
// Startseite der Web-Kachel: Lesezeichen, vom PC gesendete Seiten und Verlauf. Daten: /api/web und Hub {t:"web"}.
(function () {
  var data = { bookmarks: [], sent: [], history: [] };
  var editing = false;
  var SVGNS = "http://www.w3.org/2000/svg";
  var $ = function (id) { return document.getElementById(id); };

  function host(u) {
    try { return new URL(u).hostname.replace(/^www\./, "") || String(u); } catch (e) { return String(u || ""); }
  }
  function titleOf(it) { return (it.title && String(it.title).trim()) || host(it.url); }
  function letter(it) {
    var h = host(it.url).replace(/[^A-Za-z0-9ÄÖÜäöü]/g, "");
    return (h.charAt(0) || "?").toUpperCase();
  }
  function ago(t) {
    var s = Math.max(0, Math.floor(Date.now() / 1000 - Number(t || 0)));
    if (s < 60) return "gerade eben";
    var m = Math.floor(s / 60);
    if (m < 60) return "vor " + m + " min";
    var h = Math.floor(m / 60);
    if (h < 24) return "vor " + h + " h";
    var d = Math.floor(h / 24);
    return d === 1 ? "vor 1 Tag" : "vor " + d + " Tagen";
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function open(u) { Hub.send({ t: "web_open", url: u }); }
  function isBookmarked(u) { return data.bookmarks.some(function (b) { return b.url === u; }); }

  function renderBookmarks() {
    var g = $("grid");
    g.textContent = "";
    g.classList.toggle("edit", editing);
    $("editBtn").textContent = editing ? "Fertig" : "Bearbeiten";
    $("editBtn").classList.toggle("on", editing);
    if (!data.bookmarks.length) {
      var e = el("div", "empty", "Noch keine Lesezeichen – im Verlauf auf ☆ tippen");
      e.style.gridColumn = "1 / -1";
      g.appendChild(e);
      return;
    }
    data.bookmarks.forEach(function (b) {
      var t = el("div", "tile");
      t.setAttribute("role", "button");
      t.appendChild(el("div", "badge", letter(b)));
      t.appendChild(el("div", "t", titleOf(b)));
      t.appendChild(el("div", "h", host(b.url)));
      t.addEventListener("click", function () { if (!editing) open(b.url); });
      var d = el("div", "del");
      d.setAttribute("role", "button");
      d.setAttribute("aria-label", "Lesezeichen entfernen");
      var svg = document.createElementNS(SVGNS, "svg");
      svg.setAttribute("class", "ic");
      var use = document.createElementNS(SVGNS, "use");
      use.setAttribute("href", "/lib/icons.svg#x");
      svg.appendChild(use);
      d.appendChild(svg);
      d.addEventListener("click", function (ev) {
        ev.stopPropagation();
        Hub.send({ t: "web_bookmark", url: b.url, add: false });
        data.bookmarks = data.bookmarks.filter(function (x) { return x.url !== b.url; });
        if (!data.bookmarks.length) editing = false;
        render();
      });
      t.appendChild(d);
      g.appendChild(t);
    });
  }

  function renderList(box, items, max, emptyText) {
    box.textContent = "";
    var list = (items || []).slice(0, max);
    if (!list.length) { box.appendChild(el("div", "empty", emptyText)); return; }
    list.forEach(function (it) {
      var r = el("div", "row");
      r.setAttribute("role", "button");
      r.appendChild(el("div", "badge", letter(it)));
      var m = el("div", "m");
      m.appendChild(el("div", "t", titleOf(it)));
      m.appendChild(el("div", "h", host(it.url) + (it.time ? " · " + ago(it.time) : "")));
      r.appendChild(m);
      var on = isBookmarked(it.url);
      var s = el("div", "star" + (on ? " on" : ""), on ? "★" : "☆");
      s.setAttribute("role", "button");
      s.setAttribute("aria-label", on ? "Lesezeichen vorhanden" : "Als Lesezeichen speichern");
      s.addEventListener("click", function (ev) {
        ev.stopPropagation();
        if (isBookmarked(it.url)) return;
        Hub.send({ t: "web_bookmark", url: it.url, title: titleOf(it), add: true });
        data.bookmarks.push({ title: titleOf(it), url: it.url });
        render();
      });
      r.appendChild(s);
      r.addEventListener("click", function () { open(it.url); });
      box.appendChild(r);
    });
  }

  function render() {
    renderBookmarks();
    renderList($("sent"), data.sent, 10, "Noch nichts vom PC gesendet");
    renderList($("hist"), data.history, 30, "Noch kein Verlauf");
    $("clear").disabled = !data.history.length;
  }

  function apply(m) {
    data = {
      bookmarks: Array.isArray(m.bookmarks) ? m.bookmarks : [],
      sent: Array.isArray(m.sent) ? m.sent : [],
      history: Array.isArray(m.history) ? m.history : []
    };
    data.sent = data.sent.slice().sort(function (a, b) { return (b.time || 0) - (a.time || 0); });
    if (!data.bookmarks.length) editing = false;
    render();
  }

  function load() {
    fetch("/api/web", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(apply)
      .catch(function () {});
  }

  $("editBtn").addEventListener("click", function () { editing = !editing; renderBookmarks(); });

  // Verlauf löschen: nur nach 1 s Halten (Füllbalken)
  (function () {
    var b = $("clear"), timer = null;
    function stop() { clearTimeout(timer); timer = null; b.classList.remove("arming"); }
    b.addEventListener("pointerdown", function (ev) {
      if (b.disabled) return;
      try { b.setPointerCapture(ev.pointerId); } catch (e) {}
      b.classList.add("arming");
      timer = setTimeout(function () {
        stop();
        Hub.send({ t: "web_clear" });
        data.history = [];
        render();
      }, 1000);
    });
    ["pointerup", "pointercancel", "pointerleave"].forEach(function (n) { b.addEventListener(n, stop); });
    b.addEventListener("contextmenu", function (ev) { ev.preventDefault(); });
  })();

  Hub.on(function (m) { if (m && m.t === "web") apply(m); });
  Hub.onStatus(function (ok) { if (ok) load(); });
  setInterval(render, 60000); // relative Zeiten auffrischen
  render();
  load();
})();
