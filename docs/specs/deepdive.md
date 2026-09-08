# DeepDive — a diligence pre-flight on one resolved company

Status: **design agreed, not yet built** (2026-09-08). Panel-reviewed (Gemini 3 Pro + a
code-grounded inventory subagent; Codex unavailable — see `docs/specs/voices-panel.md`).

## 1. What the owner asked for

> "Can we build a DeepDive mode where someone gives in a startup name, or some company name, and we
> agentically get all data about it from all possible places and add it to a DeepDived companies
> corpus. This goes above and beyond what we are collecting for startups. This looks at company's
> foundations, performance in sector, leaders, strategy, revenue, profit numbers, and all key people
> in the company, potential org data, and company's customers, and overall corporate strategy as
> understood by investors, and publicly available data."

## 2. What already exists (measured, not assumed)

A code-grounded inventory of the repo found that most of the *mechanics* exist and are unwired:

| Piece | Where | State |
|---|---|---|
| Bounded per-company web read | `packages/kernel/eigen_kernel/research/deep_company.py` → `retrieve_deep_company(...)` | Works. Resolves the company's own domain (with a `_REFERENCE_DOMAINS` blocklist so wikipedia/crunchbase/LinkedIn are never mistaken for the company's site), fans out ≤8 queries / ≤18 pages / 25s, returns `list[BlockHit]` tagged `web:deep`. Fires **only** opportunistically inside `/research` when an LLM contract happens to say `subject_kind=="specific_entity"`. |
| The domain vocabulary for that read | `packages/vertical_tech/.../company_reader.py` | 6 internal facets (founders_team, product, technology, pricing, customers, blog_changelog) + 2 external (funding_investors_valuation, competitors_traction) + an `attribution_addendum` forcing "self-reported" labelling of company-site ARR/valuation/customer claims. |
| Verbatim span gate | `research/provenance.py` `BlockSpanVerifier.verify()`; applied in `react.py` `_apply_answer` | Works. Every claim is either a `VerifiedClaim` or a `RejectedClaim`. |
| Web-hit screens | `research/web_quality.py:screen_open_web_hits`, `research/web_liveness.py:drop_dead_urls` | Applied to `web:deep` legs. |
| Single-company report composer | `apps/api/diligence_route.py:answer_diligence(...)` | Works, but reads **only already-materialized graph claims — it does zero retrieval.** |
| Per-company facts | `apps/api/startups/store.py:company(cid)` | Returns facts + financing + founders + filings, each with provenance/source_url/quote. |
| Claim graph | `apps/api/claimgraph.py` (`rs_entity`, `rs_claim`, `rs_claim_evidence`) | Bitemporal, per-entity, evidence carries a span-verified quote + authority tier. |
| USD projection + refusal pattern | `apps/api/startups/pipeline.py` (`project_*_cost`), `routes.py` pre-gate | Copy this verbatim. |

**Genuinely missing:** (1) a company-scoped *endpoint* / job; (2) any wiring from the 28 connectors
(patents, papers, grants, GitHub, HN, Companies House) to a *named* company — they are ingest-time
and topic-keyed; (3) a dossier artifact with versioning; (4) a USD gate on the answer path.

So DeepDive is **mostly wiring, not new machinery**. `deep_company` retrieves; `answer_diligence`
composes; nothing connects them, and nothing persists the result.

## 3. What the panel killed, and why we agree

The review's central point: a deep crawl of a company's own domain is *full of other companies*.
Partner pages, competitor comparison pages, customer case studies. An unbounded extraction loop
reading Anthropic's blog will find a customer quote — "we saw a 50% revenue increase" — and attribute
that 50% to Anthropic. Provenance passes (the quote is real, on their domain); congruence fails.
This is exactly the failure class the **Evidence Is Typed** directive exists to make impossible.

Three requested sections are cut in v1:

- **"Corporate strategy as investors understand it"** — this is sentiment/opinion synthesis presented
  as a company fact. It violates *Sentiment is a SIGNAL*. If it returns, it returns as a clearly
  labelled market-signal register, never as a dossier section.
- **"Performance in sector"** — metrics across startups are incongruent: one company's "ARR" is
  another's GMV or bookings. Comparing undefined numbers is a congruence violation by construction.
- **"Org data" / org structure** — a trap. Startup titles are inflated, fluid and non-hierarchical;
  a synthesized reporting line from an About page is a confident hallucination. Replaced by
  **Key Personnel & Hiring Intent**: named executives from filings/official pages plus a summary of
  *active* job postings — "10 open GTM roles vs 10 open ML roles" is a verifiable fact that signals
  strategy better than a guessed org chart, and we already have the ATS board data.

