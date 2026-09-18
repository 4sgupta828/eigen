from __future__ import annotations
import pytest
from api.thesis import voices as v


@pytest.mark.asyncio
async def test_organize_voices_buckets_prunes_and_maps_ids():
    cands = [{"id": "a", "kind": "podcast", "title": "Buyer economics", "snippet": "who signs"},
             {"id": "b", "kind": "essay", "title": "GTM motion", "snippet": "land expand"},
             {"id": "c", "kind": "blog", "title": "Unrelated crypto", "snippet": "coins"}]
    async def llm(system, user):
        assert "CANDIDATE PIECES" in user
        return {"buckets": [
            {"label": "Speaks to willingness-to-pay", "items": [{"i": 0, "why": "covers the buyer"}]},
            {"label": "How operators run GTM", "items": [{"i": 1, "why": "land-and-expand"}, {"i": 9, "why": "bad idx"}]},
            {"label": "Empty bucket", "items": [{"i": 0, "why": "dup already used"}]},
        ]}
    out = await v.organize_voices(llm, directive="d", context="THESIS: x", candidates=cands)
    labels = [b["label"] for b in out["buckets"]]
    # the two model buckets, then a catch-all for whatever it didn't place (nothing retrieved is lost)
    assert labels == ["Speaks to willingness-to-pay", "How operators run GTM", "More voices in this space"]
    assert out["buckets"][0]["items"] == [{"id": "a", "why": "covers the buyer"}]
    assert out["buckets"][1]["items"] == [{"id": "b", "why": "land-and-expand"}]  # bad index 9 dropped
    assert out["buckets"][2]["items"] == [{"id": "c", "why": ""}]                 # unplaced → catch-all


@pytest.mark.asyncio
async def test_organize_voices_never_raises():
    async def boom(_s, _u):
        raise RuntimeError("x")
    out = await v.organize_voices(boom, directive="d", context="c", candidates=[{"id": "a"}])
    assert out == {"buckets": []}
    assert await v.organize_voices(None, directive="d", context="c", candidates=[{"id": "a"}]) == {"buckets": []}


def test_thesis_context_includes_lines():
    doc = {"thesis": "Sales teams will pay.", "subject": {"seg": "sales"},
           "collective_take": {"bottom_line": {"text": "Leans fund."}}}
    qs = [{"inquiry_name": "GTM motion"}, {"inquiry_name": "GTM motion"}, {"inquiry_name": "Moat"}]
    ctx = v.thesis_context(doc, qs)
    assert "LINES OF INVESTIGATION: GTM motion; Moat" in ctx and "HOW IT LEANS: Leans fund." in ctx
