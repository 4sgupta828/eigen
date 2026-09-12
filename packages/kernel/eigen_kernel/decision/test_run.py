"""The run orchestration is domain-free: it gathers via an injected seam, qualifies via the profile,
aggregates via the profile. Driven here by the toy profile + a fake gatherer — no domain, no model."""
from __future__ import annotations

import pytest

from eigen_kernel.decision import (
    Aspect, Inquiry, Question, QuestionKind,
    TARGET_SUPPORTED, TARGET_CONTRADICTED, TARGET_UNTESTED,
    ASPECT_SUPPORT, ASPECT_CONTRADICTION,
    SUPPORTED, CONTRADICTED, UNDER_TESTED, UNSETTLEABLE,
    run_question, run_aspect, run_inquiry,
)


class ToyProfile:
    def aspects(self):
        return (Aspect(key="faster", prompt="Is it faster?", critical=True),
                Aspect(key="legal", prompt="Is it allowed?", settleable="call_only", critical=True))

    def qualify(self, evidence):
        if not evidence:
            return TARGET_UNTESTED
        return TARGET_SUPPORTED if evidence[0]["side"] == "for" else TARGET_CONTRADICTED

    def aggregate_aspect(self, signals, *, critical):
        if ASPECT_CONTRADICTION in signals:
            return CONTRADICTED
        if ASPECT_SUPPORT in signals:
            return SUPPORTED
        return UNDER_TESTED


def _q(kind, pol, target="t"):
    return Question(kind=kind, text="?", target=target, polarity=pol)


@pytest.mark.asyncio
async def test_run_question_gathers_qualifies_and_synthesizes():
    async def gather(q):
        return [{"id": "e1", "side": "for"}]
    async def synth(q, ev):
        return f"grounded answer citing {ev[0]['id']}"
    st = await run_question(gather, ToyProfile(), _q(QuestionKind.SEEK_SUPPORT, 1), synth)
    assert st.target_status == TARGET_SUPPORTED
    assert st.evidence_ids == ("e1",)
    assert "e1" in st.answer


@pytest.mark.asyncio
async def test_a_failing_gather_leaves_the_question_untested_not_the_run_dead():
    async def boom(q):
        raise RuntimeError("search down")
    st = await run_question(boom, ToyProfile(), _q(QuestionKind.SEEK_SUPPORT, 1))
    assert st.target_status == TARGET_UNTESTED


@pytest.mark.asyncio
async def test_seek_contradiction_that_finds_evidence_contradicts_the_aspect():
    # a red-team question (pol -1) whose target the record CONFIRMS → the aspect is contradicted
    async def gather(q):
        return [{"id": "e2", "side": "for"}]     # the red-team target holds
    p = ToyProfile()
    verdict, statuses = await run_aspect(gather, p, p.aspects()[0],
                                         [_q(QuestionKind.SEEK_CONTRADICTION, -1)])
    assert verdict == CONTRADICTED


@pytest.mark.asyncio
async def test_call_only_aspect_with_no_findings_is_unsettleable_not_under_tested():
    async def gather(q):
        return []                                 # the record says nothing
    p = ToyProfile()
    verdict, _ = await run_aspect(gather, p, p.aspects()[1], [_q(QuestionKind.SEEK_SUPPORT, 1)])
    assert verdict == UNSETTLEABLE


@pytest.mark.asyncio
async def test_run_inquiry_covers_its_aspects():
    async def gather(q):
        return [{"id": "e", "side": "for"}]
    p = ToyProfile()
    out = await run_inquiry(gather, p, ("faster",), {"faster": [_q(QuestionKind.SEEK_SUPPORT, 1)]})
    assert out["faster"]["verdict"] == SUPPORTED
    assert len(out["faster"]["statuses"]) == 1
