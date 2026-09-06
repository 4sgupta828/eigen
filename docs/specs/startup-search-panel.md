# Startup Search — panel record (2026-09-05)

Raw reviews of docs/specs/startup-search.md v1, verbatim. The synthesis and the resulting changes are in startup-search.md §0.1.

## Codex (GPT-5.x, codex exec)

As a panel reviewer: I would not build this v1 as written. The core shape is promising, but the spec overstates what public sources can ground and underprices the operational/entity-resolution work. The highest-risk issue is false precision: the UI invites VC-style hard filters on facets that will mostly be unknown, stale, inferred, or source-biased.

**Top 5 Changes**
1. Keep facets as a projection, but stop making every source pass through the same LLM claim extractor. Structured sources should emit typed claims directly, then project from claims. No direct facet envelope, but also no unnecessary 3-gate LLM path for YC/Form D/portfolio tables.

2. Remove inferred Form D stage from default `must` behavior. Stage musts should use stated round only; Form D amount-derived stage should be a separate “financing scale inferred” facet. Amount sold is not a round, not total raised, and not reliably comparable.

3. Make ARR/revenue a weak, override-only filter. Public ARR coverage will be tiny and biased toward self-promotion. Form D `revenue_range` is not ARR. Treat `arr`, `revenue_range`, `gmv`, `bookings`, and “run-rate” as separate facets or claims.

4. Change the corpus plan from “aggressively crawl everything” to “measure precision and coverage first.” Tranche 0 should report attach precision, coverage by facet, duplication, crawl failure rate, and cost per accepted grounded facet, not just cost per company.

5. Add SBIR/STTR and federal award/procurement data before broad funding news. For deep tech, SBIR.gov, USAspending, NSF awards, NIH RePORTER, NASA/DoD/DOE award feeds are higher-signal public sources than generic news for non-dilutive funding, government pull, and technical category.

**Architecture**
The projection call in [startup-search.md](/Users/sgupta/eigen/docs/specs/startup-search.md:108) is directionally right. A second direct facet envelope would recreate the exact divergence Eigen’s claim graph is meant to prevent: cards, diligence pages, and search counts would disagree.

But the spec is too absolute. “Projection is free” is contradicted by LLM canonicalization during projection for `tech_area` [startup-search.md](/Users/sgupta/eigen/docs/specs/startup-search.md:172). Projection should be deterministic. If model canonicalization is needed, emit a claim or annotation upstream with versioned evidence and cache it.

The cheaper path should be source-specific claim writers, not direct facet rows: YC JSON → claims, Form D XML → claims, portfolio table → claims. Then reserve LLM extraction/entailment for messy company pages and unstructured news.

**Schema Problems**
`stage` is overloaded. Public/acquired do not belong in the same ordinal as seed/Series A; those are statuses. Seed extension, SAFE, pre-seed, strategic round, grant-funded, bootstrapped, and venture studio incubation do not fit a clean ordinal.

`total_raised` from summing distinct rounds is fragile. Press + Form D double-counting, amended filings, partial closes, debt, SAFEs, and undisclosed extensions will break this. You need `financing_event`, `amount_sold`, `announced_round_amount`, and `total_disclosed_funding` as separate concepts.

`investor` needs role/date/source: lead, participant, prior investor, current backer, accelerator, studio, grantor. A fund portfolio page grounds “portfolio affiliation,” not necessarily round participation or current backing.

`accelerator` should not be fed through `has_investor`. SPC, HF0, AI Fund, YC, studio programs, fellowships, and funds are different relationships. Use `affiliated_with_program` / `participated_in_program`.

`open_source=no`, `patents=0`, and `hiring=0` are not grounded facts from absence unless the source is exhaustive. Render as “none found” or unknown. Same for “not backed by X.”

Missing high-value dimensions: non-dilutive funding, government contracts, regulatory status, product maturity, deployment status, named customer evidence, university/spinout affiliation, founder commercial/operator background, founder domain expertise, lead investor, round recency, currently hiring by function, pricing/ACV signal, buyer persona, and “evidence strength.”

**Corpus**
Form D is useful but not a population backbone. Many seed/A companies do file under Reg D, but coverage is incomplete, delayed, legally named, amendment-heavy, and missing domain identifiers. “Amount sold” is especially dangerous as stage evidence.

