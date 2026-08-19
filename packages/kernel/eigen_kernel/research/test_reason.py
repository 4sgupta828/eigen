"""The grounded-reasoning GATE, tested deterministically with a fake LLM (no network).

Proves the load-bearing properties: a candidate with no valid basis or a fabricated figure is dropped
by CODE before any judge; the epistemic label is assigned by the gate from (kind, validity verdict),
never self-declared; an ARBITRARY leap is never emitted as inference (suppressed, or at most a labeled
speculation in idea mode); a judge failure demotes rather than upgrades.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .reason import (DeriveCandidate, DeriveCandidates, DerivedClaim, _Verdict, _Verdicts, derive)


@dataclass
class _F:                       # minimal stand-in for a VerifiedClaim
    text: str
    quote: str = ""


# Findings: three margins, transitively orderable. Note NO finding states "A > C" or any acquisition.
_FINDINGS = [
    _F("Company A operating margin is 40%."),
    _F("Company B operating margin is 30%."),
    _F("Company C operating margin is 25%."),
]


class _FakeLLM:
    """Returns canned candidates on the generate call and canned verdicts on the judge call, dispatched
    by response_format. `cands`/`verdicts` are what the 'model' proposes; the GATE decides what survives."""
    def __init__(self, cands, verdicts):
        self._cands, self._verdicts = cands, verdicts

    async def complete(self, *, system, messages, response_format, max_tokens):
        if response_format is DeriveCandidates:
            parsed = DeriveCandidates(derivations=self._cands)
        else:
            parsed = _Verdicts(verdicts=self._verdicts)
        return type("R", (), {"parsed": parsed, "output_tokens": 0})()


def _run(cands, verdicts, **kw):
    llm = _FakeLLM(cands, verdicts)
    return asyncio.run(derive("Which company is most efficient?", _FINDINGS, llm, **kw))


def test_valid_comparative_becomes_inference():
    out = _run(
        [DeriveCandidate(conclusion="A has a higher margin than C.", basis=[1, 3],
                         kind="comparative", warrant="40% > 25%")],
        [_Verdict(index=1, verdict="valid")])
    assert len(out) == 1 and out[0].label == "inference"
    assert out[0].basis == (1, 3)


def test_arbitrary_leap_is_dropped_not_shipped():
    # "A will acquire C" does NOT follow from margins — the judge calls it arbitrary → dropped.
    out = _run(
        [DeriveCandidate(conclusion="A will acquire C.", basis=[1, 3], kind="causal",
                         warrant="A is bigger", falsifier="no acquisition announced")],
        [_Verdict(index=1, verdict="arbitrary")])
    assert out == []                       # never emitted


def test_arbitrary_survives_only_as_labeled_speculation_in_idea_mode():
    out = _run(
        [DeriveCandidate(conclusion="A could roll up smaller-margin peers like C.", basis=[1, 3],
                         kind="opportunity", warrant="margin headroom", falsifier="no M&A capacity")],
        [_Verdict(index=1, verdict="arbitrary")], generate_ideas=True)
    assert len(out) == 1 and out[0].label == "speculation"   # quarantined, never inference


def test_valid_causal_needs_a_falsifier_to_survive():
    # a valid-but-jump causal step with NO falsifier is dropped (can't be an unfalsifiable claim)
    no_fals = _run([DeriveCandidate(conclusion="A's margin lead will compound.", basis=[1],
                                    kind="causal", warrant="scale economics")],
                   [_Verdict(index=1, verdict="valid")])
    assert no_fals == []
    with_fals = _run([DeriveCandidate(conclusion="A's margin lead will compound.", basis=[1],
                                      kind="causal", warrant="scale economics",
                                      falsifier="margins converge next filing")],
                     [_Verdict(index=1, verdict="valid")])
    assert len(with_fals) == 1 and with_fals[0].label == "hypothesis"


def test_no_basis_dropped_by_code_before_judge():
    # basis empty AND out-of-range → structural drop; the (would-be "valid") verdict never matters.
    out = _run([DeriveCandidate(conclusion="A is the best company.", basis=[], kind="comparative")],
               [_Verdict(index=1, verdict="valid")])
    assert out == []


def test_fabricated_figure_dropped_by_code():
    # introduces "$5 billion" — a hard token in NO basis finding, non-arithmetic → structural drop.
    out = _run([DeriveCandidate(conclusion="A is worth $5 billion given its 40% margin.", basis=[1],
                                kind="implication", warrant="high margin", falsifier="an independent estimate differs")],
               [_Verdict(index=1, verdict="valid")])
    assert out == []


def test_arithmetic_new_figure_allowed_when_operands_grounded():
    findings = [_F("A revenue is 100."), _F("A margin is 40%.")]
    llm = _FakeLLM([DeriveCandidate(conclusion="A profit is 40.", basis=[1, 2], kind="arithmetic",
                                    warrant="100 * 40%")],
                   [_Verdict(index=1, verdict="valid")])
    out = asyncio.run(derive("profit?", findings, llm))
    assert len(out) == 1 and out[0].label == "inference"


def test_judge_failure_demotes_does_not_upgrade():
    # no verdict returned for the candidate → conservative "plausible" → hypothesis (needs falsifier),
    # NEVER inference. Proves a judge outage can't mint a confident inference.
    out = _run([DeriveCandidate(conclusion="A leads its peers on efficiency.", basis=[1, 2, 3],
                                kind="comparative", warrant="highest margin",
                                falsifier="a peer reports higher margin")],
               [])   # empty verdicts
    assert len(out) == 1 and out[0].label == "hypothesis"
