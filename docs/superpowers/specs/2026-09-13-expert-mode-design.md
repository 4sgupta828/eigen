# Design: Expert Mode — validate a thesis with the people the record can't reach

**Date:** 2026-09-13
**Status:** Draft for panel review (no code yet)
**Feature:** new `apps/api/experts/` + a web mode in `apps/web/index.html`, plus a kernel
`PeopleSearchClient` port and a `vertical_tech` people-relevance profile. Closes the loop the thesis
engine already opens (`call_only` aspects → `POST /thesis/{id}/call`).
**Inspiration:** Tegus / GLG / AlphaSights expert calls — but as *discovery + validation from data*,
not booking. Mirrors the existing **Startup Search** discovery pattern (`apps/api/startups/`).

---

## 1. Intent

When a thesis is tested, the engine already marks certain aspects `call_only` —
`willingness_to_pay` and `switching_feasible` (`vertical_tech/decision.py:34,36`;
`thesis/schema.py:22 LADDER`) — meaning *"No document can settle this. It needs a person"*
(`attack.py:140`). Those are exactly the questions expert calls exist to answer.

Expert Mode is the missing leg of the diligence loop:

```
thesis → engine marks call_only / under-tested aspects
       → discover the experts who could settle THOSE aspects
       → generate the questions to ask each (from the aspect's target + ASK_WHO role)
       → user reaches out (we surface the public profile + draft the outreach)
       → user pastes the call transcript back
       → it enters as gated `call`-register evidence that moves the verdict
```

A call transcript is the **only** evidence that can settle a `call_only` aspect — web coverage never
can (`_enough`, `decision.py:143`; `SOURCE_REGISTER["call"]=STATED`, `schema.py:104`). This closes a
loop the product opens but currently dead-ends at "needs a person."

**Non-goal:** booking real calls. GLG/Tegus/AlphaSights are compliance-managed *services*, not search
APIs. Expert Mode = discover + validate from licensed/public data, framed as *public professional
signal*; outreach is the user's action.

## 2. What already exists (build on, not from scratch)

- **`apps/api/thesis/people.py`** — *"Who could settle a claim the record cannot."* Already derives
  operator/advisor/buyer candidates from evidence with strong-key identity discipline
  (`people.py:14-17,46,82`). Today a by-product of an attack; Expert Mode promotes it to first-class.
- **`POST /thesis/{id}/call`** (`routes.py:404`) — the loop-closer: an expert call → typed evidence
  (`register=stated, source_key="call", signal_only=False, said_by, said_role`, `routes.py:418-425`)
  on the exact rung, flipping it `unsettleable → primary_research_needed` (`routes.py:428-430`).
- **`ASK_WHO`** (`schema.py:53`) maps each `call_only` rung → which role to ask; `next_move` already
  tells the user *what* to ask (`routes.py:1012-1021`). Expert Mode makes this *actionable*.
- **Startup Search async-job pattern** — `su_job` table, `RUNNERS`/`start_job` on a daemon thread with
  its own loop+pool, `_progress` cooperative cancel, `orphan_running_jobs` recovery
  (`startups/pipeline.py:84,890-924`; `routes.py:504,548`). A ready template for a discovery job.
- **Kernel port + cassette template** — `WebSearchClient` Protocol → `CompositeWebSearch` →
  `CassetteWebSearch` → `build_web` env-key gating (`providers/websearch.py:31,44,132`;
  `runtime/build.py:76`). The exact shape a `PeopleSearchClient` copies.
- **Web UI plumbing** — `linkedinSearchUrl()` (`index.html:8571`), the `body[data-mode=…]` +
  `#…Tab` + `setMode()` mode-registration recipe (`index.html:888,3128,5176`).

> ⚠️ Naming collision: an `expert_feed` connector already exists (RSS of expert *opinion* —
> `connectors/expert_feed.py`; `schema.py:99`). Use a distinct key: **`expert_call`** (evidence) /
> **`people`** (the search port). Do not overload `expert_feed`.

## 3. What's possible (the API reality, 2026)

- **No scraping, ever.** Proxycurl (the obvious LinkedIn API) shut down July 2025 after LinkedIn sued
  its parent into a settlement; hiQ settled with a $500K judgment + data-deletion injunction; SerpAPI
  is now itself sued by Google. LinkedIn litigates scrapers out of existence.
- **Discovery → Exa** (already wired): its People Search / Websets vertical searches 1B+
  weekly-refreshed profiles by expertise described in natural language, returning public profile URLs
  with relevance scores. Zero new vendor, zero new legal surface.
- **Precision/validation → People Data Labs** (Phase 2): genuine 140-attribute Person Search (title,
  seniority, skills, past company) — licensed data with compliance docs. Coresignal is the swap-in
  (free search, pay to hydrate) if career-history depth dominates.
- **Legal posture:** licensed data + public-web semantic search only; PII minimization (name, role,
  company, expertise, public URL); honor deletion/objection; CCPA B2B exemption expired (treat US
  professional data as protected); display links, never re-hosted scraped content.

