"use strict";
// Tests für web/stats/render.js (StatsView) mit einem minimalen DOM-Ersatz (node --test tests/js/)
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

class FakeEl {
  constructor(tag) { this.tag = tag; this.attrs = {}; this.children = []; this._text = ""; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  appendChild(c) { this.children.push(c); return c; }
  removeChild(c) { this.children.splice(this.children.indexOf(c), 1); return c; }
  get firstChild() { return this.children[0] || null; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
}
global.document = { createElementNS: (ns, tag) => new FakeEl(tag) };
global.window = {};
require("../../web/stats/render.js");
const SV = global.window.StatsView;

function all(e, tag, out) {
  out = out || [];
  if (e.tag === tag) out.push(e);
  e.children.forEach((c) => all(c, tag, out));
  return out;
}

const DASH = { title: "T", width: 400, height: 300, background: "#101010", widgets: [
  { type: "value", x: 10, y: 10, w: 200, h: 40, sensor: "cpu.load", label: "CPU ", unit: "%" },
  { type: "bar", x: 10, y: 60, w: 200, h: 10, sensor: "cpu.load" },
  { type: "line", x: 10, y: 80, w: 200, h: 100, sensor: "cpu.load", seconds: 30 },
  { type: "text", x: 10, y: 200, w: 100, h: 20, text: "Hallo" },
  { type: "cores", x: 10, y: 230, w: 300, h: 60 },
  { type: "fans", x: 220, y: 10, w: 150, h: 100 }] };

test("mount zeichnet und füllt mit Werten", () => {
  const parent = new FakeEl("div"), state = SV.createState();
  const m = SV.mount(DASH, parent, state);
  assert.equal(parent.children[0], m.svg);
  assert.equal(m.svg.attrs.viewBox, "0 0 400 300");
  // ohne Werte: Strich
  assert.ok(m.svg.textContent.indexOf("–") >= 0);
  const t0 = 1000000;
  SV.ingest(state, m.view, { "cpu.load": 42.5, "cpu.clock.0": 3000, "cpu.clock.1": 4000, "fan.cpu": 900 },
    { "cpu.load": { name: "CPU-Last", unit: "%", min: 0, max: 100 }, "cpu.clock.0": { name: "P-Kern 1", unit: "MHz", min: 0, max: 5500 },
      "cpu.clock.1": { name: "E-Kern 2", unit: "MHz", min: 0, max: 5500 }, "fan.cpu": { name: "CPU Fan", unit: "RPM" } }, t0);
  SV.draw(m.view, state, t0 + 100);
  const txt = m.svg.textContent;
  assert.ok(txt.indexOf("CPU 42,5%") >= 0 || txt.indexOf("42,5") >= 0, txt);
  assert.ok(txt.indexOf("Hallo") >= 0);
  assert.ok(txt.indexOf("P1") >= 0 && txt.indexOf("E2") >= 0, "Kerne: " + txt);
  assert.ok(txt.indexOf("CPU Fan") >= 0 && txt.indexOf("900") >= 0, "Lüfter");
  const rects = all(m.svg, "rect");
  assert.ok(rects.some((r) => r.attrs.width === "85.0"), "Balken bei 42,5 % von 200");
  assert.deepEqual(m.view.lineSensors, { "cpu.load": 30 });
  assert.equal(state.hist["cpu.load"].length, 1);
});

test("veraltete Werte zeigen Strich", () => {
  const parent = new FakeEl("div"), state = SV.createState();
  const m = SV.mount(DASH, parent, state);
  SV.ingest(state, m.view, { "cpu.load": 10 }, {}, 1000);
  SV.draw(m.view, state, 1000 + SV.STALE_MS + 1);
  const vals = all(m.svg, "tspan").map((t) => t.textContent).join("|");
  assert.ok(vals.indexOf("10") < 0, vals);
});

test("Linienverlauf hält nur das Fenster", () => {
  const parent = new FakeEl("div"), state = SV.createState();
  const m = SV.mount(DASH, parent, state);
  for (let i = 0; i < 100; i++) SV.ingest(state, m.view, { "cpu.load": i }, {}, i * 1000);
  const h = state.hist["cpu.load"];
  assert.ok(h.length <= 36, h.length);                // 30 s + 5 s Puffer
  assert.equal(h[h.length - 1][1], 99);
});

test("deck.json und mobro.json lassen sich bauen", () => {
  ["deck", "mobro"].forEach((n) => {
    const d = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "dashboards", n + ".json"), "utf8"));
    const state = SV.createState(), m = SV.mount(d, new FakeEl("div"), state);
    SV.ingest(state, m.view, { "cpu.load": 5 }, {}, 1);
    SV.draw(m.view, state, 2);
    assert.equal(m.svg.attrs.viewBox, `0 0 ${d.width} ${d.height}`);
  });
});

test("reine Helfer", () => {
  assert.equal(SV.formatNumber(3.14159, 2), "3,14");
  assert.equal(SV.formatNumber(250), "250");
  assert.equal(SV.fraction(150, 0, 100), 1);
  assert.equal(SV.formatTime("HH:mm", new Date(2020, 0, 2, 3, 4, 5)), "03:04");
});
