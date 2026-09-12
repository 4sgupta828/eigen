import { test } from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { readFileSync } from "node:fs";

const SRC = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const MARKUP = SRC.replace(/<script[\s\S]*?<\/script>/g, "");

function loadThesisModule(){
  const marker = "// TestStartupThesis —";
  const at = SRC.lastIndexOf(marker);
  const start = SRC.indexOf("(function(){", at);
  const end = SRC.indexOf("})();", start) + 5;
  assert.ok(at > 0 && start > at && end > start, "thesis module not found");
  const storage = new Map();
  const context = {
    window: {USER: null}, USER: null,
    document: {getElementById: () => null, addEventListener: () => {}},
    location: {origin: "https://eigen.test", hash: "#thesis"},
    history: {replaceState: (_a, _b, hash) => { context.location.hash = hash; }},
    navigator: {clipboard: {writeText: async () => {}}},
    localStorage: {getItem: k => storage.get(k) || null,
                   setItem: (k, v) => storage.set(k, String(v))},
    CSS: {escape: x => String(x)},
    esc: x => String(x).replaceAll("&", "&amp;").replaceAll("<", "&lt;")
                         .replaceAll(">", "&gt;").replaceAll('"', "&quot;"),
    fetch: async () => { throw new Error("unexpected fetch"); },
    setTimeout, console, URLSearchParams,
  };
  vm.runInNewContext(SRC.slice(start, end), context);
  return {api: context.window.TH.__test, context, storage};
}

test("owner capability is sent in a header and never encoded into a URL", () => {
  const {api} = loadThesisModule();
  const headers = api.ownerHeaders("t1", {t1: "owner-secret"}, null);

  assert.equal(headers["X-Thesis-Owner"], "owner-secret");
  assert.doesNotMatch(api.thesisUrl("t1", "share-only"), /owner-secret/);
  assert.equal(api.thesisUrl("t1", "share-only"),
               "https://eigen.test/app#thesis/t1?share=share-only");
});

test("shared hash is parsed separately from the thesis id", () => {
  const {api} = loadThesisModule();

  assert.deepEqual({...api.parseThesisHash("#thesis/t1?share=read-cap")},
                   {id: "t1", share: "read-cap"});
  assert.deepEqual({...api.parseThesisHash("#thesis/t1")}, {id: "t1", share: ""});
});

test("shared thesis is read-only while an owner thesis can mutate", () => {
  const {api} = loadThesisModule();

  assert.equal(api.canMutate({is_owner: false}), false);
  assert.equal(api.canMutate({is_owner: true}), true);
});

test("decision brief leads with recommendation and unresolved critical claims", () => {
  const {api} = loadThesisModule();
  const html = api.decisionHtml({
    decision: {recommendation: "continue_diligence", reason: "Critical evidence is incomplete.",
               decisive_claims: ["buyer_nameable"]},
    claims: [{rung: "buyer_nameable", claim: "A buyer owns this.", critical: true,
              research_status: "under_tested", evidence: []}],
  });

  assert.ok(html.indexOf("Continue diligence") < html.indexOf("A buyer owns this."));
  assert.match(html, /Unresolved cruxes/);
  assert.match(html, /Critical evidence is incomplete/);
});

test("empty brief asks for a thesis instead of claiming diligence is complete", () => {
  const {api} = loadThesisModule();
  const html = api.decisionHtml({is_owner: true, claims: []});

  assert.match(html, /State a thesis to identify what evidence would change the decision/);
  assert.doesNotMatch(html, /critical evidence is complete/i);
});

test("case citation resolves by immutable evidence id", () => {
  const {api} = loadThesisModule();
  const evidence = [{id: "ev-stable", quote: "Exact source span."}];

  const linked = api.linkEvidence("Result [[e:ev-stable]].", evidence);
  const missing = api.linkEvidence("Invented [[e:not-here]].", evidence);

  assert.match(linked, /data-evidence="ev-stable"/);
  assert.doesNotMatch(missing, /not-here/);
});

test("new thesis reset target drops the old id and share token", () => {
  const {api} = loadThesisModule();
  assert.equal(api.newThesisHash(), "#thesis");
});

test("thesis status and errors are live regions", () => {
  assert.match(MARKUP, /id="th-progress"[^>]*role="status"[^>]*aria-live="polite"/);
  assert.match(MARKUP, /id="th-note"[^>]*role="alert"[^>]*aria-live="assertive"/);
});

test("phone layout has touch targets and a single-column decision brief", () => {
  assert.match(SRC, /@media \(max-width:560px\)[\s\S]*?\.th-decision-grid\{grid-template-columns:1fr/);
  assert.match(SRC, /\.th-acts button[^}]*min-height:44px/);
  assert.match(SRC, /\.th-ask-row button[^}]*min-height:44px/);
  assert.match(SRC, /prefers-reduced-motion:reduce/);
});

test("recent theses have a dedicated visible panel", () => {
  assert.match(MARKUP, /id="th-recents"/);
});
