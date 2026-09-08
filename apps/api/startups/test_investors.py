"""Resolving an investor must never point at a different company."""
from __future__ import annotations

from api.startups.sources.investors import display_name, name_matches, resolve


def test_the_name_gate_rejects_the_confident_wrong_answers():
    # each of these is what the ungated lookup actually returned
    assert not name_matches("gfc", "GF Securities")
    assert not name_matches("8vc", "Virginia's Community Colleges")
    assert not name_matches("accel", "Accela")            # a prefix of the STRING, not of the words
    # …while still allowing a firm that spells itself out
    assert name_matches("bessemer", "Bessemer Venture Partners")
    assert name_matches("slow_ventures", "Slow Ventures")
    assert name_matches("khosla_ventures", "Khosla Ventures")


def test_a_slug_reads_as_a_name():
    assert display_name("slow_ventures") == "Slow Ventures"
    assert display_name("8vc") == "8vc"                   # digits mean we cannot case it safely
    assert display_name("general_catalyst") == "General Catalyst"


def test_a_fund_whose_portfolio_we_crawl_needs_no_lookup():
    r = resolve("a16z")
    assert r and r["basis"] == "portfolio_page" and r["site"].startswith("https://a16z.com")


def test_a_single_token_never_resolves_by_lookup():
    """Run over the real index, one-word slugs produced AVP Beach Volleyball for 'avp', Bond
    Collective for 'bond', Town & Country for 'town' and a Dutch news site for 'gfc'. Some one-word
    slugs were right, and nothing in the answer distinguished them, so none are accepted."""
    for slug in ("avp", "bond", "town", "gfc", "wing", "zoom", "nba"):
        assert resolve(slug) is None, slug


def test_a_multi_word_name_may_resolve():
    r = resolve("slow_ventures")
    assert r is None or (r["site"].startswith("http") and r["basis"] in ("name_lookup", "portfolio_page"))
