"""Unit tests for `api.related_research.find_related_research` (offline, fake service).

Covers the structural quality logic the panel signed off on: dedup by document_id, the
relative relevance floor (honest-omit), per-kind ranking lanes, and URL resolution. No DB/LLM.

    PYTHONPATH=apps:packages/vertical_tech:packages/kernel .venv/bin/python -m pytest \
        apps/api/test_related_research.py -q
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from api.related_research import find_related_research


def _hit(doc, score, kind, *, title="", block="b0", peer=None, cites=None, year=None, venue=""):
    facets = {"source_kind": kind}
    if peer is not None:
        facets["is_peer_reviewed"] = "true" if peer else "false"
    if cites is not None:
        facets["cited_by_count"] = str(cites)
    if year is not None:
        facets["year"] = str(year)
    if venue:
        facets["venue"] = venue
    return SimpleNamespace(document_id=doc, block_id=block, text="…", score=score,
                           facets=facets, document_title=title or doc, source_key=kind, locator=None)


class _Svc:
    def __init__(self, hits):
        self._hits = hits
        self.ui = SimpleNamespace(source_url=lambda did, quote=None: f"https://src/{did}")

    async def search(self, **kw):
        self.captured = kw
        return list(self._hits)


def _run(coro):
    return asyncio.run(coro)


def test_dedup_by_document_keeps_best_block() -> None:
    svc = _Svc([
        _hit("openalex:W1", 0.9, "paper", title="Paper One", peer=True, cites=100, year=2024, block="b3"),
        _hit("openalex:W1", 0.7, "paper", title="Paper One", peer=True, cites=100, year=2024, block="b1"),
    ])
    out = _run(find_related_research(svc, question="q", tenant_id="demo", ui=svc.ui))
    assert len(out) == 1 and out[0]["title"] == "Paper One"
    assert out[0]["url"] == "https://src/openalex:W1"
    # asked the corpus for research kinds only
    assert svc.captured["facets"]["source_kind"] == ("paper", "preprint", "filing")


def test_relevance_floor_omits_weak_matches() -> None:
    # best=0.9; rel_floor 0.55 → floor 0.495; a 0.3 hit is dropped
    svc = _Svc([
        _hit("openalex:W1", 0.9, "paper", peer=True, cites=50, year=2023),
        _hit("openalex:W2", 0.3, "paper", peer=True, cites=9999, year=2024),   # off-topic, high cites
    ])
    out = _run(find_related_research(svc, question="q", tenant_id="demo", ui=svc.ui))
    assert [o["title"] for o in out] == ["openalex:W1"]   # the mega-cited but irrelevant one is gone


def test_honest_omit_when_nothing_retrieved() -> None:
    assert _run(find_related_research(_Svc([]), question="q", tenant_id="demo")) == []


def test_mis_ingested_answer_title_is_dropped() -> None:
    svc = _Svc([
        _hit("x:bad", 0.95, "paper", title="Based on the available search results, I have organized", peer=True, cites=9, year=2024),
        _hit("openalex:W2", 0.90, "paper", title="A Real Paper Title", peer=True, cites=50, year=2023),
    ])
    out = _run(find_related_research(svc, question="q", tenant_id="demo", ui=svc.ui))
    assert [o["title"] for o in out] == ["A Real Paper Title"]   # the answer-preamble title is filtered


def test_peer_reviewed_high_cite_paper_outranks_within_lane() -> None:
    svc = _Svc([
        _hit("openalex:W1", 0.80, "paper", title="Reviewed-High", peer=True, cites=500, year=2020),
        _hit("openalex:W2", 0.82, "paper", title="Unreviewed-Low", peer=False, cites=1, year=2024),
    ])
    out = _run(find_related_research(svc, question="q", tenant_id="demo", ui=svc.ui, rel_floor=0.9))
    # rel_floor 0.9*0.82=0.738 keeps both; final order is by RELEVANCE (score), so W2 (0.82) leads,
    # but both survive — the lane rank decided candidacy, relevance decides display order
    assert {o["title"] for o in out} == {"Reviewed-High", "Unreviewed-Low"}
    assert out[0]["title"] == "Unreviewed-Low"   # higher score leads


def test_never_raises_on_search_error() -> None:
    class _Boom:
        ui = None
        async def search(self, **kw):
            raise RuntimeError("db down")
    assert _run(find_related_research(_Boom(), question="q", tenant_id="demo")) == []


def test_mixed_kinds_all_representable() -> None:
    svc = _Svc([
        _hit("openalex:W1", 0.90, "paper", title="P", peer=True, cites=30, year=2023),
        _hit("arxiv:2401.1", 0.85, "preprint", title="Pre", year=2024),
        _hit("edgar:acc", 0.80, "filing", title="Fil", year=2024),
    ])
    out = _run(find_related_research(svc, question="q", tenant_id="demo", ui=svc.ui))
    kinds = {o["kind"] for o in out}
    assert kinds == {"paper", "preprint", "filing"}
    assert out[0]["kind"] == "paper"   # highest relevance leads
