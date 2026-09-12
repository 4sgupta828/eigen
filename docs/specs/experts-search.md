# Spec: Experts Search — who to ask where the evidence runs out

Status: DRAFT for review.
Date: 2026-09-11.
Panel: Codex + Gemini (two independent passes: the Talent-Map framing, then the Experts framing) plus
two code-grounded exploration agents over `/Users/sgupta/eigen` and `/Users/sgupta/roster`.
Companion specs: `docs/specs/deepdive.md`, `docs/specs/investors.md`, `docs/specs/investor-matching.md`.

---

## 0. The question, and the answer

The question was: *should we copy Talent Map Search from roster into eigen, to complete a triad of
startups / investors / talent?* — then, on reflection: *actually we need an Experts Search, like Tegus
or AlphaSense, to vet startup theses.*

The second instinct is the right one, and the panel independently arrived at it from the first. But
the product is not "find experts". Both panelists said, separately and bluntly, that a tab which
finds experts from public artifacts is a **feature an expert network can bolt onto its search layer**,
not a wedge against one. Codex:

> If "Experts Search" does not visibly change what an investor *believes* about a thesis before they
> ever schedule a call, then you've built lead-gen for Tegus rather than a product in its own right.

So the answer is narrower and, we think, better:

> **Eigen already computes what it could not verify.** Every DeepDive ends in a Manifest of Absence —
> the sources we looked in and what they did not have. Every research answer ends in gaps. Those gaps
> are not a footnote; they are *the agenda for a human conversation*. Experts Search answers: **given
> what we could not establish, who has visible, non-trivial, subject-congruent public work closest to
> that gap — and what should you ask them?**

That reframing does three things at once. It makes the feature a continuation of the product's
existing discipline rather than a new noun beside it. It gives us a defensible answer to the hardest
objection anyone can raise (below, §1.3). And it scopes the build to something we can ship, because
the gap is already computed.

**Working name:** Experts. **Not** "Talent", **not** "People", **not** "Candidates" — §7 explains why
the word matters legally.

---

## 1. Positioning

### 1.1 What the incumbents actually sell

Tegus, AlphaSense, GLG and Third Bridge are **expert networks**. Their moat is not discovery. It is
(a) a recruited, compliance-wrapped roster, (b) brokered and scheduled paid calls, (c) a growing
transcript library, and (d) a sales machine that fills the calendar. Gemini put it flatly: *"They are
in the brokered-trust business. Eigen is in the document-parsing business."*

We cannot broker calls, we have no recruited network, and we will not build KYC/NDA/scheduling flows.
Competing on roster size is a losing game we would enter last.

### 1.2 What Eigen can sell that they cannot

Three things, all of which fall out of what already exists:

1. **An unbounded universe.** An expert network can only offer people it has recruited. Our universe
   is everyone who left a public artifact — the named inventor on the blocking patent, the maintainer
   of the open-source precursor, the grant PI, the person who wrote the engineering post that the
   startup's architecture is obviously copied from. Gemini called this *the un-networked
   practitioner*, against GLG's *"former VP-level executives who sit on five different expert networks
   and give rehearsed, macro-level boilerplate."*

2. **Evidence-first justification.** A candidate card says *"we surfaced this person because of these
   concrete artifacts on this exact subtopic"*, each row carrying its register and its source link —
   never *"their profile says VP at X"*. This is the kernel used as designed.

3. **Thesis integration — the actual wedge.** The flow does not begin at "find experts in solar". It
   begins at a dossier or a research answer that has already told the reader **what it could not
   establish**, and offers the people closest to that specific hole, with a question outline drawn
   from the gap itself. We are the *pre-call copilot*: we tell you whether you need the call at all,
   and if you do, we narrow and justify the list and draft the agenda. The call still happens
   somewhere else. That is fine — the surplus we capture is the diligence, not the scheduling.

### 1.3 The strongest objection, and the answer

Gemini's closing shot is the best argument against this feature, and it deserves a direct answer:

> You are pivoting to Experts Search because you fundamentally doubt your own product's core value
> proposition. If your system successfully parses the patents, the code, and the papers to validate
> the startup's technical claims, *why do you need to find a human for the investor to call?*

