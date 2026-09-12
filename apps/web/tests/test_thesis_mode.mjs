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
