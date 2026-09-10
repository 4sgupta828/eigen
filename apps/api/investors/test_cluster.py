"""The traps §5 says must fail, as tests. Each is designed to PASS a weaker gate while being wrong."""
from api.investors.cluster import attach_cluster, cluster_funds, name_opens_with
from api.investors.sources.funds import is_spv


def _f(fid, name, persons=(), state="CA", cik="", spv=None, first_sale="2024-01-01"):
    return {"id": fid, "name": name, "state": state, "cik": cik, "first_sale": first_sale,
            "persons": [{"name": p, "roles": ["Executive Officer"]} for p in persons],
            "is_spv": is_spv(name) if spv is None else spv}


class TestNameGate:
    def test_accepts_the_firms_own_fund(self):
        assert name_opens_with("Bessemer Venture Partners", "Bessemer Venture Partners Fund X, L.P.")
        assert name_opens_with("Tamarack Global", "Tamarack Global Opportunities III, LP")

    def test_refuses_the_accela_class(self):
        assert not name_opens_with("Accel", "Accela Software Fund I")

    def test_refuses_the_hyphenated_spinout_class(self):
        """The trap the existing prefix-only helper passes: Accel-KKR is not Accel."""
        assert not name_opens_with("Accel", "Accel-KKR Capital Partners VI, L.P.")
        assert not name_opens_with("Accel", "Accel KKR Capital Partners VI, L.P.")

    def test_refuses_a_geographic_sibling_brand(self):
        assert not name_opens_with("Sequoia Capital", "Sequoia Capital India Growth Fund III")

    def test_refuses_an_spv_named_after_a_portfolio_company(self):
        assert not name_opens_with("Anthropic", "Anthropic SPV I, LLC")


class TestSpvDetection:
    def test_series_vehicles_are_spvs(self):
        assert is_spv("BI-0526 Fund I, a series of Exitfund Venture, LLC")
        assert is_spv("Axci Capital Fund R a Series of CGF2021 LLC")
        assert is_spv("OurCrowd (Investment in Morphisec) LP")
        assert is_spv("Acme Co-Invest I, LLC")

    def test_a_real_fund_is_not_an_spv(self):
        assert not is_spv("Tamarack Global Opportunities III, LP")
        assert not is_spv("Bessemer Venture Partners Fund X, L.P.")


class TestClustering:
    def test_shared_gps_join_a_managers_vehicles(self):
        funds = [_f("f1", "Layer Global Fund I, L.P.", ["ada lovelace", "alan turing"]),
                 _f("f2", "Layer China Fund I, L.P.", ["ada lovelace"]),
                 _f("f3", "Unrelated Ventures Fund I, LP", ["grace hopper"])]
        cl = cluster_funds(funds)
        assert cl["f1"] == cl["f2"], "the same GPs should join two vehicles of one manager"
        assert cl["f3"] != cl["f1"]

    def test_an_spv_platform_administrator_cannot_merge_the_market(self):
        """The measured failure: one admin signing many vehicles produced a 733-filing blob."""
        admin = "llc sydecar"
        funds = [_f(f"s{i}", f"Portfolio {i} Fund, LP", [admin, f"founder {i}"]) for i in range(30)]
        cl = cluster_funds(funds)
        assert len(set(cl.values())) == 30, "a hub signatory must not fuse unrelated managers"

    def test_spvs_are_not_clustered_at_all(self):
        funds = [_f("v1", "Deal One a Series of Platform Fund LLC", ["ops person"]),
                 _f("v2", "Deal Two a Series of Platform Fund LLC", ["ops person"])]
        assert cluster_funds(funds) == {}

    def test_the_state_qualifies_a_common_name(self):
        funds = [_f("a1", "Alpha Fund I, LP", ["john smith"], state="CA"),
                 _f("b1", "Beta Fund I, LP", ["john smith"], state="NY")]
        cl = cluster_funds(funds)
        assert cl["a1"] != cl["b1"], "a namesake in another state is another person"


class TestAttach:
    FIRMS = [{"id": "accel", "name": "Accel", "legal_name": "Accel Management Co", "cik": ""},
             {"id": "accel_kkr", "name": "Accel-KKR", "legal_name": "Accel-KKR Capital Partners", "cik": ""},
             {"id": "tamarack", "name": "Tamarack Global", "legal_name": "", "cik": "1234"}]

    def test_cik_wins(self):
        fid, method, _ = attach_cluster([_f("f", "Some Fund IV, LP", cik="1234")], self.FIRMS)
        assert (fid, method) == ("tamarack", "cik")

    def test_name_sequence_attaches_the_right_firm(self):
        fid, method, _ = attach_cluster([_f("f", "Accel-KKR Capital Partners VI, L.P.")], self.FIRMS)
        assert fid == "accel_kkr" and method == "name_sequence", "must not land on Accel"

    def test_an_unattachable_cluster_stays_unattached(self):
        fid, method, note = attach_cluster([_f("f", "Winterlight Partners Fund I, LP")], self.FIRMS)
        assert fid is None and method == "" and "no evidenced path" in note


