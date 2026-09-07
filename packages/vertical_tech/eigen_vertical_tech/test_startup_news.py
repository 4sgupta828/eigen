"""Startup press: reported activity, tiered as reporting and never as attestation."""
from __future__ import annotations

import asyncio

from eigen_vertical_tech import press_doc
from eigen_vertical_tech.authority import TechAuthorityPolicy
from eigen_vertical_tech.connectors.startup_news import FEEDS, StartupNewsConnector
from eigen_vertical_tech.evidence_kind import classify

ITEM = {"guid": "n1", "link": "https://news.crunchbase.com/acme-raises",
        "title": "Acme raises $12M Series A led by a16z", "author": "A Reporter",
        "publication": "Crunchbase News", "published": "Wed, 03 Sep 2026 12:00:00 GMT",
        "content": "<p>Acme, an inference infrastructure startup, said it raised &#36;12 million.</p>"}


def test_press_is_analysis_and_never_controlling():
    k = classify("startup_news", press_doc.facets(ITEM))
    pol = TechAuthorityPolicy()
    assert k == "analysis"
    assert pol.rank(k) == 4                        # above a preprint, below a filing
    assert pol.is_controlling(k) is False          # reporting a round is not attesting one
    assert pol.outranks("primary_filing", k) is True


def test_the_article_reaches_the_document_with_entities_decoded():
    md = press_doc.to_markdown(ITEM)
    assert "raised $12 million" in md              # &#36; decoded, tags stripped
    assert "reported, not audited" in md           # the register is written into the document
    assert "URL: https://news.crunchbase.com/acme-raises" in md


def test_the_curated_publication_name_wins_over_the_feeds_own_title():
    async def go():
        c = StartupNewsConnector(items=[dict(ITEM, publication="Crunchbase News | Data")])
        ents = await c.discover_entities({})
        return ents[0].facets
    f = asyncio.run(go())
    assert f["publication"].startswith("Crunchbase News")
    assert f["url"] == "https://news.crunchbase.com/acme-raises" and f["year"] == "2026"


def test_a_beat_narrows_the_fetch_but_never_to_nothing():
    assert set(StartupNewsConnector._select("europe")) < set(FEEDS)
    assert StartupNewsConnector._select("europe")                       # non-empty
    assert set(StartupNewsConnector._select("anything else")) == set(FEEDS)


def test_every_feed_declares_a_publication_and_a_beat():
    assert FEEDS
    for url, (pub, beat) in FEEDS.items():
        assert url.startswith("https://") and pub and beat, url
