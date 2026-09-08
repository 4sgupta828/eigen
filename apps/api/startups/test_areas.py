"""The sector back-fill: precision before recall, because these values FILTER a search."""
from __future__ import annotations

from api.startups.compile import area_named_in
from api.startups.schema import TECH_AREAS, VALUE_LABELS
from api.startups.sources.areas import PHRASES, areas_for


def test_every_new_area_is_in_the_schema_and_has_a_label():
    for area in PHRASES:
        assert area in TECH_AREAS, area
        assert VALUE_LABELS.get(area), area


def test_the_areas_people_actually_ask_for_exist():
    for area in ("ecommerce", "legal_compliance", "proptech", "edtech", "logistics_supply",
                 "crypto_web3", "insurance", "govtech", "quantum"):
        assert area in TECH_AREAS


def test_a_brief_naming_ecommerce_now_finds_an_exact_area():
    """The reported failure: "Ecommerce" had no area, so it was approximated to consumer."""
    assert area_named_in("ecommerce startups building on Shopify", "ecommerce")
    assert area_named_in("legaltech for contract review", "legal_compliance")
    assert not area_named_in("ai infrastructure startups", "ecommerce")


def test_a_distinctive_phrase_assigns_an_area_and_keeps_the_sentence_that_proves_it():
    got = areas_for("We help online stores increase conversion. Shopify merchants use our storefront.")
    assert got[0]["value"] == "ecommerce"
    assert "online stores" in got[0]["quote"]        # the assignment can be checked


def test_marketing_prose_assigns_nothing():
    """The loose version of this list matched 1,276 companies for proptech, almost all on the word
    "building" as a verb. A phrase must name an industry or be a term of art in it."""
    assert areas_for("We are building the future of work.") == []
    assert areas_for("The best platform for modern teams.") == []


def test_more_distinct_phrases_wins_over_a_passing_mention():
    got = areas_for("Our supply chain platform gives freight brokers and 3PL operators warehouse "
                    "visibility. We also accept crypto.")
    assert got[0]["value"] == "logistics_supply"


def test_at_most_two_areas_and_never_one_the_company_already_has():
    text = ("Our compliance platform helps law firms with contract review, SOC 2 and HIPAA compliance, "
            "for insurance carriers doing underwriting of policyholders, plus payroll and recruiting.")
    assert len(areas_for(text)) <= 2
    assert "legal_compliance" not in [a["value"] for a in areas_for(text, known={"legal_compliance"})]


def test_a_word_boundary_is_required():
    """"ev" inside "development" is not electric vehicles; "crop" inside "cropped" is not agriculture."""
    assert areas_for("Our development platform ships cropped images to developers.") == []


def test_an_area_the_brief_names_outright_is_never_lost():
    """"insurtech startups" came back with no tech_area at all, so nothing was filtered and all
    17,613 companies were merely ranked."""
    import api.startups.compile as cp
    c, notes = cp.build_contract({"text": "insurtech startups", "must": {}}, brief="insurtech startups")
    assert c.must.get("tech_area") == ["insurance"]
    assert any("named it" in n for n in notes)


def test_a_brief_that_merely_mentions_a_broad_word_is_untouched():
    """"data" and "sales" appear in briefs innocently; only terms of art restore an area."""
    import api.startups.compile as cp
    c, _ = cp.build_contract({"text": "startups with a great sales team", "must": {}},
                             brief="startups with a great sales team")
    assert "tech_area" not in c.must


def test_a_brief_naming_two_sectors_is_left_to_the_model():
    import api.startups.compile as cp
    c, _ = cp.build_contract({"text": "fintech and proptech startups", "must": {}},
                             brief="fintech and proptech startups")
    assert "tech_area" not in c.must          # ambiguous: rank, do not guess which one to filter on
