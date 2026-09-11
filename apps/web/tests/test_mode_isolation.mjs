// Run: node --test apps/web/tests/test_mode_isolation.mjs
//
// Switching modes used to carry the previous mode's question into the new box, "New chat" reset more
// than the mode you were in, and the composer could end up with a placeholder belonging to a mode you
// had left — or none at all. Each of those was a separate defect with the same symptom: the intake box
// telling you about a mode you are not in.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const fn = (name, len = 3000) => {
  const i = SRC.indexOf(`function ${name}(`);
  assert.ok(i > 0, `no ${name}()`);
  return SRC.slice(i, i + len);
};

test("setMode captures the previous mode BEFORE overwriting APP_MODE", () => {
  const body = fn("setMode");
  const prev = body.indexOf("PREV_MODE = APP_MODE");
  const set = body.indexOf("APP_MODE = mode");
  assert.ok(prev > 0, "setMode must remember the mode it is leaving");
  assert.ok(prev < set, "the capture must happen before APP_MODE is reassigned");
});

test("a real mode change clears the composer", () => {
  assert.match(fn("setMode"), /PREV_MODE !== mode\)\s*\{\s*q\.value = ""/,
    "another mode's question is not this mode's question");
});

test("no branch guards a clear on APP_MODE after APP_MODE was already reassigned", () => {
  // This was the original bug: `if(APP_MODE !== "deepdive") q.value = ""` inside the deepdive
  // branch could never be true, so nothing on the page ever cleared the box.
  assert.ok(!/if\(APP_MODE !== "deepdive"\)\s*q\.value/.test(SRC),
    "dead guard: APP_MODE is already the new mode by the time a branch runs");
});

test("New chat resets only the mode you are in", () => {
  const body = fn("newConversation", 2600);
  const wipe = body.indexOf("THREAD = {session_id:null, turns:[]}");
  assert.ok(wipe > 0, "Q&A still needs its thread cleared");
  for(const mode of ["panel","triage","startups","investors","guided","deepdive","voices"]){
    const at = body.indexOf(`APP_MODE === "${mode}"`);
    assert.ok(at > 0, `New chat must handle ${mode}`);
    assert.ok(at < wipe,
      `${mode} must return before the Q&A thread is wiped — otherwise a fresh ${mode} ` +
      `silently discards an unrelated Q&A conversation`);
  }
});

test("every mode states its own placeholder", () => {
  const body = fn("setMode", 9000);
  for(const mode of ["panel","guided","startups","investors","deepdive","voices","triage"]){
    // match the BRANCH (`if(mode === "x"){`), not the mode-validation expression at the top
    const m = body.match(new RegExp(`(?:\\}\\s*else\\s*)?if\\(mode === "${mode}"\\)\\s*\\{`));
    assert.ok(m, `no branch for ${mode}`);
    const i = body.indexOf(m[0]);
    assert.match(body.slice(i, i + 620), /setAttribute\("placeholder"/,
      `${mode} must set a placeholder, or it inherits the mode the reader just left`);
  }
});

test("the Q&A placeholder is restated unconditionally", () => {
  // Guarding on an empty thread left the previous mode's example in the box when a thread was live.
  assert.ok(!/if\(!THREAD\.turns\.length\) q\.setAttribute\("placeholder"/.test(SRC),
    "the Q&A branch must always restate its own placeholder");
});

test("the console copy cannot come out empty", () => {
  // loadConfig ends in `catch(e){ /* config unavailable */ }`, which once swallowed a ReferenceError
  // and skipped every line after it — repeat visitors silently lost the vertical's placeholder, its
  // example questions and its disclaimers while a first visit looked perfect. The banner that caused
  // that has been removed, but the silent catch remains, so the fallback is what guarantees the
  // reader never faces a blank intake box.
  assert.match(SRC, /BASE_PLACEHOLDER = con\.placeholder \|\| "[^"]+"/,
    "BASE_PLACEHOLDER must fall back to a real string, never to empty");
  assert.match(SRC, /function pickPlaceholder\(\)\{[\s\S]{0,200}BASE_PLACEHOLDER/,
    "pickPlaceholder must fall back to it when the vertical ships no examples");
});

test("the shell carries no medical-vertical vocabulary", () => {
  // Standing directive: eigen is a tech vertical and the shell is domain-neutral. The intake box
  // shipped with "e.g. What treatments are being studied for type 2 diabetes?" as its placeholder.
  const hits = SRC.match(/\b(diabetes|clinical trial|patients?|europepmc)\b/gi) || [];
  assert.equal(hits.length, 0, `medical vocabulary in the app shell: ${hits.join(", ")}`);
});
