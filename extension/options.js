"use strict";
const api = typeof browser !== "undefined" ? browser : chrome;
const key = document.getElementById("key"), port = document.getElementById("port");
const status = document.getElementById("status");

api.storage.local.get({ key: "", port: 8765 }).then((s) => { key.value = s.key; port.value = s.port; });

document.getElementById("save").addEventListener("click", async () => {
  const p = Number(port.value);
  if (!(p >= 1024 && p <= 65535)) { status.textContent = "Port ungültig"; return; }
  await api.storage.local.set({ key: key.value.trim(), port: p });
  status.textContent = "gespeichert";
  setTimeout(() => (status.textContent = ""), 2000);
});