The founders-vs-officers problem is correctly called out, but it is bigger than `officer_count`: Form D related persons include executives, directors, promoters, and legal/finance people. They should never seed founder identity.

Portfolio pages are biased and stale. They often list selected investments, exited companies, old logos, stealth shells, or merged/acquired brands. Treat them as affiliation evidence, not round evidence.

Domain-based entity resolution will fail on rebrands, dead domains, acquired redirects, parent/legal issuer names, DBA/product names, `.ai`/`.com` variants, subsidiaries, and reused names. Store legal issuer identity separately from product/domain identity.

Company-site crawling is acceptable only with a written policy: robots.txt, sitemap-first discovery, identified UA/contact, no login/paywall/anti-bot bypass, per-host and global throttles, ToS respect, removal process, PII minimization for founder bios, and JS-rendering fallback only where allowed.

**Eval Traps**
Strong traps: namesake Form D, officer ≠ founder, logo wall ≠ investor, wrong subject, leaky pool.

Weak traps: stale round, because a Form D amount should not resolve a press-stated stage conflict; self-stated ARR, because inclusion under `must` is the problematic behavior; SPV rejection, because regexes will miss many holding/issuer shells.

Missing traps: amended Form D double-counting, legal issuer vs product brand, rebrand/domain redirect, acquired company with live old site, YC stale status, “annualized run-rate” misread as ARR, GMV/bookings misread as revenue, accelerator membership vs investment, founder/advisor/founding engineer confusion, absence treated as no, and compile failures on negatives like “not YC,” “no crypto,” “under the radar,” or “similar to Anduril but seed.”

**Spend**
The cost model is not credible yet. At 20k companies × 15 blocks, even $0.004 per block-pair is about $1.2k before retries, news/search APIs, resolver calls, JS fetches, failed crawls, canonicalization, storage, and reprocessing. If batching changes that, the unit is unclear. Tranche 0 must measure cost per accepted facet and cost per correctly attached funding claim.

**UX**
Must/prefer/avoid is useful for expert narrowing, but a VC will not primarily think in a centered stage rail. They will type thesis briefs: “seed infra companies selling to banks, founded by ex-Stripe/Databricks, raised less than $10M, not YC, strong OSS traction, hiring GTM, last round 12-24 months ago.” Stage should be a range/filter, not the organizing center. Cards should foreground thesis match, evidence strength, last financing, traction proof, intro path/investor overlap, and gaps.

**Open Questions**
Q1: Use projection from claims. Reason: one truth store matters; reduce cost with structured claim emitters, not direct facet envelopes.

Q2: Stated-round only for stage musts. Reason: Form D amount is not stage; show inferred financing scale separately.

Q3: Do not assume enough Form D coverage. Reason: measure on YC/known AI cohorts first; backfill to 2019 only after attach precision is proven.

Q4: Crawling is acceptable with stricter policy. Reason: public pages are fair input, but robots, ToS, UA/contact, no bypass, and PII handling must be explicit.

Q5: Ship founder names/count first; add high-precision tags only. Reason: “technical” and “repeat” are inconsistently public without LinkedIn.

Q6: Downgrade ARR to prefer by default with override. Reason: low coverage plus self-reporting makes hard ARR filters misleading.

Q7: Yes: repeated roster risks are facet vocabulary collisions, leaky semantic retrieval, rail overload, and count latency. Reason: these will show up faster with open startup facets and sparse evidence.

## Gemini (gemini-3-pro-preview)

Here is the design panel critique of the `startup-search.md` spec.

### Top 5 Changes to Make Before Building

