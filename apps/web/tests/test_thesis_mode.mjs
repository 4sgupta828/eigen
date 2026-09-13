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

test("conversation text is formatted into paragraphs, not a run-on blob", () => {
  const {api} = loadThesisModule();
  const html = api.fmtBody("First point about the buyer.\n\nSecond point, a different concern.");
  assert.match(html, /<p>First point about the buyer\.<\/p>/);
  assert.match(html, /<p>Second point, a different concern\.<\/p>/);
  // a single turn renders inside a formatted body block, escaped
  const turn = api.turnHtml("agent", "attacked", "The record says <b>otherwise</b>.");
  assert.match(turn, /class="th-body"/);
  assert.match(turn, /&lt;b&gt;otherwise&lt;\/b&gt;/);
  assert.doesNotMatch(turn, /<b>otherwise<\/b>/);
});

test("a payload rides with its turn rather than being dumped into a panel", () => {
  const {api} = loadThesisModule();
  const withPay = api.turnHtml("agent", "settled", "Done here.", "<div class=\"th-sides\">EV</div>");
  assert.ok(withPay.indexOf("th-body") < withPay.indexOf("th-sides"));
  assert.ok(withPay.trim().endsWith("</div>"));
});

test("an answer to a claim question renders inline on that claim", () => {
  const {api} = loadThesisModule();
  const claim = {rung: "buyer_nameable", claim: "A buyer owns this budget.", evidence: []};
  const html = api.claimHtml(claim, false, true, {buyer_nameable: "Procurement owns it, not ops."});
  assert.match(html, /class="th-answer"/);
  assert.match(html, /Procurement owns it, not ops\./);
  // no answer for a rung that was not asked
  const blank = api.claimHtml(claim, false, true, {});
  assert.doesNotMatch(blank, /class="th-answer"/);
});

test("the empty state explains the flow instead of showing an empty brief", () => {
  const {api} = loadThesisModule();
  const html = api.introHtml();
  assert.match(html, /Test a startup thesis/);
  assert.match(html, /lines of inquiry/);                          // the new model, not a claim ladder
  assert.doesNotMatch(html, /Fund \/ Pass \/ Continue/);           // retired claims-model framing is gone
  assert.match(html, /State it/);
  assert.match(html, /Type your thesis in the box below/);
});

test("the discussion thread is a visible surface, not folded into a collapsed details", () => {
  // the conversation container must live in an always-visible section, not a <details> summary
  assert.match(MARKUP, /<section class="th-thread"[^>]*id="th-thread"[\s\S]*?id="th-conv"/);
  assert.doesNotMatch(MARKUP, /<summary>Research conversation<\/summary>/);
});

test("phase is derived from the doc: draft → ready → tested", () => {
  const {api} = loadThesisModule();
  assert.equal(api.phaseOf(null), "empty");
  assert.equal(api.phaseOf({claims: []}), "draft");                       // no claims → still in genesis
  assert.equal(api.phaseOf({claims: [{rung: "problem_exists"}]}), "ready");
  assert.equal(api.phaseOf({claims: [{rung: "x"}], research_status: "completed"}), "tested");
});

test("genesis shows an editable proposed thesis with a Use button", () => {
  const {api} = loadThesisModule();
  const html = api.genesisHtml({proposed_thesis: "Mid-market firms will pay for X.",
                                turns: [{role: "agent", payload: {questions: ["Who buys it?"], ready: false}}]});
  assert.match(html, /id="th-proposed"/);
  assert.match(html, /Mid-market firms will pay for X\./);
  assert.match(html, /id="th-use"/);
  assert.match(html, /Who buys it\?/);            // the clarifying question is surfaced as a chip
});

test("the pre-test brief shows the thesis, not an empty 'Ready to test' decision", () => {
  const {api} = loadThesisModule();
  const html = api.pretestHtml({thesis: "A concrete thesis.", is_owner: true,
                                claims: [{rung: "a", critical: true}, {rung: "b"}]});
  assert.match(html, /A concrete thesis\./);
  assert.match(html, /lines of inquiry/);                          // the new model framing
  assert.doesNotMatch(html, /claims,.*critical/);                  // no retired claims count
  assert.doesNotMatch(html, /Fund \/ Pass \/ Continue/);
  assert.doesNotMatch(html, /Ready to test/);
});

