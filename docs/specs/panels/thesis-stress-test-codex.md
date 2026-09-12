# Panel: codex — thesis stress test

Verbatim. Relayed honestly, including where it disagrees with the spec and with the other
panelist. See `docs/specs/thesis-stress-test.md`.

---

**1. Can “will product X sell?” be answered from documents?**

No. Not in the way the owner is implicitly asking.

You cannot produce a *claim* like “this pre-product X will sell for $50k/yr to ICP Y” with congruent, public evidence, because:
- There is no `filed` or `observed` evidence about a non-existent SKU.
- `stated` evidence (surveys, blog posts, interviews) about hypotheticals has weak congruence to actual budget decisions.

What *is* answerable with high confidence from your corpus:

- Whether the *problem* exists at all, and in which segments (`filed`: risk factors, incident reports; `observed`: incident postmortems, eng blogs).
- Whether organizations *already spend* money/headcount on adjacent or substitute solutions (`filed`: opex/capex categories, acquisitions; `observed`: job postings, internal-tool blogs, GitHub repos).
- Who plausibly *owns* the problem and budget line (`filed`: org descriptions, management discussion; `observed`: job descriptions, RFPs).
- Whether others have *already tried* to sell something similar, and what happened (`stated`: fundraises, PR, case studies; `market signal`: news/HN chatter).

This residue is not consoling. It cannot say “yes, it will sell,” but it can often say “if this ever sells, it will be against long odds in segment Z” with enough force to change behavior. It’s more reliable for ruling ideas *out* or pushing them to “speculative” than for green-lighting.

---

**2. Ladder of falsifiable propositions + which sources help**

A demand thesis decomposes roughly as:

1. **Problem existence**: The situation X actually occurs.
   - Help: `edgar` (risk factors, incidents), `nsf`/`nih` (funded work), `eng_blog`, `founder_essay`, `podcast`, `gdelt` (events), `stackexchange`/`reddit` (people struggling).
   - Settleable: Largely yes.

2. **Problem severity / cost**: X is painful enough to merit attention.
   - Help: `edgar` (material risks, write-offs), incident postmortems, `eng_blog` “pain” posts, `gdelt` for failures.
   - Partially settleable: you get orders of magnitude, not precise utilities.

3. **Problem ownership**: A specific function and role “owns” it.
   - Help: job postings (ATS crawlers), `companies_house` roles, conference talks by “Head of <X>”.
   - Settleable: often yes.

4. **Budget line exists**: There is an existing category where money already flows.
   - Help: `edgar` (sales & marketing, R&D, “cloud services”), S-1 customer concentration, pricing pages of incumbents, named-customer pages.
   - Partially settleable: categories, but not exact line items.

5. **Buyer can be named** (economic buyer, not user).
   - Help: job postings (“Director of Procurement, Data”), RFPs/tenders, conference talks, incumbent case studies naming champions.
   - Partially settleable: you infer from titles.

6. **Status quo is expensive** (money or time).
   - Help: `eng_blog` detailing brittle in-house systems; internal-tool GitHub repos; `edgar` when outages hit revenue; `openreview`/papers describing manual workflows.
   - Settleable to “clearly non-trivial” vs “rounding error.”

7. **Switching is feasible** (technical, organizational, regulatory).
   - Help: `eng_blog`, `github` (how entangled is the solution), patents describing proprietary constraints, `edgar` on vendor lock-in.
   - Rarely fully settleable; you mostly see *obstacles*, not latent ease.

8. **Timing / catalysts**: Something is forcing revisiting the status quo now.
   - Help: new regulations (`edgar`, `gdelt`), tech discontinuities (preprints/papers, `github` trends), major failures.
   - Partially settleable.

9. **Willingness to pay ≥ cost to serve** for a non-commodity margin.
   - Help: incumbent pricing pages, procurement docs, 10-K vendor concentration, acquisition prices, internal builds (see below).
   - Not settleable for *new* SKU; you only get priors by analogy.

