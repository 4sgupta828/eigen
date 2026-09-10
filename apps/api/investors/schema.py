"""The investor facet SCHEMA — the vocabulary of Investor Search (docs/specs/investors.md §4).

Mechanics (types, contract grammar, evaluator, counts) live in `eigen_kernel.facets`; this module only says
WHICH keys exist for entity kind `investor`, their vocabularies / bands / order, one line of guidance per key,
the ranking weights, and the labels the UI shows.

The one thing this schema carries that the startup schema does not is REGISTER. Every key is `filed`, `stated`
or `observed` (§0), and the register is a property of the KEY, not of a row — so the rail can group by it, the
card can glyph it, and the projector can refuse to write a stated value into a filed key.

Two keys the spec deliberately does NOT define here: `outcome_mix` and `follow_on_rate`. They are computed for
the dossier and are not facets — not filterable, not sortable, not rankable. A biased subset of a portfolio
produces a plausible, wrong shape, and printing the denominator does not repair it (§4).
"""
from __future__ import annotations

from eigen_kernel.facets import FacetKey, FacetSchema, FacetType, FacetWeights

KIND = "investor"
I = (KIND,)

# Every type an investor can be. `angel` and `angel_group` are separate on purpose: a network is not its members.
INVESTOR_TYPES = ("angel", "angel_group", "syndicate", "accelerator", "studio", "seed_fund", "venture_fund",
                  "growth_fund", "pe_fund", "fund_of_funds", "corporate_vc", "family_office", "crossover_hedge",
                  "sovereign", "endowment", "government", "venture_debt", "other")
# The stage vocabulary is the startup schema's, plus `all` for a firm that says it is stage-agnostic.
STAGES = ("pre_seed", "seed", "series_a", "series_b", "series_c", "growth", "all")
LEADS = ("leads", "follows", "both")
INBOUND = ("application_form", "email", "warm_intro_only", "not_stated")
DEPLOYING = ("yes_recent", "quiet")
DISCLOSURES = ("none_reported", "1_2", "3_plus")
LP_DISCLOSED = ("yes",)
EVIDENCE = ("single_source", "two_sources", "filing_backed")
# Which public register a firm is actually on — a filed fact, and the honest answer to "why is this card thin".
REGISTERS = ("sec_ria", "sec_era", "sec_formd", "fca", "esma", "sebi", "mas", "asic", "adgm", "sbic", "portfolio_page")

AUM_BANDS = (("under_10m", None, 1e7), ("10m_50m", 1e7, 5e7), ("50m_250m", 5e7, 2.5e8),
             ("250m_1b", 2.5e8, 1e9), ("1b_10b", 1e9, 1e10), ("10b_plus", 1e10, None))
FUND_BANDS = (("under_10m", None, 1e7), ("10m_50m", 1e7, 5e7), ("50m_250m", 5e7, 2.5e8),
              ("250m_1b", 2.5e8, 1e9), ("1b_plus", 1e9, None))
CHECK_BANDS = (("under_100k", None, 1e5), ("100k_500k", 1e5, 5e5), ("500k_2m", 5e5, 2e6),
               ("2m_5m", 2e6, 5e6), ("5m_15m", 5e6, 1.5e7), ("15m_plus", 1.5e7, None))
OWNERSHIP_BANDS = (("under_5", None, 5.0), ("5_10", 5.0, 10.0), ("10_15", 10.0, 15.0),
                   ("15_20", 15.0, 20.0), ("20_plus", 20.0, None))
COUNT_BANDS = (("1", 1.0, 2.0), ("2_3", 2.0, 4.0), ("4_6", 4.0, 7.0), ("7_plus", 7.0, None))
PORTFOLIO_BANDS = (("1_5", 1.0, 6.0), ("6_20", 6.0, 21.0), ("21_50", 21.0, 51.0),
                   ("51_150", 51.0, 151.0), ("150_plus", 151.0, None))
YEAR_BANDS = (("before_2010", None, 2010.0), ("2010_2015", 2010.0, 2016.0), ("2016_2020", 2016.0, 2021.0),
              ("2021_2023", 2021.0, 2024.0), ("2024_plus", 2024.0, None))
IRR_BANDS = (("under_0", None, 0.0), ("0_10", 0.0, 10.0), ("10_20", 10.0, 20.0), ("20_plus", 20.0, None))

