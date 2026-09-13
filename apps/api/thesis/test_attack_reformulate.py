from __future__ import annotations
import pytest
from api.thesis import attack as atk


@pytest.mark.asyncio
async def test_reformulate_adds_angles_and_keeps_the_claim_first():
    async def llm(system, user):
        return {"queries": ["Cerebras production inference customers 2025",
                            "Cerebras vs Nvidia enterprise deployment",
                            "Cerebras revenue named customers", "Cerebras"],  # dup of claim → deduped
                "research_relevant": False}
    ref = await atk.reformulate(llm, claim="Cerebras", context="thesis")
    qs = ref["queries"]
    assert qs[0] == "Cerebras"                              # literal claim always leads
    assert "Cerebras production inference customers 2025" in qs
    assert len(qs) == len(set(q.lower() for q in qs))       # de-duped
    assert len(qs) <= 5
    assert ref["research_relevant"] is False               # the model's judgment is carried through


@pytest.mark.asyncio
async def test_reformulate_falls_back_to_the_literal_claim():
    assert (await atk.reformulate(None, claim="X"))["queries"] == ["X"]
    async def boom(s, u): raise ValueError("down")
    assert (await atk.reformulate(boom, claim="X"))["queries"] == ["X"]


@pytest.mark.asyncio
async def test_reformulate_relevance_falls_back_to_heuristic_without_a_model():
    # No LLM → the keyword heuristic decides: a technical claim is research-relevant, a market one is not
    assert (await atk.reformulate(None, claim="A new transformer architecture improves inference latency"))[
        "research_relevant"] is True
    assert (await atk.reformulate(None, claim="Enterprises are adopting the product and pricing is rising"))[
        "research_relevant"] is False


@pytest.mark.asyncio
async def test_reformulate_model_relevance_overrides_heuristic():
    # A claim with no technical tokens (heuristic → False) that the model rules research-relevant
    async def llm(system, user):
        return {"queries": ["q1"], "research_relevant": True}
    ref = await atk.reformulate(llm, claim="the approach generalizes across domains", context="")
    assert ref["research_relevant"] is True


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


def _row(tag, basis, host):
    return {"quote": tag, "basis": basis, "independence_key": host, "source_key": basis}


def test_merge_web_is_primary_papers_get_a_reserved_supplement():
    from api.thesis.attack import _merge_evidence
    web = [_row(f"w{i}", "web", f"site{i}.com") for i in range(8)]      # web can fill the whole side
    papers = [_row(f"p{i}", "corpus", f"doc{i}") for i in range(6)]
    merged = _merge_evidence(web, papers, cap=8, per_source_cap=2, papers_cap=3)
    n_web = sum(1 for r in merged if r["basis"] == "web")
    n_pap = sum(1 for r in merged if r["basis"] == "corpus")
    assert len(merged) == 8
    assert n_web == 5 and n_pap == 3          # web primary (5), papers a bounded supplement (3)


def test_merge_papers_backfill_when_web_is_thin():
    from api.thesis.attack import _merge_evidence
    web = [_row("w0", "web", "site0.com")]                              # web nearly silent
    papers = [_row(f"p{i}", "corpus", f"doc{i}") for i in range(6)]
    merged = _merge_evidence(web, papers, cap=8, per_source_cap=2, papers_cap=3)
    n_web = sum(1 for r in merged if r["basis"] == "web")
    n_pap = sum(1 for r in merged if r["basis"] == "corpus")
    assert n_web == 1 and n_pap == 6          # papers back-fill the empty slots, web still leads


def test_merge_no_papers_is_web_only():
    from api.thesis.attack import _merge_evidence
    web = [_row(f"w{i}", "web", f"site{i}.com") for i in range(4)]
    merged = _merge_evidence(web, [], cap=8, per_source_cap=2, papers_cap=3)
    assert len(merged) == 4 and all(r["basis"] == "web" for r in merged)
