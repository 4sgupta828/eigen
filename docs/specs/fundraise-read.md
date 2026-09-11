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

## 0a. ARCHITECTURE: DeepDive becomes the superset. One reader, deeper.

Two corrections stand behind this section; both are recorded because the reasoning matters more than
the conclusion.

**First correction (mine).** The original draft proposed a separate reader that re-crawls the site,
justified by the claim that ICP, pricing, named customers and founder prior employers "are not
sections DeepDive produces". **That was false** — asserted without grepping for it:

```
assemble.py:217  named_customers()          assemble.py:225  pricing()
assemble.py:444  prior employers            startups/extract.py:81  prior_companies
extract.KINDS    what_they_sell, how_they_make_money, who_buys, pricing_terms,
                 named_customer, named_partner, differentiator, competitor, milestone
```

**Second correction (the owner's, and the better one).** The reviewers argued between "build
separately" and "lens the output". Both accepted a premise neither questioned: that DeepDive stays as
it is. The owner's call is the third option — **make DeepDive a superset.** The signals a fundraising
read wants are mostly signals a DILIGENCE read wants too. Regulatory clearance de-risks a market for
an acquirer exactly as it does for an investor; business model determines capital intensity for both.
Splitting them would have built two shallow readers where one deeper one serves everyone.

**So: DeepDive is extended, not forked, and not duplicated.**

### What is added to DeepDive itself (public sources, benefits every reader)

- `extract.KINDS` gains **`regulatory_status`** — FDA 510(k)/PMA, ClinicalTrials.gov phase, FCC ID,
  SOC 2 / ISO 27001 / FedRAMP. `filed` where it joins a registry entry, `stated` where only the
  company's own compliance page says it. This is diligence-grade evidence that happens to matter
  enormously to an investor.
- **`how_they_make_money` is surfaced to the contract.** It is already extracted and goes nowhere.
- **Hiring SHAPE, not headcount.** "5 engineers, 0 sales" says builder-phase; a count says nothing.
- **Prior employers promoted** from a field inside Key people to something the lens can read directly.

### What does NOT go into DeepDive: the deck

A dossier lives in `su_dossier`, keyed by `company_id`, carrying a `share_token` — **one shared,
versioned artifact per company**. A pitch deck is a private document. Two consequences, and they are
not negotiable:

1. Deck claims in a shared dossier mean **sharing the dossier leaks the deck**.
2. One dossier per company means **one founder's deck would surface for anyone else diving that
   company** — including an investor, or a competitor.

So the deck is read by a separate, owner-scoped path, and its claims live with the founder's
SearchMap, never in `su_dossier`. It still imports `subject_bound` and `metric_defined`, because a
deck claim must clear the same congruence bar as a site claim — and it carries its own register:
a deck is a company making claims about itself in a document written to raise money, which is the
most interested source we will ever read.

### Depths

DeepDive's existing three are reused as they are. No second stack, no second crawling policy, no
second basis string. The fundraising read is `held` or `read` on the dossier, plus the deck if one
was given.

## 1. The honest constraint, restated## 1. The honest constraint, restated## 1. The honest constraint, restated

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
| **Business model** | capital intensity, fund thesis fit | **yes** | `how_they_make_money` — already extracted, and never passed to the contract |
| **Regulatory / compliance standing** | go-to-market de-risking | **yes** — *filed* against a registry, *stated* from a compliance page | FDA 510(k), ClinicalTrials.gov, FCC OET; SOC 2 / ISO 27001 / FedRAMP claims on their own site |
| **Raise intent and terms** | what they are actually asking for | **yes**, from a deck, as *stated* | the deck — the one source DeepDive has no path to |
| **Use of funds / next milestones** | what the money buys | **yes**, as *plans* — never as facts | deck, explicitly registered as intent |
| **Hiring shape** | builder phase vs go-to-market phase | **yes** | ATS role distribution, not headcount |
| ~~Open-source traction~~ | — | **cut** | feeds no ranking axis |
| ~~Research output~~ | — | **cut** | feeds no ranking axis |
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

## 8. Panel outcome (Codex + Gemini, 2026-09-11)

**Agreed by both.**

- **Prior-employer extraction is defensible; scoring on it is not.** The line is between *reading a
  fact* and *inventing a preference*. "Founder X worked at Stripe" is quotable and STATED. It becomes
  fabrication only when fed to something that assumes a fund prefers Stripe alumni. Precedent already
  in the codebase: `iv_person` is kept for transparency and excluded from the score.
- **Refusing revenue, burn, runway and cap table is correct**, and useful rather than merely strict:
  it forces the interface to say "we cannot see your revenue — tell us and the match improves",
  which is honest and actionable.
- **Investor network value stays unranked.** Ranking it needs a proxy — follower counts, board seats
  — which is the hallucinated synthesis this product exists to refuse. It becomes a question in the
  plan, named as one.

**Where they split, and how it was resolved.**

Gemini endorsed the original "build a separate reader". Codex argued the reasoning was weaker than it
looked and cited the code above. Codex is right; Gemini was answering a question whose premise —
that DeepDive lacks these sections — I had supplied and which is false. §0a is rewritten accordingly.

**Signals added by the review:** business model (already extracted, never used), regulatory and
compliance standing, raise intent and terms, use of funds as plans, hiring shape.
**Signals cut:** open-source traction and research output — neither moves a ranking axis, and
extracting a signal that changes no outcome is work that only looks like depth.

## 9. Evaluation — cases designed to pass a naive fundraising reader while being wrong

1. **The case-study trap.** The site reads "Customer Acme increased revenue $50M and raised a Series
   C." A naive reader files that as the STARTUP's stage and milestone. `subject_bound` must reject it:
   the claim names another organisation.
2. **The unitless hype metric.** "Growth is up 5,000%." No base, no metric word. `metric_defined`
   must drop it rather than log a milestone.
3. **Intent versus evidence on stage.** The deck says Seed; a filed Form D shows Series A six months
   ago. Both are kept, `stage_disagrees` is true, and neither overwrites the other.
4. **The stale extrapolation.** A two-year-old press figure presented as current traction. It must
   carry its date, or not appear.
5. **The founder-pedigree booster.** A team page full of famous employers must change the ranking by
   exactly nothing.
6. **The logo wall misread as investors.** A "trusted by" customer wall parsed into `existing_investors`
   would poison the single strongest matching signal with companies that never invested.
7. **"We use AI".** A crypto company mentioning AI once must not be tagged into AI-infra funds;
   extraction scopes to what they SELL.
