# Panel: gemini

Verbatim transcript. Relayed honestly, including where it disagrees with the spec and with the
other panelist. The synthesised call is in `docs/specs/experts-search.md` §11.

---

**1. The wedge against Tegus / AlphaSense / GLG / Third Bridge.**

You do not have a wedge against GLG or Tegus. You have a fundamental misunderstanding of what those companies sell. They do not sell "discovery." They sell compliance-wrapped access, scheduling logistics, and historical transcripts of bespoke conversations. They are in the brokered-trust business. Eigen is in the document-parsing business. If you build "Expert Search," you are building a feature, not a product, and you are aiming it at a buyer who expects a transcript, not a Github link. 

To make this a thick wedge, you must invert the incumbent model. GLG provides former VP-level executives who sit on five different expert networks and give rehearsed, macro-level boilerplate. Eigen’s wedge must be discovering the *un-networked practitioner*—the Principal Engineer who actually committed the code for the specific vector indexing algorithm the startup is trying to disrupt, or the named inventor on the blocking patent. The buying moment is not "I need an expert on AI." The buying moment is "This startup claims their multi-modal routing is novel; I need to speak to the three people on earth who built the open-source precursor to know if that claim is true." You are selling extreme, evidence-backed technical relevance, not rolodex access.

**2. Is expertise measurable from artifacts without becoming vanity metrics?**

Not globally, and you shouldn't try. Citation counts, stars, and h-indexes are highly gameable vanity metrics that actively contradict Eigen’s standing directive: *evidence is typed.* A star on GitHub is sentiment, not a fact.

The honest unit of expertise for a diligence buyer is **Artifact-to-Thesis Distance**. You do not measure how "expert" someone is generally; you measure how densely their *observed* and *filed* artifacts intersect with the specific technical nodes the investor is investigating. The measure is a pure count of distinct `eigen_topic_edge` intersections: how many times does this person appear as the object of an `authored`, `invented`, or `committed_to` relation connected to the target technical concept? 

What this systematically misses: Trade-secret operators. You will completely miss the Apple engineers, the Renaissance Technologies quants, and the AWS infra operators who publish nothing, patent everything under generic corporate assignees, and never commit to public repos. It also misses managerial competence. You will find the person who wrote the code, not the person who scaled the team. You must explicitly warn the buyer of this blind spot.

**3. LinkedIn.**

There is no compliant path to scraping LinkedIn at scale for a commercial B2B data product. The CFAA rulings in *hiQ v. LinkedIn* were narrow, continuously litigated, and do not protect you from aggressive ToS enforcement, IP blocking, and cease-and-desists. Furthermore, scraping PII for commercial indexing without consent is a massive GDPR/CCPA liability. LinkedIn data is also entirely *stated* evidence—it is self-published marketing, not peer-reviewed reality.

Drop LinkedIn immediately. You already have the substitutes actively ingesting.
*   **Current role & Employer:** GitHub org memberships (current collaboration), OpenAlex/Arxiv institutional affiliations (academic/corporate lab roles), and SEC Form D / S-1 filings (officers/directors).
*   **Employer History:** USPTO patent assignment history. If an inventor files patents assigned to Google in 2018 and OpenAI in 2023, you have a timeline. NIH/NSF grant histories provide similar tracking for PIs.
*   **Seniority:** Derived purely from the volume and timespan of *filed* (patents) and *observed* (commits/papers) evidence. 

You will lose the mid-level Product Managers who only exist on LinkedIn. Good. They are useless for deep-tech diligence anyway.

**4. What is the UNIT of the result?**

The unit must be the **Expertise Cluster**, anchored to an artifact, not a "Person." 

If you attempt to make the unit a "Person" (e.g., a unified profile for "John Smith"), you will paralyze your engineering team with cross-source entity resolution. You will spend months trying to figure out if `j-smith99` on GitHub is the same John Smith on a USPTO filing from 2019. 

Instead, the unit is a specific technical claim or node in your `eigen_topic_edge` graph, returning a cluster of `(Artifact, Author_String, Provenance)`. You present the user with: "Here are the 14 patents, 3 papers, and 5 repos matching this technical thesis, and the raw name strings attached to them." Let the human brain—the most advanced entity resolution engine on earth—look at the list and realize that "J. R. Smith" on the paper and "John R. Smith" on the patent are the same guy. Store the artifacts; group by exact name match; do not synthesize a global person entity.

**5. Ranking people is legally loaded.**

You are operating dangerously close to NYC LL144 (Automated Employment Decision Tools) and the EU AI Act (which categorizes AI used in employment/recruitment as high-risk). Defamation and tortious interference are also risks if your LLM hallucinates and attributes a negative trait, fraudulent project, or competitor’s failure to a specific private individual.

Concrete product constraints to avoid this:
1.  **Never output a score.** Do not have an "Expertise Score," a "Rank," or a "Quality Index." Sort results strictly by chronological recency or by a dumb Boolean match count (number of relevant artifacts).
2.  **No synthetic summaries of people.** Adhere strictly to the verbatim span-check provenance gate. Do not let the ReAct loop write a summary saying "Jane Doe is a leading expert in quantum routing." The system may only output: "Jane Doe is listed as an author on three papers regarding quantum routing [cite] [cite] [cite]." 
3.  **UI Framing:** Frame the feature not as a "People Search" but as an "Authorship Facet" on a standard document search. You are searching for *work*, and filtering by who produced it. This keeps you in the realm of document retrieval, not human assessment.

**6. What would you cut from v1?**

I would cut any attempt to build a standalone "Experts Search" interface. 

To ship in two weeks, leveraging your working corpus and edge graph, build an **"Author Evidence Panel"** appended to the existing DeepDive dossier. When the investor runs a DeepDive on a startup, Eigen already extracts the technical claims and queries the graph. Simply add a module that runs a `GROUP BY author_name ORDER BY COUNT(distinct evidence_id) DESC` SQL query against the `eigen_topic_edge` nodes related to the startup's claims. 

**Refuse to build:**
*   Cross-source entity resolution for names.
*   Contact information extraction (no emails, no phone numbers). If the investor wants to call them, they can figure out how to contact them. You are a diligence platform, not ZoomInfo.
*   Any integration with external expert networks or scheduling APIs.

**7. The sharpest thing you would tell the owner that they have not asked.**

You are pivoting to Experts Search because you fundamentally doubt your own product's core value proposition. Eigen’s entire premise is that the Kernel and the ReAct loop can read, synthesize, and validate complex technical evidence better and faster than a human. If your system successfully parses the patents, the code, and the papers to validate the startup's technical claims, *why do you need to find a human for the investor to call?* By building a tool to broker human conversations, you are tacitly admitting that your machine-generated dossiers are not conclusive enough to drive an investment decision. If the artifacts are the diligence, force the user to trust the artifacts. Stop trying to build a recruiting tool to compensate for a lack of conviction in your AI's synthesis.
