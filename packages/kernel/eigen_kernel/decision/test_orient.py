"""Tests for orient_and_scan — the landscape scan that keeps QUESTIONS current.

The discipline under test: orient (name what to learn) → scan (retrieve current) → digest (dated, typed
brief), never raising, degrading to a smaller-but-valid brief on any failure, and grounding every named
specific in a real scan hit.
"""
import json

import pytest

from eigen_kernel.decision.orient import (
    orient_and_scan, empty_brief, brief_context, brief_is_empty, unsourced_specifics, _SECTIONS, NEEDS,
)

pytestmark = pytest.mark.asyncio


class FakeLLM:
    """A scripted llm_json(system, user) -> dict. Routes by a marker in the system prompt so the two
    phases (orientation, digest) get their own scripted reply."""
    def __init__(self, orient=None, digest=None, raise_on=None):
        self.orient = orient
        self.digest = digest
        self.raise_on = raise_on or ()
        self.calls = []

    async def __call__(self, system, user):
        phase = "digest" if "digesting a landscape" in system.lower() else "orient"
        self.calls.append(phase)
        if phase in self.raise_on:
            raise RuntimeError("llm down")
        return (self.digest if phase == "digest" else self.orient)


def _mk_legs(corpus=None, web=None, peers=None, corpus_raises=False):
    async def retrieve(q):
        if corpus_raises:
            raise RuntimeError("corpus down")
        return corpus or []
    async def web_leg(q):
        return web or []
    async def peers_leg(q):
        return peers or []
    return retrieve, web_leg, peers_leg


ORIENT_OK = {"queries": [
    {"q": "current CDS incumbents mid-sized hospitals 2026", "need": "incumbents", "why": "know who to test against"},
    {"q": "new FHIR-native readmission startups 2026", "need": "entrants", "why": "recent entrants"},
]}
DIGEST_OK = {
    "incumbents": [{"name": "Epic", "what_they_do": "bundles a readmission model", "src": 1}],
    "entrants": [{"name": "NovaCDS", "note": "FHIR-native, 2026 seed", "src": 2}],
    "funding": [], "regulation": [], "benchmarks": [],
    "why_now": [{"catalyst": "new CMS rule", "src": 1}],
    "unknowns": ["willingness-to-pay in mid-market"],
}
CORPUS = [{"title": "Epic readmission model", "text": "Epic ships an Unplanned Readmission model.", "source": "corpus", "as_of": "2025-08-01", "register": "filed"}]
WEB = [{"title": "NovaCDS raises seed", "text": "NovaCDS, a FHIR-native CDS vendor, raised a 2026 seed.", "url": "https://x.com/nova", "as_of": "2026-03-01"}]
PEERS = [{"name": "NovaCDS", "note": "in our index"}]


async def test_full_happy_path_builds_typed_dated_brief():
    llm = FakeLLM(orient=ORIENT_OK, digest=DIGEST_OK)
    r, w, p = _mk_legs(CORPUS, WEB, PEERS)
    brief = await orient_and_scan(llm, retrieve=r, web=w, peers=p, decision="AI CDSS for mid-sized hospitals", directive="d")
    assert brief["as_of"]
    assert any(i["name"] == "Epic" for i in brief["incumbents"])
    assert any(e["name"] == "NovaCDS" for e in brief["entrants"])
    # dates + register are carried from the cited hit
    epic = brief["incumbents"][0]
    assert epic["as_of"] == "2025-08-01" and epic["register"] == "filed"
    assert brief["unknowns"] and not brief_is_empty(brief)
    assert brief["queries"]                      # the chosen orientation queries are exposed
    assert llm.calls == ["orient", "digest"]


async def test_none_llm_returns_valid_empty_brief():
    brief = await orient_and_scan(None, decision="x thesis about something")
    assert brief_is_empty(brief) and brief["unknowns"]
    assert set(_SECTIONS).issubset(brief.keys())


async def test_empty_decision_short_circuits():
    brief = await orient_and_scan(FakeLLM(orient=ORIENT_OK), decision="   ")
    assert brief_is_empty(brief)


async def test_orientation_garbage_yields_empty_brief():
    llm = FakeLLM(orient={"nope": 1})     # no queries
    brief = await orient_and_scan(llm, decision="a real thesis sentence here", directive="d")
    assert brief_is_empty(brief)
    assert llm.calls == ["orient"]        # never reached digest


async def test_failing_corpus_leg_never_fails_the_scan():
    llm = FakeLLM(orient=ORIENT_OK, digest=DIGEST_OK)
    r, w, p = _mk_legs(CORPUS, WEB, PEERS, corpus_raises=True)
    brief = await orient_and_scan(llm, retrieve=r, web=w, peers=p, decision="thesis", directive="d")
    # web/peers still contribute; the brief is valid despite the corpus leg raising
    assert not brief_is_empty(brief)
    assert any(e["name"] == "NovaCDS" for e in brief["entrants"])


async def test_digest_llm_failure_falls_back_to_deterministic_assembly():
    llm = FakeLLM(orient=ORIENT_OK, raise_on=("digest",))
    r, w, p = _mk_legs(CORPUS, WEB, PEERS)
    brief = await orient_and_scan(llm, retrieve=r, web=w, peers=p, decision="thesis", directive="d")
    # No model digest, but the scan hits are bucketed by their orientation `need` — still current.
    assert not brief_is_empty(brief)
    assert any("Epic" in (i.get("name") or "") for i in brief["incumbents"])
    assert any("Nova" in (e.get("name") or "") for e in brief["entrants"])