1.  **Drop `arr` as a `must` filter and rely on proxies.** Startups do not post ARR on their websites unless it is a vanity milestone, and 99% of Form D filings check "Decline to Disclose" for revenue. Coverage will be <5%, meaning an `arr` MUST will artificially zero out valid candidates and make the platform look broken.
2.  **Fix the Entity Resolution (ER) blindspot for Form D.** Resolving a Form D (which only has Legal Name + State) to a website domain using exact normalized name matching will fail catastrophically (e.g., falsely merging "Apollo Inc" the AI startup with "Apollo Inc" the consulting firm). You must incorporate state registry data (e.g., Delaware Division of Corporations via OpenCorporates) to bridge the legal name to the operating entity, or tighten `llm_merge` to aggressively reject low-signal name matches.
3.  **Account for SPA/JS and ATS iframes in the crawler.** A naïve `HttpStrategy` GET on `/careers` will miss Greenhouse, Lever, and Workable widgets because they load via JavaScript or iframes. This will result in massive false negatives for your `hiring` signal. The crawler needs a headless JS execution step or specific ATS-URL resolution.
4.  **Decouple "Inferred Stage" from "Stated Stage" in the contract.** Do not allow the compiler to default a `must` on stage to include `inferred_amount`. A $15M round is a Seed in AI-infra but a Series B in consumer SaaS. Inference belongs in `prefer`, never in a deterministic `must`.
5.  **Use Content-Hashing, not ETags, for the refresh crawler.** The spend projection assumes ETag caching will save money on quarterly refreshes. Modern startup sites (Vercel, Next.js, Webflow) frequently bust ETags on every deployment even when content is unchanged. You must gate re-extraction by hashing the *rendered markdown text*, or your refresh costs will blow out.

---

### 1. Architecture: Projection vs. Envelope
**The Call:** You chose projection from the claim graph over a cheaper, parallel extraction envelope.
**Critique:** This is absolutely the right call for a diligence product. If a VC sees "Series A" on the search rail, but the evidence drawer says "Seed" because an envelope extractor ran a different prompt than the main graph extractor, user trust goes to zero.
However, projection shifts the brittleness to `startup_facets.py:PROJECTION`. You are coupling continuous/variable data (amounts, dates) to ordinal schemas (stages, bands). The bitemporal nature of `rs_claim` means the projector must be purely functional and idempotent. Ensure the projector natively understands currency conversion and convertible note double-counting (where a SAFE converts into a priced round), or your projected `total_raised` will be double reality.

### 2. The Schema
*   **Missing dimensions:** VCs filter on `months_since_last_round` (a proxy for runway/desperation) and `lead_investor` (which is often distinct from the general `investor` wall and heavily signals quality). Add these.
*   **Wrong types:** `total_raised` as a numeric band is fine, but non-USD rounds cannot simply be "kept as display only, no band." VCs look at European startups (GBP/EUR). You need a basic, dated FX table at projection time to assign them to a USD band, otherwise they fall out of `must` filters.
*   **Founder vs. Officer:** You rightly distinguish founders from Form D officers. But expecting the LLM to reliably type founders (`technical`, `ex_big_tech`) solely from marketing pages and OpenAlex without LinkedIn is a trap. Team pages rarely use standard phrasing for this, leading to sparse, low-confidence tags.

### 3. The Corpus Plan
*   **Coverage Realism:** Form D coverage is excellent for priced rounds, but weak for pre-seed/seed where SAFEs dominate (founders often batch-file or skip Form D entirely, claiming Section 4(a)(2) exemptions).
*   **Entity Resolution (ER):** As noted in the Top 5, Name + State is insufficient. SPV filtering via regex (`SPV|Fund|LP|Holdings`) will miss things like "Acme 2024 Investment LLC". The LLM step must look at the `industry_group` on the Form D and cross-reference it with the semantic description of the website.
*   **Legal/Politeness:** 1 request per 2 seconds is polite, but Cloudflare bot-protection will 403 your scraper on ~30% of startup sites if you don't use high-quality residential proxies or a specialized scraping API.
*   **Missing Leverage Source:** SEC EDGAR CIK numbers. Once you match a company to a Form D once, you have its CIK. The CIK is permanent and guarantees perfect entity resolution for all future filings.

### 4. Eval Traps
*   **Weak Trap:** Trap 7 ("Stale round") assumes Press and Form D will match on amount. They rarely do. Press reports the *total authorized/planned round* (including debt facilities). Form D reports *amount sold to date*. The trap needs to evaluate the definition of the money, not just the date.
*   **Missing Traps:**
    *   *The "Decline to Disclose" Trap:* The model must not hallucinate a revenue of $0 or place a company in the `<100k` band if the Form D revenue box is "Decline to Disclose".
    *   *The "ATS Widget" Trap:* `/careers` page has 0 roles in HTML, but 10 roles in a Greenhouse iframe. Eval must ensure this isn't falsely recorded as 0.
    *   *The "Holding Company" Trap:* Form D name is "Acme Holdings LLC" but the startup is "Acme.ai". Ensure ER handles the exact match failure correctly.