test("the follow-up context selector defaults to the decisive and critical claims", () => {
  const {api} = loadThesisModule();
  const html = api.contextHtml({
    decision: {decisive_claims: ["buyer_nameable"]},
    claims: [{rung: "buyer_nameable", critical: true}, {rung: "problem_exists", critical: false},
             {rung: "catalyst", critical: true}]});
  // decisive + critical are pre-pressed; a non-critical, non-decisive claim is not
  assert.match(html, /data-rung="buyer_nameable" aria-pressed="true"/);
  assert.match(html, /data-rung="catalyst" aria-pressed="true"/);
  assert.match(html, /data-rung="problem_exists" aria-pressed="false"/);
});

test("no partial: the testing progress carries no verdict, case, or recommendation", () => {
  // the testing surface is progress-only — asserted structurally on the CSS/markup contract
  assert.match(SRC, /class="th-testing"/);
  assert.match(SRC, /Testing this thesis against the evidence/);
  // the render() switches to renderTesting() in the testing phase and returns before takesHtml
  assert.match(SRC, /if\(phase === "testing"\)\{\s*renderTesting\(\);/);
});

test("a line of inquiry renders its questions with typed lens glyphs", () => {
  const {api} = loadThesisModule();
  api._setState({doc: {is_owner: true, claims: []}});
  const inq = {key: "buyer", name: "Who owns the budget to buy this?", framing: "the economic buyer",
    aspects: [{key: "buyer_nameable", prompt: "Can an economic buyer be named?", critical: true, verdict: "open"}],
    questions: [
      {id: "q1", aspect_key: "buyer_nameable", kind: "seek_support", text: "Is a buyer named in filings?", target: "t", polarity: 1, target_status: ""},
      {id: "q2", aspect_key: "buyer_nameable", kind: "seek_contradiction", text: "Do deals close without a named buyer?", target: "t", polarity: -1, target_status: ""},
    ]};
  const html = api.inqHtml(inq);
  assert.match(html, /Who owns the budget to buy this\?/);        // the inquiry name is the serif hero
  assert.match(html, /seeks support/);                            // the two lenses are labeled
  assert.match(html, /seeks disconfirmation/);
  assert.match(html, /data-run="buyer"/);                         // an unrun inquiry offers to run
  // lens is colour-coded: each question card + its chip carry data-lens, and the chip shows the glyph
  assert.match(html, /class="th-qn"[^>]*data-lens="seek_support"/);
  assert.match(html, /class="th-lens" data-lens="seek_contradiction"><span class="th-lens-g"/);
  assert.match(html, /⊕/);                                        // the support glyph renders
  // the aspect verdict renders as a badge (data-v), always present so status reads at a glance
  assert.match(html, /class="th-aspect-v" data-v="open"/);
});

test("an answered question shows a grounded answer with footnotes and an evidence list", () => {
  const {api} = loadThesisModule();
  api._setState({doc: {is_owner: true, claims: [{rung: "buyer_nameable",
    evidence: [{id: "ev1", quote: "Acme named as buyer in a case study", register: "stated",
                source_url: "https://x.test"}]}]}});
  const q = {id: "q1", aspect_key: "buyer_nameable", kind: "seek_support",
    text: "Is a buyer named?", target: "t", polarity: 1, target_status: "target_supported",
    evidence_ids: ["ev1"], answer: "A case study names the buyer. [[e:ev1]]"};
  const html = api.qnHtml(q, false, {});
  assert.match(html, /A case study names the buyer\./);
  assert.match(html, /<sup class="ref" data-n="1"/);              // inline footnote marker
  assert.match(html, /id="f1"/);                                  // numbered evidence item it points to
  assert.match(html, /Acme named as buyer in a case study/);     // the quote is shown, always visible
});

test("the four lenses are named for a 360-degree read, not decoration", () => {
  const {api} = loadThesisModule();
  assert.deepEqual(Object.keys(api.LENS).sort(),
    ["challenge_assumption", "resolve_ambiguity", "seek_contradiction", "seek_support"]);
});

test("during a run, the active question shows a spinner and the rest are queued", () => {
  const {api} = loadThesisModule();
  api._setState({doc: {is_owner: true, claims: []},
    inqRun: {key: "problem", run: "r1", done: 1, total: 3}});
  const inq = {key: "problem", name: "Is the problem real?", framing: "the pain",
    aspects: [{key: "problem_exists", prompt: "Does it occur?", critical: true, verdict: "supported"}],
    questions: [
      {id: "q1", aspect_key: "problem_exists", kind: "seek_support", text: "Answered one?", target: "t", polarity: 1,
       target_status: "target_supported", answer: "Yes. [[e:e1]]"},
      {id: "q2", aspect_key: "problem_exists", kind: "seek_contradiction", text: "The one being worked?", target: "t", polarity: -1, target_status: ""},
      {id: "q3", aspect_key: "problem_exists", kind: "resolve_ambiguity", text: "Still queued?", target: "t", polarity: 1, target_status: ""},
    ]};
  const html = api.inqHtml(inq);
  assert.match(html, /Researching 2 of 3 — .*The one being worked\?/);   // names the active question
  assert.match(html, /researching this question…/);                       // spinner line on the active one
  assert.match(html, /queued/);                                           // the later question waits
  // the answered question shows its grounded answer inline (no double collapse)
  assert.match(html, /class="th-answer-body"/);
});

test("each question can be run on its own — Run when unrun, Re-run when answered", () => {
  const {api} = loadThesisModule();
  api._setState({doc: {is_owner: true, claims: []}, inqRun: null});
  const unrun = {id: "q1", aspect_key: "a", kind: "seek_support", text: "?", target: "t", polarity: 1, target_status: ""};
  const answered = {id: "q2", aspect_key: "a", kind: "seek_support", text: "?", target: "t", polarity: 1,
    target_status: "target_supported", answer: "Yes."};
  const uh = api.qnHtml(unrun, true, {});
  const ah = api.qnHtml(answered, true, {});
  assert.match(uh, /data-qrun="q1"/);
  assert.match(uh, /Run this question/);
  assert.match(ah, /data-qrun="q2"/);
  assert.match(ah, /Re-run this question/);
  // while a run is in flight, no per-question run button is offered
  const running = api.qnHtml(unrun, true, {running: true, activeQid: "other"});
  assert.doesNotMatch(running, /data-qrun/);
});

test("a line with drafted questions can be deleted; an all-answered line cannot", () => {
  const {api} = loadThesisModule();
  api._setState({doc: {is_owner: true, claims: []}, inqRun: null});
  const drafted = {key: "buyer", name: "Who owns the budget?", framing: "the buyer",
    aspects: [{key: "b", prompt: "Buyer?", verdict: "open"}],
    questions: [{id: "q1", aspect_key: "b", kind: "seek_support", text: "?", target: "t", polarity: 1, target_status: ""}]};
  assert.match(api.inqHtml(drafted), /data-del="buyer"/);          // drafted line offers delete
  const answered = {key: "market", name: "Enough buyers?", framing: "size",
    aspects: [{key: "m", prompt: "Size?", verdict: "supported"}],
    questions: [{id: "q9", aspect_key: "m", kind: "seek_support", text: "?", target: "t", polarity: 1,
                 target_status: "target_supported", answer: "Yes."}]};
  assert.doesNotMatch(api.inqHtml(answered), /data-del=/);         // paid work isn't offered for deletion
});

test("delete controls call the line and clear-all endpoints and preserve answered work", () => {
  // start-fresh: clear-all and per-line delete hit DELETE endpoints; both keep answered questions.
  assert.match(SRC, /DELETE[\s\S]*?\/inquiries"/);                 // clear-all endpoint
  assert.match(SRC, /\/inquiry\/" \+ encodeURIComponent\(key\)[\s\S]*?method: "DELETE"/);  // per-line
  assert.match(SRC, /Clear all &amp; start fresh/);                // the start-fresh control
  assert.match(SRC, /Answered questions are kept/);                // the reassurance in the confirm
});
