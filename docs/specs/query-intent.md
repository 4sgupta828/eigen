# Query Intent — decoding what was asked, and steering after the answer

Status: **built (2026-09-10)**, both search modes. Adapted from roster's `query-intent-decoding.md` and
`intent-convergence-loop.md`; this document records what carried over unchanged, what eigen needed
differently, and what was checked against eigen rather than inherited.

Owner report that started it: `#startups?b=companies backed by Amplify` "returns keyword matches on amplify
vs mapping it to filter chip on rails".

---

## 1. The report was one symptom of four causes

The compile was **correct**. Prod returned `must: {investor: ["amplify"]}` on the first try. Four other
things made the results wrong anyway, and each belongs to a different layer:

| # | Cause | Layer |
|---|---|---|
| 1 | `su_company` had **no keyword leg at all** — no `tsv`, no `ts_rank`, no `ILIKE`. Every startup search was one embedding, so a query already made of the corpus's own words had nothing to anchor it | retrieval |
| 2 | The contract also kept `text: "companies backed by Amplify"`, so a semantic leg ran on the same words the filter already covered, and companies merely **named** Amplify fused in beside the ones Amplify funded | compile |
| 3 | The link wrote a **sentence** for a model to read back into a slug we already had | UI |
| 4 | **Smart relaxing** saw a two-company portfolio, decided the search had matched too little, dropped the only filter, and returned the whole index | evaluate |

Only the first is retrieval; the other three are a search being second-guessed by machinery meant to help it.

---

## 2. The principle, inherited verbatim

> Decoding intent is **cheapest-first, and every layer may abstain.**
> A layer that cannot be sure hands the term to the next one. Only the layers that cannot be wrong are
> allowed to produce a `must`.

---

## 3. The layers, as built

### Layer 0 — the lexicon (`eigen_kernel/facets/lexicon.py`, deterministic, no model call)

Look the words up before asking. **A query that IS a facet value was being dropped**: the compiler is a model
told to extract what a brief "states explicitly as a requirement", and one bare word states nothing —
`acquired` is a legal `status` and compiled to nothing at all. The fix is not a better prompt; it is to look
first.

A hit is a **candidate, never an automatic must**. It hardens only when all of:

1. the spans plus filler account for the whole brief;
2. the key is one the vertical allows to be hardened;
3. the span is not ambiguous across keys;
4. its surface is not an ordinary English word — unless the span **is** the whole query, where there is no
   grammar around it to misread.

Vocabulary lives in the vertical (`{startups,investors}/query_lexicon.py`): filler, `MUST_KEYS`,
`RISKY_VALUES`, aliases. The mechanism names no domain noun and reads the vocabularies off the schema.

**Investors harden only FILED keys.** A must on a *stated* key filters on what a firm chose to write on its
own site, and before the site pass has read that firm it is silence rather than a no — so a stated must would
filter by our own crawl progress rather than by anything about the market.

### Layer 0a — settle the text, and this is where eigen needed more than a port

Roster blanks the semantic text when **the lexicon** covers the query. That works for a closed vocabulary.
Eigen's `investor` is an **open set** that no word list can enumerate, so "companies backed by Amplify" stayed
`covered=False` and kept its words — the reported bug survives a faithful port.

So the residual is computed against the **compiled contract** as well (`claimed_by_filters`): a word that
became a filter value is accounted for, whoever accounted for it. Alias surfaces count too — "India" becomes
`country=in`, and crediting only the canonical value left "india" looking like unexplained prose.

Blanking requires something that actually narrows. A contract whose only must is the scope — `country`, which
is on most briefs and narrows almost nothing — keeps its words, or the evaluator gets an enumerate leg over
the whole index and its cap picks which arbitrary rows the reader sees.

### Layer 2 — the model, given candidates to adjudicate

The lexicon's spans are passed in the user message as `words_that_name_a_filter`, and the prompt says they are
candidates: confirm one by placing it under a key, reject it by leaving it out. That is the judgment a model is
good at and a word list is not — *is "data" here the tech area, or the noun in "a data moat"?*

### The lexical leg

`su_company` gained a `tsv` column over name, one-liner, description and domain, and `StartupStore` gained
`keyword()` and `hybrid()` — RRF-fused with the dense leg, the same shape the investor store already used.
`simple` rather than `english`: company names are proper nouns, and stemming "Ventures" to "ventur" costs
exact matching and buys nothing. RRF rather than a score blend because cosine similarity and `ts_rank` are not
on comparable scales; rank is the only thing the two legs agree on.

---

## 4. Directions — steering after the answer

From `intent-convergence-loop.md`: don't answer a vague query once and stop. `eigen_kernel/facets/directions.py`
scores the schema keys whose values split the current slice, offers the best two or three, and each carries the
size of the slice it would leave.

**Model-free by design.** This fires on every search turn, so a planner in the hot path would be a model call
per query. The counts are already in the response; a direction is a contract edit the caller applies and
re-runs. Offering one costs nothing and ignoring one costs a glance.

**Silence is a real answer.** A pool too thin to split gets nothing, and neither does one the reader has
already narrowed to a handful.

**A direction the reader tapped is a decision, not a guess** — it is marked as a user key and exempted from
relaxing, which is cause #4 above in its general form.

On the investor side the chip carries its **register**: "narrow to firms who *say* they do seed" and "narrow to
firms we have *seen* do seed" are different offers, and a founder choosing between them should be told which.

---

## 5. What was checked against eigen rather than inherited

- **Roster's §2.1 (the coverage guard is blind to set keys) does NOT apply here.** Eigen's compile-time
  coverage counts distinct subjects per key from the fact table, which sees set keys correctly. The rail's
  counts omit an `unknown` bucket for sets, but the kernel says so deliberately (`count_rows`: "never for
  sets") and the SQL store agrees with it.
- **Eigen's compile prompt was already written for queries, not documents** — roster's §1.1 fix was already in
  place, so only the candidate-adjudication half was needed.
- Roster's Layer 1 (corpus statistics / lift) is **not** built here, for the same reason it is deferred there:
  its preconditions are about having measured co-occurrence, and we have not.

---

## 6. The trap that cost a debugging round

`wireDirs` is shared by both modes. Defined inside the startups IIFE it is invisible to the investors one, and
**nothing throws**: the buttons render, no listener binds, and clicking does nothing. `apps/web/index.html` is a
stack of per-mode IIFEs; this trap has now taken DeepDive's number formatter, the shared progress banner and
this. `apps/web/tests/test_directions.mjs` walks the IIFE nesting and fails if the helper moves back inside one.

The only reliable check is evaluating `typeof fn` in a real browser. A brace-depth scan is defeated by regex
literals, and a screenshot of a rendered button proves nothing about whether it is wired.

---

## 7. Measured

| | before | after |
|---|---|---|
| `companies backed by Amplify` | Amplitude, AmplifyBio, and the portfolio | 2 companies, both real, chip live on the rail |
| `acquired fintech companies` | no filters at all | `status=acquired`, `tech_area=fintech`, text blanked |
| tapping "State / region: ca" | — | pool 3,140 → 766, the count the chip promised |

Regression guards: the spec's flagship brief compiles unchanged; a brief with real semantic residue keeps its
words; a scope-only must never blanks; a risky value inside a longer brief ranks rather than filters.
