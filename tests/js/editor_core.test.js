"use strict";
// Tests für web/editor/core.js (node --test tests/js/)
const test = require("node:test");
const assert = require("node:assert/strict");
const C = require("../../web/editor/core.js");

const R = (id, x, y, w, h, extra) => Object.assign({ id, x, y, w, h }, extra || {});
const byId = (items, id) => items.find((i) => i.id === id);
const ids = (items) => items.map((i) => i.id);

test("snap rundet aufs Raster", () => {
  assert.equal(C.snap(13, 8), 16);
  assert.equal(C.snap(11, 8), 8);
  assert.equal(C.snap(-5, 8), -8);
  assert.equal(C.snap(13, 0), 13);
  assert.equal(C.snap(13, undefined), 13);
});

test("snapRect: Raster ohne andere Rechtecke", () => {
  const r = C.snapRect(R("a", 13, 21, 50, 30), 8, [], 6);
  assert.equal(r.rect.x, 16);
  assert.equal(r.rect.y, 24);
  assert.deepEqual(r.guides, []);
});

test("snapRect: rastet an Kante eines anderen ein und liefert Hilfslinie", () => {
  const other = R("b", 100, 0, 40, 40);
  const r = C.snapRect(R("a", 53, 5, 50, 30), 8, [other], 6);   // rechte Kante 103 -> 100
  assert.equal(r.rect.x, 50);
  assert.ok(r.guides.some((g) => g.axis === "x" && g.pos === 100));
});

test("snapRect: Mitte an Mitte", () => {
  const other = R("b", 0, 100, 100, 40);        // Mitte x = 50
  const r = C.snapRect(R("a", 27, 0, 50, 30), 0, [other], 4);   // Mitte 52 -> 50
  assert.equal(r.rect.x, 25);
  assert.ok(r.guides.some((g) => g.axis === "x" && g.pos === 50));
});

test("snapRect: außerhalb der Schwelle greift das Raster; sich selbst ignorieren", () => {
  const other = R("b", 100, 100, 10, 10);
  const r = C.snapRect(R("a", 30, 30, 20, 20), 8, [other, R("a", 31, 31, 20, 20)], 3);
  assert.equal(r.rect.x, 32);
  assert.equal(r.rect.y, 32);
  assert.deepEqual(r.guides, []);
});

test("snapRect verändert die Eingabe nicht", () => {
  const a = R("a", 13, 13, 5, 5);
  C.snapRect(a, 8, [], 0);
  assert.equal(a.x, 13);
});

test("move: einfach, mit Grenzen, Eingabe unverändert", () => {
  const items = [R("a", 0, 0, 2, 2), R("b", 5, 5, 2, 2)];
  const out = C.move(items, ["a"], 3, 1, { w: 12, h: 8 });
  assert.equal(byId(out, "a").x, 3);
  assert.equal(byId(out, "a").y, 1);
  assert.equal(byId(out, "b").x, 5);
  assert.equal(items[0].x, 0);
  const clamped = C.move(items, ["b"], 50, -50, { w: 12, h: 8 });
  assert.equal(byId(clamped, "b").x, 10);
  assert.equal(byId(clamped, "b").y, 0);
});

test("move: Gruppe bewegt sich gemeinsam und bleibt als Ganzes in der Fläche", () => {
  const items = [R("a", 0, 0, 2, 2, { group: "g1" }), R("b", 4, 0, 2, 2, { group: "g1" }), R("c", 8, 0, 2, 2)];
  const out = C.move(items, ["a"], 20, 0, { w: 12, h: 8 });
  assert.equal(byId(out, "a").x, 6);   // b stößt bei 12 an
  assert.equal(byId(out, "b").x, 10);
  assert.equal(byId(out, "c").x, 8);
});

