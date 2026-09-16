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
        if "name the SPACE" in system or "Name the SPACE" in system or "name the" in system.lower():
            return {"space": "vertical AI search", "players": ["Acme", "Acme"]}   # dupe → deduped
        return {"cells": {"funding": {"text": "$20M Series A led by Foo", "src": 1},
                          "customers": {"text": "", "src": 1},          # empty → dropped
                          "bogus": {"text": "x", "src": 1}}}            # unknown dim → dropped
    land = await competitive.research_landscape(llm, _Web(), thesis="AI search for lawyers",
                                                subject="legal AI search", findings=[], columns=cols)
    assert land["space"] == "vertical AI search"
    assert len(land["players"]) == 1                       # deduped
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
