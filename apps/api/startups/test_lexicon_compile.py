"""The query lexicon and the settle-text rule — and proof that ordinary briefs are unchanged by them."""
from api.startups.compile import apply_lexicon, build_contract, lexicon_read, settle_text

COV = {"investor": .9, "stage": .9, "status": .9, "tech_area": .9, "program": .9, "metro": .9,
       "business_model": .9, "customer": .9, "country": .9}


def compiled(brief, model):
    c, notes = build_contract(model, coverage=COV, brief=brief)
    notes += apply_lexicon(c, lexicon_read(brief))
    notes += settle_text(c, brief)
    return c, notes


class TestSettleText:
    def test_a_brief_that_is_entirely_a_filter_drops_its_words(self):
        """The reported bug: the filter was right, and a semantic leg on the same words ran anyway, so
        companies merely NAMED Amplify fused in beside the ones Amplify funded."""
        c, notes = compiled("companies backed by Amplify",
                            {"text": "companies backed by Amplify", "must": {"investor": ["amplify"]}})
        assert c.must == {"investor": ["amplify"]} and c.text == ""
        assert any("filters are the search" in n for n in notes)

    def test_a_brief_with_real_semantic_content_keeps_it(self):
        c, _ = compiled("AI infrastructure startups backed by Amplify",
                        {"text": "AI infrastructure", "must": {"investor": ["amplify"]}})
        assert c.text == "AI infrastructure", "the part no filter covers must still rank"

    def test_a_scope_only_must_does_not_blank(self):
        """Blanking on a country-only must hands the evaluator the whole index and lets its cap choose."""
        c, _ = compiled("companies in the us", {"text": "companies in the us", "must": {"country": ["us"]}})
        assert c.text == "companies in the us"

    def test_the_flagship_brief_is_unchanged(self):
        """A regression guard: the spec's own example must compile as it always has."""
        brief = "seed to series A AI-infra startups selling to banks"
        c, _ = compiled(brief, {"text": "AI infrastructure sold to banks", "must": {"stage": ["seed", "series_a"]}})
        assert c.text == "AI infrastructure sold to banks" and c.must["stage"] == ["seed", "series_a"]

    def test_no_filters_means_no_blanking(self):
        c, _ = compiled("something nobody indexed", {"text": "something nobody indexed", "must": {}})
        assert c.text == "something nobody indexed"


class TestLexiconFillsWhatTheModelMissed:
    def test_a_bare_status_word_is_read(self):
        """"acquired" is a legal status and the compiler, told to extract stated requirements, saw none."""
        c, notes = compiled("acquired fintech companies", {"text": "acquired fintech companies", "must": {}})
        assert c.must.get("status") == ["acquired"]
        assert any("straight from your words" in n for n in notes)

    def test_aliases_reach_canonical_values(self):
        c, _ = compiled("b2b saas in new york", {"text": "b2b saas in new york", "must": {}})
        assert c.must.get("customer") == ["enterprise"] and c.must.get("metro") == ["new_york"]

    def test_the_model_wins_where_it_spoke(self):
        """It read the sentence; the lexicon read only words."""
        c, _ = compiled("acquired fintech companies",
                        {"text": "fintech", "must": {"status": ["active"]}})
        assert c.must["status"] == ["active"]

    def test_an_ordinary_word_that_is_also_a_value_ranks_rather_than_filters(self):
        """"data" is a tech area and an English word; a bare match is as likely to be grammar."""
        c, _ = compiled("startups with a data moat", {"text": "startups with a data moat", "must": {}})
        assert "data" not in str(c.must), "a risky value inside a longer brief must not harden"

    def test_a_brief_the_lexicon_cannot_read_is_left_alone(self):
        c, notes = compiled("companies solving protein folding",
                            {"text": "protein folding", "must": {}})
        assert c.text == "protein folding" and not c.must


class TestKeywordLeg:
    """Dense expands, sparse anchors. Until the tsv column existed a startup search had only the dense leg."""

    def test_the_store_exposes_both_legs(self):
        from api.startups.store import StartupStore
        assert hasattr(StartupStore, "keyword") and hasattr(StartupStore, "hybrid")

    def test_the_ddl_creates_the_index(self):
        from api.startups.store import _DDL
        assert "ix_su_company_tsv" in _DDL and "websearch_to_tsquery" not in _DDL
        assert "to_tsvector('simple'" in _DDL, "company names are proper nouns; stemming loses exact matches"


class TestDirectionsSurviveBothPaths:
    """A real user search runs MERGED, which builds its own response dict.

    Directions were attached inside `_evaluate_core`, so single-mode tests passed and every actual search
    lost them. The attach now happens where both paths meet, and this pins the shape so the next person
    who adds a field to one path does not lose it on the other.
    """

    def _source(self):
        import inspect
        from api.startups import routes
        return inspect.getsource(routes.build_router)

    def test_directions_are_attached_after_the_merge_branch(self):
        src = self._source()
        merge_at = src.index('out["relaxed"] = relaxed')
        attach_at = src.index('out["directions"]')
        assert attach_at > merge_at, "attached before the paths converge — the merged path loses it"

    def test_only_one_place_attaches_them(self):
        assert self._source().count('out["directions"] =') == 1, \
            "two attach points drift; the merged one is the one users hit"

    def test_the_contract_used_is_the_one_that_ran(self):
        """Relaxing can change the contract, and a direction on a key that was just relaxed away is noise."""
        src = self._source()
        i = src.index('out["directions"]')
        assert 'out.get("contract")' in src[i:i + 260]
