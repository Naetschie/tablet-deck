"use strict";
// Tests für web/editor/panellib.js (node --test tests/js/panellib.test.js); gültig = Prüfung durch bridge/layout.py
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const L = require("../../web/editor/panellib.js");

const ROOT = path.resolve(__dirname, "..", "..");
function pyValid(layout) {   // null = gültig, sonst Fehlermeldung; ohne Python: undefined
  try {
    const out = execFileSync("python", ["-c",
      "import sys, json; from bridge.layout import validate_layout\n" +
      "try:\n validate_layout(json.load(sys.stdin)); print('ok')\nexcept ValueError as e:\n print('ERR ' + str(e))"],
    { cwd: ROOT, input: JSON.stringify(layout), encoding: "utf8" }).trim();
    return out === "ok" ? null : out;
  } catch (e) { return undefined; }
}
const needPy = { skip: pyValid({ pages: [{ id: "a", title: "A", buttons: [] }] }) === undefined ? "Python nicht verfügbar" : false };

const free = (buttons, extra) => Object.assign({ id: "f", title: "F", type: "free", cols: 6, rows: 3, buttons }, extra || {});
const B = (id, x, y, w, h, extra) => Object.assign({ id, label: id.toUpperCase(), mode: "tap", x, y, w, h }, extra || {});
const lay = (...pages) => ({ title: "T", pages });

test("Bausteine sind gültige Tasten, auf jeder Seitenart", needPy, () => {
  for (const type of ["grid", "free", "shield"]) {
    for (const blk of L.BLOCKS) {
      if (blk.free && type !== "free") continue;   // Rahmen/Beschriftung nur auf freien Seiten
      const l = lay({ id: "s", title: "S", type, buttons: [] }, { id: "t", title: "T", buttons: [] });
      if (type === "free") Object.assign(l.pages[0], { cols: 12, rows: 8 });
      const b = L.newBlock(blk.kind, l, l.pages[0]);
      L.addButton(l.pages[0], b, { kind: blk.kind });
      assert.equal(pyValid(l), null, type + "/" + blk.kind);
    }
  }
});

test("Baustein Seiten-Link zeigt auf eine andere Seite, sonst auf die eigene", () => {
  const l = lay({ id: "a", title: "A", buttons: [] }, { id: "b", title: "B", buttons: [] });
  assert.equal(L.newBlock("page", l, l.pages[1]).page, "a");
  const one = lay({ id: "a", title: "A", buttons: [] });
  assert.equal(L.newBlock("page", one, one.pages[0]).page, "a");
});

test("IDs der Bausteine sind über das ganze Panel eindeutig", () => {
  const l = lay({ id: "a", title: "A", buttons: [{ id: "a_taste", label: "x" }] }, { id: "b", title: "B", buttons: [] });
  assert.equal(L.newBlock("key", l, l.pages[0]).id, "a_taste_2");
});

test("Platzhalter werden erkannt", () => {
  const l = lay({ id: "a", title: "A", buttons: [] });
  assert.ok(L.hasPlaceholder(L.newBlock("states", l, l.pages[0])));
  assert.ok(L.hasPlaceholder(L.newBlock("slider", l, l.pages[0])));
  assert.ok(!L.hasPlaceholder(L.newBlock("key", l, l.pages[0])));
});

test("Spielaktion -> Taste: ohne Lage, mit Überschrift, eindeutige ID", needPy, () => {
  const l = lay({ id: "a", title: "A", type: "grid", buttons: [{ id: "ping", label: "x" }] });
  const e = { button: { id: "ping", label: "PING", sc: "v_ping", key: "P", x: 3, zone: "front", wide: true }, group: "Modus", action: "v_ping" };
  const b = L.buttonFromAction(e, l, l.pages[0]);
  assert.deepEqual(b, { id: "ping_2", label: "PING", sc: "v_ping", key: "P", group: "Modus" });
  assert.equal(e.button.x, 3);                                   // Eingabe unverändert
  L.addButton(l.pages[0], b, {});
  assert.equal(pyValid(l), null);
  const sh = { id: "s", title: "S", type: "shield", buttons: [] };
  assert.equal(L.buttonFromAction(e, lay(sh), sh).group, undefined);
});

test("Aktionen im Panel werden gekennzeichnet", () => {
  const l = lay({ id: "a", title: "A", buttons: [{ id: "x", label: "X", sc: "v_ping" }, { id: "m", label: "M", macro: [{ wait: 1 }] }] });
  const p = L.presentSet(l);
  assert.ok(L.isPresent({ action: "v_ping", button: { id: "q" } }, p));
  assert.ok(!L.isPresent({ action: "v_andere", button: { id: "q" } }, p));
  assert.ok(L.isPresent({ action: "", button: { id: "m" } }, p));
});

test("filterActions: Suche in Beschriftung, Taste, Gruppe, Seite; leere Seiten entfallen", () => {
  const t = [{ id: "t", title: "Pilot", pages: [
    { id: "p1", title: "Flug", actions: [{ button: { label: "FAHRWERK" }, action: "v_gear", key: "N", group: "Schiff" },
      { button: { label: "LICHT" }, action: "v_lights", key: "L", group: "Schiff" }] },
    { id: "p2", title: "Waffen", actions: [{ button: { label: "FEUER" }, action: "v_fire", key: "", group: "" }] }] }];
  assert.equal(L.filterActions(t, "")[0].pages.length, 2);
  const r = L.filterActions(t, "fahr");
  assert.equal(r[0].pages.length, 1);
  assert.equal(r[0].pages[0].actions.length, 1);
  assert.equal(L.filterActions(t, "v_fire")[0].pages[0].id, "p2");
  assert.equal(L.filterActions(t, "waffen")[0].pages[0].actions.length, 1);
  assert.deepEqual(L.filterActions(t, "xyz"), []);
});