test("move: leere Auswahl und ohne Grenzen", () => {
  const items = [R("a", 0, 0, 2, 2)];
  const out = C.move(items, [], 5, 5);
  assert.deepEqual(out, items);
  assert.notEqual(out[0], items[0]);
  assert.equal(byId(C.move(items, ["a"], -5, -5), "a").x, -5);
});

test("resize: Griffe und Mindestgröße", () => {
  const it = R("a", 2, 2, 4, 3);
  let r = C.resize(it, "se", 2, 1, { w: 1, h: 1 }, { w: 12, h: 8 });
  assert.deepEqual([r.x, r.y, r.w, r.h], [2, 2, 6, 4]);
  r = C.resize(it, "nw", 1, 1, { w: 1, h: 1 }, { w: 12, h: 8 });
  assert.deepEqual([r.x, r.y, r.w, r.h], [3, 3, 3, 2]);
  r = C.resize(it, "e", -10, 0, { w: 2, h: 1 });
  assert.deepEqual([r.x, r.w], [2, 2]);
  r = C.resize(it, "w", 10, 0, { w: 2, h: 1 });
  assert.deepEqual([r.x, r.w], [4, 2]);
  r = C.resize(it, "n", 10, 10, { w: 1, h: 1 });
  assert.deepEqual([r.y, r.h], [4, 1]);
  assert.deepEqual([it.x, it.y, it.w, it.h], [2, 2, 4, 3]);
});

test("resize: Grenzen der Fläche", () => {
  const it = R("a", 2, 2, 4, 3);
  let r = C.resize(it, "se", 50, 50, { w: 1, h: 1 }, { w: 12, h: 8 });
  assert.deepEqual([r.w, r.h], [10, 6]);
  r = C.resize(it, "nw", -50, -50, { w: 1, h: 1 }, { w: 12, h: 8 });
  assert.deepEqual([r.x, r.y, r.w, r.h], [0, 0, 6, 5]);
});

test("align: alle sechs Modi", () => {
  const items = [R("a", 0, 0, 2, 2), R("b", 10, 6, 4, 4), R("c", 5, 3, 2, 2)];
  const sel = ["a", "b", "c"];   // Umgebendes: x 0..14, y 0..10
  assert.deepEqual(C.align(items, sel, "left").map((i) => i.x), [0, 0, 0]);
  assert.deepEqual(C.align(items, sel, "right").map((i) => i.x), [12, 10, 12]);
  assert.deepEqual(C.align(items, sel, "hcenter").map((i) => i.x), [6, 5, 6]);
  assert.deepEqual(C.align(items, sel, "top").map((i) => i.y), [0, 0, 0]);
  assert.deepEqual(C.align(items, sel, "bottom").map((i) => i.y), [8, 6, 8]);
  assert.deepEqual(C.align(items, sel, "vcenter").map((i) => i.y), [4, 3, 4]);
});

test("align: nur Auswahl, weniger als 2 = keine Änderung", () => {
  const items = [R("a", 1, 1, 2, 2), R("b", 9, 9, 2, 2), R("c", 5, 5, 2, 2)];
  const out = C.align(items, ["a", "b"], "left");
  assert.equal(byId(out, "b").x, 1);
  assert.equal(byId(out, "c").x, 5);
  assert.deepEqual(C.align(items, ["a"], "left"), items);
  assert.deepEqual(C.align(items, [], "left"), items);
});

test("distribute: gleiche Lücken, Enden bleiben", () => {
  const items = [R("a", 0, 0, 2, 2), R("b", 3, 0, 4, 2), R("c", 20, 0, 2, 2), R("d", 100, 0, 1, 1)];
  const out = C.distribute(items, ["a", "b", "c"], "x");
  assert.equal(byId(out, "a").x, 0);
  assert.equal(byId(out, "c").x, 20);
  // Gesamtbreite 22, belegt 8, Lücke 7
  assert.equal(byId(out, "b").x, 9);
  assert.equal(byId(out, "d").x, 100);
  const v = C.distribute([R("a", 0, 0, 1, 2), R("b", 0, 1, 1, 2), R("c", 0, 10, 1, 2)], ["a", "b", "c"], "v");
  assert.equal(byId(v, "b").y, 5);   // Gesamt 12, belegt 6, Lücke 3
});

