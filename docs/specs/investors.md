# Investor Search — a fourth mode: who funds, what they fund, and what is actually knowable about it

Status: spec **v2 (2026-09-09), panel-reviewed** — Gemini 3 Pro + a code-grounded reviewer; every objection
either applied below or explicitly overruled with a reason. Owner ask: an investor mode where an investor can be searched
by every parameter that matters — stage funded, what they have funded, success rate, how much money they make,
investor type (angel, fund, fund of funds, PE, …), cheque size and equity taken, geography, portfolio — with the
same card model, the same rail of controller parameters, and the same "save as a map" affordance as Startup
Search; proper links to the firm's site, to every startup they funded, and to their main people (LinkedIn, X,
personal site). Download everything downloadable.

Bound by CLAUDE.md: corpus-first; evidence is typed (subject + kind congruence, never "close enough"); sentiment
is a signal, never a fact; **stated intent ≠ realized fact**; kernel stays domain-free; API credits projected and
gated per tranche; mobile-friendly; every gate carries a held-out trap designed to pass the gate while being wrong.

---

## 0. The one idea this mode turns on

Startup Search had to separate *a stated round* from *an amount*. Investor Search has a harder version of the same
problem, because almost everything a VC firm says about itself is marketing and almost nothing about its returns
is public. So every number on an investor card belongs to exactly one of **three registers**, and the register is
rendered, never elided:

| Register | Glyph | Source | Examples | Rule |
|---|---|---|---|---|
| **Filed** | ▣ | SEC Form ADV, SEC Form D, a public pension's own performance release | regulatory AUM, fund size, fund vintage, fund type, GP names, HQ state, net IRR of fund *N* as CalSTRS reports it | a fact, with the filing linked and an as-of date |
| **Stated** | ▢ | the firm's own site | "we lead pre-seed", "$1–3M cheques", "we take 10–15%", "US and Europe" | **intent, never fact.** Rendered in the firm's own voice ("the firm says…"), never as a filter that claims to be true |
| **Observed** | ◈ | computed over *our* index | portfolio count, stage mix, sector mix, co-investors, follow-on rate, outcome mix, sizes of rounds they led | a measurement **of our coverage**, and it is invalid without its denominator |

The failure this prevents is precise: a firm that says "we write $5M seed cheques" while its Form D says the fund
raised $12M total, next to an "82% success rate" computed over eleven companies of which nine were funded last
year. Each of those three numbers is defensible in its own register and a lie when merged. The card never merges
them.

**What we refuse to output at all**, because no public source supports it: an IRR we did not read off a named
LP's disclosure; any "returns" or "multiple" estimate; the ownership percentage a firm took in a round; a cheque
size inferred by dividing a round by its investor count; management-fee or carry income; a ranking of firms by
"performance". Each refusal shows as a gap with the reason, which is itself an answer a VC can use.

---

## 0.5 Who this is for — both sides of the table

Startup Search serves the investor looking at companies. Investor Search serves **both directions**, and the
owner's framing is that Eigen should be where startup founders come:

- **A founder finding capital.** "Who funds pre-seed AI infra in India, writes $250k–1M, leads, and has filed a
  fund since 2024?" A founder needs the *stated* register more than the filed one — cheque size, stage, geo,
  whether the firm leads — plus two things nobody else shows honestly: **is this firm still deploying** (a fund
  that last filed in 2019 is not raising your round, however good the website looks) and **do they already fund
  a competitor** (computable from our own sector edges the moment a firm has a portfolio).
- **An investor doing diligence.** Who else is on the cap table, who co-invests with whom, which funds a public
  LP actually reports returns for, what a firm's filed AUM is versus what its homepage claims.

The same contract, rail and card serve both; only the default sort and the coverage warnings differ. A founder's
brief centres on `stated_stage` and geo; a diligence brief centres on filed keys.

---

## 1. What the user sees

A fourth tab in the shell: **◈ Investors** (`body[data-mode="investors"]`, hash `#investors`, deep links
`#investors?b=<brief>` / `#investors?map=<id>&share=<token>`, exactly the Startup Search router shape).

One box. The user types a thesis brief the way they actually say it:

> "seed funds that lead in AI infra, US or Europe, $50–250M latest fund, still deploying, at least 5 companies
> in our index, not corporate VC"

`POST /investors/compile` (one small cached model call) → a contract + notes; `POST /investors/evaluate` (pure
code, no model) → rows, counts, coverage. The page renders:

1. **Coverage banner, first.** "5,412 investors · 3,240 with a filed fund · AUM filed for 61% · stated cheque
   size for 18% · portfolio edges for 44% · **non-US firms are under-covered: Form ADV is a US register**".
   A must on a key whose known-rate is under 50% raises a warning chip *before* Apply, as in Startup Search.
2. **The rail** — the same ported rail, rows grouped by register so the user can see what they are filtering on:
   *filed* (type, AUM, fund count, latest fund size, vintage, HQ country/state/metro, still deploying,
   regulatory disclosures) · *stated* (stage focus, cheque range, ownership target, geo focus, leads or follows)
   · *observed* (portfolio size, stage mix, sector mix, co-investors, round sizes they led — **and no success
   metric: §4 keeps outcome mix and follow-on rate out of the rail entirely**). Chips carry counts over the must-filtered pool; `unknown` is a chip; edits stage; Apply re-evaluates.
3. **Cards** — one per investor, the Startup Search card grammar:
   - name → **the firm's own site** (verified: ADV website field, or a portfolio page we read, never guessed)
   - type chip (`venture_fund`, `pe_fund`, `angel`, `fund_of_funds`, `corporate_vc`, …) with its basis glyph
   - filed line: AUM · *n* funds · latest fund $X (vintage YYYY) · HQ
   - stated line, visually quoted: "leads seed and Series A · $1–3M · US, EU" — with a ▢ and the firm's page
   - observed strip: portfolio *n* (of which *m* we can date from filings) · top sectors · stage mix
   - **portfolio row**: the best-known companies as chips, each linking to that company's startup card and to
     DeepDive — this is "links to all startups they fund", the full list living in the drawer
   - **people row**: main people, each with the links a source actually stated — in · 𝕏 · ◐ personal site
   - LP-returns line when a public pension discloses one of their funds: "CalSTRS reports net IRR 18.4% for
     Fund VII (vintage 2016), as of 2025-06-30" — per fund, never averaged into a firm-level score
   - gaps: "no fund filing found", "cheque size not stated", "no LP discloses these funds"
   - actions: ☆ save · ⇄ compare · **⊞ see their portfolio in Startups** (opens Startup mode with
     `must:{investor:[slug]}` — one contract, no new data) · ◉ the firm's dossier drawer
4. **Reasons** per card from the evaluator, unchanged in mechanism.