test("freeSpot findet die erste freie Stelle, null wenn nichts passt", () => {
  const p = free([B("a", 0, 0, 2, 1), B("b", 2, 0, 4, 1)]);
  assert.deepEqual(L.freeSpot(p, 2, 1), { x: 0, y: 1 });
  assert.deepEqual(L.freeSpot(p, 6, 3), null);
  assert.deepEqual(L.freeSpot(p, 2, 1, "a"), { x: 0, y: 0 });     // eigene Taste zählt nicht
});

test("nearestFree: nächste freie Stelle zur Zielzelle", () => {
  const p = free([B("a", 2, 1, 2, 1)]);
  assert.deepEqual(L.nearestFree(p, 2, 1, 4, 2), { x: 4, y: 2 });
  assert.deepEqual(L.nearestFree(p, 2, 1, 2, 1), { x: 2, y: 0 });  // belegt: gleich weit oben/unten, oben zuerst
  assert.equal(L.nearestFree(free([B("a", 0, 0, 6, 3)]), 1, 1, 0, 0), null);
});

test("Einfügen an Zelle (frei): Zielzelle, sonst nächste freie; Klick: erste freie", () => {
  const p = free([B("a", 0, 0, 2, 1)]);
  const b1 = { id: "n1", label: "N" };
  assert.deepEqual(L.addButton(p, b1, { kind: "key", at: { x: 4, y: 2 } }), { overlap: false });
  assert.deepEqual([b1.x, b1.y, b1.w, b1.h], [4, 2, 2, 1]);
  const b2 = { id: "n2", label: "N" };
  L.addButton(p, b2, { kind: "key", at: { x: 0, y: 0 } });        // belegt -> nächste freie
  assert.deepEqual([b2.x, b2.y], [0, 1]);
  const b3 = { id: "n3", label: "N" };
  L.addButton(p, b3, { kind: "key" });
  assert.deepEqual([b3.x, b3.y], [2, 0]);
  assert.equal(Object.keys(L.overlapSet(p)).length, 0);
});

test("Einfügen: Regler ist 4 breit, passt sich schmalem Raster an", () => {
  const p = free([], { cols: 3 });
  const b = { id: "s", label: "S", slider: { up: "A", down: "B", steps: 5 } };
  L.addButton(p, b, { kind: "slider" });
  assert.equal(b.w, 3);
});

test("Einfügen in volle Seite: Zeilen wachsen bis 16, dann Überlappung gemeldet", () => {
  const p = free([B("a", 0, 0, 6, 3)]);
  const b = { id: "n", label: "N" };
  assert.deepEqual(L.addButton(p, b, { kind: "key" }), { overlap: false });
  assert.equal(p.rows, 4);
  assert.equal(b.y, 3);
  const full = free([B("a", 0, 0, 6, 16)], { rows: 16 });
  const c = { id: "m", label: "M" };
  assert.deepEqual(L.addButton(full, c, { kind: "key" }), { overlap: true });
});

test("Einfügen (automatisch): anhängen, vor einer Taste, mit Überschrift", () => {
  const p = { id: "g", title: "G", type: "grid", buttons: [{ id: "a", label: "A" }, { id: "b", label: "B", group: "X" }] };
  L.addButton(p, { id: "c", label: "C" }, {});
  L.addButton(p, { id: "d", label: "D" }, { index: 1, group: "X" });
  assert.deepEqual(p.buttons.map((b) => b.id), ["a", "d", "b", "c"]);
  assert.equal(p.buttons[1].group, "X");
  L.addButton(p, { id: "e", label: "E", group: "Z" }, { group: "" });
  assert.equal(p.buttons[4].group, undefined);
});

test("Einfügen (Schild): erste freie Zone", () => {
  const p = { id: "s", title: "S", type: "shield", buttons: [{ id: "a", label: "A", zone: "front" }] };
  const b = { id: "b", label: "B" };
  L.addButton(p, b, {});
  assert.equal(b.zone, "back");
  const c = { id: "c", label: "C" };
  L.addButton(p, c, { zone: "reset" });
  assert.equal(c.zone, "reset");
});

test("grid -> free: Positionen aus der Anordnung, Tasten bleiben, gültig", needPy, () => {
  const p = { id: "g", title: "G", type: "grid", buttons: [
    { id: "a", label: "A", key: "A", group: "X" }, { id: "b", label: "B", key: "B", group: "X" },
    { id: "c", label: "C", key: "C", group: "Y" }, { id: "w", label: "W", key: "W", wide: true }] };
  const orig = JSON.stringify(p);
  const f = L.toFree(p);
  assert.equal(JSON.stringify(p), orig);                         // toFree verändert nichts
  assert.equal(f.type, "free");
  assert.deepEqual(f.buttons.map((b) => b.id), ["a", "b", "c", "w"]);
  assert.deepEqual([f.buttons[0].x, f.buttons[0].y, f.buttons[1].x, f.buttons[2].y], [0, 0, 2, 1]);   // neue Gruppe = neue Reihe
  assert.equal(f.buttons[3].w, 12);
  assert.equal(f.buttons[0].group, "X");                         // Überschrift bleibt erhalten
  assert.equal(pyValid(lay(f)), null);
  assert.equal(Object.keys(L.overlapSet(f)).length, 0);
  assert.ok(L.setPageType(p, "free"));
  assert.equal(p.type, "free");
  assert.deepEqual(p.buttons.map((b) => [b.x, b.y, b.w, b.h]), f.buttons.map((b) => [b.x, b.y, b.w, b.h]));
});

test("grid -> free mit zu vielen Tasten: abgelehnt, Seite bleibt", () => {
  const buttons = [];
  for (let i = 0; i < 400; i++) buttons.push({ id: "b" + i, label: "B", wide: true, group: "G" + i });
  const p = { id: "g", title: "G", type: "grid", buttons };
  assert.equal(L.toFree(p), null);
  assert.equal(L.setPageType(p, "free"), false);
  assert.equal(p.type, "grid");
  assert.equal(p.buttons[0].x, undefined);
});

