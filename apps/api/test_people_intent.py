"""People NL intent parse (_parse_people_intent) — the Rule-18 contract: the LLM maps
words onto the CLOSED vocabulary; code validates every field by MEMBERSHIP so nothing the
model invents reaches SQL; LLM failure falls back to structural specialty containment
only (never a state/city/name/sort guess)."""
from __future__ import annotations

import asyncio

from eigen_kernel.providers.llm import LLMResult

from api.app import _parse_people_intent

FACETS = {
    "specialties": ["cardiology", "cardiology (interventional)", "nephrology",
                    "orthopedic (spine)"],
    "states": ["NY", "OH", "TX"],
    "countries": ["US"],
    "metrics": [{"key": "medicare_partb_services",
                 "label": "Original Medicare Part B claims, 2023"}],
}


class _LLM:
    def __init__(self, **fields):
        self.fields = fields
        self.system = None

    async def complete(self, *, system, messages, response_format, max_tokens=300,
                       temperature=None):
        self.system = system
        return LLMResult(parsed=response_format(**self.fields), output_tokens=5)


class _BrokenLLM:
    async def complete(self, **kw):
        raise RuntimeError("provider down")


def _run(coro):
    return asyncio.run(coro)


def test_valid_parse_passes_membership():
    llm = _LLM(specialty="cardiology (interventional)", state="TX", city="Houston")
    out, how = _run(_parse_people_intent("interventional cardiologists in Houston",
                                         FACETS, llm=llm))
    assert how == "llm"
    assert out["specialty"] == "cardiology (interventional)"
    assert out["state"] == "TX" and out["city"] == "Houston"
    assert out["name"] == "" and out["sort_metric"] == ""
    # the closed vocab must be IN the prompt — the model chooses, it never invents
    assert "- nephrology" in llm.system and "medicare_partb_services" in llm.system


def test_invented_values_are_dropped():
    llm = _LLM(specialty="sports medicine", state="Ohio", sort_metric="quality_score")
    out, _ = _run(_parse_people_intent("best sports medicine doc in Ohio", FACETS, llm=llm))
    assert out["specialty"] == ""            # not a listed label
    assert out["state"] == ""                # not a 2-letter member
    assert out["sort_metric"] == ""          # not a loaded metric key
    assert "no loaded metric" in out["note"]


def test_case_insensitive_specialty_and_state_normalize():
    llm = _LLM(specialty="Nephrology", state="oh")
    out, _ = _run(_parse_people_intent("kidney doctors in ohio", FACETS, llm=llm))
    assert out["specialty"] == "nephrology" and out["state"] == "OH"


def test_sort_only_from_loaded_metrics():
    llm = _LLM(specialty="cardiology", sort_metric="medicare_partb_services")
    out, _ = _run(_parse_people_intent(
        "cardiologists by medicare part b volume", FACETS, llm=llm))
    assert out["sort_metric"] == "medicare_partb_services"


def test_unmatched_specialty_surfaces_the_gap():
    llm = _LLM(specialty="", unmatched_specialty="dermatology", state="CA",
               city="Santa Clara")
    out, _ = _run(_parse_people_intent("dermatology specialist near santa clara, ca",
                                       FACETS, llm=llm))
    assert out["specialty"] == "" and out["unmatched_specialty"] == "dermatology"
    assert out["state"] == "" or out["state"] == "CA"   # CA not in FACETS states → dropped
    assert "unmatched_specialty" in out


def test_unmatched_specialty_cleared_when_specialty_matched():
    llm = _LLM(specialty="cardiology", unmatched_specialty="heart doctor")
    out, _ = _run(_parse_people_intent("heart doctor", FACETS, llm=llm))
    assert out["specialty"] == "cardiology" and out["unmatched_specialty"] == ""


def test_fallback_is_containment_only():
    out, how = _run(_parse_people_intent("cardiology in houston texas", FACETS,
                                         llm=_BrokenLLM()))
    assert how == "fallback"
    assert out["specialty"] == "cardiology"
    # NEVER guessed: no state/city/name from the fallback path
    assert out["state"] == "" and out["city"] == "" and out["name"] == ""
    assert "Intent model unavailable" in out["note"]


def test_fallback_with_no_containment_abstains():
    out, how = _run(_parse_people_intent("who is good near me", FACETS, llm=_BrokenLLM()))
    assert how == "fallback"
    assert not any(out[k] for k in ("specialty", "state", "city", "name", "sort_metric"))
