# Panel: codex talent

Verbatim transcript. Relayed honestly, including where it disagrees with the spec and with the
other panelist. The synthesised call is in `docs/specs/experts-search.md` §11.

---

**1. Is the triad thesis right?**

“Startups / Investors / Talent” is directionally right but the symmetry is misleading.

For a VC / PE / crossover buyer, “talent” is only useful when it’s explicitly *in service of* a company, thesis, or network question. The real jobs:

- Understand the *team behind an asset*: “Who actually built/run this thing?”, “What’s their prior trajectory and domain depth?”, “Is there hidden seniority or is it all title inflation?”
- Assess *talent density around a thesis*: “Who are the 30 people who actually move the needle in applied robotics safety, and which companies/investors are they clustered around?”
- Evaluate *organizational resilience*: “If the famous founder walks, how much capability is left?”, “Is there a second line of leadership with real track records?”
- Support *post-investment* work: “We need a seasoned VP Eng / CISO / independent director in this subdomain—who’s plausibly in-network given our portfolio and their collaborators?”

The fake / symmetry-driven jobs you should reject:

- Generic sourcing: “Show me the top ML engineers in Europe.” That’s recruiter work, not investor diligence.
- HR-screening surrogates: CV-style scoring, “fit scores” for individual hires, anything that smells like a hiring funnel. That pushes you into high‑risk AI regulation with little benefit to an investor buyer.
- Vanity browsing / people gossip: “Who’s important in fintech?” without a concrete deal, thesis, or portfolio question isn’t a serious job to be done.
- LinkedIn clone: undifferentiated people search with weak evidence; users already have tools for this.

So yes, talent is the “third leg” only if you define it tightly as *team and expert context around companies and theses*. If you try to make it a symmetric, free‑floating Talent Map next to Startups and Investors, you drift into fake jobs and regulatory headache.

---

**2. Port, rebuild, or generalize?**

Copying Roster’s Talent Map (option a) is a bad idea.

- Roster’s spec is aimed at a talent‑intelligence product, not investor diligence. Its abstractions (nine‑level taxonomy, Evidence Map UX) are tuned for recruiting / HR buyers.
- The hardest bit (person entity model) is explicitly not built. You’d be copying an *aspiration* and some UI, not a working core.
- It will collide with Eigen’s kernel/vertical split and three‑register evidence model, and you’ll end up with a one‑off talent snowflake bolted onto the side.

Rebuilding natively in eigen (option b) is the right near‑term move.

- You already have people entities around companies and investors (founders, execs, board, deal participants). Start by exposing *that* in a way that serves the real jobs above.
- You can stay fully aligned with Eigen’s evidence registers, congruence rules, and API‑credit discipline. No cross‑repo semantics tax.
- You can design the Talent mode from the investor’s questions backwards, instead of inheriting Roster’s HR-ish assumptions.

Generalizing to an Evidence Map primitive (option c) is architecturally right but dangerous if you treat it as a big‑bang rewrite.

Honest cost of (c):

- Kernel data model work: a generic “evidence row” schema that can express startups, investors, talent, and future verticals without domain leakage.
- Refactor of at least Startups and Investors to emit Evidence Maps, plus UI rework to render those maps in each mode.
- Re‑indexing / migration of existing corpora and query logic to the new abstraction.
- Testing + provenance/auditing changes across *every* surface.

That’s multiple quarters if taken seriously, and absolutely could become “the right architecture that never ships.”

My view:

- Near term, do (b) with an *Evidence‑Map‑shaped* internal API for Talent only.
- Design that API so that Startups/Investors can gradually migrate onto it when you have proof it works.
- Do **not** do (a). You’ll inherit Roster’s unresolved problems and create a permanent architectural fork.

---

**3. Evidence-taxonomy collision**

Roster’s nine types mix several orthogonal ideas: who asserted it (self vs employer vs third‑party), structure (free text vs structured), support (corroborated vs weak), and freshness (stale). Eigen’s three registers are about *kind of evidence* at a much more fundamental level: filed / stated / observed.

If you collapse Eigen into Roster’s nine, you risk weakening your congruence discipline because the core question “Is this filed/stated/observed?” gets blurred under more granular but less foundational labels.

What I’d do:

- Keep Eigen’s three registers as the *primary* axis in the kernel: every fact is filed, stated, or observed. That’s non‑negotiable.
- Introduce a structured `basis` (or sub‑basis) that decomposes Roster’s concerns into orthogonal facets:
  - `asserter_role`: self, counterparty/employer, neutral third‑party.
  - `structure`: unstructured text, structured form, derived metric.
  - `support_level`: artifact‑backed, corroborated (N>=2 independent sources), inferred, weak.
  - `freshness`: current, stale (with explicit timestamp delta).
  - `gap`: explicit “looked and did not find” remains a first‑class absence.

Then:

