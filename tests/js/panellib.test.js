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

test("Einfügen in volle Seite: Zeilen wachsen bis 12, dann Überlappung gemeldet", () => {
  const p = free([B("a", 0, 0, 6, 3)]);
  const b = { id: "n", label: "N" };
  assert.deepEqual(L.addButton(p, b, { kind: "key" }), { overlap: false });
  assert.equal(p.rows, 4);
  assert.equal(b.y, 3);
  const full = free([B("a", 0, 0, 6, 12)], { rows: 12 });
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
  for (let i = 0; i < 150; i++) buttons.push({ id: "b" + i, label: "B", wide: true, group: "G" + i });
  const p = { id: "g", title: "G", type: "grid", buttons };
  assert.equal(L.toFree(p), null);
  assert.equal(L.setPageType(p, "free"), false);
  assert.equal(p.type, "grid");
  assert.equal(p.buttons[0].x, undefined);
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
