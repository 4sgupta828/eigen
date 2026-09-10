Below is a critical pass, organised by your 7 questions and tagged by severity:

- P0 = will mislead users / violate “evidence is typed” ethos
- P1 = major correctness or scope risk
- P2 = makes v1 slower or more fragile but not fatal
- P3 = polish / nice-to-have

---

**1. Three‑register model (filed / stated / observed)** — **Severity: P1**

- The abstraction itself is right for CLAUDE’s “evidence is typed” directive, but the *UI semantics* are brittle. You are putting three conceptually different things behind one rail and set of sorts (docs/specs/investors.md:16‑27, 193‑247). A founder will not reliably internalise “stated = intent, observed = our partial view” when they are exposed as ordinary filters and ranking weights.
- Where it breaks first is **sorting and success-ish facets**:
  - You already weight `stated_stage`, `observed_sector`, `co_investor` in ranking (line 245‑247) without distinguishing register in the sort semantics. That is de‑facto merging registers, even if the glyphs differ.
  - `follow_on_rate` and `outcome_mix` are in the same observable rail as “safe” observed facts (portfolio_count, co_investor, etc., lines 221‑235). Even with denominators, many users will mentally treat “70% follow‑on” as a property of the firm, not “over 10 of their companies we happen to see”.
- The compile story is underspecified and likely to collapse: if a founder types “funds with good success rate” you either (a) silently ignore it, or (b) compile it to thresholds on `follow_on_rate` / `outcome_mix` which you *know* are coverage‑biased. The spec never pins what is allowed there.
- **Concrete change I’d make for v1**: 
  - Keep the three registers in storage (`iv_fact.register`, `iv_fact.denominator`, docs/specs/investors.md:291‑305), but **do not expose `follow_on_rate` or `outcome_mix` as filterable or sortable facets at all**. Show them only inside the dossier with loud wording (“Over 7 companies we see, not the whole fund”).  
  - Restrict the rail to filed + stated keys; treat observed success metrics as read‑only diagnostics. That keeps the 3‑register model but removes the most failure‑prone part from the contract.

---

**2. Identity model (firm / fund / person / angels)** — **Severity: P0**

You’re right to fear merges more than splits, but there are still real collision and fragmentation modes.

- **Firms with no website (big hole)**  
  - Spec says `iv_firm.id` is “registrable domain of the firm’s own site” (docs/specs/investors.md:107‑111), and the DDL hard‑codes `id (domain)` (docs/specs/investors.md:291‑292). ADV and non‑US registers absolutely contain managers with no web site or with only an email/contact form.
  - The jobs table (`adv`, `registers`, docs/specs/investors.md:316‑318) doesn’t say what happens when you have CRD/FRN/etc. but no domain. Today you *must* either:
    - Mint synthetic ids (`crd:12345`) and later migrate them when you discover a site, or
    - Drop them entirely from v1.
  - Without a migration/alias story, the realistic outcome is **duplicate firms**: first row keyed by `crd:12345`, later a second keyed by `examplevc.com` when `sites`/`portfolio` discovers a URL. The eval case “non‑US firm with no ADV registration must not read as small” (docs/specs/investors.md:359‑361) doesn’t cover this.
- **Multi‑brand and renamed firms**  
  - Spec *intends* Sequoia / Peak XV to be distinct cards (docs/specs/investors.md:103‑105, 359‑361). That’s fine, but you still need a plan for:
    - Single legal manager running multiple brands on *different* domains (e.g., separate seed / growth brands). You will have one `iv_firm` per domain, but ADV & LP disclosures are per legal entity. Today your schema only has `iv_return.fund_key` (docs/specs/investors.md:299‑300) and a single `iv_firm.crd`. You will either double‑count returns across brand cards, or arbitrarily attribute them to one.
    - Rebrands that *do* share CRD/CIK: you say strong ids `crd:<n>` and `cik:<n>` “merge” (docs/specs/investors.md:107‑111), but evals demand Sequoia / Peak XV stay two cards. That’s a direct tension: same CRD implies one `iv_firm`, evals insist on two.
- **Fund families**  
  - Keying `iv_fund` by Form D file number (docs/specs/investors.md:112‑115) is right, but your attach rule (`vehicle_bound`, lines 264‑270) is insufficient for large complexes:
    - Large platforms use shared GPs and addresses across vehicles. The intersection‑of‑people rule is necessary but not sufficient; you will attach specialty or secondary funds to the main flagship firm because the GP set overlaps.
    - You don’t distinguish feeders / parallel funds beyond the fund type flags already in Form D. That’s fine for card‑level “funds_count”, but it’s not fine once you start aggregating LP‑reported IRRs – they’re often reported per umbrella “Fund X” while underlying Form Ds are many file numbers.
