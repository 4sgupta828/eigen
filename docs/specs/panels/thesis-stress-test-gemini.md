# Panel: gemini — thesis stress test

Verbatim. Relayed honestly, including where it disagrees with the spec and with the other
panelist. See `docs/specs/thesis-stress-test.md`.

---

**1. The limits of the corpus**
No. "Will product X sell?" is not answerable from documents. Willingness to pay (WTP) for a non-existent artifact leaves no digital exhaust. Documents record the past and the present; they record realized capital allocation and historical pain. They do not record future hypothetical budgets. 

If you attempt to synthesize "Will it sell?" from public text, you will build a hallucination engine that hallucinates positive sentiment from tech-optimist noise. 

What *is* answerable is **Historical revealed pain** and **Current capital allocation**. This residue is not merely consoling; it is the only empirical foundation a thesis can have. It filters out "delusional novelty" (problems no one is currently spending time or money to solve). It cannot prove a startup will succeed, but it can absolutely prove that the foundational premise of the thesis is false.

**2. The demand thesis ladder**
A demand thesis rests on a ladder of falsifiable propositions. Here is the strict decomposition and its settleability in Eigen:

1.  **The problem exists in the wild.** *Settleable.* (Observed: StackExchange workarounds, GitHub issues, Reddit rants. Filed: 10-K risk factors).
2.  **The status quo has a high, measurable cost.** *Settleable.* (Stated: Eng blogs detailing "how we cut AWS bills", "why we migrated". Filed: SEC margin compression commentary).
3.  **Capital/Headcount is actively allocated to the problem.** *Settleable.* (Observed: Job postings hiring humans to do what the software should do, RFPs, NIH/NSF grants).
4.  **A specific, reachable buyer role owns the budget.** *Settleable.* (Observed: Job descriptions for specific VP titles that explicitly own the incumbent tooling).
5.  **Switching costs from the status quo are surmountable.** *Unsettleable.* Requires private integration knowledge.
6.  **Future willingness to pay exceeds cost to serve.** *Unsettleable.* Purely forward-looking.

**3. The revealed preference trap**
Your instinct that "internal build effort" (a bespoke repo, a dedicated team) proves willingness to pay is fundamentally dangerous. 

It proves the problem is acute. It does *not* prove a market exists for a vendor. 

The failure mode is the **Strategic Core vs. Context** trap. If a company builds a system internally, it may be because the logic is so violently entangled with their proprietary data mesh, security posture, or core unit economics that a third-party vendor cannot legally or technically be allowed to run it. If five tier-1 companies build internal compute orchestrators, they aren't your future customers; they are hostile terrain. The mid-market, conversely, may not have the scale to experience the pain that justifies buying your solution. "Built internally" often equals "Unvendorable."

**4. Evidencing the absence**
"What happens in the absence of it?" is the most tractable question you asked. Documents are, by definition, monuments to the status quo. 

When a product does not exist, the market bleeds out in the form of "glue." You do not look for the absence; you look for the friction of the substitute. The sources that settle this are:
*   **Code:** GitHub repos acting as duct tape between two incompatible systems.
*   **Community:** StackOverflow threads with elaborate, multi-step manual workarounds.
*   **Careers:** The existence of operations roles (e.g., "Data Entry Specialist," "Reconciliation Analyst") whose entire job description is being a human API. 

This is Eigen's highest-value signal. We can definitively map the duct tape.

**5. Sourcing the buyer, not the expert**
Finding an expert is easy. Finding a budget owner is hard. Users complain; buyers allocate. Do not optimize for the loudest complainer who has $0.

Ranked by signal quality:
1.  **Job Postings (Highest):** If a company is hiring a "$150k/yr Director of X" and requires "Experience with [Incumbent Tool]," you have just found the exact buyer persona, their budget capacity, and their current vendor.
2.  **Incumbent Case Studies (High):** Vendor websites literally name the champion. "Jane Doe, VP of Logistics at Acme, used our tool to..." This is observed evidence of a past buyer.
3.  **RFPs/Tenders (High, but skewed):** Excellent signal, but heavily biased toward government, defense, and legacy enterprise. Ignores the mid-market.
4.  **10-K Risk Factors (Medium):** Proves board-level visibility of a pain point. Rarely names the person who holds the credit card.
5.  **Review Sites / Forums (Trap):** G2/Capterra and Reddit are written by end-users, not economic buyers. A tool that end-users hate but executives love will still sell.
6.  **Conference Talks (Trap):** Engineers talk about intellectually stimulating architectures, not vendor procurement processes.

**6. The split brain of the user base**
This is a feature, not a standalone product, and it competes directly with expert networks (GLG, AlphaSights) and Tegus. 

Crucially, **Investors and Founders want entirely different things.** 
An investor wants the cheapest, fastest "No" possible. They want you to kill bad deals so they can deploy capital efficiently. A founder wants a "Yes." They want validation of their life choices.

If you build this for both, it will fail. Pick Investors. Eigen is fundamentally an evidence machine; evidence machines are inherently hostile to startup delusions. Build it to ruthlessly disqualify theses.

**7. The honesty problem**
If you build this for investors, a negative result is a massive win. You save them weeks of diligence and millions of dollars. 

If you attempt to serve founders, the UI must frame absence of evidence not as failure, but as market reality. You rely entirely on the **Manifest of Absence**. 

Output must read: *"We searched 400,000 job postings, 50,000 RFPs, and 10 years of SEC filings. There is zero stated or observed evidence that companies are currently allocating capital to solve this specific problem. If you build this, you are not capturing existing budget; you must educate the market and create a new budget line."*

This turns a "Your idea is bad" into a strategic constraint ("You are a category creator, act accordingly").

**8. The smallest v1 (Two Weeks)**
**Build: The "Status Quo & Budget Mapper."**
Input: A natural language description of the problem/pain point.
Execution:
1.  Query GitHub/StackOverflow for the workarounds (The Duct Tape).
2.  Query Job Postings for the roles hired to mitigate the pain manually (The Human Cost).
3.  Query Incumbent documentation/case studies to extract the exact job titles that historically bought adjacent solutions (The Buyer).
Output: A strict dossier of *How the world currently survives without this product*, evidencing the exact cost of the status quo. 

**Refuse:** I would explicitly refuse to build any feature that outputs a "Market Sizing" (TAM/SAM/SOM), a predictive "Will it succeed?" score, or any synthesis of future willingness to pay. No hallucinated numbers.

**9. The sharpest unasked truth**
You are trying to replace the expert interview with document retrieval. You can't. The real play isn't using Eigen to *answer* the thesis; the play is using Eigen to **weaponize the expert call**. Use the corpus to generate the exact, hyper-specific anomalies, contradictions, and failing workarounds that the investor should interrogate the GLG expert about. Do not give them the answers; give them the most devastating, empirically backed interview script possible, complete with the names of the incumbents the expert previously bought.
