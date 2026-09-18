# Spec: Orientation-first, landscape-grounded question generation

**Status:** proposed (parked — implement after the beachhead UX prototype)
**Owner:** thesis vertical + kernel decision
**One line:** Before the system asks *any* question — during thesis formation, thesis improvement, framing, or line-of-inquiry generation — it must first ask *"what do I need to know to ask the right questions here?"*, retrieve that from the **current** record (corpus + live web), and generate from that dated landscape — never from the model's parametric memory.

---

## 1. Problem

Question generation today is **purely LLM-parametric**. Verified in code:

- `POST /thesis/{id}/inquiries/generate` (`apps/api/thesis/routes.py:tl_generate`) does two pure-LLM steps and retrieves nothing fresh first:
  1. `frame_decision(take_llm, decision=thesis, context=_framing_context(d), directive=frame_directive, aspects)` — and `_framing_context` (`routes.py:839`) is **only** the genesis conversation + the author's surfaced assumptions/open threads. No corpus, no web.
  2. `generate_by_inquiry(strong_llm, decision, inquiries, aspects, directive=inquiry_directive, frame)` — generates over that frame.
- The vertical directives (`_FRAME_DIRECTIVE`, `_INQUIRY_DIRECTIVE`, `_QUESTION_DIRECTIVE` in `packages/vertical_tech/eigen_vertical_tech/decision.py`) instruct the model to *name the specific incumbents, past startups, the "why now" catalyst, the competitive field* — i.e. to recall specifics **from memory**.

The same is true wherever else questions/edits are formed: **genesis** (`/thesis/{id}/genesis`), **thesis improve / self-improve** (`/improve`), redraft, add-question.

**Consequence.** The research plan — which incumbents to interrogate, the "why now", the regulations, the benchmarks, the funding landscape — is bounded by the model's **training cutoff**. Recent entrants, new funding rounds, a 2026 regulation, a new SOTA benchmark, a market event: if the model doesn't already know it, **it is never asked about**, and no amount of grounded answering downstream recovers it. The answers are current; the *plan* is stale. This is the "asking about outdated competitors" failure, and because the plan gates all downstream evidence, it is the highest-leverage staleness bug in the product.

**Non-goal to preserve:** the answering path is already grounded/current (corpus + web + the span-check/congruence gates). This spec does **not** touch answering. It fixes *what gets asked*.

---

## 2. Principle

> **Orient before you ask.** Every place the system forms a question or edits the thesis, it first performs an *orientation* step — the LLM decides *what it must learn to ask well*, retrieves that from the current record, and only then generates, drawing every named specific from the dated retrieval, not from memory.

Two moves, in order:

1. **Ask-what-to-retrieve (meta-cognition), not just retrieve-then-ask.** The model is prompted to produce *orientation queries*: "given this thesis, what do I need to know to ask the right questions?" — the current incumbents & recent entrants, recent funding, current regulation/policy, latest benchmarks/SOTA, recent market events, the real present-day "why now". This is the insight to preserve: the model chooses what to learn, scoped to *this* thesis, rather than us hard-coding a fixed scan.
2. **Generate only from the dated landscape.** Named entities, catalysts, regulations, numbers in a frame/question/thesis-edit must trace to a dated source in the retrieved brief; anything not in the brief is phrased generically ("which incumbents currently bundle X?" not "does Epic bundle X?") or explicitly flagged *to verify*. Everything is stamped *as of {today}*.

---

## 3. Scope — everywhere a question or a claim is formed

