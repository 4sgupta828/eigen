# Panel: gemini talent

Verbatim transcript. Relayed honestly, including where it disagrees with the spec and with the
other panelist. The synthesised call is in `docs/specs/experts-search.md` §11.

---

**1. The Triad Thesis: Plausible Symmetry, Fake Jobs**

The "Startups, Investors, Talent" triad is aesthetically pleasing symmetry that fundamentally misinterprets how venture capitalists operate. "Talent" is not a co-equal, third leg of the stool; it is a subordinate dimension of a startup, or an input to an expert network.

**The Fake Jobs:** Broad, top-of-funnel talent sourcing ("Find me 50 senior ML engineers in SF open to work"). VCs are not recruiters. While some top-tier funds have internal talent partners to aid portfolio companies, deploying a "shadow LinkedIn" for this is a commodity SaaS play. If you build this, you are competing with recruiters' tools, not augmenting an investment thesis.

**The Real Jobs:**
*   **Team Verification (Diligence):** Has this founding team actually worked together before? Do their claimed academic credentials match their actual publication history? 
*   **Expert Sourcing:** "We are looking at a startup doing solid-state batteries. Find me three former patent authors in this exact sub-field who are no longer at major OEMs to use as diligence references."
*   **Momentum/Bleed Signals:** "Show me the net-flow of senior engineers out of OpenAI into this specific subset of AI startups."

A generic "Talent Search" mode solves the fake jobs. To solve the real jobs, talent must be deeply integrated into the DeepDive (company focus) or the ReAct Q&A loop (thesis focus), not isolated in a separate directory.

**2. Port, Rebuild, or Generalize?**

**Do not port.** Roster is a fork, and its core value (entity resolution) does not exist yet. Porting it means importing an empty UI over raw data, paying a massive Git merge penalty, and inheriting a parallel domain model that dilutes your kernel.

**You must choose (c): Generalize the Evidence Map.** 
Roster's spec is actually right about the primitive. An "Evidence Map" is the missing abstraction in Eigen. Right now, Eigen's Startups and Investors modes are hardcoded, domain-specific silos. Building an Evidence Map primitive into the `kernel`—where rows are generic entities linked to user intents, supported by explicit, typed evidence—is the only way to avoid the "three separate tabs" death spiral. 

The honest cost of (c) is a major architectural refactor. It will take a month to rip out the hardcoded `su_map` and `iv_map` logic and re-seat them on a generic Evidence Map. But it is the right architecture. If you choose (b) and just rebuild a Native Talent mode, you are just duct-taping a third silo onto the app shell. If a user asks, "Who are the key players in localized grid storage?", the system should return an Evidence Map containing a mix of Startups, Investors, *and* Researchers. That is impossible if they live in different API modes.

**3. The Evidence Taxonomy Collision**

**Reject Roster’s 9-level taxonomy entirely. It commits a fatal ontological error.** 

Roster conflates *provenance* (where did this come from?) with *epistemic status* (how much do we trust it?). "Employer-stated" is provenance. "Inferred", "corroborated", and "weak" are epistemic judgments. "Inferred" is literally the *absence* of direct evidence—it is a synthesizer's guess. 

If you adopt Roster's taxonomy, you violate Eigen’s Standing Directive #1 (Congruence). You can no longer trace a claim back to a specific, tangible subject-kind match. You cannot say "Show me the document that proves this" if the evidence type is "inferred."

**The Solution:** Map Roster's data into Eigen's existing three registers (`filed`, `stated`, `observed`).
*   A patent listing a person as an inventor is `filed`.
*   A company website listing a team member is `stated` (by the employer).
*   A person's own blog or GitHub bio is `stated` (by the person).
*   A GitHub commit linked to their email is `observed`.

To handle the epistemic nuance Roster was aiming for, extend Eigen's `basis` field to include a `confidence_score` or an `inference_chain` metadata block, but the *evidence register* remains strictly tied to the artifact's nature. This preserves your fail-safe of abstaining when explicit evidence is missing.

**4. The Hardest Problem: Entity Resolution**

Entity resolution—disambiguating "John Smith" the GitHub committer from "John Smith" the patent author—is notoriously difficult. It requires probabilistic record linkage, and VCs have zero tolerance for false positives in diligence. If Roster lists this as "NOT YET BUILT," then Roster does not actually have a product; it has a pile of scraped lists.

If you port Roster today, you are copying technical debt.

**The valuable, un-resolved version:** Drop the dream of a global "Shadow LinkedIn" graph. Instead, build **Context-Bound Extraction**. 
Do not try to maintain a persistent, universal record of "Dr. Sarah Chen." Instead, when a user runs a DeepDive on Startup X, dynamically pull the Form Ds, the patent assignees matching Startup X, and the academic papers funded by or affiliated with Startup X. The *company* acts as the bounding box for identity. You don't need to know where Dr. Chen went to high school; you only need to know that a Dr. Sarah Chen is listed as the PI on this company's foundational patent and is also currently committing code to their open-source repo. This sidesteps the global entity resolution nightmare entirely while perfectly serving the VC's actual diligence job.

**5. PII / Legal / Ethical Constraints**

Building a "shadow LinkedIn" of private individuals inside a high-priced financial tool is a massive, unnecessary liability. 
*   **GDPR/CCPA:** You are processing PII. "Legitimate interest" is a notoriously weak defense for compiling shadow profiles of private citizens without their consent, especially if those profiles are used in financial/investment contexts.
*   **ToS Violations:** The open web is not a free-for-all for PII. Scraping LinkedIn or Twitter for employment data routinely triggers C&Ds and IP bans. 

**The Product Constraint:** You must adopt a **"Public Professional Artifact"** constraint upfront. 
Explicitly ban the ingestion of social media profiles, inferred demographics, or scraped resume aggregators. Your talent data must come *only* from artifacts that are already matters of public regulatory, scientific, or corporate record:
1.  SEC filings (Form D executives).
2.  Patent registries (Inventors).
3.  Academic publishing graphs (Authors).
4.  Open-source repositories (Committers).
5.  Public company domain "Team" pages.

By restricting your corpus to these, you operate firmly within the realm of professional public artifacts, dramatically lowering your PII exposure, bypassing the LinkedIn ToS wars, and increasing the signal-to-noise ratio for deep-tech VC diligence.

**6. The Sharpest Thing You Have Not Asked**

You are mistaking a data category for a product feature. By trying to build separate "modes" for Startups, Investors, and now Talent, you are regressing into a Web 1.0 directory model, completely underutilizing your ReAct Q&A kernel. A true intelligence platform doesn't ask the user to choose a noun before they search. The user should ask a question—"Who is leading the transition from liquid to solid electrolytes?"—and the kernel should navigate the `rs_block` corpus to return a synthesis backed by a unified Evidence Map that includes the startups building it, the VCs funding it, and the researchers authoring the patents. Stop building siloed directories. Force your kernel to become entity-agnostic.
