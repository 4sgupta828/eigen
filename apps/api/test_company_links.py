"""Tests for company hyperlinks with recall (api.company_links.detect_and_resolve_companies).

The LLM detects company mentions; KNOWN graph companies → grounded page + /entity, UNKNOWN →
a scoped web search (never a guessed homepage). Offline: fake llm + fake store.

    PYTHONPATH=apps:packages/vertical_tech:packages/kernel .venv/bin/python -m pytest \
        apps/api/test_company_links.py -q
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from api.company_links import detect_and_resolve_companies


class _LLM:
    def __init__(self, names):
        self._names = names

    async def complete(self, **kw):
        return SimpleNamespace(parsed=SimpleNamespace(companies=list(self._names)))


class _Store:
    def __init__(self, reg):
        self._reg = reg

    async def company_norm_map(self, *, tenant_id="demo"):
        return dict(self._reg)


def _svc(names):
    return SimpleNamespace(llm=_LLM(names),
                           ui=SimpleNamespace(source_url=lambda did, q=None: "https://page/" + did))


def _run(c):
    return asyncio.run(c)


ANSWER = ("OpenAI is under pressure, and Abalone Bio is doing well. ClimateAi shut down.")


def test_known_gets_grounded_unknown_gets_web_search() -> None:
    svc = _svc(["OpenAI", "Abalone Bio", "ClimateAi"])
    store = _Store({"abalone bio": {"entity_id": "wikidata:Q42", "name": "Abalone Bio"}})
    out = _run(detect_and_resolve_companies(svc, store, answer=ANSWER, ui=svc.ui))
    by = {c["name"]: c for c in out}
    # Abalone Bio is in the registry → grounded (canonical page + Eigen entity page)
    assert by["Abalone Bio"]["grounded"] is True
    assert by["Abalone Bio"]["url"] == "https://page/wikidata:Q42"
    assert by["Abalone Bio"]["eigen_url"] == "/entity/wikidata%3AQ42"
    # OpenAI + ClimateAi are NOT in the registry → web search, no eigen page (no guessed homepage)
    assert by["OpenAI"]["grounded"] is False
    assert by["OpenAI"]["url"].startswith("https://www.google.com/search?q=")
    assert "eigen_url" not in by["OpenAI"]
    assert {"OpenAI", "Abalone Bio", "ClimateAi"} == set(by)


def test_only_verbatim_names_are_kept() -> None:
    # the LLM returns a name NOT in the text → dropped (the FE could never match it)
    svc = _svc(["OpenAI", "Nonexistent Corp"])
    out = _run(detect_and_resolve_companies(svc, _Store({}), answer="OpenAI is under pressure.", ui=svc.ui))
    assert [c["name"] for c in out] == ["OpenAI"]


def test_dedup_case_insensitive() -> None:
    svc = _svc(["OpenAI", "OpenAI"])
    out = _run(detect_and_resolve_companies(svc, _Store({}), answer="OpenAI and OpenAI.", ui=svc.ui))
    assert len(out) == 1


def test_no_llm_or_empty_answer_returns_empty() -> None:
    assert _run(detect_and_resolve_companies(SimpleNamespace(llm=None), None, answer="x")) == []
    assert _run(detect_and_resolve_companies(_svc([]), None, answer="")) == []


def test_llm_error_never_raises() -> None:
    class _Boom:
        async def complete(self, **kw):
            raise RuntimeError("llm down")
    svc = SimpleNamespace(llm=_Boom(), ui=None)
    assert _run(detect_and_resolve_companies(svc, None, answer="OpenAI here")) == []