10. **Market size**: Enough such buyers exist.
   - Help: `edgar` + `companies_house` (firm counts), job postings count, funding density by segment.
   - Settleable to rough bands.

Rungs 1–6 and 10 are document-amenable. 7–9 are the least answerable, with 9 (“will they actually pay our price?”) fundamentally not answerable from documents; you only bound it using analogs.

---

**3. Revealed preference via “someone already paid or built it”**

Your instinct is directionally right: `observed` evidence of revealed preference (spend, headcount, in-house build) is the strongest public signal of demand.

Where it misleads:

- **Elite outlier trap**: FAANG-scale companies build hyper-specialized systems because their constraints are extreme. That is not evidence the median buyer faces the same pain or will ever pay.
- **Strategic moat trap** (internal build as *anti*-market): If firms frame the system as core IP and defend it as a moat, they’re structurally disinclined to buy it as a product. The more it’s tied to their proprietary data/edge, the worse the SaaS opportunity.
- **Solved-pain mirage**: If all credible buyers already have “good enough” homegrown systems, your product competes against sunk cost and political capital, not just budget. Internal build then signals past pain, *now largely resolved*.
- **Hobby/experimentation noise**: Labs and skunkworks publish sexy infra that never became critical; treating that as “demand evidence” is cargo culting.

You need to classify internal builds by *strategicness* and *generality* to avoid over-reading them as green lights.

---

**4. “What happens in the absence of it?”**

This is strictly more tractable, because it’s about realized facts, not counterfactual preferences.

You can ask: when X doesn’t exist as a product, what do organizations actually do?

Sources:

- `eng_blog`, `founder_essay`, `podcast`, `github`/`huggingface`: descriptions of manual workflows, duct-tape scripts, custom infra.
- Job postings: “must maintain spreadsheet-based process,” “manual reconciliation.”
- `edgar` risk factors and incident disclosures: how they currently mitigate a risk.
- `stackexchange`, `reddit`: user-level substitution hacks (labelled as `market signal` + `observed` artifacts, not as advice).

You can often answer:
- Is there *any* substitute?
- Is the substitute fragile/expensive?
- Is the substitute accepted as “normal cost of doing business”?

That gets you closer to real switching calculus than abstract WTP estimates.

---

**5. Evidencing a BUYER, not just an expert**

You want “has the problem + controls budget.” Rank, roughly:

1. **RFPs / tenders** (`filed` or quasi-filed):
   - Highest signal: explicit need, budget range, selection criteria, contact roles.
   - Trap: renewal theatre where winner is predetermined; you see noise, not contestability.

2. **Job postings for senior roles** (ATS crawlers):
   - Strong: problem ownership, seniority, sometimes budget hints (“own tooling budget”).
   - Trap: aspirational hiring; roles that are never filled.

3. **10-K / 20-F / DEF 14A**:
   - Strong for function-level spend importance and risk ownership.
   - Weak on specific named buyers; you still map to titles.

4. **Conference talks / panels**:
   - Medium: practitioners complain about problems they own; title + company known.
   - Trap: vendor-curated stages; over-represents noisy edge cases.

5. **Incumbent customer pages / case studies**:
   - Medium: proves orgs *buy something* in the category and who champions it.
   - Trap: pure marketing; only success stories, no denominator.

6. **Support forums / issue trackers**:
   - Weak-to-medium: identify power users/admins, not economic buyers.
   - Trap: they scream about pain but cannot move budget.

7. **Review sites, social, HN threads**:
   - Lowest: pure `market signal`, heavy selection and gaming.
   - Trap: over-indexing on discourse rather than actual purchasing behavior.

Eigen should explicitly tag “buyer-likelihood” on identities, not just “expertise,” and expose the distinction.

---

**6. Product vs feature; competitive set; buyer**

What you’re describing has two separable pieces:

