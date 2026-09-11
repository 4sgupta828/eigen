# Investor matching — from a filter to a match

Status: spec agreed 2026-09-11, after a panel (Codex + Gemini) and a prod coverage measurement.
Owner brief, verbatim: *"you must ensure the outcome, and not just mechanical wiring of inputs to
summarization to search over investors. We need to match!! best possible based on stage, area,
location, founders, type of startup, and and all"*

## 0. What it does today, and why it is a filter rather than a match

`POST /investors/advise` (`apps/api/investors/routes.py`):

- `deck_text` reaches exactly one function — `advise.stage_from_text()` — which returns an explicit
  round name and nothing else. **The rest of a deck is discarded.**
- `name` is resolved only against our own company index (`_subject_of`). Absent from it, the request
  falls back to three dropdowns.
- Candidates come from one `enumerate` leg per facet, fused with `rrf_fuse`, then `reasons_for()`
  sums `WEIGHTS` over signal **presence**.

So the match is `stage x sector x geo`, and a firm matching `stage_stated` (0.5) + `geo` (0.4) ties a
firm with real `observed_sector` overlap (0.9). Presence, not strength.

## 1. The measurement that governs everything else (prod, 2026-09-11)

`GET /investors/coverage` over 7,453 firms:

| signal | register | coverage |
|---|---|---|
| `evidence_strength`, `aum`, `investor_type`, `registered_with` | filed | 99.6–100% |
| `country` / `state` / `metro` | filed | 89.7% / 69.7% / 46.6% |
| `funds_count`, `latest_fund_size` | filed | 27.5% |
| `first_fund_year`, `latest_fund_year`, `still_deploying` | filed | 22.3% |
| `portfolio_count`, `observed_geo`, `observed_sector`, `co_investor` | observed | **0.8%** (~59 firms) |
| `observed_stage` | observed | **0.6%** (44 firms) |
| `stated_stage`, cheque size, `leads_rounds`, `sector_focus`, `geo_focus` | stated | **absent** |

**The signals the brief names — stage, area, type of startup — exist for under 1% of firms.** This is
a coverage problem wearing a ranking problem's clothes. Any scoring function over `observed_sector`
today ranks sixty firms and is silent about 7,394. It would look like it worked, because the same
sixty firms would top every list.

**Consequence, and the spec's first rule:** coverage before ranking. A matcher that cannot say how
much it knows about a firm must not imply it knows enough to rank it.

## 2. What we extract from the startup — conservative, quotable, never inferred

Mirrors `stage_from_text` and `site.founder_links`: extract what is stated, refuse what is implied.

| field | source | use | never |
|---|---|---|---|
| `subject_name`, `subject_domain` | deck title / site `<title>` | resolve `_subject_of` → our own observed sector/geo/co-investors | fuzzy firm matching |
| `stage_claimed` | `stage_from_text()` on deck/site — a literal round name | the stage legs | inferring stage from an amount |
| `raise_target` | an explicit "we are raising $X" | cheque-size compatibility only | inferring stage from it |
| `subject_sectors` | our company index first; else a keyword map into the existing taxonomy | sector legs | an LLM free-classifying "we use AI" into every AI tag |
| `subject_geo` | site/deck HQ | geo legs, as preference | a hard filter |
| `existing_investors` | "our investors" slide/section, resolved strictly against `iv_alias` | `co_investor` leg | a name that does not resolve — leave empty |

Every extracted field carries the **verbatim span** it came from. A field with no span does not exist.

### Rejected by the panel, and accepted as rejected

**Founder matching.** Both reviewers refused it independently. Gemini: *"We do not have structured
register data that says 'Sequoia prefers repeat founders from MIT.'"* Codex: *"barely justifiable from
primary sources and dangerously close to advice and bias."* Matching on pedigree means inventing an
investor preference we have never observed — the failure the evidence directive exists to prevent.
`iv_person` stays for transparency; founders stay out of the score.

