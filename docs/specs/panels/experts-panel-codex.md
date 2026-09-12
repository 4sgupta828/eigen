# Panel: codex

Verbatim transcript. Relayed honestly, including where it disagrees with the spec and with the
other panelist. The synthesised call is in `docs/specs/experts-search.md` §11.

---

1. **Wedge vs expert networks**

Eigen is not an expert network and shouldn’t pretend to be one. Tegus / GLG / Third Bridge sell: (a) compliance-wrapped access to humans, (b) a growing transcript library, (c) a sales machine that fills your calls calendar. “Find experts from public artifacts” is, by itself, a feature they could bolt onto their search layer, not a defensible wedge.

What Eigen can actually sell, today, is something different: *evidence-backed expert *selection* and question design before you ever touch an expert network*. Concretely, the buying moment is:

- “We are exploring X; who should we *ask* and what should we *ask them*, given the entire public technical corpus and our thesis?”

Thickening the wedge requires three things that Tegus/AlphaSense do not do well:

- **Unbounded universe**: you are not constrained to “experts GLG has already recruited.” You surface obscure but high-signal people who live in arXiv / patents / GitHub / grants / quasi-anonymous eng blogs.
- **Evidence-first justification**: every candidate card is “we think this person is useful *because* of these concrete artifacts about this exact subtopic,” not “because their profile says VP at X.” That’s using the kernel as intended.
- **Thesis integration**: the product doesn’t start from “find experts in solar,” it starts from “here is my thesis doc / DeepDive; show me who to talk to where the Manifest of Absence is scariest.” You’re selling *thesis-tuning* with experts as one output.

If you just ship a tab called “Experts” that is effectively “People search across GitHub + papers + (maybe) LinkedIn,” Tegus wins every time because they also give you the phone call and the historical transcript. The non-thin wedge is: Eigen is the *pre-call copilot* that (1) tells you whether you even need a call and (2) if yes, hands you a narrowed, justified list + a question outline you can throw at Tegus/GLG/your network.

2. **Measuring expertise without vanity metrics**

You will not get a scalar “expertise score” that is both honest and not a magnet for bullshit. What you can get is a small set of *minimum viable evidence patterns* that make someone “worth 45 minutes on the phone” for a *narrow topic*.

One concrete unit: **(person, topic) → “substantive contribution streak”**:

- Count only *substantive, subject-congruent artifacts* where the person is a primary actor:  
  - Filed/observed: patents where they are inventor; grant PI/co-PI; first/last-author papers; repositories where they are owner or core maintainer; SEC/Companies House roles tied to the domain; talks/tutorials where they are main speaker.  
  - Stated: technical blog posts, longform essays, podcast episodes where they discuss the topic in depth.
- Require minimums like:
  - ≥ N independent artifacts over ≥ M years, *all within a coherent subdomain*, plus
  - At least one “hands-on” signal (code, implementation detail in papers, patent describing concrete systems), not just high-level commentary.
- Display this as *patterned facts*, not a score: “Has 3 patents and 2 first-author papers on HFT matching engines since 2019; core maintainer of repo X used by Y stars.”

What this *systematically misses*:

- Quiet operators whose expertise is locked in internal docs and production incidents.
- People in heavily regulated / secretive contexts (defense, big proprietary infra) where external artifacts are censored.
- Non-English, non-Western, or analog-first experts with sparse web presence.
- Underspecified credit in big-team science/engineering where real work ≠ being first/last author or repo owner.
- Anyone whose identity cannot be cleanly resolved across sources (name collisions, pseudonyms).

So the honest stance is: you’re not ranking “best experts”; you’re answering “who has a visible, non-trivial *track record* in this narrow slice, sufficient that a call is unlikely to be a waste.”

3. **LinkedIn**

You should treat LinkedIn as off-limits unless you have a formal licensing agreement.

hiQ v. LinkedIn helped with CFAA (public profiles ≠ “hacking”), but it did *not* make you safe on: (a) ToS breach (they’ve gone after companies for this), (b) GDPR profiling/consent, (c) unfair competition / privacy optics. Building a core product atop large-scale LinkedIn scraping is a legal and commercial risk you do not need.

Best substitutes for the LinkedIn signals:

- **Current role / seniority / employer**
  - SEC `edgar`: officer/director titles, company, dates → clean for public companies and some privates.
  - Companies House and similar registries: director roles, appointment dates, company status.
  - Grants (`nsf`, `nih_reporter`): PI institution and role at time of award.
  - Papers (`arxiv`, `openalex`, `crossref`, `semantic_scholar`): affiliations; recurring affiliation over time approximates employment/role.
  - Patents (`uspto`, `patentsview`): assignee + inventor; repeated co-occurrence with one assignee over time = likely employer.
  - Company/team pages (`eng_blog`, `founder_essay`, scraped corp sites in your “eng_blog”/“podcast” connectors): directly state titles and org hierarchy.
