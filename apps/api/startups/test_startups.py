"""Offline tests for Startup Search — schema, the extractor's gates, derived facets, the compiler's honesty
rules, Form D parsing (a synthetic quarter), ATS discovery, Form D resolution, and the kernel evaluator over an
in-memory store shaped like ours. The eval traps of docs/specs/startup-search.md §8 that are testable without a
database live here (each designed to pass a gate while wrong)."""
from __future__ import annotations

import asyncio
import csv
import io
import zipfile
from datetime import date

from eigen_kernel.facets import Contract, InMemoryFacetStore, evaluate

from api.startups import compile as cp, derive, extract, resolve
from api.startups.schema import KIND, SCHEMA, WEIGHTS, labels
from api.startups.sources import ats, formd, http


# ---------------------------------------------------------------- schema
def test_schema_is_well_formed():
    assert len(SCHEMA.keys) >= 20
    assert SCHEMA.validate_value("stage", "Series A") == "series_a"
    assert SCHEMA.validate_value("tech_area", "crypto") is None
    assert SCHEMA.band_of("total_disclosed_funding", 12e6) == "5m_20m"
    assert SCHEMA.band_of("founder_count", 2) == "2" and SCHEMA.band_of("founder_count", 7) == "4_plus"
    lab = labels()
    assert "stage" in lab["order"] and lab["values"]["series_a"] == "series A"


# ---------------------------------------------------------------- extractor gates
PAGES = [{"kind": "home", "url": "https://acme.ai/", "text": "Acme builds inference infrastructure for banks. We raised $12M in our Series A led by a16z. Trusted by Google and Stripe."},
         {"kind": "team", "url": "https://acme.ai/team", "text": "Jane Doe, co-founder and CEO, previously at Stripe. Bob Ray, founding engineer. We plan to raise a Series B next year. Our ARR is $5M."}]


def _validate(out):
    return extract.validate(out, PAGES, [{"title": "Account Executive"}], as_of=date(2026, 9, 5))


def test_extract_quote_must_be_in_pages():
    res = _validate({"facets": [{"key": "tech_area", "value": "ai_infra", "quote": "Acme builds inference infrastructure for banks"},
                                {"key": "tech_area", "value": "fintech", "quote": "this sentence is not on the site at all"}]})
    assert [f["value"] for f in res["facts"]] == ["ai_infra"]


def test_extract_invented_figure_is_dropped():
    res = _validate({"financing": [{"round_name": "Series A", "amount": "$12M", "currency": "USD", "quote": "We raised $12M in our Series A led by a16z", "lead": "a16z"},
                                   {"round_name": "Seed", "amount": "$3M", "currency": "USD", "quote": "Acme builds inference infrastructure for banks"}]})
    assert len(res["financing"]) == 1 and res["financing"][0]["amount_usd"] == 12e6 and res["financing"][0]["round_name"] == "series_a"


def test_extract_intent_never_becomes_a_fact():
    res = _validate({"facets": [{"key": "stage", "value": "series_b", "quote": "We plan to raise a Series B next year", "modality": "intent"}],
                     "financing": [{"round_name": "Series B", "amount": "", "quote": "We plan to raise a Series B next year", "modality": "intent"}]})
    assert res["facts"] == [] and res["financing"] == []


def test_extract_founder_not_founding_engineer_and_prior_company():
    res = _validate({"founders": [{"name": "Jane Doe", "title": "co-founder and CEO", "prior_companies": ["Stripe"], "quote": "Jane Doe, co-founder and CEO, previously at Stripe"},
                                  {"name": "Bob Ray", "title": "founding engineer", "prior_companies": [], "quote": "Bob Ray, founding engineer"},
                                  {"name": "Ghost Person", "title": "founder", "prior_companies": [], "quote": "Acme builds inference infrastructure for banks"}]})
    names = [f["name"] for f in res["founders"]]
    assert "Jane Doe" in names and "Ghost Person" not in names       # a name must appear in the pages
    assert res["founders"][0]["prior_companies"] == ["stripe"]