**Semantic similarity as a ranking input.** Decks and VC sites share one marketing lexicon, so cosine
returns mega-funds for every query. The model is a parser into existing tokens, never a classifier.

**Whole-deck summarisation into the search.** Dilutes signal, invites hallucination.

## 3. Ranking: strength, not presence

Replace `score = Σ WEIGHTS[present]` with per-axis **strength in [0,1]**, each derived from a counted
fact and each carrying its register:

- `recency` — from `latest_fund_year`: `exp(-λ·(now − year))`, `0` with no filing.
- `sector` — over `iv_edge` rows whose company sectors overlap: `1 − exp(-α·n)`; **and** normalised by
  `iv_fact.denominator` where we hold it, so a fund with 5 of 10 in climate outranks one with 20 of
  1,000. Stated-only `sector_focus` scores lower than observed edges, never higher.
- `stage` — count of `iv_edge.round_name` mapping to the claimed stage; `stated_stage` as the weaker fallback.
- `geo` — observed portfolio geography above stated focus.
- `co_investor` — shared portfolio companies with the startup's existing backers.
- `cheque` — `raise_target` against `iv_fund.min_investment` / typical cheque: high inside [0.3×, 3×].

**Confidence is a first-class output, not a footnote.** Each firm reports which axes had evidence at
all. A firm ranked on `recency` alone is labelled as such and must never outrank one matched on
observed sector — this is what keeps a 0.8%-coverage world honest.

## 4. Anti-signals — they move the rank, not just warn

Today `conflicts_for` attaches a ⚠ and nothing else.

- **Portfolio conflict.** A direct competitor is disqualifying, not decorative. Large negative
  adjustment, row preserved so the founder sees why.
- **Dormant fund.** No filing in ~7 years → demote hard; show only on an otherwise exceptional match,
  with the years stated.
- **Cheque mismatch.** `min_investment` ≫ raise → demote. Filed data, so this is cheap and certain.
- **Wrong vehicle type.** Hedge / fund-of-funds / secondaries excluded from early-stage queries.
- **Geo-tourist.** Stated "global", observed 99:1 — the denominator reveals it.

## 5. The claimed stage, when evidence disagrees

The reviewers split. Gemini wants the tension surfaced; Codex refuses to correct a founder
algorithmically. Resolution: **we never overwrite or correct the claim.** Where the raise target sits
in a different cheque band than the claimed round, we show both result sets and state the gap once,
in the register language the product already uses — an observation about cheque sizes, not a verdict
about the company.

## 6. Not investment advice

No "95% match", no score shown as a probability of a yes. The posture is **who has already done
this**, not who will say yes. Every row explains itself through `reasons_for`, each reason tagged
filed / stated / observed, because "they say they do seed" and "we can see eleven seed rounds" are
different grades of evidence. The existing page disclaimer stays.

## 7. Build order

1. **`sites` (free)** — fetch/parse only, populates the firm's own words. Re-measure coverage after.
2. **Decide `portfolio` / `people` / `profiles` with a projected number in front of the owner** — these
   call a model. Validate on 1–2 firms before any batch.
3. **Strength ranking + anti-signals**, against coverage that supports it.
4. **Conservative extraction** from URL/deck, every field span-backed.

## 8. Evaluation — cases designed to pass a naive matcher while being wrong

Each must fail today and pass after.

1. **The everything-fund.** A hyper-niche query where a generalist mega-fund ranks first because it
   matched on `still_deploying` alone. A specialist must win, or the matcher is broken.
2. **The stated-vs-observed liar.** A firm whose site says "we back founders early" while its filings
   show a $2B vehicle and a $50M minimum. Stated must not outrank observed.
3. **The competitor trap.** A startup whose sector matches a firm's existing portfolio company.
   Superficially the best match; must be demoted with the conflict named.
4. **The zombie.** Perfect sector and stage history, last filing 2017. Must not rank above a live fund
   with a weaker match.
5. **The thin firm.** A firm with AUM and nothing else must never appear to be a sector match — it
   must be visibly ranked on recency alone.
