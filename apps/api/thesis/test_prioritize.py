from __future__ import annotations

import pytest

from api.thesis import prioritize


class _P:
    """Toy profile: two critical corpus aspects, one non-critical, one call_only."""
    def aspects(self):
        from types import SimpleNamespace as NS
        return (NS(key="problem", critical=True, settleable="corpus"),
                NS(key="moat", critical=True, settleable="corpus"),
                NS(key="catalyst", critical=False, settleable="corpus"),
                NS(key="wtp", critical=True, settleable="call_only"))


def _q(qid, aspect, kind, answered=False):
    return {"id": qid, "aspect_key": aspect, "kind": kind, "text": f"q {qid}",
            "target_status": "target_supported" if answered else ""}


@pytest.mark.asyncio
async def test_subset_excludes_call_only_and_answered_and_keeps_a_coverage_floor():
    rows = [_q("a", "problem", "seek_support"), _q("b", "problem", "seek_contradiction"),
            _q("c", "moat", "seek_support"), _q("d", "catalyst", "seek_support"),
            _q("e", "wtp", "seek_support"),                 # call_only → excluded
            _q("f", "problem", "seek_support", answered=True)]  # already answered → excluded
    got = await prioritize.select_subset(_P(), rows, thesis="T", llm_json=None, cap=2)
    ids = {q["id"] for q in got}
    assert "e" not in ids and "f" not in ids                # call_only + answered excluded
    # cap=2 keeps the 2 highest, but the coverage floor pulls in BOTH critical aspects (problem, moat)
    assert "c" in ids                                        # moat (critical) kept by the floor
    assert any(q["aspect_key"] == "problem" for q in got)   # problem (critical) covered


@pytest.mark.asyncio
async def test_deterministic_order_prefers_disconfirming_lens_on_critical_aspects():
    rows = [_q("sup", "problem", "seek_support"), _q("con", "problem", "seek_contradiction"),
            _q("cat", "catalyst", "seek_support")]
    got = await prioritize.select_subset(_P(), rows, thesis="T", llm_json=None, cap=1)
    # cap=1 → the single top pick is the disconfirming probe on the critical aspect; the floor then adds
    # the other critical aspect if any (none here besides problem), never the non-critical catalyst first.
    assert got[0]["id"] == "con"


@pytest.mark.asyncio
async def test_llm_rank_is_used_when_present_then_falls_back():
    rows = [_q("x", "problem", "seek_support"), _q("y", "moat", "seek_support")]
    async def llm(_s, _u): return {"ranked_ids": ["y", "x"]}
    got = await prioritize.select_subset(_P(), rows, thesis="T", llm_json=llm, cap=2)
    assert [q["id"] for q in got][:2] == ["y", "x"]         # LLM order honored
    async def boom(_s, _u): raise ValueError("x")
    got2 = await prioritize.select_subset(_P(), rows, thesis="T", llm_json=boom, cap=2)
    assert {q["id"] for q in got2} == {"x", "y"}            # fallback still returns the set