def test_extract_arr_only_from_arr_metric_and_self_reported():
    res = _validate({"metrics": [{"kind": "arr", "amount": "$5M", "currency": "USD", "period": "", "quote": "Our ARR is $5M"},
                                 {"kind": "run_rate", "amount": "$12M", "currency": "USD", "period": "", "quote": "We raised $12M in our Series A led by a16z"}]})
    arr = [f for f in res["facts"] if f["key"] == "arr"]
    assert len(arr) == 1 and arr[0]["number"] == 5e6 and arr[0]["basis"] == "self_reported"


def test_extract_logo_wall_is_not_an_investor():
    res = _validate({"facets": [{"key": "investor", "value": ["google", "stripe"], "quote": "Trusted by Google and Stripe"}],
                     "customers": [{"name": "Google", "quote": "Trusted by Google and Stripe"}]})
    # the quote is real, so code cannot tell — the prompt forbids it; what code CAN guarantee is the customers list is kept separately
    assert res["customers"][0]["name"] == "Google"


def test_extract_role_functions_only_for_known_titles():
    res = _validate({"role_functions": {"Account Executive": "sales", "Made Up Role": "engineering", "account executive": "nonsense"}})
    assert res["role_functions"] == {"account executive": "sales"}


# ---------------------------------------------------------------- derived facets (stage / money rules)
def test_derive_stage_is_stated_round_only_and_filing_feeds_scale():
    fil = [{"file_num": "021-1", "accession": "A1", "sold_usd": 40e6, "sale_date": "2025-02-20", "filing_date": "2025-03-05", "revenue_range": "Decline to Disclose"}]
    facts = derive.derive_facts({}, [], fil, [], [], {}, today=date(2026, 9, 5))
    keys = {f["key"]: f for f in facts}
    assert "stage" not in keys                                        # trap 12: $40M sold is not a stage
    assert keys["financing_scale"]["number"] == 40e6 and keys["financing_scale"]["basis"] == "inferred_from_filing"
    assert "revenue_range" not in keys                                # trap 9: decline to disclose is unknown
    assert keys["evidence_strength"]["value"] == "filing_backed"


def test_derive_amendment_supersedes_and_press_within_window_not_double_counted():
    fil = [{"file_num": "021-1", "accession": "A1", "sold_usd": 9.6e6, "sale_date": "2025-02-20", "filing_date": "2025-03-05"},
           {"file_num": "021-1", "accession": "A1a", "sold_usd": 11e6, "sale_date": "2025-02-20", "filing_date": "2025-06-05", "is_amendment": True}]
    fin = [{"kind": "press", "round_name": "series_a", "amount_usd": 12e6, "event_date": "2025-03-01", "quote": "raised $12M Series A", "investors": ["a16z"], "lead": "a16z"}]
    facts = derive.derive_facts({}, fin, fil, [], [], {}, today=date(2026, 9, 5))
    keys = {f["key"]: f for f in facts}
    assert keys["total_disclosed_funding"]["number"] == 11e6         # traps 5 + 6: one event, filing figure wins
    assert keys["stage"]["value"] == "series_a" and keys["stage"]["basis"] == "stated_round"
    assert keys["lead_investor"]["value"] == "a16z"


def test_derive_officers_never_founders_and_hiring_from_roles():
    roles = [{"title": "Account Executive", "url": "u"}, {"title": "Backend Engineer", "url": "u2"}]
    facts = derive.derive_facts({}, [], [], [], roles, {"account executive": "sales"}, today=date(2026, 9, 5))
    keys = {f["key"]: f for f in facts}
    assert "founder_count" not in keys and keys["hiring"]["number"] == 2
    assert [f["value"] for f in facts if f["key"] == "hiring_function"] == ["sales"]


