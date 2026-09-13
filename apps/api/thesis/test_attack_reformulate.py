from __future__ import annotations
import pytest
from api.thesis import attack as atk


@pytest.mark.asyncio
async def test_reformulate_adds_angles_and_keeps_the_claim_first():
    async def llm(system, user):
        return {"queries": ["Cerebras production inference customers 2025",
                            "Cerebras vs Nvidia enterprise deployment",
                            "Cerebras revenue named customers", "Cerebras"]}  # dup of claim → deduped
    qs = await atk.reformulate(llm, claim="Cerebras", context="thesis")
    assert qs[0] == "Cerebras"                              # literal claim always leads
    assert "Cerebras production inference customers 2025" in qs
    assert len(qs) == len(set(q.lower() for q in qs))       # de-duped
    assert len(qs) <= 5


@pytest.mark.asyncio
async def test_reformulate_falls_back_to_the_literal_claim():
    assert await atk.reformulate(None, claim="X") == ["X"]
    async def boom(s, u): raise ValueError("down")
    assert await atk.reformulate(boom, claim="X") == ["X"]


def test_strong_json_absent_without_openai_key(monkeypatch):
    from api.thesis import llm as tl
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert tl.strong_json() is None                          # unconfigured → caller falls back


def test_dedupe_caps_by_publisher_not_the_web_bucket():
    from api.thesis.attack import _dedupe
    # 5 web hits, all source_key="web" but DISTINCT hosts → must keep all 5, not collapse to 2
    rows = [{"quote": f"q{i}", "source_key": "web", "independence_key": f"site{i}.com"} for i in range(5)]
    assert len(_dedupe(rows, cap=8, per_source_cap=2)) == 5
    # two hits from the SAME host → per-host cap of 2 keeps both, a third is dropped
    same = [{"quote": f"a{i}", "source_key": "web", "independence_key": "one.com"} for i in range(3)]
    assert len(_dedupe(same, cap=8, per_source_cap=2)) == 2
