// Run: node --test apps/web/tests/test_guided_render.mjs
//
// This pins the bug that made Guided sit on "thinking…" forever. `readingName` lived INSIDE the
// Startup Search IIFE; Guided's ready card called it bare, so it threw ReferenceError, the
// `b.innerHTML = …` assignment never ran, and the stale spinner DOM stayed up with every chip
// inert. Nothing surfaced — no console error the user would see, no failed request.
//
// The lesson this file encodes: a test that lifts functions out of index.html into ONE scope
// cannot see a cross-module scope bug, because the lifting is what creates the scope. So this
// loads the whole page script into a stubbed DOM and drives the real SG.enter() render path.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const PAGE = join(dirname(fileURLToPath(import.meta.url)), "..", "index.html");

// `esc()` in the page is `d.textContent = s; return d.innerHTML` — so the stub must mirror one into
// the other, or every escaped string comes back empty and the assertions below pass on blanks.
function el(tag = "div") {
  const node = { tagName: tag, className: "", id: "", hidden: false, style: {}, dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false }, children: [], value: "", checked: false,
    appendChild(c) { this.children.push(c); return c; }, removeChild() {}, setAttribute() {}, getAttribute: () => null,
    addEventListener() {}, removeEventListener() {}, querySelector: () => null, querySelectorAll: () => [],
    scrollIntoView() {}, focus() {}, closest: () => null, remove() {}, insertAdjacentHTML() {},
    getBoundingClientRect: () => ({ top: 0, left: 0, width: 0, height: 0 }), cloneNode: () => el(tag) };
  let text = "", html = "";
  Object.defineProperty(node, "textContent", {
    get: () => text,
    set(v) { text = v == null ? "" : String(v); html = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); },
  });
  Object.defineProperty(node, "innerHTML", { get: () => html, set(v) { html = v == null ? "" : String(v); } });
  return node;
}

function loadPage() {
  const html = readFileSync(PAGE, "utf8");
  const src = [...html.matchAll(/<script(?![^>]*src=)[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]).join("\n");
  const store = {};
  const box = el();
  const sandbox = {
    console: { log() {}, warn() {}, error() {}, info() {} }, JSON, Date, Math, Promise, Set, Map, Array, Object,
    String, Number, Boolean, RegExp, Error, isNaN, parseInt, parseFloat, encodeURIComponent, decodeURIComponent,
    URL, URLSearchParams, TextDecoder, AbortController,
    setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
    requestAnimationFrame: () => 0, fetch: async () => ({ ok: true, json: async () => ({}) }),
    localStorage: { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } },
    sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    location: { hash: "", href: "http://x/", search: "" }, history: { replaceState() {}, pushState() {} },
    navigator: { userAgent: "node", language: "en" }, matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
    alert() {}, confirm: () => true, prompt: () => null, addEventListener() {}, removeEventListener() {},
    EventSource: function () { return { addEventListener() {}, close() {} }; },
    WebSocket: function () { return { addEventListener() {}, close() {}, send() {} }; },
    document: { createElement: el, createTextNode: t => ({ textContent: t }), body: el("body"), head: el("head"),
      documentElement: el("html"), cookie: "", readyState: "complete", addEventListener() {}, removeEventListener() {},
      getElementById: () => el(), querySelectorAll: () => [],
      querySelector: sel => (sel === "#guidedbody" ? box : el()) },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox; sandbox.self = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox, { filename: "index.html" });
  return { sandbox, box, store };
}

// A READY turn shaped exactly like the one production returns, including the `recipes` list whose
// rendering is what reached across the module seam.
const READY_TURN = {
  stage: "ready", question: null,
  state: { kernel: { contract: { kind: "company", text: "ml infra", must: { tech_area: ["ai_infra"] } },
                     understanding: "You want the infrastructure layer.", ruled_out: ["consumer apps"], asked: ["country"] },
           transcript: [{ role: "user", text: "ml infra" }], pending: null, opening: "ml infra", notes: [] },
  labels: { keys: { tech_area: "Tech area" }, values: { ai_infra: "AI infra" }, units: {} },
  ready: { understood: "You want the infrastructure layer.", contract: { must: { tech_area: ["ai_infra"] } },
           pool: 361, brief: "ml infra", advice: ["a"], notes: [], ruled_out: ["consumer apps"], diagnostics: [],
           recipes: [{ name: "strict", why: "as ratified", pool: 361, must: {}, prefer: {} },
                     { name: "relaxed:country", why: "", pool: 800, must: {}, prefer: {} }] },
};

test("the guided ready card renders — every helper it calls is in scope", () => {
  const { sandbox, box, store } = loadPage();
  assert.equal(typeof sandbox.SG, "object", "SG must be exported");
  store["eigen_guided"] = JSON.stringify({ state: READY_TURN.state, last: READY_TURN, at: Date.now() });
  sandbox.SG.enter(false);
  const out = box.innerHTML;
  // The tell: on a ReferenceError, safeRender swaps in the error card instead of the real one.
  assert.ok(!/could not be drawn/.test(out), `render threw: ${out.slice(0, 200)}`);
  assert.match(out, /sg-understood/, "the analyst's read-back must render");
  assert.match(out, /sg-reading/, "the search variations must render (this is what called readingName)");
  assert.match(out, /everything you asked for/, "readingName must resolve, not just exist");
});

test("a stored thread is picked up again instead of restarting", () => {
  const { sandbox, box, store } = loadPage();
  store["eigen_guided"] = JSON.stringify({ state: READY_TURN.state, last: READY_TURN, at: Date.now() });
  sandbox.SG.enter(false);
  assert.match(box.innerHTML, /sg-understood/);
  sandbox.SG.enter(true);                    // fresh = true must forget it
  assert.equal(store["eigen_guided"], undefined, "starting over must clear the remembered thread");
});

test("a thread older than the memory window is not resurrected", () => {
  const { sandbox, box, store } = loadPage();
  store["eigen_guided"] = JSON.stringify({ state: READY_TURN.state, last: READY_TURN, at: Date.now() - 8 * 864e5 });
  sandbox.SG.enter(false);
  assert.ok(!/sg-understood/.test(box.innerHTML), "an 8-day-old thread must not come back");
});