**Revenue/profit for a private company** is either a legally mandated filing (SEC, UK Companies House)
or it is PR. So the dossier never shows a "Revenue" integer for a private company. It shows a
**Stated Milestones ledger**: what the company or a named executive publicly claimed, with date,
speaker and source — "CEO claimed $10M ARR, TechCrunch, Oct 2023". We refuse to display third-party
algorithmic estimates (PitchBook/Dealroom-style), headcount-extrapolated ranges, or any number
synthesized forward from a historical growth percentage.

## 4. The v1 shape — "diligence pre-flight"

A DeepDive is a **long-running job over one resolved company**, not a chat turn. It produces a
**versioned dossier**: an evidence ledger, not a form.

### 4.1 Resolution first
A name is not a company. Resolve to a canonical id (registrable domain, and CIK where one exists)
before spending anything. On an ambiguous name, **refuse and return the candidates** rather than
researching the wrong company. Reuses `su_company` + aliases; the `_REFERENCE_DOMAINS` blocklist
already prevents stamping a press page as the company's own site.

### 4.2 Collection, cheapest and most authoritative first
1. **What we already hold** — `store.company(cid)` facts/financing/founders/filings, crawled `su_page`
   text, corpus blocks facet-matched to the company, Voices moments bound to it. Costs nothing.
2. **Keyless public sources by identifier** — EDGAR (full filings, not just Form D), Wikidata,
   Wikipedia, USPTO, OpenAlex/arXiv, GitHub, NSF/NIH, Companies House (UK numbers are *real* revenue),
   HN. These connectors exist and are currently never invoked for a named company.
3. **Deeper own-site crawl** than the 6-page startup crawl: about, team, customers, pricing, blog, press.
4. **Web leg** (`retrieve_deep_company`) last, for what only news/analysis carries.

### 4.3 Sections (dynamically mounted — a section with zero claims does not render)
- **Foundations** — founded, incorporation, founders, funding history. Filings first.
- **Product & Pricing** — verbatim from the current site.
- **Key Personnel & Hiring Intent** — named execs from filings/official pages; open-role composition.
- **Named Customers** — only where explicitly named, with the page that names them.
- **Stated Milestones** — the claims ledger described above; speaker + date + source, always in the
  stated-intent register.
- **Filed Financials** — only where a filing exists (10-K/S-1, Companies House). Absent otherwise.

### 4.4 The two new gates

- **`SubjectBoundaryGate`** — before a claim is admitted, its sentence subject must bind to the
  resolved canonical entity, not a third party named on the entity's domain. This is the customer-quote
  fix. Held-out eval case: a case-study page where the *customer's* metric is the most quotable number.
- **`MetricDefinitionGate`** — a numeric claim must carry an explicit unit and definition from the
  source text. "Growth is up 300%" fails and is discarded; "$10M annual recurring revenue" passes.

Both fail-safe to abstain. Per **Evidence Is Typed**, each needs a held-out case *designed to pass the
span gate while being wrong*: (a) wrong-company attribution from a case study, (b) an undefined
percentage, (c) a roadmap promise read as a shipped fact, (d) a stale filing read as current.

### 4.5 The Manifest of Absence
Every dossier carries an **Attempted Sources** panel: where the agent looked and found nothing —
"USPTO: 0 patents", "SEC EDGAR: 0 filings", "Companies House: not a UK entity". In diligence a
verified negative is as valuable as a fact: a company claiming proprietary technology with zero
patents is a finding. It is also what keeps a half-empty dossier from reading as a broken product.

### 4.6 Cost
A projection per dive, a `max_usd` gate and a hard cap on web calls, following
`pipeline.py:project_*_cost` and the `routes.py` pre-gate that refuses before spending. A repeat
request for the same company returns the stored dossier with its date and offers a refresh —
dossiers are cached and versioned, never silently recomputed.

## 5. Storage

There is no report/dossier table today. The closest precedents are `su_map`/`su_map_revision`
(a versioned saved *search*) and `eigen_research_session` (`SessionStore.save(kind=..., extra=...)`,
already used by the diligence route). v1 adds `su_dossier` + `su_dossier_revision` mirroring the map
tables: company_id, version, sections jsonb, attempted jsonb, projection/spend, share_token — so
DeepDives get the same permanent shareable links as Startup and Voices searches.

## 6. Build order

1. Resolution + refusal on ambiguity (free; testable with no spend).
2. Assembly from what we already hold + keyless sources — a dossier with zero LLM cost.
3. The two gates, with their held-out eval cases, **before** any extraction lands.
4. Extraction over own-site pages, validated on 1–2 companies before any batch.
5. The web leg last, behind the USD gate.
6. UI: dynamic sections, Attempted Sources panel, share link.

Steps 1–2 are worth shipping alone: for a company we already hold, a dossier assembled from stored
facts, filings and crawled pages costs nothing and is already more than Startup Search shows.
