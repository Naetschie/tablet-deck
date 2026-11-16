"use strict";
// Schickt eine URL an die Tablet Deck Bridge (ws://127.0.0.1:8765/send). Anmeldung mit dem Sende-Schlüssel
// (Taskleisten-Symbol -> "Schlüssel für Browser-Erweiterung kopieren", in den Optionen einfügen). Der
// Schlüssel erlaubt nur das Senden von Webseiten, keine Tasten oder Maus.
const api = typeof browser !== "undefined" ? browser : chrome;
// Firefox: browser.menus (kann auch den Tab-Kontext), Chrome: chrome.contextMenus
const menus = api.menus || api.contextMenus;

async function settings() {
  const s = await api.storage.local.get({ key: "", port: 8765 });
  return { key: s.key.trim(), port: Number(s.port) || 8765 };
}

function badge(text, color) {
  api.action.setBadgeBackgroundColor({ color });
  api.action.setBadgeText({ text });
  setTimeout(() => api.action.setBadgeText({ text: "" }), 2500);
}

async function sendUrl(url) {
  if (!/^https?:\/\//i.test(url || "")) { badge("!", "#e5484d"); return; }
  const { key, port } = await settings();
  if (!key) { api.runtime.openOptionsPage(); return; }
  try {
    const reply = await new Promise((resolve, reject) => {
      const ws = new WebSocket(`ws://127.0.0.1:${port}/send`);
      const timer = setTimeout(() => { ws.close(); reject(new Error("Zeitüberschreitung")); }, 5000);
      ws.onopen = () => {
        ws.send(JSON.stringify({ t: "auth", k: key }));
        ws.send(JSON.stringify({ t: "open", url }));
      };
      ws.onmessage = (ev) => { clearTimeout(timer); ws.close(); resolve(JSON.parse(ev.data)); };
      ws.onclose = (ev) => { clearTimeout(timer); reject(new Error(ev.code === 4001 ? "Schlüssel falsch" : "Bridge nicht erreichbar")); };
      ws.onerror = () => {};
    });
    if (reply.t === "ok") badge("✓", "#3ddc84");
    else { badge("!", "#e5484d"); console.warn("Tablet Deck:", reply.msg); }
  } catch (e) {
    badge("!", "#e5484d");
    console.warn("Tablet Deck:", e.message);
  }
}

// Beim Installieren/Update und bei jedem Browserstart neu anlegen (Firefox behält sie nicht immer;
// removeAll verhindert "duplicate id" nach einem Update)
function createMenus() {
  const add = (props) => menus.create(props, () => {
    const err = api.runtime.lastError;
    if (err) console.warn("Tablet Deck: Menü", props.id, "nicht angelegt:", err.message);
  });
  // Promise-Variante: Firefox (browser.*) kennt keinen Callback, Chrome MV3 liefert ohne Callback ebenfalls eine Promise
  Promise.resolve(menus.removeAll()).then(() => {
    add({ id: "page", title: "Seite ans Tablet senden", contexts: ["page"] });
    add({ id: "link", title: "Link ans Tablet senden", contexts: ["link"] });
    add({ id: "image", title: "Bild ans Tablet senden", contexts: ["image"] });
    // Rechtsklick auf einen Tab gibt es nur in Firefox (Chrome kennt den Kontext "tab" nicht)
    if (typeof browser !== "undefined") add({ id: "tab", title: "Tab ans Tablet senden", contexts: ["tab"] });
    console.info("Tablet Deck: Menüs angelegt über", api.menus ? "menus" : "contextMenus");
  });
}
api.runtime.onInstalled.addListener(createMenus);
api.runtime.onStartup.addListener(createMenus);

menus.onClicked.addListener((info, tab) => {
  const url = info.menuItemId === "link" ? info.linkUrl
    : info.menuItemId === "image" ? info.srcUrl
    : info.menuItemId === "tab" ? (tab && tab.url)
    : (info.pageUrl || (tab && tab.url));
  sendUrl(url);
});

api.action.onClicked.addListener((tab) => sendUrl(tab && tab.url));
