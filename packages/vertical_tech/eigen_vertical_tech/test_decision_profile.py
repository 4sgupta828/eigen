"""The tech DecisionProfile adapts the kernel engine to startup-thesis testing — and preserves the
grounding discipline the whole vertical rests on (a market signal is never controlling)."""
from __future__ import annotations

import pytest

from eigen_kernel.decision import (
    DecisionProfile, aggregate_aspect, generate_questions, required_kinds_covered,
    QuestionStatus, Question, QuestionKind,
    TARGET_SUPPORTED, TARGET_CONTRADICTED, TARGET_UNTESTED,
    SUPPORTED, CONTRADICTED, UNDER_TESTED,
)
from eigen_vertical_tech.decision import TECH_DECISION_PROFILE as P


def _ev(relation, *, kind="primary_filing", signal=False, key="src", controlling=None):
    gates = {g: True for g in ("span_ok", "entailed", "on_subject", "kind_ok", "period_ok")}
    return {"relation": relation, "gate_results": gates, "evidence_kind": kind,
            "signal_only": signal, "independence_key": key,
            "is_controlling": (kind == "primary_filing") if controlling is None else controlling}


def test_profile_is_the_kernels_seam():
    assert isinstance(P, DecisionProfile)


def test_inquiries_partition_the_aspect_ladder_exactly():
    aspects = {a.key for a in P.aspects()}
    covered = [k for inq in P.inquiries() for k in inq.aspect_keys]
    assert sorted(covered) == sorted(aspects)      # every aspect covered
    assert len(covered) == len(set(covered))       # exactly once — no aspect in two inquiries


def test_one_controlling_filing_qualifies_a_target():
    assert P.qualify([_ev("supports", kind="primary_filing")]) == TARGET_SUPPORTED


def test_sentiment_alone_never_qualifies_a_target():
    # two independent SENTIMENT rows must NOT make a target hold — the panel ship-gate
    two_signal = [_ev("supports", kind="sentiment_signal", signal=True, key="hn1", controlling=False),
                  _ev("supports", kind="sentiment_signal", signal=True, key="hn2", controlling=False)]
    assert P.qualify(two_signal) == TARGET_UNTESTED
    # but two independent SUBSTANTIVE (non-signal) sources do
    two_real = [_ev("supports", kind="verified_structured", key="b1", controlling=False),
                _ev("supports", kind="verified_structured", key="b2", controlling=False)]
    assert P.qualify(two_real) == TARGET_SUPPORTED


def test_a_qualified_contradiction_dominates_the_aspect():
    from eigen_kernel.decision import ASPECT_SUPPORT, ASPECT_CONTRADICTION
    assert P.aggregate_aspect([ASPECT_SUPPORT, ASPECT_CONTRADICTION], critical=True) == CONTRADICTED
    assert P.aggregate_aspect([ASPECT_SUPPORT], critical=True) == SUPPORTED
    assert P.aggregate_aspect([], critical=True) == UNDER_TESTED


@pytest.mark.asyncio
async def test_engine_drives_the_tech_profile_end_to_end_without_a_model():
    # no LLM: generation falls open to the required lenses; the aspect still resolves deterministically
    aspect = P.aspects()[0]
    qs = await generate_questions(None, aspect=aspect, decision="A concrete thesis.",
                                  directive=P.question_directive(aspect, "A concrete thesis."))
    assert qs and qs[0].kind == QuestionKind.SEEK_SUPPORT   # honest degraded mode with no model
    # a seek_support question whose target the record confirms → the aspect is supported
    statuses = []
    for q in qs:
        st = TARGET_SUPPORTED if q.polarity >= 0 else TARGET_UNTESTED
        statuses.append(QuestionStatus(q, st))
    assert aggregate_aspect(P, statuses, critical=aspect.critical) == SUPPORTED