**Investor Maps** are Startup Maps' twin: `contract` + snapshot + revisions + share token, account-gated,
keep-fresh = re-evaluate and diff.

---

## 2. Identity — three node kinds, kept apart on purpose

The single most expensive mistake available here is merging two things that share a name. Accel and Accel-KKR are
different firms with different asset classes. Sequoia Capital and Peak XV are now different firms with a shared
history. "Anthropic SPV I, LLC" is not an investor, it is a vehicle named after a company. So:

- **`iv_firm`** — the manager, the thing a card is about. Its primary id is an **eigen slug** (`a16z`,
  `general_catalyst`) — the vocabulary the startup index's `investor` facet already speaks, which is what makes
  every existing edge usable on day one. **The domain is an attribute and a merge signal, never the key.**
  *(v1 of this spec keyed firms by domain, copying `su_company`. Measured against the real ADV data on
  2026-09-09, that is unshippable: of 7,424 VC/PE-managing firms, **980 (13%) publish no website at all**, and
  2,417 more collide on a shared domain — including **1,355 firms that list `linkedin.com` as their website**,
  which a domain key would fuse into one node. Panel objection #1, accepted with evidence.)*
  Strong ids that merge two rows: `crd:<n>` (Form ADV organization CRD — permanent), `cik:<n>`, a registrable
  domain that is not a social or hosting host. Two firms may never merge on name similarity alone.
  **The join to the startup index is not free, and v1 said it was.** Only the ~28 `kind:"investor"` entries in
  `data/portfolios.json` produce canonical slugs (`pipeline.py:619` writes the hand-authored slug). The rest of
  the 4,953 `investor` facts come from the extractor via `extract.py:210 _slug()` — lowercase-and-underscore on
  whatever the model wrote, with **no alias table and no canonicalisation** (`su_investor` is a resolution cache
  keyed by slug, not a registry: `store.py:173-178`). So `a16z`, `andreessen_horowitz` and
  `andreessen_horowitz_a16z` are three different join keys today, and `sequoia` is already absorbing Sequoia
  China and Peak XV mentions — the very merge §2 exists to prevent, latent in the key itself. **`iv_alias(slug,
  canonical_id, basis)` is therefore a first-class table and the `link` job's main product**, not a detail.
- **A firm with no website is still a firm.** Its slug is minted from the register id (`crd-342972-galileo-global`)
  and upgraded to a readable slug the moment a site is discovered, with the old slug kept in `iv_alias` — so the
  no-website population (980 of 7,424 VC/PE managers) never becomes a duplicate card later.
- **Slug is a merge key only after disambiguation.** Two firms that print the same name in different geos get
  `name` and `name-<state>`; the slug is minted, never inferred from a name alone. *(Codex was right that
  treating a name-derived slug as a strong id smuggles name-similarity merging back in through the side door.)*
- **One CRD is one firm; brands are display, not identity.** Where a single registered manager runs several
  brands, that is one `iv_firm` with brand aliases — the Sequoia / Peak XV case is two cards because they are two
  registered advisers, not because they look different. If a genuine same-CRD multi-brand appears, returns and
  AUM attach to the CRD once and are shown on each brand with the shared basis named, never double-counted.
- **Brand succession** is an explicit relation, not a merge: `iv_firm_rel(from, to, kind=renamed|spun_out|affiliate,
  effective, source_url)`. Sequoia Capital → Peak XV is two cards and one dated arrow, so a pre-split portfolio
  stays attributed to who actually held it.
- **`iv_fund`** — one vehicle. Keyed by Form D **file number** (amendments share it — this is already how
  `su_financing` dedups). Carries the fund's legal name, the **fund type the form itself states** (Venture Capital
  Fund · Private Equity Fund · Hedge Fund · Other Investment Fund), total offered, **total sold**, date of first
  sale (= vintage), number of investors, minimum investment, manager city/state, and the related persons. A fund
  attaches to a firm only by an evidenced rule (§4.3); an unattached fund is still a row and still searchable,
  it simply has no firm card.