async def test_digest_drops_specifics_not_in_scan():
    # The model tries to name something with a src that points nowhere → source blanks, but the entity is
    # still surfaced (the runtime lint/generators treat un-sourced specifics as to-verify).
    llm = FakeLLM(orient=ORIENT_OK, digest={"incumbents": [{"name": "Ghost Corp", "what_they_do": "made up", "src": 99}], "entrants": [], "funding": [], "regulation": [], "benchmarks": [], "why_now": [], "unknowns": []})
    r, w, p = _mk_legs(CORPUS, WEB, PEERS)
    brief = await orient_and_scan(llm, retrieve=r, web=w, peers=p, decision="thesis", directive="d")
    ghost = brief["incumbents"][0]
    assert ghost["name"] == "Ghost Corp" and ghost["source"] == ""     # bad src → no source


async def test_orientation_query_cap_is_respected():
    many = {"queries": [{"q": f"query number {i}", "need": "entrants", "why": "w"} for i in range(20)]}
    llm = FakeLLM(orient=many, digest=DIGEST_OK)
    r, w, p = _mk_legs(CORPUS, WEB, PEERS)
    brief = await orient_and_scan(llm, retrieve=r, web=w, peers=p, decision="thesis", directive="d", n_queries=3)
    assert len(brief["queries"]) == 3


async def test_web_surfaces_entrant_the_orientation_did_not_know():
    # Staleness case: the model's orientation asked broadly; only the WEB leg knows the recent entrant,
    # and it must reach the brief (deterministic path proves the retrieval carries it, not memory).
    llm = FakeLLM(orient={"queries": [{"q": "recent CDS entrants 2026", "need": "entrants", "why": "w"}]}, raise_on=("digest",))
    r, w, p = _mk_legs(None, WEB, None)
    brief = await orient_and_scan(llm, retrieve=r, web=w, peers=p, decision="thesis", directive="d")
    assert any("Nova" in (e.get("name") or "") for e in brief["entrants"])


async def test_orient_accepts_json_string_replies():
    llm = FakeLLM(orient=json.dumps(ORIENT_OK), digest=json.dumps(DIGEST_OK))
    r, w, p = _mk_legs(CORPUS, WEB, PEERS)
    brief = await orient_and_scan(llm, retrieve=r, web=w, peers=p, decision="thesis", directive="d")
    assert not brief_is_empty(brief)


async def test_brief_context_renders_dated_block_and_empty_is_blank():
    llm = FakeLLM(orient=ORIENT_OK, digest=DIGEST_OK)
    r, w, p = _mk_legs(CORPUS, WEB, PEERS)
    brief = await orient_and_scan(llm, retrieve=r, web=w, peers=p, decision="thesis", directive="d")
    ctx = brief_context(brief)
    assert "CURRENT LANDSCAPE" in ctx and "Epic" in ctx and "as of" in ctx.lower()
    assert brief_context(empty_brief()) == ""


async def test_orientation_non_dict_json_string_never_raises():
    # A model that returns a JSON *array* string (decodes to a list, not a dict) must not crash the scan.
    llm = FakeLLM(orient="[1, 2, 3]")
    brief = await orient_and_scan(llm, decision="a real thesis sentence here", directive="d")
    assert brief_is_empty(brief)      # no queries formed → valid empty brief, no exception


async def test_needs_vocabulary_is_domain_free():
    # a litmus that the kernel names generic diligence axes, not domain nouns
    for n in NEEDS:
        assert n.islower() and " " not in n


# ── the anti-unsourced-entity lint (spec §5.1 / the "no-unsourced-entity gate") ──

BRIEF = {"as_of": "2026-09-18",
         "incumbents": [{"name": "Oracle Health", "what_they_do": "x", "source": "s", "as_of": "", "register": "coverage"}],
         "entrants": [{"name": "NovaCDS", "note": "y", "source": "s", "as_of": "", "register": "stated"}],
         "funding": [], "regulation": [], "benchmarks": [], "why_now": [], "unknowns": []}


def test_lint_passes_entities_that_are_in_the_brief():
    assert unsourced_specifics("How does Oracle Health price its readmission module?", BRIEF) == []
    assert unsourced_specifics("Is NovaCDS a credible entrant?", BRIEF) == []


def test_lint_flags_a_stale_multiword_entity_absent_from_the_brief():
    # "Cerner Millennium" is not in the brief → a specific the model recalled from memory, flagged.
    flagged = unsourced_specifics("Does Cerner Millennium bundle a comparable model?", BRIEF)
    assert "Cerner Millennium" in flagged


def test_lint_does_not_flag_generic_present_tense_phrasing():
    # the desired phrasing names no specific → nothing flagged (multi-word cap phrases only)
    assert unsourced_specifics("Which incumbents currently bundle a predictive readmission model?", BRIEF) == []
    assert unsourced_specifics("What is the willingness-to-pay in mid-sized hospitals?", BRIEF) == []


def test_lint_is_off_when_the_brief_is_empty():
    # no scan → nothing to check against; the discipline binds only once a landscape exists
    assert unsourced_specifics("Does Acme Corp compete here?", empty_brief()) == []
