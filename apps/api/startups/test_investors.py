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