- **`iv_person`** — a human. Two populations with different identity rules:
  - **firm people** (GPs, partners, principals) — keyed `<firm_id>:<name_slug>`, so a namesake at another firm
    can never merge in. Sourced from the firm's team page and from Form D related-person rows on its funds.
  - **angels** — keyed `angel:<name_slug>`, minted on first sighting. An angel is promoted to a card by EITHER
    a stated strong id (their own site, an X handle, or a LinkedIn URL printed on a page we read) **or
    corroboration**: named as an investor by **two independent sources** — two different companies' pages, or a
    company page and a press item. *(v1 required a strong id and nothing else; the panel was right that this
    erases exactly the quiet, high-value angels a founder is looking for. Corroboration keeps coverage without
    inventing a person.)* A single unverified mention still shows, honestly, as "an investor named *X* is named
    by 1 company — no profile source found", which is a real search result rather than a fabricated profile.
  - **PII discipline for individuals, stronger than for firms** (panel objection #4, accepted): an `iv_person`
    card carries name, stated role, the edges that name them, and links a source printed — and **never a
    computed financial metric**. No `led_round_size`, no `outcome_mix`, no success rate, no inferred net worth
    for a human being. Those are firm-only measures. No photos, no contact details, no home addresses (Form D
    related-person addresses are dropped at parse time, not at render time). `/admin/investors/remove` suppresses
    on request, and the spec treats that as a *product requirement*, not a courtesy.

**Suppression, not deletion**, for people who ask to be removed (`/admin/investors/remove`), matching the startup
module's ethos.

---

## 3. Sources — verified 2026-09-09, all free, all downloadable

| # | Source | Yields | Register | Mechanics |
|---|---|---|---|---|
| 1 | **SEC Form ADV bulk** — `sec.gov/…/information-about-registered-investment-advisers-exempt-reporting-advisers`, monthly zips, *registered* (17,149 firms, 448 cols) and *exempt reporting advisers* (6,686 firms, 171 cols). **ERAs are where venture capital lives** — the VC-adviser exemption. Measured: **3,240 firms flagged "Any VC Funds", 4,553 "Any PE Funds", 5,227 ERAs with a website** | legal + primary business name, CRD, CIK, **website**, HQ street/city/state/country, entity type, state of organization, employee counts, **regulatory AUM (5F(2)(c))**, private-fund counts by type (VC / PE / hedge / real estate / securitized / other), total gross private-fund assets, latest filing date, status, **Item 11 disclosure counts** | filed | new `sources/adv.py` — download, join, upsert. No model. Monthly refresh, keyed by CRD |
| 2 | **SEC Form D pooled filings** — we already hold **412,356 filings across 30 quarters** in `su_formd`; one quarter (2026Q2) alone carries **2,983 Venture Capital Fund + 2,596 Private Equity Fund + 2,682 Hedge Fund** offerings | per-vehicle: fund legal name, **`INVESTMENTFUNDTYPE` as filed**, offered / **sold**, first-sale date, investor count, `MINIMUMINVESTMENTACCEPTED`, city/state, **related persons with roles = the GPs** | filed | **more work than v1 claimed.** The parser reads the tables, but `INVESTMENTFUNDTYPE` is consumed only for truthiness (`sources/formd.py:135`) — the *value* is never captured — and `MINIMUMINVESTMENTACCEPTED` is not read at all. `su_formd` persists neither `is_pooled` nor fund type (`store.py:108-134`), though it **does already hold every pooled filing**, related persons included (`run_formd` filters nothing on write; `is_operating` is a read-side filter). And a re-run cannot ride `run_formd`: it skips quarters already present (`pipeline.py:165-168`) and inserts `ON CONFLICT (accession) DO NOTHING` (`store.py:368`). So `funds` gets its **own quarter loop, parser extension and writer**. Still free — bandwidth, not credits |
| 3 | **Our own index** — 33,457 companies, 23,269 with a financing event, 4,953 with an `investor` fact, 40 crawled portfolio pages, 32,101 crawled sites | every firm→company edge we hold, plus everything known about the company on the other end: stage, sector, geo, status, outcome | observed | pure SQL. Zero new fetching |
| 4 | **The firm's own site** (reuses `sources/site.py` + `sources/http.py`: robots-first, 1 req / 2 s, 400 KB cap, content-hash refresh) | thesis, stage focus, **cheque range**, **ownership target**, geo focus, leads-or-follows, team page, portfolio page | stated | crawl free, **with two additions the reviewer caught**: `site.crawl()` has an 8-page budget and a `_WANT` vocabulary (`site.py:18-23`, `:67-74`) that knows *investors* but **has no `portfolio` page kind at all** — the page that matters most for a firm — so the vocabulary gains `portfolio / companies / investments`; and `site.founder_links()` (`site.py:137-156`) is a **matcher, not an extractor** — it attaches links to names you already have, needs two name tokens, matches X by anchor text only, and **extracts no personal site**. A structural team-page person parser is new code (free); the `people` job is only free once it exists |
| 5 | **Portfolio pages** — today 40 curated; this mode grows the list to every firm whose site we resolve, reusing `sources/portfolio.py` (structural link + embedded-JSON reader, no model) | firm→company edges, and **new companies** for the startup index as a side effect | filed-adjacent (`verified_structured`: the firm asserting its own portfolio) | the edge means **affiliation**, not round participation — the existing rule, inherited verbatim |
| 6 | **Public pension LP disclosures** — CalSTRS "Private Equity Portfolio Performance" (verified 200; annual PDF), CalPERS PEP fund performance, Oregon OIC, Washington SIB, UTIMCO, TRS | per fund: vintage, capital committed, contributed, distributed, **net IRR**, as-of date, and the LP's name | filed | one small parser per LP, annual refresh. This is the **only** honest source for "what they make" |
| 7 | **Form D related persons on operating-company filings** | a VC's partner sitting as a director of a portfolio company → an edge, and a person link | filed | already in `su_formd.officers`; needs a matcher, no fetching |
| 8 | **SEC Form 13F data sets** (quarterly zips, `sec.gov/…/form-13f-data-sets`, verified 200) | actual public-equity holdings of institutions over $100M — the honest window into crossover funds (Tiger, Coatue) and the post-IPO leg of a venture portfolio | filed | new adapter; panel-suggested, accepted |
| 9 | Company sites' "investors / backed by" sections (we already crawled 32,101 of them) and funding press | **named angels** and firm participation | stated / press | the primary angel population; §5 |

### 3b. Beyond the US — the regional registers, and the angel lists

Form ADV is a **US** register, so a v1 built on it alone would render Index, Balderton, Atomico, Blume, Sequoia
India/Peak XV, AirTree and Shorooq as thin cards, which reads as "small" and is simply wrong. Every major venture
geography keeps a public register of authorised fund managers, and each is the local analogue of ADV. Probed
2026-09-09 unless noted:

| Geo | Register | Status | Yields |
|---|---|---|---|
| UK | **FCA Financial Services Register** (`register.fca.org.uk`, plus a free-key JSON API) | page 200; API needs a free key | authorised firm name, FRN, status, address, permissions |
| EU | **ESMA registers** — EuVECA / EuSEF managers, AIFMD managers | registers-and-data page 200; per-register file to pin | EU venture fund managers by member state |
| India | **SEBI registered Alternative Investment Funds** (`intmId=16`) and **Registered Venture Capital Funds** (`intmId=21`) — Category I AIF is where India's VC *and its registered angel funds* sit | both pages 200; the table is AJAX-loaded, so the fetch is a POST, not the page | fund name, registration number, category, address, contact |
| Singapore | **MAS Financial Institutions Directory** (`eservices.mas.gov.sg/fid`) | 200 | licensed and registered fund management companies |
| Australia | **ASIC AFS licensee register** (published as open data) | to pin — the data.gov.au query I tried 404'd | licensee name, ABN, address, authorisations |
| UAE | **ADGM** and **DFSA** public registers | to probe | authorised firms in the two financial free zones where Gulf VC is domiciled |
| UK (ownership) | **Companies House PSC bulk snapshot** (`download.companieshouse.gov.uk/en_pscdata.html`) | 200 | persons and entities with significant control of UK companies — real, filed cap-table structure for UK startups |
| Global | **Wikidata** SPARQL (keyless, verified working) | 200 | long-tail firm identity: country, inception, website, parent — a fallback identity source, never an authority |

**Angel lists are their own population**, and they are organised as *networks*, which is the tractable unit:

| List | Status | Yields |
|---|---|---|
| **Angel Capital Association** member directory (US) | 200 | ~250 US angel groups: name, region, site |
| **UKBAA** member directory | 200 | UK angel networks and syndicates |
| **EBAN** members (Europe) | 200 | European angel federations and networks, by country |
| Regional networks named by the owner — India (Indian Angel Network, Mumbai Angels, LetsVenture), UAE (Dubai Angel Investors, Womena), Australia (Australian Angel Investment networks) | to probe per network | group name, region, stated cheque range, sometimes a member list |
| **Company sites + press we already hold** (32,101 crawled sites) | in hand | the *individual* angels — §5's promotion rule decides which become cards |

Two honest limits, stated on the card rather than papered over: a register proves a firm is **authorised**, not
that it is **active** — `still_deploying` comes from filings, not from registration; and an angel *network* is
not its members. A network card lists the network, and names individuals only where the network publishes them.

**Licensing is part of "free"** (Codex, accepted): Companies House bulk is Open Government Licence and requires
attribution; Wikidata is CC-BY-SA and its share-alike terms mean Wikidata-derived facts are surfaced as
attributed enrichment, never blended into our own dataset; each regulator's register carries its own reuse terms,
checked per adapter before it ships. **Also added on Codex's suggestion:** the **SBA SBIC licensee list** — an
official roster of licensed US small-business investment companies, which is the only structured source for the
venture-debt / SBIC corner of `investor_type`.

**Not used**, and the product says so: Crunchbase, PitchBook, Dealroom, Tracxn, Harmonic (licensed); LinkedIn as a
*source* (ToS — we link to a profile a page printed, we never read linkedin.com); AngelList/Wellfound.

**Coverage honesty, stated in the banner and on every card** (and the reason §3b exists): Form ADV is a US register. A European or Asian firm
with no US adviser registration has no filed AUM here, and its card will rest on its own site plus our observed
edges. That is a coverage fact, not a quality judgment, and the card must not read as if the firm were smaller.

---

## 4. The investor facet schema

Entity kind `investor`. Mechanics come from `eigen_kernel.facets` untouched (`FacetKey`, `FacetSchema`,
`Contract`, `evaluate`, `grouping`, `contract_search`, `intake`) — this mode adds **vocabulary only**, in
`apps/api/investors/schema.py`, mirroring `apps/api/startups/schema.py`. No kernel diff, no domain noun in the
kernel.

**Filed keys**

| Key | Type | Values / bands | Source | Truth rule |
|---|---|---|---|---|
| `investor_type` | categorical | `angel · angel_group · syndicate · accelerator · studio · seed_fund · venture_fund · growth_fund · pe_fund · fund_of_funds · corporate_vc · family_office · crossover_hedge · sovereign · endowment · government · venture_debt · other` | ADV private-fund flags + Form D `INVESTMENTFUNDTYPE` + entity form; `accelerator`/`studio` from the existing `program` vocabulary; `angel` from §5 | a *filed* type wins a stated one. `seed_fund` vs `venture_fund` is decided by **filed fund size**, not by self-description |
| `aum` | numeric USD | <10M · 10–50M · 50–250M · 250M–1B · 1B–10B · 10B+ | ADV 5F(2)(c) regulatory AUM; else Σ of filed fund sizes, **labelled differently** (`basis=adv_raum` vs `basis=sum_of_filed_funds`) | never mix the two bases in one number; the card says which |
| `funds_count` | numeric | 1 · 2–3 · 4–6 · 7+ | distinct `iv_fund` file numbers attached | amendments never double-count |
| `latest_fund_size` | numeric USD | bands | latest fund's **amount sold** | "sold" not "offered": offered is a ceiling a filer may never reach |
| `latest_fund_year` | numeric year | | first-sale date of the latest fund | drives `still_deploying` |
| `first_fund_year` | numeric year | | earliest attached fund | vintage/age of the firm |
| `still_deploying` | categorical | `yes_recent · quiet · unknown` | a new fund filing within 36 months | `quiet` is "no new fund filed", **never** "dead" |
| `country` / `state` / `metro` | set | | ADV main office; else Form D manager state; else site | the geo they *are*, distinct from the geo they *fund* |
| `regulatory_disclosures` | numeric | none_reported · 1–2 · 3+ | ADV Item 11 counts, linked to the official IAPD report | a filed count with a link; the mode never characterises it |
| `evidence_strength` | ordinal | single_source < two_sources < filing_backed | how many independent source kinds back the card | |

**Stated keys** — every one of these renders in the firm's own voice, and a must on one filters *what the firm
claims*, which the rail label says outright ("the firm says…").

| Key | Type | Values / bands |
|---|---|---|
| `stated_stage` | set | pre_seed · seed · series_a · series_b · growth · all |
| `stated_check_min` / `stated_check_max` | numeric USD | <100k · 100k–500k · 500k–2M · 2–5M · 5–15M · 15M+ |
| `stated_ownership` | numeric % | <5 · 5–10 · 10–15 · 15–20 · 20+ |
| `leads_rounds` | categorical | leads · follows · both |
| `geo_focus` | set | country / region tokens |
| `sector_focus` | set | the startup schema's `TECH_AREAS` vocabulary reused verbatim. Note the deliberate arity change: `tech_area` is `categorical` on a company, `set` on an investor (a firm funds many sectors). Same vocabulary, different type — so the two modes' *counts* are not directly comparable and the UI must not present them as if they were |
| `open_to_inbound` | categorical | `application_form · email · warm_intro_only · not_stated` — from the firm's own contact/apply page, with `apply_url` carried for the card's ⇢ Apply link. The single most useful field for a founder, and it exists only in the stated register |

**Observed keys** — *every one carries its denominator*, and the rail label shows it ("over the 34 of their
companies we hold").

| Key | Type | Definition |
|---|---|---|
| `portfolio_count` | numeric | distinct companies with an edge, by basis |
| `observed_stage` | set | stage / financing scale of those companies |
| `observed_sector` | set | their `tech_area` mix |
| `observed_geo` | set | their country/metro mix |
| `led_round_size` | numeric USD | sizes of rounds this firm is **stated to have led** — labelled "round sizes they led", **never** "cheque size" |
| `co_investor` | set | firms co-occurring on the same company |
| `follow_on_rate` | **dossier only — not a facet** | share of their companies that raised again ≥ 12 months after the edge's date |
| `outcome_mix` | **dossier only — not a facet** | acquired · public · shut_down · active, by vintage cohort |
| `notable_investment` | set | their largest-funded companies, for display |
| `sector_conflict` | computed at query time | how many of their portfolio companies sit in the sector the founder named — shown on the card as "already funds 3 in fintech", never stored as a firm property |

**Success metrics are not searchable, and this is the panel's unanimous call.** `follow_on_rate` and
`outcome_mix` are **not in the rail, not filterable, not sortable, and not rankable**. They appear only inside
`/investors/{id}`, in words rather than as a headline number. The reasoning is Codex's and it is the strongest
argument in the whole review: *the shape is the lie, not the digits.* A 2014-vintage seed firm did 25 deals; we
see the 7 that were US, funded, and covered; 3 exited and none are marked dead. Every gate in §5 passes — vintage
≥ 3 years, n = 7 ≥ 5 — and we print "43% acquired, 0% shut down" about a firm whose partners know they have 3
winners in 25. Printing the denominator does not repair that, because the *selection* is what is wrong.
So: the mode also **refuses to compile a success filter**. A brief that says "funds with a good track record"
comes back with a note — "track record is not searchable here; no public source supports it. The closest honest
filters are: has filed a fund recently, and has a fund a public LP reports returns for" — which is a better
answer than a plausible number. *(This is a real narrowing of the original ask, made deliberately and stated
plainly rather than quietly delivered as a worse feature.)*

**Individuals never carry computed metrics.** `follow_on_rate`, `outcome_mix`, `regulatory_disclosures` and every
return metric are **firm-only**. An `iv_person` card shows name, stated role, the edges that name them, and links
a page printed — nothing computed, nothing evaluative. Publishing "Angel X: 0% follow-on (n=5)" about an
identifiable human, from a corpus we know is partial, is a reputational claim we cannot support and will not
make. Both external reviewers raised this independently. Storage enforces it: `iv_fact` carries an entity kind
and the projector refuses a computed key on an individual.

**Returns keys — filed by a named LP, or absent**

| Key | Type | Definition |
|---|---|---|
| `lp_disclosed` | categorical | `yes · no` — does any public LP report one of their funds |
| `net_irr_best` / `net_irr_median` | numeric % | over **their funds a public LP discloses**, each figure carrying LP name, fund name, vintage, as-of date |
| `dpi` / `tvpi` | numeric ratio | same provenance rule |

An LP reports an umbrella fund ("NEA 16"); Form D reports many file numbers. `iv_return` therefore binds to a
**fund family**, not a file number, and the mapping is explicit and evidenced — an unmapped LP row stays
unattached rather than being attributed to the nearest-looking vehicle.

**One control per concept, three registers underneath** (panel objection #3, accepted). A founder searching for
seed investors must not have to know whether a firm *says* it does seed or merely *does* seed. So the rail shows
**one `stage` control**, and it matches a firm when EITHER register does — `stated_stage` from their site OR
`observed_stage` from their edges. The register is not hidden, it is reported as the **match reason** on the card
("matched seed: the firm says so" · "matched seed: 14 of their 21 dated rounds"), and a one-tap toggle on the
control narrows to a single register for anyone who wants that. The same shape applies to cheque size (stated
range OR the sizes of rounds they led) and geo (HQ OR stated focus OR where their portfolio is). This keeps §0's
promise — a stated number is never *rendered* as a filed one — while making the search actually usable.

Ranking weights follow the startup module's shape (prefer `investor_type` 0.15, `sector_focus` 0.12,
`observed_sector` 0.12, `stated_stage` 0.12, geo 0.10, `co_investor` 0.10; avoid `investor_type` 0.20), with
`center` available on the ordinal stage keys the way `stage` centres Startup Search.

---

## 5. The gates — three, each with a trap designed to pass it while being wrong

The span check and the startup module's `subject_bound` / `metric_defined` are inherited. Three are new, all
string- or SQL-level, all free, all fail-safe to abstain.

**`cohort_bound` — an outcome mix is meaningless without a vintage.** A firm whose first cheque was written in
2024 has a portfolio that is 100% "active", which renders as a 0% failure rate and is the most seductive wrong
number this mode can produce. Rule: `outcome_mix`, `follow_on_rate` and anything the UI is willing to call a
success measure are computed **per vintage cohort** (edges by year), are shown only for cohorts at least 3 years
old, and require `n ≥ 5` in the cohort. Below that: "too few companies of this vintage to say".
*Trap:* a seed firm with 40 companies, 38 of them 2024–25 vintage, must render "2 companies old enough to judge",
never "95% still active".

**And the cohort gate alone is not enough** (panel objection #2, accepted). Our edges come mostly from portfolio
pages, and **a portfolio page is a denominator the subject controls**: a firm that funded 20 companies in 2021,
buried the 14 that died and lists the 6 that lived passes `n ≥ 5` and passes the 3-year test, and we would emit
"100% still active". So outcome metrics obey a second rule — **`denominator_independent`**: an outcome mix or a
survival number may only be computed over edges whose *discovery* is independent of the firm — a Form D filing
(permanent, never scrubbed), a related-person row, or dated press. Portfolio-page edges populate the *portfolio*,
never the *denominator*, and the card labels the difference in words: "44 companies they list · 12 we can date
from filings · outcomes computed over those 12".

**`vehicle_bound` — a fund is not a firm, and most "venture capital funds" are neither.** Measured on the
2026Q2 Form D quarter (2,983 filings typed *Venture Capital Fund* by the filer):

- **59% (1,763) are SPVs** — "… a Series of X LLC", "OurCrowd (Investment in Morphisec) LP", per-deal
  co-investment vehicles. They are not funds and their manager is not a firm. Dropped by name form.
- **Naive GP-overlap clustering collapses.** Union-find on shared related persons produced two blobs of **733
  and 674 filings**. The cause is exact and fixable: the top signatories are SPV administration platforms —
  `fund gp, llc` (733), `belltower fund group, ltd.` (715), `llc sydecar` (673), and one platform employee (669)
  — who sign hundreds of unrelated vehicles a quarter. **29 signatories of 2,224 carry all the damage.**
- **The rule that works:** drop SPV-shaped names, then cluster the remainder on shared related persons whose
  **degree ≤ 8 filings per quarter**, keyed with the manager's state. Result: 1,220 real fund vehicles →
  **924 manager clusters, largest cluster 8** (Tamarack Global's four vehicles, WH Capital's four, …).

A cluster attaches to a named firm when (a) manager CIK matches, or (b) the cluster's fund name begins with the
firm's legal or brand name as a **word sequence**, or (c) a page we read on the firm's own site names the fund.

  **Clause (b) needs more than the existing helper.** `sources/investors.py:42-52 name_matches()` is a *prefix*
  test on word lists: it correctly refuses `accel` → "Accela", but it **accepts `accel` → "Accel KKR Capital
  Partners"**, because `["accel"]` is a prefix of `["accel","kkr",…]`. That is this spec's own §5 trap passing
  its own gate — caught by the code-grounded reviewer, and exactly the failure class CLAUDE.md asks us to design
  traps for. The fund-attach variant therefore requires the words *after* the firm's name to be **fund-form words
  only** (`fund · capital · partners · ventures · lp · llc · i–xx · growth · opportunities · co-invest`); a
  content word the firm's name does not contain (`kkr`, `india`, `china`) **refuses the attach**. Name-sequence matching alone
attached **28%** of a quarter's VC filings to an ADV firm — which is why clustering-then-attaching is the design
and name matching alone is not. An unattached cluster is still a searchable row; it simply has no firm card.
*Trap:* "Anthropic SPV I, LLC" must not attach to Anthropic; "Accel-KKR Capital Partners" must not attach to
Accel; the 733 Sydecar-administered vehicles must not become one firm.

**`register_bound` — a stated number may never be shown where a filed one belongs.** The projector refuses to
write a stated value into a filed key, and the card refuses to render a stated figure without its ▢ and its
"the firm says" framing. A firm's homepage "$500M fund" and a Form D reporting $180M sold are **both** displayed,
filed first.
*Trap:* a firm whose site says "we manage over $1B" while ADV reports RAUM of $210M must show $210M as `aum` and
the $1B only as a quoted claim.

And one inherited rule stated again because it bites hardest here: **absence is never a value.** No fund filing
found ≠ no fund. Not in the ADV register ≠ not a real investor (they may be non-US). No LP disclosure ≠ bad
returns.

---

## 6. Storage, endpoints, jobs

`apps/api/investors/` — a detached feature exactly like `apps/api/startups/`, its own tables, mounted behind
`EIGEN_INVESTOR_SEARCH=1`, OFF a true no-op. It mounts as a **sibling** of the startups block in `app.py`
(~`:1860-1900`), not nested inside it the way DeepDive is (`app.py:1877-1886`, which is gated on
`EIGEN_STARTUP_SEARCH` too) — investor mode must not require startup mode. Wiring: its own
`investor_search_enabled()`, its own lazy asyncpg pool (a 4th pool on the same DSN), store, router, a distinctly
named orphan-jobs startup hook, an `"investor_search_enabled"` key in `/config` (`app.py:1957`), and — if a
`/investors` URL is wanted — a redirect stub like `apps/web/startups.html`, since the mode itself lives inside
`apps/web/index.html`.

```
iv_firm     id (domain) · name · legal_name · crd · cik · slug · site · hq_* · type · status · crawl · embedding
iv_fund     file_num PK · firm_id? · name · fund_type · offered_usd · sold_usd · first_sale · investors_n
            · min_investment · city · state · persons jsonb · accession · match_method · match_note
iv_person   id · firm_id? · name · title · role · links jsonb {linkedin, x, site} · basis · source_url · quote
iv_edge     firm_id · company_id · basis (portfolio_page | press_round | company_site | formd_person | lead)
            · role · round · event_date · source_url · quote          -- the portfolio, one row per evidenced edge
iv_fact     firm_id · key · value · number · display · register (filed|stated|observed) · basis · provenance
            · source_url · quote · as_of · denominator · confidence   -- the rail's read model
iv_return   fund_key · lp · fund_name · vintage · committed · contributed · distributed · net_irr · dpi · tvpi
            · as_of · source_url
iv_alias    slug PK · canonical_id · basis · source_url      -- the join key's registry (see 2)
iv_firm_rel from · to · kind (renamed|spun_out|affiliate) · effective · source_url
iv_map / iv_map_revision / iv_list / iv_job     -- the su_* twins, same share-token model
```

`iv_fact.register` and `iv_fact.denominator` are the two columns that make §0 enforceable in SQL rather than by
convention.

**The job machinery is not reusable as-is.** `_job`, `_progress` (heartbeat *and* cancel), `orphan_running_jobs`
and `start_job` are all literal `su_job` SQL bound to `StartupStore` (`pipeline.py:63-90`, `:897-927`), and the
routes add a 30-minute stale watchdog (`routes.py:513`). A second module either duplicates ~80 lines and two
copies of a cancel/heartbeat contract that must not drift, or a small generic `jobs.py` is factored out first,
parameterised on table name + store factory. **Decision: factor it out**, port startups to it in the same change,
and keep `test_job_heartbeat.py` green as the contract test — one implementation is cheaper than two that diverge.

**Endpoints** (mirroring `apps/api/startups/routes.py`): `POST /investors/compile` · `POST /investors/evaluate` ·
`POST /investors/group` · `GET /investors/coverage` · `GET /investors/{id}` (the dossier: funds, people,
portfolio, observed metrics with denominators, LP returns, sources) · maps CRUD + navigate + share ·
`POST /admin/investors/jobs` with `X-Admin-Token`.

**Jobs**, in dependency order, and all of them free unless marked:

| kind | does | spends |
|---|---|---|
| `adv` | download the two monthly ADV zips → `iv_firm` (name, CRD, CIK, site, HQ, type flags, AUM, disclosures) | — |
| `registers` | the non-US registers of §3b (FCA, ESMA, SEBI AIF + VCF, MAS, ASIC, ADGM/DFSA) → `iv_firm` with `basis=<register>`; one small adapter per register, each independently skippable | — |
| `networks` | angel-network directories (ACA, UKBAA, EBAN, and the regional networks) → `iv_firm(type=angel_group)` + their published members | — |
| `funds` | re-parse the 30 Form D quarters keeping the pooled-fund fields → `iv_fund` | — |
| `attach` | `vehicle_bound` fund→firm attachment | — |
| `link` | firm ↔ the startup index's `investor` slug vocabulary; firm ↔ existing portfolio pages | — |
| `sites` | resolve + crawl firm sites (robots-first, paced) | — |
| `portfolio` | read every resolved firm's portfolio page structurally → `iv_edge` (+ new companies for the startup index) | — |
| `people` | team pages → `iv_person` with stated links; Form D related persons → GPs | — |
| `angels` | harvest named individuals from the 32,101 company pages we already hold, from press, and from Form D related persons → `iv_firm(kind=individual)` + edges | — |
| `lp` | ingest the public-pension performance releases → `iv_return` | — |
| `derive` | recompute all observed facts with denominators and cohorts | — |
| `terms` | **model call**: read stated stage / cheque / ownership / geo / leads-or-follows off crawled firm pages | ~$0.01 / firm |
| `embed` | firm embeddings for the semantic leg | ~$0.0001 / firm |

**Budget.** Everything structural is free. The only real spend is `terms` over ~5,000 VC/PE firms with a
resolvable site ≈ **$50**, plus embeddings ≈ $1, plus per-search compile calls (cached by brief hash). Per the
credit directive: validate on 25 firms, report precision, then tranche in 500s with a review between; the job
refuses past `max_usd`, as `extract` already does.

---

## 7. Build strategy

The order is chosen so that **every step ships something usable on its own** and **every step is measured before
the next one is funded**. Nothing here needs the step after it to be worth having.

### Step 0 — the free US spine (no model spend)
`adv` → `funds` → `attach` → `link` → `derive`, then a bare mode behind `EIGEN_INVESTOR_SEARCH=1`.
Produces ~7,400 VC/PE-managing firms with type, AUM, fund history, HQ, plus the ~5,000 investor edges the startup
index already holds. **Ship criterion:** `vehicle_bound` precision ≥ 95% on a hand-checked 100-cluster sample,
and a coverage table published per key. **Ship criterion 2:** zero firms merged on a shared domain — the
`linkedin.com` case is a regression test, not a note.

### Step 1 — the card and the rail ✅ BUILT (2026-09-09)
The mode's UI: coverage banner, ported rail with the one-control-three-registers behaviour, cards, drawer, and
the cross-mode "see their portfolio in Startups" jump. Investor Maps reuse the `su_map` share-token model.
Mobile pass at ≤400px before it is called done. **This is the step that makes the data a product**, so it comes
before more data, not after.
*Coordination note: `apps/web/index.html` is a single 9,457-line file that other work is actively editing, and
per-mode IIFEs mean anything shared must be defined at true top level (the DeepDive `usd()` lesson). The investor
mode lands as one contiguous block, added when the file is quiet.*

### Step 2 — portfolio, people, links (free) ✅ BUILT (2026-09-10)
`sites` → `portfolio` → `people`. Firm sites crawled with the existing robots-first, paced fetcher; portfolio
pages read structurally; team pages give people plus the LinkedIn / X / personal links they print. This is where
"links to all startups they fund" and "their main people" actually arrive, and it back-fills new companies into
the startup index as a side effect. **Measure:** site-resolution rate, portfolio-page parse rate, people-per-firm,
link-extraction precision on a 25-firm sample.

### Step 3 — the rest of the world (free, one adapter at a time)
`registers`: FCA (UK) → SEBI AIF + VCF (India) → MAS (Singapore) → ASIC (Australia, CSV on data.gov.au, verified)
→ ESMA (EU) → ADGM/DFSA (UAE). Then `networks` for the angel groups (ACA, UKBAA, EBAN, and the regional networks).
Each adapter reports row count, duplicate rate against the existing spine, and geo coverage before the next starts.
*The panel argued for cutting this from v1 and owning a US-only product. **Overruled, deliberately:** the owner's
goal is that founders come here, and a founder in Bangalore, London or Dubai is not served by a US register. The
compromise is sequencing — one adapter at a time, each independently skippable — not deferral.*

### Step 4 — stated terms (the first real spend)
`terms` reads stage focus, cheque range, ownership target, geo focus, leads-or-follows and the application path
off crawled pages. **Validate on 25 firms, report precision, then tranche in 500s with a review between**, per the
credit directive. Projected: ~5,000 firms with a resolvable site × ~$0.01 ≈ **$50** for one pass, plus ~$1 of embeddings — but
"$50 total" was wrong: a prompt or schema change re-spends it, and quarterly site refreshes re-spend the changed
subset. Two schema iterations plus an annual refresh is realistically **low hundreds of dollars a year**, which
is still small and should be stated as what it is. The
job refuses past `max_usd`, exactly as `run_extract` already does.

### Step 5 — angels at scale (spends; v1 said free, wrongly)
`angels` harvests named individuals from the 32,101 company sites we already hold, from press, and from Form D
related-person rows, applying the corroboration rule and the individual-PII rule. Angel *networks* arrive with
Step 3; the individuals arrive here.
**Cost correction (Codex, accepted):** the Form D related-person leg is genuinely free and structured, but
pulling named angels out of arbitrary marketing copy on 32,101 company pages is a model job — the same 3-gate
extractor the founder path uses (`extract.py`). A regex over "backed by" prose has either unusable precision or
unusable recall, and v1 marked this free by ignoring that choice. Budget it, validate on 25 companies, tranche it.
Also: no personal emails, phone numbers or non-public addresses are stored for an individual, ever — only links
already printed on a public page.

### Step 6 — returns, honestly scoped
`lp` starts with whatever a public pension publishes **machine-readably**, and treats the PDF-only releases as a
small, human-verified import rather than an automated parser. *(Panel objection #5, accepted: CalSTRS/CalPERS
publish reformatted annual PDFs, and calling that "a small parser" was wrong. Panel also argued to cut returns
entirely as founder-irrelevant — **partly accepted**: returns move behind everything else, but they stay, because
they are the only honest answer to a question the owner asked directly, and the diligence half of the audience
does ask it.)* Every figure carries LP name, fund name, vintage and as-of date, or it does not render.

### Step 7 — 13F, patents-style long tail
Crossover and growth holdings from the 13F data sets; Wikidata as a last-resort identity fallback.

### What the panel wanted cut, and what I kept
Both reviewers argued for a leaner v1: drop returns, drop non-US registers, drop angel cards, drop maps.
**Kept, with reasons:** non-US registers (Step 3) — the owner's goal is that founders come here, and a founder in
Bangalore or London is not served by a US register; angels (Step 5) — explicitly reaffirmed by the owner after
the risk was put to them, and now built with a corroboration rule and a hard no-computed-metrics rule for
individuals; maps — they are a near-free reuse of `su_map`. **Accepted:** returns move to Step 6, behind
everything; success metrics leave the rail entirely; angel cards get evidence requirements rather than volume.

### What is deliberately NOT built
Any IRR we did not read off a named LP's release. Any returns or multiple estimate. Ownership percentages not
stated by the firm. Cheque sizes inferred by dividing a round by its investor count. A league table of firms by
performance. Financial metrics computed about a private individual. Each of these renders as a gap with its
reason, which is itself a usable answer.

## 8. Evals

A held-out set in `evals/`, one case per gate trap above, plus: a firm with no ADV registration (non-US) must
render with filed keys unknown and no implication of smallness; a firm with two brands (Sequoia / Peak XV) must
be two cards; a fund of funds must not have its LPs' portfolios attributed to it; an angel named by four
companies with no profile source must render as an un-promoted name, not a person card.

---

## 9. Open items and things that are red before we start

- **Both kernel guardrails are RED today, for different reasons, and neither is our doing.**
  `tools/check_kernel_invariant.sh` fails on genuine tech vocabulary that has leaked into kernel *prompts*
  (`research/react.py:116-118` puts "patent" and "moat" in a kernel prompt string; also `research/web_coverage.py`,
  `research/deep_company.py`, `retrieval/materialize.py`). Separately, the pytest that claims to mirror it
  (`packages/kernel/eigen_kernel/conformance/test_kernel_invariant.py:12-17`) carries a **stale banlist from the
  pre-eigen lineage** (`docket|puco|ohio|rate case|roe|filing|…`) and currently fails on the string **"Jane Roe"**
  in a test fixture — so CI's guardrail is not enforcing the documented invariant at all. Per CLAUDE.md's "never
  normalize a failing test": these are two tracked bugs, not background noise. Investor work's exit criterion is
  **no new violations**, and neither gate inspects `apps/api/**` anyway (`check_kernel_invariant.sh:13`,
  `check_kernel_imports.py:16`).
- **Two more red tests, verified pre-existing at clean HEAD on 2026-09-09** (checked in a detached worktree, so
  neither this work nor another session's in-flight edits are implicated):
  `research/test_explore_legs.py::test_flag_on_enumerative_behavior_unchanged` and
  `research/test_react.py::test_zero_evidence_answer_converts_to_search` (the ReAct loop returns an ungrounded
  empty answer where the test asserts it recovers by searching). Filed, not normalised.
- **`su_company.id` is not purely a domain.** `pipeline.py:502` mints `cik:<n>` for Form D issuers with no
  resolvable site, so a firm↔company join on domain silently misses that population. The edge table joins on the
  company id, whatever its shape.
- **The `su_financing` precedent for "file number dedups amendments" does not exist as v1 claimed**: uniqueness is
  `(company_id, kind, file_num, round_name, event_date)` (`store.py:80`), so an amendment with a different sale
  date creates a second row. `iv_fund` must dedup on file number itself, deliberately.
- **`max_usd` is per job invocation, not cumulative** (`pipeline.py:305` and siblings). A tranche plan of "500s
  with a review between" is enforced by the operator, not the gate. If tranching matters, a running-spend ledger
  is a small, worthwhile addition.
- **The compile cache lives in the route, not in `compile.py`** — a new module gets the model call for free and
  must re-implement the cache.
- **Unmeasured, and measured before it is trusted:** what share of our existing investor edges come from
  independently-discovered sources rather than portfolio pages. That number decides how much of §5's
  `denominator_independent` rule can actually fire on day one. It is a SQL query, and it is the first thing
  Step 0 reports.

---

## 10. What Step 0 measured, once it was built (2026-09-09)

The spine is built and runs end to end against Postgres: `adv → funds → attach → link → derive`, plus the
search endpoints. Numbers from a full local run over the September ADV files and the 2026Q2 Form D quarter:

| | |
|---|---|
| Firms ingested | **7,424** venture/PE-managing advisers, every one typed (3,240 venture · 4,184 PE) |
| Firms with no website | 2,881 — all present, none dropped, because the id is a minted slug |
| Shared-domain registrants | **323 affiliate relations** recorded instead of merges |
| Fund vehicles (one quarter) | 11,483 pooled filings; 2,423 SPVs excluded; 5,431 venture/PE vehicles clustered into **2,113 managers**, largest cluster 11 |
| Attach | **242 clusters / 392 funds** by evidenced path (238 name-sequence, 4 CIK) |
| Link | binds curated brand slugs and refuses unknown ones (`totally_unknown_fund` stayed unbound, by design) |

Four things the build changed in the design, each because running it showed the spec was wrong:

1. **A shared domain must not merge two registrants.** a16z.com is the website of both Andreessen Horowitz and
   *a16z Perennial Management* — different advisers, different asset classes. Merging them handed the `a16z`
   card to the wealth arm and typed it `pe_fund`. Now only CRD merges; a shared domain writes an `affiliate`
   relation. **Curated brand slugs are reserved before ADV mints anything**, so `a16z` stays the brand's.
2. **An affiliate's register flag may not type the brand.** Having built affiliate-based typing, it was removed:
   the evidence's subject (Perennial) is not the claim's subject (a16z). A brand with no filing of its own shows
   **no type** until one of its own funds attaches. This is §0's congruence rule applied to our own convenience.
3. **The name gate needed a recall fix and then a new guard.** ADV records the manager ("UP PARTNERS MANAGEMENT
   COMPANY, LLC") while the fund is filed under the brand ("UP Partners Fund II, LP"), so full-legal-name
   matching attached 50 of 2,113 clusters. Stripping the manager tail took it to 244 — and a hand-check of 40
   found every doubtful case in one class: a **one-word brand** ("Reach", "Eclipse", "Ascend"). One-word brands
   now require a state match AND uniqueness across all firms; a brand two firms share names neither. 244 → 230.
4. **Retrieval is hybrid, and the startup mode's is not.** Startup Search fuses *recipes* by RRF; there is no
   lexical leg anywhere in it. Investor Search adds one: a Postgres FTS index over names, city and domain, plus
   an alias arm, reciprocal-rank-fused with the vector leg (`store.hybrid`). The reason is concrete — a vector
   index answers "climate infrastructure funds in Europe" well and **"8VC" not at all**, because a short proper
   noun has no semantic signal, and no embedding of a name will ever take "andreessen horowitz" to `a16z`. RRF
   rather than a score blend because cosine similarity and `ts_rank` are not on comparable scales. The fused
   score maps back onto `sim`, so the kernel evaluator is untouched, and `found_by` travels to the card.

**Step 1 shipped with Step 0's spine.** `POST /investors/compile`, the inline mode, the register-grouped rail,
the cards and a named order control are live behind the flag. Two things only the rendered page revealed:
with no words the kernel breaks a score tie on the id string, so results came back alphabetically (010118
Management above 5AM Ventures) — there is now an explicit, labelled order defaulting to latest fund vintage,
and the store's candidate slice is ordered the same way, since *which* 400 rows are fetched is itself a
ranking decision. And every card shouted a red list of missing registers; a gap is not a failure, so it is
said once, quietly. Verified at 390px and 1280px.

Still deferred: `api/startups/pipeline.py` is **not** yet ported onto the new generic
`api/jobs.py` — that port touches a module with live ingest running against it, so it is a tracked follow-up
rather than a drive-by.

---

## 11. Step 2 and the Advisor, as built (2026-09-10)

Four free jobs — `sites`, `people`, `profiles`, `portfolio` — plus a fifth surface, the **Startup Advisor**.

**The team-page parser is the substance of Step 2**, and the design changed twice under measurement:

- v1 anchored on LinkedIn URLs. Measured on eight real team pages, that reads almost nobody: Bessemer prints
  **zero** LinkedIn links, USV zero, Initialized one, Craft four. What every one of them prints is a link to
  the person's own page whose slug is their name — `/team/david-sacks`, `/people/fred-wilson/`,
  `data-name="byron deeter"`. That became the primary anchor; a heading followed by a known role catches the
  pages that link nothing at all.
- The social links live **one hop away**, on each person's own page, where the binding rule can loosen because
  the subject is already known. What remains is telling their handle from the firm's, which sits on the same
  page every time: `davidoliversacks` binds David Sacks, `craft_ventures` binds nobody. 87% of profile fetches
  yielded a LinkedIn or an X handle.

Two parser bugs worth keeping as rules: names are matched **per element**, because flattened HTML reads
`<h4>David Sacks</h4><p>Partner</p><h4>Elyse Davis</h4>` as one four-token name; and role words are in the
not-a-name stoplist, or the pattern swallows the title beside the name.

**The Advisor** answers "who will fund me" as the nearest knowable thing — who has already funded companies
like yours, at your stage, in your geography, and has filed a fund recently — with each row's signals labelled
by register. Two rules keep it from becoming a list of everyone: *still deploying alone is not advice* (true of
thousands of firms; ranking on it yields an alphabetical list wearing the costume of a recommendation), and
*candidates come from one filter per signal, fused by RRF* — the first version passed the signals as
preferences with no filter, which re-ranks a prominence-ordered slice and never retrieves the firm that
actually matches. A deck's NAMED round is read; the amount it asks for is not.

Conflicts — the firm already funds something in your sector — are shown as a warning at the foot of the card,
because that is the one place a strong match argues against reaching out, and our sector labelling is on both
sides of it.
