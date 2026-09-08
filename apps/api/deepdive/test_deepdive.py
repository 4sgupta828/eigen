"""Tests for DeepDive. Every one of these runs free — no model, no network, no database.

The gate tests are the point: each is a case DESIGNED to pass the verbatim span check while being
wrong, which is what the "Evidence Is Typed" directive requires of every gate we add.
"""
from __future__ import annotations

from api.deepdive.assemble import build, named_customers, pricing, stated_milestones
from api.deepdive.gates import metric_defined, subject_bound
from api.deepdive.resolve import as_domain, norm

SUBJ = ["Anthropic", "anthropic"]


# ---------------------------------------------------------------- SubjectBoundaryGate
def test_a_customers_metric_on_our_own_case_study_page_is_refused():
    """The failure the gate exists for: the quote is verbatim, on the company's own domain, and the
    50% belongs to the CUSTOMER. Provenance passes; congruence must not."""
    s = "Since deploying our platform, we saw a 50% increase in annual revenue."
    ok, why = subject_bound(s, SUBJ, url="https://anthropic.com/customers/acme-health")
    assert not ok and "customer page" in why


def test_a_sentence_about_a_named_peer_is_refused():
    ok, why = subject_bound("Acme Health Inc. reported $40 million in annual revenue.", SUBJ)
    assert not ok and "Acme Health" in why


def test_the_subject_named_with_nobody_else_passes():
    ok, _ = subject_bound("Anthropic raised $450 million in a Series C round.", SUBJ)
    assert ok


def test_first_person_on_an_ordinary_page_is_the_company_speaking():
    ok, _ = subject_bound("We now serve more than 300,000 business customers.", SUBJ,
                          url="https://anthropic.com/about")
    assert ok


def test_a_sentence_naming_nobody_is_refused():
    ok, _ = subject_bound("The market for inference is expected to double.", SUBJ)
    assert not ok


# ---------------------------------------------------------------- MetricDefinitionGate
def test_a_bare_percentage_is_not_a_number_we_can_keep():
    ok, why = metric_defined("Growth is up 300% year over year.")
    assert not ok and "no metric named" in why


def test_a_multiple_with_no_base_is_refused():
    assert not metric_defined("Usage grew 4x last quarter.")[0]


def test_a_defined_figure_passes():
    assert metric_defined("The company reached $10 million in annual recurring revenue.")[0]
    assert metric_defined("We now serve 1,200 customers.")[0]


# ---------------------------------------------------------------- resolution
def test_a_url_or_hostname_resolves_to_a_domain_and_a_name_does_not():
    assert as_domain("https://www.anthropic.com/about") == "anthropic.com"
    assert as_domain("anthropic.com") == "anthropic.com"
    assert as_domain("Anthropic") == ""


def test_legal_suffixes_never_distinguish_two_companies():
    assert norm("Acme Labs, Inc.") == norm("acme") == "acme"
    assert norm("Acme Health") != norm("Acme Bio")


# ---------------------------------------------------------------- assembly
def _company(**over) -> dict:
    c = {"id": "acme.com", "name": "Acme", "legal_name": "Acme Inc.", "cik": None, "website": "https://acme.com",
         "one_liner": "agents for support", "description": "", "hq": "San Francisco, CA", "yc_slug": "",
         "yc_batch": "W24", "aliases": [], "sources": ["yc"], "status": "active", "crawl": {"at": "2026-09-01", "pages": 6},
         "facts": [{"key": "founded", "value": "2023", "number": 2023.0, "display": "2023", "provenance": "yc",
                    "basis": "", "source_url": "https://acme.com", "quote": "Founded in 2023", "as_of": None,
                    "confidence": 1.0},
                   {"key": "hiring", "value": "6_20", "number": 8.0, "display": "8 open roles", "provenance": "ats",
                    "basis": "", "source_url": "https://jobs.ashbyhq.com/acme/x", "quote": "Staff Engineer\nAE, Enterprise",
                    "as_of": None, "confidence": 1.0}],
         "financing": [], "founders": [{"name": "Dana Lee", "title": "CEO", "prior_companies": ["stripe"],
                                        "provenance": "site", "source_url": "https://acme.com/team", "quote": "Dana Lee, CEO",
                                        "links": {}, "bio": "Previously at Stripe."}],
         "filings": []}
    c.update(over)
    return c