test("distribute: sortiert nach Position, weniger als 3 = keine Änderung", () => {
  const items = [R("c", 20, 0, 2, 2), R("a", 0, 0, 2, 2), R("b", 3, 0, 4, 2)];
  const out = C.distribute(items, ["a", "b", "c"], "h");
  assert.equal(byId(out, "b").x, 9);
  assert.deepEqual(ids(out), ["c", "a", "b"]);
  assert.deepEqual(C.distribute(items, ["a", "b"], "h"), items);
});

test("sameSize: Breite, Höhe, beides", () => {
  const items = [R("a", 0, 0, 2, 3), R("b", 5, 5, 4, 1), R("c", 9, 9, 7, 7)];
  let out = C.sameSize(items, ["a", "b"], "w");
  assert.deepEqual([byId(out, "b").w, byId(out, "b").h], [2, 1]);
  out = C.sameSize(items, ["a", "b"], "h");
  assert.deepEqual([byId(out, "b").w, byId(out, "b").h], [4, 3]);
  out = C.sameSize(items, ["a", "b"], "both");
  assert.deepEqual([byId(out, "b").w, byId(out, "b").h], [2, 3]);
  assert.equal(byId(out, "c").w, 7);
  assert.deepEqual(C.sameSize(items, ["a"], "w"), items);
});

test("Gruppen: group, expandSelection, ungroup", () => {
  const items = [R("a", 0, 0, 1, 1), R("b", 2, 0, 1, 1), R("c", 4, 0, 1, 1)];
  const g = C.group(items, ["a", "c"]);
  assert.equal(byId(g, "a").group, byId(g, "c").group);
  assert.ok(byId(g, "a").group);
  assert.equal(byId(g, "b").group, undefined);
  assert.equal(items[0].group, undefined);
  assert.deepEqual(C.expandSelection(g, ["a"]), ["a", "c"]);
  assert.deepEqual(C.expandSelection(g, ["b"]), ["b"]);
  assert.deepEqual(C.expandSelection(g, []), []);
  const u = C.ungroup(g, ["c"]);   // ganze Gruppe wird gelöst
  assert.equal(byId(u, "a").group, undefined);
  assert.equal(byId(u, "c").group, undefined);
});

test("Gruppen: neue IDs kollidieren nicht, Einzelelement bildet keine Gruppe, Zusammenlegen", () => {
  let items = [R("a", 0, 0, 1, 1), R("b", 2, 0, 1, 1), R("c", 4, 0, 1, 1), R("d", 6, 0, 1, 1)];
  items = C.group(items, ["a", "b"]);
  items = C.group(items, ["c", "d"]);
  assert.notEqual(byId(items, "a").group, byId(items, "c").group);
  const single = C.group([R("a", 0, 0, 1, 1)], ["a"]);
  assert.equal(single[0].group, undefined);
  const merged = C.group(items, ["a", "c"]);   // beide Gruppen -> eine
  assert.equal(new Set(merged.map((i) => i.group)).size, 1);
});

test("Ebenen: forward/backward/front/back", () => {
  const items = ["a", "b", "c", "d"].map((i, n) => R(i, n, 0, 1, 1));
  assert.deepEqual(ids(C.bringForward(items, ["b"])), ["a", "c", "b", "d"]);
  assert.deepEqual(ids(C.bringForward(items, ["d"])), ["a", "b", "c", "d"]);
  assert.deepEqual(ids(C.bringForward(items, ["b", "c"])), ["a", "d", "b", "c"]);
  assert.deepEqual(ids(C.sendBackward(items, ["c"])), ["a", "c", "b", "d"]);
  assert.deepEqual(ids(C.sendBackward(items, ["a"])), ["a", "b", "c", "d"]);
  assert.deepEqual(ids(C.sendBackward(items, ["c", "d"])), ["a", "c", "d", "b"]);
  assert.deepEqual(ids(C.toFront(items, ["a", "c"])), ["b", "d", "a", "c"]);
  assert.deepEqual(ids(C.toBack(items, ["b", "d"])), ["b", "d", "a", "c"]);
  assert.deepEqual(ids(C.toBack(items, [])), ["a", "b", "c", "d"]);
});

