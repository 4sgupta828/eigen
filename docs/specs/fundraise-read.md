# Reading a startup with fundraising intent

Status: DRAFT for panel review, 2026-09-11. Companion to `investor-matching.md`, which covers the
other side of the join (how investors are ranked once we know what the startup is).

## 0. Why a second lens over the same dossier

DeepDive already resolves a company, discovers it on the web when we do not hold it, crawls its own
site, extracts claims with a model call per page, and gates every claim on a verbatim quote plus
subject congruence plus metric definition. It is projected and capped before it spends.

It is written for **diligence on a company**: is what they say true, and what is missing. A founder
asking *who should I raise from* needs a different reading of the same gated claims — and an investor
deciding whether to take the meeting is looking for things a diligence dossier does not foreground.

`from_dossier.py` is the first cut of that lens: existing backers, round history, team, milestones,
hiring. This spec is about making it **deep enough to matter**.

## 0a. ARCHITECTURE: a separate reader. DeepDive is not modified.

Decided before drafting: **DeepDive's pipeline is not touched.** It is a live, tested, cost-gated
diligence feature and a fundraising lens has no business changing its prompts, its sections or its
store.

Three options were on the table:

| | | |
|---|---|---|
| **A. Consume its output** | call `POST /deepdive`, re-read the dossier | what `from_dossier.py` does today. Zero risk, and permanently limited to what a DILIGENCE extraction happened to surface. ICP, pricing shape, customer names and founder prior employers are not sections it produces. |
| **B. Reuse its primitives** | a separate module importing `deepdive/gates.py` and the shared site crawler, with its own fundraising-intent extraction, its own prompts, its own store | **chosen** |
| **C. Independent implementation** | rebuild crawling, gating, costing | rejected: it would fork the congruence gates, which are the part that must never diverge |

**B**, because the thing worth sharing is the DISCIPLINE, not the output. `subject_bound` and
`metric_defined` are the gates that stop a customer testimonial on a company's own case-study page
becoming a claim about that company, and stop a number whose metric word is absent from becoming a
metric. A fundraising reader needs exactly those gates and a different set of questions.

Concretely:

- **Shared, imported, unchanged:** `deepdive/gates.py`, `startups/sources/site.py` (one crawling
  policy in this codebase, not two), the projection-and-cap discipline.
- **New and separate:** extraction prompts written for a raise, the fundraising profile shape, its
  store rows, its routes.
- **Untouched:** every file under `apps/api/deepdive/`. If this spec ever requires a change there,
  that is a signal the lens is wrong, not that DeepDive is.

The cost of B is one more crawl of the same site when a founder has already run a dive. Accepted:
caching across two features whose depths and freshness rules differ is a worse problem than a second
fetch, and the crawler is paced and robots-first either way.

## 1. The honest constraint, restated

`investor-matching.md` §1 measured the other side: observed sector is known for 0.8% of 7,453 firms,
observed stage for 0.6%, and the stated register is empty. A richer read of the STARTUP does not fix
that. What it does fix is the half we control completely — the startup side is one company, its own
site, and public filings, so depth here is achievable in a way that depth across 7,453 firms is not.

That asymmetry should shape the whole feature: **be precise about the startup, honest about the
index, and let the plan carry what the ranking cannot.**

## 2. What an investor actually looks for, and what we can ground

The test for every row is not "would an investor care" but "can we show the words it came from".

| Signal | Investor reads it as | Can we ground it? | Source |
|---|---|---|---|
| What it builds, for whom | category and ICP | **yes** | own site, gated claims |
| Named customers | commercial proof | **yes**, as *stated* | customers page, with attribution |
| Published pricing | model maturity, ACV shape | **yes**, as *stated* | pricing page |
| Round history | stage, momentum | **yes**, *filed* where Form D exists | filings, press |
| Existing backers | who has already underwritten them | **yes** | dossier Investors section |
| Founder background | pattern-matching on prior work | **partly** — prior employers are quotable; "quality" is not | team page, public profiles |
| Hiring velocity | growth, and what they are building next | **yes**, as open roles — never as headcount growth | ATS |
| Open-source traction | developer pull | **yes** | GitHub stars/forks, as *observed* |
| Research output | technical depth | **yes** | papers, patents (application vs grant kept apart) |
| Revenue / ARR | the number everyone wants | **NO** | refused: DeepDive refuses a revenue integer for a private company and this must not undo it |
| Burn, runway, cap table | the other numbers everyone wants | **NO** | not public; asking a model to infer them is fabrication |
| "Momentum" / "traction strength" | narrative | **NO** | an assessment, not a fact |

The last three rows are the spec's spine. A fundraising lens is exactly where the temptation to
invent them is strongest, because they are what the meeting is about.

## 3. What a startup should look for in an investor

The mirror image, and the same test applies.

| Dimension | Groundable from | Coverage today |
|---|---|---|
| Writes cheques at this size | `iv_fund.min_investment`, size / investor count | 27.5% have fund data |
| Has funded this category | `iv_edge` + our sector labels | **0.8%** |
| Leads or follows | stated, occasionally observed from round roles | ~0% |
| Still deploying | latest Form D filing date | 22.3% |
| Conflict with a competitor | `iv_edge` against the startup's sector | 0.8% |
| Network value, operator background, helpfulness | **nothing we hold** | — |

The last row is what founders most want ranked and is the least groundable thing on either side.
This spec's position: it is not scored, not estimated, and not silently omitted — it is named as a
question to ask a partner directly, in the plan.

## 4. Depth, and what each costs

Mirrors DeepDive's three depths rather than inventing new ones.

- **held** — free. What we already hold plus keyless public sources. Enough to say whether we know
  the company at all, and to populate backers/rounds when we do.
- **read** — a deeper crawl of the company's own site, one model call per page, every claim gated.
  This is the depth a fundraising read should default to when the founder has asked for it, because
  the site is where ICP, pricing, customers and team live.
- **full** — adds the bounded web read for rounds and coverage the site does not carry.

Every depth above `held` is projected and gated before spending, as DeepDive already does. A
fundraising read must not become a back door around that.

## 5. Output: a fundraising profile

Two halves, and the second is not optional.

**What we found** — each field with its verbatim quote and source, absent fields listed as unknown:
company, one-liner, ICP, category, geography, round history, existing backers, team with prior
employers, named customers, pricing presence, hiring, open-source and research signals.

**What we could not establish** — explicitly, as a list. Revenue, burn, runway and cap table appear
here permanently, because they are not public and we will not infer them.

## 6. What this feeds

- `contract_from()` → sectors, geo, stage (claimed AND evidenced, never merged), co-investors.
- The plan → the questions our index cannot answer, with the coverage numbers stated.
- A SearchMap → the reading, the plan and the list as they stood.

## 7. Not investment advice

Unchanged from `investor-matching.md` §6. The posture is *who has already done this*, never *who will
say yes*, and never how much to raise. A fundraising lens makes that line easier to cross, which is
why it is restated here.

## 8. Questions for the panel

1. Is the ground/refuse split in §2 right? Specifically: is founder prior-employer extraction
   defensible, given both reviewers previously refused founder-based *scoring*?
2. Is there a signal investors weigh heavily that is genuinely groundable and missing from §2?
3. §3 says network/value-add is unrankable and becomes a question in the plan. Is that the right
   call, or a cop-out?
4. What should `read` depth extract that DeepDive's diligence pass does not already?
5. What in this spec is not worth building?
