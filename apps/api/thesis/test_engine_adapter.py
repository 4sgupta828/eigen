from __future__ import annotations

import pytest

from api.thesis.engine_adapter import make_gather, make_synthesize
from eigen_kernel.decision import Question, QuestionKind, run_question
from eigen_vertical_tech.decision import TECH_DECISION_PROFILE as P


def _q(target, pol=1, kind=QuestionKind.SEEK_SUPPORT):
    return Question(kind=kind, text="?", target=target, polarity=pol)


@pytest.mark.asyncio
async def test_gather_shares_one_retrieval_across_identical_targets():
    calls = []
    async def attack_fn(target):
        calls.append(target)
        return {"evidence": [{"id": "e1", "relation": "supports"}]}
    gather = make_gather(attack_fn)
    await gather(_q("the same target"))
    await gather(_q("the same target", pol=-1))   # different question, SAME target
    await gather(_q("a different target"))
    assert calls == ["the same target", "a different target"]   # the pair shared one attack


@pytest.mark.asyncio
async def test_gather_survives_a_failing_attack():
    async def boom(target):
        raise RuntimeError("down")
    gather = make_gather(boom)
    assert await gather(_q("t")) == []


@pytest.mark.asyncio
async def test_synthesize_grounds_and_gates_citations():
    async def llm(system, user):
        # cites one real id and one invented id in separate sentences
        return {"sentences": [
            {"text": "A filing states revenue grew.", "evidence_ids": ["e1"]},
            {"text": "Invented claim.", "evidence_ids": ["not_real"]},
        ]}
    synth = make_synthesize(llm)
    out = await synth(_q("Revenue grew."), [{"id": "e1", "quote": "revenue up", "register": "filed"}])
    assert "A filing states revenue grew." in out and "[[e:e1]]" in out
    assert "Invented claim." not in out               # dropped by the kernel gate


@pytest.mark.asyncio
async def test_synthesize_returns_empty_without_a_model_or_evidence():
    synth = make_synthesize(None)
    assert await synth(_q("t"), [{"id": "e1"}]) == ""      # no model
    synth2 = make_synthesize(lambda s, u: {"sentences": []})
    assert await synth2(_q("t"), []) == ""                 # no evidence


@pytest.mark.asyncio
async def test_engine_run_question_through_the_real_adapter_and_tech_profile():
    async def attack_fn(target):
        # two independent substantive supporting rows → the tech profile qualifies the target
        gates = {g: True for g in ("span_ok", "entailed", "on_subject", "kind_ok", "period_ok")}
        return {"evidence": [
            {"id": "a", "relation": "supports", "gate_results": gates, "evidence_kind": "verified_structured",
             "independence_key": "s1", "is_controlling": False},
            {"id": "b", "relation": "supports", "gate_results": gates, "evidence_kind": "verified_structured",
             "independence_key": "s2", "is_controlling": False}]}
    gather = make_gather(attack_fn)
    st = await run_question(gather, P, _q("The problem occurs."))
    from eigen_kernel.decision import TARGET_SUPPORTED
    assert st.target_status == TARGET_SUPPORTED
    assert set(st.evidence_ids) == {"a", "b"}
