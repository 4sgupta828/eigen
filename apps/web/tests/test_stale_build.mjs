// Run: node --test apps/web/tests/test_stale_build.mjs
//
// A tab open across a deploy runs the JavaScript it started with. The server sends no-store, so a reload
// always gets the new page — but an SPA never reloads itself, and nothing on screen said so. That cost a
// real round of "it's deployed" / "I don't see it", with both statements true.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC = readFileSync(new URL("../index.html", import.meta.url), "utf8");

test("the page carries a build stamp the server fills in", () => {
  assert.match(SRC, /const BUILD = "__BUILD__"/);
});

test("it compares its own build against the server's", () => {
  const i = SRC.indexOf("function announceStaleBuild");
  assert.ok(i > 0, "no staleness check");
  const body = SRC.slice(i, i + 700);
  assert.match(body, /serverBuild === BUILD/, "must compare, not just read");
  assert.match(body, /location\.reload/, "must offer the one action that fixes it");
});

test("the check runs on the config the app already fetches", () => {
  assert.match(SRC, /announceStaleBuild\(c\.build\)/, "no extra request should be needed");
});

test("an unstamped page (local dev) says nothing", () => {
  const i = SRC.indexOf("function announceStaleBuild");
  assert.match(SRC.slice(i, i + 400), /BUILD === "__BUILD__"/,
    "local dev serves the literal placeholder and must not nag");
});