### 5. Spend/Cost Realism
Your LLM compute estimates ($300–$500 for 10k companies) are accurate *if* your 10/call extraction batching holds at ~2k tokens with a cheap model (working out to ~$0.016 per company).
However, your compute cost for *fetching* is ignored. Processing 20k domains × 6 pages requires handling bot-challenges, infinite scroll / JS rendering (for team and career pages), and managing timeouts. The engineering and proxy costs for the `company_site` connector will vastly outstrip the LLM extraction costs.

### 6. UX
Centering on `stage` is exactly how VCs build lists. The rail UI ported from `roster` is excellent.
However, a VC will not type your example prompt ("ARR over $1M"). VCs use search to find proxies for momentum that aren't on PitchBook yet. A realistic prompt is: *"AI agents, raised >$3M over 18 months ago, hiring GTM/sales, founders from Google/Meta."*
Because of this, the `unknown` chip will dominate your UI. You need to ensure the "staged edits" (Apply) mechanism makes it painfully obvious to the user that adding a `must` on a low-coverage key (like ARR or Founder Type) will decimate their result set before they click apply.

---

### 7. Open Questions (Section 10)

**Q1. Projection-from-claims vs envelope extraction?**
*Recommendation:* Stick with projection-from-claims.
*Reason:* In a diligence tool, conflicting facts between the search rail and the bitemporal evidence drawer will instantly destroy user trust.

**Q2. Stage: `basis`-tagged inference acceptable in a MUST?**
*Recommendation:* Stated-round only for MUST, with inferred shown as a separate selectable chip.
*Reason:* Mapping funding amounts to stage is too variable across sectors (e.g., $15M is Seed in AI, but Series B in consumer SaaS) to be a deterministic filter.

**Q3. Form D coverage: back-filling to 2019 worth 30 zips?**
*Recommendation:* Yes, backfill completely.
*Reason:* Form D is the highest-authority financial ground truth available without paid licensing; it is the necessary anchor for your entire claim graph.

**Q4. Company-site crawling: missing anything on legal/politeness?**
*Recommendation:* You are missing a JS-rendering step and ATS-iframe resolution.
*Reason:* A naive HTTP GET will miss Greenhouse/Lever job postings and React-rendered content, silently failing your `hiring` and `open_source` facets.

**Q5. Founder typing from public text without LinkedIn?**
*Recommendation:* Ship `founder_count` + names only for v1.
*Reason:* Attempting to extract detailed backgrounds (`ex_big_tech`) from marketing pages will yield unacceptable recall and make the platform look broken.

**Q6. Is `arr` as a first-class must honest enough?**
*Recommendation:* The compiler MUST downgrade it to a `prefer` by default.
*Reason:* Startups rarely self-report ARR, and 99% of Form Ds check "Decline to Disclose," making a MUST filter a guaranteed empty state.

**Q7. Anything roster learned the hard way about this architecture?**
*Recommendation:* Watch out for vocabulary collisions and hallucinations in the semantic leg.
*Reason:* Mapping arbitrary LLM text to a closed set (e.g., `tech_area`) is exactly where the "leaky pool" invariant silently breaks if the taxonomy drifts.

## Code-grounded subagent (file:line verification)

Verified read-only against /Users/sgupta/eigen and /Users/sgupta/roster; the only execution was pytest on the ported kernel tests and the two guardrail scripts.

