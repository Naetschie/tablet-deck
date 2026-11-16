"use strict";
(function () {
  var vol = document.getElementById("vol"), fill = document.getElementById("fill"),
      pct = document.getElementById("pct"), muteBtn = document.getElementById("mute");
  var level = 0, muted = false, dragging = null, lastSent = 0, pending = null;

  function show(v) {
    fill.style.width = Math.round(v * 100) + "%";
    pct.textContent = Math.round(v * 100) + " %";
    vol.classList.toggle("muted", muted);
    muteBtn.classList.toggle("on", muted);
  }

  // Lautstärke vom PC (auch wenn sie am PC geändert wird); während des Ziehens nicht überschreiben
  Hub.on(function (m) {
    if (m.t !== "volume") return;
    muted = !!m.mute;
    if (dragging === null) { level = m.v; }
    show(dragging === null ? level : dragging);
  });

  function fromX(e) {
    var r = vol.getBoundingClientRect();
    return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
  }
  function sendThrottled(v) {
    pending = v;
    var now = Date.now();
    if (now - lastSent >= 60) { Hub.send({ t: "volume", v: pending }); lastSent = now; pending = null; }
  }
  vol.addEventListener("pointerdown", function (e) {
    e.preventDefault(); vol.setPointerCapture(e.pointerId);
    dragging = fromX(e); show(dragging); sendThrottled(dragging);
  });
  vol.addEventListener("pointermove", function (e) {
    if (dragging === null) return;
    dragging = fromX(e); show(dragging); sendThrottled(dragging);
  });
  function end() {
    if (dragging === null) return;
    Hub.send({ t: "volume", v: dragging });   // Endwert immer senden
    level = dragging; dragging = null; pending = null;
  }
  vol.addEventListener("pointerup", end);
  vol.addEventListener("pointercancel", end);

  muteBtn.addEventListener("pointerdown", function (e) {
    e.preventDefault();
    Hub.send({ t: "mute", on: !muted });
  });

  document.querySelectorAll("[data-media]").forEach(function (el) {
    el.addEventListener("pointerdown", function (e) {
      e.preventDefault();
      el.classList.add("down");
      Hub.send({ t: "media", a: el.getAttribute("data-media") });
      setTimeout(function () { el.classList.remove("down"); }, 150);
    });
  });
  show(0);
})();