def test_a_section_with_no_claims_does_not_render():
    d = build(_company(), pages=[])
    titles = [s["title"] for s in d["sections"]]
    assert "Foundations" in titles and "Key people" in titles
    assert "Named customers" not in titles     # no customer page was crawled
    assert "Filed financials" not in titles    # no filing exists


def test_absence_is_recorded_as_a_finding_not_a_silence():
    d = build(_company(), pages=[])
    by = {a["source"]: a for a in d["attempted"]}
    assert by["SEC EDGAR (Form D)"]["result"] == "nothing found"
    assert by["Granted patents"]["found"] == 0
    assert by["Named founders"]["found"] == 1


def test_hiring_intent_replaces_the_org_chart_and_reads_the_titles_we_already_hold():
    d = build(_company(), pages=[])
    hire = next(s for s in d["sections"] if s["title"] == "Hiring intent")["claims"][0]
    assert hire["open_roles"] == 8
    assert "Staff Engineer" in hire["titles"] and "AE, Enterprise" in hire["titles"]


def test_the_milestones_ledger_keeps_our_claim_and_drops_the_customers():
    pages = [{"url": "https://acme.com/about",
              "text": "Acme was founded in 2023. Acme now has $4 million in annual recurring revenue."},
             {"url": "https://acme.com/customers/globex",
              "text": "Since switching to Acme, we cut support costs by 40% and grew revenue 3x."}]
    rows = stated_milestones(pages, ["Acme", "acme"])
    claims = " ".join(r["claim"] for r in rows)
    assert "annual recurring revenue" in claims
    assert "cut support costs" not in claims


def test_pricing_and_customer_pages_are_found_by_path_not_guessed():
    pages = [{"url": "https://acme.com/pricing", "text": "Team $20 per seat per month."},
             {"url": "https://acme.com/customers", "text": "Globex, Initech and Umbrella build on Acme."},
             {"url": "https://acme.com/blog/hello", "text": "hello"}]
    assert len(pricing(pages)) == 1 and len(named_customers(pages)) == 1


def test_every_stated_row_carries_its_register_and_attribution():
    pages = [{"url": "https://acme.com/about", "text": "Acme now has $4 million in annual recurring revenue."}]
    d = build(_company(), pages)
    stated = next(s for s in d["sections"] if s["title"] == "Stated milestones")
    assert stated["claims"] and all(r["register"] == "stated" and r["attribution"] for r in stated["claims"])


def test_a_form_d_offering_is_labelled_as_an_offering_and_never_as_revenue():
    c = _company(cik=1234, filings=[{"accession": "0001-24-000001", "entity_name": "Acme Inc.", "city": "SF",
                                     "state": "CA", "filing_date": "2025-03-01", "sale_date": None,
                                     "sold_usd": 5000000, "offering_usd": 8000000, "revenue_range": "1_1m",
                                     "is_amendment": False, "match_method": "name", "officers": []}])
    d = build(c, pages=[])
    filed = next(s for s in d["sections"] if s["title"] == "Filed financials")
    assert "offering" in filed["claims"][0]["claim"]
    assert "revenue" not in filed["claims"][0]["claim"].lower()
    assert filed["claims"][0]["register"] == "filed"


# ---------------------------------------------------------------- keyless public sources
def _fake_http(monkeypatch, table: dict):
    """Serve canned JSON by URL substring; anything unlisted raises, as a dead source would."""
    import json as _json

    from api.deepdive import public as pub

    async def fetch(url, **_):
        for frag, payload in table.items():
            if frag in url:
                return _json.dumps(payload).encode()
        raise RuntimeError("404")
    monkeypatch.setattr(pub._HTTP, "fetch", fetch)