## 4. Architecture (kernel/vertical split)

- **Kernel (domain-free):** `providers/people_search.py` — `PersonResult` DTO (name, headline,
  current/past roles, org, profile_url, expertise[], relevance, provider, providers[]),
  `PeopleSearchClient` Protocol (`search(query, *, filters, max_results) -> list[PersonResult]`),
  `CompositePeopleSearch`, `FakePeopleSearch`, `CassettePeopleSearch` (namespace `"people"`);
  `runtime/build.py:build_people(mode=…)` gated on env keys, Fake/replay when absent. The kernel never
  learns what an "expert" or "buyer" is.
- **Vertical (`vertical_tech`):** the judgment — phrase an expertise query for a tech-investment
  aspect, map `call_only` rungs → roles (reuse `ASK_WHO`), and a **credibility/authority signal for
  people** (a VP of Ops at a target-segment 3PL outranks a random commenter — the people analogue of
  the source-authority pyramid).
- **App (`apps/api/experts/`):** the async discovery job (mirror `su_job`), the routes, and the wiring
  back to `/thesis/{id}/call`.
- **Typed-evidence discipline:** "this person is an expert in X" is itself a claim that must bind
  congruent public evidence (their profile / a talk / a filing), never asserted from a bought record
  alone — a purchased record is *signal*; the public profile is the source.

## 5. End-to-end flow

1. On a tested thesis, gather the **`call_only`** aspects (primary) and their `ASK_WHO` roles. An
   `under_tested` aspect is eligible ONLY if the vertical explicitly brands it primary-research — the
   default response to under-tested is better retrieval/ingest (corpus-first), NOT jumping to a call.
2. Per (aspect, role), generate a thesis-native expertise query (like `generate_inquiries` does for
   questions) — e.g. "heads of warehouse operations at mid-market US 3PLs."
3. Discovery job fans out to the `PeopleSearchClient` (Exa; later + PDL), dedupes, ranks by relevance
   × people-authority.
4. Present ranked **expert cards** scoped to the thesis: name · headline · org · why-relevant · public
   profile link · the **questions to ask** (from the aspect targets).
5. User reaches out (LinkedIn link + a drafted outreach message).
6. User pastes the call transcript → Phase 3 ingests it into gated `call`-register evidence → the
   verdict on that aspect moves.

## 6. Phasing (each ships value alone)

- **Phase 0 — Promote what exists (no new API).** A first-class "Who to ask / what to ask" panel on a
  tested thesis, from `people.py` + `ASK_WHO`, plus a drafted-outreach generator and the existing
  LinkedIn-search link. Cheapest, highest-signal; validates the loop before any provider spend.
- **Phase 1 — Exa people discovery.** `PeopleSearchClient` (kernel) + Exa provider; per-aspect
  expertise-query generation; Expert mode UI + ranked cards. **Discovery runs IN-REQUEST** (a fan-out
  of a few ~1–3s Exa searches over the aspects), NOT the heavy `su_job` daemon-thread pattern — that
  machinery is for minute-long ingest, and would be unnecessary complexity here. Escalate to a job only
  if PDL hydration or transcript work later proves slow.
- **Phase 2 — PDL structured validation.** Turn fuzzy hits into a filterable, validated shortlist;
  composite = Exa (reach) + PDL (precision).
- **Phase 3 — Close the loop.** Transcript-ingestion: paste a call transcript → **chunk it** (calls
  run 8–10k words, well past a single LLM context) → **extract atomic, typed claims** (subject, period,
  aspect_key, who-said-it, role) → gate each (`on_subject` is subtle: a call mixes talk of the target
  AND its peers, and "what our customers do" vs "what I'd personally pay") → write `call`-register
  evidence rows. This is NOT "just reuse the synthesis machinery": that machinery assumes third-party
  artifacts, not first-person testimony, so it needs an explicit transcript path. **Verdict semantics
  (must be decided here, not handwaved):** a call stays `stated` and is NEVER auto-`is_controlling`; a
  `call_only` rung moves `unsettleable → primary_research_needed` on the first account (as today), and
  may reach `supported`/`contradicted` only with **≥2 independent accounts** (independence keyed per
  person AND per firm, so three employees of one buyer ≠ three independent accounts). One enthusiastic
  buyer never "proves" willingness-to-pay. This is a deliberate extension of `TechDecisionProfile`, to
  be re-tuned with held-out cases, before Phase 3 ships.
- **Phase 4 (optional).** Real expert-network integration via MCP/services (Third Bridge/Guidepoint
  MCP; Tegus transcripts in AlphaSense) — a partnership track, not a search-API track.

## 7. Guardrails (non-negotiable)

- **No scraping.** Licensed data + public-web semantic search only; never a synthetic-account vendor.
- **Three data classes kept strictly separate**, never blended into one "expert card" blob:
  (a) public-web discovery (Exa), (b) licensed records (PDL), (c) user-provided transcripts. PeopleSearch
  output (a, b) are **ranking/UI features only** — they NEVER become `evidence` rows and never affect a
  rung's verdict. Only class (c), via the gated `/call` path, is evidence.
