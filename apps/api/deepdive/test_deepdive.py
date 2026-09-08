"""Tests for DeepDive. Every one of these runs free — no model, no network, no database.

The gate tests are the point: each is a case DESIGNED to pass the verbatim span check while being
wrong, which is what the "Evidence Is Typed" directive requires of every gate we add.
"""
from __future__ import annotations

import json

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


def test_open_roles_come_from_the_board_rows_we_already_hold():
    """The dossier must never be thinner than the card: the card reads crawl.ats.roles, so this does."""
    c = _company()
    c["crawl"]["ats"] = {"board": ["ashby", "https://jobs.ashbyhq.com/acme"],
                         "roles": [{"title": "Staff Engineer", "location": "SF", "department": "Eng", "url": "u1"},
                                   {"title": "AE, Enterprise", "location": "NY", "department": "Sales", "url": "u2"},
                                   {"title": "Backend Engineer", "location": "SF", "department": "Eng", "url": "u3"}]}
    d = build(c, pages=[])
    hire = next(s for s in d["sections"] if s["title"] == "Open roles")["claims"][0]
    assert hire["open_roles"] == 8 and hire["roles_total"] == 3
    assert hire["board_url"] == "https://jobs.ashbyhq.com/acme"
    assert hire["roles"][0]["location"] == "SF"          # the card shows location and department
    # a sample shows the SHAPE of the hiring: one per function before a second from any
    assert [r["title"] for r in hire["roles"]][:2] == ["Staff Engineer", "AE, Enterprise"]


def test_a_single_posting_climbs_to_the_whole_board():
    """"30 open roles" linking to one job was a real complaint on the card."""
    from api.deepdive.assemble import board_root
    assert board_root("https://jobs.ashbyhq.com/acme/a1e5-cdbc") == "https://jobs.ashbyhq.com/acme"
    assert board_root("https://boards.greenhouse.io/acme/jobs/4093") == "https://boards.greenhouse.io/acme"
    assert board_root("") == ""


def test_investors_are_named_and_linked_and_say_which_round():
    """A slug is not a name and a Google search is not a link — the card learned this the hard way."""
    from api.deepdive.assemble import investors
    byk = {"lead_investor": [{"key": "lead_investor", "value": "a16z", "source_url": "u", "quote": "q"}],
           "investor": [{"key": "investor", "value": "general_catalyst", "source_url": "u", "quote": "q"},
                        {"key": "investor", "value": "unknown_fund", "source_url": "u", "quote": "q"}]}
    fin = [{"kind": "formd", "round_name": "Series A", "event_date": "2025-03-01",
            "amount_usd": 8000000, "investors": ["general_catalyst"], "lead": "a16z"}]
    rows = investors(byk, fin, {"a16z": {"name": "Andreessen Horowitz", "site": "https://a16z.com"},
                                "general_catalyst": {"name": "General Catalyst", "site": "https://gc.com"}})
    assert rows[0]["lead"] and rows[0]["name"] == "Andreessen Horowitz"      # the lead comes first
    assert rows[0]["rounds"][0]["round"] == "Series A"
    gc = next(r for r in rows if r["slug"] == "general_catalyst")
    assert gc["site"] == "https://gc.com" and gc["rounds"][0]["amount_usd"] == 8000000
    # a firm we cannot resolve is still NAMED, just not linked
    unk = next(r for r in rows if r["slug"] == "unknown_fund")
    assert unk["name"] and unk["site"] == ""


def test_the_dossier_is_a_superset_of_the_card():
    c = _company()
    c["crawl"]["ats"] = {"board": ["ashby", "https://jobs.ashbyhq.com/acme"],
                         "roles": [{"title": "Staff Engineer", "location": "SF", "department": "Eng", "url": "u"}]}
    c["facts"] += [{"key": "investor", "value": "a16z", "number": None, "display": "", "provenance": "site",
                    "basis": "", "source_url": "u", "quote": "q", "as_of": None, "confidence": 1.0},
                   {"key": "total_disclosed_funding", "value": "5m_20m", "number": 8000000.0,
                    "display": "$8M", "provenance": "derived", "basis": "", "source_url": "u",
                    "quote": "q", "as_of": None, "confidence": 1.0}]
    c["financing"] = [{"kind": "formd", "round_name": "Series A", "amount_usd": 8000000,
                       "offering_usd": 8000000, "event_date": "2025-03-01", "investors": ["a16z"],
                       "lead": "a16z", "source_url": "u", "quote": "q"}]
    titles = [s["title"] for s in build(c, pages=[], sites={})["sections"]]
    for expected in ("Key people", "Investors", "Funding", "Funding rounds", "Open roles"):
        assert expected in titles, expected