- **Work history / domain trajectory**
  - Sequences of the above over time: affiliation changes in papers, patents, grants; changes in SEC/Companies House roles; narrative in founder essays (“previously at X, built Y”).
  - GitHub/HuggingFace: organizations of repos they own/maintain; explicit employer in bio *if* their ToS allows this kind of indexing (much less aggressive than LinkedIn, but you still need to read them carefully).

You will not get the clean, single-source “Senior Director at X, previously Y, Z.” Accept that. Model employment as *best-effort timeline of affiliations with citations*, and show users exactly how uncertain each field is.

4. **Unit of result**

A global “person” is too coarse. An “artifact cluster” is too abstract for a buyer who needs a human to call. The right unit is:

> **(Person, Subdomain Topic) as an “expertise edge,” with attached evidence.**

Formally, something like `person --[has_expertise_in, confidence, time_span]--> topic`, where the edge is backed by a bag of `eigen_edge_evidence` documents.

Why this unit:

- It’s aligned with Eigen’s graph already (person entities + topic edges).
- It’s naturally query-scoped: you rank *edges* relevant to the question, then surface the person as the human, with all edge evidence explaining *why for this topic*.
- You avoid the fiction of “global expertise rank.” The same person may be top-3 for one sub-subdomain and irrelevant for another.

This *does* require cross-source ER for persons, but you can be conservative in v1: only merge identities when you have strong keys (email, ORCID, consistent name+affiliation across multiple connectors). Where you don’t, treat them as separate people and let the UI show that ambiguity.

5. **Legal constraints: ranking and defamation**

To stay out of NYC LL144 / EU AI Act high-risk territory and reduce defamation exposure:

- **Don’t position this as hiring/talent tooling.**
  - No ATS integrations, no “export as candidates,” no copy like “source talent” or “top candidates.”
  - No features explicitly about employment decisions (screening, shortlisting for hire, performance prediction).
- **Keep scores query-local and descriptive.**
  - Internally you rank, but externally you show “relevance” and *evidence counts*, not “9.3/10 expert score,” and never “top X% of candidates.”
  - Present it as a *search and research* tool: it helps you discover who to talk to for an investment thesis, not who to hire.
- **No sensitive/demographic inference or filters.**
  - Never infer gender, race, age, nationality, disability, etc.
  - No filters on school, age, or other obvious proxies that look like a screening tool.
- **Defamation mitigation via discipline of claims.**
  - Only assert claims that are strictly backed by `filed` or `observed` evidence (e.g., “Named as inventor on US patent XXX,” “Core maintainer of repo Y”), or tightly qualified `stated` claims (“Describes themselves as…”).
  - Avoid negative/value-laden language (“incompetent,” “fraud,” “low-quality researcher”). Your fail-safe is omission and abstention.
  - Make provenance visible on every card and allow individuals to request removal or correction; especially for EU/UK, you need a subject-access and rectification story anyway.

This is not bulletproof, but it keeps you clearly on the “research copilot” side rather than the “automated hiring/screening” side.

6. **What to cut from v1**

A believable two-week v1, leveraging what you already have:

- **Scope:** tech vertical only, no LinkedIn, no new connectors.
- **Input:** a research question or thesis tag (“vector databases for recommender systems”, “lab automation in synthetic biology”).
- **Output:** a list of, say, 10–30 `(person, topic)` cards:
  - One-sentence summary: “Works on X at Y; visible contributions in Z.”
  - A compact “Evidence of expertise” block with 3–8 artifacts (papers, patents, repos, grants, filings) and explicit `filed`/`stated`/`observed` tags.
  - Minimal “coverage view”: which topic facets they cover vs your query.
  - Links to source docs; optionally surfaced contact vectors only if already in your corpus (personal website, email on paper, GitHub profile link).

This is mostly: new retrieval/ranking glue over `eigen_topic_edge` + a slim UI.

What I would explicitly *refuse* for v1:

- Any LinkedIn dependence (scraping or API) or other gray-area social scraping.
- Cross-domain “expert index of the world”; stay within domains where your connectors are strong.
- Fit/quality scores (N/100 expert score, “Tier 1 expert”) that pretend to be more than “relevance to query + evidence count.”
- Automated outreach, compensation, or compliance flows (no “book a call,” no KYC/AML, no NDAs) — that’s how you drift into full expert network complexity.
- Any “talent search” framing or features that resemble candidate screening.

7. **Sharpened thing you haven’t asked**

You are one small product decision away from diluting Eigen into a generic “smart people search” tool, which is a brutal, sales-heavy, lowest-common-denominator space. Your unfair advantage is not that you can find people; it’s that you can *argue, with evidence, about where a thesis is weak*, and then show which humans sit closest to those weak spots. If “Experts Search” does not visibly change what an investor *believes* about a thesis before they ever schedule a call, then you’ve built lead-gen for Tegus rather than a product in its own right, and almost all of the surplus will accrue to whoever actually runs the calls.