- Roster’s nine buckets become *vertical‑specific views* over those basis fields.
- Eigen’s talent vertical can show the same nine labels in the UI if that’s useful, but the kernel only ever sees “filed/stated/observed + basis facets”.

This preserves congruence: type is clear, and the sub‑basis only refines strength and provenance, it doesn’t redefine what the evidence *is*. Mapping nine → three without adding basis would throw away the very nuance that makes an Evidence Map meaningful; adopting nine as the new primitive would pollute the kernel with talent‑specific vocabulary. Extending the three with basis is the only choice that’s compatible with your directives.

---

**4. Talent without full person entity resolution**

You’re right that the hard part is entity resolution. If Roster hasn’t built it, what you’d “copy” is essentially a UX and taxonomy pointed at a non‑existent spine.

You can still ship something valuable without full cross‑source identity resolution, *if* you scope it correctly and lean into transparency:

- **Company‑anchored team maps.** For a given startup or investor, assemble a map of named individuals from *within each source* (filings officers, board, cap table signatories, authors on papers, maintainers on org‑scoped repos, team pages). Don’t pretend they’re all fused; show per‑source rows and only surface “likely same” hints where you’re very sure. For most investor questions, seeing “this company has three repeat collaborators on robotics papers and the same names on the founding team” is already useful, even if you don’t absolutely unify every profile.
- **Thesis‑anchored expert maps.** Let a user ask “who’s doing serious work on X?” and respond with a ranked list of *person‑source tuples*: (name, paper set), (name, repo set), (name, grant records). You don’t need a canonical global ID; the evidence is the work itself. For diligence, that’s often enough: they want “who to talk to / who is around this asset,” not a perfect person graph.
- **User‑in‑the‑loop resolution for high‑value cases.** For named founders / senior leaders / key experts, let them or the investor explicitly merge identities (“yes, this GitHub + this Google Scholar + this corporate bio are the same person”). That gives you a high‑quality, sparse spine where it matters without pretending you have global resolution.

What you must *not* do without robust resolution:

- Produce global per‑person scores (“X has 50 patents and 5k stars”) that silently aggregate across sources.
- Imply coverage (“this map is the complete career of Jane Doe”) when you only see a corner.

So there *is* a meaningful, shippable version of Talent that is evidence‑first and honest about uncertainty, but it does *not* look like a smooth, LinkedIn‑like profile universe. It looks like a set of scoped evidence maps tied to companies and theses.

---

**5. PII / legal / ethical constraints**

You are absolutely walking into a minefield if you frame this as “shadow LinkedIn inside diligence” and don’t constrain it early.

Key constraints you should bake into the spec now:

- **Source and scope limits.**
  - Only ingest data that is clearly public and not behind logins or explicit anti‑scraping fences (public registries, company sites, open code hosts, open scholarly graphs).
  - Avoid LinkedIn‑style gray‑zone scraping entirely; the ToS and case law are hostile.
  - Consider a role threshold: focus on founders, execs, directors, and clearly public‑facing experts, not every random employee.

- **Regulatory posture.**
  - Under GDPR/CCPA you are a controller of personal data. You need DSAR/erasure flows, data‑minimization, retention limits, and a clear legitimate‑interest story (“investment diligence and risk assessment around companies”), not “general people search.”
  - NYC LL144 / similar “automated employment decision tool” rules and the EU AI Act high‑risk employment category become a risk if customers use this for hiring decisions. Your product and contracts should explicitly disallow using Talent maps as sole or primary automated hiring filters, and the UI should say this plainly.

- **No “people scores” for hiring.**
  - Stick to *evidence + congruent claims*, not opaque scores or rankings at the person level.
  - Any ordering should be transparently grounded (“sorted by number of robotics papers in the last 3 years”) and clearly not a suitability or performance prediction.

- **Sensitive attributes and fairness.**
  - Do not ingest or infer sensitive attributes (race, religion, health, etc.).
  - Be careful with photo‑based or name‑based inferences; better, don’t do them.

- **User rights and visibility.**
  - Provide a way for individuals to see what you hold about them and request correction/removal.
  - Make clear when a person is included because they are a public officer/director versus inferred by network analysis.

If you don’t set these guardrails upfront, you’ll end up with a technically clever “shadow LinkedIn” that legal/compliance forces you to cripple or kill later.

---

**6. The sharpest thing I’d tell the owner**

You’re flirting with a vanity symmetry—“Startups / Investors / Talent” as a tidy triad—without yet proving that your *evidence discipline* can survive at the person level, where errors are reputationally and legally costly. Unless you’re willing to ship a narrower, company‑anchored, evidence‑first Talent view and say “no” to generic people search and hiring use cases, you risk building an impressive‑looking third tab that erodes trust in the whole product and drags you into a regulatory category you’re not staffed to handle. The real opportunity is not to mirror LinkedIn; it’s to make Eigen the one place where every claim about *anything*—company, fund, or person—is auditable, typed, and congruent. If Talent doesn’t strengthen that core, don’t ship it.