def test_prose_claims_are_read_by_a_model_never_scraped_by_a_regex():
    """Found on a real dive: cutting sentences out of raw pages produced "Blazel can adjust
    usage-based pricing upon 60 days prior written notice. (b) Taxes." from a terms page and "I'm
    doing 10 demos a week" — someone else's words in the first person on the company's own site.
    Both passed every gate, because the gates check congruence, not whether a sentence is a claim.
    A sentence becomes a claim only when a model says what it establishes and the quote is checked
    back against the page."""
    pages = [{"url": "https://acme.com/terms",
              "text": "Acme can adjust usage-based pricing upon 60 days prior written notice. (b) Taxes."},
             {"url": "https://acme.com/about", "text": "I'm doing 10 demos a week and onboarding 5 customers."}]
    assert stated_milestones(pages, ["Acme", "acme"]) == []


def test_pricing_and_customer_pages_are_found_by_path_not_guessed():
    pages = [{"url": "https://acme.com/pricing", "text": "Team $20 per seat per month."},
             {"url": "https://acme.com/customers", "text": "Globex, Initech and Umbrella build on Acme."},
             {"url": "https://acme.com/blog/hello", "text": "hello"}]
    assert len(pricing(pages)) == 1 and len(named_customers(pages)) == 1


def test_every_stated_row_carries_its_register_and_attribution():
    """The self-reported ARR facet still stands: it was extracted WITH provenance in the first
    place, which is exactly the difference from a sentence cut out of a page."""
    c = _company()
    c["facts"].append({"key": "arr", "value": "1m_10m", "number": 4000000.0, "display": "$4M ARR",
                       "provenance": "site", "basis": "self_reported", "source_url": "https://acme.com/about",
                       "quote": "Acme now has $4 million in annual recurring revenue", "as_of": None,
                       "confidence": 1.0})
    d = build(c, pages=[])
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


# ---------------------------------------------------------------- the web leg
class _Hit:
    def __init__(self, text, facet, url, title="TechCrunch"):
        self.text, self.facets, self.extra = text, {"deep_facet": facet, "url": url}, {}
        self.locator, self.document_id, self.document_title = None, url, title


def test_the_web_leg_keeps_claims_and_drops_everything_that_only_looks_like_one():
    """Measured against the first live full dive on Fluidstack, which returned all five of these."""
    from api.deepdive.web import _claims_from
    hits = [
        _Hit("For most of human history, you farmed or you starved.", "product", "https://fluidstack.io/"),
        _Hit("“Fluidstack’s dedicated support is excellent.", "customers", "https://fluidstack.io/customers"),
        _Hit("The cloud-computing startup Fluidstack Ltd.", "funding_investors_valuation", "https://bloomberg.com/x", "Bloomberg"),
        _Hit("For more information about Fluidstack, please visit fluidstack.io.", "funding_investors_valuation", "https://m.com/y", "Mishcon"),
        _Hit("We’ve seen the company go from strength to strength.", "funding_investors_valuation", "https://m.com/y", "Mishcon"),
        _Hit("Fluidstack builds infrastructure for the leading AI labs and deploys clusters at speed.", "product", "https://fluidstack.io/"),
        _Hit("Fluidstack raised $830 million in a Series A round announced this week.", "funding_investors_valuation", "https://bloomberg.com/x", "Bloomberg"),
    ]
    by = _claims_from(hits, ["Fluidstack", "fluidstack"], "fluidstack.io")
    kept = [c["claim"] for rows in by.values() for c in rows]
    assert len(kept) == 2
    assert any(k.startswith("Fluidstack builds infrastructure") for k in kept)     # a real claim
    assert any("raised $830 million" in k for k in kept)                           # a real number
    assert not any("human history" in k for k in kept)                             # landing-page manifesto
    assert not any("dedicated support" in k for k in kept)                         # the customer's voice
    assert not any("cloud-computing startup" in k for k in kept)                   # a fragment
    assert not any("please visit" in k for k in kept)                              # boilerplate
    assert not any("strength to strength" in k for k in kept)                      # a quoted third party


