"""Founder/investor essays: full-text first-person writing, tiered as a named person's opinion."""
from __future__ import annotations

import asyncio

from eigen_vertical_tech.authority import TechAuthorityPolicy
from eigen_vertical_tech.connectors.founder_essay import VOICES, FounderEssayConnector
from eigen_vertical_tech.evidence_kind import classify

ITEM = {"guid": "p1", "link": "https://avc.com/p1", "title": "What I got wrong about seed pricing",
        "author": "", "publication": "AVC", "published": "Wed, 03 Sep 2026 12:00:00 GMT",
        "content": "<p>We priced our seed round too high in 2021 and it cost the company a year.</p>",
        "_writer": "Fred Wilson", "_role": "investor"}


def test_essay_is_expert_analysis_and_never_controlling():
    c = FounderEssayConnector(items=[ITEM])
    ent = asyncio.run(c.discover_entities({}))[0]
    kind = classify("founder_essay", ent.facets)
    pol = TechAuthorityPolicy()
    assert kind == "expert_analysis"
    assert pol.is_evidence(kind) is True         # it IS evidence of what the person argues …
    assert pol.is_controlling(kind) is False     # … and never normative for a factual claim


def test_the_writer_and_their_role_survive_a_feed_with_no_byline():
    c = FounderEssayConnector(items=[ITEM])
    ent = asyncio.run(c.discover_entities({}))[0]
    assert ent.facets["author"] == "Fred Wilson"      # the feed omitted it; curation filled it in
    assert ent.facets["voice_role"] == "investor"     # an investor's view of pricing, not a founder's
    assert ent.facets["year"] == "2026"


def test_a_feeds_own_byline_wins_over_the_curated_name():
    rec = dict(ITEM, author="Guest Writer")
    ent = asyncio.run(FounderEssayConnector(items=[rec]).discover_entities({}))[0]
    assert ent.facets["author"] == "Guest Writer"


def test_the_body_reaches_the_document():
    c = FounderEssayConnector(items=[ITEM])
    doc = asyncio.run(c.list_documents(asyncio.run(c.discover_entities({}))[0]))[0]
    body = asyncio.run(c.fetch_artifact(doc)).decode()
    assert "priced our seed round too high" in body
    assert "expert analysis / opinion" in body        # the register is written into the document

def test_every_curated_voice_declares_a_role():
    assert VOICES, "the allowlist must not be empty"
    for url, (writer, role) in VOICES.items():
        assert url.startswith("https://"), url
        assert writer and role in ("founder", "investor", "operator", "analyst"), (writer, role)