test("Rahmen sind Hintergrund, Zonen ohne Lage zählen nicht", () => {
  const p = free([{ kind: "frame", id: "f", label: "R", x: 0, y: 0, w: 6, h: 4 }, B("a", 1, 1, 2, 1),
    { kind: "shield", id: "s", x: 6, y: 0, w: 4, h: 3 }, { id: "z", label: "V", zone: "front" }], { cols: 12, rows: 8 });
  assert.deepEqual(Object.keys(L.overlapSet(p)), []);                          // Taste auf Rahmen: keine Überlappung
  assert.deepEqual(L.insideFrame(p, p.buttons[0]), ["a"]);
  assert.deepEqual(L.toItems(p).map((i) => i.id), ["f", "a", "s"]);   // Zone hat keine Lage
  const b = { id: "n", label: "N" };
  L.addButton(p, b, { kind: "key" });
  assert.ok(!(b.x < 10 && b.y < 3 && b.x + b.w > 6));            // nicht auf das Schiff
  assert.deepEqual(L.duplicate({ pages: [p] }, p, ["s", "z"]), []);   // Schiff/Zonen nie doppelt
  L.setPageType(p, "grid");
  assert.deepEqual(p.buttons.map((x) => x.id), ["a", "z", "n"]);   // Rahmen/Schiff entfallen
  assert.equal(p.buttons[1].zone, undefined);
});

test("Review a9443c3: Raster ändern lässt Zonen ohne Lage, Rahmen ohne Tastenfelder, Art-Wechsel ohne look", () => {
  const p = free([{ kind: "frame", id: "f", label: "R", x: 0, y: 0, w: 6, h: 4 }, B("a", 1, 1, 2, 1, { style: "accent" }),
    { kind: "shield", id: "s", x: 6, y: 0, w: 4, h: 3 }, { id: "z", label: "V", zone: "front" }], { cols: 12, rows: 8 });
  assert.equal(L.setGrid(p, 10, 6), true);
  assert.equal(p.buttons[3].x, undefined);
  L.setShared([p.buttons[0], p.buttons[1]], "style", "danger", "free");
  L.setShared([p.buttons[0], p.buttons[1]], "mode", "hold-confirm", "free");
  assert.equal(p.buttons[0].style, undefined);
  assert.equal(p.buttons[0].mode, undefined);
  assert.equal(p.buttons[1].style, "danger");
  const k = { id: "k", label: "K", key: "F1", look: "arrow", dir: "up", mode: "double" };
  L.convertArt(k, "states", {});
  assert.equal(k.look, undefined);
  const d = { id: "d", label: "D", key: "F1", mode: "double" };
  L.convertArt(d, "hold", {});
  assert.equal(d.mode, "double");
  const g = free([{ kind: "frame", id: "f", label: "R", x: 0, y: 0, w: 4, h: 4 }, B("a", 0, 0, 4, 4)], { cols: 4, rows: 4 });
  const f2 = { kind: "frame", id: "f2", label: "R2" };
  L.addButton(g, f2, { kind: "frame", at: { x: 1, y: 1 } });
  assert.equal(g.rows, 4);                                        // Rahmen: keine Platzsuche, Raster wächst nicht
});

test("free -> grid entfernt die Lage; -> Schild vergibt Zonen", () => {
  const p = free([B("a", 0, 0, 2, 1)]);
  L.setPageType(p, "grid");
  assert.deepEqual(Object.keys(p.buttons[0]).sort(), ["id", "label", "mode"]);
  assert.equal(p.cols, undefined);
  L.setPageType(p, "shield");
  assert.equal(p.buttons[0].zone, "front");
});

test("Verschieben in Zellen: begrenzt auf das Raster", () => {
  const p = free([B("a", 0, 0, 2, 1), B("b", 2, 0, 2, 1)]);
  L.moveBy(p, ["a", "b"], 10, 5);
  assert.deepEqual(p.buttons.map((b) => [b.x, b.y]), [[2, 2], [4, 2]]);
  L.moveBy(p, ["a"], -9, -9);
  assert.deepEqual([p.buttons[0].x, p.buttons[0].y], [0, 0]);
});

test("Ausrichten in Zellen: ganze Zahlen, einzelne Taste am Raster", () => {
  const p = free([B("a", 1, 0, 2, 1), B("b", 3, 1, 3, 1)]);
  L.alignCells(p, ["a", "b"], "left");
  assert.deepEqual(p.buttons.map((b) => b.x), [1, 1]);
  const q = free([B("a", 1, 0, 2, 1)]);
  L.alignCells(q, ["a"], "right");
  assert.equal(q.buttons[0].x, 4);
  L.alignCells(q, ["a"], "hcenter");
  assert.equal(q.buttons[0].x, 2);
  const r = free([B("a", 0, 0, 2, 1), B("b", 3, 2, 3, 1)]);
  L.alignCells(r, ["a", "b"], "hcenter");                         // 1,5 -> ganze Zelle
  assert.ok(r.buttons.every((b) => Number.isInteger(b.x)));
});

test("Verteilen ab 3, gleiche Größe ab 2", () => {
  const p = free([B("a", 0, 0, 1, 1), B("b", 1, 0, 1, 1), B("c", 5, 0, 1, 1)]);
  assert.equal(L.distributeCells(p, ["a", "b"], "x"), false);
  assert.ok(L.distributeCells(p, ["a", "b", "c"], "x"));
  assert.deepEqual(p.buttons.map((b) => b.x), [0, 3, 5]);
  const q = free([B("a", 0, 0, 2, 1), B("b", 3, 1, 3, 2)]);
  assert.ok(L.sameSizeCells(q, ["a", "b"], "both"));
  assert.deepEqual(q.buttons.map((b) => [b.w, b.h]), [[2, 1], [2, 1]]);
  assert.deepEqual(L.arrangeState(2), { align: true, distribute: false, sameSize: true });
  assert.deepEqual(L.arrangeState(0), { align: false, distribute: false, sameSize: false });
});