test("Ebenen: Gruppe wandert gemeinsam", () => {
  const items = [R("a", 0, 0, 1, 1), R("b", 1, 0, 1, 1, { group: "g1" }), R("c", 2, 0, 1, 1), R("d", 3, 0, 1, 1, { group: "g1" })];
  assert.deepEqual(ids(C.toFront(items, ["b"])), ["a", "c", "b", "d"]);
});

test("selectInRect: Berührung zählt, Gruppen werden ergänzt", () => {
  const items = [R("a", 0, 0, 2, 2), R("b", 10, 10, 2, 2, { group: "g1" }), R("c", 20, 0, 2, 2, { group: "g1" }), R("d", 2, 0, 2, 2)];
  assert.deepEqual(C.selectInRect(items, { x: 1, y: 1, w: 3, h: 3 }), ["a", "d"]);
  assert.deepEqual(C.selectInRect(items, { x: 9, y: 9, w: 2, h: 2 }), ["b", "c"]);
  assert.deepEqual(C.selectInRect(items, { x: 100, y: 100, w: 5, h: 5 }), []);
  assert.deepEqual(C.selectInRect(items, null), []);
  // Rahmen von rechts unten nach links oben (negative Breite)
  assert.deepEqual(C.selectInRect(items, { x: 3, y: 3, w: -3, h: -3 }), ["a", "d"]);
});

test("History: undo/redo, Verzweigung, Limit, tiefe Kopie", () => {
  const h = new C.History(3);
  assert.equal(h.canUndo(), false);
  assert.equal(h.undo(), null);
  const s1 = { items: [{ id: 1 }] };
  h.push(s1);
  s1.items[0].id = 99;                       // spätere Änderung des Originals darf nichts ändern
  h.push({ items: [{ id: 2 }] });
  assert.equal(h.canUndo(), true);
  assert.deepEqual(h.undo(), { items: [{ id: 1 }] });
  assert.equal(h.canRedo(), true);
  assert.deepEqual(h.redo(), { items: [{ id: 2 }] });
  assert.equal(h.redo(), null);
  h.undo();
  h.push({ items: [{ id: 3 }] });            // Wiederholen-Zweig weg
  assert.equal(h.canRedo(), false);
  assert.equal(h.push({ items: [{ id: 3 }] }), false);   // gleicher Stand wird nicht doppelt abgelegt
  h.push({ x: 4 }); h.push({ x: 5 });         // Limit 3: ältester fällt heraus
  assert.deepEqual(h.undo(), { x: 4 });
  assert.deepEqual(h.undo(), { items: [{ id: 3 }] });
  assert.equal(h.undo(), null);
  const got = h.redo(); got.items = "x";      // Rückgabe ist eine Kopie
  h.undo();
  assert.deepEqual(h.redo(), { x: 4 });
  h.clear();
  assert.equal(h.canUndo() || h.canRedo(), false);
});