def test_independent_coverage_is_a_signal_and_the_companys_own_page_is_not():
    from api.deepdive.web import _claims_from
    by = _claims_from([
        _Hit("Fluidstack raised $830 million in a Series A round announced this week.",
             "funding_investors_valuation", "https://bloomberg.com/x", "Bloomberg"),
        _Hit("Fluidstack builds infrastructure for the leading AI labs and deploys clusters at speed.",
             "product", "https://fluidstack.io/"),
    ], ["Fluidstack"], "fluidstack.io")
    assert by["funding_investors_valuation"][0]["register"] == "signal"
    assert by["product"][0]["register"] == "stated"


def test_the_dive_is_projected_before_it_is_run():
    from api.deepdive.routes import project
    assert project("held", 12, None)["projected_usd"] == 0.0
    read = project("read", 12, None)
    assert read["pages"] == 12 and read["projected_usd"] > 0
    full = project("full", 12, {"max_queries": 8})
    assert full["projected_usd"] > read["projected_usd"] and full["web_usd"] > 0
    # the page count is capped, so a company with a huge site cannot blow past the projection
    assert project("read", 500, None)["pages"] == 14


def test_a_manifesto_on_the_web_is_not_a_claim_even_in_the_first_person():
    """Survived the first tightening: `subject_bound` lets first person stand on a company's own
    pages, which is right for a page we crawled and wrong for one we found on the web."""
    from api.deepdive.web import _claims_from
    by = _claims_from([
        _Hit("We believe whoever deploys frontier infrastructure fastest will shape whether AI expands human freedom.",
             "founders_team", "https://fluidstack.io/"),
        _Hit("We hire people who care deeply about this problem space.", "founders_team", "https://fluidstack.io/"),
        _Hit("Fluidstack builds infrastructure for the leading AI labs and deploys clusters at speed.",
             "product", "https://fluidstack.io/"),
    ], ["Fluidstack", "fluidstack"], "fluidstack.io")
    kept = [c["claim"] for rows in by.values() for c in rows]
    assert kept == ["Fluidstack builds infrastructure for the leading AI labs and deploys clusters at speed."]


def test_every_attempted_row_can_be_rendered():
    """The Manifest of Absence reads `result` when nothing was found; a row without one printed
    "undefined" on the page."""
    from api.deepdive.web import _att
    for row in (_att("Web read", 0, "pages"), _att("Web read", 3, "pages")):
        assert row["result"] and row["source"] and row["unit"]


def test_a_short_factual_sentence_is_prose_and_a_nav_bar_is_not():
    """A flat floor of five lowercase words threw away real claims; the ratio does not."""
    from api.deepdive.assemble import reads_like_a_sentence as prose
    assert prose("Fluidstack builds gigawatt-scale data centers.")
    assert prose("Fluidstack Ltd. raised $830 million in a Series A round.")
    assert not prose("Home About Pricing Careers Blog Contact Us Sign In.")
    assert not prose("Product Platform Solutions Docs API Reference Support.")


def test_coverage_may_say_the_company_after_naming_it_once():
    """295 of 329 web sentences were dropped for "does not name the company" — which is simply how
    articles are written. Within one retrieved chunk the reference is unambiguous."""
    from api.deepdive.web import _claims_from
    news = ("Fluidstack Ltd. raised $830 million in a Series A round. The company operates data "
            "centers for AI labs. It plans to add 500 megawatts of capacity next year. "
            "Rivals such as Globex Corp. have grown faster.")
    by = _claims_from([_Hit(news, "funding_investors_valuation", "https://bloomberg.com/x", "Bloomberg")],
                      ["Fluidstack", "fluidstack"], "fluidstack.io")
    kept = [c["claim"] for c in by["funding_investors_valuation"]]
    assert any("raised $830 million" in k for k in kept)          # named outright
    assert any(k.startswith("The company operates") for k in kept)  # anaphora, subject established
    assert not any("Globex" in k for k in kept)                   # a peer never inherits the reference