- **Angels and two‑person syndicates**  
  - Angels are keyed `angel:<name_slug>` (docs/specs/investors.md:121‑125). That plus the current `founder_links` logic on company sites (apps/api/startups/sources/site.py:133‑155) is enough to **silently merge two different people** if they share a full name *and* a LinkedIn slug or X handle – which is not impossible when handles get reused or sold.
  - Two‑person brands (“Alice & Bob Angels”) will come through company pages as a single name string; under the current rules that becomes *one* `iv_person` with edges from all their deals. There is no way to recover the individual people later.
  - Conversely, informal syndicates that companies list as “Alice Smith, Bob Lee” will create two `angel:<slug>` ids even if they always invest together; your “primary population from company sites + press” (docs/specs/investors.md:171) doesn’t attempt to model “syndicate as unit” at all.
- **Multi‑brand firms and slug collisions**  
  - Slugs for startup investors are minted via `slug()` (apps/api/startups/store.py:193‑195) from free‑text names, and you treat `slug` as a strong id for `iv_firm` (docs/specs/investors.md:107‑111). If two distinct funds share the same printed name in different geos (plausible for generic names), they collide in `su_investor.slug` (apps/api/startups/store.py:173‑178) and so in `iv_firm.slug`. You’ve banned name‑similarity merges, but you *do* merge on slug; that’s a hidden name‑similarity path.

**My view**: the identity model is directionally right, but you need explicit rules for (a) no‑website firms, (b) how strong‑id merges interact with deliberate multi‑card cases like Sequoia/Peak XV, and (c) when to *refuse* to attach LP performance and success metrics to `iv_person` at all.

---

**3. “Success rate” and cohort gate** — **Severity: P0**

The `cohort_bound` rule (docs/specs/investors.md:256‑262) fixes only one failure mode: “all active because it’s too recent.” It does not address survivorship or selection bias.

- **Selection bias on the company side is unbounded.**  
  - Edges come from Form D, portfolio pages, and “investors / backed by” sections plus press (docs/specs/investors.md:136‑139, 171). That strongly favours:
    - US companies (Form D).
    - Higher‑profile rounds and companies that still maintain web pages.
  - For a 2015 seed fund that did 30 deals, it’s entirely plausible you only ever see 8–10 of them in `su_company` (because the rest died quietly / never filed / are not in your corpus). Yet your cohort gate triggers on `n ≥ 5` **over your observed edges**, not true portfolio n.
  - You can easily emit “40% acquired or public; 60% still active (n=10, vintage 2015)” when the *real* base is 30 with 3 exits and 20 write‑offs. A VC who knows their book will call that number wrong, even if you print “10 companies we hold” under it.
- **Follow‑on rate is even more fragile.**  
  - Defined as “share of their companies that raised again ≥ 12 months after the edge’s date” (docs/specs/investors.md:232). You only observe follow‑ons if:
    - There’s another Form D, or
    - There is press you picked up with your funding‑news + site extractor (startup‑search spec, docs/specs/startup-search.md:68‑71, 170‑171; extract.py).
  - That structurally over‑weights US, noisy, high‑signal winners and late‑stage rounds; quiet bridge rounds or small follow‑ons vanish. A firm whose US winners are oversampled and non‑US losses are invisible will look like a monster.
- **LP returns are safer but still identity‑fragile.**  
  - You gate IRR strictly on “named LP disclosure” (docs/specs/investors.md:237‑243), which is correct from an evidence perspective. The remaining risk is mis‑attachment of funds in complexes (see identity critique above), not selection bias per se.
- **Strongest wrong‑but‑plausible number I think you can still emit**  
  - A 2014 vintage seed firm that did 25 deals. Your data only ever sees 7 of them (US + high‑profile). Of those 7, 3 are acquired/public, 4 are still active, 0 marked shut down.  
  - Under your rules this cohort passes: vintage ≥3 years, n=7≥5. You happily show something like  
    - “Outcome mix (2014‑vintage, 7 companies we hold): 43% acquired/public, 57% active, 0% shut down; follow‑on rate 86%.”  
  - A partner at that firm, who knows they have maybe 3 winners out of 25, is going to say “those numbers are wrong” even with the denominator printed. The *shape* (most companies successful) is the lie, not the digits.
