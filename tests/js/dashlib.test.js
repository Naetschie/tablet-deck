"use strict";
// Tests für web/editor/dashlib.js (node --test tests/js/); das Schema kommt echt aus bridge/dashboard.py.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const L = require("../../web/editor/dashlib.js");

const ROOT = path.resolve(__dirname, "..", "..");
let schema = null;
try {
  schema = JSON.parse(execFileSync("python", ["-c", "import json; from bridge import dashboard; print(json.dumps(dashboard.schema()))"],
    { cwd: ROOT, encoding: "utf8" }));
} catch (e) { /* ohne Python: Schema-Tests überspringen */ }
const needSchema = { skip: schema ? false : "Python/Schema nicht verfügbar" };

test("fitScale passt ein, vergrößert höchstens bis max", () => {
  assert.equal(L.fitScale(576, 400, 1152, 800), 0.5);
  assert.equal(L.fitScale(2000, 400, 1152, 800), 0.5);
  assert.equal(L.fitScale(5000, 5000, 100, 100), 2);
  assert.equal(L.fitScale(0, 400, 1152, 800), 1);
});

test("toEditable vergibt IDs, toSave entfernt sie wieder und rundet", () => {
  const dash = { title: "T", width: 400, height: 300, background: "#000", widgets: [
    { type: "text", x: 1.234, y: 2, w: 100, h: 20, text: "a" }, { type: "rect", x: 0, y: 0, w: 5, h: 5, group: "g1" }] };
  const e = L.toEditable(dash);
  assert.deepEqual(e.widgets.map((w) => w.id), ["w1", "w2"]);
  assert.equal(dash.widgets[0].id, undefined);          // Eingabe unverändert
  const s = L.toSave(e);
  assert.equal(s.widgets[0].id, undefined);
  assert.equal(s.widgets[0].x, 1.23);
  assert.equal(s.widgets[1].group, "g1");
  assert.equal(L.nextId(e.widgets), "w3");
});

test("newWidget: mittig, aufs Raster, begrenzt auf die Fläche", () => {
  const w = L.newWidget("gauge", { width: 1152, height: 800 }, 8, []);
  assert.equal(w.type, "gauge");
  assert.equal(w.x, 480); assert.equal(w.y, 304);                // (952/2 = 476 -> 480, 300 -> 304)
  assert.equal(w.id, "w1");
  const big = L.newWidget("cores", { width: 300, height: 150 }, 8, [{ id: "w4" }]);
  assert.equal(big.w, 300); assert.equal(big.h, 150); assert.equal(big.x, 0); assert.equal(big.id, "w5");
  Object.keys(L.TYPE_DEFAULTS).forEach((t) => assert.ok(L.TYPE_LABELS[t], t));
});

test("hitTest: oberstes Widget gewinnt", () => {
  const ws = [{ id: "a", x: 0, y: 0, w: 100, h: 100 }, { id: "b", x: 50, y: 50, w: 100, h: 100 }];
  assert.equal(L.hitTest(ws, 60, 60).id, "b");
  assert.equal(L.hitTest(ws, 10, 10).id, "a");
  assert.equal(L.hitTest(ws, 500, 5), null);
});

test("parseInput: Zahlen, Pflicht, leer", needSchema, () => {
  const f = schema.fields;
  assert.deepEqual(L.parseInput(f.w, "120,5", schema, true), { value: 120.5 });
  assert.equal(L.parseInput(f.w, "0", schema, true).error, "größer als 0");
  assert.equal(L.parseInput(f.w, "", schema, true).error, "Pflichtfeld");
  assert.deepEqual(L.parseInput(f.min, "", schema, false), { remove: true });
  assert.equal(L.parseInput(f.min, "-", schema, false).error, "Zahl erwartet");
  assert.equal(L.parseInput(f.decimals, "1,5", schema, false).error, "ganze Zahl erwartet");
  assert.deepEqual(L.parseInput(f.decimals, "2", schema, false), { value: 2 });
  assert.equal(L.parseInput(f.scale, "0", schema, false).error, "nicht 0");
  assert.equal(L.parseInput(f.weight, "650,5", schema, false).error, "ganze Zahl erwartet");
  assert.equal(L.parseInput(f.size, "2", schema, false).error, "mindestens 4");
});

