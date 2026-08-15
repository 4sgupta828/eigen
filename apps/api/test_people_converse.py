"""People concierge phase B (_people_converse_turn) — the narrowing-agent contract:
candidate ids are MEMBERSHIP-validated against the fetched rows (the model can only pick
among real matches), present with no valid ids downgrades to clarify, and LLM failure
falls back to a counts-based clarify built from the breakdown (structural, no guessing)."""
from __future__ import annotations

import asyncio

from eigen_kernel.providers.llm import LLMResult

from api.app import _people_converse_turn

INTENT = {"specialty": "nephrology", "state": "NY", "city": "", "name": "",
          "sort_metric": "", "note": ""}
BREAKDOWN = {"total": 3,
             "by_specialty": [{"value": "nephrology", "count": 3}],
             "by_city": [{"value": "NEW YORK", "count": 2}, {"value": "BUFFALO", "count": 1}],
             "by_state": [{"value": "NY", "count": 3}]}
CANDS = [
    {"entity_id": "npi:1000000001", "name": "A ONE", "specialty": "nephrology",
     "city": "NEW YORK", "state": "NY", "credential": "MD"},
    {"entity_id": "npi:1000000002", "name": "B TWO", "specialty": "nephrology",
     "city": "NEW YORK", "state": "NY", "credential": "DO"},
    {"entity_id": "npi:1000000003", "name": "C THREE", "specialty": "nephrology",
     "city": "BUFFALO", "state": "NY", "credential": ""},
]


class _LLM:
    def __init__(self, **fields):
        self.fields = fields
        self.system = None
        self.user = None

    async def complete(self, *, system, messages, response_format, max_tokens=700,
                       temperature=None):
        self.system = system
        self.user = messages[0]["content"]
        return LLMResult(parsed=response_format(**self.fields), output_tokens=5)


class _BrokenLLM:
    async def complete(self, **kw):
        raise RuntimeError("provider down")


def _run(coro):
    return asyncio.run(coro)


def test_present_membership_validated():
    llm = _LLM(action="present", message="Two in New York fit the situation.",
               candidate_ids=["npi:1000000001", "npi:9999999999", "npi:1000000002"])
    out = _run(_people_converse_turn("User: kidney doctor in NY", INTENT, BREAKDOWN,
                                     CANDS, llm=llm))
    assert out["action"] == "present"
    ids = [c["entity_id"] for c in out["candidates"]]
    assert ids == ["npi:1000000001", "npi:1000000002"]   # invented id dropped, order kept
    # the model saw the live breakdown and the real rows — its only sources of fact
    assert "total matches: 3" in llm.user and "npi:1000000003" in llm.user


def test_present_without_valid_ids_downgrades_to_clarify():
    llm = _LLM(action="present", message="Here are options.",
               candidate_ids=["npi:0000000000"])
    out = _run(_people_converse_turn("User: kidney doctor", INTENT, BREAKDOWN, CANDS,
                                     llm=llm))
    assert out["action"] == "clarify" and out["candidates"] == []


def test_valid_ids_force_present_even_if_model_says_clarify():
    llm = _LLM(action="clarify", message="Here are adult nephrologists: A One; B Two.",
               candidate_ids=["npi:1000000001", "npi:1000000002"])
    out = _run(_people_converse_turn("User: show me options", INTENT, BREAKDOWN, CANDS,
                                     llm=llm))
    assert out["action"] == "present"
    assert [c["entity_id"] for c in out["candidates"]] == ["npi:1000000001",
                                                           "npi:1000000002"]


def test_clarify_passthrough_and_cap():
    llm = _LLM(action="clarify", message="Which city — New York or Buffalo?")
    out = _run(_people_converse_turn("User: kidney doctor in NY", INTENT, BREAKDOWN,
                                     CANDS, llm=llm))
    assert out["action"] == "clarify"
    assert out["message"] == "Which city — New York or Buffalo?"
    assert out["candidates"] == []


def test_names_in_prose_recovered_to_clickable_candidates():
    # the observed prod failure: names listed in message, candidate_ids empty
    llm = _LLM(action="clarify", candidate_ids=[],
               message="Here are adult nephrologists in Akron: A One, MD; C Three, DO.")
    out = _run(_people_converse_turn("User: show me options", INTENT, BREAKDOWN, CANDS,
                                     llm=llm))
    assert out["action"] == "present"
    assert [c["entity_id"] for c in out["candidates"]] == ["npi:1000000001",
                                                           "npi:1000000003"]


def test_clarify_budget_reaches_the_model():
    llm = _LLM(action="present", message="Options.", candidate_ids=["npi:1000000001"])
    _run(_people_converse_turn("User: x", INTENT, BREAKDOWN, CANDS, n_asked=2, llm=llm))
    assert "Clarifying questions you have already asked: 2." in llm.user
    assert "LIMIT REACHED" in llm.user
    llm2 = _LLM(action="clarify", message="Which city?")
    _run(_people_converse_turn("User: x", INTENT, BREAKDOWN, CANDS, n_asked=1, llm=llm2))
    assert "already asked: 1." in llm2.user and "LIMIT REACHED" not in llm2.user


def test_only_real_filters_named_in_prompt():
    llm = _LLM(action="clarify", message="Which city?")
    _run(_people_converse_turn("User: x", INTENT, BREAKDOWN, CANDS, llm=llm))
    assert "NO distance/radius" in llm.system
    assert "at most 2 clarifying questions" in llm.system


def test_llm_failure_falls_back_to_counts():
    out = _run(_people_converse_turn("User: kidney doctor", INTENT, BREAKDOWN, CANDS,
                                     llm=_BrokenLLM()))
    assert out["action"] == "clarify"
    assert "3 specialists match" in out["message"]


def test_llm_failure_zero_matches_suggests_relaxing():
    bd = {"total": 0, "by_specialty": [], "by_city": [], "by_state": []}
    out = _run(_people_converse_turn("User: kidney doctor in nowhere", INTENT, bd, [],
                                     llm=_BrokenLLM()))
    assert out["action"] == "clarify"
    assert "relaxing" in out["message"]