- **Mitigation**: For v1, I would:
  - Forbid **all** success‑rate‑style facets in the rail and sorts; keep them inside `/investors/{id}` only, with explicit wording “over 7 of N companies we see, which is a strict subset of their portfolio”.
  - Add a second gate that hides `outcome_mix` and `follow_on_rate` unless `portfolio_count_observed / portfolio_count_true` can be lower‑bounded, e.g. via ADV AUM and fund size or Form D investors_count; otherwise, label them as “insufficient coverage to estimate outcomes”.

---

**4. Sources: missing or unusable** — **Severity: P2**

- **One high‑value free source that’s missing**  
  - For the PE / venture‑debt / SBIC corner of your “investor_type” taxonomy (docs/specs/investors.md:197‑199), the **US SBA SBIC licensee lists** are a natural fit: they’re an official list of licensed SBIC managers and funds, including location and license status. They’d give you structured coverage of an entire important investor type (US small‑business PE / debt) that’s now only captured indirectly via ADV / Form D. The canonical entry point is on `sba.gov` under the SBIC program pages; you’d need to check the current URL and ToS before ingesting.
- **Likely‑tricky sources already in the spec**  
  - FCA’s JSON API, MAS FID, ADGM/DFSA registers and several angel‑network directories (docs/specs/investors.md:156‑160, 167‑170) are all *interactive* sites, not stable zipped datasets like ADV/Form D. Expect:
    - Per‑IP rate limits and session cookies that make naive cron‑jobs brittle.
    - Per‑site ToS that may restrict bulk download for commercial use. The spec assumes “all free, all downloadable” (line 132) but doesn’t talk about licence terms — e.g. Companies House PSC bulk is under the UK Open Government Licence and at minimum requires attribution (docs/specs/investors.md:160).
  - You also list Wikidata as a fallback identity source (docs/specs/investors.md:160‑161). That’s OK as enrichment, but its CC‑BY‑SA licence can be viral; the spec should explicitly constrain how you surface Wikidata‑derived facts to avoid needing to treat Eigen as a derivative database.

I wouldn’t call any of the listed sources totally unusable, but there is non‑trivial engineering and legal diligence buried behind the “all free, all downloadable” claim.

---

**5. Angel coverage, “strong‑id only”, PII/defamation** — **Severity: P0**

- **“No card until strong id” is necessary but not sufficient.**  
  - The promotion rule (docs/specs/investors.md:121‑125) is good, but it only protects against *fabricated* people. It doesn’t protect against:
    - Wrongly merged angels (same name + same LinkedIn slug, see above).
    - Cards for real people whose only evidence is a small handful of web mentions plus a scraped profile link.
  - Given the owner’s “FULL angel coverage” goal, the pressure will be to treat any `angel:<slug>` with ≥5 edges as “card‑worthy” even if the strong id signal is weak or ambiguous. The spec doesn’t put any hard cap on that.
- **Defamation / unfair inference risks on individuals**  
  - The same observed success metrics (`follow_on_rate`, `outcome_mix`) and LP‑style notions are implicitly applicable to `iv_person` because `iv_fact` has no “kind” column and the facet schema is “entity kind investor” generic (docs/specs/investors.md:186‑190, 297‑299). There is *no explicit statement* that you will *not* compute follow‑on rates / outcomes for individual angels.
  - Publishing “Angel X — 0% follow‑on (n=5, vintage 2017‑2019)” based on your partial corpus is exactly the sort of reputational hit that will look like defamation to a human if it’s wrong or heavily biased. The fact that it’s technically “observed” and has a denominator glyph doesn’t change that.
  - Combining that with scraped LinkedIn / X / personal site links (docs/specs/investors.md:122‑123; apps/api/startups/sources/site.py:133‑155) amplifies the harm: you’re effectively attaching a negative metric to an identifiable individual with direct contact links.
- **PII boundaries are underspecified.**  
  - For angels you’ll inevitably see personal emails, secondary employers, etc., on company pages and network directories. The spec is explicit about PII minimisation on founder bios (startup‑search.md §4.4) but silent for investors. There is no rule like “store no personal emails, phone numbers, or home addresses; use only professional websites and public profiles already printed.”
- **Suggested spec changes**  
  - State explicitly in investors.md that:
    - `follow_on_rate`, `outcome_mix`, `regulatory_disclosures`, and all LP‑style return metrics *never* apply to `iv_person` (angels or firm people). For individuals, you show only portfolio edges and neutral facts (“named by N companies we index”), not outcome or compliance metrics.
    - Angel cards require *both* a strong id *and* a minimum evidence diversity (e.g., at least two independent sources mentioning the same strong id), not just one scraped LinkedIn link from a company team page.
    - You will not store or surface emails / phone numbers or non‑public addresses for individuals; only links that were already printed on public firm or company pages.

