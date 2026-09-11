// Run: node --test apps/web/tests/test_stale_build.mjs
//
// The page still stamps the build it was served with, but no longer nags about it. The banner
// ("A newer version is available — Reload") was removed at the owner's request: it interrupted the
// reader to report our deploy schedule, which is our problem, not theirs.
//
// The stamp itself stays. It is how anyone can tell which build a tab is running — type EIGEN_BUILD
// in the console — which is the diagnostic the banner was wrapped around, and the part that actually
// settles an "it's deployed" / "I don't see it" disagreement.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC = readFileSync(new URL("../index.html", import.meta.url), "utf8");

test("the page carries a build stamp the server fills in", () => {
  assert.match(SRC, /const BUILD = "__BUILD__"/);
});

test("the stamp is reachable from the console", () => {
  assert.match(SRC, /window\.EIGEN_BUILD = BUILD/,
    "without this there is no way to ask a tab which build it is running");
});

test("the placeholder is never written as a literal outside its one declaration", () => {
  // The server replaces EVERY occurrence when it stamps the build. A second literal is silently
  // rewritten into whatever the build is — which is how `BUILD === "__BUILD__"` once shipped as an
  // always-true test and the check never fired.
  const hits = SRC.match(/__BUILD__/g) || [];
  assert.equal(hits.length, 1, `the placeholder appears ${hits.length} times; only the declaration may use it`);
});

test("the nagging banner stays gone", () => {
  for(const dead of ["announceStaleBuild", "stalebuild", "A newer version of Eigen"]){
    assert.ok(!SRC.includes(dead), `"${dead}" is back`);
  }
});