test("Größe ändern in Zellen: Mindestgröße 1, im Raster", () => {
  const p = free([B("a", 4, 1, 2, 1)]);
  L.resizeCells(p, "a", "se", 5, 5);
  assert.deepEqual([p.buttons[0].w, p.buttons[0].h], [2, 2]);
  L.resizeCells(p, "a", "w", 9, 0);
  assert.deepEqual([p.buttons[0].x, p.buttons[0].w], [5, 1]);
});

test("Rahmenauswahl in Zellen; gleiche Überschrift bildet keine Gruppe", () => {
  const p = free([B("a", 0, 0, 2, 1, { group: "X" }), B("b", 3, 0, 2, 1, { group: "X" }), B("c", 0, 2, 2, 1)]);
  assert.deepEqual(L.selectInRect(p, { x: 0.5, y: 0, w: 1, h: 1 }), ["a"]);
  assert.deepEqual(L.selectInRect(p, { x: 0, y: 0, w: 6, h: 3 }), ["a", "b", "c"]);
});

test("Duplizieren: neue IDs, freie Stelle bzw. hinter dem Original, gültig", needPy, () => {
  const p = free([B("a", 0, 0, 2, 1, { key: "A" })]);
  const l = lay(p);
  const ids = L.duplicate(l, p, ["a"]);
  assert.deepEqual(ids, ["a_2"]);
  const c = p.buttons[1];
  assert.deepEqual([c.x, c.y, c.key], [1, 1, "A"]);
  assert.equal(pyValid(l), null);
  const g = { id: "g", title: "G", type: "grid", buttons: [{ id: "x", label: "X" }, { id: "y", label: "Y" }] };
  assert.deepEqual(L.duplicate(lay(g), g, ["x"]), ["x_2"]);
  assert.deepEqual(g.buttons.map((b) => b.id), ["x", "x_2", "y"]);
});

test("cellAt / cellStep rechnen Pixel in Zellen um", () => {
  const box = { left: 100, top: 50, width: 1000, height: 400 };      // 10 x 4, Abstand 0
  assert.deepEqual([L.cellAt(box, 0, 10, 4, 100, 50).x, L.cellAt(box, 0, 10, 4, 100, 50).y], [0, 0]);
  const c = L.cellAt(box, 0, 10, 4, 1099, 449);
  assert.deepEqual([c.x, c.y], [9, 3]);
  assert.deepEqual([L.cellAt(box, 0, 10, 4, 5000, -9).x, L.cellAt(box, 0, 10, 4, 5000, -9).y], [9, 0]);
  assert.deepEqual(L.cellStep(box, 0, 10, 4), { x: 100, y: 100 });
  assert.ok(Math.abs(L.cellStep({ left: 0, top: 0, width: 108, height: 10 }, 8, 2, 1).x - 58) < 1e-9);   // 50 + 8
});

test("Gemeinsame Felder: nur wo sie gelten, 'verschieden' bei Unterschieden", () => {
  const bs = [{ id: "a", label: "A", style: "accent" }, { id: "b", label: "B" }, { id: "s", label: "S", slider: { up: "A", down: "B", steps: 5 } },
    { id: "p", label: "P", page: "x" }];
  const f = Object.fromEntries(L.commonFields(bs, "grid").map((x) => [x.key, x]));
  assert.ok(f.style.mixed);
  assert.equal(f.mode.count, 2);                                   // Regler und Link haben kein mode
  assert.equal(f.hold.count, 2);
  assert.ok(f.group);
  assert.equal(f.zone, undefined);
  const sh = Object.fromEntries(L.commonFields(bs, "shield").map((x) => [x.key, x]));
  assert.ok(sh.zone);
  assert.equal(sh.group, undefined);
});

test("setShared: gilt nur für passende Tasten, Ergebnis bleibt gültig", needPy, () => {
  const p = { id: "g", title: "G", type: "grid", buttons: [{ id: "a", label: "A", key: "A" },
    { id: "s", label: "S", slider: { up: "A", down: "B", steps: 5 } }, { id: "p", label: "P", page: "g" },
    { id: "st", label: "ST", key: "F1", states: [{ label: "1" }, { label: "2" }] }] };
  L.setShared(p.buttons, "mode", "hold-confirm", "grid");
  L.setShared(p.buttons, "hold", "1", "grid");
  L.setShared(p.buttons, "style", "danger", "grid");
  L.setShared(p.buttons, "group", "Neu", "grid");
  assert.equal(p.buttons[0].mode, "hold-confirm");
  assert.equal(p.buttons[1].mode, undefined);
  assert.equal(p.buttons[2].hold, undefined);
  assert.equal(p.buttons[3].mode, undefined);
  assert.ok(p.buttons.every((b) => b.style === "danger" && b.group === "Neu"));
  assert.equal(pyValid(lay(p)), null);
  L.setShared(p.buttons, "style", "", "grid");
  assert.equal(p.buttons[0].style, undefined);
});

test("metaText / kindOf / isMapped", () => {
  assert.equal(L.kindOf({ slider: {} }), "slider");
  assert.equal(L.kindOf({ open: "https://x" }), "open");
  assert.equal(L.kindOf({ key: "A" }), "key");
  assert.ok(!L.isMapped({ id: "x" }));
  assert.equal(L.metaText({ key: "A", mode: "toggle", group: "G" }), "G · A · Schalter");
});

// ---------------------------------------------------------------- Art (Schritt 6)
const ART_IDS = L.ARTS.map((a) => a.id);

