x# Design: Test Thesis — Threads, Questions, Answered with Citations

**Date:** 2026-09-12
**Status:** Draft for panel review (no code yet)
**Feature:** `apps/api/thesis/` + `apps/web/index.html` (thesis mode). Builds on the decision-agent flow
just shipped (genesis → async test → follow-up), replacing only the RESULT SURFACE.
**Inspiration:** `~/factra`'s thread/question/finding model (`rs_thread` = a workstream with
`questions[]`; `rs_finding.answers_question` + `rs_question_synthesis` = a grounded answer to a
question, with citations, grouped as "Q → answer").

---

## 1. Intent

Today a tested thesis renders as a **decision brief with a two-column "Case for / Case against"
table** (`decisionHtml`, `index.html:11515`; `argue.cases_for` writes `case_for`/`case_against` per
rung). Two problems: the for/against split flattens ten claims into two prose blobs, and it reads as an
argument to win rather than a decision to inform.

Move to factra's shape: **a set of THREAD cards**, each a focused area of the thesis test; opening a
thread lists its **questions**, and **each question carries a grounded ANSWER built from the corpus and
the web, with citations**. The threads together give coverage of the thesis test. The reader sees "what
did we ask, and what did the evidence say," not "here is the case for and the case against."

The grounding discipline is unchanged and is the whole point: an answer states only what congruent,
cited evidence supports; sentiment stays a labeled signal; a question with no qualified evidence is
answered "not established," never guessed.

## 2. Contract

### User-visible behavior (tested phase)

- The result is a **top-line recommendation** (Fund / Pass / Continue diligence — unchanged, from the
  deterministic policy) followed by a **grid of thread cards**. No for/against table.
- Each **thread card** shows: the thread's name, a one-line framing, and a compact status — how many of
  its questions are answered / supported / contradicted / still open (verdict pips, as the ledger has).
- **Opening a thread** (expand in place, or a detail view) lists its **questions**. Each question shows:
  its **answer** — one to three sentences of grounded prose — with **inline citations** to the evidence
  (source + register: filed / stated / signal), and the question's **verdict** (supported /
  contradicted / under-tested / needs-a-person / not-established).
- The evidence quotes stay reachable (a citation expands to the exact span + source, as today) but are
  no longer the primary surface — the answer is.
- The **follow-up agent** (just shipped) is unchanged: pick claims/questions, ask, it explains
  read-only. The claim selector maps naturally onto thread questions.

### Success criteria

- A tested thesis renders as thread cards → questions → answers-with-citations; the for/against grid is
  gone from the UI and `case_for`/`case_against` are no longer the render source.
- Every answer sentence is backed by a cited piece of evidence on that question; an answer that cannot
  bind congruent evidence reads "Not established in the record" (fail-safe), never a guess.
- Threads give full coverage: every ladder rung appears in exactly one thread; no rung is orphaned.
- Sentiment-derived evidence never produces a "supported" answer on its own (authority discipline
  unchanged); an answer built only on signal is labeled a market signal.

### Invariants (unchanged from the shipped feature)

- The fixed ladder is the coverage guarantee and is **not the model's to edit** (`schema.py`). Threads
  are a fixed GROUPING of the ladder, so coverage cannot regress by free generation.
- The recommendation still comes only from the deterministic `thesis_policy.decide` over verdicts.
- Evidence stays typed; the span-check + congruence + authority gates are untouched — the answer
  synthesis reads only already-gated evidence and cannot introduce a source.
- Human owns the decision; the answer synthesis is generated, cited, and grounding-gated, never a
  verdict.

## 3. Architecture

### 3.A Threads = a fixed grouping of the ladder (coverage-safe)

Add a small static map in `schema.py` (vertical vocabulary, already tech-specific there): each rung
belongs to exactly one thread. Proposed grouping (name → rungs):

- **"Is the problem real, and does it cost?"** — `problem_exists`, `status_quo_costs`, `already_spending`
- **"Who owns the budget to buy this?"** — `function_owns`, `budget_category`, `buyer_nameable`,
  `willingness_to_pay`
- **"Can they switch, and why now?"** — `switching_feasible`, `catalyst`
- **"Are there enough buyers?"** — `enough_buyers`

A thread's **questions are the (instantiated) rung questions** it contains — `decompose` already writes
the concrete claim per rung, and `schema.QUESTION` holds the canonical question. So each thread question
= one rung, carrying its claim, its evidence, its verdict, and (new) its answer. **No dynamically
generated questions in v1** — the ladder is the coverage contract; free question generation is the
exact thing that could miss a rung or drift off-thesis (deferred to §7).

Rationale over one-card-per-rung (10 cards) or fully dynamic threads (factra-style): grouping keeps a
legible handful of cards AND keeps the ladder's guaranteed coverage. This is the main decision for the
panel (§8.1).

### 3.B Answering a question with citations (replaces case_for/case_against)

Keep the whole evidence-gathering pipeline unchanged: the async runner already calls `attack_claim` per
rung (corpus FOR + red-team AGAINST over the web where the corpus is silent), producing gated evidence
with `run_id`, register, subject, kind, period, and the verdict.