Because the Manifest of Absence is real and it is not going away. Eigen's honesty discipline means it
routinely and correctly reports that it **cannot** establish the thing that matters most: whether the
architecture actually works at claimed scale, whether the customer logo is a pilot or a contract,
whether the moat survives a competent competitor. Those are not parsing failures we will engineer
away; they are facts that were never written down anywhere public.

A product that says "here is what I could not verify" and stops is honest but inert. A product that
says "here is what I could not verify, here are the four people on earth whose public work sits
closest to that question, and here is what to ask them" has converted an admission into a next step.
That is not a lack of conviction in the synthesis. It is the synthesis knowing its own edge.

The guard against Gemini's version of the failure is a design constraint, adopted here: **Experts is
reachable from a gap, and a card must name the gap it addresses.** A generic people-search box with
no thesis attached is the failure mode, and §6 refuses to build one.

### 1.4 Jobs to be done — the real ones

| Job | Trigger | Anchor |
|---|---|---|
| **Validate a technical claim** — "they say their routing is novel; who built the precursor?" | a DeepDive claim we could only register as `stated` | company |
| **Fill a named gap** — "we could not establish unit economics; who has run this model at scale?" | a Manifest of Absence row | company |
| **Vet a thesis** — "is solid-state actually 3 years out? who would know?" | a research question | thesis |
| **Find the un-networked practitioner** — "the three people who wrote the open-source precursor" | a technology/topic | thesis |
| **Reference a team** — "do the founders' claimed credentials match their publication record?" | founder names already held | company |

And the fake jobs, which we refuse (§6.2): generic sourcing, anything resembling hiring, contact-data
provision, a browsable index of people.

---

## 2. Why we are not porting Talent Map from roster

Measured, not assumed. A code-grounded pass over `/Users/sgupta/roster` found:

**It is ~14,200 lines of shipping code** (≈21,800 with tests and specs): `people_population.py` 3,756
lines, `facet_store.py` 582, `artifacts.py` 811, `linkedin_resolve.py` 504, `person_discovery.py` 489,
`maps.py` 480, `claimgraph.py` ~600 of 2,161, ~1,100 lines of routes and closures inside
`app.py`, ~2,200 kernel lines, ~1,270 vertical lines, ~1,124 ingest lines, ~1,880 lines of
`index.html`.

**It does not search the corpus.** Roster's own `apps/api/facet_store.py:391-396` states the
asymmetry: *"`rs_block` (the research corpus) has a `tsv` tsvector column; `rs_job` and `rs_entity`,
which are what people and jobs search, have NONE"*. Talent Map reads `roster_entity_facet` +
`rs_person_vec`, populated by `scripts/ingest_people.py` — a **GitHub user-search sweep tiled across
49 cities × 20 languages = 980 windows** to beat the 1000-result cap. Eigen has no such table and no
such sweep. The thing that makes Talent Map work is the part that does not exist here.

**Its table names are hardcoded, not parameterized.** `roster_entity_facet`, `rs_entity` with
`WHERE e.kind = 'person' AND e.status = 'active'`, `rs_person_vec` — written as literals into every
query across 582 lines. Eigen's family is `iv_*` / `su_*`. Porting means rewriting, not renaming.