test("artOf erkennt bestehende Tasten", () => {
  assert.equal(L.artOf({ key: "A" }), "press");
  assert.equal(L.artOf({ key: "A", mode: "hold-confirm" }), "press");
  assert.equal(L.artOf({ key: "A", hold: true }), "hold");
  assert.equal(L.artOf({ key: "A", mode: "toggle" }), "toggle");
  assert.equal(L.artOf({ key: "A", states: [{ label: "a" }, { label: "b" }] }), "states");
  assert.equal(L.artOf({ slider: { up: "A", down: "B", steps: 5 } }), "slider");
  assert.equal(L.artOf({ page: "x" }), "page");
  assert.equal(L.artOf({ open: "https://x.de" }), "open");
  assert.equal(L.artOf({ macro: [{ key: "A" }, { wait: 5 }] }), "macro");
  assert.equal(L.artOf({ macro: [{ media: "mute" }] }), "media");
  assert.equal(L.artOf({ id: "leer" }), "press");
});

test("convertArt: jede Art -> jede Art ergibt eine gültige Taste ohne fremde Felder", needPy, () => {
  const starts = {
    press: { key: "LALT+F" }, hold: { key: "F", hold: true }, toggle: { key: "F", mode: "toggle" },
    states: { key: "F", mode: "tap", states: [{ label: "A" }, { label: "B", key: "G" }] },
    slider: { slider: { up: "PGUP", down: "PGDN", steps: 4 } }, page: { page: "b" }, open: { open: "https://x.de" },
    macro: { macro: [{ key: "H" }, { wait: 10 }] }, media: { macro: [{ media: "volup" }] }
  };
  const allowed = {
    press: ["key", "mode", "sc"], hold: ["key", "mode", "hold", "sc"], toggle: ["key", "mode", "sc"],
    states: ["key", "mode", "states"], slider: ["mode", "slider"], page: ["page"], open: ["mode", "open"],
    macro: ["mode", "macro"], media: ["mode", "macro"]
  };
  const base = ["id", "label", "group", "style", "x", "y", "w", "h"];
  for (const from of ART_IDS) for (const to of ART_IDS) {
    const l = lay({ id: "a", title: "A", type: "free", cols: 6, rows: 3, buttons: [] }, { id: "b", title: "B", buttons: [] });
    const b = Object.assign({ id: "t", label: "T", group: "G", style: "accent", sc: "v_x", x: 0, y: 0, w: 2, h: 1 },
      JSON.parse(JSON.stringify(starts[from])));
    l.pages[0].buttons.push(b);
    L.convertArt(b, to, { page: l.pages[0], pages: l.pages });
    assert.equal(L.artOf(b), to, from + " -> " + to);
    assert.equal(pyValid(l), null, from + " -> " + to);
    if (from === to) continue;
    for (const k of Object.keys(b)) assert.ok(base.concat(allowed[to]).includes(k), from + " -> " + to + ": Feld " + k);
  }
});

test("convertArt: sc bleibt zwischen Tastenarten, fällt bei anderen Arten weg", () => {
  const b = L.convertArt({ id: "t", label: "T", key: "F", sc: "v_flightready" }, "hold");
  assert.strictEqual(b.sc, "v_flightready");
  L.convertArt(b, "toggle");
  assert.strictEqual(b.sc, "v_flightready");
  L.convertArt(b, "macro");
  assert.strictEqual(b.sc, undefined);
});

test("convertArt: Taste wird übernommen", () => {
  const b = L.convertArt({ id: "t", label: "T", key: "LALT+F" }, "hold");
  assert.equal(b.key, "LALT+F"); assert.equal(b.hold, true);
  L.convertArt(b, "macro");
  assert.deepEqual(b.macro, [{ key: "LALT+F" }]);
  L.convertArt(b, "toggle");
  assert.equal(b.key, "LALT+F"); assert.equal(b.mode, "toggle"); assert.equal(b.hold, undefined);
  const s = L.convertArt({ id: "s", label: "S", slider: { up: "A", down: "B", steps: 3 } }, "states");
  assert.equal(s.key, "A");
});

test("convertArt: Spielaktion (sc) bleibt nur bei Tastenarten, hold-confirm bleibt wo erlaubt", () => {
  const b = { id: "t", label: "T", sc: "v_x", key: "A", mode: "hold-confirm" };
  L.convertArt(b, "macro");
  assert.equal(b.sc, undefined);
  assert.equal(b.mode, "hold-confirm");
  L.convertArt(b, "slider");
  assert.equal(b.mode, undefined);
  assert.equal(b.slider.up, "A");
});

test("convertArt: Seite wechseln nimmt eine andere Seite; Platzhalter statt leerer Felder", () => {
  const l = lay({ id: "a", title: "A", buttons: [] }, { id: "b", title: "B", buttons: [] });
  const b = { id: "t", label: "T", key: "A" };
  L.convertArt(b, "page", { page: l.pages[1], pages: l.pages });
  assert.equal(b.page, "a");
  assert.equal(b.key, undefined);
  const s = L.convertArt({ id: "u", label: "U" }, "states");
  assert.equal(s.key, L.PLACEHOLDER.states);
  assert.ok(L.hasPlaceholder(s));
  assert.ok(L.hasPlaceholder(L.convertArt({ id: "v", label: "V" }, "open")));
});

test("convertArt: Medien <-> Makro behält den Schritt, gleiche Art ändert nichts", () => {
  const b = { id: "t", label: "T", macro: [{ media: "mute" }] };
  L.convertArt(b, "macro");
  assert.deepEqual(b.macro, [{ media: "mute" }, { wait: 200 }]);
  assert.equal(L.artOf(b), "macro");
  const k = { id: "k", label: "K", key: "A", hold: true };
  assert.equal(L.convertArt(k, "hold"), k);
  assert.deepEqual(k, { id: "k", label: "K", key: "A", hold: true });
});

