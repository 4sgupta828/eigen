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
async def test_synthesize_returns_empty_only_without_a_model():
    synth = make_synthesize(None)
    assert await synth(_q("t"), [{"id": "e1"}]) == ""      # no model → no prose (verdict stands alone)


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


@pytest.mark.asyncio
async def test_synthesize_always_explains_never_bare_not_established():
    # model finds nothing citable but explains the gap in `note` → the note is the answer
    async def llm(system, user):
        return {"sentences": [], "note": "The record has only market-signal coverage; a filed figure "
                "would be needed to settle it."}
    synth = make_synthesize(llm)
    out = await synth(_q("Do enough buyers exist?"), [{"id": "e1", "quote": "q"}])
    assert "market-signal coverage" in out
    assert out != "Not established in the record."
    assert "[[e:" not in out                       # a gap note carries no citations


@pytest.mark.asyncio
async def test_synthesize_appends_caveat_to_a_cited_answer():
    async def llm(system, user):
        return {"sentences": [{"text": "Two vendors report 40% adoption.", "evidence_ids": ["e1"]}],
                "note": "No filing confirms the figure."}
    synth = make_synthesize(llm)
    out = await synth(_q("Adoption?"), [{"id": "e1", "quote": "q"}])
    assert "Two vendors report 40% adoption." in out and "[[e:e1]]" in out
    assert "No filing confirms the figure." in out   # the caveat rides along


@pytest.mark.asyncio
async def test_synthesize_no_evidence_still_explains():
    async def llm(s, u):
        return {"sentences": [], "note": "x"}
    synth = make_synthesize(llm)
    out = await synth(_q("t"), [])                    # no evidence at all
    assert "search returned nothing" in out.lower() or "needed to settle" in out.lower()


@pytest.mark.asyncio
async def test_uncited_sentences_are_recovered_by_content_not_dropped():
    # The model writes a real, specific finding but forgets evidence_ids. Recovery binds it to the
    # source that contains its distinctive tokens, so the grounded answer survives instead of
    # collapsing to "not established".
    async def llm(system, user):
        return {"sentences": [
            {"text": "OpenAI runs GPT-5.6 inference on Cerebras WSE-3 at 750 tokens per second.",
             "evidence_ids": None},                                     # forgotten citation
            {"text": "A vague unsupported aside about the weather.", "evidence_ids": None}],  # binds to nothing
            "note": ""}
    ev = [{"id": "e1", "block_text": "Report: OpenAI deployed GPT-5.6 on Cerebras WSE-3 hitting 750 tokens/sec in production."},
          {"id": "e2", "block_text": "Unrelated filing about quarterly revenue of 12 million dollars."}]
    synth = make_synthesize(llm)
    out = await synth(_q("Are customers switching?"), ev)
    assert "750 tokens per second" in out                              # the real finding is kept
    assert "[[e:e1]]" in out                                           # bound to the right source
    assert "weather" not in out                                        # the unbindable aside is dropped


def test_recover_citations_requires_a_real_content_match():
    from api.thesis.engine_adapter import _recover_citations
    ev = [{"id": "e1", "block_text": "Cerebras posted 750 tokens per second on WSE-3."}]
    # a number match binds
    got = _recover_citations([{"text": "Throughput reached 750 tokens/sec.", "evidence_ids": []}], ev)
    assert got[0]["evidence_ids"] == ["e1"]
    # a sentence sharing no distinctive token binds to nothing and is dropped (never enters uncited)
    got2 = _recover_citations([{"text": "The team is optimistic about the future.", "evidence_ids": []}], ev)
    assert got2 == []
    # an already-cited sentence is left untouched
    got3 = _recover_citations([{"text": "x", "evidence_ids": ["e9"]}], ev)
    assert got3[0]["evidence_ids"] == ["e9"]