test("parseInput: Farbe, Sensor, Text, Gruppe", needSchema, () => {
  const f = schema.fields;
  assert.deepEqual(L.parseInput(f.color, " #4fb3ff ", schema, false), { value: "#4fb3ff" });
  assert.deepEqual(L.parseInput(f.color, "rgba(0,0,0,.5)", schema, false), { value: "rgba(0,0,0,.5)" });
  assert.ok(L.parseInput(f.color, "rot", schema, false).error);
  assert.deepEqual(L.parseInput(f.sensor, "gpu.temp", schema, true), { value: "gpu.temp" });
  assert.ok(L.parseInput(f.sensor, "GPU Temp", schema, true).error);
  assert.deepEqual(L.parseInput(f.text, " a ", schema, true), { value: " a " });
  assert.equal(L.parseInput(f.group, "g 1", schema, false).error, "nur a-z, 0-9, _ und -");
  assert.ok(L.parseInput(f.label, "x".repeat(61), schema, false).error);
});

test("fieldError: Zonen und Auswahl", needSchema, () => {
  const z = schema.fields.zones;
  assert.equal(L.fieldError(z, [{ from: 0.5, color: "#fff" }, { from: 0.8, color: "#f00" }], schema), null);
  assert.match(L.fieldError(z, [{ from: 0.8, color: "#fff" }, { from: 0.5, color: "#f00" }], schema), /aufsteigend/);
  assert.match(L.fieldError(z, [{ from: 2, color: "#fff" }], schema), /0 bis 1/);
  assert.match(L.fieldError(z, [{ from: NaN, color: "#fff" }], schema), /0 bis 1/);
  assert.equal(L.fieldError(schema.fields.font, "mono", schema), null);
  assert.ok(L.fieldError(schema.fields.font, "comic", schema));
  assert.equal(L.fieldError(schema.fields.ring, true, schema), null);
});

test("mitgelieferte Dashboards bestehen die Feldprüfung des Editors", needSchema, () => {
  ["deck", "mobro"].forEach((n) => {
    const d = JSON.parse(fs.readFileSync(path.join(ROOT, "dashboards", n + ".json"), "utf8"));
    d.widgets.forEach((w, i) => {
      assert.ok(schema.types[w.type], n + " " + i);
      Object.keys(w).forEach((k) => {
        if (k === "type") return;
        assert.ok(schema.types[w.type].fields.indexOf(k) >= 0, `${n}[${i}] ${w.type}: Feld ${k} fehlt im Schema`);
        assert.equal(L.fieldError(schema.fields[k], w[k], schema), null, `${n}[${i}] ${w.type}.${k}`);
      });
    });
  });
});

test("Palette: jede Art hat Standardwerte, die dem Schema genügen", needSchema, () => {
  Object.keys(schema.types).forEach((t) => {
    const w = L.newWidget(t, { width: 1152, height: 800 }, 8, []);
    schema.types[t].required.forEach((k) => assert.ok(k in w, t + " braucht " + k));
    Object.keys(w).forEach((k) => {
      if (k === "type" || k === "id") return;
      assert.ok(schema.types[t].fields.indexOf(k) >= 0, t + "." + k);
      assert.equal(L.fieldError(schema.fields[k], w[k], schema), null, t + "." + k);
    });
    assert.ok(L.TYPE_LABELS[t], t);
  });
});