// ---------------------------------------------------------------- Aufnahme
function press(codes, keyNames, altGraph) {   // Folge von [type, code] -> Ergebnisse
  const st = L.newCapture(), out = [];
  for (const [type, code] of codes) {
    const r = L.captureEvent(st, { type, code, altGraph: !!altGraph }, keyNames);
    if (r) out.push(r);
  }
  return out;
}

test("codeName: Buchstaben, Ziffern, F-Tasten, Numpad, Pfeile, Sondertasten", () => {
  const exp = { KeyR: "R", Digit7: "7", F5: "F5", F12: "F12", Numpad9: "NUMPAD9", NumpadEnter: "NUMPADENTER",
    NumpadAdd: "NUMPADADD", ArrowUp: "UP", PageDown: "PGDN", Backquote: "GRAVE", ControlRight: "RCTRL", AltRight: "RALT",
    Backslash: "BACKSLASH", Space: "SPACE" };
  for (const k of Object.keys(exp)) assert.equal(L.codeName(k), exp[k], k);
  for (const k of ["F13", "F0", "PrintScreen", "Pause", "NumLock", "MetaLeft", "IntlBackslash", "toString", ""]) assert.equal(L.codeName(k), null, k);
});

test("Aufnahme: Kombination mit Zusatztasten in fester Reihenfolge", () => {
  assert.deepEqual(press([["down", "AltLeft"], ["down", "ControlRight"], ["down", "Numpad9"]]), [{ done: "RCTRL+LALT+NUMPAD9" }]);
  assert.deepEqual(press([["down", "ShiftLeft"], ["down", "KeyF"]]), [{ done: "LSHIFT+F" }]);
  assert.deepEqual(press([["down", "F5"]]), [{ done: "F5" }]);
});

test("Aufnahme: Esc bricht ab, Strg+Esc wird aufgenommen, Zusatztasten allein", () => {
  assert.deepEqual(press([["down", "Escape"]]), [{ cancel: true }]);
  assert.deepEqual(press([["down", "ControlLeft"], ["down", "Escape"]]), [{ done: "LCTRL+ESC" }]);
  assert.deepEqual(press([["down", "ShiftLeft"], ["up", "ShiftLeft"]]), [{ done: "LSHIFT" }]);
  assert.deepEqual(press([["down", "ShiftLeft"], ["down", "KeyA"], ["up", "KeyA"], ["up", "ShiftLeft"]]), [{ done: "LSHIFT+A" }]);
});

test("Aufnahme: AltGr wird zu RALT ohne Strg-links", () => {
  assert.deepEqual(press([["down", "ControlLeft"], ["down", "AltRight"], ["down", "KeyQ"]], null, true), [{ done: "RALT+Q" }]);
  assert.deepEqual(press([["down", "ControlLeft"], ["down", "AltRight"], ["up", "AltRight"]], null, true), [{ done: "RALT" }]);
});

test("Aufnahme: nicht abbildbare Tasten geben einen Hinweis", () => {
  assert.match(press([["down", "MetaLeft"]])[0].hint, /Windows/);
  assert.match(press([["down", "F13"]])[0].hint, /F13/);
  assert.match(press([["down", "AudioVolumeUp"]])[0].hint, /Medien/);
  assert.match(press([["down", "KeyA"]], ["B"])[0].hint, /nicht senden/);
});

test("Aufnahme erzeugt nur Namen, die bridge/keys.py kennt", needPy, () => {
  const codes = ["KeyA", "Digit0", "F1", "F12", "Numpad0", "Numpad9", "NumpadAdd", "NumpadSubtract", "NumpadMultiply", "NumpadDivide",
    "NumpadDecimal", "NumpadEnter", "ArrowLeft", "Home", "End", "PageUp", "Insert", "Delete", "Tab", "Space", "Enter", "Backspace",
    "Minus", "Equal", "BracketLeft", "BracketRight", "Semicolon", "Quote", "Backquote", "Backslash", "Comma", "Period", "Slash",
    "CapsLock", "ScrollLock", "Escape"];
  const b = codes.map((c, i) => ({ id: "b" + i, label: "x", key: "LCTRL+" + L.codeName(c) }));
  assert.equal(pyValid(lay({ id: "a", title: "A", buttons: b })), null);
  const mods = ["LCTRL", "RCTRL", "LSHIFT", "RSHIFT", "LALT", "RALT"].map((m, i) => ({ id: "m" + i, label: "x", key: m }));
  assert.equal(pyValid(lay({ id: "a", title: "A", buttons: mods })), null);
});

// ---------------------------------------------------------------- Doppelbelegung
test("normKey: Groß-/Kleinschreibung, Aliase, Reihenfolge der Zusatztasten", () => {
  assert.equal(L.normKey("lalt + f"), "LALT+F");
  assert.equal(L.normKey("F+LALT"), "LALT+F");
  assert.equal(L.normKey("CTRL+NP_9"), "LCTRL+NUMPAD9");
  assert.equal(L.normKey("KP_7"), "NUMPAD7");
  assert.equal(L.normKey("RCTRL+LCTRL+X"), "LCTRL+RCTRL+X");
  assert.notEqual(L.normKey("LCTRL+A"), L.normKey("RCTRL+A"));
  assert.equal(L.normKey(""), "");
  assert.equal(L.normKey(null), "");
});

