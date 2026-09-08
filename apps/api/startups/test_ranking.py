"""Sorting must never hide the companies it cannot rank."""
from __future__ import annotations

from api.startups import ranking


def rows():
    return [
        {"id": "a", "score": 0.9, "numeric": {"total_disclosed_funding": 1_000_000}},
        {"id": "b", "score": 0.8, "numeric": {"total_disclosed_funding": 50_000_000}},
        {"id": "c", "score": 0.7, "numeric": {}},                       # nothing on record
        {"id": "d", "score": 0.6, "numeric": {"total_disclosed_funding": 5_000_000}},
    ]


def test_the_biggest_number_leads_and_the_unknown_stays():
    rs = rows()
    got = ranking.apply(rs, "funding")
    assert [r["id"] for r in rs] == ["b", "d", "a", "c"]
    assert got["ranked"] == 3 and got["unranked"] == 1        # the unknown is present, not dropped
    assert rs[-1]["unranked"] is True and rs[0]["rank"] == 1


def test_an_ascending_sort_reads_the_other_way():
    rs = [{"id": "a", "score": 1, "numeric": {"last_round_months": 40}},
          {"id": "b", "score": 1, "numeric": {"last_round_months": 3}},
          {"id": "c", "score": 1, "numeric": {}}]
    ranking.apply(rs, "recent_money")
    assert [r["id"] for r in rs] == ["b", "a", "c"]


def test_relevance_and_an_unknown_sort_leave_the_order_alone():
    for key in ("relevance", "", "nonsense"):
        rs = rows()
        before = [r["id"] for r in rs]
        ranking.apply(rs, key)
        assert [r["id"] for r in rs] == before


def test_a_number_on_the_company_is_used_when_the_row_has_none():
    rs = [{"id": "a", "score": 1, "numeric": {},
           "company": {"facts": [{"key": "hiring", "number": 12}]}},
          {"id": "b", "score": 1, "numeric": {"hiring": 3}}]
    ranking.apply(rs, "hiring")
    assert [r["id"] for r in rs] == ["a", "b"]


def test_there_is_no_profitability_sort():
    """We hold profit for nobody. The nearest real signals are offered under their own names."""
    assert "profitability" not in ranking.SORTS
    assert "revenue" in ranking.SORTS and "few companies file one" in ranking.SORTS["revenue"]["why"]
