"""Voices end to end against a real Postgres (skipped without EIGEN_STARTUPS_TEST_DSN).

Proves the three things that only a database can prove: a chapter document really does split into one
block per chapter, keyword search really does find a moment with no embeddings anywhere, and the
binder really does refuse the wrong company while accepting the right one.
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest

DSN = os.environ.get("EIGEN_STARTUPS_TEST_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="needs EIGEN_STARTUPS_TEST_DSN")

EPISODE = {
    "guid": "ep-42", "link": "https://show.fm/ep/42", "publication": "20VC",
    "title": "20VC: Rebuilding after the seed round with Ryan Petersen, CEO @ Flexport",
    "published": "Tue, 02 Sep 2026 10:00:00 GMT",
    "summary": ("<p>(00:00) Cold open on the crash<br/>"
                "(02:25) How the first product died<br/>"
                "13:00 Why the Series A nearly killed us<br/>"
                "(48:10) What we would do differently</p>"),
}
ESSAY = {
    "guid": "essay-1", "link": "https://avc.com/seed-pricing", "publication": "AVC",
    "title": "What I got wrong about seed pricing", "author": "Fred Wilson",
    "published": "Wed, 03 Sep 2026 12:00:00 GMT",
    "content": "<p>We priced our seed round too high in 2021 and it cost the company a full year.</p>",
    "_writer": "Fred Wilson", "_role": "investor",
}


def _run(coro):
    return asyncio.run(coro)


async def _setup():
    import asyncpg
    from eigen_kernel.retrieval.postgres import PostgresRetrievalSource
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
    pg = PostgresRetrievalSource(DSN, dim=1536, table="rs_block")
    await pg.ensure_schema()
    async with pool.acquire() as c:
        await c.execute("DELETE FROM rs_block WHERE source_key IN ('show_notes','founder_essay')")
    return pool, pg


async def _ingest(pg):
    from api.voices.ingest import ingest_voices
    from eigen_vertical_tech.connectors.founder_essay import FounderEssayConnector
    from eigen_vertical_tech.connectors.show_notes import ShowNotesConnector

    class M:                     # a manifest stub carrying fixture-injected connectors: no network
        connectors = {"show_notes": ShowNotesConnector(episodes=[EPISODE]),
                      "founder_essay": FounderEssayConnector(items=[ESSAY])}
    return await ingest_voices(M(), pg, tenant_id="default", limit=10)


def test_a_chapter_list_becomes_one_block_per_chapter_with_no_embeddings():
    async def go():
        pool, pg = await _setup()
        blocks = await _ingest(pg)
        assert blocks["show_notes"] >= 4 and blocks["founder_essay"] >= 1
        async with pool.acquire() as c:
            rows = await c.fetch("SELECT text, embedding FROM rs_block WHERE source_key='show_notes' "
                                 "AND text LIKE '[%' ORDER BY text")
            assert len(rows) == 4                        # four chapters → four blocks, not one blob
            assert all(r["embedding"] is None for r in rows)     # keyword-only ingest, zero spend
            assert any("?t=780" in r["text"] for r in rows)      # the 13:00 chapter deep-links
        await pool.close()
    _run(go())


def test_keyword_search_finds_the_moment_and_labels_the_pointer():
    async def go():
        from api.voices.search import build_query, moment
        pool, pg = await _setup()
        await _ingest(pg)
        sql, params = build_query(q="series a", limit=10)
        async with pool.acquire() as c:
            rows = [dict(r) for r in await c.fetch(sql, *params)]
        assert rows, "keyword search must work with no embedding provider at all"
        ms = [moment({**r, "facets": json.loads(r["facets"]) if isinstance(r["facets"], str)
                      else r["facets"]}) for r in rows]
        hit = next(m for m in ms if "Series A" in m["text"])
        assert hit["kind"] == "chapter" and hit["quotable"] is False and hit["t_start"] == 780
        assert hit["show"] == "20VC" and hit["speaker"] == "Ryan Petersen"
        await pool.close()
    _run(go())


def test_the_binder_attaches_the_right_company_and_refuses_the_wrong_one():
    async def go():
        from api.startups.store import StartupStore
        from api.voices.ingest import bind_guests
        pool, pg = await _setup()
        await _ingest(pg)

        async def getter():
            return pool
        store = StartupStore(getter)
        await store.ensure_schema()
        async with pool.acquire() as c:
            await c.execute("DELETE FROM su_founder WHERE company_id IN ('flexport.com','doordash.com')")
            await c.execute("DELETE FROM su_company WHERE id IN ('flexport.com','doordash.com')")
        await store.upsert_company({"id": "flexport.com", "name": "Flexport", "sources": ["test"]})
        await store.upsert_company({"id": "doordash.com", "name": "DoorDash", "sources": ["test"]})
        await store.replace_founders("flexport.com", "test", [{"name": "Ryan Petersen"}])
        await store.replace_founders("doordash.com", "test", [{"name": "Tony Xu"}])

        stats = await bind_guests(pool)
        assert stats["guest_and_company"] == 1
        async with pool.acquire() as c:
            f = await c.fetchval("SELECT facets FROM rs_block WHERE document_id LIKE '%ep-42%' LIMIT 1")
            facets = json.loads(f) if isinstance(f, str) else f
            assert facets["company_id"] == "flexport.com"      # the guest's own company, bound
            assert facets["person"] == "Ryan Petersen"
            # and nothing bound DoorDash, whose founder was never the guest
            n = await c.fetchval("SELECT count(*) FROM rs_block WHERE facets->>'company_id' = 'doordash.com'")
            assert n == 0
        await pool.close()
    _run(go())