test("duplicate: neue IDs, Versatz, Gruppen bleiben Gruppen, Eingabe unverändert", () => {
  const items = [R("a", 0, 0, 2, 2, { group: "g1" }), R("b", 3, 0, 2, 2, { group: "g1" }), R("c", 9, 9, 1, 1)];
  let n = 0;
  const res = C.duplicate(items, ["a"], { x: 1, y: 1 }, (it) => it.id + "_" + ++n);
  assert.deepEqual(res.ids, ["a_1", "b_2"]);
  assert.equal(res.items.length, 5);
  assert.deepEqual(ids(res.items), ["a", "b", "c", "a_1", "b_2"]);
  const a1 = byId(res.items, "a_1"), b2 = byId(res.items, "b_2");
  assert.deepEqual([a1.x, a1.y, b2.x, b2.y], [1, 1, 4, 1]);
  assert.equal(a1.group, b2.group);
  assert.notEqual(a1.group, "g1");
  assert.equal(items.length, 3);
  assert.equal(items[0].x, 0);
});

test("duplicate: leere Auswahl, ID-Funktion sieht bisherige Kopien", () => {
  const items = [R("a", 0, 0, 1, 1), R("b", 1, 0, 1, 1)];
  assert.deepEqual(C.duplicate(items, [], { x: 1, y: 1 }, () => "x"), { items, ids: [] });
  const fresh = (it, all) => {
    let i = 1;
    while (all.some((o) => o.id === it.id + "_" + i)) i++;
    return it.id + "_" + i;
  };
  const res = C.duplicate(items, ["a", "b"], { x: 0, y: 2 }, fresh);
  assert.deepEqual(res.ids, ["a_1", "b_1"]);
  const again = C.duplicate(res.items, ["a"], { x: 0, y: 0 }, fresh);
  assert.deepEqual(again.ids, ["a_2"]);
});

test("boundsOf", () => {
  assert.equal(C.boundsOf([]), null);
  assert.deepEqual(C.boundsOf([R("a", 1, 2, 3, 4), R("b", 5, 0, 1, 1)]), { x: 1, y: 0, w: 5, h: 6 });
});

test("Review: distribute mit breitem, früh beginnendem Element", () => {
  const items = [{ id: "a", x: 0, y: 0, w: 100, h: 10 }, { id: "b", x: 10, y: 0, w: 10, h: 10 },
    { id: "c", x: 50, y: 0, w: 10, h: 10 }];
  const out = C.distribute(items, ["a", "b", "c"], "x");
  const xs = Object.fromEntries(out.map((i) => [i.id, i.x]));
  // Ausdehnung 0..100, belegt 120 -> Lücke -10; Reihenfolge a, b, c bleibt
  assert.deepStrictEqual([xs.a, xs.b, xs.c], [0, 90, 90]);
});

test("Review: IDs wie constructor/hasOwnProperty", () => {
  const items = [{ id: "constructor", x: 0, y: 0, w: 1, h: 1 }, { id: "hasOwnProperty", x: 5, y: 0, w: 1, h: 1 },
    { id: "z", x: 9, y: 0, w: 1, h: 1 }];
  assert.strictEqual(C.selectInRect(items, { x: 100, y: 100, w: 1, h: 1 }).length, 0);
  const out = C.distribute(items, ["constructor", "hasOwnProperty", "z"], "x");
  assert.strictEqual(out.length, 3);
});

test("Review: zweimal duplizieren ergibt verschiedene IDs, zwei Gruppen bleiben getrennt", () => {
  let items = [{ id: "a", x: 0, y: 0, w: 1, h: 1 }];
  items = C.duplicate(items, ["a"], { x: 1, y: 0 }).items;
  items = C.duplicate(items, ["a"], { x: 2, y: 0 }).items;
  assert.strictEqual(new Set(items.map((i) => i.id)).size, items.length);
  const g = [{ id: "p", x: 0, y: 0, w: 1, h: 1, group: "g1" }, { id: "q", x: 2, y: 0, w: 1, h: 1, group: "g1" },
    { id: "r", x: 4, y: 0, w: 1, h: 1, group: "g2" }];
  const d = C.duplicate(g, ["p", "r"], { x: 0, y: 5 });
  const neu = d.items.filter((i) => d.ids.includes(i.id));
  const groups = new Set(neu.map((i) => i.group));
  assert.strictEqual(groups.size, 2);
  assert.ok(!groups.has("g1") && !groups.has("g2"));
});

