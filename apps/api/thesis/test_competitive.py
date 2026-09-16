from __future__ import annotations

import pytest

from api.thesis import competitive


class _Hit:
    def __init__(self, url, title, body):
        self.url, self.title, self.highlights, self.snippet, self.body = url, title, (), "", body


class _Web:
    async def search(self, query, max_results=6, open_web=True):
        return [_Hit("https://ex.com/a", "Acme raises $20M", "Acme is a vertical AI search tool, $20M Series A led by Foo.")]


@pytest.mark.asyncio
async def test_research_landscape_identifies_players_and_grounds_cells():
    cols = [{"key": "funding", "label": "Funding"}, {"key": "customers", "label": "Customers"}]
    async def llm(system, user):
        s = system.lower()
        if "focused market" in s and "queries" in s:              # _focus_queries
            return {"focus": "vertical AI search for lawyers", "queries": ["ai legal search competitors"]}
        if "mapping one focused market" in s:                     # _identify_players (direct-first)
            return {"players": [{"name": "Acme", "kind": "direct"},
                                {"name": "Acme", "kind": "direct"},          # dupe → deduped
                                {"name": "FarAway", "kind": "adjacent"}]}
        return {"cells": {"funding": {"text": "$20M Series A led by Foo", "src": 1},
                          "customers": {"text": "", "src": 1},          # empty → dropped
                          "bogus": {"text": "x", "src": 1}}}            # unknown dim → dropped
    land = await competitive.research_landscape(llm, _Web(), thesis="AI search for lawyers",
                                                subject="legal AI search", findings=[], columns=cols)
    assert land["space"] == "vertical AI search for lawyers"          # the focus is the market label
    names = [p["name"] for p in land["players"]]
    assert names[0] == "Acme"                              # direct first
    assert names.count("Acme") == 1                        # deduped
    p = land["players"][0]
    assert p["name"] == "Acme" and p["is_subject"] is False
    assert p["cells"]["funding"]["text"].startswith("$20M")
    assert p["cells"]["funding"]["source_url"] == "https://ex.com/a"   # grounded to the source
    assert "customers" not in p["cells"] and "bogus" not in p["cells"] # empty + unknown dropped


@pytest.mark.asyncio
async def test_research_landscape_is_safe_without_a_model_or_web():
    land = await competitive.research_landscape(None, None, thesis="t", subject="s", findings=[],
                                                columns=[{"key": "funding", "label": "F"}])
    assert land["empty"] is True and land["players"] == []
