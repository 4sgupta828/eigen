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

test("Thesis Explorations is a dedicated full page behind a button, not a column that collides with the chat", () => {
  assert.match(MARKUP, /<div class="th-explore">/);
  assert.match(MARKUP, /<section class="th-rail"[^>]*id="th-rail"[^>]*role="dialog"/);
  assert.match(MARKUP, /Thesis Explorations/);
  assert.match(MARKUP, /id="th-rail-list"/);
  assert.match(MARKUP, /id="th-rail-toggle"/);                    // the button that opens the page
  assert.match(MARKUP, /id="th-rail-back"/);                      // ← Back closes it
  // the page is a full-screen overlay, hidden until opened — not a persistent column or a side drawer
  assert.match(SRC, /\.th-rail\{display:none;position:fixed;inset:0/);
  assert.match(SRC, /\.th-rail\.open\{display:block/);
  assert.match(SRC, /function setRail\(/);
  assert.match(MARKUP, /<div class="th-main">[\s\S]*id="th-takes"[\s\S]*id="th-thread"/);
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
  assert.match(html, /Type your thesis in the box above/);
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

test("genesis shows the UPDATED thesis every turn with a Use button — no form", () => {
  const {api} = loadThesisModule();
  // No thesis yet → nothing.
  assert.doesNotMatch(api.payloadHtml({ready: false, proposed_thesis: ""}), /th-landed|th-use|th-proposed/);
  // A working thesis mid-conversation → the live card + Use button (not gated on ready).
  const working = api.payloadHtml({ready: false, proposed_thesis: "Mid-market 3PLs will pay for X."});
  assert.match(working, /th-landed/);
  assert.match(working, /Working thesis/);
  assert.match(working, /id="th-use"/);
  assert.match(working, /Mid-market 3PLs will pay for X\./);
  // Ready → the same card, emphasised.
  const ready = api.payloadHtml({ready: true, proposed_thesis: "Mid-market 3PLs will pay for X."});
  assert.match(ready, /th-landed ready/);
  assert.match(ready, /The thesis I\u2019d test|The thesis I.d test/);
  assert.doesNotMatch(ready, /id="th-proposed"|textarea/);     // no editable form — the chat is the interface
});

test("the thesis card shows the agent's memory — open threads + assumptions", () => {
  const {api} = loadThesisModule();
  const html = api.payloadHtml({ready: false, proposed_thesis: "A thesis.",
    memory: {open_threads: ["specialist supply ceiling"], assumptions: ["CMS reimbursement holds"], resolved: []}});
  assert.match(html, /Still resolving/);
  assert.match(html, /specialist supply ceiling/);
  assert.match(html, /Assumptions it rests on/);
  assert.match(html, /CMS reimbursement holds/);
  // no memory → no panel
  assert.doesNotMatch(api.payloadHtml({ready: false, proposed_thesis: "A."}), /th-mem\b/);
});

test("the thesis card offers a redline of changes since the PREVIOUS turn, hidden by default", () => {
  const {api} = loadThesisModule();
  const prev = "Mid-market 3PLs will pay for route planning.";
  const curr = "Mid-market 3PLs (40-200 trucks) will pay for automated route planning.";
  const html = api.payloadHtml({ready: false, proposed_thesis: curr}, prev);
  assert.match(html, /th-landed-q th-clean/);              // the clean thesis is what shows by default
  assert.match(html, /th-redline-toggle/);                 // a toggle to reveal changes
  assert.match(html, /th-redline"[^>]*hidden/);            // the redline block is hidden by default
  assert.match(html, /changes since last turn/);           // labelled as since-last-turn, not since-beginning
  assert.match(html, /<ins>\(40-200/);                      // additions wrapped when revealed
  // no previous thesis → no redline block, no toggle
  const first = api.payloadHtml({ready: false, proposed_thesis: curr}, "");
  assert.doesNotMatch(first, /th-redline-toggle|<ins>|<del>/);
  assert.match(first, /th-landed-q th-clean/);
});

test("the landing offers a one-click 'generate a plausible thesis' button wired to /thesis/sample", () => {
  const {api} = loadThesisModule();
  const html = api.introHtml();
  assert.match(html, /id="th-sample"/);
  assert.match(html, /Generate a plausible thesis/);
  assert.match(SRC, /function sampleThesis\(/);
  assert.match(SRC, /\/thesis\/sample"/);
  assert.match(SRC, /await submit\(d\.thesis\)/);   // the generated thesis starts the genesis chat
});

test("genesis docks the composer (ChatGPT-style) once the conversation starts", () => {
  // draft + turns → body.chatting so the composer pins to the bottom and the thread scrolls above it
  assert.match(SRC, /const genesisChat = phase === "draft" && turns\.length > 0/);
  assert.match(SRC, /classList\.toggle\("chatting", genesisChat\)/);
  assert.match(SRC, /body\[data-mode="thesis"\]\.chatting \.th-main\{padding-bottom/);
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

test("an explicit run/re-run sends a fresh idempotency key so it is not deduped to the last run", () => {
  // the content-hash default on the server would make Re-run a no-op; the client forces a new run.
  assert.match(SRC, /idempotency_key:\s*freshRunKey\("q-" \+ qid\)/);      // single question
  assert.match(SRC, /idempotency_key:\s*freshRunKey\("inq-" \+ key\)/);    // line of inquiry
  assert.match(SRC, /function freshRunKey\(/);
});

test("The 'Who to ask' panel is gone; the per-line expert loop replaces it", () => {
  // The bottom aspect-scoped panel and its container/functions are removed.
  assert.doesNotMatch(SRC, /id="th-experts"/);
  assert.doesNotMatch(SRC, /async function loadExperts\(/);
  assert.doesNotMatch(SRC, /async function discoverExperts\(/);
  assert.doesNotMatch(SRC, /async function logCall\(/);
  // The ready/tested view now loads saved transcripts instead.
  assert.match(SRC, /id="th-loi"><\/div>/);
  assert.match(SRC, /loadTranscripts\(\);/);
});

test("Every line of inquiry offers 'Ask an expert' and 'Upload transcript'", () => {
  assert.match(SRC, /Ask an expert about this line/);
  assert.match(SRC, /Upload expert transcript/);
  assert.match(SRC, /data-ask="/);
  assert.match(SRC, /data-up="/);
  assert.match(SRC, /askExpert\(b\.dataset\.ask\)/);       // hand-off wired
  assert.match(SRC, /function askExpert\(/);
});

test("Ask-an-expert builds a people query from the line's subject + framing", () => {
  const {api} = loadThesisModule();
  api._setState({doc: {subject: {segment: "mid-market 3PLs"}}});
  const q = api.expertQueryFor({name: "Switching costs", framing: "How locked-in are buyers?"});
  assert.match(q, /mid-market 3PLs/);          // the subject
  assert.match(q, /Switching costs/);          // the line's name
  assert.match(q, /locked-in/);                // what it tests
  assert.equal(api.segmentOf({subject: {segment: "mid-market 3PLs"}}), "mid-market 3PLs");
});

test("The per-line transcript posts to the inquiry endpoint and consents", () => {
  assert.match(SRC, /\/inquiry\/" \+ encodeURIComponent\(inqKey\) \+ "\/transcript/);
  assert.match(SRC, /class="th-tx-transcript"/);
  assert.match(SRC, /async function uploadTranscript\(/);
  assert.match(SRC, /no NDA \/ internal recordings/);      // consent copy
  assert.match(SRC, /save_to_roster: true/);               // also saved to the roster
});

test("Insights render with a validates/invalidates/context stance and the expert URL", () => {
  const {api} = loadThesisModule();
  api._setState({transcripts: {inq1: [{
    id: "tx1", expert_name: "Dana Ops", expert_url: "https://linkedin.com/in/dana", firm: "Acme",
    tally: {validates: 1, invalidates: 1},
    insights: [{quote: "we would not switch lightly", insight: "high lock-in", stance: "validates", refers_to: "How locked-in?"},
               {quote: "pricing keeps climbing", insight: "price pressure", stance: "invalidates", refers_to: ""}]}]}});
  const html = api.insightsHtml("inq1");
  assert.match(html, /Dana Ops/);
  assert.match(html, /https:\/\/linkedin\.com\/in\/dana/);   // the expert URL is shown
  assert.match(html, /data-s="validates"/);
  assert.match(html, /data-s="invalidates"/);
  assert.match(html, /high lock-in/);
  assert.equal(api.insightsHtml("nope"), "");                 // no transcripts → nothing
});

test("Experts mode is first-class, with a saved roster and jump-in search", () => {
  assert.match(MARKUP, /id="expertsTab"[^>]*data-mode|id="expertsTab"/);
  assert.match(MARKUP, /<section id="expertsbody"/);
  assert.match(SRC, /window.EX = \{enter, search, reset, searchFor, loadRoster\}/);
  assert.match(SRC, /APP_MODE === "experts"/);          // submit + reset route to EX
  assert.match(SRC, /\/experts\/search"/);              // standalone endpoint, no thesis
  assert.match(SRC, /\/experts\/roster"/);              // the saved-expert map
  assert.match(SRC, /function searchFor\(/);            // the Ask-an-expert hand-off target
  assert.match(SRC, /exbtn = \$\("#expertsTab"\)/);      // shown by applyModeTabs
  assert.match(SRC, /mode === "experts" && THESIS_ENABLED/);  // gated + allowed in setMode
});

test("Experts mode has a precise filters panel (PDL) alongside the semantic box", () => {
  assert.match(SRC, /class="ex-filters"/);
  assert.match(SRC, /data-fx="' \+ k \+ '"/);          // inputs built from the FX list
  // the FX list names the PDL filter fields, including past-company
  assert.match(SRC, /\["title",/);
  assert.match(SRC, /\["seniority",/);
  assert.match(SRC, /\["past_company",/);
  assert.match(SRC, /\["skills",/);
  assert.match(SRC, /\["location",/);
  assert.match(SRC, /filters: filters/);              // filters are sent to the endpoint
  assert.match(SRC, /function readFilters\(/);
});

test("thesis intro offers 'Discover a published thesis to start from' → seeds genesis", () => {
  // the discovery search box + endpoint are wired into the thesis landing (not a separate mode)
  assert.match(SRC, /discover a published thesis to start from/i);
  assert.match(SRC, /id="th-disc-q"/);                 // the search input
  assert.match(SRC, /fetch\("\/discover\/theses"/);    // hits the discovery endpoint
  assert.match(SRC, /function discSeed\(/);            // builds a genesis seed from a result
  assert.match(SRC, /Start a thesis from this/);       // per-result CTA
  assert.match(SRC, /interpretation — not a fact/);    // honest register on every thesis card
});

test("the Collective Take renders a reasoning FLOW over the whole take, not a shallow verdict picture", () => {
  assert.match(SRC, /function takeReasoningFlow\(take, c\)/);   // builds from the take's own sections
  assert.match(SRC, /\+ takeReasoningFlow\(take, c\)/);         // wired into the take, next to the BLUF
  // section-driven stages (grounded + analysis) so the flow always fills, not just when analysis exists
  assert.match(SRC, /items\(\["at_stake"\]/);                  // stage: what must be true
  assert.match(SRC, /items\(\["by_line", "strengths"\]/);      // stage: what the evidence established
  assert.match(SRC, /items\(\["synthesis", "conviction"\]/);   // stage: what it implies
  assert.match(SRC, /items\(\["what_would_change"\]/);         // stage: what would change the read
  assert.match(SRC, /stages\.length < 2\)\{/);                 // thin-take fallback flows every section
  assert.match(SRC, /th-rf-bluf/);                             // the BLUF is the converging "read"
  assert.match(SRC, /not investment advice/);                  // honest: a reading, human owns the decision
});

test("genesis draft offers auto-improve + a backtrackable version timeline", () => {
  assert.match(SRC, /function improveThesis\(/);          // agent self-improves the thesis
  assert.match(SRC, /fetch\("\/thesis\/" \+ encodeURIComponent\(STATE\.id\) \+ "\/improve"/);
  assert.match(SRC, /function revertThesis\(/);           // backtrack to an earlier version
  assert.match(SRC, /"\/revert"/);
  assert.match(SRC, /function versionsHtml\(/);           // the version timeline
  assert.match(SRC, /Improve my thesis/);
  assert.match(SRC, /vs\.length < 2\) return ""/);        // no timeline until there's something to backtrack to
});

test("the LoI bar offers a critical-subset run and dedicated competitive research", () => {
  assert.match(SRC, /function runCriticalSubset\(/);
  assert.match(SRC, /\/inquiries\/run_critical/);
  assert.match(SRC, /function researchCompetitive\(/);
  assert.match(SRC, /\/competitive\/research/);
  assert.match(SRC, /Run the critical subset/);
  assert.match(SRC, /Research competitive landscape/);
});

test("the competitive artifact renders per-player cards + an at-a-glance table (not a passive matrix)", () => {
  assert.match(SRC, /function competitiveHtml\(comp\)/);
  assert.match(SRC, /th-comp-card/);                    // per-player cards
  assert.match(SRC, /At-a-glance comparison/);          // the compact summary table
  assert.match(SRC, /th-comp-src/);                     // each cell links its web source
  assert.match(SRC, /function legacyCompTable\(/);      // backward-compat with the old matrix shape
});
