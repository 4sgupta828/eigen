"""The decision engine is domain-free — proven by driving it with a TOY, non-tech profile. If the
engine needed any tech vocabulary, this fixture could not exist. It is the litmus for §14."""
from __future__ import annotations

import pytest

from eigen_kernel.decision import (
    QuestionKind, Question, QuestionStatus, Aspect, Inquiry,
    TARGET_SUPPORTED, TARGET_CONTRADICTED, TARGET_UNTESTED,
    ASPECT_SUPPORT, ASPECT_CONTRADICTION, ASPECT_NONE,
    SUPPORTED, CONTRADICTED, UNDER_TESTED,
    generate_questions, required_kinds_covered, resolve_signal, aggregate_aspect,
    DecisionProfile,
)


class ToyProfile:
    """A deliberately non-technology decision profile: 'should we take the coastal route?'. Nothing here
    (or in the kernel it drives) names a domain the kernel would have to know."""
    def aspects(self):
        return (Aspect(key="faster", prompt="Is the coastal route faster?", critical=True),
                Aspect(key="scenic", prompt="Is the coastal route more scenic?"))

    def inquiries(self):
        return (Inquiry(key="trip", name="The trip", framing="time and views",
                        aspect_keys=("faster", "scenic")),)

    def question_directive(self, aspect, decision):
        return "You help decide a route."

    def qualify(self, evidence):
        # a toy rule: any evidence at all qualifies; empty → untested
        if not evidence:
            return TARGET_UNTESTED
        return TARGET_SUPPORTED if evidence[0].get("side") == "for" else TARGET_CONTRADICTED

    def aggregate_aspect(self, signals, *, critical):
        if ASPECT_CONTRADICTION in signals:
            return CONTRADICTED
        if ASPECT_SUPPORT in signals:
            return SUPPORTED
        return UNDER_TESTED


def test_toy_profile_satisfies_the_protocol():
    assert isinstance(ToyProfile(), DecisionProfile)   # structural: the seam is real, domain-free


@pytest.mark.asyncio
async def test_generation_falls_open_to_a_single_seek_support_with_no_model():
    a = ToyProfile().aspects()[0]
    qs = await generate_questions(None, aspect=a, decision="coastal vs inland", directive="x")
    # honest degraded mode: one seek-support on the canonical proposition — NOT a fabricated red-team
    assert len(qs) == 1 and qs[0].kind == QuestionKind.SEEK_SUPPORT
    assert not required_kinds_covered(qs)              # thin coverage, reported honestly
    assert all(q.target for q in qs)


@pytest.mark.asyncio
async def test_model_questions_are_coverage_gated_and_capped():
    async def llm(_sys, _user):
        # model returns only one lens and an unknown kind and a bad row
        return {"questions": [
            {"kind": "seek_support", "text": "Is it faster on weekdays?", "target": "It is faster on weekdays.", "polarity": 1},
            {"kind": "not_a_kind", "text": "junk", "target": "junk"},
            {"kind": "resolve_ambiguity", "text": "Faster by distance or by time?", "target": "It is faster by time.", "polarity": 1},
            {"kind": "no_target", "text": "missing target"},
        ]}
    a = ToyProfile().aspects()[0]
    qs = await generate_questions(llm, aspect=a, decision="d", directive="x")
    # the model omitted seek_contradiction; we do NOT fabricate one — the gate reports under-coverage
    assert not required_kinds_covered(qs)
    assert len(qs) <= 4 and len(qs) >= 2               # the two valid model questions survived, junk dropped
    assert all(isinstance(q.kind, QuestionKind) for q in qs)


def test_polarity_resolution_is_generic():
    # a seek_contradiction question (polarity -1) whose target IS confirmed contradicts the aspect
    q = Question(kind=QuestionKind.SEEK_CONTRADICTION, text="Do storms close it?",
                 target="Storms frequently close the coastal route.", polarity=-1)
    assert resolve_signal(QuestionStatus(q, TARGET_SUPPORTED)) == ASPECT_CONTRADICTION
    # …and if that red-team target is REFUTED, that supports the aspect
    assert resolve_signal(QuestionStatus(q, TARGET_CONTRADICTED)) == ASPECT_SUPPORT
    # a plain seek_support (polarity +1) confirmed supports
    qs = Question(kind=QuestionKind.SEEK_SUPPORT, text="", target="", polarity=1)
    assert resolve_signal(QuestionStatus(qs, TARGET_SUPPORTED)) == ASPECT_SUPPORT
    assert resolve_signal(QuestionStatus(qs, TARGET_UNTESTED)) == ASPECT_NONE


def test_aggregate_delegates_thresholds_to_the_profile():
    p = ToyProfile()
    qsup = QuestionStatus(Question(QuestionKind.SEEK_SUPPORT, "", "", 1), TARGET_SUPPORTED)
    qcon = QuestionStatus(Question(QuestionKind.SEEK_CONTRADICTION, "", "", -1), TARGET_SUPPORTED)
    assert aggregate_aspect(p, [qsup], critical=True) == SUPPORTED
    assert aggregate_aspect(p, [qsup, qcon], critical=True) == CONTRADICTED   # a contradiction dominates
    assert aggregate_aspect(p, [], critical=True) == UNDER_TESTED


@pytest.mark.asyncio
async def test_generate_inquiries_is_thesis_native_clustered_and_coverage_gated():
    from eigen_kernel.decision import generate_inquiries
    aspects = ToyProfile().aspects()   # keys: faster, scenic
    async def llm(_sys, user):
        # model clusters thesis-native questions but COVERS ONLY 'faster' — 'scenic' is missing
        return {"inquiries": [
            {"name": "Speed of the coastal route", "framing": "time",
             "questions": [{"dimension": "faster", "kind": "seek_support",
                            "text": "Is the coastal route faster on weekday mornings?",
                            "target": "The coastal route is faster on weekday mornings.", "polarity": 1}]}]}
    inqs = await generate_inquiries(llm, decision="coastal vs inland", aspects=aspects, directive="x")
    covered = {q["dimension"] for i in inqs for q in i["questions"]}
    assert covered == {"faster", "scenic"}            # 'scenic' gap-filled by the coverage gate
    assert any(i["name"] == "Speed of the coastal route" for i in inqs)   # thesis-native cluster kept
    assert any("Further checks" in i["name"] for i in inqs)               # the gap-fill cluster


@pytest.mark.asyncio
async def test_generate_inquiries_falls_open_to_full_coverage_with_no_model():
    from eigen_kernel.decision import generate_inquiries
    aspects = ToyProfile().aspects()
    inqs = await generate_inquiries(None, decision="d", aspects=aspects, directive="x")
    covered = {q["dimension"] for i in inqs for q in i["questions"]}
    assert covered == {a.key for a in aspects}        # every dimension present, honest degraded mode