---

**6. Cost / effort realism** — **Severity: P1**

The $50 claim (docs/specs/investors.md:331‑333) is optimistic even if token prices cooperate; more importantly, it ignores *engineering* cost on the “free” side.

- **You’re undercounting LLM spend for angels and people.**  
  - The `angels` job is marked as free (docs/specs/investors.md:325), but the only realistic way to harvest “named individuals from 32,101 company pages we already hold, from press, and from Form D related persons” without unacceptable noise is to reuse the same 3‑gate extractor pattern you already use for founders and investors in Startup Search (apps/api/startups/extract.py:1‑56, 176‑219). That is one LLM pass per company or per batch of pages.
  - If you *don’t* use an LLM here, you’re relying on brittle regex/name heuristics over arbitrary marketing copy. Either your precision is too low for production, or your recall is too low to meet the “FULL angel coverage” promise. In both cases the “free” label is misleading.
- **Re‑runs and refreshes blow up the “$50 once” assumption.**  
  - `terms` runs “read stated stage / cheque / ownership / geo / leads‑or‑follows off crawled firm pages” (docs/specs/investors.md:328‑333). That needs to be re‑run:
    - Every time sites change materially (and you *do* plan quarterly crawls, similar to Startup Search, docs/specs/startup-search.md:4.4).
    - Every time you significantly change the prompt, schema, or model.
  - Even if single pass is ~$50 on 5k firms, two schema iterations + one refresh per year already puts you at mid‑hundreds of dollars. That’s still small in absolute terms, but the spec’s “only ~$50 of model spend” is no longer true.
- **Engineering effort on “free” connectors is non‑trivial.**  
  - You’re proposing to build and maintain bespoke scrapers for ADV, at least 5 non‑US regulators, multiple pension funds, and several angel networks (docs/specs/investors.md:132‑171, 326). Each has its own schema evolution, down‑time, and ToS. None of that is accounted for in the tranches or budget narrative.
  - Startup Search v2 already had to walk back optimism on cost and complexity (docs/specs/startup-search.md:39‑45, 65‑70). You’re repeating the same pattern here: assuming all structural ingest is “just code” and only token costs matter.

---

**7. What to cut to ship something honest and useful sooner** — **Severity: P1/P2 mix**

If the goal is “founders can actually find relevant investors” rather than “research‑grade performance stats”, I would cut or defer:

- **Cut for v1 (P1 – distorts trust vs. effort)**  
  - All success metrics (`follow_on_rate`, `outcome_mix`, `net_irr_*`, `dpi`, `tvpi`) and the `Returns` section entirely (docs/specs/investors.md:237‑243, 351). They are (a) expensive to do right, (b) heavily coverage‑biased, and (c) high‑risk for defamation when mis‑attached. The honest MVP does *not* need them.
  - Angels v1 as full cards. Instead:
    - In v1, surface “Named angels” only as strings attached to company cards and per‑firm lists (“X is named by N of this firm’s companies”), *without* promoting them to first‑class search entities. Defer the `angels` job and `iv_firm(kind=individual)` (docs/specs/investors.md:325, 352) to a dedicated later tranche once you’ve proven you can keep firms clean.
- **Defer (P2 – scope / timeline cuts)**  
  - Non‑US registers beyond one or two easiest wins. The tranche plan insists `registers` + `networks` ship in v1 (docs/specs/investors.md:340‑346), but that’s a lot of surface. Ship US (`adv` + `funds` + `attach`) plus maybe one non‑US register where you already have experience (e.g. Companies House) before tackling MAS / SEBI / ADGM.
  - LP performance ingest (`lp` job, docs/specs/investors.md:326, 351). These PDFs are annoying to parse and identity‑match, and they don’t materially help a founder find a lead for a seed round.
  - Maps / compare for investors (`iv_map` family, docs/specs/investors.md:290‑301, 354‑355). You already have this working for startups (`su_map`, apps/api/startups/store.py:140‑164); reusing it is straightforward, but it’s still surface area and UI work. A simple list view with saved briefs would be enough for v1.

If you pared v1 back to:

- `adv` + `funds` + `attach` + `link` + `sites` + `portfolio` (jobs docs/specs/investors.md:316‑323),
- Filed and stated facets (schema docs/specs/investors.md:193‑219),
- Portfolio edges back into Startup Search (iv_edge → su_company),

you’d still ship something distinctly better than what founders have today — with far less risk of publishing “precise but wrong” performance numbers or over‑promising on angels.
