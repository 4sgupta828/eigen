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

### A deck makes the reading ACCOUNT-PRIVATE, and the interface must say so

A dossier lives in `su_dossier`, keyed by `company_id`, carrying a `share_token` — **one shared,
versioned artifact per company**. A pitch deck is a private document. Two consequences follow, and
neither is negotiable:

1. Deck claims inside a shared dossier mean **sharing the dossier leaks the deck**.
2. One dossier per company means **one founder's deck would surface for anyone else diving that
   company** — an investor, or a competitor.

**The rule: if a deck is supplied, the resulting reading is private to the account that supplied it.**

Concretely:

- The **public dossier is never written from deck content.** It stays exactly what it is today: what
  public sources say, shareable, one per company.
- The **deck-enriched reading is a separate, owner-scoped artifact**, stored against the account and
  carried in that founder's SearchMap. It is not reachable by `company_id`, has no share token, and
  never merges into the public record.
- Deck claims still pass `subject_bound` and `metric_defined` — the same congruence bar as a site
  claim — and carry their own register: a company making claims about itself, in a document written
  to raise money, is the most interested source we will ever read.

**The interface must state this where the deck is attached, not in a settings page or a policy.** A
founder uploading a confidential deck is entitled to know, at the moment they upload it, exactly what
becomes of it. Required copy, at the upload control and again on the resulting reading:

> Attaching a deck makes this reading private to your account. It is not shared, not added to the
> public record for your company, and not visible to anyone else who looks that company up.

And the corollary, which must be equally visible: a reading produced **without** a deck, from public
sources only, is the ordinary shareable kind. The difference between the two states is never implied
by a subtle badge — it is stated in words, because a founder guessing wrong about this is the one
failure in the feature that cannot be undone.

### Depths### Depths

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

## 10. Worked scenarios, run against the real scorer

Not reasoned about on paper — executed through `reasons_for` / `penalties_for` as they stand today
(2026-09-11). The numbers below are what the code actually returns.

### A. UK pre-seed hardware. Technical founders, no backers, capital-intensive.

```
US seed fund, huge, generalist              fit=0.000  axes=[]
UK deep-tech specialist (the right answer)  fit=0.000  axes=[]
```

Both zero. The right answer ties a generalist, because we hold neither firm's sector nor geography.
Worse, nothing in the model knows that **hardware and software need different amounts of money** —
capital intensity is not a dimension, so a fund that writes $500k cheques and one that writes $15M
look identical to a founder building a reactor.

### B. US Series A devtools, seed led by Amplify. Who leads the A?

```
Co-invests with Amplify + sector   fit=0.877  axes=[sector, co_investor]
Sector only                        fit=0.460  axes=[sector]
Backs a direct competitor          fit=0.000  axes=[sector]   penalised: already funds your sector
```

This one works. The ordering is right and the conflict is correctly last. But the founder's actual
question — *who **leads** an A after a seed led by Amplify* — is unanswerable: lead-versus-follow is
not an axis and `leads_rounds` has effectively no coverage.

### C. Seed medical device with an FDA 510(k) clearance.

```
Health specialist   fit=0.948  axes=[sector, stage]
```

A good score for the wrong reason. **The 510(k) — the single most de-risking fact this company owns —
changes the ranking by nothing.** Neither side has a regulatory dimension.

### D. Bootstrapped, revenue, never raised institutionally.

```
Generalist SaaS fund   fit=0.455  axes=[sector]
```

The strongest signal we hold, `co_investor`, is **structurally unavailable to every founder who has
never raised** — which is precisely the founder most likely to use this feature. This is not a
coverage gap that time fixes; it is a design flaw in relying on that axis.

## 11. Dimensions these scenarios discovered

Each is groundable, and none is currently modelled.

| Dimension | Why it decides a match | Source | Scenario |
|---|---|---|---|
| **Capital intensity** | hardware, bio and infra need cheques software does not. A fund's typical cheque against the round's shape is a fit question, not a filter | `iv_fund.sold_usd / investors_n`, joined to `how_they_make_money` | A |
| **Round progression** | "who led the round *after* a seed led by X" is the real question at every stage above pre-seed | `iv_edge`: same company, later `round_name`, different firm — **we already hold this and never query it** | B |
| **Lead vs follow** | a founder needs someone to *lead*; a list of followers is not a round | `iv_edge.role`, where present | B |
| **Regulatory fluency** | a fund that has taken companies through FDA or FedRAMP understands the timeline; one that has not will misprice it | portfolio companies' `regulatory_status` (the new KIND), joined through `iv_edge` | C |
| **First-round behaviour** | which firms actually lead FIRST institutional rounds, for founders with no cap table | `iv_edge` where the company has no earlier round | D |
| **Geographic coverage bias** | Form ADV is a **US register**. Non-US funds are not merely unknown, they are *systematically* under-represented — a UK founder gets a US-skewed list and no warning | structural; must be stated, not silently ranked around | A |

Round progression and first-round behaviour deserve emphasis: **both are computable today from
`iv_edge` rows we already hold.** They need no new ingestion and no model spend — only a query we
have never written. That makes them the highest-value additions on this list.

## 12. Showing the reasoning, not just the rank

A number is not an explanation, and this product's entire claim is that its answers can be checked.
Every row must carry the chain that produced it, in the reader's language:

```
Why this firm is here
  ▣ filed      Their latest fund closed in 2026, so they are writing cheques now.
  ◈ observed   Eleven of their thirty-one holdings are developer tooling — your category.
  ◈ observed   They have co-invested with Amplify, who led your seed, four times.
  ▢ stated     They say they lead at Series A. We have not seen this independently.
Against
  ⚠ conflict   They already fund Rival, in your category. Worth knowing before you email.
What we could not check
  Lead capability at your stage: we hold no round roles for this firm.
  Cheque size: no Form D filings on record.
```

Three rules for that block:

1. **Every line carries its register.** "They say they lead" and "we have seen them lead eleven
   times" are different kinds of claim and the reader must be able to tell them apart at a glance.
2. **The unchecked list is not optional.** A firm matched on one axis out of six must show the five
   it was not matched on, or the reader infers confidence that was never earned — most dangerous at
   today's 0.8% sector coverage.
3. **No synthetic confidence.** No percentage, no "strong match", no stars. The reasoning IS the
   score's justification; if it reads thin, the match IS thin, and the interface should let that show
   rather than dress it.