Replace `argue.cases_for` (per-rung `case_for`/`case_against`) with `argue.answer_questions`: one call
over the whole thesis that writes, per rung, **one grounded ANSWER** to that rung's question — 1–3
sentences saying what the evidence establishes, with immutable `[[e:<id>]]` citations (the same stable
marker the cases already use, `linkEvidence` at `index.html`) and honest register ("A 10-K states…",
"coverage suggests…"). The answer is bound to the SAME allowed-evidence-id set and sanitized the same
way (`sanitize_case` → `sanitize_answer`): a sentence citing an id not on the claim's evidence is
dropped; an answer with nothing to cite becomes "Not established in the record." The `overall` reading
stays (it's the decision rationale). One call for the whole thesis, after evidence — same cost shape.

New per-rung field: `ts_claim.answer text` (+ the answer reuses `ts_evidence` for its citations). Retire
`case_for`/`case_against` from the render (columns stay in the DB, unused, additive-safe).

### 3.C UI — thread cards → questions → answers

Replace `decisionHtml`'s for/against grid with:
- The recommendation header (unchanged).
- A **thread-card grid** (`threadsHtml`): one card per thread, name + framing + verdict pips over its
  questions + "N of M answered." Cards are keyboard-focusable; on a phone they stack (existing 560px
  pass).
- **Expanding a card** (a `<details>` or an in-place expand) lists its questions; each question renders
  the claim, its verdict chip, and its **answer with inline citations** (reusing `linkEvidence` +
  the citation-expand-to-evidence interaction already wired in `wireTakes`). "Unresolved cruxes" and
  "What would change this" stay as a small summary under the cards (they are decision-grade and cheap).
- The ledger ("Claims and evidence") stays as the raw drill-down; the thread view is the primary read.
- The follow-up context selector's chips become **grouped by thread** (a small change to `contextHtml`).

## 4. Data model (additive)

- `ts_claim`: `+ answer text NOT NULL DEFAULT ''` (the grounded answer to the rung's question). Reuses
  `ts_evidence` for citations. `case_for`/`case_against` remain (unused by the new render).
- `schema.py`: a static `THREADS: tuple[(name, framing, (rungs…))]` grouping — vertical vocabulary,
  code-owned, not a table.
- No new tables; the answer is per-claim, threads are derived from the static grouping.
- API: the tested-thesis payload already returns claims with evidence + verdict; add `answer` (free via
  `SELECT *`), and a small `threads` shaping (server-side helper or client-side grouping from the static
  map shipped via `/thesis/labels`).

## 5. Reuse vs net-new

- **Reuse:** the whole async runner + `attack_claim` + gates + `run_id` idempotency; the ladder; the
  stable `[[e:<id>]]` citation markers + `linkEvidence` + citation→evidence expand; `thesis_policy`;
  the decision header; the follow-up agent; the 560px responsive pass.
- **Net-new (small):** `argue.answer_questions` (replaces `cases_for`); `sanitize_answer`;
  `ts_claim.answer`; the `THREADS` static grouping + label plumbing; `threadsHtml` + thread expand +
  thread-grouped `contextHtml` (replaces the for/against grid in `decisionHtml`).
- **Removed from the render:** the "Case for / Case against" two-column grid.
- **Deferred (§7):** dynamically generated sub-questions per thread (factra-style); per-thread source
  policies; a thread as its own detail route.

## 6. Verification (free-first)

- **Coverage (deterministic):** a test that the `THREADS` grouping partitions the ladder exactly — every
  rung in exactly one thread, no rung missing, no unknown rung.
- **Answer grounding (deterministic):** `sanitize_answer` drops a sentence citing an id not on the
  claim; an answer with no citable evidence becomes "Not established in the record."
- **Render (web):** a tested doc renders thread cards, each expandable to questions-with-answers; the
  for/against grid is absent; a citation still resolves to its evidence.
- **No regression:** the async runner, follow-up read-only integrity test, and genesis gate tests stay
  green; kernel guardrails green.
- **One gated real-LLM smoke** (projected + approved), only after the free suite: a tested thesis
  produces per-question answers that cite real evidence and refuse where the record is silent.

## 7. Phasing

- **Phase 1 (this spec):** static thread grouping; per-question grounded answers with citations
  (`answer_questions` + `sanitize_answer` + `ts_claim.answer`); the thread-card UI replacing the
  for/against grid; the coverage + grounding + render tests.
- **Phase 2 (deferred):** LLM-generated sub-questions per thread (with a coverage gate so a rung is
  never dropped); per-thread source curation; thread detail routes.

## 8. Open questions / risks (for the panel)

1. **Threads = fixed grouping of the ladder (my proposal) vs one-card-per-rung vs factra-style dynamic
   threads.** Fixed grouping keeps guaranteed coverage + a legible ~4 cards; dynamic threads read more
   like factra but risk missing a rung or drifting off-thesis. Is the fixed grouping the right call for
   a coverage-critical stress test, or does the owner want dynamically-constructed threads (with a
   coverage gate)?
2. **Keep the Fund/Pass/Continue header?** Proposed: yes, as the top line over the cards — the decision
   is still the point; threads are how it was tested. Confirm the owner doesn't want the recommendation
   demoted.
3. **Answer vs raw evidence as the primary surface.** The answer is a generated (grounded, gated)
   synthesis. Is a per-question one-liner the right density, or should the card show the top cited quote
   verbatim first (less synthesis, more raw record)?
4. **Cost/latency:** answering is still one `argue`-shaped call over the whole thesis (same as
   `cases_for`), so no new spend. Confirm we do not want per-question separate calls (10× cost).
5. **Sentiment answers:** an answer built only on `signal` evidence must be labeled a market signal and
   can never read "supported." The synthesis prompt + the existing authority gate enforce this — worth a
   held-out eval case (sentiment-as-fact) per the standing directive.

---

## 9. Panel review (2026-09-12)

Codex (gpt-5.1), Gemini 3 Pro, and a code-grounded subagent (verified every file:line premise). This
round all three landed. Relayed honestly.

**Code-grounded subagent — all premises TRUE.** `cases_for` shape, the ladder + `QUESTION`, the
for/against grid source (`decisionHtml` at `index.html:11505`, forCases/againstCases at 11515–11516,
grid at 11528), `linkEvidence` + `sanitize_case`, `attack_claim`'s returned keys, `ts_claim` has
case_for/case_against but no `answer`, the runner calls `_write_cases`→`cases_for` at `routes.py:511`,
and the citation→evidence wiring in `wireTakes` (11560). Nits: `decisionHtml` is at 11505 not 11515;
`answer_questions` slots into `_write_cases`.

**Both external CLIs agree on the two load-bearing points:**
1. **Fixed grouping of the ladder is the right call** for a coverage-critical stress test (dynamic
   threads risk dropping a rung / drifting off-thesis). Requires a deterministic partition test.
2. **The real risk is losing the adversarial framing** — disconfirmation is the whole point. Adopted
   mitigations (both): keep the verdict chip prominent; the `answer_questions` prompt must LEAD with
   contradictory evidence when it exists and state "we looked and found none" for a supported-but-
   attacked claim, never blend into a middle-ground summary. Codex adds a machine-derived per-question
   **counts row** (supporting / contradictory / signal, from the existing `attack_claim` `counts`) and
   an "attack attempted" indicator, and keeping `case_for`/`case_against` as an optional drill-down.

**Gemini's sharp catch on grounding (adopted):** the `sanitize_case` **sentence splitter is fragile** —
(a) a false clause ending in a valid citation escapes the gate ("100% market share [[e:valid]]"), and
(b) the `(?<=[.!?])\s+` regex splits on "Inc." / "Ltd." (the exact splitter trap the DeepDive work
already hit). **Fix: `answer_questions` returns a JSON ARRAY of discrete sentences**, each `{text,
evidence_ids}`; `sanitize_answer` validates each item's ids ⊆ the claim's allowed set and drops a
factual item with an invalid or missing id — gating the LLM's own sentence units, bypassing the regex
splitter entirely and tightening intra-sentence grounding.

**Spec corrections (minor, both reviewers):** "attack_claim produces evidence with run_id" — run_id is
stamped by the runner/store, not `attack_claim`; "cases_for writes …" — it returns, `store.set_cases`
writes; "a citation expands to the exact span" — it scrolls to the ledger row + a title tooltip, not an
inline expand.

**Synthesized call — proceed, with three strengthenings folded in:**
- **Threads = static grouping** of the ladder, guarded by a deterministic partition test (§6).
- **Disconfirmation stays first-class**: per-question verdict chip + a counts row + an answer that names
  contradictory evidence first; `case_for`/`case_against` kept as a drill-down toggle, not deleted. The
  UI drops the two-column *table*, not the adversarial content.
- **`answer_questions` emits a sentence array** `[{text, evidence_ids}]`; `sanitize_answer` gates each
  item (ids ⊆ allowed, factual item must cite) — no regex sentence-splitting. A deterministic test
  mirrors `test_case_model_output_is_validated_against_claim_evidence`, plus a web test that only valid
  markers become clickable sources. Free-first; the real-LLM smoke stays gated.

---

## 10. Revision — the Socratic question framework (owner direction, 2026-09-12)

This supersedes §3.B's "one grounded answer per rung" and the panel's "make the answer lead with
disconfirmation." The panel was right that a single answer risks bias; the owner's fix is deeper: **do
not remove bias in the answer — remove it in the QUESTIONS.** Neutrality is a property of asking a
balanced, 360° set; the answer is then just "what evidence exists."

### The model

- **Thread = a group of related aspects** of the thesis (anchored to the fixed ladder so coverage
  cannot regress — the ladder rungs are the aspects; threads group them, as in §3.A).
- **Questions are the Socratic instrument.** Per aspect, generate a set of questions that explore it in
  a 360° manner, each TYPED by intent:
  - `seek_support` — is there evidence that the aspect holds?
  - `seek_contradiction` — is there evidence against it? (the red-team lens)
  - `resolve_ambiguity` — where the thesis could go two ways, which does the record show?
  - `challenge_assumption` — name a hidden premise the aspect rests on and test it.
  The balance ACROSS these kinds is what makes the inquiry unbiased — not a hedged answer. **Rule 18:
  the model owns the Socratic wording; CODE owns the coverage gate** — each aspect must yield the
  required kinds (at least `seek_support` + `seek_contradiction`; `resolve_ambiguity` /
  `challenge_assumption` where the aspect warrants), or the aspect is under-covered and re-asked. The
  aspect set stays fixed (the ladder), so no aspect is dropped; only the wording is generated.
- **Answering is evidence lookup, not argument.** Each question runs corpus+web (the existing
  `attack_claim` retrieval + gates). The answer states, with `[[e:<id>]]` citations, ONLY what
  qualified evidence was found: for a `seek_support`/`seek_contradiction` question, either "the record
  shows X [cite]" or **"no qualified evidence found."** Finding is support or disconfirmation *by the
  question's framing* — we do not editorialize. The sentence-array + `sanitize_answer` gate (§9) still
  applies per question.
- **Verdict is derived, deterministic** (code, not the model): aggregate the balanced set —
  `seek_support` satisfied AND `seek_contradiction` empty ⇒ supported; a `seek_contradiction` that
  found qualified evidence ⇒ contradicted; a broken `challenge_assumption` ⇒ weakened/contradicted; an
  unresolved `resolve_ambiguity` or nothing found ⇒ under-tested / not established. This keeps judgment
  out of the prose and in the policy, and preserves "sentiment can never be controlling."

### What changes vs §3

- Question generation becomes a real step (Socratic, typed, coverage-gated) between decompose and the
  evidence run — one `llm_json` call per aspect or one batched call, budget-capped, fail-open to the
  canonical rung question when the model is absent.
- Data model grows a **`ts_question`** row set (thesis_id, aspect/rung, kind, text, order, answer,
  found_verdict), with evidence linked to the question it answers (add `question_id` to `ts_evidence`,
  or keep evidence per-aspect and tag by question). The claim/aspect verdict is derived from its
  questions.
- UI: a thread card opens to its aspects → each aspect shows its typed questions, each with its
  evidence-found answer + citations + a tiny kind tag (⊕ seeks support, ⊖ seeks contradiction, ⟲
  resolves ambiguity, ⚑ challenges assumption). The reader sees a 360° interrogation, not a two-sided
  table.

### Open questions this raises (for a focused re-panel)

- **Cost**: N aspects × K typed questions × (retrieval + a relation judgment) is more calls than the
  current one-attack-per-rung. Needs a projection + cap and probably a per-aspect question ceiling
  (e.g. ≤4). Batching the generation and reusing one retrieval across a support/contradiction pair may
  be needed.
- **Coverage gate shape**: which kinds are REQUIRED per aspect vs optional, and how the re-ask works
  without unbounded spend.
- **Verdict aggregation rules**: the exact deterministic mapping from the found-set to
  supported/contradicted/under-tested — this is the new load-bearing policy and deserves the panel's eye
  and a held-out eval (a `seek_support` that finds sentiment-only evidence must NOT read supported).

---

## 11. Naming (owner decision, 2026-09-12)

The card abstraction is a **"Line of inquiry"** (shortened to **"Inquiry"** on cards) — NOT "thread"
(that is factra's term, and a weaker abstraction). A line of inquiry is a focused facet of the thesis,
interrogated 360° by a balanced set of typed Socratic questions. Throughout the implementation: the
grouping is `INQUIRIES` (not `THREADS`), a card is an inquiry, and the model surfaces read "Lines of
inquiry." The kernel/vertical split is unchanged — this vocabulary lives in the tech vertical / app
layer, never the kernel.

---

## 12. Curated, per-inquiry kickoff (owner direction, 2026-09-12)

Supersedes the "one explicit Test this thesis runs everything at once" model for the tested phase.
Exploration is expensive and the user owns it, so:

- **Nothing runs automatically.** After decompose + question generation (§10), the user is shown the
  lines of inquiry with their Socratic questions, and NOTHING is explored yet.
- **The user curates the questions first.** Per line of inquiry, they can **edit** a question's wording,
  **add** a question, or **remove** one — before any spend. (`ts_question` is mutable while unrun.)
- **The user kicks off inquiries one at a time.** They select a line of inquiry (or a subset of its
  questions) and run THAT one; the cost is projected and approved **per kickoff**. There is no
  "run all." A line of inquiry that the user never runs is never explored.
- **Each inquiry run is its own async job, no partial WITHIN it** — the §3.B/async-runner machinery,
  but scoped to one inquiry (its questions), with its own progress + resume. The "no half-painted
  result" guarantee holds per inquiry: an inquiry's answers appear when its run completes.
- **Editing after a run** re-opens that inquiry to a re-run (idempotent; a changed question is a new
  question row, superseding the old — factra's `superseded_by_id` pattern — so prior answers stay
  traceable).

### What this changes vs §3.B / the shipped async runner

- The run is **scoped to an inquiry**, not the whole thesis. `ts_run` gains an inquiry key (or a run
  carries the set of `question_id`s it covers). `research/start`/`run`/`status` take an inquiry id.
- The one-active-run constraint becomes **one active run per inquiry** (or a global serialize —
  a panel question: allow parallel inquiries, or one at a time to bound cost/racing?).
- The UI: each inquiry card has its own state — unrun (with editable questions + a "Run this inquiry $X"
  button), running (its own progress), done (answers + derived verdict). The top-line recommendation is
  computed only over the inquiries actually run, and says which are still unexplored.

### Panel questions this adds

- Per-inquiry run vs whole-thesis run: confirm the `ts_run` scoping and whether inquiries may run in
  parallel or must serialize (cost/lock).
- Question editing model: mutable-until-run vs immutable-with-supersede; how a re-run after an edit
  reuses vs re-spends.
- The recommendation over a PARTIALLY-explored thesis: how to present "Continue diligence" honestly
  when only some lines of inquiry have been run (unexplored ≠ under-tested).

---

## 13. Panel review — Socratic + per-inquiry mechanics (2026-09-12)

Codex (gpt-5.1), Gemini 3 Pro, and a code-grounded subagent (all file:line premises in §10–12 verified
TRUE — `ts_run` is per-thesis with `ux_ts_run_one_active ON ts_run(thesis_id)` at `store.py:139`,
enforced twice (index + `create_run` query at `store.py:429`); `_run_research` sweeps all claims at
`routes.py:486`; `thesis_policy.qualify/decide` consume per-CLAIM evidence only; authority's
`is_controlling` = `primary_filing` only at `authority.py:41`; `attack_claim` retrieval is claim-scoped;
no `ts_question` exists). All three landed. Two refinements are load-bearing:

**A — Questions carry a DECLARATIVE SUB-CLAIM; the pipeline never sees the question (Gemini, the key
mechanism fix).** `attack_claim` expects a declarative claim (noun-binding + entailment); a Socratic
question ("Why do customers churn?") breaks it — a document cannot *entail* a question. So each generated
question is `{kind, text (the Socratic question, user-facing), target_claim (a declarative proposition),
polarity (does confirming target support or contradict the aspect)}`. The backend runs the UNCHANGED
`attack_claim` on `target_claim`; the user reads the question. This also DISSOLVES the polarity /
double-negative trap (a negatively-phrased "seek_contradiction" whose confirmation actually supports the
aspect): polarity is explicit on the sub-claim, so aggregation never guesses verdict from question type.

**B — Keep ALL normative verdicts flowing through `TechThesisPolicy.qualify`; the Socratic layer is a
pure VIEW, not a second decision engine (Codex + Gemini, the biggest risk).** Per-question status =
`qualify` over THAT question's evidence slice (never the prose answer). The question-set → aspect verdict
mapping is a new deterministic `TechThesisPolicy.aggregate_questions(...)`, in the vertical, using the
per-question statuses + polarities. **Hardening required:** today `enough`/`_independent`
(`thesis_policy.py:63`) counts any qualified row incl. sentiment — two independent sentiment rows could
make a seek_support question read "supported." Change so sentiment-only can never satisfy "enough"
(require `is_controlling` OR ≥2 independent NON-signal rows), and port `test_signal_rows_never_move_a_
verdict` to the new path. **Required eval:** a seek_support question with only sentiment evidence → the
aspect reads `under_tested`, never `supported`.

**Cost (Codex + Gemini, reconciled):** the expensive parts (refuter, retrieval, binding) stay **1× per
aspect**. `seek_support` + `seek_contradiction` are **lenses over the aspect's existing FOR/AGAINST
pull** (filter by `relation`) — reuse one retrieval; the search query stays the aspect claim, not the
Socratic wording. **Phase 1: run the per-aspect attack once and answer all four kinds from that
evidence** — costs stay within today's order of magnitude; `resolve_ambiguity` / `challenge_assumption`
get their own targeted retrieval only in Phase 2, under a separate per-question budget + ceiling.
`project_inquiry_cost(n_aspects_in_inquiry, k_questions)`, gated per kickoff, no run-all.

**Per-inquiry runs — SERIALIZE per thesis in Phase 1 (Codex's call, adopted over Gemini's parallel).**
All inquiries write shared `ts_thesis`/`ts_evidence` rows, and the credit directive says never launch a
spending run while another is in flight against shared state → keep `ux_ts_run_one_active ON
(thesis_id)`; the user runs one inquiry at a time (others show ready/queued). Parallel (index →
`(thesis_id, inquiry_key)` + mirror the `create_run` query + guard shared writes) is deferred. Scoping
changes: `ts_run` gains an inquiry key + `metadata.question_ids`; `_run_research` `todo` scoped to the
inquiry (`routes.py:486`); `research/start|run|status` take an inquiry id; `status` must REQUIRE a
run_id (inference from the first claim breaks with multiple runs, `routes.py:533`).

**Question editing (all three agree — immutable-with-supersede):** `run_id==''` → edit in place
(mutable-until-run, no spend yet); once answered → an edit inserts a NEW `ts_question` row + sets
`superseded_by_id` on the old, re-opening the inquiry. **Re-run idempotency = a hash of the active
question set** as the run's `idempotency_key` — `create_run` already dedups on `(thesis_id,
idempotency_key)` (`store.py:417`), so the same set re-runs free and a changed set is a new run, with
prior answers preserved on the superseded rows.

### Synthesized call — proceed to implement, with these locked:
1. Each question = `{kind, text, target_claim, polarity}`; `attack_claim` runs on `target_claim`,
   unchanged.
2. Verdicts only via `qualify`; new `aggregate_questions` in the vertical; harden `enough` vs
   sentinel-only; the sentiment-only eval is the ship gate.
3. Phase 1 shares one per-aspect retrieval across all four question kinds; per-inquiry cost projection +
   kickoff gate; no run-all.
4. Inquiry runs serialize per thesis (Phase 1); `ts_run` gains an inquiry key + question_ids; status
   requires run_id.
5. `ts_question` table; mutable-until-run then immutable-with-supersede; idempotency = active-question-set
   hash.

---

## 14. Build it generic: a kernel decision-testing engine + a vertical DecisionProfile (owner direction, 2026-09-12)

This reframes WHERE the feature lives. Per the standing **Kernel/Vertical Split** directive, the
MECHANICS are domain-free and central; a vertical ADAPTS them to become native. The litmus — "could a
LEGAL or BIOTECH vertical reuse this by supplying its own manifest, kernel untouched?" — is now the
design's explicit goal: the same engine informs a startup thesis here, a clinical-case decision in
noesis, a hiring decision in roster.

**Hard constraint (No-coupling-with-noesis directive):** the kernel names NO domain noun and eigen
contains NO medical/hiring vocabulary. "Generic so noesis/roster can reuse it" means the kernel is
shared *design lineage* those SEPARATE products adapt with their OWN profiles in their OWN repos. Eigen
ships exactly one profile — the tech one. The grep + AST guardrails (`tools/check_kernel_*`) enforce
this and must stay green.

### 14.1 The kernel engine (`packages/kernel/eigen_kernel/decision/`, domain-free)

Generic vocabulary — the tech vertical maps its nouns onto these; the kernel never says "thesis",
"startup", "rung", "claim":

- **Decision** — the proposition to be informed (tech: the thesis).
- **Aspect** — a coverage unit the decision rests on (tech: a ladder rung). The aspect SET is the
  coverage contract, supplied by the profile, not the model's to edit.
- **Inquiry** — a group of related aspects (the card).
- **Question** — `{kind, text, target, polarity}`: `kind` ∈ the generic lens taxonomy below; `text` is
  the Socratic question shown to the user; `target` is the declarative proposition the evidence pipeline
  actually tests; `polarity` says whether confirming `target` supports or contradicts the aspect.
- **QuestionKind** (generic decision-testing lenses, domain-free): `SEEK_SUPPORT`, `SEEK_CONTRADICTION`,
  `RESOLVE_AMBIGUITY`, `CHALLENGE_ASSUMPTION`.
- **Verdict** — `supported / contradicted / under_tested / unsettleable / open` (generic).

Kernel MECHANICS (no domain vocabulary): the Socratic question generator (prompted by the profile), the
per-`target` evidence run over kernel retrieval + the existing grounding/congruence/authority gates, the
per-question status, the deterministic aspect-verdict aggregation (delegated to the profile's policy),
and the run/curation/supersede/idempotency machinery. These are the pieces §10–13 specified — they move
into the kernel, parameterized.

### 14.2 The adaptation seam: `DecisionProfile` on the VerticalManifest

The vertical supplies, via `manifest.py` (like `thesis_policy` already is):

- `aspects()` → the coverage structure + each aspect's canonical question + settleability
  (tech: the 10-rung ladder, `schema.py`).
- `inquiries()` → the grouping of aspects into lines of inquiry.
- `decompose_directive` / `question_directive` → domain-flavored prompts: what a concrete decision looks
  like, and how to phrase typed Socratic questions + their declarative `target` sub-claims for this
  domain.
- `authority` + `qualify` + `aggregate_questions` → the domain judgment (authority tiers, what counts as
  "enough", the question-set→aspect-verdict mapping). Already vertical (`thesis_policy.py`,
  `authority.py`); `aggregate_questions` is the new piece (§13).
- connectors / corpus (already vertical).

The **tech vertical** implements `TechDecisionProfile` from the current startup-thesis ladder + tech
authority + the hardened aggregation policy. A medical or hiring product implements its own profile in
its own repo — never in eigen.

### 14.3 App layer becomes a thin adapter

`apps/api/thesis/` stops owning the mechanics: its routes wire the kernel engine + the active vertical's
`DecisionProfile` (from `build_manifest()`), exactly as the app already resolves `manifest.thesis_policy`
and `manifest.ui`. The just-shipped genesis (converse-to-a-decision) and the async runner are themselves
generic decision-support mechanics; they MIGRATE into the kernel engine under the same profile as part of
this work (or a tracked fast-follow) so there is one philosophy, not a kernel engine beside an app-layer
twin.

### 14.4 What this changes for the plan

- Build the NEW work (inquiries, typed Socratic questions, `aggregate_questions`, per-question runs) in
  `eigen_kernel/decision/` FIRST, domain-free, with the `DecisionProfile` contract; the tech vertical
  supplies the profile; the app wires it.
- Keep `tools/check_kernel_invariant.sh` + `check_kernel_imports.py` green at every step (no "thesis",
  "startup", "buyer", "sentiment" in kernel code/prompts — those come from the profile as data).
- Conformance: a second, MINIMAL profile fixture in tests (a toy non-tech decision) proves the engine is
  actually vertical-neutral — the real proof of §14's litmus, and the guard against the tech vocabulary
  creeping back into the kernel.

### Panel question this adds
- The `DecisionProfile` boundary: is the split above (kernel = mechanics + lens taxonomy + run/aggregate
  machinery; profile = aspects + inquiries + directives + authority + qualify/aggregate) the right cut,
  or does any piece (e.g. the lens taxonomy, the polarity model) belong on the vertical side? And is
  migrating genesis + the async runner into the kernel now in-scope, or a fast-follow?

---

## 15. Systematic question generation — the right set, right number, no duplication (owner direction, 2026-09-16)

**Status:** Draft for panel review (no code yet). Supersedes the question-generation MECHANICS of §10/§14
and the coverage CONTRACT of `TechDecisionProfile._LADDER`. Everything else (per-question target →
`qualify` → `aggregate`, per-inquiry runs, supersede/idempotency, the three synthesis artifacts) is
unchanged — this section only fixes WHAT gets asked and HOW MANY.

### 15.1 The problem (observed on a test thesis)

The generated questions are not a systematic sweep of the space that a funding decision turns on. Some
are sharp; others rabbit-hole into whatever the frame found interesting, and some duplicate each other.
Grounded in the code, three concrete causes:

1. **The coverage contract is incomplete for a FUND/PASS call.** `_LADDER` (`decision.py:27-41`) is a
   *will-anyone-buy-this* market ladder — problem, buyer, timing, market, plus a late-added
   competition/defensibility pair. But the diligence artifacts it feeds (`_PITCH_DECK_SECTIONS`,
   `_COLLECTIVE_TAKE_SECTIONS`, `_COMPETITIVE_COLUMNS`, `decision.py:170-261`) already reason over
   **team** (deck 193-195), **traction** (deck 187-189, matrix 256), **moat** (deck 190-192, matrix 253),
   and, weakly, **core technology** (matrix `tech_edge` 254) — dimensions the aspect contract does NOT
   name. Question generation can only systematically test what the contract names, so those
   decision-critical areas are covered only by whatever the free-form frame happens to surface. **Prior
   attempts** and **differentiation** are absent from BOTH the contract and the artifacts — genuinely
   net-new. Missing dimensions the owner named explicitly: *prior attempts / who else built this and what happened*,
   *true value proposition*, *differentiation*, *core technology required + feasibility/build risk*,
   *go-to-market / how the right customers are acquired*, *team / founder-market fit*.

2. **Budgeting is a ceiling, not an allocation — so depth is unbalanced.** `generate_inquiries`
   (`generate.py:16-17,126`) enforces `MAX_QUESTIONS=24` and `MAX_PER_DIMENSION=4` but **no minimum per
   dimension and no global allocation**. A model that finds one dimension juicy spends its four there
   while another dimension gets only the after-the-fact single gap-fill question (`generate.py:137-147`).
   "Right number" is not controlled; only "not too many total."

3. **No de-duplication and no relevance gate.** `generate_inquiries` coerces, caps, and covers, but
   never compares questions to each other — two clusters can ask near-identical `target`s. And nothing
   drops a question that binds to neither a load-bearing assumption/risk nor a decision artifact, so an
   interesting-but-off-thesis tangent survives. This is the rabbit-holing and duplication directly.

### 15.2 The principle

The question set is an INSTRUMENT for a single end — a defensible **Fund / Pass / More-diligence** call
and the three artifacts it rests on (memo, deck, competitive table). "Systematic" therefore means:

- **Complete over the space that determines the decision** — the contract must name every dimension the
  decision turns on, so no critical area is left to chance.
- **Bounded and balanced** — each dimension gets a deliberate, criticality-weighted *budget* of
  questions (a floor AND a ceiling), so nothing is starved and nothing rabbit-holes.
- **Precise and non-duplicative** — every question earns its place by binding to a specific
  assumption/risk or an artifact slot, and no two questions test the same proposition.

Neutrality still comes from the balanced lens SET (§10), not from hedged answers. This section changes
the *shape* and *bounds* of the set, not the typed-Socratic/`target`/polarity mechanism (§13.A) or the
verdict path (§13.B).

### 15.3 The redesigned coverage contract (vertical: `_LADDER` + `_INQUIRIES`)

Expand the tech ladder so the contract IS the funding-decision space. Proposed dimensions, grouped into
lines of inquiry (each aspect in exactly one — the partition test §6 still holds). `critical` drives the
budget (§15.4); `settleable` is unchanged (`corpus` / `partly` / `call_only`).

- **Thesis & value** — `problem_exists`, `status_quo_costs`, `already_spending`, **`value_prop`** *(is
  the claimed value real, specific, and quantified — not a generic "saves time")*.
- **Prior attempts & why-now** — **`prior_attempts`** *(who else — startups and incumbents — has tried
  to solve this, i.e. the graveyard)*, **`prior_outcomes`** *(why they succeeded or failed, and whether
  the blocking cause is now removed)*, `catalyst` *(why now)*.
- **Buyer & willingness** — `function_owns`, `budget_category`, `buyer_nameable`, `willingness_to_pay`.
- **Competition, differentiation & moat** — `competition` *(how crowded)*, **`differentiation`** *(the
  specific, true difference vs. named alternatives — not marketing)*, `defensibility` *(is the advantage
  durable — the moat)*.
- **Core technology & feasibility** — **`core_tech`** *(what technology is actually required)*,
  **`tech_feasibility`** *(is it proven or does it carry research/build risk this team must retire)*.
- **Go-to-market** — **`gtm_motion`** *(the strategy to reach and win the RIGHT customers — channel,
  wedge-to-scale)*, `switching_feasible` *(the switching cost / integration burden)*.
- **Market** — `enough_buyers` *(segment size)*.
- **Team** — **`team_credibility`** *(founder-market fit; `call_only` — the record rarely settles it,
  and it must read `unsettleable`, never fabricated)*.

Every aspect gains one field: **`feeds: tuple[str,...]`** — the artifact slot key(s) its answers
populate (a deck section key, a memo section key, or a competitive column key from the existing specs).
This is the machine link that makes "begin with the end in mind" (§13 directives) *structural*, not just
prompt guidance: the generator and the relevance gate (§15.5) use it. `feeds` is vertical vocabulary
(deck/memo/matrix keys), so it lives on the profile, not the kernel.

Rationale: this is bigger than today's ladder, but the per-dimension budget (§15.4) keeps the *question
count* bounded even as the *coverage* becomes complete. Contract completeness and set size are now two
separate knobs — which is the whole fix.

### 15.4 Question budget = a deterministic allocation, not a ceiling (kernel)

Replace `MAX_QUESTIONS`/`MAX_PER_DIMENSION` with a kernel `allocate_budget(aspects) -> {aspect_key: n}`:

- Each aspect gets **`n = 3` if `critical` else `2`**, clamped to `[1, 3]` — a floor of 1 (no dimension
  starved) and a ceiling of 3 (no dimension rabbit-holes). The total is the sum (≈ 28–32 across the
  contract; still one generation call). The vertical can tune the weights via the profile; the kernel
  owns the clamp.
- The generator is TOLD the budget per dimension and must fill it — the model chooses *which lenses* and
  *how to word* within each dimension's allotment (Rule 18: model owns wording, code owns structure).
- Enforcement is deterministic post-generation: for each dimension, keep at most its budget (required
  lenses first, as `questions.py:79-86` already does) and, if the model under-filled a dimension, the
  gap-fill (`generate.py:150`, thesis-native, already exists) tops it to the floor. The generic
  raw-rubric fallback stays the last resort only.

This makes "right number" a property of the contract + weights, computed, not emergent.

### 15.5 Precision: de-duplication + a relevance gate (kernel)

Two new deterministic passes in `generate.py`, both fail-open, both domain-free:

- **`dedup_questions(questions)`** — normalize each `target` (lowercase, strip punctuation/stopwords) and
  drop a question whose target is a near-duplicate of one already kept (token-Jaccard ≥ ~0.8; use
  embedding cosine if a cheap embedder is wired, else lexical). On a tie, keep the higher-priority lens
  (a `seek_contradiction` outranks a redundant `seek_support`) and the one tagged to a still-unfilled
  dimension. This removes the cross-cluster duplication directly.
- **`relevance_gate(question, frame, feeds_index)`** — drop a question that binds to NEITHER a frame
  assumption/risk (`frame.py` output) NOR any artifact slot in its dimension's `feeds`. A question that
  moves no assumption and fills no artifact does not move the decision — this is the anti-rabbit-hole
  cut. Gate runs only when a substantive frame exists (§13); with no frame it is a no-op (fall open).

Both run before the budget clamp, so dedup/relevance shrink the pool and the budget floor then re-fills
any dimension a drop emptied — keeping coverage while removing noise.

### 15.6 Kernel / vertical split

- **Kernel (`eigen_kernel/decision/`)**: `allocate_budget`, `dedup_questions`, `relevance_gate`;
  `generate_inquiries` rewired to consume a budget map + run the two gates. Still names no domain noun —
  weights and `feeds` come from the profile as data; the passes are pure string/graph mechanics. Guard
  with the existing `tools/check_kernel_*`.
- **Vertical (`eigen_vertical_tech/decision.py`)**: the expanded `_LADDER` (with `critical` + `feeds`) and
  `_INQUIRIES`; new prompt language in `_FRAME_DIRECTIVE`/`_INQUIRY_DIRECTIVE` naming the added
  dimensions (prior attempts & why-they-failed, value prop, differentiation, core tech + feasibility,
  GTM, team) and instructing the frame to decompose the thesis INTO these dimensions. `Aspect` gains an
  optional `feeds` field (kernel type, generic — a tuple of opaque slot keys).
- **App (`apps/api/thesis/`)**: unchanged wiring; `tl_generate` (endpoint `routes.py:1121`, call site `routes.py:1145`) already calls
  `generate_inquiries`. The larger set flows through the existing per-inquiry curation + run untouched.

### 15.7 Verification (free-first)

- **Contract completeness (deterministic):** every artifact slot in `_PITCH_DECK_SECTIONS` /
  `_COLLECTIVE_TAKE_SECTIONS` / `_COMPETITIVE_COLUMNS` is `feeds`-referenced by ≥1 aspect (no artifact
  the questions never gather for); the `_INQUIRIES` partition still covers `_LADDER` exactly (§6).
- **Budget (deterministic):** `allocate_budget` gives every aspect ∈ `[1,3]`; after generation every
  dimension has ≥ its floor and ≤ its budget; total ≤ Σ budgets.
- **Dedup (deterministic):** a fixture with two near-identical targets collapses to one; a
  `seek_contradiction` is preferred over a duplicate `seek_support`.
- **Relevance (deterministic):** a question binding to no assumption/risk and no `feeds` slot is dropped
  when a frame is present, kept when no frame (fall-open).
- **No regression:** verdict path (`qualify`/`aggregate_questions`), per-inquiry runs, supersede, the
  three synthesis artifacts, and kernel guardrails stay green.
- **One gated real-LLM smoke** (projected + approved, after the free suite): the same test thesis now
  produces a balanced set — every dimension present, none over-asked, no duplicate targets, each question
  traceable to an assumption/risk or an artifact slot. Compare against the pre-change output.

### 15.8 Open questions (for the panel)

1. **Contract size vs. cost.** ~15 aspects × 2–3 questions ≈ 28–32 questions, each a `target` evidence
   run. Even with the §13 "one per-aspect retrieval, four lenses off it" reuse, this is more spend than
   today. Is the fuller contract right for a flagship diligence run, with the per-inquiry kickoff gate
   (§12) as the cost control (the user still runs one line at a time), or should some dimensions
   (team, tech feasibility) be *curation-only* — drafted for the user to run, not auto-budgeted?
2. **`feeds` as the relevance test.** Is "binds to an assumption/risk OR an artifact slot" the right
   precision gate, or too permissive (nearly everything feeds *some* slot)? Alternative: require binding
   to a frame assumption/risk for non-critical dimensions.
3. **Dedup threshold + embedder.** Lexical Jaccard is cheap and deterministic but misses paraphrase; an
   embedding dedup is sharper but adds a call/dependency. Which for Phase 1?
4. **Weights.** `critical→3 / else→2` is a guess. Should the frame's own emphasis (a dimension it flags
   as load-bearing for THIS thesis) raise that dimension's budget by 1, within the clamp?
5. **Team / willingness-to-pay honesty.** `team_credibility` and `willingness_to_pay` are `call_only` —
   they should read `unsettleable` and route to the people-discovery leg, never be answered from the
   record. Confirm they still get questions (to frame the expert call) but never a corpus verdict.

### 15.9 Panel review (2026-09-16)

Codex (gpt-5.1), Gemini 3 Pro, and a code-grounded subagent. All three landed; relayed honestly.

**Code-grounded subagent — §15's mechanical premises verified TRUE** at exact lines (`_LADDER` 12 keys
`decision.py:27-41`; `MAX_QUESTIONS=24`/`MAX_PER_DIMENSION=4` `generate.py:16-17,126`; single
after-the-fact `_gapfill` `generate.py:137-150`; no dedup and no relevance gate in the coerce/cap loop
`generate.py:112-131`; `Aspect` has no `feeds` field `types.py:50-57`; `MAX_QUESTIONS_PER_ASPECT` +
required-lenses-first trim `questions.py:79-86`). **Two corrections, now folded into §15.1/§15.6:**
"prior attempts" and "differentiation" are absent from the artifacts too (net-new, not "artifacts
already need them"); the `generate_inquiries` call site is `routes.py:1145` (1121 is the endpoint).

**Both external CLIs independently reached the same two load-bearing objections:**

1. **The static budget (`critical→3/else→2`) does not fix rabbit-holing — it moves it INSIDE a
   dimension and forces filler.** A dimension with one real frame risk is padded to quota with generic
   questions — exactly the low-signal content complained about. Both want a **frame-weighted allocator**:
   Gemini — base 1 + 1 per tagged frame risk/assumption, cap 3; Codex — a global target total (~24)
   distributed by weights from `critical` + the count of frame assumptions/risks tagged to each dimension
   (`frame.py:29-40`), floor 1 / cap 4, with **reallocation** of an unfillable dimension's budget to
   higher-weight dimensions INSTEAD of generic gap-fill. Depth must follow this thesis's risk density.

2. **The relevance gate must be a ranking SCORE, not a binary filter.** A false negative wipes a
   question entirely; the gate is a no-op exactly when the frame is weak (the worst drift case); and
   anchoring it on `feeds` (downstream artifact slots) both leaks and is too permissive (Gemini: almost
   anything maps to *some* deck slide). Reconciled: compute a per-question relevance score to the frame's
   assumptions/risks (primary signal), use it to SELECT the top questions within each dimension's soft
   budget, and never drop a dimension below floor 1. `feeds` is at most a weak secondary signal, and the
   kernel treats feed keys as OPAQUE tokens (both — else the kernel/vertical split is violated).

**Dedup (both):** lexical Jaccard is too brittle for paraphrased `target`s — a cheap **embedding** pass
at question-gen time is worth it (far cheaper than the evidence runs it prevents, consistent with the
credit discipline). Codex adds: dedup must be **dimension-aware and used as a tie-breaker within
selection**, never a blind global pass that can delete a dimension's only serious probe because it shares
vocabulary with another dimension.

**`call_only` dimensions must not auto-drive evidence runs (both — the safety fix).** `team_credibility`
and `willingness_to_pay` predictably end `unsettleable` yet, as coded, still fire the full attack
pipeline if their inquiry is run (`routes.py:744-755`, `decision/run.py:48-55`). Default them to
**questions-only** (an expert-call agenda), no evidence run, always reading `unsettleable`/needs-a-person
— structurally encoded via `settleable`, not left to a prompt.

**Codex-unique (adopted):**
- **The contract still misses evidence-settleable dimensions** the artifacts already carry: **traction /
  proof** (deck 187-189, matrix 256) and **business model / unit economics** (deck 184-186) as
  first-class aspects, and a home for **regulatory / platform / ecosystem dependence**.
- **Over-atomization / layer confusion (the deepest point).** `value_prop`, `gtm_motion`, and much of
  `core_tech` are largely *how the thesis reads* — precisely what the FRAME already captures
  (`frame.py:86-103`). Making each a separate aspect double-counts: one frame assumption spawns three
  overlapping questions across three aspects, then gets awkwardly deduped. §15 conflates three distinct
  layers — **decision dimensions** (evidence-settleable, the contract), **how this thesis is framed**
  (the frame), and **how artifacts are laid out** (deck/memo/matrix). Keep them separate: the contract
  stays a lean set of evidence-settleable dimensions; value-prop/GTM emphasis rides in the frame and
  BIASES the budget, rather than adding rungs.
- **`prior_attempts` vs `competition` is a fuzzy boundary** → near-duplicate questions. Merge into one
  "historical & current landscape" aspect, or split by TYPE (incumbents vs. past startups), not
  outcome-vs-competition.
- **Budget math mismatch:** ~20 aspects × 2–3 ≈ 40–60, but §15.8 assumed ~15 → 28–32. A leaner contract
  (~10–12 evidence dimensions) under a global-target allocator reconciles this to ~24.
- **Drop 15.7's "every artifact slot fed by ≥1 aspect" test** — cross-cutting slots (`diligence`,
  `what_would_change`, `ask`) are summarizers, not fed from one rung; the test invites nonsense mappings
  made only to pass it. Keep only the `_INQUIRIES`-partitions-`_LADDER` test; `feeds` is informational.
- **Cost: add a shallow-vs-deep default.** §15 hardwires the deep config; the credit discipline wants a
  systematic-but-shallow default (1 `seek_support` + 1 `seek_contradiction` on critical dimensions) with
  deep as an explicit opt-in, plus visibility of cumulative cross-inquiry spend.

**Both CLIs' verdict: PROCEED-WITH-CHANGES.** The direction (explicit contract + structural budget +
precision passes) is right and fixes real failures; as written it is too rigid and too reliant on
brittle lexical heuristics to be a trustworthy "systematic sweep."

### 15.10 Synthesized call — proceed, with these locked (supersedes §15.4–§15.8)

1. **Contract = lean, evidence-SETTLEABLE dimensions only** (§15.3 revised). Keep the market/buyer/timing
   rungs; ADD `prior_landscape` (incumbents + past startups + their outcomes, one aspect — not split
   prior/competition), `differentiation`, `traction`, `business_model`/unit-economics, `core_tech`+
   `tech_feasibility`, and a `regulatory_platform` home where a thesis rides on rules/platforms. **Do
   NOT** add `value_prop`/`gtm_motion`/team as corpus rungs — value-prop and GTM live in the FRAME (they
   bias the budget); `team_credibility` + `willingness_to_pay` are **`call_only`, questions-only** (an
   expert-call agenda, never an evidence run, always `unsettleable`). Target ~10–12 evidence dimensions.
2. **Frame-weighted global-target allocator** (replaces the flat `critical→3/else→2`).
   `allocate_budget(aspects, frame, total≈24)`: weight = f(`critical`, count of frame assumptions/risks
   tagged to the dimension `frame.py:29-40`); floor 1, cap 4; **reallocate** an unfillable dimension's
   budget to higher-weight dimensions rather than manufacturing gap-fill. `MAX_QUESTIONS` stays a hard
   profile/user upper bound. A default **shallow** mode (1 support + 1 contradiction on critical dims)
   with **deep** as explicit opt-in.
3. **Relevance + dedup = a scoring/selection mechanism, never hard filters.** Score each question by
   binding to the frame's assumptions/risks (primary); select top-N within each dimension's soft budget;
   never drop a dimension below floor 1. Embedding-based dedup at gen-time as a **dimension-aware
   tie-breaker** (drop the lower-relevance near-duplicate), not a blind global pass. `feeds` stays
   OPAQUE to the kernel and is at most a weak secondary signal.
4. **Structural honesty for call-only dimensions:** `settleable=="call_only"` ⇒ no evidence run, verdict
   fixed to `unsettleable`, routed to the people-discovery leg — enforced in the run path
   (`routes.py:744-755`, `decision/run.py`), not by prompt.
5. **Verification unchanged in spirit + the `_INQUIRIES`-partitions-`_LADDER` test stays; DROP the
   "every artifact slot fed by ≥1 aspect" test.** New deterministic tests: allocator floor/cap +
   reallocation; relevance/dedup as selection preserving floor 1 per dimension; call-only never emits an
   evidence run. Free-first; the one gated real-LLM smoke compares the new balanced set against today's
   output. The sentiment-only and evidence-typing evals (§13) are unchanged and remain ship gates.

Open for the owner before code: the shallow-vs-deep default (is shallow the right default, or does a
flagship thesis always run deep?), and whether `regulatory_platform` is one aspect or folded into
`core_tech`/`defensibility`.

### 15.11 Implementation landed (2026-09-16) — §15.10 built, owner decisions made

Built kernel-first per §15.10. All new code is domain-free and green (`tools/check_kernel_*` show no new
leak; 161 targeted tests pass; the full `packages` suite adds zero failures — the 3 reds are pre-existing
on `main`). **Two open owner decisions, made to ship a quality product:**
- **Depth default = STANDARD (a full systematic sweep, `total≈24`), not shallow.** The allocator exposes
  `total` so a shallower pass is one argument, and cost is already gated per-inquiry kickoff (§12) + the
  new call-only exclusion — so the quality sweep is the default and the credit control is the kickoff
  gate, not a thinned default set.
- **`regulatory_platform` is its OWN aspect** (in the "timing / dependencies" line of inquiry), not
  folded into `core_tech`/`defensibility` — platform/regulatory dependence is a distinct failure mode a
  funding decision must see named.

What shipped:
- **Kernel** `decision/budget.py` — `allocate_budget(aspects, frame, total)`: frame-weighted
  (`critical` + count of frame assumptions/risks tagged to the dimension), floor 1, cap 4, with
  reallocation of an unfillable share (no filler). `decision/select.py` — `score_questions` (relevance
  to the frame's assumptions/risks; lexical by default, optional `embed` seam, one batch reused for
  dedup) + `select_for_aspect` (required-lenses-first, top-by-relevance to soft budget, dedup as a
  tie-breaker, never below floor 1). `decision/generate.py` rewired around both; the flat
  `MAX_QUESTIONS`/`MAX_PER_DIMENSION` ceilings and blind gap-fill-to-quota are gone (a hard safety
  ceiling remains). `decision/run.py` — a `call_only` aspect NEVER gathers evidence (no spend), reads
  `unsettleable`. `Aspect` gained an opaque `feeds` field.
- **Vertical** `decision.py` — the redesigned lean, evidence-settleable ladder (18 aspects incl.
  `prior_landscape`, `differentiation`, `tech_feasibility`, `traction`, `business_model`,
  `regulatory_platform`; `value_prop`/`gtm`/`core_tech` live in the FRAME, not as rungs;
  `team_credibility` + `willingness_to_pay` + `switching_feasible` are `call_only`), a 7-line-of-inquiry
  partition, `feeds` hints, and directives updated to name the new dimensions.
- **App** `thesis/routes.py` — `call_only` aspects excluded from the evidence sweep, cost projection, and
  run progress (`_evidence_questions`); their verdict reads `unsettleable`; `/experts` surfaces all three
  call-only dimensions. `thesis/schema.py` — `team_credibility` added to the legacy ladder + `ASK_WHO`
  so the expert-call path stays consistent.
- **Tests** `decision/test_budget.py` (allocator floor/cap/reallocation/frame-emphasis; selection
  required-lenses-first; dedup never empties a dimension), `decision/test_run.py` (call-only spends no
  gather). The `_INQUIRIES`-partitions-`_LADDER` invariant still holds.

Not yet wired: the optional `embed` seam is built and kernel-tested but the app passes `embed=None`
(deterministic lexical dedup) to avoid an unprojected live embedding call in the generate path — enabling
it is one argument at `generate_inquiries(...)`. UI is data-driven, so the new contract renders with no
`apps/web` change. Not run against prod (no spend) — a gated real-LLM smoke on one thesis is the
suggested next verification.
