Here is a hard, critical review of the `investors.md` spec, ranked by severity from fatal structural flaws down to scope bloat. 

### 1. Critical: The `domain` primary key guarantees silent data loss (Ref: §2, §3.1)
**Objection:** Keying `iv_firm` strictly by "registrable domain of the firm's own site" (§2) mathematically breaks your own free spine. In §3.1, you note there are 6,686 Exempt Reporting Advisers, but only 5,227 have a website. Because your primary ID is the domain, you are silently dropping 1,459 registered US venture/PE firms before the system even boots. 
*   **Renamed firms/Multi-brand:** If a firm changes from `sequoiacap.com` to `peakxv.com`, they are treated as two disconnected firms. How do you attribute the pre-split `observed` portfolio? You don't.
*   **No-website syndicates/angels:** Angel syndicates rarely have dedicated domains. Keying by domain means they simply cannot exist as an `iv_firm` unless you invent dummy domains. 
*   **The Fix:** The primary key must be an internal UUID or Eigen-specific slug. Domain is an *attribute* that acts as a strong merge signal, not the primary key.

### 2. Critical: The cohort gate fails to stop survivorship bias, generating VC lies (Ref: §5, §3.5)
**Objection:** The `cohort_bound` trap (`n ≥ 5`, age `≥ 3 years`) is dangerously insufficient to protect the "outcome mix" from selection bias. It will emit exactly the inflated numbers you are trying to avoid.
*   **The flaw:** Your `observed` edges come heavily from "The firm's own site" and "Portfolio pages" (§3.4, §3.5). VCs actively scrub dead companies from their websites. 
*   **The wrong-but-plausible number:** A firm funded 20 companies in 2021. 14 died, 6 lived. They scrubbed the 14 dead ones from their site. We scrape the 6 survivors. We see `n=6` (passes gate) and `age=5 years` (passes gate). Your system confidently emits: **"100% active/success rate for 2021 cohort"**. 
*   **The Fix:** If the denominator relies on a source controlled by the subject (their own portfolio page), you cannot publish a "success rate" or "outcome mix" without a giant warning that it is heavily biased, or you must restrict outcome calculations *only* to edges discovered independently (e.g., Form D filings).

### 3. High: The Three-Register model will collapse the UI for founders (Ref: §0, §4)
**Objection:** The filed/stated/observed separation is intellectually pure for the card display, but it creates a UX nightmare for the rail and search parameters.
*   **The UX break:** A founder comes to search: *"Who funds pre-seed AI infra... writes $250k–1M"* (§0.5). To do this, they must use the `stated_check_min` and `stated_stage` filters on the rail. But what if a firm *actually* does this (observed via edges) but doesn't explicitly write "We write $250k cheques" on their landing page? The founder filters them out. 
*   **The consequence:** If a founder has to select `stated_stage: seed` OR `observed_stage: seed` to get a complete list of seed investors, the UI is broken. If you merge them under the hood to make the search work, you violate the core principle of §0 ("never a filter that claims to be true"). 
*   **The Fix:** You need a unified query engine that searches across registers but clearly attributes the *match reason* in the result (e.g., "Matched Seed because: Stated on website").

### 4. High: Angel coverage mandate contradicts the promotion rule + PII risks (Ref: §2, §5)
**Objection:** The owner wants "aggressive" angel coverage, but the rule states: "no card until a strong id is stated... a name match alone never promotes" (§2).
*   **The contradiction:** If an angel is named as a participant in 20 press-released rounds but has no personal website or linked social profile, they remain a ghost text string. This heavily penalizes quiet, high-value angels—exactly the people founders want to find.
*   **Privacy/PII risk:** You are taking private individuals (angels) and computing financial metrics (`led_round_size`, `outcome_mix`) based on scraped data, then publishing it. Under GDPR and CCPA, constructing financial profiles of individuals from disparate data sources without consent is a massive legal risk. "Suppression, not deletion" (§2) is not a legally sufficient defense for PII. 
*   **The Fix:** Do not compute or render `observed` financial metrics (like round sizes or success rates) for `iv_person` entities. Restrict those computations to corporate `iv_firm` entities. 

### 5. Medium: Cost/Effort realism is a fantasy, specifically around PDFs and global registers (Ref: §6, §3.6, §3b)
**Objection:** Claiming this is built on a "free spine" with zero model spend for ingestion is false.
*   **LP Returns (§3.6):** CalSTRS/CalPERS publish returns in massively complex, heavily formatted, annually changing PDFs. Extracting `net_irr` reliably from these is not a "small parser" job—it requires OCR/Vision models and constant maintenance.
*   **Global Registers (§3b):** India's SEBI AIF tables are often AJAX-heavy or require CAPTCHAs. EU ESMA is fragmented. Scraping these reliably without getting IP-banned is a heavy data engineering lift, not a "free" adapter.
*   **Missing Source:** You are missing **SEC Form 13F** filings. For late-stage/crossover funds (Tiger, Coatue) holding public equities, 13F is structured, free, and explicitly tracks actual holdings.

### 6. Low/Strategic: What must be CUT to ship (Ref: §7)
**Objection:** The spec is bloated with "diligence" features that distract from the core founder use-case.
*   **CUT LP Returns (Tranche 3):** Founders do not care about a VC's Net IRR or DPI from CalSTRS. They care if the VC has a fresh fund (`still_deploying`) and writes cheques. Building a fragile PDF parser for 5 public pensions is a complete waste of v1 engineering cycles.
*   **CUT Global Registers for v1 (Tranche 0b):** Ship US ADV + Form D first. Prove the three-register UI works. Trying to map SEBI and FCA regulatory edge cases into your schema before verifying the core UX will stall the project for months. Own the US bias in v1, label it clearly, and expand later.