class TestBrandVariants:
    def test_the_management_company_tail_is_stripped(self):
        from api.investors.cluster import brand_variants
        got = dict(brand_variants({"name": "UP PARTNERS MANAGEMENT COMPANY, LLC", "legal_name": ""}))
        assert "UP PARTNERS MANAGEMENT COMPANY, LLC" in got and "up" in got

    def test_a_one_token_brand_demands_a_state_match(self):
        from api.investors.cluster import brand_variants
        got = dict(brand_variants({"name": "Bond Capital", "legal_name": ""}))
        assert got["bond"] is True, "a one-word brand must be confirmed by the state"

    def test_a_two_token_brand_does_not(self):
        from api.investors.cluster import brand_variants
        got = dict(brand_variants({"name": "Tamarack Global Management LLC", "legal_name": ""}))
        assert got["tamarack global"] is False


class TestAttachWithBrands:
    FIRMS = [{"id": "up", "name": "UP PARTNERS MANAGEMENT COMPANY, LLC", "legal_name": "", "cik": "", "hq_state": "CA"},
             {"id": "bond", "name": "Bond Capital", "legal_name": "", "cik": "", "hq_state": "CA"},
             {"id": "accel", "name": "Accel", "legal_name": "", "cik": "", "hq_state": "CA"},
             {"id": "accel_kkr", "name": "Accel-KKR Capital Partners", "legal_name": "", "cik": "", "hq_state": "CA"}]

    def test_the_brand_closes_the_recall_gap(self):
        fid, method, _ = attach_cluster([_f("f", "UP Partners Fund II, LP", state="CA")], self.FIRMS)
        assert (fid, method) == ("up", "name_sequence")

    def test_a_one_token_brand_in_another_state_does_not_attach(self):
        fid, _, _ = attach_cluster([_f("f", "Bond Fund I, LP", state="NY")], self.FIRMS)
        assert fid is None, "a generic one-word brand needs the state to agree"

    def test_the_hyphenated_spinout_trap_still_holds_after_the_recall_fix(self):
        fid, _, _ = attach_cluster([_f("f", "Accel-KKR Capital Partners VI, L.P.", state="CA")], self.FIRMS)
        assert fid == "accel_kkr"


class TestBrandAmbiguity:
    """The one doubtful class the hand-check found: a one-word brand two firms share."""

    FIRMS = [{"id": "eclipse_ventures", "name": "Eclipse Ventures LLC", "legal_name": "", "cik": "", "hq_state": "CA"},
             {"id": "eclipse_capital", "name": "Eclipse Capital Management", "legal_name": "", "cik": "", "hq_state": "CA"},
             {"id": "lowercarbon", "name": "Lowercarbon Capital", "legal_name": "", "cik": "", "hq_state": "WY"}]

    def test_a_shared_one_word_brand_attaches_to_neither(self):
        from api.investors.cluster import attach_cluster
        fid, _, note = attach_cluster([_f("f", "Eclipse Partners Fund VI, L.P.", state="CA")], self.FIRMS)
        assert fid is None and "no evidenced path" in note

    def test_an_unshared_one_word_brand_still_attaches(self):
        from api.investors.cluster import attach_cluster
        fid, method, _ = attach_cluster([_f("f", "Lowercarbon Fund IV, LP", state="WY")], self.FIRMS)
        assert (fid, method) == ("lowercarbon", "name_sequence")

    def test_a_named_vehicle_needs_a_clustermate_to_attach(self):
        """"Lowercarbon Tesseract" is theirs, but the NAME alone cannot prove it — "Tesseract" is a content
        word, and the same shape is how "Sequoia Capital India" would smuggle itself in. It attaches only
        because a GP it shares signs a fund whose name does say so."""
        from api.investors.cluster import attach_cluster
        alone = attach_cluster([_f("f", "Lowercarbon Tesseract, LP", state="WY")], self.FIRMS)
        assert alone[0] is None
        with_mate = attach_cluster([_f("f", "Lowercarbon Tesseract, LP", state="WY"),
                                    _f("g", "Lowercarbon Fund IV, LP", state="WY")], self.FIRMS)
        assert with_mate[0] == "lowercarbon"