1. CONFIRMED — roster `facets/` imports only stdlib + siblings; no banned noun; rename-only port: 22 tests pass under eigen's venv, both guardrails green on the copy (scratch copy kept).
2. PARTIAL — the module is 772 lines (schema/contract/evaluate/store/tests); 1,029 includes `intake.py` + `test_intake.py`, whose test fixtures carry people-search vocabulary. Decide explicitly whether intake comes along.
3. WRONG — "guardrails green": eigen's own kernel invariant is RED today (`research/web_coverage.py:4,115,116`, `react.py:116,118,1459,1482,2424`, `test_contract_directive.py:41,44`, `deep_company.py:41,43`, `test_prior_verify.py:147`; `conformance/test_kernel_invariant.py::test_kernel_names_no_domain_noun` fails). Also pre-existing medical vocabulary on `VerticalManifest` (`contract/manifest.py:64,70,103`) and in `people/store.py:1-12`.
4. PARTIAL — no `facet_schema` manifest field; roster mounts its schema on the existing `extraction_schema` slot (eigen `contract/manifest.py:49`). Reuse it.
5. CONFIRMED — claim graph is 8 tables (`claimgraph.py:127-283`), bitemporal (`valid_from/valid_to`, `observed_at`, `superseded_at`, `retracted_at`), quote + `authority_tier` + `evidence_kind` on `rs_claim_evidence`, resolution table with conflict set. No embedding on `rs_entity` (it has `facets jsonb` and `primary_domain`).
6. WRONG — "18 predicates": 6 slice-1 + 14 diligence = 20; there is already a `revenue` predicate designed for ARR. Use it.
7. CONFIRMED — `stage` deliberately not a predicate (`claim_predicates.py:103-106`), proxies named there differ from the spec's.
8. WRONG — the extractor emits text objects only (`claim_extract.py:78-80, 203-209`): no amount/currency/period, no intent-vs-realized modality anywhere. Typed values + modality are a new output contract and a schema change.
9. WRONG — no block-level extraction cache in `claim_extract_job.py` (`_select_blocks :188-224` re-selects everything); idempotence is claim-id only; the LLM call is re-spent.
10. WRONG — cost model: the claim extractor is 1 extract + 1 entail call PER BLOCK (`claim_extract_job.py:124-127`), default $0.01/call → ≈ $0.30 per 15-block company, ~8× the spec's figure.
11. CONFIRMED — `resolve_entity` methods `strong_id | exact_norm | new | llm_merge | unresolved | mention` (`canonicalize.py:129`); strong-id schemes are opaque caller-supplied names; `multisource_enrich.py` rejects namesake issuers before extraction.
12. PARTIAL — the YC extraction job mints `yc:<slug>` subject ids (`claim_extract_job.py:331`); nothing in prod code mints `domain:` ids (only tests). Prod's 15 `domain:` companies came from outside the connectors. Two id spaces must be reconciled.
13. CONFIRMED — YC connector fetches founders + year_founded from the detail page (`yc.py:115-140`).
14. PARTIAL — Form D parsing covers 9 offering fields (`edgar.py:32-58`), NOT related persons/roles, revenue range, entity type, state; per-issuer full-text search, not bulk zips.
15. CONFIRMED — no company-website crawler connector; the answer-time deep reader (`research/deep_company.py` + vertical `company_reader.py`, with an "self-reported" `ATTRIBUTION_ADDENDUM :14-21`) is the only site reader.
16. WRONG — `HttpStrategy` (`_http.py`, 60 lines) has retry/backoff + UA only: no per-host pacing, robots, byte cap, ETag.
17. CONFIRMED — GDELT (headline metadata, ≤1 req/5 s), PatentsView (granted only; empty without `EIGEN_PATENTSVIEW_KEY`), GitHub, Companies House, Wikidata, OpenAlex, HuggingFace, NSF, NIH RePORTER connectors exist; Exa/Brave providers exist.
18. CONFIRMED — mode switch pattern (`index.html:1379-1383`, `:553-567`); `setMode :3770` hard-gates to panel|triage|qa → a third value is a code edit + hash router (`:6020-6036`).
19. CONFIRMED — the rail is ~120 lines (`roster index.html:7481-7580`, CSS `:658-677`); ~30 lines depend on roster-only globals (`JOBS_RENDERS`, `PEOPLE_RENDERS`, `authHeaders`, `loadMapView`, `gotoPeoplePage`).
20. WRONG — the evidence drawer is person-specific (`:9137-9425`, ~290 lines: LinkedIn resolve, OpenAlex footprint, review state); only the `.ev-inline-box` skeleton (~10 lines) + CSS (~40) port. Cards are person-shaped too.
21. CONFIRMED — roster's SQL store applies musts in SQL on every leg (`facet_store.py:86-127`, used at :186/:212/:232); `project()` DELETEs then re-inserts (a rebuildable read model). ~240 of 393 lines port as-is.
22. CONFIRMED — no `self_stated` evidence kind; an official company page classifies `technical_signal` (rank 2); `is_controlling` is exactly `primary_filing`.

Porting estimate (steps 1–3): kernel 772 lines verbatim + ≤15 wiring; schema/projector/store/route ≈ 1,100–1,400 lines (projector must parse money/round/period from text objects unless the extractor is typed first); UI ≈ 550–750 lines (rail ported, cards + drawer body new).