test("Farbwähler: Umrechnung und Alpha", () => {
  assert.equal(L.colorToPicker("#abc"), "#aabbcc");
  assert.equal(L.colorToPicker("#4FB3FF80"), "#4fb3ff");
  assert.equal(L.colorToPicker("rgba(1,2,3,.5)"), "#000000");
  assert.equal(L.pickerToColor("#112233", "#4FB3FF80"), "#11223380");
  assert.equal(L.pickerToColor("#112233", "#fff"), "#112233");
});

test("filterSensors und Wertanzeige", () => {
  const l = [{ id: "cpu.load", name: "CPU-Last", unit: "%", value: 12.34 }, { id: "gpu.temp", name: "GPU Temperatur", unit: "°C", value: 61 },
    { id: "fan.cpu", name: "CPU Fan", unit: "RPM", value: 1200 }];
  assert.deepEqual(L.filterSensors(l, "cpu").map((s) => s.id), ["cpu.load", "fan.cpu"]);
  assert.deepEqual(L.filterSensors(l, "CPU fan").map((s) => s.id), ["fan.cpu"]);
  assert.equal(L.filterSensors(l, "", 2).length, 2);
  assert.equal(L.formatSensorValue(l[0]), "12,3 %");
  assert.equal(L.formatSensorValue(l[2]), "1200 RPM");
  assert.equal(L.formatSensorValue({ id: "x" }), "–");
});

test("snapMove: Raster, Kanten anderer Widgets, Gruppe, Grenzen", () => {
  const items = [{ id: "a", x: 10, y: 10, w: 50, h: 20 }, { id: "b", x: 200, y: 100, w: 40, h: 40 }];
  let r = L.snapMove(items, ["a"], 13, 7, 8, 0, null);
  assert.equal(r.items[0].x, 24); assert.equal(r.items[0].y, 16);       // 23 -> 24, 17 -> 16
  r = L.snapMove(items, ["a"], 189, 85, 8, 6, null);                     // linke Kante 199 -> 200 (Kante von b)
  assert.equal(r.items[0].x, 200);
  assert.ok(r.guides.some((g) => g.axis === "x" && g.pos === 200));
  const grp = [{ id: "a", x: 0, y: 0, w: 10, h: 10, group: "g1" }, { id: "b", x: 20, y: 0, w: 10, h: 10, group: "g1" }];
  r = L.snapMove(grp, ["a"], 16, 0, 8, 0, null);
  assert.deepEqual([r.items[0].x, r.items[1].x], [16, 36]);
  r = L.snapMove(items, ["a"], -50, -50, 8, 0, { w: 400, h: 300 });
  assert.equal(r.items[0].x, 0); assert.equal(r.items[0].y, 0);
});

test("snapResize: bewegte Kanten rasten ein, Mindestgröße, Grenzen", () => {
  const it = { id: "a", x: 16, y: 16, w: 100, h: 40 };
  let r = L.snapResize(it, "se", 13, 5, 8, [], 0, { w: 2, h: 2 }, null);
  assert.equal(r.rect.w, 112);                                           // rechte Kante 129 -> 128
  assert.equal(r.rect.h, 48);                                            // untere Kante 61 -> 64
  r = L.snapResize(it, "w", 30, 0, 8, [], 0, { w: 2, h: 2 }, null);
  assert.equal(r.rect.x, 48); assert.equal(r.rect.w, 68);
  r = L.snapResize(it, "e", 500, 0, 8, [], 0, { w: 2, h: 2 }, { w: 200, h: 100 });
  assert.equal(r.rect.x + r.rect.w, 200);
  r = L.snapResize(it, "e", -500, 0, 8, [], 0, { w: 2, h: 2 }, null);
  assert.equal(r.rect.w, 2);
  r = L.snapResize(it, "e", 85, 0, 8, [{ id: "b", x: 203, y: 0, w: 10, h: 10 }], 6, { w: 2, h: 2 }, null);
  assert.equal(r.rect.x + r.rect.w, 203);
  assert.ok(r.guides.some((g) => g.axis === "x" && g.pos === 203));
});
