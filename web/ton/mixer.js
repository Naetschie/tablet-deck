"use strict";
// Mixer: Lautstärke je App und Ausgabegerät (Hub meldet {"t":"mixer","sessions":[…],"devices":[…],"default":id})
(function () {
  var list = document.getElementById("apps"), outs = document.getElementById("outs"),
      outBtn = document.getElementById("out"), cur = outBtn.querySelector(".cur"),
      card = list.parentNode;
  var rows = {};          // Schlüssel -> {el, name, slider, fill, pct, mute, level, muted, dragging, lastSent}
  var devKey = "";

  function pct(v) { return Math.round(v * 100); }

  function show(r, v) {
    r.fill.style.width = pct(v) + "%";
    r.pct.textContent = pct(v) + " %";
    r.slider.classList.toggle("muted", r.muted);
    r.mute.classList.toggle("on", r.muted);
    r.mute.setAttribute("aria-pressed", r.muted);
    r.icon.setAttribute("href", "/lib/icons.svg#" + (r.muted ? "mute" : "vol-up"));   // zeigt den Zustand
  }

  function makeRow(k) {
    var el = document.createElement("div");
    el.className = "row";
    var slider = document.createElement("div");
    slider.className = "slider";
    var fill = document.createElement("div");
    fill.className = "fill";
    var nm = document.createElement("div");
    nm.className = "nm";
    var name = document.createElement("span");
    nm.appendChild(name);
    var val = document.createElement("div");
    val.className = "val";
    slider.appendChild(fill); slider.appendChild(nm); slider.appendChild(val);
    var mute = document.createElement("div");
    mute.className = "key";
    mute.setAttribute("role", "button");
    mute.setAttribute("aria-label", "Stumm");
    mute.innerHTML = '<svg class="ic"><use href="/lib/icons.svg#vol-up"/></svg>';
    el.appendChild(slider); el.appendChild(mute);
    var r = { el: el, name: name, slider: slider, fill: fill, pct: val, mute: mute,
              icon: mute.querySelector("use"),
              level: 0, muted: false, dragging: null, lastSent: 0, hold: 0 };

    function fromX(e) {
      var b = slider.getBoundingClientRect();
      return Math.min(1, Math.max(0, (e.clientX - b.left) / b.width));
    }
    function sendV(v, force) {
      var now = Date.now();
      if (force || now - r.lastSent >= 60) { Hub.send({ t: "app_volume", k: k, v: v }); r.lastSent = now; }
    }
    // Die Regler füllen die Liste fast ganz aus: senkrecht wischen muss scrollen (touch-action: pan-y, der
    // Browser übernimmt und meldet pointercancel). Erst eine klare Bewegung zur Seite stellt die Lautstärke,
    // ein kurzes Antippen setzt sie auf die Stelle.
    var start = null;
    slider.addEventListener("pointerdown", function (e) {
      if (start) return;          // nur der erste Finger zählt
      start = { x: e.clientX, y: e.clientY, id: e.pointerId };
    });
    slider.addEventListener("pointermove", function (e) {
      if (!start || e.pointerId !== start.id) return;
      if (r.dragging === null) {
        var dx = e.clientX - start.x, dy = e.clientY - start.y;
        if (Math.abs(dx) < 8 || Math.abs(dx) <= Math.abs(dy)) return;
        slider.setPointerCapture(e.pointerId);
      }
      r.dragging = fromX(e); show(r, r.dragging); sendV(r.dragging);
    });
    function finish(v) {
      sendV(v, true);   // Endwert immer senden
      r.level = v; r.dragging = null;
      r.hold = Date.now() + 1500;   // ein schon unterwegs befindlicher alter Stand ließe den Regler zurückspringen
      show(r, v);
    }
    slider.addEventListener("pointerup", function (e) {
      if (!start || e.pointerId !== start.id) return;
      if (r.dragging !== null) finish(r.dragging);
      else if (start && Math.abs(e.clientX - start.x) < 8 && Math.abs(e.clientY - start.y) < 8) finish(fromX(e));
      start = null;
    });
    slider.addEventListener("pointercancel", function (e) {
      if (!start || e.pointerId !== start.id) return;
      start = null;
      if (r.dragging !== null) finish(r.dragging);
    });
    mute.addEventListener("click", function () {      // click: nicht beim Scrollen auslösen
      r.muted = !r.muted; show(r, r.dragging === null ? r.level : r.dragging);
      Hub.send({ t: "app_mute", k: k, on: r.muted });
    });
    return r;
  }

  function syncApps(sessions) {
    var seen = {};
    sessions.forEach(function (s, i) {
      if (typeof s.k !== "string") return;
      seen[s.k] = true;
      var r = rows[s.k];
      if (!r) { r = rows[s.k] = makeRow(s.k); }
      if (list.children[i] !== r.el) list.insertBefore(r.el, list.children[i] || null);
      r.name.textContent = String(s.name);   // Prozessnamen vom PC: nie als HTML
      r.muted = !!s.mute;
      if (r.dragging === null && Date.now() >= r.hold) r.level = Number(s.v) || 0;   // beim Ziehen nicht überschreiben
      show(r, r.dragging === null ? r.level : r.dragging);
    });
    Object.keys(rows).forEach(function (k) {
      if (!seen[k]) { list.removeChild(rows[k].el); delete rows[k]; }
    });
    list.classList.toggle("empty", sessions.length === 0);
  }

  function syncDevices(devices, def) {
    var key = JSON.stringify([devices, def]);
    if (key === devKey) return;
    devKey = key;
    outs.textContent = "";
    cur.textContent = "–";
    devices.forEach(function (d) {
      if (d.id === def) cur.textContent = String(d.name);
      var c = document.createElement("div");
      c.className = "chip" + (d.id === def ? " on" : "");
      c.textContent = String(d.name);
      c.addEventListener("click", function () {   // click: Scrollen in der Liste wählt nichts aus
        card.classList.remove("pick");
        if (d.id === def) return;
        Hub.send({ t: "output", id: d.id });
      });
      outs.appendChild(c);
    });
  }

  var note = document.getElementById("mixnote");
  Hub.on(function (m) {
    if (m.t !== "mixer" || !Array.isArray(m.sessions) || !Array.isArray(m.devices)) return;
    syncApps(m.sessions);
    syncDevices(m.devices, m.default);
    // Hinweis vom PC (z. B. Gerät nicht wählbar); nur als Text
    note.hidden = typeof m.note !== "string";
    note.textContent = typeof m.note === "string" ? m.note : "";
  });
  outBtn.addEventListener("click", function () {
    card.classList.toggle("pick");
  });
  list.classList.add("empty");
})();
