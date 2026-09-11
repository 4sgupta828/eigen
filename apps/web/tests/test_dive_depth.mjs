// Run: node --test apps/web/tests/test_dive_depth.mjs
//
// A dive READS. The mode used to default to "what we hold" and then offer, one priced button at a
// time, to read their site and then the web — so the dossier a reader got depended on how many
// upgrade buttons they found. These tests pin the default and keep the per-leg clicks from coming
// back.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC = readFileSync(new URL("../index.html", import.meta.url), "utf8");

test("DeepDive starts at the deepest read", () => {
  assert.match(SRC, /busy: false, depth: "full"/,
    "the mode's default depth is what decides what a first-time reader sees");
});

test("the depth control agrees with the default", () => {
  // A bar whose pressed button says `held` while STATE.depth is `full` is a lie on screen.
  const bar = SRC.slice(SRC.indexOf('id="dd-depth"'), SRC.indexOf('id="dd-depth"') + 1200);
  assert.match(bar, /data-depth="full" aria-pressed="true"/);
  assert.ok(!/data-depth="(held|read)" aria-pressed="true"/.test(bar),
    "only one depth may be pressed, and it is the deepest");
});

test("a small spend does not interrupt the reader", () => {
  assert.match(SRC, /const AUTO_USD = /,
    "there must be a ceiling under which a dive just runs");
  assert.match(SRC, /if\(usd <= AUTO_USD\) return true;/);
});

test("a spend above the ceiling is still shown and still asked", () => {
  assert.match(SRC, /window\.confirm\("This reads "[\s\S]{0,200}Projected cost/,
    "the gate is the number in front of the reader, not the absence of one");
});

test("the priced per-leg upgrade button is gone", () => {
  for(const dead of ["adv-deep", "deep.offer", "Read the site properly", "Read it — $"]){
    assert.ok(!SRC.includes(dead), `"${dead}" is back — the incremental read returned`);
  }
});

test("the founder's own reading dives all the way, and discovers", () => {
  const fn = SRC.slice(SRC.indexOf("async function readStartup()"),
                       SRC.indexOf("function profileHtml(d)"));
  assert.match(fn, /depth: "full", discover: true/,
    "a founder who typed their website asked to be read, not to be quoted a price");
  assert.ok(!/project_only/.test(fn), "readStartup must not price-and-offer any more");
});

test("the basis is read as a list of legs, not matched as a fixed string", () => {
  // Adding the corpus leg changed every basis string. An exact-string map would have fallen through
  // to printing "held+corpus+read+web" at the reader.
  assert.match(SRC, /function basisWords\(basis\)/);
  assert.match(SRC, /corpus: "our corpus"/);
  assert.ok(!SRC.includes('"held+read+web": "their site and the web, read"'),
    "the old exact-match basis map is back");
});

test("a corpus row shows the document it came from", () => {
  // These rows used to fall through to factRow, which prints a claim and drops the document title —
  // the one thing that says whose document the passage is.
  assert.match(SRC, /corpus: corpusRow/, "the corpus section kind must have its own renderer");
  assert.match(SRC, /function corpusRow\(c\)[\s\S]{0,400}c\.document_title/);
  assert.match(SRC, /function corpusRow\(c\)[\s\S]{0,600}c\.quote/,
    "the passage is the evidence; a headline without it is a claim to take on faith");
});

test("dossier sections can be narrower than their longest line", () => {
  // A grid item defaults to min-width:auto, so one long URL inside a quote made every dossier
  // section 641px wide inside a 363px column and the whole page scrolled sideways on a phone.
  assert.match(SRC, /\.dd-secs > \*, \.dd-rows > \*\{min-width:0;\}/,
    "without this the grid is as wide as its widest unbreakable string");
  assert.match(SRC, /\.dd-quote, \.dd-secnote, \.dd-v, \.dd-doc\{overflow-wrap:anywhere;\}/);
});