# ---------------------------------------------------------------- compiler honesty
def test_compile_downgrades_arr_and_low_coverage_and_keeps_must_not():
    c, notes = cp.build_contract({"text": "AI infra for banks", "must": {"tech_area": ["ai_infra"], "arr": {"min": 1e6}, "founder_prior_company": ["stripe"]},
                                  "must_not": {"program": ["yc"]}, "center": {"key": "stage", "value": "seed", "span": 1}},
                                 coverage={"tech_area": 0.9, "founder_prior_company": 0.2, "arr": 0.05})
    assert c.must == {"tech_area": ["ai_infra"]}
    assert c.prefer == {"founder_prior_company": ["stripe"]}
    assert c.scope == {"exclude": {"program": ["yc"]}}
    assert c.center == {"key": "stage", "value": "seed", "span": 1}
    assert len(notes) == 2


def test_compile_rejects_off_vocabulary_and_bad_rank():
    c, notes = cp.build_contract({"text": "x", "must": {"tech_area": ["crypto"], "nonsense": ["y"]}, "rank_by": "investor"}, coverage={})
    assert c.must == {} and c.rank_by == "match"


# ---------------------------------------------------------------- Form D bulk parsing (synthetic quarter)
def _quarter_zip() -> bytes:
    def tsv(rows):
        buf = io.StringIO(); w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), delimiter="\t"); w.writeheader(); w.writerows(rows); return buf.getvalue()
    sub = [{"ACCESSIONNUMBER": "A1", "FILE_NUM": "021-1", "FILING_DATE": "05-MAR-2025"}, {"ACCESSIONNUMBER": "A2", "FILE_NUM": "021-2", "FILING_DATE": "06-MAR-2025"},
           {"ACCESSIONNUMBER": "A3", "FILE_NUM": "021-3", "FILING_DATE": "07-MAR-2025"}]
    iss_cols = {"IS_PRIMARYISSUER_FLAG": "YES", "STREET1": "", "STREET2": "", "STATEORCOUNTRYDESCRIPTION": "", "ZIPCODE": "", "ISSUERPHONENUMBER": "", "JURISDICTIONOFINC": "DE",
                "ISSUER_PREVIOUSNAME_1": "", "ISSUER_PREVIOUSNAME_2": "", "ISSUER_PREVIOUSNAME_3": "", "EDGAR_PREVIOUSNAME_1": "", "EDGAR_PREVIOUSNAME_2": "", "EDGAR_PREVIOUSNAME_3": "",
                "ENTITYTYPEOTHERDESC": "", "YEAROFINC_TIMESPAN_CHOICE": "", "ISSUER_SEQ_KEY": "101"}
    iss = [{"ACCESSIONNUMBER": "A1", "CIK": "0001", "ENTITYNAME": "Acme AI, Inc.", "CITY": "AUSTIN", "STATEORCOUNTRY": "TX", "ENTITYTYPE": "Corporation", "YEAROFINC_VALUE_ENTERED": "2022", **iss_cols},
           {"ACCESSIONNUMBER": "A2", "CIK": "0002", "ENTITYNAME": "Acme Opportunity Fund II, LP", "CITY": "NEW YORK", "STATEORCOUNTRY": "NY", "ENTITYTYPE": "Limited Partnership", "YEAROFINC_VALUE_ENTERED": "", **iss_cols},
           {"ACCESSIONNUMBER": "A3", "CIK": "0003", "ENTITYNAME": "Acme SPV 2024 LLC", "CITY": "AUSTIN", "STATEORCOUNTRY": "TX", "ENTITYTYPE": "Limited Liability Company", "YEAROFINC_VALUE_ENTERED": "2024", **iss_cols}]
    off_cols = {"INVESTMENTFUNDTYPE": "", "IS40ACT": "false", "AGGREGATENETASSETVALUERANGE": "", "FEDERALEXEMPTIONS_ITEMS_LIST": "06b", "PREVIOUSACCESSIONNUMBER": "", "YETTOOCCUR": "false",
                "MORETHANONEYEAR": "false", "ISDEBTTYPE": "false", "ISOPTIONTOACQUIRETYPE": "false", "ISSECURITYTOBEACQUIREDTYPE": "false", "ISTENANTINCOMMONTYPE": "false", "ISMINERALPROPERTYTYPE": "false",
                "ISOTHERTYPE": "false", "DESCRIPTIONOFOTHERTYPE": "", "ISBUSINESSCOMBINATIONTRANS": "false", "MINIMUMINVESTMENTACCEPTED": "0", "TOTALREMAINING": "0", "HASNONACCREDITEDINVESTORS": "false", "NUMBERNONACCREDITEDINVESTORS": "0"}
    off = [{"ACCESSIONNUMBER": "A1", "INDUSTRYGROUPTYPE": "Other Technology", "REVENUERANGE": "$1 - $1,000,000", "ISAMENDMENT": "false", "SALE_DATE": "20-FEB-2025", "ISEQUITYTYPE": "true",
            "ISPOOLEDINVESTMENTFUNDTYPE": "false", "TOTALOFFERINGAMOUNT": "12000000", "TOTALAMOUNTSOLD": "9600000", "TOTALNUMBERALREADYINVESTED": "7", **off_cols},
           {"ACCESSIONNUMBER": "A2", "INDUSTRYGROUPTYPE": "Pooled Investment Fund", "REVENUERANGE": "Decline to Disclose", "ISAMENDMENT": "false", "SALE_DATE": "", "ISEQUITYTYPE": "true",
            "ISPOOLEDINVESTMENTFUNDTYPE": "true", "TOTALOFFERINGAMOUNT": "Indefinite", "TOTALAMOUNTSOLD": "50000000", "TOTALNUMBERALREADYINVESTED": "30", **off_cols},
           {"ACCESSIONNUMBER": "A3", "INDUSTRYGROUPTYPE": "Other Technology", "REVENUERANGE": "Decline to Disclose", "ISAMENDMENT": "false", "SALE_DATE": "01-MAR-2025", "ISEQUITYTYPE": "true",
            "ISPOOLEDINVESTMENTFUNDTYPE": "false", "TOTALOFFERINGAMOUNT": "5000000", "TOTALAMOUNTSOLD": "5000000", "TOTALNUMBERALREADYINVESTED": "3", **off_cols}]
    rel = [{"ACCESSIONNUMBER": "A1", "RELATEDPERSON_SEQ_KEY": "101", "FIRSTNAME": "Jane", "MIDDLENAME": "", "LASTNAME": "Doe", "STREET1": "", "STREET2": "", "CITY": "", "STATEORCOUNTRY": "",
            "STATEORCOUNTRYDESCRIPTION": "", "ZIPCODE": "", "RELATIONSHIP_1": "Executive Officer", "RELATIONSHIP_2": "Director", "RELATIONSHIP_3": "", "RELATIONSHIPCLARIFICATION": ""}]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("2025Q1_d/FORMDSUBMISSION.tsv", tsv(sub)); z.writestr("2025Q1_d/ISSUERS.tsv", tsv(iss)); z.writestr("2025Q1_d/OFFERING.tsv", tsv(off)); z.writestr("2025Q1_d/RELATEDPERSONS.tsv", tsv(rel))
    return buf.getvalue()