def test_coreference_does_not_survive_another_company_in_the_sentence():
    from api.deepdive.web import _claims_from
    news = "Fluidstack raised $830 million. It now resells capacity through Globex Corp."
    by = _claims_from([_Hit(news, "competitors_traction", "https://x.com/y", "Reuters")],
                      ["Fluidstack"], "fluidstack.io")
    kept = [c["claim"] for rows in by.values() for c in rows]
    assert not any("Globex" in k for k in kept)


def test_the_web_leg_never_re_imports_the_companys_own_marketing():
    from api.deepdive.web import _claims_from
    by = _claims_from([_Hit("We hire people who care deeply about this problem space. "
                            "Fluidstack builds gigawatt-scale data centers.",
                            "product", "https://fluidstack.io/")], ["Fluidstack"], "fluidstack.io")
    kept = [c["claim"] for rows in by.values() for c in rows]
    assert kept == ["Fluidstack builds gigawatt-scale data centers."]


def test_a_company_suffix_does_not_end_a_sentence():
    """"Fluidstack Ltd. raised $830 million…" split into two fragments, both too short to keep, so
    the claim silently never existed — the worst kind of bug: a quiet omission."""
    from api.deepdive.assemble import sentences
    assert sentences("Fluidstack Ltd. raised $830 million in a Series A round. It grew fast.") == [
        "Fluidstack Ltd. raised $830 million in a Series A round.", "It grew fast."]
    assert len(sentences("Acme Inc. and Globex Corp. signed a deal. Both grew.")) == 2


def test_markup_never_reaches_a_claim():
    """"a target valuation of <strong>$18 billion</strong>" rendered with the tags on the page."""
    from api.deepdive.web import _claims_from
    by = _claims_from([_Hit("Fluidstack is raising at a valuation of <strong>$18 billion</strong>, "
                            "people briefed on the matter said.", "funding_investors_valuation",
                            "https://bloomberg.com/x", "Bloomberg")], ["Fluidstack"], "fluidstack.io")
    kept = [c["claim"] for rows in by.values() for c in rows]
    assert kept and "<" not in kept[0] and "$18 billion" in kept[0]


def test_facts_carry_the_label_a_reader_sees_not_the_column_name():
    d = build(_company(), pages=[])
    found = next(s for s in d["sections"] if s["title"] == "Foundations")
    assert all(c["key_label"] for c in found["claims"])
    from api.deepdive.assemble import KEY_LABELS
    assert KEY_LABELS["financing_scale"] == "Latest filing sold"
    assert KEY_LABELS["last_round_months"] == "Last round age"


def test_stripped_markup_leaves_no_gap_before_punctuation():
    from api.deepdive.assemble import sentences
    assert sentences("A valuation of $18 billion , according to people.") == [
        "A valuation of $18 billion, according to people."]


# ---------------------------------------------------------------- discovery
def test_a_name_we_do_not_hold_is_an_offer_not_a_dead_end(monkeypatch):
    """Reported from production: typing a company we have not indexed ended the dive with
    "no company we hold matches that name" — true, and useless."""
    import asyncio

    from api.deepdive import discover

    async def fake_resolve(**kw):
        return "blazel.com"
    monkeypatch.setattr("eigen_kernel.research.deep_company.resolve_own_domain", fake_resolve)

    class M:
        company_reader = {"domain_query_template": "{company} official website"}
    got = asyncio.run(discover.find("Blazel", manifest=M()))
    assert got["status"] == "found" and got["domain"] == "blazel.com"


def test_a_domain_that_is_not_the_company_asked_for_is_offered_not_assumed(monkeypatch):
    import asyncio

    from api.deepdive import discover

    async def fake_resolve(**kw):
        return "globex.com"
    monkeypatch.setattr("eigen_kernel.research.deep_company.resolve_own_domain", fake_resolve)

    class M:
        company_reader = {"domain_query_template": "{company} official website"}
    got = asyncio.run(discover.find("Blazel", manifest=M()))
    assert got["status"] == "unsure" and got["domain"] == "globex.com"


