// Run: node --test apps/web/tests/test_auth_gate.mjs
//
// The gate captures name + email at landing so every reader is identified. The old "Not now" waiver
// (look around first) was removed on purpose: everyone creates an account / identifies before using
// the product. The remaining runs-based logic still governs WHEN a returning, unattested reader is
// re-prompted; there is simply no way to dismiss the gate without continuing.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC = readFileSync(new URL("../index.html", import.meta.url), "utf8");

test("the gate has no waiver — the reader must identify to continue", () => {
  assert.ok(!/id="idskip"/.test(SRC), "the skip control must be gone (no 'Not now')");
  assert.ok(!/Not now/.test(SRC), "no 'Not now' escape hatch");
  assert.match(SRC, /id="idgo"/, "the continue control must remain");
});

test("the allowance is a named constant, not a magic number", () => {
  assert.match(SRC, /const FREE_RUNS = \d+/);
});

test("the gate becomes required once the free runs are spent", () => {
  const i = SRC.indexOf("function gateRequired");
  assert.ok(i > 0, "no gateRequired()");
  const body = SRC.slice(i, i + 420);
  assert.match(body, /runsUsed\(\) >= FREE_RUNS/, "must compare runs against the allowance");
  assert.match(body, /loggedIn\(\)/, "a signed-in reader is never gated");
  assert.match(body, /isSharedLink\(\)/, "a shared link must stay readable without an account");
  assert.match(body, /ACCOUNTS_ENABLED/, "accounts off → no gate at all");
});

test("runs are counted at the one place every mode's search passes through", () => {
  const i = SRC.indexOf('$("#ask").addEventListener("submit"');
  assert.ok(i > 0, "no submit handler");
  const body = SRC.slice(i, i + 900);
  assert.match(body, /gateRequired\(\)\)\s*\{\s*showGate\(true\);\s*return;/, "a spent allowance must block the run");
  assert.match(body, /noteRun\(\)/, "a run that happens must be counted");
  // Guided restarts itself with send("") — charging that would lock a reader out unasked.
  assert.match(body, /question \|\| ATTACHMENTS\.length/, "an empty submit is not a run");
});

test("the gate scrolls on a short screen", () => {
  // It was a fixed grid with place-items:center and no overflow, so on a phone — where the
  // on-screen keyboard also halves the viewport — a tall card was clipped at BOTH ends and
  // "continue" could not be reached.
  const i = SRC.indexOf(".idmodal{position:fixed");
  assert.ok(i > 0, "no overlay rule");
  const block = SRC.slice(i, i + 620);
  assert.match(block, /overflow-y:auto/, "the overlay must scroll");
  assert.match(block, /\.idcard\{[^}]*margin:auto/,
    "margin:auto is the centring that still scrolls; place-items:center alone clips the top");
});

test("the role dropdown is gone, with no dangling references", () => {
  for(const dead of ["idprof", "I am a", "idhint"]){
    assert.ok(!SRC.includes(dead), `"${dead}" still present`);
  }
});