- **PeopleSearch output stays in its lane:** a provider may not infer thesis-role (buyer/operator/
  advisor) — that's the vertical's job from `ASK_WHO`; and "this person is an expert in X" must bind a
  congruent public source, never be asserted from a bought record alone.
- **DSAR as a concrete mechanism, not a sentence:** a person can be located and purged across (a) the
  PeopleSearch cache, (b) any thesis where surfaced, (c) transcript-derived rows — a single delete-by-
  person path. Store only name/role/company/expertise/public-URL; retention: re-verify or drop
  PeopleSearch hits and Exa/PDL response caches on a fixed clock; US professional data is protected
  (CCPA B2B exemption expired); EU relies on documented legitimate interest.
- **Transcript consent:** the UI makes the user attest they have the right to share the content; no
  recordings of internal meetings or NDA-covered material; calls are private to the thesis owner
  (already enforced: `store.py:263` hides `source_key=="call"` from non-owners) and not used for
  training beyond labeling that thesis's rungs.
- **No booking / no de-facto booking** (no auto-calendar-invites to non-users).
- People-search spend projected + gated like every paid run (credit discipline).
- The standing "a call is `stated`, decisive only for the rung documents can't reach, never laundered
  upward / never auto-`is_controlling`" rule stays.

## 8b. Cite corrections (from the code-grounded verifier)

The spec's file:line claims verified accurate; three cosmetic fixes: the `"No document can settle
this…"` quote is at `attack.py:141` (line 140 is the `call_only` guard); `decision.py:34` is
`switching_feasible`, `:36` is `willingness_to_pay` (§1 named them reversed); and the "web can never
settle a `call_only` rung" rule lives in `verdict_for` (`attack.py:140`), while `_enough`
(`decision.py:143`) backs the related "a market signal never carries an aspect."

## 8. Open forks (want a decision before building)

1. **Evidence storage:** owner-only `ts_evidence` rows (current `/call` path, private) vs. also
   ingesting transcripts into the `rs_block` corpus (retrievable, but blurs public/private). *Lean
   owner-only.*
2. **Second provider:** PDL (clean structured filters, breadth) vs Coresignal (free search, career
   depth). *Lean PDL for MVP.*
3. **Scope:** always thesis-scoped vs. also a standalone searchable directory. *Lean thesis-scoped
   first (the differentiator; a directory is the commodity).*
4. **Booking:** confirm out of MVP scope. *Lean yes.*

## 9. Litmus (kernel/vertical split)

Could a LEGAL or BIOTECH vertical reuse the `PeopleSearchClient` port by supplying its own
people-relevance profile (which roles matter, how to phrase the query, how to rank credibility),
kernel untouched? If yes, the split is right. The kernel names no "expert," "buyer," or "LinkedIn."

## 10. Panel review & decisions (2026-09-13)

Reviewed by Codex (gpt-5.1) + Gemini (gemini-3-pro-preview) + a code-grounded verifier.
**Both models: build with changes. Verifier: spec is accurate.** Decisions:

- **Reframe (close the `call_only` loop):** ACCEPTED — both called it the right, differentiated framing.
- **Kernel/vertical split:** ACCEPTED — `PeopleSearchClient` mirrors `WebSearchClient` cleanly, no
  domain-noun leak; people-authority belongs beside `TechAuthorityPolicy`.
- **Forks — DECIDED:** #1 owner-only `ts_evidence` (corpus ingest would need per-owner partitioning +
  new congruence bugs + DSAR sprawl); #2 PDL for MVP (attributes stay ranking-only); #3 thesis-scoped,
  enforced by API shape (primary entry `/thesis/{id}/experts?aspect_key=…`, no freeform directory);
  #4 no booking.
- **Scope discipline (Codex):** ADOPTED — primary = `call_only`; under-tested is not a default trigger
  (§1/§5 tightened). Protects corpus-first.
- **Phase 1 in-request, not `su_job` (Gemini):** ADOPTED (§6).
- **Phase 3 verdict semantics + chunking (Codex/Gemini, the biggest risk):** ADOPTED — no handwave;
  independence per person AND firm; ≥2 accounts to move past `primary_research_needed`; never
  controlling; explicit chunk→extract→gate pass (§6).
- **Legal hardening (both):** ADOPTED — three-data-class separation, DSAR mechanism, transcript
  consent, retention (§7).
- **Phase 0 branding (Codex):** ADOPTED — label "Who to ask / what to ask"; reserve "Expert Mode" for
  Phase 1; instrument non-empty rate + click-through as the Phase-1 go/no-go.
- **Identity unification (Gemini):** NOTED for Phase 1 — PeopleSearch candidates (LinkedIn URL/name)
  stay a separate lane from `people.py` strong-key identities; never name-merged.

**Next:** build Phase 0 (no new provider).
