"""Grouping a startup result set: free dimensions, and what the model is not allowed to reach for."""
from __future__ import annotations

from api.startups.grouping import (GROUP_DIMENSIONS, row_line, segment_prompt, values_for)


def test_funding_and_age_fall_into_bands_a_reader_thinks_in():
    row = {"numeric": {"total_disclosed_funding": 12_000_000, "founded": 2019}}
    assert values_for(row, "derived:funding_band", this_year=2026) == ["$5M–20M"]
    assert values_for(row, "derived:age_band", this_year=2026) == ["5–10 years"]


def test_a_company_with_nothing_on_record_is_not_guessed_into_a_band():
    assert values_for({"numeric": {}}, "derived:funding_band", this_year=2026) == []
    assert values_for({"numeric": {"founded": 0}}, "derived:age_band", this_year=2026) == []


def test_a_facet_dimension_reads_the_row_it_is_given():
    row = {"facets": {"tech_area": ["ai_infra", "fintech"]}}
    assert values_for(row, "facet:tech_area", this_year=2026) == ["ai_infra", "fintech"]


def test_the_model_is_shown_what_they_do_and_nothing_it_could_group_by_free():
    row = {"id": "acme.com", "facets": {"stage": ["seed"], "metro": ["bay_area"], "investor": ["a16z"]},
           "company": {"name": "Acme", "one_liner": "Inference gateway for banks", "hq": "San Francisco"}}
    line = row_line(3, row)
    assert line.startswith("3| Acme")
    assert "Inference gateway for banks" in line
    for leaked in ("seed", "bay_area", "a16z", "San Francisco"):
        assert leaked not in line          # the facet controls already group by these, for free


def test_the_prompt_forbids_the_free_dimensions_and_the_query_word():
    p = segment_prompt()
    for forbidden in ("funding stage", "city", "investor", "accelerator", "company size"):
        assert forbidden in p
    assert "that word is the search itself" in p


def test_auto_leads_the_menu_and_every_dimension_declares_its_kind():
    assert GROUP_DIMENSIONS[0][0] == "auto"
    for key, label, source, kind in GROUP_DIMENSIONS:
        assert label and kind in ("auto", "categorical", "identity")
        assert kind == "auto" or source.startswith(("facet:", "derived:"))


def test_the_menu_only_offers_a_dimension_that_organises_these_rows():
    """Eligibility is judged on the rows in front of the reader, not on the index. A dimension where
    almost nothing is stated, or where one value swallows the set, is hidden rather than offered
    as a junk drawer."""
    from eigen_kernel.facets.grouping import eligible
    balanced = ["ai_infra"] * 4 + ["fintech"] * 3 + ["bio_health"] * 3
    assert eligible(balanced, kind="categorical").ok

    one_swallows = ["ai_infra"] * 9 + ["fintech"]
    assert not eligible(one_swallows, kind="categorical").ok

    mostly_unknown = ["ai_infra", "fintech"] + [""] * 8
    assert not eligible(mostly_unknown, kind="categorical").ok


def test_a_proposed_segmentation_is_made_safe_before_it_is_shown():
    from eigen_kernel.facets.grouping import enforce
    proposed = [{"name": "Developer infrastructure", "why": "tools for engineers", "ids": [0, 1, 2]},
                {"name": "Overlap", "why": "", "ids": [2, 3]},          # 2 is already taken
                {"name": "Tiny", "why": "", "ids": [4]},                 # below min_size
                {"name": "Bad ids", "why": "", "ids": [99, 100]}]
    groups, leftovers, notes = enforce(proposed, 6)
    names = [g.name for g in groups]
    assert "Developer infrastructure" in names
    assert "Tiny" not in names                       # a group of one is not a group
    assert all(len(set(g.ids)) == len(g.ids) for g in groups)
    assert 2 in groups[0].ids and all(2 not in g.ids for g in groups[1:])   # single membership
    assert any("99" in n for n in notes)             # an id outside the set is reported, not silently kept


def test_the_thresholds_fit_this_index_not_a_dense_one():
    """Measured on a real 60-row result set: 'what they build' was hidden for having 9 groups against
    a limit of 8, and 'where they are' for 27% unstated against a limit of 25%. Both are useful cuts
    and both were lost on a technicality."""
    from eigen_kernel.facets.grouping import eligible
    nine_groups = [f"area{i%9}" for i in range(54)] + [""] * 6
    assert not eligible(nine_groups, kind="categorical").ok                       # the old limit
    assert eligible(nine_groups, kind="categorical", max_unstated=0.60, max_groups=12).ok

    quarter_unknown = ["bay_area"] * 20 + ["new_york"] * 12 + ["london"] * 12 + [""] * 16
    assert not eligible(quarter_unknown, kind="identity").ok
    assert eligible(quarter_unknown, kind="identity", max_unstated=0.60, max_groups=12).ok


def test_what_stays_strict_is_the_rule_that_matters():
    """A dimension where one value swallows the set organises nothing, however much is stated."""
    from eigen_kernel.facets.grouping import eligible
    swallowed = ["yc"] * 55 + ["techstars"] * 5
    assert not eligible(swallowed, kind="categorical", max_unstated=0.60, max_groups=12).ok
    almost_nothing = ["saas"] * 6 + [""] * 54
    assert not eligible(almost_nothing, kind="categorical", max_unstated=0.60, max_groups=12).ok