def test_edgar_names_what_each_filing_IS_so_an_offering_is_never_read_as_an_annual_report(monkeypatch):
    import asyncio

    from api.deepdive.public import edgar_filings
    _fake_http(monkeypatch, {"submissions": {"filings": {"recent": {
        "form": ["10-K", "D", "S-1", "SC 13G/X"], "filingDate": ["2026-02-01", "2024-05-01", "2025-01-01", "2020-01-01"],
        "accessionNumber": ["0001-26-1", "0001-24-2", "0001-25-3", "0001-20-4"],
        "primaryDocument": ["a.htm", "b.htm", "c.htm", "d.htm"]}}}})
    rows, att = asyncio.run(edgar_filings(1018724))
    claims = [r["claim"] for r in rows]
    assert "10-K — annual report (audited)" in claims
    assert "D — exempt offering (Form D)" in claims
    assert not [c for c in claims if c.startswith("SC 13G/X")]      # an unrecognised form is not guessed at
    assert att["found"] == 3 and all(r["register"] == "filed" for r in rows)


def test_a_company_with_no_cik_says_so_rather_than_going_quiet():
    import asyncio

    from api.deepdive.public import edgar_filings
    rows, att = asyncio.run(edgar_filings(None))
    assert rows == [] and "no CIK" in att["result"]


def test_wikidata_is_refused_unless_its_official_site_is_our_domain(monkeypatch):
    """The gate that stops a three-letter company name resolving to a bank or a film."""
    import asyncio

    from api.deepdive.public import wikidata_profile
    _fake_http(monkeypatch, {
        "wbsearchentities": {"search": [{"id": "Q999"}]},
        "wbgetentities": {"entities": {"Q999": {"claims": {
            "P856": [{"mainsnak": {"datavalue": {"value": "https://somebodyelse.com"}}}],
            "P571": [{"mainsnak": {"datavalue": {"value": {"time": "+2021-01-26T00:00:00Z"}}}}]}}}}})
    rows, att = asyncio.run(wikidata_profile("Acme", "acme.com"))
    assert rows == [] and "official site" in att["result"]


def test_wikidata_is_accepted_when_the_identity_is_proven(monkeypatch):
    import asyncio

    from api.deepdive.public import wikidata_profile
    _fake_http(monkeypatch, {
        "wbsearchentities": {"search": [{"id": "Q1"}]},
        "wbgetentities": {"entities": {"Q1": {"claims": {
            "P856": [{"mainsnak": {"datavalue": {"value": "https://www.acme.com/"}}}],
            "P571": [{"mainsnak": {"datavalue": {"value": {"time": "+2021-01-26T00:00:00Z"}}}}],
            "P749": [{"mainsnak": {"datavalue": {"value": {"id": "Q42"}}}}]}}}}})
    rows, att = asyncio.run(wikidata_profile("Acme", "acme.com"))
    claims = [r["claim"] for r in rows]
    assert "founded: 2021-01-26" in claims
    assert not [c for c in claims if "Q42" in c]        # an unlabelled entity id tells a reader nothing
    assert att["found"] == 1 and all(r["register"] == "stated" for r in rows)


def test_a_github_org_that_is_not_this_company_is_refused(monkeypatch):
    import asyncio

    from api.deepdive.public import github_org
    _fake_http(monkeypatch, {"/orgs/": {"login": "acme", "blog": "https://someone-else.io"}})
    rows, att = asyncio.run(github_org("acme.com", "Acme"))
    assert rows == [] and "no public org" in att["result"]


def test_a_source_that_is_down_becomes_an_attempted_row_not_an_exception(monkeypatch):
    import asyncio

    from api.deepdive.public import gather
    _fake_http(monkeypatch, {})       # every call raises
    secs, att = asyncio.run(gather({"id": "acme.com", "name": "Acme", "website": "https://acme.com", "cik": 42}))
    assert secs == []
    assert {a["source"] for a in att} == {"SEC EDGAR (all filings)", "Wikidata", "GitHub"}
    assert all(a["found"] == 0 for a in att)


def test_page_furniture_never_becomes_a_milestone():
    """Found in production on the first live dive: a crawled page's navigation stack passed both
    gates because it happened to contain digits and the word "developers"."""
    junk = ("Features Jul 6, 2026 The Making of Claude Code The inside story of how Claude Code went "
            "from an internal tool to a product used by developers everywhere")
    assert not metric_defined(junk)[0]
    rows = stated_milestones([{"url": "https://acme.com/", "text": junk}], ["Acme", "acme"])
    assert rows == []