class TestChainingIsNotClustering:
    """The failure found by running the real thirty quarters, not the one-quarter sample.

    Union-find is transitive: A signs with B, B with C, and a chain of individually-plausible links merged
    Access Capital, ARDIAN and Arrow — three unrelated European managers — into one 142-vehicle cluster,
    because a Luxembourg fund administrator sat on all of them.
    """

    def _admin_chain(self):
        # one administrator, three unrelated managers, each with its own partner
        return [
            _f("a1", "Access Capital Emerging Managers Fund SCSp", ["lux admin", "alice access"], state="N4"),
            _f("a2", "Access Capital Growth Fund II SCSp", ["lux admin", "alice access"], state="N4"),
            _f("b1", "ARDIAN Americas Infrastructure Fund V SCSp", ["lux admin", "bruno ardian"], state="N4"),
            _f("c1", "Arrow Bridging SCSp, SICAV-RAIF", ["lux admin", "carla arrow"], state="N4"),
            _f("c2", "Arrow Credit Opportunities III SCSp", ["lux admin", "carla arrow"], state="N4"),
        ]

    def test_one_shared_administrator_does_not_merge_three_managers(self):
        cl = cluster_funds(self._admin_chain())
        assert cl["a1"] != cl["b1"], "Access Capital and ARDIAN share only an administrator"
        assert cl["b1"] != cl["c1"], "ARDIAN and Arrow share only an administrator"

    def test_but_a_managers_own_vehicles_still_join(self):
        cl = cluster_funds(self._admin_chain())
        assert cl["a1"] == cl["a2"], "two shared signers is a manager"
        assert cl["c1"] == cl["c2"]

    def test_a_generic_leading_word_is_not_a_brand(self):
        """"Fund", "Capital", "II" are not identities — one shared signer plus one of those is not a manager."""
        funds = [_f("g1", "Capital Partners Fund I, LP", ["shared person", "one"], state="NY"),
                 _f("g2", "Capital Growth Fund II, LP", ["shared person", "two"], state="NY")]
        cl = cluster_funds(funds)
        assert cl["g1"] != cl["g2"]

    def test_a_real_brand_word_plus_a_shared_signer_does_join(self):
        funds = [_f("t1", "Tamarack Global Opportunities II, LP", ["shared person", "one"], state="CA"),
                 _f("t2", "Tamarack Blue Energy I, LP", ["shared person", "two"], state="CA")]
        cl = cluster_funds(funds)
        assert cl["t1"] == cl["t2"]

    def test_a_prolific_gp_is_not_mistaken_for_an_administrator(self):
        """The first cap was a total of 8 across all time, which discarded working GPs over thirty quarters."""
        funds = [_f(f"p{i}", f"Meridian Fund {i}, LP", ["prolific gp", f"partner {i}"], state="CA",
                    first_sale=f"20{15 + i}-01-01") for i in range(10)]
        cl = cluster_funds(funds)
        assert len(set(cl.values())) == 1, "one fund a year for ten years is a GP, not a fund administrator"


class TestClusterSpanningSeveralFirms:
    """Measured in prod: 122 Blackstone vehicles all attached to one Blackstone arm."""

    IDX_FIRMS = [{"id": "bx_tac", "name": "Blackstone Tactical Opportunities Advisors", "legal_name": "", "cik": "", "hq_state": "NY"},
                 {"id": "bx_credit", "name": "Blackstone Alternative Credit Advisors", "legal_name": "", "cik": "", "hq_state": "NY"},
                 {"id": "tamarack", "name": "Tamarack Global Management", "legal_name": "", "cik": "", "hq_state": "CA"}]

    def _index(self):
        from api.investors.cluster import build_firm_index
        return build_firm_index(self.IDX_FIRMS)

    def test_a_cluster_that_matches_two_firms_is_split_not_handed_to_one(self):
        from api.investors.cluster import assign_cluster
        cluster = [_f("f1", "Blackstone Tactical Opportunities Fund IV, L.P.", state="NY"),
                   _f("f2", "Blackstone Alternative Credit Fund II, L.P.", state="NY"),
                   _f("f3", "Blackstone Bodyguard Partners L.P.", state="NY")]
        per = assign_cluster(cluster, self._index())
        assert per["f1"][0] == "bx_tac" and per["f2"][0] == "bx_credit"
        assert per["f3"][0] is None, "an unmatched vehicle in a split cluster evidences no firm"
        assert "spans 2 firms" in per["f3"][2]

    def test_a_single_firm_cluster_still_carries_its_unmatched_vehicles(self):
        from api.investors.cluster import assign_cluster
        cluster = [_f("g1", "Tamarack Global Opportunities III, LP", state="CA"),
                   _f("g2", "Tamarack Blue Energy I, LP", state="CA")]
        per = assign_cluster(cluster, self._index())
        assert per["g1"][0] == "tamarack" and per["g2"][0] == "tamarack", \
            "shared GPs are evidence the unmatched vehicle belongs to the same manager"

    def test_a_cluster_matching_nobody_stays_unattached(self):
        from api.investors.cluster import assign_cluster
        per = assign_cluster([_f("x1", "Winterlight Fund I, LP", state="MA")], self._index())
        assert per["x1"][0] is None


class TestTrailingSeriesVehicles:
    """Measured in prod: "Okeanos Venture Partners II, LLC - Series 106" and 69 siblings counted as 70 funds."""

    def test_a_trailing_series_designation_is_a_vehicle_not_a_fund(self):
        assert is_spv("Okeanos Venture Partners II, LLC - Series 106")
        assert is_spv("EquityZen Growth Opportunity Fund XI LLC - Series 2")
        assert is_spv("Acme Fund II, LLC, Series B")

    def test_a_roman_numeral_fund_is_still_a_fund(self):
        assert not is_spv("Tribe Capital Fund III, L.P.")
        assert not is_spv("Bessemer Venture Partners Fund X, L.P.")

    def test_a_series_word_inside_a_name_is_not_a_trailing_designation(self):
        assert not is_spv("Series Ventures Fund I, LP")