SCHEMA = FacetSchema(keys=(
    # ---------------- filed: a regulator or a filing says so ----------------
    FacetKey(key="investor_type", type=FacetType.categorical, kinds=I, label="Type", values=INVESTOR_TYPES,
             guidance="what kind of investor: angel (an individual), angel_group / syndicate, accelerator, "
                      "seed_fund / venture_fund / growth_fund by fund size, pe_fund, fund_of_funds, corporate_vc, "
                      "family_office, crossover_hedge, sovereign, endowment, government, venture_debt"),
    FacetKey(key="registered_with", type=FacetType.set, kinds=I, label="On the register", values=(), top_n=12,
             guidance="(derived: which public register carries this firm)"),
    FacetKey(key="aum", type=FacetType.numeric, kinds=I, label="Assets under management", unit="usd", bands=AUM_BANDS,
             guidance="(derived: regulatory AUM from Form ADV, or the sum of filed fund sizes — the card says which)"),
    FacetKey(key="funds_count", type=FacetType.numeric, kinds=I, label="Funds raised", unit="funds", bands=COUNT_BANDS,
             guidance="(derived: distinct fund vehicles attached to this firm)"),
    FacetKey(key="latest_fund_size", type=FacetType.numeric, kinds=I, label="Latest fund", unit="usd", bands=FUND_BANDS,
             guidance="(derived: amount SOLD on the newest fund filing, not the amount offered)"),
    FacetKey(key="latest_fund_year", type=FacetType.numeric, kinds=I, label="Latest fund vintage", unit="year", bands=YEAR_BANDS,
             guidance="(derived: first-sale year of the newest fund)"),
    FacetKey(key="first_fund_year", type=FacetType.numeric, kinds=I, label="First fund", unit="year", bands=YEAR_BANDS,
             guidance="(derived: first-sale year of the oldest fund we hold)"),
    FacetKey(key="still_deploying", type=FacetType.categorical, kinds=I, label="Still deploying", values=DEPLOYING,
             guidance="(derived: a new fund filed within 36 months. `quiet` means no new fund filed — never 'dead')"),
    FacetKey(key="country", type=FacetType.set, kinds=I, label="Country", top_n=15,
             guidance="lowercase code of the head-office country (us, uk, in, ae, au, sg, de, il)"),
    FacetKey(key="state", type=FacetType.set, kinds=I, label="State / region", top_n=15,
             guidance="lowercase state or province code of the head office (ca, ny, ma, tx)"),
    FacetKey(key="metro", type=FacetType.set, kinds=I, label="Metro", top_n=15,
             guidance="normalized head-office metro token (bay_area, new_york, london, bangalore, dubai, singapore)"),
    FacetKey(key="regulatory_disclosures", type=FacetType.categorical, kinds=I, label="Disclosures on file",
             values=DISCLOSURES, guidance="(derived: count of Form ADV Item 11 disclosures, linked to the official report)"),
    FacetKey(key="evidence_strength", type=FacetType.ordinal, kinds=I, label="Evidence", values=EVIDENCE,
             guidance="(derived: how many independent source kinds back this card)"),

    # ---------------- stated: the firm says so, on its own site ----------------
    FacetKey(key="stated_stage", type=FacetType.set, kinds=I, label="Stage (they say)", values=(), top_n=8,
             guidance="the stages the firm's own site says it invests at: pre_seed, seed, series_a, series_b, series_c, growth, all"),
    FacetKey(key="stated_check_min", type=FacetType.numeric, kinds=I, label="Cheque from (they say)", unit="usd", bands=CHECK_BANDS,
             guidance="the LOW end of a cheque range the firm's own page states"),
    FacetKey(key="stated_check_max", type=FacetType.numeric, kinds=I, label="Cheque to (they say)", unit="usd", bands=CHECK_BANDS,
             guidance="the HIGH end of a cheque range the firm's own page states"),
    FacetKey(key="stated_ownership", type=FacetType.numeric, kinds=I, label="Ownership target (they say)", unit="%", bands=OWNERSHIP_BANDS,
             guidance="an ownership percentage the firm's own page says it targets"),
    FacetKey(key="leads_rounds", type=FacetType.categorical, kinds=I, label="Leads or follows (they say)", values=LEADS,
             guidance="whether the firm says it LEADS rounds, follows, or both"),
    FacetKey(key="geo_focus", type=FacetType.set, kinds=I, label="Invests in (they say)", top_n=15,
             guidance="geographies the firm says it invests in, as lowercase tokens (us, europe, india, mena, sea, global)"),
    FacetKey(key="sector_focus", type=FacetType.set, kinds=I, label="Sectors (they say)", top_n=20,
             guidance="sectors the firm says it invests in, using the startup index's tech-area vocabulary"),
    FacetKey(key="open_to_inbound", type=FacetType.categorical, kinds=I, label="How to reach them", values=INBOUND,
             guidance="how the firm's own contact page says to approach: application_form, email, warm_intro_only"),

    # ---------------- observed: measured over OUR index, with a denominator ----------------
    FacetKey(key="portfolio_count", type=FacetType.numeric, kinds=I, label="Companies we hold", unit="companies",
             bands=PORTFOLIO_BANDS, guidance="(derived: distinct companies with an evidenced edge to this firm)"),
    FacetKey(key="observed_stage", type=FacetType.set, kinds=I, label="Stage (observed)", top_n=8,
             guidance="(derived: the stages of the companies we hold for this firm)"),
    FacetKey(key="observed_sector", type=FacetType.set, kinds=I, label="Sectors (observed)", top_n=20,
             guidance="(derived: the tech areas of the companies we hold for this firm)"),
    FacetKey(key="observed_geo", type=FacetType.set, kinds=I, label="Where they fund (observed)", top_n=15,
             guidance="(derived: the countries of the companies we hold for this firm)"),
    FacetKey(key="co_investor", type=FacetType.set, kinds=I, label="Co-invests with", top_n=20,
             guidance="(derived: firms appearing on the same companies)"),
    FacetKey(key="led_round_size", type=FacetType.numeric, kinds=I, label="Rounds they led", unit="usd", bands=FUND_BANDS,
             guidance="(derived: sizes of rounds this firm is STATED to have led — a round size, never a cheque size)"),
    FacetKey(key="people_count", type=FacetType.numeric, kinds=I, label="People listed", unit="people",
             bands=(("1_3", 1.0, 4.0), ("4_10", 4.0, 11.0), ("11_30", 11.0, 31.0), ("31_plus", 31.0, None)),
             guidance="(derived: how many people the firm's own team page lists)"),
    FacetKey(key="team_role", type=FacetType.set, kinds=I, label="Team includes", top_n=10,
             guidance="(derived: the roles the firm's own team page prints)"),
    FacetKey(key="lp_disclosed", type=FacetType.categorical, kinds=I, label="A public LP reports returns", values=LP_DISCLOSED,
             guidance="(derived: a public pension discloses performance for at least one of their funds)"),
    FacetKey(key="net_irr_best", type=FacetType.numeric, kinds=I, label="Best disclosed net IRR", unit="%", bands=IRR_BANDS,
             guidance="(derived: the best net IRR a named public LP reports for one of their funds, with as-of date)"),
))

