"""Unit tests for the investor spine: identity, registers, bands, and the rules the panel forced."""
import pytest

from api.investors.pipeline import _investor_type, band_of, country_token, metro_token, mint_id, num_fact
from api.investors.schema import DOSSIER_ONLY, FIRM_ONLY, REGISTER, SCHEMA, UNIFIED, labels
from api.investors.sources import adv as adv_src
from api.investors.store import NOT_A_SITE, domain_of, slug


class TestSchemaShape:
    def test_every_key_declares_a_register(self):
        assert not [k.key for k in SCHEMA.keys if k.key not in REGISTER]

    def test_the_schema_is_investor_only(self):
        assert SCHEMA.kinds() == ("investor",)

    def test_success_metrics_are_not_facets(self):
        """The panel's unanimous call: a coverage-biased subset must not be filterable (spec §4)."""
        keys = {k.key for k in SCHEMA.keys}
        for k in DOSSIER_ONLY:
            assert k not in keys, f"{k} must not be a searchable facet"

    def test_unified_pairs_exist_on_both_sides(self):
        keys = {k.key for k in SCHEMA.keys}
        for a, b in UNIFIED.items():
            assert a in keys and b in keys

    def test_labels_carry_the_register_for_the_rail(self):
        lab = labels()
        assert lab["register"]["aum"] == "filed"
        assert lab["register"]["stated_check_min"] == "stated"
        assert lab["register"]["portfolio_count"] == "observed"

    def test_firm_only_metrics_are_declared(self):
        """Individuals never carry computed financial metrics — enforced at the projector, declared here."""
        assert "led_round_size" in FIRM_ONLY and "aum" in FIRM_ONLY


class TestDomainIdentity:
    @pytest.mark.parametrize("url", ["https://linkedin.com/company/acme", "http://www.x.com/vc",
                                     "https://facebook.com/fund", "https://crunchbase.com/organization/x"])
    def test_a_social_page_is_not_a_domain(self, url):
        """1,355 ADV firms give linkedin.com as their website; a domain key would fuse them into one node."""
        assert domain_of(url) == ""

    def test_a_real_site_resolves_to_its_registrable_domain(self):
        assert domain_of("https://www.a16z.com/portfolio") == "a16z.com"
        assert domain_of("https://sub.balderton.co.uk/team") == "balderton.co.uk"

    def test_the_social_list_covers_the_measured_offenders(self):
        for host in ("linkedin.com", "twitter.com", "x.com", "facebook.com", "instagram.com", "youtube.com"):
            assert host in NOT_A_SITE


class TestMintedIds:
    def test_a_domain_gives_a_readable_id(self):
        assert mint_id(name="Andreessen Horowitz", domain="a16z.com", crd="1", state="CA", taken=set()) == "a16z"

    def test_a_firm_with_no_website_still_gets_an_id(self):
        got = mint_id(name="Galileo Global Ltd", domain="", crd="342972", state="CO", taken=set())
        assert got and got != "crd_342972", "a name is better than a bare CRD when we have one"

    def test_a_name_collision_is_disambiguated_not_merged(self):
        first = mint_id(name="Summit Partners", domain="", crd="1", state="MA", taken=set())
        second = mint_id(name="Summit Partners", domain="", crd="2", state="TX", taken={first})
        assert first != second, "two firms printing one name in two states are two firms"

    def test_disambiguation_terminates_even_when_state_is_taken(self):
        taken = {"acme", "acme_ca", "crd_9_acme"}
        got = mint_id(name="Acme", domain="", crd="9", state="CA", taken=taken)
        assert got not in taken


class TestBands:
    def test_aum_bands_read_off_the_schema(self):
        assert band_of("aum", 484_007_760) == "250m_1b"
        assert band_of("aum", 39_070_000_000) == "10b_plus"
        assert band_of("aum", 0) == "under_10m"

    def test_an_absent_number_has_no_band(self):
        assert band_of("aum", None) == ""
        assert num_fact("aum", None) == []

    def test_a_numeric_fact_carries_both_band_and_raw_number(self):
        f = num_fact("latest_fund_size", 30e6, basis="form_d")[0]
        assert f["value"] == "10m_50m" and f["number"] == 30e6