def test_formd_parse_filters_funds_and_spvs_and_keeps_officers():
    recs = formd.parse_quarter(_quarter_zip())
    by = {r["accession"]: r for r in recs}
    assert by["A1"]["is_operating"] and by["A1"]["sold_usd"] == 9.6e6 and by["A1"]["sale_date"] == "2025-02-20" and by["A1"]["name_norm"] == "acme"
    assert by["A1"]["officers"][0]["roles"] == ["Executive Officer", "Director"]
    assert not by["A2"]["is_operating"] and not by["A3"]["is_operating"]     # trap 2: fund + SPV rejected structurally
    assert "Related persons: Jane Doe (Executive Officer, Director)" in formd.render_summary(by["A1"])


def test_formd_name_norm_strips_legal_forms():
    assert formd.name_norm("The Acme Holdings, LLC") == "acme" and formd.name_norm("Acme Labs Inc.") == "acme"


# ---------------------------------------------------------------- resolution
def test_resolve_prefers_cik_then_located_name_else_asks():
    f = {"cik": "9", "name_norm": "acme", "city": "Austin", "state": "TX", "previous_names": []}
    assert resolve.decide_structural(f, [{"name": "Acme", "hq": "Boston, MA", "cik": "9"}])[0] == "cik"
    assert resolve.decide_structural(f, [{"name": "Acme", "hq": "Austin, TX"}, {"name": "Acme", "hq": "Boston, MA"}])[0] == "exact_name"
    assert resolve.decide_structural(f, [{"name": "Acme", "hq": "Boston, MA"}, {"name": "Acme", "hq": "Denver, CO"}])[0] == "ambiguous"   # trap 1: namesake
    assert resolve.decide_structural(f, [])[0] == "none"