- A **thesis decomposition + evidence-mapping engine** (what must be true + what we see). This is a *feature* that should sit across DeepDive, Startups search, Investors search.
- A **mode for orchestrating actual expert/buyer conversations** (finding, qualifying, scheduling, aggregating). This is closer to a *product* that competes with:
  - Expert networks (GLG, Tegus).
  - VoC / user research tooling (UserInterviews, Respondent, dscout).
  - Survey panels and generic market research shops.

If you try to serve both founders and investors with one mode, you’ll fail. Investors want:
- Fast falsification, calibrated priors, systematic manifests of absence.

Founders often want:
- Narrative support and idea expansion.

The value prop, UI framing, and pricing will diverge. I’d bias v1 toward the investor/allocator use case; they are structurally more tolerant of negative answers and care about evidence registers.

---

**7. The honesty problem**

To make “no demand evidence” feel like product *success*:

- **Score the *evidence graph*, not the idea.** Show coverage: which rungs of the ladder had any congruent `filed`/`stated`/`observed` evidence, and which are blank.
- **Separate “no evidence” from “evidence of absence.”** A pane that literally says:
  - “Checked: SEC, patents, eng blogs, job postings, RFPs, news. Found *zero* congruent mentions of [problem/role/category] in [time window].”
- **Benchmark against known successes/failures.** “For Segment A data tools pre-launch, we usually see ≥ N job postings and ≥ M eng blogs mentioning pain X. Here we see ≪ that.” Negative via relative absence is easier to swallow than “you are wrong.”
- **Lock sentiment in a ‘Market Signals’ box.** Visibly quarantined, never uplifted to main conclusion.

UI-wise, the mode should:
- Default to “Risk view” (where negatives are first-class).
- Let the user *annotate* gaps as hypotheses (“We think this is under the radar because…”) so the tool is a partner, not a judge.
- Make it impossible to share a pretty “green” story without the manifest of absence attached.

---

**8. Smallest v1 that moves belief**

In ~2 weeks, with your corpus and dossier engine, I’d ship:

- **Thesis parser:** Input: free-text thesis (“CFOs at mid-market banks will buy X to avoid Y”). Output: structured ladder (problem, segment, owner, substitutes, timing).
- **Rung-specific retrieval:** For each rung, auto-route queries to relevant connectors (as sketched in 2), producing:
  - A table of congruent evidence blocks with type (`filed`/`stated`/`observed`/`market signal`).
  - Per-rung summary in neutral language.
- **Coverage + absence panel:** Sidecar showing:
  - Which sources were consulted.
  - For each, whether we found congruent evidence or not.
  - A coarse comparables baseline.

- **Exportable interview guide:** Given the uncovered/weak rungs, auto-generate a question script for human buyer interviews. This ties the desk-research mode directly to real-world validation.

What I would *refuse* to build in v1:

- Any scalar “demand score” or “probability of success.”
- WTP estimates or pricing recommendations inferred from adjacent categories.
- Automatic recruitment/outreach to named individuals from public data (high risk of spam, misidentification, and regulatory blowback).

---

**9. The sharpest thing I’d tell the owner**

If you frame this as “stress testing a thesis” but mostly sell it to founders, you will accidentally build a machine for very expensive confirmation bias. The only honest framing is: “We help you find where your thesis currently has *no right* to be confident, even if you still choose to bet.” That means building for people who are willing to kill ideas—not for people whose identity is tied up in them.

---

**Manifest of Absence (conceptual, for this mode)**

We would lean on: `edgar`, `companies_house`, `uspto`/`patentsview`, `arxiv`/`openalex`/`semantic_scholar`/`openreview`, `github`/`huggingface`, `nsf`/`nih_reporter`, `job boards`, `eng_blog`, `founder_essay`, `podcast`/`youtube_chapters`, `hackernews`, `stackexchange`, `reddit`, `gdelt`/`startup_news`, plus per-company careers/pricing/customer crawlers.

None of these can provide:
- Direct `filed` evidence of willingness to pay for a non-existent product.
- Account-level switching costs or politics.
- Ground-truth counterfactuals (“what they *would* have bought”).

That absence is structural; the product must never pretend otherwise.