**Its schema version is a hash of roster's own key set.** `COMPATIBLE_EXTRACTION_VERSIONS =
("77c3be380247", "7566973b714a")` (`facet_schema.py:101`) gates re-extraction. Any eigen schema hashes
differently, so the list resets — and resetting it means re-reading the corpus.

**It is mid-cutover and not finished.** Two engines run side by side behind `ROSTER_FACET_EVALUATOR`,
and roster's own spec records the state verbatim: *"Step 4 CUTOVER (2026-09-05, owner: 'still not
working' on a brief typed straight into Talent Map)"* (`docs/specs/facet-contract-evaluator.md:413`).

**And the hard part is listed as not built.** Roster's `CLAUDE.md` roadmap item 1 is *"Entity model —
first-class person/company entities with stable IDs and cross-source resolution — not yet built."*

Verdict: **do not port.** What is genuinely portable is already here — eigen has the whole kernel
facets package (`contract.py`, `evaluate.py`, `schema.py`, `store.py`, `grouping.py`, `intake.py`,
`lexicon.py`, `directions.py`, `intent_check.py`, `contract_search.py`) and already uses it for
`kind="investor"`. What we would be copying is a person-ingest pipeline we do not want and an
identity model that does not exist.

---

## 3. What Eigen already has (the reason this is cheap)

This is the finding that changes the estimate. Eigen holds people in **six unconnected places**, plus
one complete, indexed, unused people platform sitting in the kernel.

### 3.1 The dead people store

`packages/kernel/eigen_kernel/people/store.py` — **383 lines, fully implemented, imported by nothing.**
A repo-wide grep for `PeopleStore|eigen_kernel.people|eigen_entity` returns only documentation.

It already encodes, in code, the exact legal posture §7 demands:

- `eigen_entity` keyed on a **natural registry key** (`'npi:1234567890'` in its current shape;
  `'github:<login>'`, `'orcid:<id>'`, `'uspto:<inventor>'` in ours) — identity is a source's key, never
  a name we minted.
- `status` ∈ `active | suppressed | retired | deceased`, and **suppression is a status flip, never a
  delete** — right of reply, built in.
- `eigen_entity_metric`, append-only, with `metric_label` chosen by the **caller** for honesty — the
  docstring's own example is *"Original Medicare Part B claims, 2023 — never 'patients seen'"*.
- `eigen_entity_edge` requires a mandatory `evidence_key` — the **shared fact** that justifies the
  edge (a group id, a facility id, a paper id) — *"never inference"*.
- `search()` has **no default ranking**: neutral `ORDER BY e.name` unless the caller passes an explicit
  `sort_metric`, because *"the user must actively choose the sort key"*.
- `connections()` unions stored edges with **live** shared-affiliation neighbours rather than
  materialising a 500-person org's 125k pairs.

The one blocker is that it is medical-shaped: `vertical DEFAULT 'medical'`, `kind DEFAULT 'physician'`,
`license_status`, `board_certified`, `discipline_status`. That is a **standing-directive violation**
(`CLAUDE.md`: "No medical-vertical vocabulary or code … in the app shell or kernel") independent of
this feature, and it is a rename pass away from fixed. `learnings/design-improvement.md:144` already
flags it honestly.

### 3.2 The evidence-backed edge graph

`packages/kernel/eigen_kernel/graph/store.py:32` — `eigen_topic_edge`: subject / relation / object /
context, `label` ∈ `established | supported | hypothesized`, `provenance` ∈ `curated | harvested |
seed`, `status` ∈ `shadow | active | demoted`, `confidence`, and `seen_count` counting **DISTINCT**
evidence documents. Plus `eigen_edge_evidence` (`:58`) holding a verbatim quote per document per edge.

`relation` is explicitly *"vertical vocabulary (validated on write)"* — so `invented`, `authored`,
`maintains`, `awarded`, `officer_of` are supplied by the tech vertical with **zero kernel change**.
This is the machinery roster's roadmap says it has not built.

### 3.3 The connectors, already ingesting

Every source the panel said to restrict ourselves to is already running: `edgar` (officers, directors,
Form D related persons, and DEF 14A — the connector comment at `connectors/edgar.py:29` literally calls
the proxy *"the people layer"*), `uspto` + `patentsview` (inventors), `arxiv` + `openalex` + `crossref`
+ `semantic_scholar` + `openreview` (authors), `github` + `huggingface` (owners, maintainers),
`companies_house` (UK directors), `nsf` + `nih_reporter` (grant PIs), `wikidata`, `yc`, `eng_blog`,
`founder_essay`, `podcast`/`show_notes`/`youtube_chapters`.

Corpus composition, as measured: ~650,525 blocks — 464k SEC filings, 92k preprints, 33k code
documents, 19k papers, plus patents, funding and news. **The gap is extraction, not ingest.**

### 3.4 Person material already extracted

| Where | What | Scale |
|---|---|---|
| `su_founder` (`startups/store.py:101`) | founders + `title`, `prior_companies[]`, `links jsonb`, `bio` | **11,330 founders with LinkedIn or X links** (`voices/people.py:3`) |
| `iv_person` (`investors/store.py:108`) | firm people, `role` ∈ gp/partner/principal/related_person/angel, `links`, `basis`, `source_url`, `quote` | live |
| `su_formd.officers` (`startups/store.py:146`) | filed related persons with stated roles — *"never founders"* | live |
| `iv_fund.persons` (`investors/store.py:97`) | Form D related persons, fund side | live |
| `rs_entity` / `rs_mention` (`claimgraph.py:127,270`) | claim-graph person nodes, mention-first ER lane | sparse |
| `rs_block.facets` | `author`, `guest` from feeds, papers, repos, podcasts | corpus-wide |

Plus `packages/vertical_tech/eigen_vertical_tech/person_reader.py` — a ready-made 8-query deep-read
facet plan — and `entities.py:8`, where `person` is **already a declared entity type**.

### 3.5 The failure classes already paid for

Three modules already encode the wrong-person discipline, learned the expensive way:

- **`voices/bind.py`** — measured 2026-09-07: naive matching of company names in episode text bound
  **100%** of episodes (because *inside*, *check*, *built*, *ambition* and *mercury* are all company
  names in the index); gated matching bound **1–4%**, and those were correct. This is the same failure
  class as the `Clay` corpus bug fixed earlier today.
- **`voices/people.py:69`** — a name shared by two held rows resolves to **nobody**: *"Ambiguity is the
  same failure as a wrong guess, just with an audit trail."*
- **`deepdive/assemble.py:127`** — single-token names fold into a full name only when they match
  exactly one: *"two Roberts stay two Roberts, because guessing there would merge two people."*

These are not incidental. §5 makes them the identity rule.

---

## 4. Evidence typing

### 4.1 We keep three registers and extend `basis`

Roster uses nine evidence types: self-stated / employer-stated / artifact-backed / structured /
corroborated / inferred / weak / gap / stale. Both panelists said, independently, **do not adopt them**.

Codex's diagnosis is the precise one: those nine **mix four orthogonal axes** — who asserted it, how
structured the source is, how much support exists, and how fresh it is. Gemini's is sharper still:
*"'Inferred' is literally the absence of direct evidence — it is a synthesizer's guess."* Adopting a
taxonomy in which one value means "we have no evidence" would break congruence, because the register
would no longer answer *what kind of thing is this*.

So: **the three registers stay the primary axis**, and roster's nine become orthogonal `basis` facets
that refine strength without redefining kind.

| Roster type | Eigen register | Eigen `basis` |
|---|---|---|
| Structured (EDGAR, Companies House, ORCID, patents) | `filed` ▣ | `registry` |
| Artifact-backed (commit, paper, patent text, dataset, talk) | `observed` ◈ | `artifact` |
| Employer-stated (team page, press release, speaker bio) | `stated` ▢ | `employer_stated` |
| Self-stated (personal site, GitHub bio, own essay) | `stated` ▢ | `self_stated` |
| Corroborated | *unchanged* | `corroborated_by:<n>` — n **independent families** |
| Stale | *unchanged* | carried as `as_of`; the UI ages it |
| Inferred | **not a register** | a derived field, labelled as derived, never cited as evidence |
| Weak | **not admitted** | fails `subject_bound`; becomes a Manifest-of-Absence row |
| Gap | **not a register** | already first-class as an absence row |

Corroboration counts **families**, not documents, and the families must be independent: three news
articles rewriting one press release is one family, and a paper plus a patent plus a repo is three.

### 4.2 The register follows the source, never the prose

Exactly as `deepdive/corpus.py:45` already does for the corpus leg: the register is a property of
*what the source is*, decided from where the document came from, never from how confident the text
sounds. A patent naming an inventor is `filed` whoever wrote the abstract.

---

## 5. Identity: bounded, never global

### 5.1 The rule

> **We never merge two identities on name similarity. We merge only on a shared strong key, and where
> there is no strong key we show the separate rows and say so.**

The panel converged here from two directions. Gemini: *"the company acts as the bounding box for
identity … let the human brain — the most advanced entity resolution engine on earth — look at the
list."* Codex: merge *"only when you have strong keys (email, ORCID, consistent name+affiliation
across multiple connectors)"*, and *"where you don't, treat them as separate people and let the UI show
that ambiguity."*

Eigen's own precedents (§3.5) already say the same thing in code. This rule is therefore not a
compromise; it is the house discipline applied to a new noun.

### 5.2 Strong keys, in order

| Key | Source | Merges |
|---|---|---|
| `orcid:<id>` | OpenAlex, Crossref, OpenReview | papers across venues |
| `github:<login>` | GitHub, HuggingFace | repos, orgs, commits |
| `openalex:<id>` | OpenAlex | an author's works |
| `uspto:inventor:<id>` | PatentsView | patents |
| `cik:<n>` + role | EDGAR | filed officer/director roles |
| `companies_house:<n>` | Companies House | UK directorships |

Cross-key merges (`orcid` ↔ `github`) require **either** a self-declared link the person published
themselves (an ORCID on a GitHub profile, a GitHub URL in a paper) — which is `stated`, and labelled —
**or** an explicit human confirmation. Never a similarity score.

### 5.3 The unit of a result

Codex argued for `(person, subdomain topic)` as an expertise **edge**; Gemini argued for an artifact
cluster with no synthesized person at all. We take Codex's unit with Gemini's discipline:

> The unit is an **expertise edge**: `identity --[relation, evidence]--> topic`, where `identity` is a
> *strong key*, not a name, and the edge is backed by a bag of `eigen_edge_evidence` documents.

This is exactly what `eigen_topic_edge` already stores. A person card is then a **view** over the edges
sharing an identity — and when two identities plausibly name one human but share no strong key, the UI
shows two cards side by side with an explicit *"these may be the same person; we hold no link that
says so"* line. That line is a feature. It is the product being honest about the thing every
competitor quietly guesses at.

---

## 6. The measure: evidence patterns, not a score

### 6.1 What we compute

**No expertise score. No rank. No percentile. No tier.** Both panelists were emphatic and the legal
analysis in §7 makes it binding.

What we compute per `(identity, topic)` is a **contribution pattern**, displayed as facts:

- **Primary-actor artifacts only.** Inventor on a patent; PI or co-PI on a grant; first or last author
  on a paper; owner or core maintainer of a repository; officer or director in a filing; main speaker
  on a talk. A middle author on a 200-author paper is not evidence of expertise and is not counted as
  one; it is shown, labelled, and weighted at zero.
- **Subject congruence.** The artifact must be about *this topic*, decided by the same
  `subject_bound` + `metric_defined` gates the dossier uses. Adjacency is not expertise.
- **Span and recency.** ≥ N independent artifacts across ≥ M years within one coherent subdomain.
  Defaults `N = 3`, `M = 2`, both tunable and both displayed.
- **At least one hands-on signal.** Code, an implementation-level paper, or a patent describing a
  concrete system — not only commentary. Gemini's framing: we find *"the person who wrote the code,
  not the person who scaled the team"*, and we should say so rather than pretend otherwise.

Ordering is by **count of distinct congruent artifacts**, then recency. That is a dumb, legible,
defensible sort — Gemini's *"sort results strictly by chronological recency or by a dumb Boolean match
count"* — and it is the same neutral-ordering posture already coded into `PeopleStore.search()`.

### 6.2 What this systematically misses — stated on the page

This must be rendered to the reader, not buried in a spec. Both panelists produced the same list:

- **Trade-secret operators.** The Apple engineer, the Renaissance quant, the AWS infra lead who
  publishes nothing and patents under a generic corporate assignee. Gemini: *"You must explicitly warn
  the buyer of this blind spot."*
- **Managerial competence.** We see who built it, never who scaled the team.
- **Regulated and classified work** — defense, proprietary infrastructure.
- **Non-English and analog-first experts** with sparse web presence.
- **Mis-assigned credit in big-team science**, where real contribution ≠ author position.
- **Anyone whose identity we cannot key.** Pseudonyms, name collisions.

This is a Manifest of Absence for the expert search itself, and it is required output.

---

## 7. Legal and ethical constraints — adopted up front

### 7.1 LinkedIn: a link, never a source

The request named LinkedIn as an evidence source. We will not read it, and the reason is already
written in this repo. `packages/vertical_tech/eigen_vertical_tech/person_reader.py:1-11` states the
position: LinkedIn and X are login-walled and ToS-forbidden, *"Proxycurl was sued+shut down in 2025"*,
so they are the profile **link**, never a scrape target.

Both panelists reached the same conclusion independently. Gemini: *"There is no compliant path to
scraping LinkedIn at scale for a commercial B2B data product … LinkedIn data is also entirely* stated
*evidence — it is self-published marketing, not peer-reviewed reality."* Codex noted that *hiQ*
resolved the CFAA question and left ToS breach, GDPR profiling and unfair-competition exposure
untouched.

And we have our own measurement showing it would not even work. `apps/api/investors/sources/people.py`
measured four real VC team pages on 2026-09-10: **Bessemer prints zero LinkedIn links, USV zero,
Initialized one, Craft four.** A LinkedIn-anchored parser reads almost nobody. That is why that module
is link-anchored on the site's *own* profile URLs instead.

What replaces each LinkedIn field, from sources that are unambiguously public record:

| Field | Source | Register |
|---|---|---|
| Current employer | recurring paper affiliation; GitHub org membership; patent assignee over time | `stated` / `observed` |
| Role and seniority | EDGAR officer/director titles; Companies House appointments; grant PI role; team pages | `filed` / `stated` |
| Employment history | affiliation sequence across papers, patents, grants and filings, as a **best-effort timeline with citations and explicit uncertainty** | mixed, per row |
| Profile link | the person's own published links (site, GitHub, ORCID), plus a LinkedIn **search** URL | `stated` |

The existing UI precedent is already correct: `apps/web/index.html:8132` builds
`linkedinSearchUrl(name, company, title)` — a search query, never a fabricated profile URL — and
`voices/people.py:24-41` links LinkedIn's and X's own people directories rather than general web
results. Keep both.

### 7.2 Staying out of employment-decision regulation

NYC LL144 governs Automated Employment Decision Tools; the EU AI Act classes AI used in employment and
recruitment as high-risk. An expert-discovery tool for investment diligence is not that — but **the UI
is what decides which side of the line you are on.** Binding constraints:

1. **No score, rank, tier or percentile is ever emitted**, internally-computed or not.
2. **No hiring vocabulary anywhere** — no "candidate", "talent", "shortlist", "source", "fit". The
   mode is called **Experts**, results are **people**, the artifact is an **expert map**.
3. **No ATS integration, no export-as-candidates, no outreach, no scheduling.**
4. **No demographic inference and no proxy filters** — never gender, race, age, nationality,
   disability; no filtering on school or graduation year.
5. **An explicit refusal in the disclaimer**, in the vertical's `ui.console()` disclaimer block
   alongside the existing investment-advice text: this is research, not a hiring tool, and must not be
   used to make employment decisions.

### 7.3 Defamation and the right of reply

We will be asserting things about named private individuals. Therefore:

1. **Only `filed` and `observed` claims are asserted.** *"Named as inventor on US 11,123,456."*
   *"Core maintainer of repo X."* A `stated` claim is always attributed: *"describes themselves as…"*.
   No synthesized character judgement, ever — Gemini's line holds: the system may say *"Jane Doe is
   listed as an author on three papers regarding quantum routing [cite][cite][cite]"* and may not say
   *"Jane Doe is a leading expert in quantum routing."*
2. **No negative or value-laden language.** The fail-safe is omission, as everywhere else in Eigen.
3. **Suppression is a status flip, never a delete** — already implemented in `PeopleStore.set_status`.
   A named person can ask to be removed and the row goes `suppressed` with the audit trail intact.
4. **No contact extraction.** No emails, no phone numbers, no scraped addresses. Gemini: *"If the
   investor wants to call them, they can figure out how to contact them. You are a diligence platform,
   not ZoomInfo."* Published profile links only.
5. **A subject-access path** for GDPR/CCPA: what we hold, where each row came from, and how to correct
   or suppress it.

---

## 8. Build plan

Four phases, each with a gate that can stop the next.

### Phase 0 — Measure before building (free, ~half a day)

The investors work established the precedent: coverage measurement drives design, and we found
`observed_sector` at 0.8% and `observed_stage` at 0.6% only by counting first.

Count, over the live corpus:

- Blocks per people-bearing `source_key`, and of those, how many carry a resolvable **strong key**
  (ORCID on a paper, GitHub login on a repo, inventor id on a patent, CIK+role on a filing).
- Distinct identities per key type.
- For 20 hand-picked deep-tech topics, how many identities clear the §6.1 pattern bar (≥3 congruent
  primary-actor artifacts across ≥2 years).

**Gate:** if fewer than ~5 identities clear the bar on a median topic, the feature has no foundation
and we stop here and ingest first. This is a free SQL count. It costs nothing and it can save a month.

### Phase 1 — De-medicalise and wake the people store (~2 days)

Independent of this feature, and owed anyway as a directive violation:

- Rename the medical defaults in `eigen_kernel/people/store.py` — `vertical DEFAULT 'medical'`,
  `kind DEFAULT 'physician'`, `license_status`, `board_certified`, `discipline_status` — to
  domain-free equivalents (`credential_status`, `standing_status`, no defaults).
- Confirm `tools/check_kernel_invariant.sh` and `check_kernel_imports.py` stay green. Note that the
  grep gate does **not** ban `person`/`people`/`talent`, so the CLAUDE.md litmus ("could a LEGAL or
  BIOTECH vertical reuse this?") is the real constraint here, not the script.
- Add the relation vocabulary to the **vertical** (`entities.py`): `invented`, `authored`, `maintains`,
  `awarded`, `officer_of`, `spoke_on`. Zero kernel change — the kernel already validates
  vertical-supplied relations on write.

### Phase 2 — Extraction into edges (~1 week, mostly free)

Per source, extract `(strong_key, relation, topic)` edges into `eigen_topic_edge` with verbatim
evidence into `eigen_edge_evidence`. **All of this is deterministic parsing of structured fields — no
model call:**

| Source | Edge | Register |
|---|---|---|
| PatentsView | `uspto:inventor:<id> --invented--> <CPC topic>` | `filed` |
| OpenAlex / arXiv / Crossref | `orcid:<id> --authored--> <concept>` (first/last author only) | `observed` |
| GitHub | `github:<login> --maintains--> <repo topic>` (owner/core only) | `observed` |
| NSF / NIH | `<pi> --awarded--> <program area>` | `filed` |
| EDGAR / Companies House | `<cik>:<role> --officer_of--> <company>` | `filed` |

Reuse `investors/sources/people.py` verbatim for team pages — it is measured, model-free, and its
binding rule (a name is accepted only when its tokens appear in the profile slug) is exactly right.

**Gate:** hand-audit 50 random edges. A wrong-person edge rate above ~2% stops the phase.

### Phase 3 — The two entry points (~1 week)

No new top-level tab in v1. Experts appears where a gap already exists:

1. **From a DeepDive gap.** Each Manifest of Absence row that a human could close gets a *"who could
   answer this"* affordance. The topic comes from the gap; the card names the gap it addresses.
2. **From a research answer.** Same affordance on the gaps the research loop reports.

The card: name as the source writes it, the strong key it is bound by, 3–8 congruent artifacts with
register glyphs and source links, the span, the hands-on signal, the blind-spot note from §6.2, and a
drafted **question outline** derived from the gap — which is the part that changes what the investor
believes before any call.

**Gate:** run it on five real theses. If the people surfaced are ones the investor already knew, the
unbounded-universe claim is false and the wedge is not there.

### Phase 4 — Expert maps, only if Phase 3 earns it

A saved, shareable expert map. Copy `su_map`'s implementation, not `iv_map`'s — of the three saved-
artifact implementations in the repo it is the only one that actually writes revisions, does not leak
its share token to non-owners, and uses a resolved user id rather than a raw bearer token.

### Not now, explicitly

Cross-source identity resolution beyond strong keys. A standalone Experts tab with a free-text people
box. Contact data. Expert-network integrations or scheduling. A global index of people. Any of the
nine-type taxonomy. LinkedIn ingestion in any form.

---

## 9. Eval cases

Per the standing directive, every gate needs a held-out case **designed to pass the gate while being
wrong**. Seeded from failures this repo has already paid for:

1. **The common-word name.** A person whose surname is an ordinary noun or a given name — the `Clay`
   failure, at person scale. Must not bind on the bare name.
2. **The homonym.** Two real researchers with the same name in adjacent fields. Must resolve to
   neither, and say so — the `voices/people.py:69` rule.
3. **The middle author.** A 200-author physics paper naming the subject. Must be shown, labelled, and
   counted at zero.
4. **The bibliography.** A paper citing the topic, not contributing to it. Must be excluded — the same
   `looks_like_bibliography` gate the corpus leg uses.
5. **The corporate assignee.** A patent assigned to a large employer with a generic inventor list.
   Must not imply the inventor is an expert in the assignee's whole portfolio.
6. **The adjacent topic.** An artifact one concept-hop away. Must fail `subject_bound`, not scrape in.
7. **The stale expert.** Strong artifacts, all more than eight years old. Must surface with the age
   stated, never silently.
8. **The self-declared link.** A GitHub bio claiming an ORCID that belongs to someone else. Must be
   labelled `stated` and must not merge the identities.

---

## 10. Open questions

1. **Does Phase 0 clear its own gate?** Everything downstream is contingent. Unknown until counted.
2. **Do we ever merge across key families?** The spec says only on a self-declared link or a human
   confirmation. If Phase 3 shows readers are annoyed by split cards, revisit — but the answer is a UI
   affordance ("these look like one person — is that right?"), never an automatic similarity merge.
3. **Where does the question outline come from?** Deriving it from the gap is the highest-value part of
   the card and the only part needing a model call. It needs its own projection and gate, and probably
   its own spec section once Phase 3 is real.
4. **Does the triad survive?** Startups and Investors are two instances of something like an Evidence
   Map, and Experts would be a third. Codex warned that generalising now is *"the right architecture
   that never ships"*; Gemini warned that not generalising is *"three separate tabs"*. The resolution
   adopted here: build Experts natively on eigen's own primitives, keep its internal shape
   Evidence-Map-like, and **only** refactor Investors and Startups onto a shared primitive once
   Experts has shipped and proved the contract — with the existing investor trap tests as the guard
   that the refactor changes no behaviour.

---

## 11. Panel record

Two independent passes, both with Codex and Gemini, plus two code-grounded agents verifying every
file:line claim above. Full transcripts are in the session scratchpad.

**Where both panelists agreed:** do not port roster's code; reject the nine-type taxonomy; keep three
registers and extend `basis`; do not touch LinkedIn; bound identity by context rather than resolving
globally; emit no person-level score; refuse contact data; name the trade-secret blind spot on the
page.

**Where they disagreed:** Codex would build Experts natively and generalise later; Gemini would extract
the Evidence Map primitive first or accept permanent silos. Codex would ship a slim standalone list;
Gemini would ship only an evidence panel on the existing dossier and no standalone surface at all.

**The call taken here:** Codex on sequencing, Gemini on the destination and on the entry point. Experts
rides existing surfaces in v1 (Gemini), built natively on eigen's own primitives with an
Evidence-Map-shaped internal contract (Codex), with the generalisation deferred behind a shipped proof
rather than attempted up front.

**What the panel did not know, and what changed the estimate:** that `eigen_topic_edge` +
`eigen_edge_evidence` already exist in the kernel with per-edge verbatim evidence and a promotion
lifecycle; that `eigen_kernel/people/store.py` is a complete, unused people platform whose design
already encodes the legal posture both panelists demanded; and that this repo has already measured,
in `investors/sources/people.py`, that LinkedIn-anchored parsing reads almost nobody.
