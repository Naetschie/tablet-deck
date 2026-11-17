"use strict";
// Editor am PC im Browser: Verbindung, Spiel-/Panelwahl, Speichern, Dialog „Automatisch erzeugen“ und Reiter.
// Zugang nur mit Token aus dem Taskleisten-Symbol (#k=…). Der Panel-Baukasten selbst liegt in panel.js,
// der Reiter „Dashboards“ in dash.js.
(function () {
  var token = (location.hash.match(/k=([A-Za-z0-9_-]+)/) || [])[1];
  var ws = null, layout = null, saved = "", pendingSave = null, keyNames = [];
  var games = [], cur = { game: null, panel: null };   // Spiel/Panel im Editor
  var isNew = false;   // aktuelles Panel ist ein noch nie gespeicherter Entwurf
  var asking = false, copying = false;   // Rückfrage „Kopie bearbeiten?“ offen / Kopie wird angelegt
  var BUNDLED_PREFIX = "std--";          // wie bridge/profiles.py: mitgelieferte Panels (panels/) sind schreibgeschützt
  var LOCK = "\u{1F512} ";
  var actionsFor = null;   // Spiel, für das die Palette (Spielaktionen) geladen wurde
  var $ = function (id) { return document.getElementById(id); };

  // ---------------------------------------------------------------- Verbindung
  function status(text, cls) { var s = $("status"); s.textContent = text; s.className = cls || ""; }
  function send(o) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); }
  // Das Layout gehört dem Baukasten (er ändert es an Ort und Stelle); hier wird nur getauscht
  function setLayout(l) {
    layout = l;
    if (l) PanelEditor.load(l); else PanelEditor.clear();
  }

  function connect() {
    if (!token) { status("Kein Zugangstoken – Editor über das Taskleisten-Symbol öffnen.", "err"); return; }
    ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/edit");
    ws.onopen = function () {
      actionsFor = null;
      ws.send(JSON.stringify({ t: "auth", k: token })); ws.send(JSON.stringify({ t: "games" }));
      DashEditor.onOpen();
    };
    ws.onmessage = function (ev) {
      var m = JSON.parse(ev.data);
      if (DashEditor.onMessage(m)) return;      // dash_* und deren Fehler: Reiter „Dashboards“ (dash.js)
      if (PanelEditor.onMessage(m)) return;     // actions und dessen Fehler: Palette (panel.js)
      if (m.t === "games") {
        games = m.games;
        if (!cur.game) {
          var g = games.filter(function (x) { return x.id === m.current && x.panels.length; })[0] ||
            games.filter(function (x) { return x.panels.length; })[0];
          if (g) cur = { game: g.id, panel: g.panels[0].id };
        }
        renderSelects();
        get();
      } else if (m.t === "layout") {
        keyNames = m.keys;
        PanelEditor.setKeys(m.keys, m.media);
        var dl = $("keyNames"); dl.innerHTML = "";
        keyNames.forEach(function (k) { var o = document.createElement("option"); o.value = k; dl.appendChild(o); });
        var other = m.game !== cur.game || m.panel !== cur.panel;
        if (other && isDirty()) { status("Panel nicht gefunden – Änderungen bleiben erhalten, Speichern legt es neu an", "err"); return; }
        if (!layout || !isDirty() || other) {
          cur = { game: m.game, panel: m.panel }; isNew = false;
          saved = JSON.stringify(m.layout);
          setLayout(m.layout);
          renderSelects(); syncFields(); status("Geladen", "ok");
        }
      } else if (m.t === "created" || m.t === "deleted") {
        copying = false;
        games = m.games;
        if (m.t === "created") cur = { game: m.game, panel: m.panel };
        else { var g2 = games.filter(function (x) { return x.id === cur.game; })[0]; cur.panel = g2 && g2.panels[0] ? g2.panels[0].id : null; }
        saved = ""; setLayout(null); syncFields(); renderSelects();
        if (cur.panel) get(); else status("Noch kein Panel – mit „+ Panel“ anlegen", "");
      } else if (m.t === "templates") {
        genTemplates(m);
      } else if (m.t === "draft") {
        genDraft(m);
      } else if (m.t === "saved") {
        saved = pendingSave; pendingSave = null;
        if (isNew) { isNew = false; send({ t: "games" }); }   // neues Panel in der Auswahl zeigen
        if (isDirty()) changed(); else status("Gespeichert – Tablet aktualisiert sich", "ok");
      } else if (m.t === "ai_key") {
        aiKeyShow(m);
      } else if (m.t === "bind_status") {
        if (m.game === cur.game) bindStatusShow(m);
      } else if (m.t === "bind_learn") {
        if (m.game === cur.game) learnShow(m);
      } else if (m.t === "web_found") {
        $("genWebAi").disabled = false;
        if (m.game === cur.game) webShow(m);
      } else if (m.t === "web_saved") {
        if (m.game === cur.game) {
          $("genWebOut").innerHTML = "";
          $("genWebOut").appendChild(el("p", { cls: "hint ok", text: "Als Vorlage gespeichert – jetzt oben auswählen und erzeugen." }));
          genWantTpl = m.template;
          send({ t: "templates", game: cur.game }); send({ t: "bind_status", game: cur.game });
        }
      } else if (m.t === "ai_prompt") {
        genPromptShow(m);
      } else if (m.t === "error" && /^ai_key_/.test(m.req || "")) {
        aiKeyBusy(false); aiKeyMsg("Fehler: " + m.msg, "err");
      } else if (m.t === "error" && /^bind_learn/.test(m.req || "")) {
        learnUi("idle"); learnMsg("Lernmodus: " + m.msg, true);
      } else if (m.t === "error" && /^web_/.test(m.req || "")) {
        $("genWebAi").disabled = false;
        $("genWebOut").innerHTML = ""; $("genWebOut").appendChild(el("p", { cls: "hint warn", text: m.msg }));
      } else if (m.t === "error" && m.req === "bind_status") {
        $("genBind").textContent = "Tastenbelegung nicht geprüft: " + m.msg; $("genBind").className = "hint warn";
      } else if (m.t === "error" && (m.req === "generate" || m.req === "templates" || m.req === "ai")) {
        if (m.req === "ai") $("genAiRun").disabled = false;
        $("genReport").textContent = "Fehler: " + m.msg;
      } else if (m.t === "error" && m.req === "copy") {
        copying = false;
        if (layout && isBundled()) { setLayout(JSON.parse(saved)); syncFields(); }
        status("Kopie nicht angelegt: " + m.msg, "err");
      } else if (m.t === "error") {
        pendingSave = null;
        if (m.req === "save" && isNew && m.code === "exists") {
          // Name belegt (z. B. ungültige Datei gleichen Namens): freie id wählen, Entwurf bleibt erhalten
          var taken = {}; taken[cur.panel] = 1;
          (curGame() ? curGame().panels : []).forEach(function (p) { taken[p.id] = 1; });
          cur.panel = uniqueId(cur.panel.slice(0, 36), function (x) { return taken[x]; }).replace(/_/g, "-");
          renderSelects();
          status("Name war schon vergeben – als „" + cur.panel + "“ neu benannt. Bitte erneut speichern.", "dirty");
        } else {
          status("Nicht gespeichert: " + m.msg, "err");
        }
      }
    };
    ws.onclose = function (ev) {
      DashEditor.onClose();
      // laufende KI-Anfrage: Antwort geht verloren - Knopf wieder freigeben
      if ($("genAiRun").disabled) { $("genAiRun").disabled = false; $("genReport").textContent = "Verbindung unterbrochen – KI-Ergebnis verloren, bitte erneut erzeugen."; }
      if (ev.code === 4001) { status("Zugangstoken ungültig (Bridge neu gestartet?) – Editor neu über das Taskleisten-Symbol öffnen.", "err"); return; }
      status("Verbindung zur Bridge getrennt – neuer Versuch …", "err");
      setTimeout(connect, 2000);
    };
  }
  function isDirty() { return layout && JSON.stringify(layout) !== saved; }
  // Mitgelieferte Panels (Präfix std--, nie ein ungespeicherter Entwurf) sind nur ansehbar
  function isBundled() { return !!cur.panel && !isNew && cur.panel.indexOf(BUNDLED_PREFIX) === 0; }
  // Jede Bearbeitung eines mitgelieferten Panels fragt nach einer Kopie (wie im Reiter Dashboards): ja = die Kopie
  // bekommt gleich die Änderung, nein = zurück zum Original. Die Frage läuft verzögert, nicht mitten in einer Mausaktion.
  function askCopy() {
    if (asking || copying) return;
    asking = true;
    setTimeout(function () {
      asking = false;
      if (!layout || !isBundled() || !isDirty()) return;
      if (confirm("„" + (JSON.parse(saved).title || cur.panel) + "“ ist mitgeliefert und schreibgeschützt.\n" +
          "Kopie bearbeiten? (Die Änderung landet in einer eigenen Kopie, das Original bleibt unverändert.)")) {
        copying = true;
        send({ t: "copy", game: cur.game, panel: cur.panel, layout: layout });
        status("Lege Kopie an …", "");
      } else {
        setLayout(JSON.parse(saved)); syncFields(); changed();
      }
    }, 0);
  }
  function changed() {
    if (isBundled()) {
      syncFields();
      if (isDirty()) { status("Mitgeliefert – schreibgeschützt", "dirty"); askCopy(); }
      else status("Mitgeliefert – schreibgeschützt", "");
      return;
    }
    if (document.activeElement !== $("holdMs")) syncFields();
    if (isDirty()) status("Ungespeicherte Änderungen", "dirty"); else status("Gespeichert", "ok");
  }
  // Titel und Haltezeit in der Kopfleiste (nach Laden, Rückgängig usw.)
  function syncFields() {
    $("holdMs").value = layout ? layout.holdMs || 1000 : "";
    $("holdMs").disabled = $("panelTitle").readOnly = isBundled();
    if (document.activeElement !== $("panelTitle")) $("panelTitle").value = layout ? layout.title || "" : "";
  }
  window.addEventListener("beforeunload", function (e) { if (isDirty() || DashEditor.isDirty()) { e.preventDefault(); e.returnValue = ""; } });

  $("save").onclick = function () {
    if (!layout) return;
    if (isBundled()) { status("Mitgeliefert – schreibgeschützt; zum Bearbeiten „Kopie bearbeiten“ wählen", "err"); return; }
    if (!ws || ws.readyState !== 1) { status("Keine Verbindung zur Bridge – nicht gespeichert", "err"); return; }
    var ph = 0;
    layout.pages.forEach(function (pg) { pg.buttons.forEach(function (b) { if (PanelLib.hasPlaceholder(b)) ph++; }); });
    if (ph && !confirm(ph + " Taste(n) haben noch Platzhalter-Tasten (Rollen bzw. Bild↑/Bild↓) und senden diese am "
      + "Tablet wirklich an den PC. Trotzdem speichern?")) return;
    pendingSave = JSON.stringify(layout);   // dieser Stand gilt nach der Bestätigung als gespeichert
    ws.send(JSON.stringify({ t: "save", game: cur.game, panel: cur.panel, layout: layout, new: isNew }));
    status("Speichere …", "");
  };
  $("revert").onclick = function () {
    if (!layout || !saved) return;
    if (isDirty() && !confirm("Alle ungespeicherten Änderungen verwerfen?")) return;
    setLayout(JSON.parse(saved)); syncFields(); changed();
  };
  $("holdMs").onchange = function () { if (!layout) return; layout.holdMs = parseInt(this.value, 10) || 1000; PanelEditor.checkpoint(); changed(); };
  $("panelTitle").oninput = function () { if (!layout) return; layout.title = this.value; changed(); };
  $("panelTitle").onchange = function () { PanelEditor.checkpoint(); };

  // ---------------------------------------------------------------- Spiele und Panels
  function get() { if (cur.game && cur.panel) send({ t: "get", game: cur.game, panel: cur.panel }); }
  function curGame() { return games.filter(function (g) { return g.id === cur.game; })[0]; }
  function leaveOk() { return !isDirty() || confirm("Ungespeicherte Änderungen verwerfen?"); }
  function renderSelects() {
    var gs = $("gameSel"), ps = $("panelSel");
    gs.innerHTML = ""; ps.innerHTML = "";
    games.forEach(function (g) {
      gs.appendChild(el("option", { value: g.id, text: g.name + (g.panels.length ? "" : " (noch keine Panels)") }));
    });
    gs.value = cur.game || "";
    var g = curGame();
    (g ? g.panels : []).forEach(function (p) {
      var b = p.origin === "bundled";
      ps.appendChild(el("option", { value: p.id, text: (b ? LOCK : "") + p.title + (b ? " (mitgeliefert)" : ""), cls: b ? "bundled" : "" }));
    });
    var panels = (g ? g.panels : []).map(function (p) { return { id: p.id, title: p.title }; });
    if (cur.panel && !(g && g.panels.some(function (p) { return p.id === cur.panel; }))) {
      var t = (layout && layout.title || cur.panel) + " (neu, ungespeichert)";
      ps.appendChild(el("option", { value: cur.panel, text: t }));
      panels.push({ id: cur.panel, title: layout && layout.title || cur.panel });
    }
    ps.value = cur.panel || "";
    var bundled = isBundled();
    $("dupPanel").disabled = !cur.panel; $("delPanel").disabled = !cur.panel || bundled;
    $("save").disabled = $("revert").disabled = bundled; $("panelBanner").hidden = !bundled;
    $("dupPanel").textContent = bundled ? "Kopie bearbeiten" : "Kopie";
    syncFields();
    PanelEditor.setInfo({ game: g ? g.name : "", panels: panels, panel: cur.panel });
    if (cur.game && cur.game !== actionsFor && ws && ws.readyState === 1) { actionsFor = cur.game; PanelEditor.requestActions(cur.game); }
  }
  $("gameSel").onchange = function () {
    var v = this.value;
    if (!leaveOk()) { this.value = cur.game; return; }
    var g = games.filter(function (x) { return x.id === v; })[0];
    cur = { game: v, panel: g && g.panels[0] ? g.panels[0].id : null };
    saved = ""; setLayout(null); syncFields(); renderSelects();
    if (cur.panel) get(); else status("Noch kein Panel – mit „+ Panel“ anlegen", "");
  };
  $("panelSel").onchange = function () {
    if (!leaveOk()) { this.value = cur.panel; return; }
    cur.panel = this.value; saved = ""; setLayout(null); syncFields(); get();
  };
  function slug(t) {
    return t.toLowerCase().replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss")
      .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 36) || "panel";
  }
  function newPanel(copy) {
    if (copy && isBundled()) { copyBundled(); return; }
    if (!cur.game || (copy && !layout) || !leaveOk()) return;
    var title = prompt(copy ? "Titel der Kopie:" : "Titel des neuen Panels (z. B. Bergbau):", copy ? layout.title + " (Kopie)" : "");
    if (!title) return;
    var taken = {}; (curGame() ? curGame().panels : []).forEach(function (p) { taken[p.id] = 1; });
    send({ t: "create", game: cur.game, panel: uniqueId(slug(title), function (x) { return taken[x]; }).replace(/_/g, "-"),
      title: title.slice(0, 40), copy: copy ? cur.game + "/" + cur.panel : null });
  }
  // Kopie eines mitgelieferten Panels: der Hub vergibt den Namen (<name>-eigen); das Original wird nie geändert
  function copyBundled() {
    if (!cur.panel || copying) return;
    copying = true;
    send({ t: "copy", game: cur.game, panel: cur.panel });
    status("Lege Kopie an …", "");
  }
  $("panelBannerCopy").onclick = copyBundled;
  $("newPanel").onclick = function () { newPanel(false); };
  $("dupPanel").onclick = function () { newPanel(true); };
  $("delPanel").onclick = function () {
    if (!cur.panel || isBundled() || !confirm("Panel „" + (layout && layout.title || cur.panel) + "“ löschen? (landet in profiles/.papierkorb)")) return;
    send({ t: "delete", game: cur.game, panel: cur.panel });
  };

  // ---------------------------------------------------------------- Automatisch erzeugen
  var genLast = null, genList = [];
  $("genPanel").onclick = function () {
    if (!cur.game) return;
    $("genReport").innerHTML = ""; $("genTake").disabled = true; genLast = null;
    $("genSource").textContent = "Vorlagen werden geladen …";
    $("genBind").textContent = "Tastenbelegung wird gesucht …"; $("genBind").className = "hint";
    learnUi("idle"); learnMsg("", false);
    send({ t: "templates", game: cur.game });
    send({ t: "bind_status", game: cur.game });
    send({ t: "ai_key_status" });
    send({ t: "ai_prompt" });
    $("genDlg").showModal();
  };
  $("genClose").onclick = function () { $("genDlg").close(); };

  // ---------------------------------------------------------------- Einstellungen: KI-Schlüssel
  // Der Schlüssel geht nur zum Hub (Datei secrets/anthropic.key); zurück kommt nur „hinterlegt ja/nein“.
  var aiKeySet = null, aiProvTouched = false;
  function aiProv() { return $("aiProv").value || "anthropic"; }
  // Anbieter wechseln = als aktiv speichern; Schlüsselzustand des gewählten Anbieters zeigen
  $("aiProv").onchange = function () {
    aiProvTouched = true; aiKeyMsg("Wird geladen …");
    send({ t: "ai_settings_set", provider: aiProv() });
  };
  $("aiModel").onchange = function () { send({ t: "ai_settings_set", provider: aiProv(), openai_model: $("aiModel").value.trim() }); };
  function aiKeyMsg(text, cls) { var e = $("aiKeyState"); e.textContent = text; e.className = "hint " + (cls || ""); }
  function aiKeyBusy(b) { ["aiKeySave", "aiKeyCheck", "aiKeyDel"].forEach(function (id) { $(id).disabled = b; }); if (!b) aiKeyButtons(); }
  function aiKeyButtons() { $("aiKeyCheck").disabled = !aiKeySet; $("aiKeyDel").disabled = !aiKeySet; }
  function aiKeyShow(m) {
    // verspätete Antwort für einen anderen Anbieter (schneller Wechsel): nur den Hinweis im Dialog „Automatisch“ nutzen
    var stale = aiProvTouched && m.provider && m.provider !== aiProv();
    var activeSet0 = m.active_set !== undefined ? !!m.active_set : !!m.set;
    if (stale) { $("genAiNoKey").hidden = activeSet0; return; }
    aiKeySet = !!m.set;
    if (m.active) {
      if (!$("setDlg").open || !aiProvTouched) $("aiProv").value = m.provider || m.active;
      if (document.activeElement !== $("aiModel")) $("aiModel").value = m.openai_model || "";
      $("aiModelLab").hidden = $("aiProv").value !== "openai";
      $("aiKeyIn").placeholder = $("aiProv").value === "openai" ? "sk-…" : "sk-ant-…";
    }
    var activeSet = m.active_set !== undefined ? !!m.active_set : aiKeySet;
    $("genAiNoKey").hidden = activeSet;
    $("genAiRun").title = activeSet ? "" : "Erst unter ⚙ Einstellungen einen API-Schlüssel eintragen";
    aiKeyBusy(false);
    var base = aiKeySet ? "Schlüssel hinterlegt." : "Kein Schlüssel hinterlegt.";
    if (m.check) aiKeyMsg(base + " Prüfung: " + m.check.msg, m.check.ok ? "ok" : "err");
    else if (m.msg) aiKeyMsg(base + " (" + m.msg + ")", aiKeySet ? "ok" : "");
    else aiKeyMsg(base, aiKeySet ? "ok" : "");
  }
  function openSettings() {
    $("aiKeyIn").value = ""; aiProvTouched = false; aiKeyMsg("Wird geladen …"); send({ t: "ai_key_status" });
    if (!$("setDlg").open) $("setDlg").showModal();
    $("aiKeyIn").focus();
  }
  $("setBtn").onclick = openSettings;
  $("genAiSet").onclick = openSettings;
  $("setClose").onclick = function () { $("aiKeyIn").value = ""; $("setDlg").close(); };
  $("setDlg").addEventListener("close", function () { $("aiKeyIn").value = ""; });
  $("aiKeySave").onclick = function () {
    var k = $("aiKeyIn").value.trim();
    var okFmt = aiProv() === "openai" ? /^sk-[A-Za-z0-9_\-]{20,300}$/.test(k) && !/^sk-ant-/.test(k) : /^sk-ant-[A-Za-z0-9_\-]{20,250}$/.test(k);
    if (!okFmt) { aiKeyMsg(aiProv() === "openai" ? "Das sieht nicht wie ein OpenAI-Schlüssel aus (beginnt mit sk-)." :
      "Das sieht nicht wie ein Anthropic-API-Schlüssel aus (beginnt mit sk-ant-).", "err"); return; }
    if (!ws || ws.readyState !== 1) { aiKeyMsg("Keine Verbindung zur Bridge.", "err"); return; }
    aiKeyBusy(true); aiKeyMsg("Speichere …");
    send({ t: "ai_key_set", provider: aiProv(), key: k });
    $("aiKeyIn").value = "";
  };
  $("aiKeyIn").addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); $("aiKeySave").click(); } });
  $("aiKeyCheck").onclick = function () { aiKeyBusy(true); aiKeyMsg("Prüfe beim Anbieter …"); send({ t: "ai_key_check", provider: aiProv() }); };
  $("aiKeyDel").onclick = function () {
    if (!confirm("API-Schlüssel von diesem PC entfernen? „Mit KI erstellen“ geht danach erst wieder mit neuem Schlüssel.")) return;
    aiKeyBusy(true); send({ t: "ai_key_delete", provider: aiProv() });
  };
  // Prompt der KI: fester Teil nur zur Ansicht, änderbarer Teil wird in diesem Browser gemerkt
  var PROMPT_STORE = "td-ai-style-prompt", promptDefault = "";
  function storeGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function storeSet(k, v) { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* egal */ } }
  function genPromptShow(m) {
    promptDefault = m.style || "";
    $("genPromptFixed").textContent = m.fixed || "";
    $("genPromptStyle").maxLength = m.max_style || 4000;
    var own = storeGet(PROMPT_STORE);
    $("genPromptStyle").value = own !== null ? own : promptDefault;
  }
  $("genPromptStyle").addEventListener("input", function () {
    var v = $("genPromptStyle").value;
    storeSet(PROMPT_STORE, v === promptDefault ? null : v);
  });
  $("genPromptReset").onclick = function () { $("genPromptStyle").value = promptDefault; storeSet(PROMPT_STORE, null); };
  // Woher die Tasten kommen (Adapter oder generische Suche in den Spielordnern) und Lernmodus
  function bindStatusShow(m) {
    var cls = m.state === "read" && m.ok ? "ok" : m.state === "recognized" ? "check" : "warn";
    var txt = m.ok ? m.count + " Aktionen mit Taste – " + m.source
      : "Achtung: " + m.source + ". Erzeugte Tasten haben dann keine Taste (gestrichelt).";
    $("genBind").textContent = txt; $("genBind").className = "hint " + cls;
    $("genLearnRow").hidden = !!m.adapter;           // Spiele mit eigenem Adapter (Star Citizen) brauchen das nicht
    $("genLearnForget").hidden = !m.learned;
  }
  function learnMsg(t, warn) { var e = $("genLearnMsg"); e.hidden = !t; e.textContent = t || ""; e.className = "hint" + (warn ? " warn" : ""); }
  function learnUi(step) {
    $("genLearn").hidden = step === "wait"; $("genLearnDone").hidden = step !== "wait"; $("genLearnCancel").hidden = step !== "wait";
  }
  function learnShow(m) {
    if (m.step === "started") {
      learnUi("wait");
      learnMsg("Jetzt im Spiel eine Taste ändern und die Einstellungen speichern (gern wieder zurückstellen), dann „Fertig“ klicken. " +
        "(" + m.files + " Dateien beobachtet)");
    } else if (m.step === "done") {
      learnUi("idle");
      learnMsg(m.msg + (m.changed && m.changed.length ? " · geändert: " + m.changed.join(", ") : ""), !m.found);
      send({ t: "bind_status", game: cur.game });
    } else if (m.step === "forgotten") {
      learnMsg("Gelernte Datei vergessen – es wird wieder automatisch gesucht.", false);
      send({ t: "bind_status", game: cur.game });
    }
  }
  $("genLearn").onclick = function () { learnMsg("Merke den Zustand der Spieldateien …", false); send({ t: "bind_learn_start", game: cur.game }); };
  $("genLearnDone").onclick = function () { learnMsg("Suche geänderte Dateien …", false); send({ t: "bind_learn_done", game: cur.game }); };
  $("genLearnCancel").onclick = function () { learnUi("idle"); learnMsg("", false); };
  $("genLearnForget").onclick = function () { send({ t: "bind_learn_forget", game: cur.game }); };

  // Standardtasten aus dem Netz: suchen -> Vorschau mit Quelle -> speichern
  var genWantTpl = null;
  function webShow(m) {
    var box = $("genWebOut"); box.innerHTML = "";
    var link = el("a", { text: m.title || m.url });
    link.href = m.url; link.target = "_blank"; link.rel = "noopener noreferrer";
    box.appendChild(el("p", { cls: "hint" }, [document.createTextNode(m.site + ": " + m.count + " Tasten – "), link]));
    var tb = el("tbody");
    m.rows.forEach(function (r) { tb.appendChild(el("tr", {}, [el("td", { text: r[0] }), el("td", { text: r[1] }), el("td", { cls: "k", text: r[2] })])); });
    box.appendChild(el("table", { cls: "rep" }, [el("thead", {}, [el("tr", {}, ["Bereich", "Aktion", "Taste"].map(function (h) { return el("th", { text: h }); }))]), tb]));
    if (m.others && m.others.length) box.appendChild(el("p", { cls: "hint", text: "Weitere Treffer: " + m.others.map(function (o) { return o.title; }).join(" · ") +
      " – bei Bedarf deren Adresse einfügen." }));
    box.appendChild(el("div", { cls: "row end" }, [el("button", { id: "genWebSave", text: "Als Vorlage speichern" })]));
    $("genWebSave").onclick = function () { send({ t: "web_save", game: cur.game }); };
  }
  $("genWebAi").onclick = function () {
    if (!cur.game) return;
    $("genWebAi").disabled = true;   // kostenpflichtig: nicht doppelt
    $("genWebOut").innerHTML = ""; $("genWebOut").appendChild(el("p", { cls: "hint", text: "KI sucht und liest Seiten, danach Prüfung … (meist 1–3 Minuten)" }));
    send({ t: "web_find", game: cur.game, ai: true });
  };
  $("genWebFind").onclick = function () {
    if (!cur.game) return;
    $("genWebOut").innerHTML = ""; $("genWebOut").appendChild(el("p", { cls: "hint", text: "Suche und lese die Seite …" }));
    send({ t: "web_find", game: cur.game, url: $("genWebUrl").value.trim() || null });
  };
  function genTplSource() {
    var t = genList.filter(function (x) { return x.id === $("genTpl").value; })[0], s = t && t.source, box = $("genTplSource");
    box.innerHTML = "";
    if (!s) return;
    box.appendChild(document.createTextNode("Tasten der Vorlage aus: " + (s.site || "?") + (s.note ? " (" + s.note + ")" : "") +
      (s.date ? ", Stand " + s.date : "") + (s.url ? " – " : "")));
    if (s.url && /^https?:\/\//i.test(s.url)) { var a = el("a", { text: "Quelle" }); a.href = s.url; a.target = "_blank"; a.rel = "noopener noreferrer"; box.appendChild(a); }
  }

  function genOptions() { return { style: $("genStyle").value, skip_device: $("genSkipDev").checked }; }
  function genStyleHint() {
    var t = genList.filter(function (x) { return x.id === $("genTpl").value; })[0];
    $("genStyleHint").textContent = t && !t.semantic ? "Diese Vorlage hat feste Seiten – die Darstellung gilt nur für " +
      "neue Vorlagen und „Mit KI erstellen“." : "";
  }
  $("genStyle").onchange = function () { $("genReport").innerHTML = ""; $("genTake").disabled = true; };
  $("genSkipDev").onchange = $("genStyle").onchange;

  function genTemplates(m) {
    genList = m.templates;
    var sel = $("genTpl"); sel.innerHTML = "";
    $("genRun").disabled = !genList.length;
    $("genAi").open = !genList.length;
    if (!genList.length) {
      $("genSource").textContent = "Für dieses Spiel gibt es noch keine Vorlage – unten mit KI erstellen.";
      renderGenPages(); return;
    }
    $("genSource").textContent = "Tasten kommen aus deiner Belegung im Spiel, sonst aus der Vorlage (Rückfall).";
    genList.forEach(function (t) { sel.appendChild(el("option", { value: t.id, text: t.title })); });
    sel.appendChild(el("option", { value: "", text: "– keine Vorlage: mit KI neu erstellen –" }));
    if (genWantTpl && genList.some(function (x) { return x.id === genWantTpl; })) { sel.value = genWantTpl; genWantTpl = null; }
    renderGenPages(); genStyleHint(); genTplSource();
  }
  function renderGenPages() {
    var box = $("genPages"); box.innerHTML = "";
    var t = genList.filter(function (x) { return x.id === $("genTpl").value; })[0];
    (t ? t.pages : []).forEach(function (p) {
      var c = el("input", { type: "checkbox", value: p.id }); c.checked = true;
      box.appendChild(el("label", { cls: "check" }, [c, document.createTextNode(p.title)]));
    });
  }
  $("genTpl").onchange = function () {
    var none = !$("genTpl").value;   // ganz neu: nur die KI
    $("genRun").disabled = none; if (none) $("genAi").open = true;
    renderGenPages(); genStyleHint(); genTplSource(); $("genReport").innerHTML = ""; $("genTake").disabled = true;
  };
  $("genAiRun").onclick = function () {
    if (!cur.game) return;
    if (!ws || ws.readyState !== 1) { $("genReport").textContent = "Keine Verbindung zum Hub – bitte erneut versuchen."; return; }
    $("genAiRun").disabled = true;   // kostenpflichtig: nicht doppelt auslösen
    var o = genOptions();
    send({ t: "ai", game: cur.game, hint: $("genHint").value, prompt: $("genPromptStyle").value || null,
      style: o.style, skip_device: o.skip_device });
    $("genReport").textContent = "KI erstellt die Vorlage … (dauert meist unter einer Minute)";
    $("genTake").disabled = true;
  };
  $("genRun").onclick = function () {
    var tid = $("genTpl").value; if (!tid) return;
    var pages = Array.prototype.filter.call($("genPages").querySelectorAll("input"), function (c) { return c.checked; })
      .map(function (c) { return c.value; });
    if (!pages.length) { $("genReport").textContent = "Mindestens eine Seite wählen."; return; }
    var o = genOptions();
    send({ t: "generate", game: cur.game, template: tid, pages: pages, style: o.style, skip_device: o.skip_device });
    $("genReport").textContent = "Erzeuge …";
  };
  function genDraft(m) {
    if (m.template === "ki") $("genAiRun").disabled = false;
    if (m.game !== cur.game || (m.template !== "ki" && m.template !== $("genTpl").value)) return;   // inzwischen andere Vorlage gewählt
    var lay = m.layout, rows = m.report;   // der Hub hat die gewählten Seiten schon gefiltert
    genLast = { layout: lay, template: m.template };
    var ok = rows.filter(function (r) { return r.source === "Belegung"; }).length;
    var miss = rows.filter(function (r) { return r.source === "fehlt"; }).length;
    var gone = rows.filter(function (r) { return r.source === "weggelassen"; }).length;
    rows = rows.filter(function (r) { return r.source !== "weggelassen"; }).concat(
      rows.filter(function (r) { return r.source === "weggelassen"; }));   // Weggelassenes ans Ende
    var box = $("genReport"); box.innerHTML = "";
    box.appendChild(el("p", { cls: "gen-sum", text: "Quelle: " + m.source + " · " + (rows.length - gone) + " Tasten: " + ok +
      " aus deiner Belegung, " + (rows.length - ok - miss - gone) + " aus der Vorlage, " + miss + " ohne Taste" +
      (gone ? ", " + gone + " weggelassen (Joystick/Gamepad)" : "") }));
    var tb = el("tbody");
    rows.forEach(function (r) {
      var note = r.note || "";
      if (r.source === "fehlt" && r.suggest) note += (note ? " – " : "") + "Vorschlag: im Spiel auf " + r.suggest + " legen";
      tb.appendChild(el("tr", { cls: r.source === "fehlt" ? "fehlt" : r.source === "weggelassen" ? "weg" : "" }, [
        el("td", { text: r.page }), el("td", { text: r.label }), el("td", { cls: "k", text: r.key || "–" }),
        el("td", { text: r.source }), el("td", { text: note })]));
    });
    var head = el("tr", {}, ["Seite", "Taste", "Kürzel", "Quelle", "Hinweis"].map(function (h) { return el("th", { text: h }); }));
    box.appendChild(el("table", { cls: "rep" }, [el("thead", {}, [head]), tb]));
    $("genTake").disabled = !lay.pages.length;
  }
  $("genTake").onclick = function () {
    if (!genLast || !leaveOk()) return;
    var panels = curGame() ? curGame().panels : [], taken = {}, titles = {};
    panels.forEach(function (p) { taken[p.id] = 1; titles[p.title] = 1; });
    var base = (genLast.layout.title || (genLast.template === "ki" ? "KI-Panel" : genLast.template)).slice(0, 36);
    var id = uniqueId(slug(base), function (x) { return taken[x]; }).replace(/_/g, "-");
    var t = base, n = 2;
    while (titles[t]) t = base + " " + (n++);
    genLast.layout.title = t;
    cur.panel = id; saved = ""; isNew = true;
    setLayout(genLast.layout);      // der Entwurf öffnet sich im Baukasten
    $("genDlg").close();
    renderSelects(); syncFields();
    status("Entwurf „" + t + "“ – noch nicht gespeichert. Anpassen, dann Speichern legt das Panel an.", "dirty");
  };

  // ---------------------------------------------------------------- Hilfen
  function el(tag, props, children) {
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
  function uniqueId(base, taken) { var i = 1, id = base; while (taken(id)) id = base + "_" + (++i); return id; }

  // ---------------------------------------------------------------- Reiter Panels / Dashboards
  // Der Panel-Editor bleibt beim Wechsel unverändert (nur ausgeblendet)
  var dashTab = false;
  function showTab(name) {
    var dash = name === "dash";
    if (dashTab && !dash && !DashEditor.canLeave()) return;     // ungespeicherte Dashboard-Änderungen: nachfragen
    dashTab = dash;
    $("viewPanels").hidden = dash; $("toolbar").hidden = dash; $("panelTools").hidden = dash;
    $("viewDash").hidden = !dash; $("dashToolbar").hidden = !dash;
    $("tabBtnPanels").className = dash ? "" : "on"; $("tabBtnDash").className = dash ? "on" : "";
    try { sessionStorage.setItem("editorTab", name); } catch (e) { /* ohne Speicher: Panels */ }
    if (dash) { PanelEditor.deactivate(); DashEditor.activate(); }
    else { DashEditor.deactivate(); PanelEditor.activate(); if (layout) changed(); else status("", ""); }
  }
  Array.prototype.forEach.call($("mainTabs").querySelectorAll("button"), function (bt) {
    bt.onclick = function () { PanelEditor.stopCapture(); showTab(bt.getAttribute("data-tab")); };
  });

  // Strg+S speichert
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); if (dashTab) DashEditor.save(); else $("save").click(); }
  });
  PanelEditor.init({ send: send, status: status, changed: changed });
  DashEditor.init({ send: send, status: status, isOpen: function () { return !!ws && ws.readyState === 1; } });
  PanelEditor.activate();
  connect();
  try { if (sessionStorage.getItem("editorTab") === "dash") showTab("dash"); } catch (e) { /* egal */ }
})();