# The register each key belongs to (§0). The UI groups the rail by this; the projector enforces it.
REGISTER = {
    **{k: "filed" for k in ("investor_type", "registered_with", "aum", "funds_count", "latest_fund_size",
                            "latest_fund_year", "first_fund_year", "still_deploying", "country", "state", "metro",
                            "regulatory_disclosures", "evidence_strength", "lp_disclosed", "net_irr_best")},
    **{k: "stated" for k in ("stated_stage", "stated_check_min", "stated_check_max", "stated_ownership",
                             "leads_rounds", "geo_focus", "sector_focus", "open_to_inbound")},
    **{k: "observed" for k in ("portfolio_count", "observed_stage", "observed_sector", "observed_geo",
                               "co_investor", "led_round_size", "people_count", "team_role")},
}

# One control, two registers underneath (§4): a rail control on the left key ALSO matches the right key, so a
# founder asking for seed investors need not know whether the firm says it or does it. The card reports which.
UNIFIED = {"stated_stage": "observed_stage", "sector_focus": "observed_sector", "geo_focus": "observed_geo"}

# Computed for the dossier and deliberately NOT facets — see the module docstring and §4.
DOSSIER_ONLY = ("outcome_mix", "follow_on_rate")
# Never computed for an individual, whatever the evidence (§4).
FIRM_ONLY = ("led_round_size", "regulatory_disclosures", "lp_disclosed", "net_irr_best", "aum", "funds_count")