test("duplicates: gleiche Taste auch über Seiten, Regler/Zustände zählen, Makro/Platzhalter nicht", () => {
  const st = [{ label: "x" }, { label: "y" }];
  const l = lay(
    { id: "a", title: "A", buttons: [
      { id: "a1", label: "Eins", key: "LALT+F" },
      { id: "a2", label: "Zwei", key: "f+lalt" },
      { id: "a3", label: "Drei", key: "G" },
      { id: "a4", label: "Reg", slider: { up: "H", down: "J", steps: 3 } },
      { id: "a5", label: "Mak", macro: [{ key: "G" }] },
      { id: "a6", label: "Pl1", key: "SCROLLLOCK", states: st },
      { id: "a7", label: "Pl2", key: "SCROLLLOCK", states: st }] },
    { id: "b", title: "B", buttons: [
      { id: "b1", label: "Andere Seite", key: "g" },
      { id: "b2", label: "Zust", key: "X", states: [{ label: "a" }, { label: "b", key: "H" }] },
      { id: "b3", label: "Link", page: "a" }] });
  const d = L.duplicates(l);
  assert.deepEqual(d.groups.map((g) => g.key), ["LALT+F", "G", "H"]);
  assert.equal(d.keys, 3);
  assert.equal(d.count, 6);
  assert.deepEqual(d.byId.a3[0].others.map((o) => o.id), ["b1"]);
  assert.equal(d.byId.b1[0].others[0].pageTitle, "A");
  assert.equal(d.byId.a5, undefined);
  assert.equal(d.byId.a6, undefined);
  assert.equal(L.duplicates(lay({ id: "a", title: "A", buttons: [{ id: "q", label: "q", key: "A", states: st }] })).count, 0);
});

// ---------------------------------------------------------------- Makro-Baukasten
const macroLay = (macro) => lay({ id: "a", title: "A", buttons: [{ id: "m", label: "M", macro }] });
const KEYS = ["A", "B", "ENTER", "LALT", "LCTRL", "1", "F5", "SPACE"], MEDIA = ["playpause", "next", "prev", "stop", "mute", "voldown", "volup"];

test("Makro: Grenzen wie layout.py (Anzahl, Warten, Text)", needPy, () => {
  assert.equal(L.MACRO_MAX, 50); assert.equal(L.MACRO_WAIT_MAX, 5000); assert.equal(L.MACRO_TEXT_MAX, 500);
  const ok = (m) => assert.equal(pyValid(macroLay(m)), null, JSON.stringify(m).slice(0, 60));
  const bad = (m) => assert.match(pyValid(macroLay(m)), /^ERR/, JSON.stringify(m).slice(0, 60));
  ok(Array.from({ length: 50 }, () => ({ wait: 0 }))); bad(Array.from({ length: 51 }, () => ({ wait: 0 }))); bad([]);
  ok([{ wait: 5000 }]); bad([{ wait: 5001 }]); bad([{ wait: -1 }]); bad([{ wait: 1.5 }]);
  ok([{ text: "x".repeat(500) }]); bad([{ text: "x".repeat(501) }]); bad([{ text: "" }]);
});

test("stepError stimmt mit layout.py überein", needPy, () => {
  const cases = [{ key: "LALT+1" }, { key: "lalt + f5" }, { key: "" }, { key: "LALT+" }, { key: "+A" }, { key: "UNSINN" }, { key: "ALT+A" },
    { text: "o7" }, { text: "" }, { text: "x".repeat(501) }, { wait: 0 }, { wait: 5000 }, { wait: 5001 }, { wait: -5 }, { wait: 2.5 },
    { wait: NaN }, { wait: "5" }, { media: "mute" }, { media: "foo" }, { foo: 1 }, { key: "A", wait: 1 }, {}];
  const names = ["A", "F5", "1", "LALT", "ALT", "ENTER", "LCTRL"];
  for (const s of cases) {
    const py = pyValid(macroLay([s, { wait: 1 }]));
    const js = L.stepError(s, [], MEDIA);
    // Ohne Namensliste prüft JS nur die Form; unbekannte Tastennamen kennt nur der Hub
    if (s.key === "UNSINN") { assert.equal(js, ""); assert.notEqual(L.stepError(s, names, MEDIA), ""); continue; }
    assert.equal(js === "", py === null, JSON.stringify(s) + " js=" + js + " py=" + py);
  }
});

test("newStep: Standardschritte sind gültig", needPy, () => {
  for (const k of L.STEP_KINDS) {
    const s = L.newStep(k.kind, MEDIA);
    assert.equal(L.stepKind(s), k.kind);
    assert.equal(L.stepError(s, KEYS, MEDIA), "");
    assert.equal(pyValid(macroLay([s, { wait: 1 }])), null, k.kind);
  }
});

test("Makro-Operationen: einfügen, duplizieren, verschieben, löschen (gültig, Original unverändert)", needPy, () => {
  const m0 = [{ key: "A" }, { text: "hi" }, { wait: 100 }];
  const snap = JSON.stringify(m0);
  let r = L.macroInsert(m0, { wait: 10 }, 0);
  assert.deepEqual(r.macro, [{ key: "A" }, { wait: 10 }, { text: "hi" }, { wait: 100 }]); assert.equal(r.index, 1);
  assert.equal(L.macroInsert(m0, { wait: 10 }).index, 3);
  assert.equal(L.macroInsert(m0, { wait: 10 }, -1).index, 0);
  r = L.macroDuplicate(m0, 1); assert.deepEqual(r.macro[2], { text: "hi" }); assert.notEqual(r.macro[2], r.macro[1]); assert.equal(r.index, 2);
  r = L.macroMove(m0, 0, 2); assert.deepEqual(r.macro, [{ text: "hi" }, { wait: 100 }, { key: "A" }]); assert.equal(r.index, 2);
  assert.ok(L.macroMove(m0, 0, -1).err); assert.ok(L.macroMove(m0, 2, 3).err);
  r = L.macroRemove(m0, 1); assert.deepEqual(r.macro, [{ key: "A" }, { wait: 100 }]);
  assert.equal(JSON.stringify(m0), snap);
  for (const x of [L.macroInsert(m0, { wait: 10 }, 0), L.macroDuplicate(m0, 0), L.macroMove(m0, 0, 2), L.macroRemove(m0, 0)])
    assert.equal(pyValid(macroLay(x.macro)), null);
});

