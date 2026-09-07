# Startup Search — a third mode: typed facets over a grounded startup population, rendered as cards

Status: spec **v2 (2026-09-05), panel-reviewed** (Codex, Gemini 3 Pro, code-grounded subagent — raw reviews in
`startup-search-panel.md`). Owner ask: add a Startup Search mode (next to Q&A and Expert Panel) in the model of
`~/roster`'s people search — results are CARDS, the brief carries MUST-HAVE facets (funding > Y, tech area,
ARR > X, investors X/Y/Z, number and type of founders, accelerator affiliation such as YC / SPC / AI Fund, …),
results CENTER on stage. Aggressively build the startup corpus from public sources and extract details from each
startup's own public site. Borrow roster's UI.

Bound by CLAUDE.md: kernel domain-free; corpus-first; evidence is typed (subject + kind congruence, never "close
enough"); sentiment is a signal, never a fact and never `is_controlling`; intent ≠ realized fact; API credits
projected + gated per tranche; mobile-friendly; every gate has a held-out trap designed to pass while wrong.

---

## 0. What roster proved, what eigen already has, and what the panel changed

### 0.0 Roster's mechanism (verified portable)

Roster built ONE mechanism for every search-like surface: `evaluate(contract) over a typed entity set → rows,
counts, coverage`. Its kernel module `roster_kernel/facets/` (schema · contract · evaluate · store + tests, 772
lines) has five structural facet TYPES, `unknown` as a first-class value, a contract grammar (`must` filters,
`prefer` / `avoid` rank, `center` = ordinal distance, `rank_by`), a deterministic evaluator (no model call) and a
store protocol with an in-memory reference store. **Verified by the code-grounded reviewer: a rename-only copy
(`roster_kernel` → `eigen_kernel`) passes its 22 tests under eigen's venv and both eigen guardrail scripts on the
copy.** The rail UI (~120 lines JS + CSS; tap cycles ● must → ▲ prefer → ▼ avoid, staged Apply, `unknown` chip,
folds under 560 px) ports with ~30 lines rewritten. Roster's SQL store applies musts in SQL on every leg; ~240 of
its 393 lines port as-is.

### 0.1 What eigen has that roster does not — and the facts the panel corrected

Eigen has a GROUNDED BITEMPORAL CLAIM GRAPH (`apps/api/claimgraph.py`: 8 tables — `rs_entity`, `rs_entity_alias`,
`rs_claim`, `rs_claim_evidence`, `rs_claim_resolution`, `rs_predicate`, `rs_extraction_run`, `rs_mention`), 20
registered tech predicates (6 landscape + 14 diligence, incl. `has_founder`, `has_investor`, `raised_funding`,
`revenue`, `headcount`, `company_location`, `company_status`, `business_model`, `traction_metric`,
`customer_evidence`), a 3-gate extractor, strong-id entity resolution with namesake rejection, a YC connector with
founders, an EDGAR connector with partial Form D XML parsing, a per-company entity page and a diligence route.

Corrections from the panel that this v2 applies (each changed the design, not just the wording):
- **Cost model was ~8× too low.** The claim extractor is ONE extract + ONE entail call PER BLOCK
  (`claim_extract_job.py:124-127`), and there is NO block-level extraction cache — re-running re-spends. → §2:
  structured sources (YC, Form D, portfolio tables) write claims DIRECTLY with no model call; the LLM path is
  reserved for company pages and news; a `(block_sha, predicate_set_version, model, prompt_version)` cache is a
  step-2 deliverable; §6 re-derived.
- **The extractor emits text only** — no amount/currency/period, no intent-vs-realized modality anywhere. →
  §5 defines a NEW typed output contract + a numeric column; "the prompt already distinguishes intent" was false.
- **Two id spaces.** The YC job mints `yc:<slug>` subjects; nothing in prod code mints `domain:` (prod's 15
  `domain:` companies came from outside the connectors). → §4.1 defines one identity model with a minting path.
- **Form D parsing covers 9 offering fields**, not related persons / revenue range / entity type / state, and is
  per-issuer FTS, not bulk; `HttpStrategy` has retry + UA only (no pacing, robots, byte cap, ETag). → §4 budgets
  these as new code.
- **Guardrails are already red**: eigen's kernel invariant fails today on 13 pre-existing hits (`research/
  web_coverage.py`, `react.py`, `deep_company.py`, two tests) and the manifest still carries medical format
  fields. → step 1's exit criterion is "no NEW violations" and the pre-existing red is filed as a tracked bug (§9).
- **Stage must be stated-round only in a must** (both external reviewers): "$15M is a seed in AI infra and a
  Series B in consumer SaaS". → §3: inferred financing scale is its OWN facet; public/acquired move to `status`.
- **ARR must default to prefer** (both): public ARR coverage will be < 5–10% and self-selected; Form D revenue is
  a RANGE, mostly "Decline to Disclose", and is not ARR. → §3: `arr` ≠ `revenue_range`; the compiler downgrades a
  must on ARR to a prefer with a one-tap override.
- **Founder typing v1 = count + names only** (both): `technical / ex_big_tech / repeat` are not reliably public
  without LinkedIn. → §3, tranche 3 ships typing only for tags that reach measured precision.
- **Accelerator ≠ investor; portfolio page ≠ round participation** (Codex). → `participated_in_program` predicate;
  `investor` rows carry a `role`.
- **Absence is not "no"** (Codex): `open_source=no`, `patents=0`, `hiring=0` are "none found", never facts.
- **Crawler realism** (Gemini): JS-rendered team/careers pages, ATS iframes, Cloudflare 403s (~30% of sites),
  ETags busted on every deploy. → §4.4: ATS board JSON APIs instead of headless rendering; content-hash gating;
  fetch failure recorded as `fetch_failed`, never as absence.
- **Entity resolution for Form D by name + state is not enough** (both): CIK becomes a permanent strong id after
  the first confirmed match; legal issuer identity is stored separately from product/domain identity.
- **Missing high-leverage sources** (Codex): SBIR/STTR, NSF, NIH RePORTER, USAspending — non-dilutive funding and
  government pull for deep tech; eigen already has `nsf` and `nih_reporter` connectors.
- **VCs type thesis briefs, not facet lists** (both): "seed infra selling to banks, founders ex-Stripe, raised
  < $10M, not YC, hiring GTM, last round 12–24 months ago". → §1: stage is a filter AND an optional centre; the
  compiler must handle negatives ("not YC") and time windows; the coverage warning fires BEFORE Apply.

Where the two external reviewers disagreed: **Form D back-fill to 2019.** Gemini: back-fill completely now (it is
the highest-authority financial ground truth). Codex: measure attach precision on a known cohort first. **Call:**
download every quarterly zip now (free, no model call, ~30 files) and ingest the filings as corpus documents;
ATTACH to companies only after tranche 0 reports attach precision ≥ 95% on the YC cohort. Both concerns honoured.

---

## 1. The mode, as the user sees it

A third tab in the shell: **◆ Startups** (`body[data-mode="startups"]`; `setMode` at `index.html:3770` gains a third
legal value; hash router updated). One input box; the user types a thesis brief:

  "seed to series A AI-infra startups selling to banks, ≥ $5M raised, last round 12–24 months ago, founders
   ex-Stripe or ex-Databricks, not YC, hiring GTM, US"

`POST /startups/compile` (one small model call, cached by text hash) turns it into a CONTRACT and a list of NOTES:

```json
{"contract":{"kind":"company","text":"AI infrastructure sold to banks",
  "must":{"tech_area":["ai_infra"],"customer":["enterprise"],"total_disclosed_funding":{"min":5000000},
          "last_round_date":{"min":365,"max":730},"geo":["us"],"hiring_function":["sales"]},
  "avoid":{"program":["yc"]},
  "prefer":{"founder_prior_company":["stripe","databricks"]},
  "center":{"key":"stage","value":"seed","span":1},"rank_by":"match","limit":60},
 "notes":["'not YC' compiled as avoid:program=yc (a must-not is an avoid with weight 1.0 — see §3)",
          "founder prior company is known for 31% of startups — kept as a preference"]}
```

`POST /startups/evaluate` runs it (deterministic, no model call) → `{rows, counts, coverage, contract, labels}`.
The page renders:

1. **Coverage banner** first: "1,840 startups in the index · funding known for 62% · founders known for 48% ·
   ARR known for 6% · 212 satisfy every must". A must on a key whose index-wide known-rate is below 50% is
   rendered as a warning chip BEFORE Apply ("ARR is known for 6% — this filters by absence; keep as must?").
2. **The rail** (ported): rows = stage (ordinal; the centre marked), financing scale, tech area, total disclosed
   funding, last round, revenue range, ARR, lead investor, investors, program, non-dilutive, founders (count),
   HQ, headcount, founded, business model, customer, status, hiring (by function), evidence strength; signal
   keys (GitHub, news velocity) in a visually separate "signals" row. Chips carry counts over the must-filtered
   pool; `unknown` is a chip; edits are staged; Apply re-evaluates.
3. **Cards** (grid; one column ≤ 560 px): name → site; one-liner; **stage chip with basis glyph** (◆ stated round
   only — inferred scale is its own chip ◇); last financing (amount · date · lead) with provenance glyph
   (▣ filing · ▤ press · ▢ self-reported); total disclosed funding; revenue range / ARR (ARR ALWAYS prefixed
   "self-reported" unless from a filing); lead + top investors; founders (count, names); program badges; HQ;
   headcount; sector tags; **evidence strength** (how many independent sources, newest as-of); gaps ("no funding
   source found"); signals row. Click → the **claim drawer** (new body on roster's inline-panel skeleton): every
   cell's quote, source, tier, as-of, match method, and the conflict set with the resolution winner.
   Actions: ☆ save to a list · ⇄ compare · ◉ grounded entity page · "Diligence" → `/research/diligence`.
4. **Reasons** per card from the evaluator ("prefers founder prior company: stripe", "stage: series_a is 1 step
   from seed (nearby)", "arr: unknown").

Navigation never calls a model. Same contract → same rows. Contracts hash, diff and save (Startup Lists =
roster's saved maps: `contract` + snapshot + revisions; keep-fresh = re-evaluate + diff).

---

## 2. Architecture: claims first, facets as a projection — with the cheap path for structured sources

```
STRUCTURED sources ── code-owned CLAIM WRITERS (no model) ──┐
  YC JSON · Form D tables · portfolio tables · ATS boards   │
  · NSF / NIH / SBIR awards · PatentsView · GitHub          ├──▶ rs_claim + rs_claim_evidence (quote = the field
                                                            │      as rendered in the doc; span-verified; tier)
UNSTRUCTURED sources ── 3-gate LLM extractor (typed, §5) ───┘
  company pages · funding news · YC long description
                                                            │  resolve_conflicts (authority wins; losers kept)
                                                            ▼
                      PROJECTOR (pure code, idempotent, versioned) ──▶ eigen_entity_facet (rebuildable read model)
                                                            │
             compile (LLM, cached) ──▶ contract ──▶ evaluate (kernel, no model) ──▶ cards + rail + drawer
```

**Why projection (unanimous).** A claim in `rs_claim` already carries subject identity (strong-id resolved,
namesake-rejected), evidence kind, tier, period and a span-verified quote; a facet row derived from it inherits
all of that by construction. The drawer, the entity page, the diligence route and the rail then agree — one
truth, four renderings. "If the rail says Series A and the drawer says seed, trust goes to zero" (Gemini).

**The two corrections.** (a) Structured sources do NOT go through the LLM extractor: a Form D row, a YC record, a
portfolio table row or an ATS board entry becomes a claim by a code-owned writer (predicate fixed by the
source field — Rule 18: this is a computable field read, not a semantic judgment), with the rendered field text
as the quote so the span gate still holds. (b) The projector is DETERMINISTIC. The one place the v1 draft
smuggled a model call into projection (`tech_area` canonicalisation) moves upstream: the extractor emits the
closed-vocabulary `tech_area` as a claim annotation (versioned, cached), and the raw category entity is kept for
the map surface.

The projector reads WINNING claims only (`rs_claim_resolution`), parses typed values (money, dates, ranges) from
the typed columns (§5), applies the `basis` rules (§3), and DELETE-then-INSERTs a company's rows per key
(roster's `project()` semantics — a read model, explicitly NOT append-only like claims).

**Where things live**

| Piece | Location | Domain words? |
|---|---|---|
| facet types, contract, edit, evaluate, counts, store protocol, in-memory store | `packages/kernel/eigen_kernel/facets/` — roster's module, rename only (decision: `intake.py` is NOT ported in v1; its tests carry people vocabulary) | No |
| startup facet SCHEMA + weights + labels + PROJECTION rules | `packages/vertical_tech/eigen_vertical_tech/startup_facets.py`; mounted on the manifest's EXISTING `extraction_schema` slot (`contract/manifest.py:49`, roster's precedent — zero kernel diff) | Yes |
| predicate additions | `claim_predicates.py` (+4: `participated_in_program`, `founded_on`, `received_award`, `lead_investor` role on `has_investor` via a typed `role` field) | Yes |
| claim writers for structured sources | `eigen_vertical_tech/claim_writers/{yc,formd,portfolio,ats,awards}.py` | Yes |
| projector · SQL facet store · company vec table | `apps/api/facet_projector.py` (new), `apps/api/facet_store.py` (ported; company legs rewritten), DDL in `claimgraph.py` | neutral |
| compile, endpoints, lists, coverage | `apps/api/startups_route.py` (new; roster's `compile_contract` + `downgrade_uncovered_musts` port with light edits) | uses the schema only |
| connectors | `connectors/{formd_bulk,portfolio,company_site,ats_board,sbir}.py` + `*_doc.py`; `_http.py` gains politeness | Yes |
| UI | `apps/web/index.html`: mode, rail (ported), cards + drawer body (new), coverage banner | — |

---

## 3. The startup facet schema (vertical vocabulary) — v2

Entity kind `company`. Every key: type, values or bands, one line of `guidance`, `navigable`, and its PROJECTION
rule (predicate → parse → `basis`). Rules that apply to every key: `unknown` is roster's (a must excludes
unknowns; prefer/avoid/centre are neutral); a "must-not" (the brief's "not YC") compiles to `avoid` with weight
1.0 and is applied in SQL as an exclusion when the key is closed-vocabulary; **absence is never a value** — a key
with no claim is `unknown`, and the card says "none found" only when the source consulted is exhaustive for that
key (e.g. GitHub org search done, PatentsView queried) and then with the as-of date.

| Key | Type | Values / bands | Projection | Truth rule |
|---|---|---|---|---|
| `stage` | ordinal | pre_seed < seed < series_a < series_b < series_c < series_d_plus < growth | latest `raised_funding` claim with a STATED round name (`basis=stated_round`) — filing (a Form D never states a round), press or self-reported; YC batch alone → NOT a stage | the CENTRE key. A must on stage matches `stated_round` ONLY. Seed extension / SAFE / strategic / bridge map to the nearest named stage with the raw label in display |
| `financing_scale` | ordinal | none_disclosed < under_1m < 1_5m < 5_20m < 20_50m < 50m_plus | Form D `amount_sold` of the LATEST filing (`basis=inferred_from_filing`) | the honest home for "inferred stage"; a chip next to stage, never merged into it |
| `total_disclosed_funding` | numeric USD | <1M · 1–5M · 5–20M · 20–50M · 50–100M · 100M+ | Σ over `financing_event`s: one event = one Form D file number (amendments supersede, never add) OR one press-stated round not matched to a filing within ±120 days; SAFE-to-priced conversion cannot be detected → the card labels the sum "disclosed, may double-count converted notes" when both a filing and a press round exist in the same 12 months | figure must appear verbatim in the quote; EUR/GBP/CAD converted with a dated FX table (`data/fx.json`, monthly) and the assumption shown; other currencies display-only |
| `last_round_amount` / `last_round_date` | numeric USD / days-ago | bands; 6m · 12m · 24m · older | latest financing event | recency = momentum; time-window musts ("12–24 months ago") compile to a numeric range |
| `lead_investor` | set (canonical slug) | | `has_investor` with `role=lead` (press: "led by"; portfolio page never gives lead) | |
| `investor` | set | | `has_investor` any role; each row carries `role ∈ {lead, participant, portfolio_affiliation}` and the drawer shows it | a fund's portfolio page grounds AFFILIATION, not round participation; a logo wall on the company's site grounds nothing |
| `program` | set (closed) | yc · techstars · spc · ai_fund · a16z_speedrun · neo · pear · hf0 · antler · ef · alchemist · 500 · sequoia_arc · other | `participated_in_program` (YC directory; program's own directory page; press) | accelerator / studio / fellowship / membership are one relation: participation |
| `non_dilutive` | numeric USD | none_found · <500k · 500k–2M · 2M+ | `received_award` (SBIR/STTR, NSF, NIH RePORTER, USAspending — structured writers) | filing-tier; deep-tech signal; "none_found" only after the award sources were queried |
| `revenue_range` | ordinal | no_revenue < 1_1m < 1m_5m < 5m_25m < 25m_100m < 100m_plus | Form D revenue-range box (`basis=filing_range`); "Decline to Disclose" → unknown | NOT ARR; a range the filer chose to disclose |
| `arr` | numeric USD | <100k · 100k–1M · 1–10M · 10–50M · 50M+ | `revenue` claims typed `metric_kind=arr` (run-rate, GMV, bookings are DIFFERENT metric kinds and never project to `arr`) | self-reported unless in a filing; compile DOWNGRADES a must on `arr` to prefer with a note; one tap re-promotes it (explicit user edits are never downgraded) |
| `tech_area` | set (closed) | ai_infra · llm_apps · agents · devtools · data · security · robotics · hardware_semis · bio_health · climate_energy · fintech · consumer · enterprise_saas · space_defense · other | extractor annotation on `operates_in_category` (closed vocabulary, versioned) | vocabulary changes re-extract — deliberately, and gated |
| `customer` | categorical | enterprise · smb · developer · consumer · government | `targets_customer` | |
| `founder_count` | numeric | 1 · 2 · 3 · 4+ | count of `has_founder` person objects (YC, team page, press) | Form D related persons → `officer_count` (separate key, navigable=false in v1), never founders |
| `founder_prior_company` | set (slug) | | `role_background` typed `prior_company` per founder — ONLY when the team page / YC profile / press states it | the one founder tag shipped in v1 beyond count + names; `technical / phd / repeat` wait for measured precision (tranche 3) |
| `headcount` | numeric | 1–10 · 11–50 · 51–200 · 201–1000 · 1000+ | `headcount` | |
| `geo` | hierarchical | country/state/metro | `company_location` → geo normaliser (code) | |
| `founded` | numeric year | <2020 · 2020–22 · 2023 · 2024 · 2025+ | `founded_on` / YC `year_founded` / Form D incorporation year (basis shown) | |
| `business_model` | categorical | saas · usage · marketplace · hardware · open_core · services · consumer_subscription · other | `business_model` | |
| `status` | categorical | active · acquired · shut_down · public | `company_status` (YC status; press; EDGAR issuer status) | public/acquired live HERE, not in stage |
| `hiring` / `hiring_function` | numeric / set | 0 · 1–5 · 6–20 · 20+ ; engineering · sales · product · … | ATS board JSON (Greenhouse / Lever / Ashby public APIs) or careers page; `fetch_failed` is unknown | SIGNAL (momentum); a role's function is model-typed at ingest with the posting title as quote |
| `open_source` | categorical | found · none_found | GitHub org with a public repo | never "no" |
| `patents_granted` | numeric | none_found · 1–3 · 4+ | PatentsView assignee, granted only (pending = intent) | |
| `evidence_strength` | ordinal | single_source < two_sources < filing_backed | count of independent source kinds behind the card's funding facts | rankable; VCs asked for it |
| `news_velocity` | numeric | none · low · high | GDELT mentions / 90 d | SIGNAL, lowest tier; a must is REFUSED at compile (prefer + note) |

Weights: prefer program 0.15, lead_investor 0.15, investor 0.10, tech_area 0.12, founder_prior_company 0.12,
geo 0.10; avoid status 0.20; must-not (avoid weight 1.0) applied as exclusion; centre 0.08 per stage step beyond
span; signal keys 0.03 max.

---

## 4. Corpus: build the population aggressively from PUBLIC sources — corpus-first, precision-measured

Target after tranche 2: **15–25k startups** with identity + one-liner + sector + HQ + status; ~8–12k with a
grounded financing event; ~5k with founders named; ~1k with an ARR/revenue band. Tranche 0 reports, per source:
attach precision, coverage per facet, duplicate rate, crawl failure rate, and **cost per accepted grounded facet**
(Codex's metric) — not cost per company.

### 4.1 Identity (the whole game for funding)

One company node, two identities kept apart:
- **Product identity**: `domain:<registrable domain>` — the strong id minted by the YC writer (from `website`),
  the portfolio writer (link target after redirects) and the company-site connector. Existing `yc:<slug>` nodes
  are re-keyed: the YC writer emits `strong_ids={"domain": …, "yc_slug": …}`; `resolve_entity` merges by strong
  id and the `yc:` id becomes an alias (`rs_entity_alias`). Rebrands / redirects: a 301 from an old domain writes
  an alias, never a second node; an acquired company whose old site is live keeps `status=acquired` from press.
- **Legal identity**: `cik:<n>` for any issuer matched once to a Form D — permanent and exact for every later
  filing (Gemini's point). Legal name + state + city from the filing are stored on the entity (`legal_name`,
  `incorporation_state`) so "Acme Holdings LLC" ↔ "acme.ai" is a resolved pair, not a string match.
- **Form D attach rule**: exact normalised legal-name match to a known company's legal or product name AND a
  compatible state/city → attach; otherwise `llm_merge` with the filing's industry group + city/state against the
  candidate's one-liner + HQ as evidence (existing `resolve_entity`), accepted only above a confidence threshold
  measured on tranche 0; otherwise the issuer stays an `__unresolved` node that is NEVER attached (existing
  namesake rule). Pooled funds / SPVs / holding shells are rejected first by entity-type field (Form D states it)
  and name-form (`SPV|Fund|LP|Holdings|Investment` — a structural name-form check, not a semantic one), then the
  LLM confirms "operating company?" on the residue.

### 4.2 Sources (in order of authority and leverage)

| # | Source | Yields | Tier | Mechanics / new code |
|---|---|---|---|---|
| 1 | **SEC Form D bulk data sets** (quarterly zips, e.g. `sec.gov/files/structureddata/data/form-d-data-sets/2025q4_d.zip`; index page verified 200 on 2026-09-05) | issuer legal name / state / city / entity type / incorporation year, related persons + ROLES, industry group, revenue range, total offering, **amount sold**, date of first sale, exemption, **file number (dedups amendments)** | `primary_filing` | NEW `formd_bulk` connector (zip → per-filing doc with a rendered field summary) + `formd` claim writer (no model). Existing `edgar.py` Form D parsing (9 offering fields) is extended to related persons / revenue range / entity type for per-issuer refresh. All ~30 zips downloaded in tranche 0; attach gated on measured precision |
| 2 | **YC directory** (Algolia verified 200; connector exists with founders) | 5k companies: batch, one-liner, description, tags, HQ, status, team size, website, founders | `verified_structured` | `yc` claim writer (structural fields → claims); long description → LLM extractor |
| 3 | **Program + VC portfolio pages** (`data/portfolios.json`, ~60 URLs, dated) | name + link (+ sector/stage labels) → `participated_in_program` / `has_investor{role=portfolio_affiliation}` | `verified_structured` (the fund asserting its own portfolio) | NEW `portfolio` connector; LLM only for unstructured pages; monthly refresh; stale / exited logos are exactly why the row is affiliation, not a round |
| 4 | **The startup's own site** | home, /about, /team, /customers, /pricing, /press, /blog (latest 5): founders + roles + prior companies, headcount hints, customers, model, self-reported metrics | NEW evidence kind `self_stated` (rank between `technical_signal` and `expert_analysis`; never controlling) | NEW `company_site` connector — §4.4 |
| 5 | **ATS boards** (Greenhouse `boards-api`, Lever `api.lever.co/v0/postings`, Ashby `posting-api`) — public JSON, discovered from the careers page link or the ATS slug | open roles + titles + locations | `verified_structured` | NEW `ats_board` connector; this replaces headless rendering for hiring (Gemini's ATS-iframe point) |
| 6 | **Non-dilutive awards**: SBIR.gov, NSF (connector exists), NIH RePORTER (exists), USAspending | award amounts, agency, dates, PI | `primary_filing` | NEW `sbir` connector + `awards` writer |
| 7 | **Funding news** — GDELT (exists; headline metadata only) + Exa/Brave scoped `"<company>" (raises OR funding OR "Series")` | round name, amount, lead, date | `press` | web leg by design (frequently changing); cross-checked to filings by the resolver |
| 8 | GitHub org, HuggingFace, PatentsView (granted; needs `EIGEN_PATENTSVIEW_KEY`), OpenAlex founder papers, Companies House (UK officers), Wikidata | technical signals, granted IP, founder scholarly background, UK registry | as classified today | tranche 3 |
| 9 | Hacker News Launch/Show HN, Product Hunt | launch dates, sentiment | `sentiment` | tranche 4, prefer-only |

NOT used: Crunchbase / PitchBook / Dealroom / Tracxn / Harmonic (licensed), LinkedIn (ToS; roster's "never read
from linkedin.com" holds), Wellfound. Public-source-only is the product claim.

### 4.3 Coverage honesty about Form D

Form D covers priced rounds well and pre-seed/seed poorly (SAFEs are often batch-filed late or filed under
4(a)(2) without a Form D). Press + YC + program pages carry seed; Form D anchors A and later. The coverage banner
states the known-rate per key; tranche 0 measures the share of the YC AI cohort with any Form D match so the
number in the banner is measured, not assumed.

### 4.4 Company-site crawling — the written policy (new code, budgeted)

- Discovery: robots.txt first, sitemap-first, then the fixed path list; identified User-Agent with a contact
  address; no login walls, no paywalls, no bot-protection bypass, no proxies. A 403/429/JS-challenge is recorded
  as `fetch_failed` on the entity (visible in coverage; never an absence).
- Politeness: per-host 1 request / 2 s, global concurrency cap, 250 KB per page, 8 pages per site, HTML →
  markdown; `HttpStrategy` gains these (today it has retry + UA only).
- Refresh: gated by the **content hash of the rendered markdown**, not ETag (ETags churn on every deploy of a
  Next.js / Webflow site); site quarterly, careers monthly via the ATS API.
- PII minimisation: founder bios are stored as claims with quotes, no photos, no personal contact data; a
  removal process (`/admin/startups/remove`) suppresses an entity (status flip, never delete — existing ethos).
- Team pages that render client-side are handled by the `<script type="application/ld+json">` / `__NEXT_DATA__`
  payloads when present; otherwise `fetch_failed` for that page. No headless browser in v1.
- The existing answer-time deep company reader keeps working; when a corpus copy of a page exists, the corpus
  copy wins (corpus-first). Its `ATTRIBUTION_ADDENDUM` ("label the claim as self-reported") is reused verbatim
  in the extractor prompt for `company_site` docs.

---

## 5. Extraction: a TYPED output contract for the 3-gate extractor (new), plus the invented-figure rule

Today the extractor emits `{predicate, object (text), quote}`. v2 adds, per claim:
- `value: {amount, currency, period, metric_kind?, round_name?, role?}` for the numeric / typed predicates
  (`raised_funding`, `revenue`, `headcount`, `has_investor`, `received_award`), with the object text kept;
- `modality ∈ {realized, intent}` — "we plan to raise", "targeting $10M ARR by 2027" are `intent`, stored in the
  graph for diligence prose, NEVER projected;
- `tech_area` annotation (closed vocabulary) on `operates_in_category` claims.

`rs_claim` gains `value_num numeric`, `value_currency text`, `value_period text`, `value_kind text`, `modality
text` (default `realized`) — a schema ALTER-ensure in the existing style. Code owns normalisation (M/B suffixes,
FX by dated table) and the rule ported from roster: **the digits of a figure must occur verbatim in the quote**,
else the numeric part is dropped and the facet stays unknown ("eight figures" cannot become 12,000,000).

Subject congruence: the extractor is told the subject; a /customers page's "Stripe raised $6.5B" is not this
company's `raised_funding`. Founder claims are `has_founder` only when the text says founder / co-founder / CEO
& founder; "founding engineer", "advisor", "head of" are never founders.

Cache: `(block_sha, predicate_set_version, model, prompt_version)` → immutable result (NEW; today re-runs
re-spend). Batching: the extract prompt takes up to 5 blocks of one company per call where the blocks fit
(today 1 block/call); entailment stays batched per claim list. Both are step-2 deliverables measured in tranche 0.

---

## 6. Spend projection — DeepSeek, re-derived from the real call count; "everything under $10 first"

Provider: `EIGEN_LLM_PROVIDER=deepseek` (`runtime/build.py:47-51`, `deepseek-chat`). Roster measured the same
model at ≈ $0.05 per 80 schema-extraction calls (2,000 postings). Unit facts (verified): the claim extractor is
1 extract + 1 entail call per block today; at DeepSeek prices a 2k-token call is ≈ $0.001, so a company with 10
LLM-path blocks costs ≈ $0.02 today and ≈ $0.01 with 5-block batching. Structured sources cost embeddings only
(OpenAI `text-embedding-3-small`, $0.02 / M tokens — negligible at this scale).

**Phase A — everything that costs < $10 total (owner's rule: prove it here first).**

| Step | Spend | What it proves |
|---|---|---|
| kernel port, typed extractor contract, cache, writers, projector, store, endpoints, UI (§9 steps 0–4) | $0 | offline tests, parity, 390 px |
| YC full directory (5k) through the YC writer + embeddings | ≈ $0.10 | the population seed with founders, batch, HQ, status — no LLM |
| all Form D quarterly zips → corpus docs + writer (no attach yet) | ≈ $0.50 embeddings | the financing backbone exists |
| portfolio / program pages (60 URLs) through the writer | ≈ $0.10 | investor + program affiliation |
| ATS boards for the YC cohort (JSON, no LLM) | $0 | hiring signal |
| SBIR / NSF / NIH / USAspending for the YC cohort (structured) | $0 | non-dilutive funding |
| Form D attach on the YC cohort: exact-name path free; `llm_merge` on ~1,000 ambiguous issuers | ≈ $1 | attach precision measured on a 100-issuer hand check |
| LLM extraction (site pages + 2 news each) for **300 YC AI companies** | ≈ $3–6 | cost per accepted grounded facet; founder / customer / model / self-reported metric coverage |
| compile prompt on the 20 golden briefs | < $0.10 | the rail end to end |

Phase A total ≈ $5–8. It yields a working Startup Search over ~5k YC companies with grounded funding where a
filing or press exists, and typed detail for 300 of them.

**Phase B — after Phase A proves the numbers (each tranche gated on the measured unit cost).**

| Tranche | Scope | DeepSeek LLM | Notes |
|---|---|---|---|
| 1 | site + news extraction for the remaining ~4.7k YC companies | ≈ $50–90 | |
| 2 | portfolio-page companies (~10k new): sites + news + Form D attach | ≈ $100–200 | |
| 3 | founder prior-company typing, GitHub / patents / OpenAlex for the top 5k | ≈ $30 | tags shipped only at ≥ 90% precision on a 100-founder sample |
| refresh | ATS monthly (free), sites quarterly (hash-gated), Form D quarterly (writer), news monthly | ≈ $10–20 / month | |

Not in these numbers: Exa/Brave news probes (≈ $0.005 each; ~$25 per 5k companies), the crawler's engineering
time (the largest cost of the plan). Rules: dry-run projection printed, explicit go per tranche, never two
spending runs in flight, failed batches diagnosed before re-run.

---

## 7. Endpoints and data

```
POST /startups/compile    {text}                     → {contract, notes[]}  (model; cached; refuses must on signal keys;
                                                        downgrades must→prefer on keys with <50% known-rate and on arr; explains each note)
POST /startups/evaluate   {contract}                 → {rows, counts, coverage, contract, labels}  (no model)
GET  /startups/{entity_id}                           → claims, quotes, sources, tiers, as-of, match methods, conflict sets, basis
POST /startups/lists      {name, contract, rows}     → {id}   GET /startups/lists/{id}   POST /startups/lists/{id}/navigate {edits}
GET  /startups/coverage                              → index size, known-rate per key, freshness per source, fetch_failed counts
POST /admin/startups/ingest  {source, params, limit} → queue jobs (formd_bulk, portfolio, company_site, ats_board, sbir, yc)
POST /admin/startups/project {entity_ids?|all}       → projector run (idempotent, no spend)
POST /admin/startups/remove  {entity_id, reason}     → status flip (suppressed), never delete
```

`eigen_entity_facet`: `tenant_id, entity_kind, entity_id, facet_key, facet_value_norm, number, display_value,
provenance, basis, role, claim_id, evidence_tier, valid_as_of, schema_version, confidence`; indexes on
(tenant, kind, key, value) and (entity, key). `eigen_company_vec`: one embedding per company (one-liner +
description) for the semantic leg; musts filter in SQL on every leg (roster's leaky-pool invariant, re-tested
against the SQL adapter with the in-memory store as reference). `rs_entity` gains `legal_name`,
`incorporation_state`; `rs_claim` gains the typed columns (§5).

Flag `EIGEN_STARTUP_SEARCH` (default OFF; tab hidden; OFF path byte-identical).

---

## 8. Eval traps (held-out, written BEFORE the code they pin) — each designed to pass a gate while wrong

Identity
1. Namesake Form D ("Cognition Therapeutics" vs the AI lab) → not attached.
2. SPV / pooled fund / "Acme 2024 Investment LLC" → rejected by entity type or LLM confirm, never attached.
3. Holding company: "Acme Holdings LLC" ↔ acme.ai → attached via legal-name pair, once; the drawer shows the pair.
4. Rebrand / 301 redirect → alias, one node; acquired company with a live old site → status=acquired from press.

Money
5. Amended Form D (D/A) → one financing event per file number; the sum does not double.
6. Press "$12M round" + Form D "$9.6M sold" within 120 days → one event; the filing figure wins; press shown as
   "reported"; stage from press's stated round name only.
7. Invented figure ("eight figures" → 12,000,000) → numeric dropped, facet unknown.
8. Currency: "raised €10M" → converted with the dated table and the assumption shown; "raised ₹80 Cr" → display
   only, band unknown.
9. Decline to Disclose revenue → `revenue_range` unknown, never `no_revenue`.
10. "Run-rate $5M" / "GMV $20M" / "bookings" → never `arr`.

Stage / status
11. Intent: "we're raising our Series B" → stage stays series_a; the intent claim is in the drawer only.
12. Form D $40M sold, no stated round → `financing_scale=20_50m`, `stage` unknown; a stage must does not match.
13. Public / acquired → `status`, not `stage`.

People / programs / investors
14. Form D related persons (4) → `officer_count=4`, `founder_count` unknown.
15. "Founding engineer", "advisor", "head of engineering" → not a founder.
16. Logo wall "Trusted by Google" → no investor; fund portfolio page → `role=portfolio_affiliation`, not lead.
17. SPC membership → `program=spc`, not `investor=spc`.

Compile / evaluate
18. "Startups with great press" → must on `news_velocity` refused (prefer + note).
19. "Not YC", "no crypto", "under $10M" → avoid-as-exclusion / numeric max; "similar to Anduril but seed" →
    text leg + stage centre, no invented facts.
20. Leaky pool: a semantic-leg row lacking a must value never reaches rows (kernel test re-run on the SQL adapter).
21. Wrong subject on a company page ("Stripe raised $6.5B" on /customers) → no claim for this company.
22. Absence: no GitHub org found → `open_source=none_found` with as-of; a `fetch_failed` careers page → hiring
    unknown, not 0. ATS iframe with 10 roles + empty HTML → 10 (from the board API).
23. Vocabulary drift: a `tech_area` value outside the closed set is dropped at validation (roster's collision
    lesson), never stored.

Golden: 20 briefs with expected row sets over a fixture graph (offline), on every change; one flagship prod
verification per tranche.

---

## 9. Migration (in order; nothing deleted; each step lands with NO NEW guardrail violations)

0. **File the pre-existing red** as a tracked bug (CLAUDE.md: never normalise a failing test): kernel invariant
   fails today on 13 hits in `research/web_coverage.py`, `research/react.py`, `research/deep_company.py`,
   `test_contract_directive.py`, `test_prior_verify.py`; medical format fields on `VerticalManifest`;
   `people/store.py` docstring. Fix or explicitly allow-list BEFORE step 1 lands, so step 1's "green" is real.
1. **Kernel port** — `eigen_kernel/facets/` (schema, contract, evaluate, store, tests; not intake), 22 tests
   green, guardrails: no new hits. **No spend.**
2. **Typed extractor contract + claim columns + cache + writers** — §5 columns, `claim_extract.py` typed output,
   the block cache, structured claim writers for YC (re-keying `yc:` → `domain:`), Form D, portfolio, ATS,
   awards; `self_stated` evidence kind. Offline tests. **No spend.**
3. **Schema + projector + store + endpoints** — `startup_facets.py`, `facet_projector.py`, `facet_store.py`
   (ported; company legs), `eigen_company_vec`, `/startups/*`, behind the flag; project the 15 existing
   companies. Parity test SQL ↔ in-memory. **No spend.**
4. **UI** — ◆ Startups tab, rail (ported), cards + claim drawer body (new), coverage banner, warning-before-Apply;
   verified at 390 px. **No spend.**
5. **Connectors** — `formd_bulk`, `portfolio`, `company_site` (+ `_http.py` politeness/robots/cap/hash),
   `ats_board`, `sbir`; download all Form D zips. **Embeddings only.**
6. **Tranche 0** (25 companies) → measured report → **tranche 1** with the measured unit cost in front of the owner.
7. Lists + keep-fresh; tranche 2; founder prior-company typing (tranche 3); signals (tranche 4).

Estimated code (code-grounded reviewer): kernel 772 lines verbatim; step 2 ≈ 600–900 (extractor contract,
columns, cache, five writers); step 3 ≈ 1,100–1,400; step 4 ≈ 550–750; step 5 ≈ 900–1,200.

---

## 10. Panel answers to the open questions (recorded)

| Q | Codex | Gemini | Call |
|---|---|---|---|
| Q1 projection vs envelope | projection; cut cost with structured claim writers | projection; divergence kills trust | **projection + writers** (§2) |
| Q2 inferred stage in a must | stated only; inferred = separate "financing scale" | stated only; inference belongs in prefer | **stated only; `financing_scale` facet** |
| Q3 Form D back-fill | measure precision first | back-fill fully | **download all now, attach after ≥ 95% precision** |
| Q4 crawling | fine with a written policy (robots, UA, no bypass, PII, removal) | needs JS/ATS handling; Cloudflare 403s | **policy in §4.4; ATS JSON APIs; `fetch_failed` ≠ absence; no headless in v1** |
| Q5 founder typing | names + count; only high-precision tags | names + count only | **count + names + `founder_prior_company` (stated only); rest gated on measured precision** |
| Q6 ARR must | prefer by default with override | must downgrade to prefer | **downgrade + one-tap override; `revenue_range` separate** |
| Q7 roster lessons | vocabulary collisions, leaky retrieval, rail overload, count latency | taxonomy drift breaks the pool | **closed vocab validated at write; counts cached per must-set; rail rows collapsed to top 5 + more** |

## 11. Non-goals (v1)

No valuation inference or estimation of anything; no licensed data; no LinkedIn; no headless browser; no
learned weights; no model call inside evaluate; no cross-tenant lists; no "similar startups" neighbours until
the population is > 5k; no founder `technical / phd / repeat` tags until measured.

---

## 12. Build status (2026-09-05, evening) — what exists and what is running

Built as a DETACHED feature (owner's call: "completely new, done right, reuse roster's data where sharable"):
- `packages/kernel/eigen_kernel/facets/` — roster's kernel module, rename-only port (13 tests).
- `apps/api/startups/` — `schema.py` (26 keys), `store.py` (`su_*` tables + SQL facet store with musts and
  exclusions in SQL), `sources/{http,yc,formd,ats,site,roster_ats}.py`, `extract.py` (schema-driven JSON
  extraction; quote-in-page and figure-in-quote gates; intent dropped; founder ≠ founding engineer),
  `resolve.py` (CIK → located exact name → model judgment), `derive.py` (stage = stated round only;
  financing_scale from the latest filing; amendments supersede; press within 120 days of a filing not double
  counted), `compile.py` (must-not → SQL exclusion; ARR and <50%-coverage musts downgraded with a note),
  `pipeline.py` (jobs on a daemon thread, `su_job` progress, `extract` refuses past `max_usd`), `routes.py`.
  Tests: 21 offline + 2 Postgres integration (`EIGEN_STARTUPS_TEST_DSN`), all green; existing API tests green.
- `apps/web/startups.html` — the page (rail with staged Apply, cards, evidence drawer, coverage banner, saved
  lists via `#list=`); verified at 390 px. `index.html` shows a ◆ Startups tab when `startup_search_enabled`.
- Roster's data, shared: 3,001 ATS boards / 190k open roles exported over `railway ssh` and imported through
  `POST /admin/startups/roster-ats` (matched by company name).
- Provider: DeepSeek returned 402 Insufficient Balance on 2026-09-05; `EIGEN_STARTUP_LLM_PROVIDER=openai`
  (gpt-4o-mini) is set on prod until the balance is topped up. One extraction ≈ $0.01.
- Prod: deployed with `EIGEN_STARTUP_SEARCH=1`; Phase A jobs launched (YC all batches with founders; Form D
  2019→now). Next in the chain: roster-ats import → match → crawl → extract (≤ $5) → derive.
- Known gaps: sites that render client-side yield little text (recorded honestly as gaps); Form D name matching
  attaches few seed-stage companies (2 of 166 on the local W25 test — expected, most have not filed yet);
  `open_source` / `patents_granted` / `non_dilutive` have no source wired in v1; the kernel-invariant guardrail
  was already red on main before this work (13 pre-existing hits) and this feature adds none.

### 2026-09-06 — accounts, Startup Maps, dead links
- **Password accounts** (roster's model): `eigen_user.pw_hash/pw_salt` (PBKDF2-HMAC-SHA256, 240k), `POST /auth/register`
  (name + email + password; an existing email is refused with 409 — sign in instead), `POST /auth/login`,
  `POST /auth/logout`, `GET /me`; per-device bearer tokens as before. On when `EIGEN_ACCOUNTS=1`. The identity
  modal on both pages gained a password field and a sign-in / create-account toggle; professions are investor
  vocabulary (the clinical list was a leftover).
- **Startup Maps**: `su_map` + `su_map_revision`; `POST/GET /startups/maps`, `GET /startups/maps/{id}?share=…`,
  `POST …/navigate` (re-evaluate without saving), `POST …/revise` (new revision: contract + snapshot),
  `DELETE`. A map is owner-private; a share token gives read-only access. UI: ☆ Save as map, 🗺 My maps, map bar
  with inline rename, revision count, share link; `#map=<id>[&share=<token>]` opens one. `su_list` is superseded.
- **Removed from the shell for now**: Videos, Pulse (bell + page), Coverage link — empty or not working in prod.
  Explorer, Crossviews, Past sessions, Concepts stay (they serve).
- Verified locally end to end (browser): create account → save map → My maps → main page signed-in state.

### 2026-09-06 (later) — Startup Search is a MODE of the shell
- The separate page is gone: `apps/web/index.html` carries `#startupsbody` (rail, cards, drawer, maps) as
  `body[data-mode="startups"]`, sharing the heading, the intake box, the identity modal and the theme. The ◆ Startups
  tab switches mode; `#startups?b=<brief>` and `#startups?map=<id>[&share=<token>]` deep-link; `/startups` redirects
  and rewrites old `#map=` links. Class names that collided with the shell are `su-` prefixed; the CSS is scoped
  under `#startupsbody`.
- Landing: the effort control and the Discover / Understand / Act strip are replaced by a mission statement and an
  evidence-beam animation (a beam sweeps a shelf of public documents; the company mark at the centre lights as grounded),
  frozen under `prefers-reduced-motion`.
- Identity modal: Sign in / Create account tabs; no country, no NPI.

---

## 13. Data plan (2026-09-06) — where coverage stands and what comes next

### Coverage now (prod)

| Dimension | Known | Share of 6,159 |
|---|---|---|
| founders named | 6,095 | 99% |
| headcount · founded · HQ metro | 5,930 · 5,140 · 5,017 | 96% · 84% · 82% |
| filing-backed funding (Form D matched) | 711 | 11.5% |
| open roles (roster's ATS boards) | 907 | 15% |
| customers · business model (site extraction, 875 sites) | 434 · 502 | 7% · 8% |
| stated round · investors · lead investor | 67 · 66 · 29 | ≈ 1% |
| ARR (self-reported) · revenue range (filing) | 25 · 35 | < 1% |

The population is YC only. Money and backers are the gap: startup sites rarely state rounds; Form D never states
a round name; only press does.

### Running now (launched 2026-09-06, all free of model spend)

1. **Crawl every remaining YC site** (`crawl`, limit 5,000; ~10 h at the polite pace). Extraction of those sites is a
   separate, gated step (below).
2. **Form D issuers as companies** (`formd_companies`): unmatched operating issuers in technology-ish industry groups
   (Other Technology, Computers, Biotechnology, Health Care, Medical Device, Pharmaceuticals, Energy, Aerospace,
   Business Services, Telecommunications) with ≥ $2M sold since 2022 → `cik:<n>` companies with filing-backed
   funding, officers (never founders), city/state, incorporation year; a name match to an existing company is left to
   the match job. Filing-only cards link to EDGAR and say "no website on record".
3. **Funding-news probe** (`news`, 200 companies, ≈ $1): Brave query per company; titles + snippets to the model in
   batches; every event quotes an article verbatim with the figure and the round word inside; one round reported by
   several articles collapses to one event (also in derive, so totals never double). The probe's hit rate decides the
   full run below.

### Gated on the owner's go (over the $10 line)

| Run | Yields | Cost | Order |
|---|---|---|---|
| Extract the remaining ~4,800 YC sites (`extract`, 600 per job) | founders' prior companies, customers, business model, stated rounds where a site states them | ≈ $50 (gpt-4o-mini) or ≈ $58 (DeepSeek) | after the crawl lands |
| News leg for all YC companies (`news`) | stage, lead, investors where press exists | ≈ $31 Brave + < $2 model | after the probe's hit rate is in |
| News + site crawl for the new `cik:` companies (no website on record → a website-discovery step first) | identity for the filing-only population | to be projected once their count is known | later |

### Next sources, in order of leverage (not built yet)

1. **VC / accelerator portfolio pages** (`portfolio` connector, curated URL list): the fund asserting its own
   portfolio → `investor{role=portfolio_affiliation}` / `program`; adds ~10k non-YC startups with a website.
2. **SBIR / NSF / NIH RePORTER / USAspending** (`awards`): non-dilutive funding and government pull for deep tech;
   NSF and NIH connectors already exist in the tech vertical.
3. **Website discovery for `cik:` companies**: one search per issuer (name + city) → domain → then the site crawl and
   news legs apply to them.
4. **GitHub org / PatentsView (granted) / OpenAlex** for `open_source`, `patents_granted`, founder scholarly background.
5. **Refresh cadence**: ATS boards monthly (free), sites quarterly (content-hash gated), Form D quarterly, news monthly.

### Provider state
DeepSeek returned 402 Insufficient Balance twice (2026-09-05 and 2026-09-06 evening); prod runs
`EIGEN_STARTUP_LLM_PROVIDER=openai` (gpt-4o-mini). When DeepSeek is out of credit, compile silently degrades to a
text-only contract — switch the variable rather than leave it.

### 2026-09-06 (night) — Guided mode for startups (roster's intake, adapted)
- A third tab, ◍ Guided, between Quick Q&A and ◆ Startups. Opening words → the brief compiler → questions gated on the
  index's counts (kernel `facets/intake.py`, ported): REQUIRED tech area and stage (stage lands as the CENTRE, never a
  must); OPTIONAL funding floor, country, last-round window, founder count, program, customer, model, hiring, metro —
  asked only when the current slice is spread on the key and the budget remains (2 + 2). Chips carry live counts over
  the slice; typed answers go through one small model read; "Search now" ends it; the ready card shows the plain
  reading, the contract chips, the pool and advice; ◆ Search hands the contract to the Startups rail.
- Compiler hardening found on the way: a stage only when the brief names one; every named area / place / program /
  figure must land under a key (rules + two worked examples in the prompt for gpt-4o-mini); bare numbers become a
  floor or a band; a must on a sparse key stays a must when the requested values are common (≥ 25 startups) —
  the filing-only companies had dragged tech area / metro / program below the 50 % coverage line.

### 2026-09-07 — contract search (roster's guided-intake §12, adapted): merge, don't pick; judge the head
- Kernel: roster's current evaluator (with words the pool is the SEMANTIC NEIGHBOURHOOD — no enumerate union, which
  was the source of unrelated rows; prefer legs; relevance bands first) and `facets/contract_search.py` (recipes ·
  collapsing-must rule · co-occurrence readings · RRF fusion · blind ids · verdict order · head precision), tests ported.
- App `startups/contract_search.py`: index-aware step (a compiled must — never the user's — that leaves < 20 while its
  removal multiplies the pool ≥ 5×, on a relaxable key, ranks instead); recipes strict / default / relaxed:<key> /
  loose probed by a bounded slice size; survivors evaluated; RRF (k = 60); ONE blind judge over the top 40 (row shape:
  name · one-liner · areas · sells to · stage · funding · HQ · founders · program · evidence; yes / partial / no, ≤ 8
  words; ≈ $0.003 on gpt-4o-mini); order = fits, partials, ungraded tail, then the 'no' rows; WEAK = < 3 fits.
- `/startups/evaluate` runs merged by default whenever the contract has words (`merge.mode = single` opts out;
  `merge.off` switches readings off; `merge.user_keys` = the user's own constraints, never relaxed). Rail edits carry
  the merge options; the rail shows "Model read: N of 40 graded fit" and the readings as toggles; cards carry a
  labelled fit pill ("reads as a fit · model") with the verdict's reason and which readings found the row.
- Guided READY: index-aware notes, the readings with their measured pools, U diagnostics ("your must metro: boston
  leaves 3 — without it 400"); the hand-off contract carries `merge` so the Startups mode runs the merged search.

### 2026-09-07 — smart relaxing (roster §12.12b, adapted)
Too few results → musts relax to PREFERENCES, least important first, the compile's before the user's own chips, until the
pool is a good size: the must-slice is probed and relaxed until it holds 30, then the search runs and while it returns
fewer than 12 rows one more must relaxes per evaluate (≤ 3). Order (least → most important): hiring function, hiring,
business model, customer, founders' prior company, lead investor, investor, program, founder count, last-round window,
metro, funding floors, stage. The thesis (tech area) and the scope (country) never relax; a numeric floor relaxes by
removal (a preference cannot hold a range) and the note says so. First searches only (a compile, a Guided hand-off) —
a rail Apply runs the chips exactly as set. The rail's "Showing more" block names each relaxed filter (the user's own
marked); its chip already sits at ▲ prefer so one tap restores it.

### 2026-09-07 — the non-YC population
- `portfolio` job: for each fund in `startups/data/portfolios.json` (40 accelerators and funds) the portfolio page's own links
  and embedded JSON, then the sitemap's profile pages (Sequoia 425, Accel 775, General Catalyst 606, NEA 914, Lux 215, …),
  each read for the company's site — name from the title / heading / slug, the site from the external link that echoes the
  name or reads "visit"; a domain on ≥ 3 profiles is the fund's chrome. Companies key by domain; the fund's page grounds
  `investor{portfolio_affiliation}` or `program`. Pages that render client-side yield little; no headless browser.
- `discover_sites` job: filing-only companies (cik:<n>) get a website from Clearbit's keyless autocomplete when the suggested
  name equals the issuer's normalised name; an existing site-keyed company with that domain absorbs the filing identity
  (CIK, financing, filings; the cik: row is suppressed). Source `lookup` on the card says the site was found by name.
- Rejected on measurement: DuckDuckGo HTML (blocked), GDELT (429s), Wikidata (≈ 500 recent software companies), Show HN
  (side projects). Search-API discovery (Brave) stays the better route when its credits are allowed.

### 2026-09-07 — survive an outage; a founder is a person
- **The words can fail; the filters must not.** OpenAI's embeddings answered `429 credit_balance_exhausted`,
  which made `/startups/evaluate` return 500 — an outage in one leg took the whole search down. The bound store now
  catches an embedding failure and falls back to `enumerate`, so the typed contract still selects companies; the
  multi-recipe merged path falls back to a single evaluate. The response carries `coverage.degraded` and the rail
  says the words cannot rank, filters only. Search NEVER returns a 500 because a model is unavailable
  (`test_search_survives_an_embedding_outage`).
- **A founder row names a person.** Prod held three collective rows ("Founding Team", "Founders and operators from …").
  `extract.is_person_name` rejects collective words and sentence-length strings. It is deliberately narrow: mononyms,
  nicknames in quotes or parentheses and post-nominal letters are all real founder names in the index, so a stricter
  "two capitalised tokens" rule would have deleted 129 real founders. The three rows are replaced on the next
  extraction pass for those companies.

## 14. Extraction backlog — the resume plan (written 2026-09-07, paused on credits)

**Where it stands.** Downloading is done; reading the downloaded pages is not.

| Stage | Count | Note |
| --- | --- | --- |
| Companies indexed | 17,665 | all embedded |
| With a website | 13,659 | |
| Crawled | 13,528 | crawl job 46 finished the tail |
| Crawled with usable pages | 11,614 | 32,067 pages stored |
| Extracted from their own site | 800 | `su_fact.basis = 'self_reported'` |
| **Extraction backlog** | **10,814** | the whole of the remaining work |

Search works today without it: filings ground 8,894 companies, derive 9,022, portfolio affiliation 3,448,
named founders 6,108, ATS 914. Extraction is what adds the site-grounded keys — ARR, customers, business model,
stated rounds, founder prior companies — so the backlog is the difference between a directory and a read corpus.

**Why it is paused.** Both model accounts are empty: DeepSeek 402 `Insufficient Balance` (2026-09-06 evening),
OpenAI 429 `credit_balance_exhausted` (2026-09-07). Extraction is one model call per company, so it cannot run
at all until credit is added. Nothing else blocks it — the pages are already in `su_page`.

**Cost.** `EXTRACT_USD_PER_COMPANY` is 0.012 (a DeepSeek-priced estimate of ~30k in / 1k out).

| Provider | Per company | 10,814 backlog |
| --- | --- | --- |
| Our projection constant | $0.012 | ~$130 |
| OpenAI gpt-4o-mini (actual list) | ~$0.010 | ~$110 |
| DeepSeek chat (actual list) | ~$0.009 | ~$97 |

**How to resume (do this in order).**
1. Confirm credit is really there before launching anything: one extraction on a single company
   (`{"kind":"extract","params":{"limit":1,"max_usd":0.05}}`) and check `su_fact` gained `self_reported` rows.
   A batch launched against an empty account burns the whole tranche on 402/429 retries.
2. Set the provider to whichever account has credit: `railway variables --set "EIGEN_STARTUP_LLM_PROVIDER=deepseek|openai" -s eigen-api`.
   Setting a variable redeploys, which orphans running jobs — do it BEFORE launching, never during.
3. Run in tranches of 600 with `max_usd: 8.0` (the job refuses a projection above `max_usd`), reviewing between:
   `POST /admin/startups/jobs {"kind":"extract","params":{"limit":600,"max_usd":8.0}}`. About 18 tranches clears
   the backlog. The selection already skips companies with no crawled pages and companies already extracted, so
   tranches never overlap and a re-run after an orphan resumes where it stopped.
4. Order matters more than volume. The first tranches should be the companies most likely to be searched —
   those with funding or recency signals (`su_fact` carrying `total_disclosed_funding` or `founded >= 2023`) —
   so the index gets deep where users actually look. The plain selection is arbitrary; add an ORDER BY before
   the first tranche rather than after.
5. Run `derive` after every few tranches (`{"kind":"derive"}`, free and deterministic) so the new
   self-reported rows fold into stage, financing scale and evidence strength.
6. Watch for the deploy hazard: every `railway up` restarts the API and orphans in-flight jobs. Do not deploy
   while a tranche is running; if one is orphaned, just relaunch — jobs resume idempotently.

**When it is done.** Coverage for `arr` (29 companies today), `customer` (439), `business_model` (527) and
`founder_prior_company` (104) should rise by roughly the extraction hit rate seen so far — job 19 turned 512
companies into 2,777 facts, about 5.4 facts per company.