def test_ats_discovery_and_domain():
    html = '<a href="https://boards.greenhouse.io/acme">jobs</a> <script src="https://jobs.ashbyhq.com/acme/embed"></script> <a href="https://jobs.lever.co/acme-inc">x</a>'
    assert ats.discover([html]) == [("greenhouse", "acme"), ("lever", "acme-inc"), ("ashby", "acme")]
    assert http.registrable_domain("https://www.acme.ai/about") == "acme.ai" and http.registrable_domain("http://acme.co.uk") == "acme.co.uk"
    assert http.html_to_text("<p>Hi<br>there</p><script>x()</script>") == "Hi\nthere"


# ---------------------------------------------------------------- evaluator over our row shape (leaky pool, unknown, centre, exclusion)
def _rows():
    return [{"id": "a.ai", "kind": KIND, "sim": 0.9, "facets": {"stage": ["seed"], "tech_area": ["ai_infra"], "program": ["yc"]}, "numeric": {"total_disclosed_funding": 8e6}},
            {"id": "b.ai", "kind": KIND, "sim": 0.8, "facets": {"stage": ["series_b"], "tech_area": ["ai_infra"]}, "numeric": {"total_disclosed_funding": 60e6}},
            {"id": "c.ai", "kind": KIND, "sim": 0.95, "facets": {"tech_area": ["ai_infra"]}, "numeric": {}}]


def test_evaluate_musts_exclude_unknown_and_center_ranks():
    store = InMemoryFacetStore(_rows(), SCHEMA)
    c = Contract(kind=KIND, text="ai infra", must={"total_disclosed_funding": {"min": 5e6}}, center={"key": "stage", "value": "seed", "span": 1})
    out = asyncio.run(evaluate(c, store, SCHEMA, WEIGHTS))
    ids = [r["id"] for r in out["rows"]]
    assert "c.ai" not in ids                                   # trap 20: unknown never satisfies a must
    assert ids[0] == "a.ai"                                    # seed beats series_b (3 steps) despite lower sim
    assert out["counts"]["stage"] == {"seed": 1, "series_b": 1}


def test_exclusion_applied_by_the_route_helper():
    from api.startups.routes import _excluded
    assert _excluded(_rows()[0], {"program": ["yc"]}) and not _excluded(_rows()[1], {"program": ["yc"]})


def test_compile_downgrades_values_absent_from_the_index_and_zero_coverage_keys():
    c, notes = cp.build_contract({"text": "agents for healthcare", "must": {"tech_area": ["agents", "bio_health"], "founder_count": ["2"], "hiring": {"min": 1}}},
                                 coverage={"tech_area": 0.9}, value_counts={"tech_area": {"bio_health": 40}, "founder_count": {}})
    assert c.must == {"tech_area": ["bio_health"], "hiring": {"min": 1.0}}   # agents dropped (0 in the index); the explicit range stays
    assert c.prefer == {"founder_count": ["2"]}                    # a categorical key nobody has yet → preference
    assert any("open roles" in n.lower() for n in notes) and len(notes) == 3
