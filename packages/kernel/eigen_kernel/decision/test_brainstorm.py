from __future__ import annotations

import pytest

from eigen_kernel.decision import (
    compose_brainstorm, merge_memory, empty_memory, memory_context,
)
from eigen_kernel.decision.brainstorm import _history_block


@pytest.mark.asyncio
async def test_compose_brainstorm_shapes_and_filters():
    async def llm(system, user):
        assert "FULL CONTEXT" in user and "USER JUST SAID" in user
        return {
            "reply": "The buyer is RevOps, and the wedge is agent write-back.",
            "sections": [
                {"kind": "related_questions", "items": ["Who signs the contract?", "Who signs the contract?"]},
                {"kind": "gaps", "items": ["No willingness-to-pay evidence yet."]},
                {"kind": "not_a_kind", "items": ["dropped"]},
                {"kind": "adjacent_areas", "items": []},
            ],
            "directions": [
                {"kind": "experts", "label": "Find GTM experts in vertical SaaS", "query": "vertical SaaS RevOps GTM leaders"},
                {"kind": "bogus", "label": "nope", "query": "x"},
                {"kind": "media", "label": "Podcasts on agent CRM", "query": ""},
            ],
            "memory": {"summary": "Explored the buyer and wedge.", "explored": ["buyer"], "open_threads": ["pricing"]},
        }
    out = await compose_brainstorm(llm, directive="be a sharp partner", context="Thesis: agent-native CRM.",
                                   said="Who really buys this?", memory=empty_memory(), history=[])
    assert out["reply"].startswith("The buyer is RevOps")
    kinds = [s["kind"] for s in out["sections"]]
    assert kinds == ["related_questions", "gaps"]                    # unknown + empty dropped
    assert out["sections"][0]["items"] == ["Who signs the contract?"]  # de-duped
    dkinds = [d["kind"] for d in out["directions"]]
    assert dkinds == ["experts", "media"]                            # bogus kind dropped
    assert out["directions"][1]["query"] == "Podcasts on agent CRM"  # empty query falls back to label
    assert "pricing" in out["memory"]["open_threads"]


@pytest.mark.asyncio
async def test_compose_brainstorm_never_raises_on_bad_llm():
    async def bad(_s, _u):
        raise RuntimeError("boom")
    mem = {"summary": "prior", "assumptions": [], "explored": ["x"], "open_threads": ["y"]}
    out = await compose_brainstorm(bad, directive="d", context="c", said="hi", memory=mem)
    assert out["reply"] == "" and out["sections"] == [] and out["directions"] == []
    assert out["memory"]["explored"] == ["x"]                        # prior memory preserved


@pytest.mark.asyncio
async def test_empty_said_short_circuits():
    called = {"n": 0}
    async def llm(_s, _u):
        called["n"] += 1
        return {}
    out = await compose_brainstorm(llm, directive="d", context="c", said="   ")
    assert called["n"] == 0 and out["reply"] == ""


def test_merge_memory_unions_and_caps():
    prior = {"summary": "old", "assumptions": ["a1"], "explored": ["e1"], "open_threads": ["o1"]}
    upd = {"summary": "new", "assumptions": ["a1", "a2"], "explored": ["e2"], "open_threads": []}
    m = merge_memory(prior, upd)
    assert m["summary"] == "new"
    assert m["assumptions"] == ["a1", "a2"]                          # union, de-duped
    assert set(m["explored"]) == {"e1", "e2"}
    assert m["open_threads"] == ["o1"]                               # prior kept when update empty


def test_memory_context_and_history_render():
    ctx = memory_context({"summary": "s", "open_threads": ["ot"], "explored": ["ex"], "assumptions": ["as"]})
    assert "WHERE THIS BRAINSTORM STANDS" in ctx and "STILL OPEN" in ctx
    h = _history_block([{"role": "user", "text": "q"}, {"role": "agent", "text": "a"}])
    assert "You: q" in h and "Eigen: a" in h