def test_a_short_name_is_confirmed_rather_than_assumed(monkeypatch):
    """"GFC" resolves to whichever GFC the web ranks highest; the investor work showed what that costs."""
    import asyncio

    from api.deepdive import discover

    async def fake_resolve(**kw):
        return "gfc.nl"
    monkeypatch.setattr("eigen_kernel.research.deep_company.resolve_own_domain", fake_resolve)

    class M:
        company_reader = {"domain_query_template": "{company} official website"}
    got = asyncio.run(discover.find("GFC", manifest=M()))
    assert got["status"] == "unsure"


def test_a_web_search_that_finds_nothing_says_so(monkeypatch):
    import asyncio

    from api.deepdive import discover

    async def fake_resolve(**kw):
        return ""
    monkeypatch.setattr("eigen_kernel.research.deep_company.resolve_own_domain", fake_resolve)

    class M:
        company_reader = {"domain_query_template": "{company} official website"}
    got = asyncio.run(discover.find("Zzqq Nonexistent", manifest=M()))
    assert got["status"] == "unknown" and not got["domain"]


def test_name_matching_is_stricter_than_the_read_time_matcher():
    from api.deepdive.discover import name_matches_domain as m
    assert m("ElevenLabs", "elevenlabs.io") and m("Eleven Labs", "elevenlabs.io")
    assert m("Fluidstack", "fluidstack.io")
    assert not m("Acme", "globex.com")


# ---------------------------------------------------------------- the deeper questions
def test_the_dossier_answers_how_it_works_how_it_earns_and_who_it_is_up_against():
    from api.deepdive.extract import _ORDER, KINDS, sections_from
    for k in ("core_technology", "how_they_make_money", "competitor"):
        assert k in KINDS and k in _ORDER
    kept = [{"kind": "core_technology", "text": "Runs a distributed vector index on FPGAs.",
             "quote": "q1", "source_url": "https://acme.com/tech"},
            {"kind": "how_they_make_money", "text": "Charged per million queries.", "quote": "q2",
             "source_url": "https://acme.com/pricing"},
            {"kind": "competitor", "text": "Compares itself to Globex.", "quote": "q3",
             "source_url": "https://acme.com/compare"}]
    titles = [s["title"] for s in sections_from(kept)]
    assert titles == ["How it works", "How they make money", "Who they compare themselves to"]


def test_a_competitor_claim_must_be_the_companys_own_comparison():
    """It names another company on purpose — the one thing the subject gate refuses — so it is
    admissible only from our own site, naming us."""
    from api.deepdive.extract import keep
    page = "Acme is faster than Globex for hybrid search."
    ok, _ = keep({"kind": "competitor", "text": "x", "quote": page},
                 page_text=page, page_url="https://acme.com/compare", subject_terms=["Acme"],
                 own_domain="acme.com")
    assert ok
    ok, why = keep({"kind": "competitor", "text": "x", "quote": page},
                   page_text=page, page_url="https://someoneelse.com/x", subject_terms=["Acme"],
                   own_domain="acme.com")
    assert not ok and "own site" in why
    ok, why = keep({"kind": "competitor", "text": "x", "quote": "Globex leads hybrid search."},
                   page_text="Globex leads hybrid search.", page_url="https://acme.com/compare",
                   subject_terms=["Acme"], own_domain="acme.com")
    assert not ok and "must name the company" in why


def test_one_heading_one_card():
    """The index knows the business model, the site states it and the press describes it — three
    cards with the same title makes the reader do the joining."""
    from api.deepdive.assemble import merge_sections
    out = merge_sections([
        {"title": "How they make money", "kind": "fact", "claims": [{"display": "usage"}], "note": "n1"},
        {"title": "Named customers", "kind": "pages", "claims": []},
        {"title": "How they make money", "kind": "stated",
         "claims": [{"claim": "Charged per million queries."}, {"display": "usage"}]},
    ])
    assert [s["title"] for s in out] == ["How they make money"]
    assert len(out[0]["claims"]) == 2          # the duplicate value is not repeated
    assert out[0]["note"] == "n1"


def test_a_merged_section_renders_each_row_in_its_own_shape():
    from api.deepdive.assemble import merge_sections
    out = merge_sections([
        {"title": "Named customers", "kind": "pages", "claims": [{"source_url": "u", "excerpt": "x"}]},
        {"title": "Named customers", "kind": "stated", "claims": [{"claim": "Globex uses it."}]},
    ])
    rows = out[0]["claims"]
    assert [r["row"] for r in rows] == ["pages", "stated"]


