// Run: node --test apps/web/tests/test_roles_link.mjs
//
// These pin the crash that blanked the startup surface: `crawl.pages` is a LIST of pages on one
// payload and a COUNT of them on another (the company detail returns `pages: 1`). `|| []` keeps a
// truthy 1, `(1).find` threw, and because cardHtml is mapped over every row, one such company
// emptied the ENTIRE result list — every startup search and every saved map rendered blank.
//
// No test runner and no npm install: the functions are pure, so they are lifted out of index.html
// and run as they ship. If the shipped code changes, these fail.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const fn = (name) => {
  const i = SRC.indexOf("function " + name + "(");
  if (i < 0) throw new Error("not found in index.html: " + name);
  // read to the matching close brace
  let depth = 0, j = SRC.indexOf("{", i);
  for (let k = j; k < SRC.length; k++) {
    if (SRC[k] === "{") depth++;
    else if (SRC[k] === "}" && --depth === 0) return SRC.slice(i, k + 1);
  }
  throw new Error("unbalanced: " + name);
};
const load = new Function(fn("boardUrlOf") + fn("boardRootOf") + fn("rolesLinkOf")
  + "return { rolesLinkOf, boardRootOf };");
const { rolesLinkOf } = load();

test("THE CRASH: a page COUNT where a page LIST was expected must not throw", () => {
  // the company-detail payload: {"crawl": {"pages": 1}}
  assert.doesNotThrow(() => rolesLinkOf({ pages: 1 }, null));
  assert.equal(rolesLinkOf({ pages: 1 }, null), "");
});

test("a real page list still finds the careers page", () => {
  const crawl = { pages: [{ kind: "about", url: "https://x.test/about" },
                          { kind: "careers", url: "https://x.test/careers" }] };
  assert.equal(rolesLinkOf(crawl, null), "https://x.test/careers");
});

test("no crawl at all is not an error", () => {
  assert.equal(rolesLinkOf(null, null), "");
  assert.equal(rolesLinkOf(undefined, undefined), "");
  assert.equal(rolesLinkOf({}, null), "");
});

test("a null entry inside the list does not throw", () => {
  assert.doesNotThrow(() => rolesLinkOf({ pages: [null, { kind: "careers", url: "https://x.test/c" }] }, null));
  assert.equal(rolesLinkOf({ pages: [null, { kind: "careers", url: "https://x.test/c" }] }, null), "https://x.test/c");
});

test("a string or an object where a list was expected is ignored, not iterated", () => {
  assert.equal(rolesLinkOf({ pages: "3" }, null), "");
  assert.equal(rolesLinkOf({ pages: { careers: "…" } }, null), "");
});

test("with no careers page it climbs back up from a single posting", () => {
  const r = rolesLinkOf({ pages: 1 }, { source_url: "https://boards.greenhouse.io/acme/jobs/12345" });
  assert.match(r, /greenhouse\.io\/acme/);
});
