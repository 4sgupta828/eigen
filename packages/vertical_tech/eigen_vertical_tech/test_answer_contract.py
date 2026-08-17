"""Offline tests for the tech ANSWER-CONTRACT (evidence-regime) — NO network.

Prove the derivation parses a `stance`, the vertical profiles carry the right regime knobs, and the
kernel's stance→profile selection picks them (current → recency-first + authority suppressed;
established → authority-first, no recency; unknown → no profile = today's behavior).
"""
from __future__ import annotations

import asyncio

from eigen_kernel.providers.llm import FakeLLM
from eigen_kernel.research.contract import _ContractOut, derive_contract

from .answer_contract import ANSWER_PROFILES, TECH_CONTRACT_PROMPT


def _llm_returning(stance: str):
    return FakeLLM(lambda system, messages, rf: _ContractOut(mode="exploratory", stance=stance))


def test_derivation_parses_stance():
    c = asyncio.run(derive_contract("what are the latest frontier models",
                                    _llm_returning("current"), TECH_CONTRACT_PROMPT))
    assert c is not None and c.stance == "current" and c.mode == "exploratory"


def test_current_profile_is_recency_first_authority_suppressed():
    p = ANSWER_PROFILES["current"]
    assert p["suppress_authority"] is True
    assert p["recency"] and p["recency"]["min_rank"] == 0 and p["recency"]["weight"] >= 0.4
    assert "recent" in p["planner_steer"].lower() and "newest" in p["answer_directive"].lower()
    # honesty: a fresh release must be labeled, never presented as benchmarked
    assert "benchmarks pending" in p["answer_directive"].lower()


def test_established_profile_is_authority_first_no_recency():
    p = ANSWER_PROFILES["established"]
    assert p["suppress_authority"] is False and p["recency"] is None
    assert "peer-reviewed" in p["planner_steer"].lower() or "benchmark" in p["planner_steer"].lower()


def test_unknown_stance_selects_no_profile():
    # the kernel resolves profile = answer_profiles.get(stance); "balanced"/unknown → None → today's behavior
    assert ANSWER_PROFILES.get("balanced") is None
    assert ANSWER_PROFILES.get("") is None
