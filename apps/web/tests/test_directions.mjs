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

test("directions render inside the results box both modes wire", () => {
  assert.match(SRC, /wireDirs\(box,\s*applyDirection\)/, "startups must wire its directions");
  assert.match(SRC, /wireDirs\(box\(\),\s*applyIvDirection\)/, "investors must wire its directions");
});
