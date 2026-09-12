from __future__ import annotations

import pytest

from .thesis_policy import TechThesisPolicy


POLICY = TechThesisPolicy()


def _claim(rung: str, state: str, *, critical: bool = True) -> dict:
    return {"rung": rung, "claim": rung.replace("_", " "), "critical": critical,
            "research_status": state}


def test_one_critical_contradiction_is_a_pass() -> None:
    got = POLICY.decide([
        _claim("problem_exists", "supported"),
        _claim("willingness_to_pay", "contradicted"),
    ])

    assert got == {
        "recommendation": "pass",
        "decisive_claims": ["willingness_to_pay"],
        "reason": "A critical claim is contradicted.",
    }


def test_all_critical_claims_supported_is_fund() -> None:
    got = POLICY.decide([
        _claim("problem_exists", "supported"),
        _claim("willingness_to_pay", "supported"),
        _claim("catalyst", "open", critical=False),
    ])

    assert got == {
        "recommendation": "fund",
        "decisive_claims": ["problem_exists", "willingness_to_pay"],
        "reason": "Every critical claim has qualified support and no blocker remains.",
    }


@pytest.mark.parametrize("state", [
    "open", "conflicted", "under_tested", "attack_unavailable", "failed",
    "primary_research_needed",
])
def test_unresolved_critical_claim_continues_diligence(state: str) -> None:
    got = POLICY.decide([_claim("problem_exists", state)])

    assert got["recommendation"] == "continue_diligence"
    assert got["decisive_claims"] == ["problem_exists"]


def test_no_critical_claims_continues_diligence() -> None:
    got = POLICY.decide([_claim("context", "supported", critical=False)])

    assert got["recommendation"] == "continue_diligence"


def test_one_interview_account_cannot_qualify_a_critical_claim() -> None:
    status, note = POLICY.qualify([
        {"relation": "supports", "source_key": "call", "said_by": "one buyer",
         "independence_key": "one buyer", "gate_results": {"span_ok": True,
         "entailed": True, "on_subject": True, "kind_ok": True, "period_ok": True}},
    ], settleable="call_only")

    assert status == "primary_research_needed"
    assert "one account" in note.lower()


def test_two_independent_admissible_sources_can_support() -> None:
    evidence = [
        {"relation": "supports", "source_key": "edgar", "independence_key": "issuer-a",
         "gate_results": {"span_ok": True, "entailed": True, "on_subject": True,
                          "kind_ok": True, "period_ok": True}},
        {"relation": "supports", "source_key": "github", "independence_key": "org-b",
         "gate_results": {"span_ok": True, "entailed": True, "on_subject": True,
                          "kind_ok": True, "period_ok": True}},
    ]

    assert POLICY.qualify(evidence, settleable="corpus")[0] == "supported"


def test_signal_never_qualifies_a_claim() -> None:
    evidence = [
        {"relation": "signal", "source_key": "news", "independence_key": "publisher-a",
         "gate_results": {"span_ok": True, "entailed": True, "on_subject": True,
                          "kind_ok": True, "period_ok": True}},
        {"relation": "signal", "source_key": "reddit", "independence_key": "thread-b",
         "gate_results": {"span_ok": True, "entailed": True, "on_subject": True,
                          "kind_ok": True, "period_ok": True}},
    ]

    assert POLICY.qualify(evidence, settleable="corpus")[0] == "under_tested"
