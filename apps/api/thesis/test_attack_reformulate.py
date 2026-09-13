from __future__ import annotations
import pytest
from api.thesis import attack as atk


@pytest.mark.asyncio
async def test_reformulate_adds_angles_and_keeps_the_claim_first():
    async def llm(system, user):
        return {"queries": ["Cerebras production inference customers 2025",
                            "Cerebras vs Nvidia enterprise deployment",
                            "Cerebras revenue named customers", "Cerebras"]}  # dup of claim → deduped
    qs = await atk.reformulate(llm, claim="Cerebras", context="thesis")
    assert qs[0] == "Cerebras"                              # literal claim always leads
    assert "Cerebras production inference customers 2025" in qs
    assert len(qs) == len(set(q.lower() for q in qs))       # de-duped
    assert len(qs) <= 5


@pytest.mark.asyncio
async def test_reformulate_falls_back_to_the_literal_claim():
    assert await atk.reformulate(None, claim="X") == ["X"]
    async def boom(s, u): raise ValueError("down")
    assert await atk.reformulate(boom, claim="X") == ["X"]


def test_strong_json_absent_without_openai_key(monkeypatch):
    from api.thesis import llm as tl
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert tl.strong_json() is None                          # unconfigured → caller falls back


def test_dedupe_caps_by_publisher_not_the_web_bucket():
    from api.thesis.attack import _dedupe
    # 5 web hits, all source_key="web" but DISTINCT hosts → must keep all 5, not collapse to 2
    rows = [{"quote": f"q{i}", "source_key": "web", "independence_key": f"site{i}.com"} for i in range(5)]
    assert len(_dedupe(rows, cap=8, per_source_cap=2)) == 5
    # two hits from the SAME host → per-host cap of 2 keeps both, a third is dropped
    same = [{"quote": f"a{i}", "source_key": "web", "independence_key": "one.com"} for i in range(3)]
    assert len(_dedupe(same, cap=8, per_source_cap=2)) == 2


def test_corpus_sources_defaults_to_research_papers(monkeypatch):
    monkeypatch.delenv("EIGEN_THESIS_CORPUS_SOURCES", raising=False)
    assert atk._corpus_sources() == ["arxiv", "openalex"]
    monkeypatch.setenv("EIGEN_THESIS_CORPUS_SOURCES", "arxiv, uspto ,")
    assert atk._corpus_sources() == ["arxiv", "uspto"]
    monkeypatch.setenv("EIGEN_THESIS_CORPUS_SOURCES", "")     # empty → whole corpus, no scope
    assert atk._corpus_sources() == []


def test_src_filter_scopes_when_sources_set_and_is_empty_when_not(monkeypatch):
    monkeypatch.setenv("EIGEN_THESIS_CORPUS_SOURCES", "arxiv,openalex")
    params = ["demo"]
    clause = atk._src_filter(params)
    assert "lower(source_key) = ANY($2)" in clause and params[-1] == ["arxiv", "openalex"]
    monkeypatch.setenv("EIGEN_THESIS_CORPUS_SOURCES", "")
    params2 = ["demo"]
    assert atk._src_filter(params2) == "" and params2 == ["demo"]


@pytest.mark.asyncio
async def test_corpus_hits_unions_both_legs_and_dedupes_by_block(monkeypatch):
    monkeypatch.setenv("EIGEN_THESIS_CORPUS_SOURCES", "arxiv")

    class FakeConn:
        async def fetch(self, sql, *params):
            if "embedding <=>" in sql:                       # semantic leg
                return [{"document_id": "d1", "block_id": "b1"},   # overlaps keyword
                        {"document_id": "d2", "block_id": "b2"}]
            return [{"document_id": "d1", "block_id": "b1"},        # dup of semantic
                    {"document_id": "d3", "block_id": "b3"}]        # keyword leg

    rows = await atk._corpus_hits(FakeConn(), "demo", "Cerebras wafer scale inference", vec=[0.1, 0.2])
    keys = {(r["document_id"], r["block_id"]) for r in rows}
    assert keys == {("d1", "b1"), ("d2", "b2"), ("d3", "b3")}     # union, block d1/b1 counted once
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_corpus_hits_keyword_only_when_no_vector(monkeypatch):
    monkeypatch.setenv("EIGEN_THESIS_CORPUS_SOURCES", "arxiv")
    seen = {"semantic": False, "keyword": False}

    class FakeConn:
        async def fetch(self, sql, *params):
            if "embedding <=>" in sql:
                seen["semantic"] = True
            else:
                seen["keyword"] = True
            return []

    await atk._corpus_hits(FakeConn(), "demo", "Cerebras inference customers", vec=None)
    assert seen["keyword"] and not seen["semantic"]              # no embedding → keyword carries it
