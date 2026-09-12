// Run: node --test apps/web/tests/test_thesis_mode.mjs
//
// TestStartupThesis — the shell side. Plus the escape guard: `\uXXXX` is a JAVASCRIPT string escape.
// Inside a JS string literal the engine resolves it; sitting in raw HTML markup it is just six
// characters, and the reader sees "🕘 Recent" on the button.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC = readFileSync(new URL("../index.html", import.meta.url), "utf8");

// Everything outside <script>…</script> is markup the browser renders literally.
const MARKUP = SRC.replace(/<script[\s\S]*?<\/script>/g, "");

test("no javascript escape sequences leak into HTML markup", () => {
  const bad = [...MARKUP.matchAll(/(\\u[0-9a-fA-F]{4})/g)].map(m => m[1]);
  assert.deepEqual(bad, [],
    `these render as literal text, not characters: ${bad.join(" ")}`);
});

test("the mode's own controls carry real characters", () => {
  for (const [id, ch] of [["thesisTab", "⚗"], ["th-recent", "\u{1F558}"], ["th-reset", "↻"]]) {
    const i = MARKUP.indexOf(id);
    assert.ok(i > 0, `${id} is missing`);
    assert.ok(MARKUP.slice(i, i + 260).includes(ch), `${id} lost its glyph`);
  }
});

test("the mode is wired end to end in the shell", () => {
  assert.match(SRC, /THESIS_ENABLED = !!c\.thesis_enabled/, "the flag must come from /config");
  assert.match(SRC, /\(mode === "thesis" && THESIS_ENABLED\)/, "setMode must allow it");
  assert.match(SRC, /APP_MODE === "thesis"/, "the composer must dispatch to it");
  assert.match(SRC, /window\.TH = \{/, "the module must export");
});

test("against-evidence renders before for-evidence", () => {
  // A stress test that leads with the supporting quote is a search engine.
  assert.match(SRC, /const sides = against\.concat\(forr\)/,
    "the disconfirming side is the point of this mode and must come first");
});

test("sentiment is labelled on the row, not silently counted", () => {
  assert.match(SRC, /signal, not evidence/);
});

test("the composer is the conversation, not a one-shot input", () => {
  // The first version took the thesis, dumped ten claims, and left buttons. What you typed after
  // that was stored and never read.
  const fn = SRC.slice(SRC.indexOf("async function submit(text)"), SRC.indexOf("async function open(id)"));
  assert.match(fn, /if\(STATE\.id\)\{[\s\S]{0,300}return say\(t\)/,
    "typing after the thesis exists must go to the agent as a reply");
});

test("the agent replies to what was said rather than walking the ledger", () => {
  // Server-side guard mirrored here so the shell's contract is visible: /turn carries the text.
  assert.match(SRC, /const say = \(text\) => post\("\/turn", \{text: text\}\)/);
});

test("it opens on one claim, not ten", () => {
  const fn = SRC.slice(SRC.indexOf("async function submit(text)"), SRC.indexOf("async function open(id)"));
  assert.match(fn, /await turn\(\)/, "the first exchange must start the conversation");
});

test("the ledger is collapsed behind a summary", () => {
  assert.match(SRC, /<details class="th-ledger"/, "ten claims must not be the first thing shown");
  assert.match(SRC, /claims tested<\/span>/, "the summary has to say what is in there");
});

test("evidence rides the turn that argues from it", () => {
  assert.match(SRC, /function payloadHtml\(pay\)/);
  assert.match(SRC, /i === turns\.length - 1/, "only the live turn carries its grounds");
});

test("the takes render as a table with both cases side by side", () => {
  assert.match(SRC, /function takesHtml\(d\)/);
  assert.match(SRC, /<th>The take<\/th><th>The case for<\/th><th>The case against<\/th>/,
    "a reader has to be able to compare the two cases without scrolling between them");
});

test("an empty side says so rather than being left blank", () => {
  // "There is no case to make for this yet" is the most useful sentence this mode produces.
  assert.match(SRC, /Nothing in the record speaks to this side yet/);
});

test("every row can be asked about, and the question carries its rung", () => {
  assert.match(SRC, /async function askRow\(rung, text\)/);
  assert.match(SRC, /body: JSON\.stringify\(\{text: text, rung: rung\}\)/,
    "without the rung the answer lands on whatever claim was in focus, not the one asked about");
  assert.match(SRC, /data-asked="/, "each row needs its own control");
});

test("the table stacks into cards on a phone", () => {
  const css = SRC.slice(SRC.indexOf(".th-table{"), SRC.indexOf(".th-table{") + 2600);
  assert.match(css, /@media \(max-width:760px\)/, "a side-by-side table is unreadable at 400px");
  assert.match(css, /td\[data-col\]::before\{content:attr\(data-col\)/,
    "stacked cells lose their column, so the label has to come back");
});

test("citations hang off the case they support", () => {
  assert.match(SRC, /function citesHtml\(ev, side\)/);
  assert.match(SRC, /e\.signal_only \? " \\u00b7 signal"/,
    "sentiment stays labelled even when it is only a chip");
});
