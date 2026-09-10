"""The investor query lexicon: which keys may harden, and which may never."""
from api.investors.compile import apply_lexicon, build_contract, lexicon_read, settle_text

COV = {"investor_type": .9, "country": .9, "metro": .9, "state": .9, "still_deploying": .9,
       "stated_stage": .9, "sector_focus": .9, "leads_rounds": .9}


def compiled(brief, model=None):
    plan = lexicon_read(brief)
    c, notes = build_contract(model or {"text": brief, "must": {}}, coverage=COV, brief=brief)
    notes += apply_lexicon(c, plan)
    notes += settle_text(c, brief, plan)
    return c, notes


class TestFiledKeysHarden:
    def test_an_investor_type_is_read_from_the_words(self):
        c, _ = compiled("venture capital firms in India")
        assert c.must["investor_type"] == ["venture_fund"] and c.must["country"] == ["in"]

    def test_an_alias_surface_still_blanks_the_text(self):
        """"India" becomes country=in through an alias; crediting only the value left "india" looking
        like unexplained prose and kept a semantic leg the brief did not need."""
        c, notes = compiled("venture capital firms in India")
        assert c.text == "" and any("filters are the search" in n for n in notes)

    def test_pe_and_a_metro(self):
        c, _ = compiled("pe funds in the bay area")
        assert c.must["investor_type"] == ["pe_fund"] and c.must["metro"] == ["bay_area"]


class TestStatedKeysNeverHarden:
    def test_a_stated_key_is_not_hardened_by_the_lexicon(self):
        """A must on a stated key filters by our own crawl progress, not by the market."""
        from api.investors.query_lexicon import MUST_KEYS
        for k in ("stated_stage", "stated_check_min", "sector_focus", "leads_rounds", "open_to_inbound"):
            assert k not in MUST_KEYS

    def test_a_sector_ranks_rather_than_filters(self):
        c, _ = compiled("funds investing in climate tech")
        assert "sector_focus" not in c.must


class TestRiskyWords:
    def test_angel_inside_a_longer_brief_does_not_harden(self):
        c, _ = compiled("funds that back angel-stage biotech companies in Texas")
        assert c.must.get("investor_type") != ["angel"]

    def test_semantic_residue_is_kept(self):
        c, _ = compiled("funds with deep operator networks", {"text": "deep operator networks", "must": {}})
        assert c.text == "deep operator networks"
