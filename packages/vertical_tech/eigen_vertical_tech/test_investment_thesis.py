"""Investment-thesis connector: the corpus slice behind 'Discover theses'. A VC thesis is a named
investor's interpretation — its own slice (source_kind=investment_thesis), tiered as opinion, never
controlling."""
from __future__ import annotations

import asyncio

from eigen_vertical_tech.authority import TechAuthorityPolicy
from eigen_vertical_tech.connectors.investment_thesis import THESES, InvestmentThesisConnector
from eigen_vertical_tech.evidence_kind import classify

ITEM = {"guid": "t1", "link": "https://www.nfx.com/post/marketplace-thesis",
        "title": "Why we invested in vertical marketplaces", "author": "James Currier",
        "publication": "", "published": "Tue, 10 Feb 2026 09:00:00 GMT",
        "content": "<p>Vertical marketplaces win by owning the transaction, not just the listing.</p>",
        "_firm": "NFX", "_kind": "vc_thesis"}


def test_thesis_is_its_own_slice_and_never_controlling():
    c = InvestmentThesisConnector(items=[ITEM])
    ent = asyncio.run(c.discover_entities({}))[0]
    assert ent.facets["source_kind"] == "investment_thesis"    # a distinct corpus slice, not "essay"
    assert ent.facets["doc_kind"] == "investment_thesis"       # discovery search scopes on this
    assert ent.facets["firm"] == "NFX"
    assert ent.facets["thesis_kind"] == "vc_thesis"
    kind = classify("investment_thesis", ent.facets)
    pol = TechAuthorityPolicy()
    assert kind == "expert_analysis"
    assert pol.is_evidence(kind) is True
    assert pol.is_controlling(kind) is False                   # a thesis is intent/opinion, never a fact


def test_the_firm_fills_the_publication_when_the_feed_omits_it():
    ent = asyncio.run(InvestmentThesisConnector(items=[ITEM]).discover_entities({}))[0]
    assert ent.facets["publication"] == "NFX"                  # feed had none; curation filled it


def test_the_thesis_body_reaches_the_document():
    c = InvestmentThesisConnector(items=[ITEM])
    doc = asyncio.run(c.list_documents(asyncio.run(c.discover_entities({}))[0]))[0]
    body = asyncio.run(c.fetch_artifact(doc)).decode()
    assert "owning the transaction" in body


def test_every_curated_thesis_source_is_https_and_typed():
    assert THESES, "the allowlist must not be empty"
    for url, (firm, kind) in THESES.items():
        assert url.startswith("https://"), url
        assert firm and kind in ("vc_thesis", "market_map", "rfs", "analysis"), (firm, kind)