WEIGHTS = FacetWeights(
    prefer={"investor_type": 0.15, "sector_focus": 0.12, "observed_sector": 0.12, "stated_stage": 0.12,
            "observed_stage": 0.10, "country": 0.10, "metro": 0.10, "geo_focus": 0.10, "co_investor": 0.10,
            "still_deploying": 0.10},
    avoid={"investor_type": 0.20, "country": 0.10, "sector_focus": 0.10},
    default_prefer=0.08, default_avoid=0.08, center_per_step=0.08, max_hits_per_key=3)

SCHEMA_VERSION = SCHEMA.version()

VALUE_LABELS = {
    "angel": "angel", "angel_group": "angel group", "seed_fund": "seed fund", "venture_fund": "venture fund",
    "growth_fund": "growth fund", "pe_fund": "private equity", "fund_of_funds": "fund of funds",
    "corporate_vc": "corporate VC", "family_office": "family office", "crossover_hedge": "crossover / hedge",
    "sovereign": "sovereign fund", "endowment": "endowment", "venture_debt": "venture debt", "government": "government",
    "pre_seed": "pre-seed", "series_a": "series A", "series_b": "series B", "series_c": "series C", "all": "any stage",
    "yes_recent": "raising / deploying", "quiet": "no new fund filed",
    "none_reported": "none reported", "1_2": "1–2", "3_plus": "3+",
    "under_10m": "< $10M", "10m_50m": "$10–50M", "50m_250m": "$50–250M", "250m_1b": "$250M–1B",
    "1b_10b": "$1–10B", "10b_plus": "$10B+", "1b_plus": "$1B+",
    "under_100k": "< $100k", "100k_500k": "$100–500k", "500k_2m": "$500k–2M", "2m_5m": "$2–5M",
    "5m_15m": "$5–15M", "15m_plus": "$15M+",
    "under_5": "< 5%", "5_10": "5–10%", "10_15": "10–15%", "15_20": "15–20%", "20_plus": "20%+",
    "2_3": "2–3", "4_6": "4–6", "7_plus": "7+", "1_5": "1–5", "6_20": "6–20", "21_50": "21–50",
    "51_150": "51–150", "150_plus": "150+",
    "before_2010": "before 2010", "2010_2015": "2010–15", "2016_2020": "2016–20", "2021_2023": "2021–23",
    "2024_plus": "2024+", "under_0": "negative", "0_10": "0–10%", "10_20": "10–20%",
    "sec_ria": "SEC registered adviser", "sec_era": "SEC exempt reporting adviser", "sec_formd": "SEC Form D",
    "fca": "FCA (UK)", "esma": "ESMA (EU)", "sebi": "SEBI (India)", "mas": "MAS (Singapore)",
    "asic": "ASIC (Australia)", "adgm": "ADGM (UAE)", "sbic": "SBA SBIC", "portfolio_page": "their portfolio page",
    "application_form": "open application", "email": "email them", "warm_intro_only": "intro only",
    "not_stated": "not stated", "leads": "leads rounds", "follows": "follows", "both": "leads or follows",
    "single_source": "one source", "two_sources": "two sources", "filing_backed": "filing-backed",
    "yes": "yes", "us": "US", "uk": "UK", "ae": "UAE", "in": "India", "au": "Australia", "sg": "Singapore",
    "bay_area": "Bay Area", "new_york": "New York", "london": "London", "bangalore": "Bangalore", "dubai": "Dubai",
}
KEY_ORDER = [k.key for k in SCHEMA.keys if k.navigable]


def labels() -> dict:
    """What the UI needs to render the rail: key labels, value labels, types, order, and the register of each key."""
    return {"keys": {k.key: k.label for k in SCHEMA.keys}, "values": VALUE_LABELS,
            "types": {k.key: k.type.value for k in SCHEMA.keys}, "order": KEY_ORDER,
            "units": {k.key: k.unit for k in SCHEMA.keys if k.unit},
            "register": dict(REGISTER), "unified": dict(UNIFIED), "version": SCHEMA_VERSION}