| Surface | Endpoint / fn | What must be landscape-grounded |
|---|---|---|
| Thesis formation (genesis) | `/thesis/{id}/genesis`, `converse`/`genesis.turn` | The **sharpening questions** the agent asks, and any specific it asserts back ("an incumbent already does X"), must reflect a current scan. |
| Thesis improve / self-improve | `/thesis/{id}/improve` (`genesis.improve`) | The **proposed thesis edit** must be checked against the current landscape (e.g. don't propose a "wedge" an incumbent already ships as of today). |
| Framing | `frame_decision` | Mechanism, load-bearing assumptions, **competitive field**, "why now" — grounded in the scan. |
| Line-of-inquiry generation | `generate_by_inquiry` / `generate_inquiries` | The questions and their declarative `target`s. |
| Per-aspect / redraft / add-question | `generate_questions`, redraft path | Same discipline. |

**Intensity scales with cost tolerance:** genesis/improve get a *light* scan (cheap, few queries, snappy); inquiry generation gets the *full* scan (it is already a gated, projected spend). See §6.

---

## 4. Design

### 4.1 The reusable step: `orient_and_scan → LandscapeBrief`

A single, reusable capability with three phases. **Kernel/vertical split:** the *mechanism* (orient → retrieve → digest) is domain-free and lives in the kernel; the *vocabulary* of "what a thesis of this kind needs to know" is a vertical directive.

**Phase A — Orientation (meta call).**
Input: the thesis text + its structured `subject` (`product`, `segment`, `substitute`, `job`) + (for improve/genesis) the conversation so far.
The LLM, under a vertical **orientation directive**, emits a small, typed set of **orientation queries**, each with an intent tag:

```
{"queries": [
  {"q": "<search query in current terms>", "need": "incumbents|entrants|funding|regulation|benchmark|why_now|market_event|substitute",
   "why": "<what asking this lets me ask well>"}
]}
```

- Cap the count (e.g. ≤ N_light=4 for genesis/improve, ≤ N_full=8 for generate).
- The directive forbids the model from *answering* here — only naming what it must learn. It must include at least one "who/what is current *now*" query per relevant `need`.
- Queries are phrased in the thesis's own nouns + the segment, and are **present-tense/dated** ("... 2026", "latest", "current").

**Phase B — Retrieve (current, typed).**
Run each orientation query against, in order:
1. **Corpus** (hybrid keyword + pgvector), scoped to the thesis subject/segment — durable, tier-classified.
2. **Live web leg** (`atk._web_client(manifest)`) for freshness/recency — news-grade, sentiment.
3. **Startup Search** (the injected `_thesis_su_search`) for *current* peers/entrants — reuse; dedupe with competitive discovery (§7).

Keep the register + tier discipline on every hit (source, `register` filed|stated|observed, `evidence_kind`, `as_of` date, tier). **Coverage is signal, not fact.** Bounded fan-out; cap total web calls.

**Phase C — Digest → `LandscapeBrief`.**
Compose a compact, cited digest (one grounded model call, or deterministic assembly) — bounded size — with typed sections:

```
LandscapeBrief = {
  as_of: <today>,
  incumbents: [{name, what_they_do, source, register, as_of}],
  entrants:   [{name, note, source, as_of}],       # recent / current
  funding:    [{who, round, source, as_of}],
  regulation: [{rule, status, source, as_of}],
  benchmarks: [{name, result, source, as_of}],
  why_now:    [{catalyst, source, as_of}],
  unknowns:   [<what the scan could NOT establish — feeds "to verify">]
}
```

Every entry carries a **date** and a **register**. Entries the scan could not ground go in `unknowns`, not into the "facts".

### 4.2 Grounding the generators

Feed `LandscapeBrief` into the frame + question generators as the **authoritative source of specifics**, and change the directives:

- **Name specifics ONLY from the brief.** Any incumbent, entrant, regulation, benchmark, funding fact named in a frame/question/target must appear in the brief (with its date). If a needed specific is absent, either (a) phrase the question generically so evidence fills it, or (b) name it and tag it `to_verify`.
- **Prefer present-tense, entity-open phrasings:** "which incumbents currently bundle a predictive readmission model?" over "does Epic bundle one?".
- **Date-stamp:** the frame and questions are "as of {today}"; the model treats any recency it "remembers" as a hypothesis to check against the brief.
- **Use `unknowns`** to seed red-team / "what would change this" questions.

`_framing_context(doc)` is extended to append a `CURRENT LANDSCAPE (as of {today}, dated + typed — use these specifics, do not recall from memory):\n<brief>` block. `generate_by_inquiry` gets the brief too (not only via the frame).

### 4.3 Reuse downstream

The `LandscapeBrief` is cached on the thesis (jsonb, with `as_of` + a TTL). It also:
- seeds the **competitive artifact** (dedupe/merge with `competitive.research_landscape`);
- is available as context to genesis/improve without re-scanning within the TTL;
- can surface in the UI (the prototype's Plan screen: *"scanned the current landscape — 6 recent entrants, 1 new CMS rule"*), making currency visible.

---

## 5. Anti-staleness discipline (hard rules)

1. **No unsourced specific.** A named competitor/regulation/benchmark/number in a question, target, frame, or thesis-edit must trace to a dated brief entry, else it is generic or `to_verify`. (Enforceable by a lint: scan generated questions for known-entity tokens absent from the brief.)
2. **Everything dated.** `as_of` on the brief and stamped into the frame; the model must not present model-recalled recency as current.
3. **Coverage ≠ fact.** A scan hit is a *lead to verify*, never a settled fact; it keeps its register and never upgrades a downstream answer's authority (existing authority discipline holds).
4. **Orientation is scoped, not generic.** The orientation queries must be specific to *this* thesis's mechanism/segment — a generic "who are competitors" is a failure; "which 2026 FHIR-native CDS entrants target mid-sized hospitals" is right.

---

## 6. Cost / credit discipline

- **Bounded + gated.** Orientation is 1 small LLM call; retrieval is capped (≤ N queries × capped web calls); digest is 1 call. Project the cost and fold it into the existing `/inquiries/generate` gate (it is already a projected, approved spend).
- **Two intensities.** *Light scan* for genesis/improve (N_light queries, corpus-first, minimal web) so shaping stays snappy; *full scan* at inquiry generation.
- **Cache + TTL.** Store the brief on the thesis; reuse within TTL (e.g. 7 days) for improve/answers; a "refresh landscape" action re-scans. Never re-scan silently on every keystroke.
- **Never launch a scan while another run is in flight** against the same thesis (existing one-active-run discipline).

---

## 7. Where it plugs into the code

- **New kernel capability** (domain-free): `eigen_kernel/decision/orient.py` (or `landscape.py`):
  `async def orient_and_scan(llm_json, *, retrieve, web, peers, decision, subject, directive, caps) -> LandscapeBrief`.
  `retrieve`/`web`/`peers` are injected callables (corpus hybrid search, web client, startup search) so the kernel names no domain source.
- **Vertical directive** (`eigen_vertical_tech/decision.py`): `orientation_directive(decision)` — the "what a tech-investment thesis must know to ask well" vocabulary (incumbents, entrants, funding, regulation, benchmarks, why-now, substitutes). Add the anti-staleness rules to `_FRAME_DIRECTIVE`, `_INQUIRY_DIRECTIVE`, `_QUESTION_DIRECTIVE`, and the genesis/improve directives.
- **App wiring** (`apps/api/thesis/routes.py`):
  - `tl_generate` (`~:1258`): call `orient_and_scan` (full) **before** `frame_decision`; store the brief on the thesis; extend `_framing_context` to append it; pass it to `generate_by_inquiry`.
  - `/genesis` + `/improve`: call `orient_and_scan` (light) and pass the brief into the genesis/improve LLM context so sharpening questions + proposed edits are current.
  - Reuse `atk._web_client(manifest)` and the injected `_thesis_su_search`; corpus search via the existing retrieval path.
- **Persistence** (`apps/api/thesis/store.py`): `ALTER TABLE ts_thesis ADD COLUMN landscape_brief jsonb ... ` + `as_of`; setter/getter; expose on `GET /thesis/{id}` for the UI note.
- **Prompts:** the orientation directive + the "name specifics only from the dated brief / else generic or to_verify / as of {today}" clauses.

---

## 8. Eval (held-out, designed to catch staleness)

- **Stale-incumbent case:** a thesis whose real incumbent/landscape changed *after* the model's cutoff → assert the generated questions name the *current* entity (from the scan), not the stale one (from memory).
- **Missing-entrant case:** a recent entrant that only the web knows → assert at least one question interrogates it.
- **No-unsourced-entity gate:** scan every generated question/target for named entities; fail if any named entity/regulation/benchmark is absent from the `LandscapeBrief`.
- **Genericity check:** questions about a landscape the scan couldn't ground must be phrased generically or tagged `to_verify`, never fabricate a specific.
- **Cost regression:** the scan stays within the projected budget; light-scan latency at genesis stays acceptable.

---

## 9. Rollout / phasing

1. **Phase 1** — `orient_and_scan` (kernel) + vertical orientation directive; wire into `tl_generate` (full scan) → questions grounded. Ship the anti-unsourced-entity lint + the two staleness eval cases.
2. **Phase 2** — feed the brief into `frame_decision` explicitly; surface the "scanned the landscape" note in the UI.
3. **Phase 3** — light scan into `/genesis` + `/improve` so thesis formation is current.
4. **Phase 4** — dedupe/merge the brief with competitive discovery; caching + "refresh landscape" action; broaden eval.

---

## 10. Open decisions (resolve at implementation)

- Scan depth vs. latency at genesis (how light is "light"?).
- Brief TTL and when a "refresh" is forced (thesis edited materially? > N days old?).
- Web-thin domains: fallback behavior when the live web returns little (lean on corpus; widen `unknowns`).
- Whether the digest is a grounded LLM call or deterministic assembly of retrieval rows (cost vs. coherence).
- How aggressively to *rewrite* questions the model already produced vs. generate fresh from the brief.

---

## 11. UX surface (reflected in the beachhead prototype)

The lifecycle prototype now shows the intended surface, which the build must implement:

- **Plan screen** — a "🛰 Scanned the current landscape · as of today — so the questions name what's real *now*, not the model's memory" strip sits *above* the generated questions, with dated chips for what the scan found (recent entrants, a new rule, an incumbent's current capability). A **"Re-scan landscape"** action re-runs the scan (forces a fresh brief, §6). Every named entity in a question is understood to trace to a dated brief entry.
- **Brainstorm screen** — the thesis-native Q&A proactively surfaces "💡 Weak points it surfaces — probe these"; those probes and their answers should likewise be grounded in the current brief, and any gap they hit hands off to **Experts**.
- **Genesis / Improve** — (light scan) the sharpening questions and proposed thesis edits should visibly reflect current reality (e.g. "an incumbent already ships this today"), not stale recall.

**Come back to this after the beachhead UX prototype is locked.** The IA is settled; this spec is the backend contract that makes the "as of today" promise on those screens real.
