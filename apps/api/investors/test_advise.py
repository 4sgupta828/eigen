"""Startup Advisor: what counts as a reason, and what is refused."""
from api.investors.advise import (SPECIFIC, build_contract, conflicts_for, is_advice, reasons_for,
                                  stage_from_text)


class TestStageFromDeck:
    def test_an_explicit_round_is_read(self):
        assert stage_from_text("We are raising our Series A this quarter") == "series_a"
        assert stage_from_text("Raising a seed round of $3M") == "seed"
        assert stage_from_text("Pre-seed round now open") == "pre_seed"

    def test_the_latest_named_round_wins(self):
        """A Series A deck recaps the seed on its traction slide."""
        assert stage_from_text("We raised a seed in 2024. Now raising Series A.") == "series_a"

    def test_an_amount_is_never_a_stage(self):
        """$3M is a seed in one sector and a pre-seed in another; guessing it silently is the failure."""
        assert stage_from_text("We are raising $3M at a $15M valuation") == ""
        assert stage_from_text("ARR is $1.2M and growing") == ""


class TestWhatCountsAsAReason:
    def _row(self, **facets):
        return {"facets": facets, "numeric": {"latest_fund_year": 2026}}

    def test_a_sector_match_is_advice(self):
        why, _ = reasons_for(self._row(observed_sector=["fintech"]), stage="", sectors=["fintech"],
                             geo=[], co_investors=[])
        assert is_advice(why) and why[0]["signal"] == "sector" and why[0]["register"] == "observed"

    def test_still_deploying_alone_is_not_advice(self):
        """True of thousands of firms — ranking on it yields an alphabetical list dressed as a recommendation."""
        why, _ = reasons_for(self._row(still_deploying=["yes_recent"]), stage="seed", sectors=["fintech"],
                             geo=["us"], co_investors=[])
        assert why and not is_advice(why)

    def test_a_stated_match_is_labelled_as_stated(self):
        why, _ = reasons_for(self._row(stated_stage=["seed"]), stage="seed", sectors=[], geo=[], co_investors=[])
        assert why[0]["register"] == "stated", "the firm saying it is not the same as us seeing it"

    def test_an_observed_stage_outranks_a_stated_one(self):
        obs, s_obs = reasons_for(self._row(observed_stage=["seed"]), stage="seed", sectors=[], geo=[], co_investors=[])
        std, s_std = reasons_for(self._row(stated_stage=["seed"]), stage="seed", sectors=[], geo=[], co_investors=[])
        assert s_obs > s_std

    def test_a_co_investor_match_counts(self):
        why, _ = reasons_for(self._row(co_investor=["sequoia"]), stage="", sectors=[], geo=[],
                             co_investors=["sequoia"])
        assert is_advice(why) and why[0]["signal"] == "co_investor"

    def test_every_specific_signal_is_declared(self):
        for sig in ("sector", "stage_observed", "stage_stated", "geo", "co_investor"):
            assert sig in SPECIFIC


class TestConflicts:
    def test_a_portfolio_company_in_your_sector_is_flagged(self):
        got = conflicts_for([{"id": "rival.com", "name": "Rival"}], ["fintech"], {"rival.com": ["fintech"]})
        assert got and got[0]["name"] == "Rival" and got[0]["sector"] == "fintech"

    def test_an_unrelated_portfolio_company_is_not(self):
        assert conflicts_for([{"id": "x.com", "name": "X"}], ["fintech"], {"x.com": ["robotics"]}) == []

    def test_a_company_we_cannot_type_is_not_a_conflict(self):
        assert conflicts_for([{"id": "y.com", "name": "Y"}], ["fintech"], {}) == []


class TestContract:
    def test_the_signals_are_preferences_not_filters(self):
        """Three hard filters return an empty page long before they return a wrong one."""
        c = build_contract(stage="seed", sectors=["fintech"], geo=["us"])
        assert c.must == {} and "observed_sector" in c.prefer and "stated_stage" in c.prefer


class TestPreSeedIsNotSeed:
    def test_pre_seed_is_read_as_pre_seed(self):
        """"pre-seed round" contains "seed round"; checked in the wrong order it reads as a seed."""
        assert stage_from_text("Pre-seed round now open") == "pre_seed"
        assert stage_from_text("raising preseed") == "pre_seed"

    def test_a_later_round_still_wins_over_a_pre_seed_mention(self):
        assert stage_from_text("We raised a pre-seed in 2024, now raising Series A") == "series_a"
