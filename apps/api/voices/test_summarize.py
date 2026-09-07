"""The summary gates. A summary is a convenience; a fabricated one is a liability."""
from __future__ import annotations

import asyncio

from api.voices import summarize as S

TEXT = ("We priced our seed round too high in 2021 and it cost the company a full year of runway. "
        "The mistake was believing the headline valuation mattered more than the partner. "
        "We raised $4M at a $40M post and the next round had to clear that bar in a worse market. "
        "Eventually we raised a flat round at half the dilution and the company survived.")


def test_a_figure_the_piece_never_states_is_dropped():
    good = "They raised $4M at a $40M post-money valuation."
    bad = "The company grew revenue 300% in the year after the round."
    kept = S.verify([good, bad], TEXT)
    assert kept == [good]                       # the invented 300% does not survive


def test_a_point_with_no_figures_passes():
    p = "The author argues a high price sets a bar the next round must clear."
    assert S.verify([p], TEXT) == [p]


def test_no_model_still_produces_a_panel_and_says_where_it_came_from():
    out = asyncio.run(S.summarize(title="Seed pricing", author="Fred Wilson", text=TEXT,
                                  is_chapter=False, llm_json=None))
    assert out["basis"] == "extractive" and len(out["points"]) >= 3
    assert "no model was available" in out["note"]
    assert all(p in TEXT for p in out["points"])       # the piece's own sentences, not new prose


def test_a_model_outage_degrades_instead_of_failing():
    async def broken(system, user):
        raise RuntimeError("credit_balance_exhausted")
    out = asyncio.run(S.summarize(title="t", author="a", text=TEXT, is_chapter=False, llm_json=broken))
    assert out["basis"] == "extractive" and "No model available" in out["note"]


def test_an_episode_is_summarised_by_its_own_chapter_list_and_never_quoted():
    md = ("[00:00:00] Cold open — https://s.fm/1?t=0\n"
          "[00:02:25] How the first product died — https://s.fm/1?t=145\n"
          "[00:13:00] Why the Series A nearly killed us — https://s.fm/1?t=780\n")
    out = asyncio.run(S.summarize(title="ep", author="", text=md, is_chapter=True, llm_json=None))
    assert out["basis"] == "chapters"
    assert "Why the Series A nearly killed us" in out["points"]
    assert "Nothing here is a quotation" in out["note"]
    assert all("http" not in p for p in out["points"])   # the link never leaks into the words


def test_a_model_summary_is_labelled_as_one():
    async def fake(system, user):
        return {"heading": "Seed pricing", "points": ["A high price sets a bar the next round must clear."]}
    out = asyncio.run(S.summarize(title="t", author="Fred Wilson", text=TEXT, is_chapter=False,
                                  llm_json=fake))
    assert out["basis"] == "model" and out["heading"] == "Seed pricing"
    assert "by Fred Wilson" in out["note"]
