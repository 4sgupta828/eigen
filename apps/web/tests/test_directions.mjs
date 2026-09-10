// Run: node --test apps/web/tests/test_directions.mjs
//
// index.html is a stack of per-mode IIFEs. A helper two modes share must be defined at TRUE top level,
// and when it is not the failure is silent: the buttons render, nothing binds, and clicking does
// nothing. That cost a debugging round here and has cost others before (DeepDive's formatter, the
// shared progress banner), so it is pinned structurally.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC = readFileSync(new URL("../index.html", import.meta.url), "utf8");

/** Is this declaration outside every `(function(){ … })()` in the file? */
function atTopLevel(decl) {
  const at = SRC.indexOf(decl);
  assert.ok(at > 0, `not found in index.html: ${decl}`);
  // walk from the last <script> open to `at`, tracking IIFE nesting by brace depth
  const start = SRC.lastIndexOf("<script", at);
  let depth = 0, inIife = 0;
  const region = SRC.slice(start, at);
  const iife = /\(function\s*\w*\s*\([^)]*\)\s*\{|\}\s*\)\s*\(\s*\)\s*;/g;
  let m;
  while ((m = iife.exec(region))) inIife += m[0].startsWith("(") ? 1 : -1;
  return inIife <= 0;
}

test("wireDirs is shared by both modes, so it must be top level", () => {
  assert.ok(atTopLevel("function wireDirs(box, apply)"),
    "wireDirs is called from the investors IIFE; inside another IIFE it is invisible there");
});

test("each mode owns its own apply, so those may be scoped", () => {
  assert.ok(SRC.includes("function applyDirection(i)"), "startups apply missing");
  assert.ok(SRC.includes("function applyIvDirection(i)"), "investors apply missing");
});

test("a tapped direction is never relaxed away", () => {
  // Smart relaxing widens a brief that matched too little; a filter the reader chose is a decision.
  const i = SRC.indexOf("function applyDirection(i)");
  const body = SRC.slice(i, i + 900);
  assert.match(body, /relax:\s*false/, "a direction the reader tapped must not be relaxed away");
});

test("directions sit ABOVE the rail, with the intent debugger", () => {
  // They answer the same question — "these are not quite right, now what" — and were split by twenty rows
  // of filters, which is most of a phone screen of scrolling before you reach the second half.
  assert.match(SRC, /wireDirs\(ib,\s*applyDirection\)/, "startups directions belong in the intent slot");
  assert.match(SRC, /wireDirs\(\$\("#iv-intent"\),\s*applyIvDirection\)/, "investors likewise");
  for (const slot of ["su-intent", "su-rail", "iv-intent", "iv-rail"]) {
    assert.ok(SRC.includes(`id="${slot}"`), `${slot} missing`);
  }
  assert.ok(SRC.indexOf('id="su-intent"') < SRC.indexOf('id="su-rail"'), "startups slot must precede the rail");
  assert.ok(SRC.indexOf('id="iv-intent"') < SRC.indexOf('id="iv-rail"'), "investors slot must precede the rail");
});

test("the row explains itself when there is nothing to offer", () => {
  // A search returning a handful of results legitimately has nothing left to split — but a row that just
  // vanishes is indistinguishable from a broken feature, and it vanished on exactly the narrow searches a
  // reader studies most closely. Reported twice as "still no directions".
  const i = SRC.indexOf("function dirsHtml");
  const body = SRC.slice(i, i + 1100);
  assert.match(body, /d\.steering/, "must read the reason the gate gave");
  assert.match(body, /dirs-none/, "must render the reason, not return empty");
});