test("units: Gruppe als ein Block, exact zerlegt", () => {
  const it = [R("a", 0, 0, 10, 10, { group: "g1" }), R("b", 50, 0, 10, 10), R("c", 20, 30, 10, 10, { group: "g1" })];
  const u = C.units(it, ["a", "b"]);
  assert.equal(u.length, 2);
  assert.deepEqual(u[0].members, ["a", "c"]);
  assert.deepEqual([u[0].x, u[0].y, u[0].w, u[0].h], [0, 0, 30, 40]);
  assert.equal(C.units(it, ["a", "b"], true).length, 2);
  assert.deepEqual(C.units(it, ["a"], true)[0].members, ["a"]);
});

test("alignUnits: Gruppe bleibt zusammen, eine Einheit richtet sich an der Fläche aus", () => {
  const it = [R("a", 10, 0, 10, 10, { group: "g1" }), R("c", 30, 20, 10, 10, { group: "g1" }), R("b", 100, 50, 20, 20)];
  const r = C.alignUnits(it, ["a", "b"], "left");
  assert.deepEqual([byId(r, "a").x, byId(r, "c").x, byId(r, "b").x], [10, 30, 10]);
  assert.equal(byId(r, "c").y, 20);
  const s = C.alignUnits(it, ["a"], "right", { w: 200, h: 100 });
  assert.deepEqual([byId(s, "a").x, byId(s, "c").x], [170, 190]);        // Gruppe 10..40 -> bis 200
  const m = C.alignUnits(it, ["b"], "vcenter", { w: 200, h: 100 });
  assert.equal(byId(m, "b").y, 40);
  assert.deepEqual(C.alignUnits(it, ["b"], "left"), it);                 // ohne Fläche und mit einer Einheit: nichts
  const one = C.alignUnits(it, ["a"], "left", { w: 200, h: 100 }, true);  // exact: nur a
  assert.deepEqual([byId(one, "a").x, byId(one, "c").x], [0, 30]);
});

test("distributeUnits: Gruppen zählen als Block, ab drei Einheiten", () => {
  const it = [R("a", 0, 0, 10, 10, { group: "g" }), R("a2", 10, 0, 10, 10, { group: "g" }),
    R("b", 30, 0, 10, 10), R("c", 100, 0, 10, 10)];
  const r = C.distributeUnits(it, ["a", "b", "c"], "x");
  // Einheiten: g (0..20), b (10 breit), c (10 breit) in 0..110: Lücke (110-40)/2 = 35
  assert.deepEqual([byId(r, "a").x, byId(r, "a2").x, byId(r, "b").x, byId(r, "c").x], [0, 10, 55, 100]);
  assert.deepEqual(C.distributeUnits(it, ["b", "c"], "x"), it);
});

test("toggleSelection: ergänzt und entfernt samt Gruppe", () => {
  const it = [R("a", 0, 0, 5, 5, { group: "g" }), R("b", 9, 0, 5, 5, { group: "g" }), R("c", 20, 0, 5, 5)];
  assert.deepEqual(C.toggleSelection(it, ["c"], ["a"]), ["a", "b", "c"]);
  assert.deepEqual(C.toggleSelection(it, ["a", "b", "c"], ["b"]), ["c"]);
  assert.deepEqual(C.toggleSelection(it, [], ["c"]), ["c"]);
});

test("move exact verschiebt nur das Einzelelement einer Gruppe", () => {
  const it = [R("a", 0, 0, 5, 5, { group: "g" }), R("b", 9, 0, 5, 5, { group: "g" })];
  const r = C.move(it, ["a"], 3, 0, null, true);
  assert.deepEqual([byId(r, "a").x, byId(r, "b").x], [3, 9]);
  assert.deepEqual([byId(C.move(it, ["a"], 3, 0), "b").x], [12]);
});