test("Makro: Höchstzahl wird eingehalten", () => {
  const full = Array.from({ length: L.MACRO_MAX }, () => ({ wait: 1 }));
  assert.ok(L.macroInsert(full, { wait: 1 }).err);
  assert.ok(L.macroDuplicate(full, 0).err);
  assert.ok(L.macroInsertMany(full.slice(0, 49), [{ key: "A" }, { key: "B" }]).err);
  assert.equal(L.macroInsertMany(full.slice(0, 48), [{ key: "A" }, { key: "B" }]).macro.length, 50);
});

test("Makro: letzter Schritt und einzelner Medien-Schritt sind geschützt", () => {
  assert.ok(L.macroRemove([{ key: "A" }], 0).err);
  assert.ok(L.macroRemove([{ media: "mute" }, { wait: 5 }], 1).err);              // bliebe einzelner Medien-Schritt
  assert.ok(L.macroSetKind([{ key: "A" }], 0, "media", MEDIA).err);
  assert.equal(L.macroRemove([{ media: "mute" }, { wait: 5 }, { key: "A" }], 2).macro.length, 2);
  assert.equal(L.macroSetKind([{ key: "A" }, { wait: 1 }], 0, "media", MEDIA).macro[0].media, "playpause");
  assert.equal(L.isSoloMedia([{ media: "mute" }]), true);
  assert.equal(L.isSoloMedia([{ media: "mute" }, { wait: 1 }]), false);
  // Jede vom Baukasten erreichbare Operation lässt ein Makro ein Makro bleiben
  const m = [{ key: "A" }, { wait: 200 }];
  for (const r of [L.macroInsert(m, L.newStep("media", MEDIA)), L.macroRemove(m, 0), L.macroDuplicate(m, 1), L.macroMove(m, 0, 1)])
    if (r.macro) assert.equal(L.artOf({ macro: r.macro }), "macro");
});

test("macroErrors: je Schritt, leer und zu lang", () => {
  assert.deepEqual(L.macroErrors([{ key: "A" }, { wait: 9999 }, { media: "x" }], KEYS, MEDIA).map((e) => e.index), [1, 2]);
  assert.equal(L.macroErrors([], KEYS, MEDIA)[0].index, -1);
  assert.equal(L.macroErrors(Array.from({ length: 51 }, () => ({ wait: 1 })), KEYS, MEDIA)[0].index, -1);
  assert.deepEqual(L.macroErrors([{ key: "LALT+1" }, { text: "o7" }], KEYS, MEDIA), []);
});

test("recordToSteps: Pausen werden Warten-Schritte (gerundet, Mindestpause, Kappung)", needPy, () => {
  const ev = (...a) => a.map(([t, key]) => ({ t, key }));
  assert.deepEqual(L.recordToSteps([]).steps, []);
  assert.deepEqual(L.recordToSteps(ev([500, "A"])).steps, [{ key: "A" }]);            // Anlaufzeit vor der ersten Taste entfällt
  assert.deepEqual(L.recordToSteps(ev([0, "A"], [40, "B"], [300, "LALT+1"])).steps,
    [{ key: "A" }, { key: "B" }, { wait: 260 }, { key: "LALT+1" }]);                  // 40 ms < 50: keine Pause
  assert.deepEqual(L.recordToSteps(ev([0, "A"], [51, "B"])).steps, [{ key: "A" }, { wait: 50 }, { key: "B" }]);
  assert.deepEqual(L.recordToSteps(ev([0, "A"], [1234, "B"])).steps[1], { wait: 1230 });
  assert.deepEqual(L.recordToSteps(ev([0, "A"], [99999, "B"])).steps[1], { wait: 5000 });
  assert.deepEqual(L.recordToSteps(ev([0, "A"], [50, "B"])).steps, [{ key: "A" }, { key: "B" }]);   // genau minGap: keine Pause
  const res = L.recordToSteps(ev([0, "A"], [1000, "B"], [2000, "A"]), 4);               // A w B | w A passt nicht mehr
  assert.equal(res.cut, true); assert.equal(res.steps.length, 3);
  const many = Array.from({ length: 80 }, (_, i) => ({ t: i * 500, key: "A" }));
  const big = L.recordToSteps(many);
  assert.ok(big.cut && big.steps.length <= 50);
  assert.equal(pyValid(macroLay(big.steps)), null);
  assert.equal(L.macroInsertMany([{ wait: 200 }], big.steps.slice(0, 49)).macro.length, 50);
});

test("Profile: artOf aller Makros unverändert (Medien nur bei genau einem media-Schritt)", () => {
  const fs = require("node:fs");
  const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).flatMap((e) => e.isDirectory() ? walk(path.join(d, e.name)) : e.name.endsWith(".json") ? [path.join(d, e.name)] : []);
  const dir = path.join(ROOT, "profiles");
  if (!fs.existsSync(dir)) return;
  for (const f of walk(dir)) {
    let j; try { j = JSON.parse(fs.readFileSync(f, "utf8")); } catch (e) { continue; }
    for (const p of j.pages || []) for (const b of p.buttons || []) {
      if (!b.macro) continue;
      const media = b.macro.length === 1 && b.macro[0].media !== undefined;
      assert.equal(L.artOf(b), media ? "media" : "macro", f + " " + b.id);
      assert.deepEqual(L.macroErrors(b.macro, [], MEDIA), [], f + " " + b.id);   // bestehende Makros bestehen die Prüfung
    }
  }
});

test("stepError: Textlänge in Zeichen wie layout.py (Emojis zählen einfach)", () => {
  assert.equal(L.stepError({ text: "😀".repeat(500) }), "");
  assert.notEqual(L.stepError({ text: "😀".repeat(501) }), "");
});