class TestGeo:
    def test_known_countries_normalise(self):
        assert country_token("United States") == "us"
        assert country_token("United Arab Emirates") == "ae"
        assert country_token("India") == "in"

    def test_an_unknown_country_is_kept_not_guessed(self):
        assert country_token("Republic of Elbonia") == "republic_of_elbonia"

    def test_metros_only_where_we_actually_know(self):
        assert metro_token("Menlo Park") == "bay_area"
        assert metro_token("Bengaluru") == "bangalore"
        assert metro_token("Nowheresville") == "", "a city we cannot place is unknown, never a guess"


class TestInvestorType:
    FIRM = {"kind": "firm", "sources": ["sec_era"], "fund_flags": {}}

    def test_seed_versus_venture_is_decided_by_filed_fund_size(self):
        """'Seed fund' is a self-description a $400M fund also uses; the filing decides."""
        assert _investor_type(self.FIRM, {"Venture Capital Fund"}, 30e6) == "seed_fund"
        assert _investor_type(self.FIRM, {"Venture Capital Fund"}, 400e6) == "venture_fund"

    def test_private_equity_only(self):
        assert _investor_type(self.FIRM, {"Private Equity Fund"}, 500e6) == "pe_fund"

    def test_an_individual_is_an_angel(self):
        assert _investor_type({"kind": "individual", "sources": []}, set(), None) == "angel"

    def test_no_filing_and_no_register_gives_no_type(self):
        assert _investor_type({"kind": "firm", "sources": ["portfolio_page"]}, set(), None) == ""

    def test_the_register_types_a_firm_whose_funds_are_not_attached_yet(self):
        """Without this, a16z and Kleiner Perkins render as "other" — the register already said venture."""
        f = {"kind": "firm", "sources": ["sec_ria"], "fund_flags": {"vc": True, "pe": False}}
        assert _investor_type(f, set(), None) == "venture_fund"
        assert _investor_type({**f, "fund_flags": {"vc": False, "pe": True}}, set(), None) == "pe_fund"

    def test_a_filed_fund_size_outranks_the_register_flag(self):
        f = {"kind": "firm", "sources": ["sec_ria"], "fund_flags": {"vc": True}}
        assert _investor_type(f, {"Venture Capital Fund"}, 30e6) == "seed_fund"

    def test_a_register_flag_alone_never_says_seed(self):
        """`seed_fund` is a claim about size, and the register states no size."""
        f = {"kind": "firm", "sources": ["sec_era"], "fund_flags": {"vc": True}}
        assert _investor_type(f, set(), None) == "venture_fund"


class TestAdvParsing:
    ROW = {"Organization CRD#": "309765", "Primary Business Name": "UP PARTNERS MANAGEMENT COMPANY, LLC",
           "Legal Name": "UP PARTNERS MANAGEMENT COMPANY, LLC", "Website Address": "https://up.partners",
           "Main Office City": "SANTA MONICA", "Main Office State": "CA", "Main Office Country": "United States",
           "3A": "Limited Liability Company", "Firm Type": "ERA", "Any VC Funds": "Y",
           "Total number of VC funds": "8", "Total Gross Assets of Private Funds": "  484,007,760.00 "}

    def test_a_firm_row_parses(self):
        p = adv_src.parse_firm(self.ROW)
        assert p["crd"] == "309765" and p["domain"] == "up.partners"
        assert p["aum"] == 484007760.0 and p["aum_basis"] == "adv_private_fund_assets"
        assert p["funds"]["vc"] and adv_src.is_investor(p)

    def test_raum_wins_over_private_fund_assets_when_both_are_filed(self):
        p = adv_src.parse_firm({**self.ROW, "5F(2)(c)": "2,792,196,229.00"})
        assert p["aum"] == 2792196229.0 and p["aum_basis"] == "adv_raum", "the two are different measures"

    def test_a_row_with_no_crd_is_not_a_firm(self):
        assert adv_src.parse_firm({**self.ROW, "Organization CRD#": ""}) is None

    def test_a_hedge_only_manager_is_not_in_this_population(self):
        p = adv_src.parse_firm({**self.ROW, "Any VC Funds": "N", "Any Hedge Funds": "Y"})
        assert not adv_src.is_investor(p)

    def test_the_era_flag_picks_the_right_register(self):
        assert adv_src.registers_of(adv_src.parse_firm(self.ROW)) == ["sec_era"]
        assert adv_src.registers_of(adv_src.parse_firm({**self.ROW, "Firm Type": "RIA"})) == ["sec_ria"]


