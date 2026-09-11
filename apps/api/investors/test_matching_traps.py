"""The five traps from docs/specs/investor-matching.md §8.

Each is built to PASS a naive matcher while being wrong for the founder. They are written against
`reasons_for` / `penalties_for` directly, because the ranking is where each of these is decided.
"""
from api.investors.advise import (WEIGHTS, axes_with_evidence, conflicts_for,
                                  penalties_for, reasons_for, recency_multiplier)

NOW = 2026


def row(**facets):
    """A search row as store.hydrate builds it: facet values, numbers, and the denominators that say
    what an observed fact was measured over."""
    num = facets.pop("_num", {})
    den = facets.pop("_den", {})
    return {"id": facets.pop("_id", "f1"), "facets": {k: v for k, v in facets.items()},
            "numeric": num, "denom": den}


def fit(r, **kw):
    kw.setdefault("stage", ""); kw.setdefault("sectors", []); kw.setdefault("geo", [])
    kw.setdefault("co_investors", [])
    return reasons_for(r, now_year=NOW, **kw)[1]


# ── 1. The everything-fund ────────────────────────────────────────────────────────────────────
def test_a_generalist_that_only_filed_recently_loses_to_a_sector_specialist():
    """`still_deploying` used to weigh 1.0 — more than sector at 0.9 — so the firm that had merely
    filed a fund outranked the one that actually invests in the founder's sector."""
    generalist = row(still_deploying=["yes_recent"], _num={"latest_fund_year": 2026})
    specialist = row(observed_sector=["climate_energy"], _num={"latest_fund_year": 2024},
                     _den={"observed_sector": 12})
    assert fit(specialist, sectors=["climate_energy"]) > fit(generalist, sectors=["climate_energy"])


def test_recency_alone_scores_nothing():
    r = row(still_deploying=["yes_recent"], _num={"latest_fund_year": 2026})
    assert fit(r, sectors=["fintech"]) == 0.0, "being alive is not a reason to email someone"


def test_a_niche_fund_outranks_a_mega_fund_on_the_same_hit():
    """Concentration, not accumulation: 5 of 12 is a thesis, 5 of 900 is a rounding error."""
    niche = row(observed_sector=["climate_energy"], _num={"latest_fund_year": 2025}, _den={"observed_sector": 12})
    mega  = row(observed_sector=["climate_energy"], _num={"latest_fund_year": 2025}, _den={"observed_sector": 900})
    assert fit(niche, sectors=["climate_energy"]) > fit(mega, sectors=["climate_energy"])


# ── 2. The stated-vs-observed liar ────────────────────────────────────────────────────────────
def test_saying_you_do_seed_never_outranks_being_seen_doing_it():
    says = row(stated_stage=["seed"], _num={"latest_fund_year": 2025})
    does = row(observed_stage=["seed"], _num={"latest_fund_year": 2025})
    assert fit(does, stage="seed") > fit(says, stage="seed")
    assert WEIGHTS["stage_stated"] < WEIGHTS["stage_observed"]


def test_a_stated_sector_is_worth_less_than_a_funded_one():
    says = row(sector_focus=["ai_infra"], _num={"latest_fund_year": 2025})
    does = row(observed_sector=["ai_infra"], _num={"latest_fund_year": 2025}, _den={"observed_sector": 20})
    assert fit(does, sectors=["ai_infra"]) > fit(says, sectors=["ai_infra"])


# ── 3. The competitor trap ────────────────────────────────────────────────────────────────────
def test_a_fund_that_already_backs_your_competitor_is_pushed_down():
    """Superficially the single best match — same sector, funded it already — and the one firm a
    founder must not email first. conflicts_for only ever attached a warning."""
    portfolio = [{"id": "rival.com", "name": "Rival"}]
    conflicts = conflicts_for(portfolio, ["fintech"], {"rival.com": ["fintech"]})
    assert conflicts, "a portfolio company in the founder's own sector is a conflict"
    penalty, notes = penalties_for(row(_num={"latest_fund_year": 2026}), conflicts=conflicts)
    assert penalty > WEIGHTS["sector"], "the penalty must outweigh the sector match that attracted them"
    assert any("competitor" in n or "your sector" in n for n in notes)


def test_no_conflict_means_no_penalty():
    penalty, notes = penalties_for(row(_num={"latest_fund_year": 2026}), conflicts=[])
    assert penalty == 0.0 and notes == []


# ── 4. The zombie ─────────────────────────────────────────────────────────────────────────────
def test_a_dormant_fund_loses_to_a_live_one_with_a_weaker_match():
    live   = row(observed_sector=["devtools"], _num={"latest_fund_year": 2026}, _den={"observed_sector": 40})
    zombie = row(observed_sector=["devtools"], observed_stage=["seed"], observed_geo=["us"],
                 _num={"latest_fund_year": 2016}, _den={"observed_sector": 10})
    assert fit(live, sectors=["devtools"]) > fit(zombie, sectors=["devtools"], stage="seed", geo=["us"]), \
        "a perfect history at a fund that stopped writing cheques is not a match"


def test_a_dormant_fund_says_so():
    _, notes = penalties_for(row(_num={"latest_fund_year": 2016}), conflicts=[])
    assert any("2016" in n for n in notes), "state the year rather than silently demoting"


def test_never_filing_is_treated_as_dormant_not_as_fine():
    assert recency_multiplier(None, NOW) == recency_multiplier(2016, NOW)