def test_a_percentage_beside_a_metric_word_is_still_a_percentage_with_no_base():
    assert not metric_defined("Revenue is up 300% year over year.")[0]
    assert metric_defined("Revenue reached $12 million last year.")[0]


def test_a_date_is_not_a_measurement():
    assert not metric_defined("Founded in 2023 by two engineers.")[0]
    assert not metric_defined("On Jul 6, 2026 the team shipped to developers.")[0]


# ---------------------------------------------------------------- extraction and its gates
def test_a_peer_whose_name_contains_ours_is_not_us():
    """"Acme Health Inc." starts with "Acme". Substring matching called that our company and would
    have filed a peer's revenue under our name — the wrong-company attribution, exactly."""
    ok, why = subject_bound("Acme Health Inc. reported $40 million in annual revenue.", ["Acme", "acme"],
                            own_domain="acme.com")
    assert not ok and "Acme Health" in why


def test_the_sentence_subject_decides_when_both_are_named():
    ok, _ = subject_bound("Acme raised $450 million from Spark Capital.", ["Acme", "acme"], own_domain="acme.com")
    assert ok
    assert not subject_bound("Spark Capital led a $450 million round in Acme.", ["Acme", "acme"],
                             own_domain="acme.com")[0]


def test_a_companys_own_page_is_allowed_to_speak_without_naming_itself():
    """Demanding the company name itself in every sentence refuses nearly all of its own copy. Its
    own domain establishes the subject — but only off the customer and case-study pages."""
    S, D = ["Acme", "acme"], "acme.com"
    assert subject_bound("Pricing starts at $99 per month for the Team plan.", S,
                         url="https://acme.com/pricing", own_domain=D)[0]
    assert not subject_bound("Pricing starts at $99 per month.", S,
                             url="https://someoneelse.com/x", own_domain=D)[0]
    assert not subject_bound("Since switching, we cut support costs by 40%.", S,
                             url="https://acme.com/customers/globex", own_domain=D)[0]


def test_acronyms_and_marketing_capitals_are_not_companies():
    S, D = ["Acme", "acme"], "acme.com"
    assert subject_bound("Enterprise plans include SSO and SOC2 reports.", S,
                         url="https://acme.com/security", own_domain=D)[0]


def test_a_price_is_a_defined_figure():
    assert metric_defined("Pricing starts at $99 per month for the Team plan.")[0]


def test_a_paraphrased_quote_is_an_invented_quote():
    from api.deepdive.extract import keep
    page = "Acme sells a hosted vector database. Pricing starts at $99 per month."
    ok, why = keep({"kind": "what_they_sell", "text": "Acme sells a managed vector DB.",
                    "quote": "Acme sells a managed vector DB."},
                   page_text=page, page_url="https://acme.com/", subject_terms=["Acme"], own_domain="acme.com")
    assert not ok and "verbatim" in why


def test_a_kind_outside_the_vocabulary_is_refused():
    from api.deepdive.extract import keep
    page = "Acme sells a hosted vector database."
    ok, why = keep({"kind": "vibes", "text": "x", "quote": "Acme sells a hosted vector database."},
                   page_text=page, page_url="https://acme.com/", subject_terms=["Acme"], own_domain="acme.com")
    assert not ok and "vocabulary" in why


def test_extraction_reports_what_it_dropped_and_why():
    import asyncio

    from api.deepdive.extract import read_pages

    async def llm(system, user):
        return {"claims": [
            {"kind": "what_they_sell", "text": "Acme sells a hosted vector database.",
             "quote": "Acme sells a hosted vector database."},
            {"kind": "milestone", "text": "made up", "quote": "Acme is the fastest database on earth."},
        ]}
    pages = [{"url": "https://acme.com/", "kind": "home",
              "text": "Acme sells a hosted vector database. " + "Filler sentence about the product. " * 12}]
    out = asyncio.run(read_pages(llm, name="Acme", subject_terms=["Acme"], pages=pages, own_domain="acme.com"))
    assert out["read"] == 1 and out["kept"] == 1
    assert out["dropped"] == {"quote is not verbatim in the page": 1}
    assert [s["title"] for s in out["sections"]] == ["What they sell"]