class TestSlug:
    def test_slug_is_stable_and_bounded(self):
        assert slug("Andreessen Horowitz") == "andreessen_horowitz"
        assert slug("!!!") == ""
        assert len(slug("x" * 200)) <= 60


class TestDisplayName:
    def test_the_legal_tail_comes_off(self):
        from api.investors.store import display_name
        assert display_name("UP PARTNERS MANAGEMENT COMPANY, LLC") == "Up Partners Management Company"
        assert display_name("Greycroft LP") == "Greycroft"
        assert display_name("Acme Holdings, LLC, L.P.") == "Acme Holdings"

    def test_acronym_brands_are_not_mangled(self):
        """A plain .title() turns the brands this mode is about into nonsense."""
        from api.investors.store import display_name
        assert display_name("A16Z") == "A16Z"
        assert display_name("8VC") == "8VC"
        assert display_name("DCVC") == "DCVC"
        assert display_name("RCP ADVISORS, LLC") == "RCP Advisors"

    def test_a_normal_mixed_case_name_is_left_alone(self):
        from api.investors.store import display_name
        assert display_name("Kleiner Perkins") == "Kleiner Perkins"


class TestSubjectCongruence:
    """A related entity's fact is not this entity's fact — the rule the whole spec turns on."""

    def test_an_affiliates_register_flag_never_types_the_brand(self):
        """a16z Perennial Management is registered and runs PE funds. The venture brand a16z is a different
        subject, and typing it `pe_fund` from its affiliate would pass every string-level check while being
        wrong. A brand with no filing of its own stays untyped."""
        brand = {"kind": "firm", "sources": ["portfolio_page"], "fund_flags": {}}
        assert _investor_type(brand, set(), None) == ""


class TestCompile:
    """The compiler's two investor-specific rules."""

    def _build(self, out, **kw):
        from api.investors.compile import build_contract
        return build_contract(out, **kw)

    def test_a_track_record_brief_is_refused_with_an_alternative(self):
        c, notes = self._build({"text": "x", "must": {}}, brief="funds with the best track record")
        assert any("not searchable here" in n and "still deploying" in n for n in notes)
        assert not c.must

    def test_irr_and_top_tier_also_trip_it(self):
        for brief in ("top quartile funds", "highest IRR seed funds", "who has the best returns"):
            _, notes = self._build({"text": "x"}, brief=brief)
            assert any("not searchable" in n for n in notes), brief

    def test_a_stated_key_with_no_coverage_becomes_a_preference(self):
        """Before the firm-site pass runs, a must on a stated key returns nothing at all."""
        c, notes = self._build({"text": "x", "must": {"stated_stage": ["seed"]}},
                               coverage={"stated_stage": 0.0}, brief="seed funds")
        assert "stated_stage" not in c.must and c.prefer["stated_stage"] == ["seed"]
        assert any("no investor in the index states this yet" in n for n in notes)

    def test_a_partly_covered_stated_key_keeps_its_must_and_says_what_it_sees(self):
        c, notes = self._build({"text": "x", "must": {"leads_rounds": ["leads"]}},
                               coverage={"leads_rounds": 0.2}, brief="funds that lead")
        assert c.must["leads_rounds"] == ["leads"]
        assert any("only 20% of investors state this" in n for n in notes)

    def test_no_coverage_table_means_unknown_not_uncovered(self):
        """A failed coverage read must not silently turn every must into a preference."""
        c, notes = self._build({"text": "x", "must": {"country": ["us"]}}, coverage=None, brief="us funds")
        assert c.must == {"country": ["us"]} and not notes

    def test_a_well_covered_filed_key_is_left_alone(self):
        c, notes = self._build({"text": "x", "must": {"latest_fund_size": {"min": 5e7}}},
                               coverage={"latest_fund_size": 0.62}, brief="funds over $50m")
        assert c.must["latest_fund_size"] == {"min": 5e7} and not notes

    def test_an_observed_key_is_moved_onto_its_stated_twin(self):
        """One control, two registers: the filter matches either, so the contract carries the stated key."""
        c, _ = self._build({"text": "x", "must": {"observed_sector": ["fintech"]}},
                           coverage={"sector_focus": 0.9}, brief="fintech investors")
        assert c.must.get("sector_focus") == ["fintech"] and "observed_sector" not in c.must

    def test_an_invented_key_is_dropped_not_crashed(self):
        c, _ = self._build({"text": "x", "must": {"vibes": ["good"], "country": ["us"]}},
                           coverage={"country": 0.86}, brief="us funds")
        assert c.must == {"country": ["us"]}

    def test_a_thin_key_survives_when_the_requested_values_are_well_covered(self):
        c, _ = self._build({"text": "x", "must": {"metro": ["bay_area"]}},
                           coverage={"metro": 0.4}, value_counts={"metro": {"bay_area": 900}}, brief="bay area")
        assert c.must["metro"] == ["bay_area"]