# ── 5. The thin firm ──────────────────────────────────────────────────────────────────────────
def test_a_firm_we_know_nothing_about_cannot_look_like_a_sector_match():
    thin = row(still_deploying=["yes_recent"], _num={"latest_fund_year": 2026, "aum": 900_000_000})
    why, _ = reasons_for(thin, stage="seed", sectors=["fintech"], geo=["us"], co_investors=[], now_year=NOW)
    assert axes_with_evidence(why) == [], "AUM is not a reason; the axes we matched on must read empty"


def test_the_axes_we_matched_on_are_reported():
    r = row(observed_sector=["fintech"], observed_stage=["seed"], _num={"latest_fund_year": 2026})
    why, _ = reasons_for(r, stage="seed", sectors=["fintech"], geo=[], co_investors=[], now_year=NOW)
    assert axes_with_evidence(why) == ["sector", "stage"]


# ── the cheque-size anti-signal (filed data, so cheap and certain) ─────────────────────────────
def test_a_fund_whose_minimum_dwarfs_the_round_is_demoted():
    r = row(_num={"latest_fund_year": 2026, "min_investment": 50_000_000})
    penalty, notes = penalties_for(r, conflicts=[], raise_target=750_000)
    assert penalty > 0 and any("minimum cheque" in n for n in notes)


def test_a_sensible_cheque_is_not_penalised():
    r = row(_num={"latest_fund_year": 2026, "min_investment": 1_000_000})
    penalty, _ = penalties_for(r, conflicts=[], raise_target=3_000_000)
    assert penalty == 0.0


# ── round behaviour: the two questions the spec's scenarios exposed (§10, §11) ─────────────────
def behav(fid="f1", follows=0, firsts=0, **facets):
    r = row(_id=fid, **facets)
    r["behaviour"] = {"follows_on": follows, "first_round": firsts}
    return r


def test_a_firm_that_follows_your_backers_outranks_a_bare_sector_match():
    """'Who leads the A after a seed led by Amplify' is the question at every stage above pre-seed,
    and it was unanswerable: both firms scored on sector alone. It is a join over iv_edge rows we
    already hold — same company, later date, different firm."""
    follower = behav(follows=4, observed_sector=["devtools"],
                     _num={"latest_fund_year": 2026}, _den={"observed_sector": 30})
    plain    = behav(observed_sector=["devtools"],
                     _num={"latest_fund_year": 2026}, _den={"observed_sector": 30})
    ask = dict(sectors=["devtools"], co_investors=["amplify"])
    assert fit(follower, **ask) > fit(plain, **ask)


def test_following_more_often_ranks_higher():
    a = behav(follows=6, observed_sector=["devtools"], _num={"latest_fund_year": 2026})
    b = behav(follows=1, observed_sector=["devtools"], _num={"latest_fund_year": 2026})
    ask = dict(sectors=["devtools"], co_investors=["amplify"])
    assert fit(a, **ask) > fit(b, **ask)


def test_a_founder_with_no_cap_table_gets_first_round_behaviour_instead():
    """co_investor is structurally unavailable to anyone who has never raised — which is the founder
    this feature is for. Writing first institutional cheques is the closest thing we can SEE."""
    first = behav(firsts=22, observed_sector=["enterprise_saas"],
                  _num={"latest_fund_year": 2026}, _den={"observed_sector": 50})
    plain = behav(observed_sector=["enterprise_saas"],
                  _num={"latest_fund_year": 2026}, _den={"observed_sector": 50})
    ask = dict(sectors=["enterprise_saas"], co_investors=[])
    assert fit(first, **ask) > fit(plain, **ask)


def test_first_round_behaviour_is_suppressed_once_there_are_backers_to_follow():
    # For a founder with a cap table, "they write first cheques" is noise beside "they followed yours".
    r = behav(firsts=22, observed_sector=["devtools"], _num={"latest_fund_year": 2026})
    why, _ = reasons_for(r, stage="", sectors=["devtools"], geo=[], co_investors=["amplify"], now_year=NOW)
    assert "first_round" not in axes_with_evidence(why)


def test_behaviour_axes_still_lose_to_a_dormant_multiplier():
    # Round behaviour is history. A fund that stopped writing cheques in 2016 has plenty of it.
    live   = behav(observed_sector=["devtools"], _num={"latest_fund_year": 2026})
    zombie = behav(follows=8, observed_sector=["devtools"], _num={"latest_fund_year": 2016})
    ask = dict(sectors=["devtools"], co_investors=["amplify"])
    assert fit(live, **ask) > fit(zombie, **ask)


# ── the coverage bias a non-US founder is otherwise never told about (§11) ─────────────────────
from api.investors.advise import coverage_bias_note


def test_a_non_us_search_says_the_index_is_a_us_register():
    """Form ADV is a US filing system, so a London founder searching UK seed funds gets a US-skewed
    list that LOOKS complete. Silence about that is the difference between a coverage limit and a
    misleading answer."""
    n = coverage_bias_note(["uk"])
    assert "SEC adviser registers" in n and "UK" in n
    assert "not a finding about" in n, "must name it as our limit, not a fact about the market"


def test_a_us_search_is_not_warned():
    assert coverage_bias_note(["us"]) == ""
    assert coverage_bias_note([]) == ""


def test_a_mixed_search_warns_about_the_non_us_part_only():
    # The warned REGION is IN; "US" still appears in the prose explaining why, which is correct.
    n = coverage_bias_note(["us", "in"])
    assert "Firms in IN appear" in n
    assert "Firms in IN, US" not in n and "Firms in US" not in n
