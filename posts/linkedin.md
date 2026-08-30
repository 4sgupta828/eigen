# Eigen — What would it take to trust AI with an investment memo?

*A LinkedIn post. Repo: https://github.com/4sgupta828/eigen*

---

**The problem with "AI for research":**

Ask a general model to "assess this company's competitive position and funding trajectory" and you'll get a fluent, authoritative answer that is part real, part confabulated — and no way to tell which sentence is which. For an analyst doing diligence, that's not a time-saver; it's a landmine. The value of research isn't the prose. It's the **traceability** — being able to stand behind every claim because you can point to the source.

**What I explored: Eigen — a vertical-agnostic, evidence-grounded research engine, deployed as a deep-tech / VC-diligence Q&A platform.**

The structural guarantee is the product: **a fabricated citation cannot reach the reader.** Before any claim enters an answer, the model must supply a verbatim quote, and deterministic code checks that the exact string exists in the block it cited. A quote that isn't really there fails a substring check and the claim is dropped — no "close enough." Eigen doesn't *know* things; it **finds** documents, **quotes** them, **verifies** the quotes exist, and only then **writes**.

Two more disciplines that matter in finance specifically:
- **Sentiment is a signal, not a fact.** News tone and social buzz are the lowest authority tier and can never be presented as established fact.
- **Stated intent ≠ realized fact.** A patent *application* or press release is intent; a *granted* patent or an audited filing is fact. Conflating them is how bad research gets made.

**What AI solves well:**
- Hybrid retrieval + synthesis across filings, patents, papers, and news — surfacing and connecting evidence a human would take days to assemble.
- Writing a genuinely useful, structured answer *once it's forced to stay grounded.*

**What AI does NOT solve — and where code must own it:**
- Its own citations. The provenance gate is deterministic on purpose. You cannot ask the model to police its own honesty.
- Authority ranking. What counts as a controlling source vs. a rumor is a policy the system enforces, not a judgment you delegate to the generator.

**What stays genuinely hard:**
- Freshness and completeness: markets move; "examine all competitors" is only as good as your coverage, and a retrieval sample quietly becoming "the whole universe" is a subtle, dangerous failure.
- The wrong-but-real citation: a quote that exists but supports a different claim than the one it's attached to. Verifying a string exists is necessary but not sufficient for *reasoning* correctness.
- Derivation: the real analyst value is a *reasoned conclusion*, not an evidence dump — and auditable, grounded derivation is much harder than grounded quotation.

**How to take it from here:**
- A second gate on *inference provenance* — not just "is the quote real?" but "does the conclusion actually follow from the cited evidence?"
- Coverage-driven retrieval that knows the difference between "the answer" and "a sample of the answer."
- Kernel/vertical split so the same engine serves legal, policy, or scientific diligence.

**Products this could become:**
- A diligence copilot that drafts the memo with every claim clickable.
- A monitoring engine that flags when new filings/patents change a thesis.
- A licensed "grounded research" platform per vertical.

**To go deeper, look up:** retrieval-augmented generation, attributed QA (AIS), reciprocal-rank fusion for hybrid retrieval, financial NLP, and the literature on faithfulness/hallucination in long-form generation.

The takeaway: **the future of AI research tools isn't a model that sounds like an analyst — it's an engine that can't make a claim it didn't retrieve, quote, and verify.**

#VentureCapital #InvestmentResearch #DueDiligence #RAG #FintechAI #TrustworthyAI