def test_the_web_leg_does_not_re_read_pages_we_read_properly_ourselves():
    """The internal facets returned the company's own copy UNextracted — the same pages the
    site-reading leg reads with a model against verbatim quotes. Less noise, and fewer paid queries."""
    from api.deepdive.web import external_only, project_web_cost
    t = {"internal": {"a": "x", "b": "y", "c": "z"}, "external": {"funding": "f", "competitors": "c"},
         "max_queries": 8}
    assert external_only(t)["internal"] == {}
    assert external_only(t)["max_queries"] == 2
    assert project_web_cost(t)["queries"] == 2


def test_a_crawled_page_is_offered_as_a_link_not_as_its_navigation():
    """"Secureframe packages Skip to main content CMMC Pause…" was rendered as a claim: the first
    600 characters of a crawled page are its nav bar."""
    pages = [{"url": "https://acme.com/pricing", "text": "Skip to main content Home Product Pricing"},
             {"url": "https://acme.com/customers", "text": "Skip to main content Trusted by"}]
    for row in pricing(pages) + named_customers(pages):
        assert "Skip to main content" not in json.dumps(row)
        assert row["source_url"] and row["claim"]


def test_search_snippets_arrive_escaped_and_truncated():
    from api.deepdive.assemble import sentences
    assert sentences("Secureframe&#x27;s latest funding round is Angel....") == [
        "Secureframe's latest funding round is Angel."]
    assert sentences("Secureframe raised a total of $78.71M…") == [
        "Secureframe raised a total of $78.71M."]


# ---------------------------------------------------------------- one fact, one person
def test_two_sources_agreeing_is_one_fact_not_two_rows():
    """Found on a live dive: YC and the company's own site both state the country, and the dossier
    printed "US · US" — which reads as a bug, not as corroboration."""
    from api.deepdive.assemble import dedupe_facts
    rows = dedupe_facts([
        {"key": "country", "value": "us", "number": None, "provenance": "site", "quote": "", "source_url": "u"},
        {"key": "country", "value": "us", "number": None, "provenance": "yc",
         "quote": "Location: Bridgeton, MO, USA", "source_url": "u"},
    ])
    assert len(rows) == 1
    assert rows[0]["sources"] == ["site", "yc"]          # the agreement is kept, the repetition is not
    assert rows[0]["quote"]                              # and the row with evidence is the one shown


def test_the_same_founder_under_two_names_is_one_person():
    """"Marty" from one page and "Marty Kausas" from another is not two co-founders."""
    from api.deepdive.assemble import merge_founders
    out = merge_founders([
        {"name": "Marty", "title": "Co-founder", "bio": "", "links": {}, "prior_companies": []},
        {"name": "Marty Kausas", "title": "Founder", "bio": "CEO of Pylon, started coding early.",
         "links": {"linkedin": "x"}, "prior_companies": []},
    ])
    assert [r["name"] for r in out] == ["Marty Kausas"]
    assert out[0]["links"] == {"linkedin": "x"} and out[0]["bio"]


def test_an_ambiguous_first_name_is_never_merged():
    """Two Roberts stay two Roberts — guessing there merges two people."""
    from api.deepdive.assemble import merge_founders
    out = merge_founders([
        {"name": "Robert", "title": "Co-founder", "bio": "", "links": {}, "prior_companies": []},
        {"name": "Robert Eng", "title": "Founder", "bio": "", "links": {}, "prior_companies": []},
        {"name": "Robert Chen", "title": "Founder", "bio": "", "links": {}, "prior_companies": []},
    ])
    assert sorted(r["name"] for r in out) == ["Robert", "Robert Chen", "Robert Eng"]


def test_a_domain_is_not_a_biography():
    c = _company()
    c["founders"] = [{"name": "Advith Chelikani", "title": "Founder", "prior_companies": [],
                      "provenance": "site", "source_url": "u", "quote": "", "links": {},
                      "bio": "usepylon.com"}]
    person = build(c, pages=[])["sections"][1]["claims"][0]
    assert person["name"] == "Advith Chelikani" and person["bio"] == ""