class TestDeriveWritesWhatItDeclares:
    """`put_facts` DELETES every key in its `keys=` list before inserting, so a key that is declared but never
    produced does not merely go missing — it is actively erased on every run.

    This is not hypothetical: reverting an unrelated block deleted the two lines that append `investor_type`,
    the value was still computed and then dropped on the floor, and 7,424 investors shipped with no type at
    all. It survived the unit tests because they test `_investor_type` in isolation, and survived the local
    run because that ran before the revert.
    """

    def _derive_source(self):
        import inspect
        from api.investors import pipeline
        return inspect.getsource(pipeline.run_derive)

    def test_every_declared_key_is_actually_produced(self):
        import re
        src = self._derive_source()
        declared = re.search(r"put_facts\(fid, facts, keys=\[(.*?)\]\)", src, re.S)
        assert declared, "run_derive should declare the keys it rewrites"
        keys = re.findall(r'"([a-z_]+)"', declared.group(1))
        assert len(keys) > 5
        body = src[:declared.start()]
        for k in keys:
            produced = f'"key": "{k}"' in body or f'num_fact("{k}"' in body or f'"{k}")' in body
            assert produced, f"{k} is deleted on every derive but never written back"

    def test_investor_type_specifically(self):
        src = self._derive_source()
        assert '"key": "investor_type"' in src, "the type is the primary facet; it must be written"


class TestCompanyLabel:
    """A portfolio card that reads "Visit Website · Visit Website · Visit Website" is useless."""

    def _l(self, n, d):
        from api.investors.pipeline import company_label
        return company_label(n, d)

    def test_a_real_name_survives(self):
        assert self._l("Notion", "notion.so") == "Notion"
        assert self._l("Scale AI", "scale.com") == "Scale AI"

    def test_generic_anchor_text_falls_back_to_the_domain(self):
        assert self._l("Visit Website", "sourcegraph.com") == "Sourcegraph"
        assert self._l("Read more", "stripe.com") == "Stripe"
        assert self._l("→", "glue.ai") == "Glue"
        assert self._l("", "withgrid.com") == "Withgrid"

    def test_a_bare_domain_becomes_a_name(self):
        assert self._l(".databricks.com →", "databricks.com") == "Databricks"
        assert self._l("harmonic.ai", "harmonic.ai") == "Harmonic"


class TestCuratedBrandMerging:
    """A curated brand slug and the registered firm behind it are one investor, or two — and the difference
    is whether the registrant reduces to exactly that brand."""

    def _brands(self, name):
        from api.investors.cluster import brand_variants
        from api.investors.store import slug
        return [slug(c) for c, _ in brand_variants({"name": name, "legal_name": ""})]

    def test_the_same_firm_reduces_to_the_brand(self):
        assert "felicis" in self._brands("Felicis Ventures Management Company")

    def test_a_different_business_line_does_not(self):
        """a16z Perennial is a wealth business; merging it with the venture brand mistypes the venture firm."""
        assert "a16z" not in self._brands("A16Z Perennial Management")
        assert "a16z" not in self._brands("AH Capital Management")

    def test_company_label_strips_screen_reader_suffixes(self):
        from api.investors.pipeline import company_label
        assert company_label("aaru.com/ (opens in new tab)", "aaru.com") == "Aaru"
        assert company_label("Assort Health (opens in a new window)", "assorthealth.com") == "Assort Health"
