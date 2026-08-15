"""Offline tests for multi-query retrieval dispatch (recall + repeat bonus)."""
from __future__ import annotations

import asyncio

from eigen_kernel.contract.dto import RetrievalRequest
from eigen_kernel.retrieval.dispatch import multi_query_retrieve
from eigen_kernel.retrieval.memory import IndexedBlock, InMemoryRetrievalSource


def _src() -> InMemoryRetrievalSource:
    src = InMemoryRetrievalSource()
    src.add(IndexedBlock(block_id="eq", document_id="d", tenant_id="t",
                         text="The approved return on equity was set at nine point six percent."))
    src.add(IndexedBlock(block_id="capstruct", document_id="d", tenant_id="t",
                         text="The capital structure reflects an equity ratio consistent with peers."))
    return src


def _run(src, req, variants):
    return asyncio.run(multi_query_retrieve(src, req, variants))


def test_multi_query_improves_recall() -> None:
    src = _src()
    base = RetrievalRequest(query="return on equity", tenant_id="t", k=10)
    # the original query alone misses the capital-structure block; a variant finds it
    ids = {h.block_id for h in _run(src, base, ["equity ratio capital structure"])}
    assert ids == {"eq", "capstruct"}


def test_repeat_bonus_prefers_multi_variant_hits() -> None:
    # "both" is retrieved by the original AND the variant (rank 2 in each);
    # "a1"/"b1" are each retrieved by only one query (rank 1). The repeat bonus +
    # cross-query agreement lifts "both" to the top over the single-query rank-1s.
    src = InMemoryRetrievalSource()
    src.add(IndexedBlock(block_id="both", document_id="d", tenant_id="t", text="alpha beta together"))
    src.add(IndexedBlock(block_id="a1", document_id="d", tenant_id="t", text="alpha alpha alpha"))
    src.add(IndexedBlock(block_id="b1", document_id="d", tenant_id="t", text="beta beta beta"))
    base = RetrievalRequest(query="alpha", tenant_id="t", k=10)
    hits = _run(src, base, ["beta"])
    assert hits[0].block_id == "both"
    assert hits[0].extra["queries_hit"] == 2
