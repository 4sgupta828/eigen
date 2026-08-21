"""Integration tests for ClaimGraphStore — DB round-trips.

Skipped unless EIGEN_CORPUS_DSN points at a Postgres, so the offline suite stays
green without a DB (mirrors `eigen_kernel/retrieval/test_postgres.py`).

    EIGEN_CORPUS_DSN=postgresql://strata:strata@localhost:5433/eigen_test \
      /Users/sgupta/eigen/.venv/bin/python -m pytest apps/api/test_claimgraph_integration.py -q

Each test runs its whole async body in ONE event loop (an asyncpg pool is bound to
the loop that created it). Tests use unique per-run ids and never TRUNCATE, so they
are safe against a populated claim graph.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from api.claimgraph import ClaimGraphStore, normalize_name

DSN = os.environ.get("EIGEN_CORPUS_DSN")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DSN, reason="set EIGEN_CORPUS_DSN for claim-graph integration"),
]

_ALL_TABLES = ["rs_entity", "rs_entity_alias", "rs_claim", "rs_claim_evidence",
               "rs_claim_resolution", "rs_predicate", "rs_extraction_run"]
_SEED_PREDICATES = ["operates_in_category", "offers_product", "targets_customer",
                    "uses_technology", "claims_differentiator", "compared_to"]


def _uid(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex[:12]}"


def test_ensure_schema_creates_tables_and_seeds_predicates() -> None:
    async def body():
        store = ClaimGraphStore(DSN)
        try:
            await store.ensure_schema()
            await store.ensure_schema()   # idempotent second call
            pool = await store._get_pool()
            async with pool.acquire() as conn:
                for t in _ALL_TABLES:
                    exists = await conn.fetchval("SELECT to_regclass($1)", t)
                    assert exists is not None, f"table {t} missing"
                active = {r["name"] for r in await conn.fetch(
                    "SELECT name FROM rs_predicate WHERE status='active'")}
            assert set(_SEED_PREDICATES) <= active
        finally:
            await store.close()
    asyncio.run(body())


def test_entity_upsert_idempotent_and_status_preserved() -> None:
    async def body():
        store = ClaimGraphStore(DSN)
        try:
            eid = _uid("domain")
            await store.upsert_entity(eid, "company", "Acme Inc", primary_domain="acme.com")
            # suppress, then re-upsert — status must NOT be reset to active
            pool = await store._get_pool()
            async with pool.acquire() as conn:
                await conn.execute("UPDATE rs_entity SET status='suppressed' WHERE entity_id=$1", eid)
            await store.upsert_entity(eid, "company", "Acme Incorporated", primary_domain="acme.io")
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT name, primary_domain, status FROM rs_entity WHERE entity_id=$1", eid)
                n = await conn.fetchval("SELECT count(*) FROM rs_entity WHERE entity_id=$1", eid)
            assert n == 1                                   # idempotent, no dup
            assert row["name"] == "Acme Incorporated"       # refreshed
            assert row["primary_domain"] == "acme.io"
            assert row["status"] == "suppressed"            # never resurrected
        finally:
            await store.close()
    asyncio.run(body())


def test_alias_roundtrip() -> None:
    async def body():
        store = ClaimGraphStore(DSN)
        try:
            eid = _uid("domain")
            base = "Acmeco" + uuid.uuid4().hex[:8]            # unique so alias_norm can't collide
            await store.upsert_entity(eid, "company", base + " Inc")
            await store.add_alias(base + ", Inc.", eid, source="test")
            assert await store.resolve_alias(base.lower()) == eid          # normalized match
            assert await store.resolve_alias(base + " LLC") == eid         # suffix-stripped match
            assert await store.resolve_alias("nonexistent-" + uuid.uuid4().hex) is None
        finally:
            await store.close()
    asyncio.run(body())


def test_claim_upsert_idempotent() -> None:
    async def body():
        store = ClaimGraphStore(DSN)
        try:
            eid = _uid("domain")
            cat = _uid("category")
            await store.upsert_entity(eid, "company", "Acme")
            c1 = await store.upsert_claim(subject_id=eid, predicate="operates_in_category",
                                          object_kind="entity", object_entity_id=cat,
                                          confidence=0.9)
            c2 = await store.upsert_claim(subject_id=eid, predicate="operates_in_category",
                                          object_kind="entity", object_entity_id=cat,
                                          confidence=0.5)
            assert c1 == c2                                  # same logical claim → same id
            pool = await store._get_pool()
            async with pool.acquire() as conn:
                n = await conn.fetchval("SELECT count(*) FROM rs_claim WHERE claim_id=$1", c1)
                conf = await conn.fetchval("SELECT confidence FROM rs_claim WHERE claim_id=$1", c1)
            assert n == 1                                    # no dup
            assert float(conf) == 0.5                        # confidence refreshed
        finally:
            await store.close()
    asyncio.run(body())


def test_evidence_dedup() -> None:
    async def body():
        store = ClaimGraphStore(DSN)
        try:
            eid = _uid("domain")
            await store.upsert_entity(eid, "company", "Acme")
            cid = await store.upsert_claim(subject_id=eid, predicate="offers_product",
                                           object_kind="value", object_value="Widget")
            doc = _uid("doc")
            e1 = await store.add_evidence(cid, doc, "b1", "Acme  ships a Widget", authority_tier=2)
            # same block + reflowed/case-variant quote → same quote_hash → dedup no-op
            e2 = await store.add_evidence(cid, doc, "b1", "acme ships a widget", authority_tier=2)
            assert e1 == e2
            pool = await store._get_pool()
            async with pool.acquire() as conn:
                n = await conn.fetchval("SELECT count(*) FROM rs_claim_evidence WHERE claim_id=$1", cid)
            assert n == 1
        finally:
            await store.close()
    asyncio.run(body())


def test_population_and_mark_stale() -> None:
    async def body():
        store = ClaimGraphStore(DSN)
        try:
            eid = _uid("domain")
            await store.upsert_entity(eid, "company", "Zeta Labs")
            obj_norm = "cat-" + uuid.uuid4().hex[:10]       # unique so population is clean
            cid = await store.upsert_claim(subject_id=eid, predicate="operates_in_category",
                                           object_kind="entity",
                                           object_entity_id="category:" + obj_norm,
                                           object_norm=obj_norm, confidence=0.8)
            doc = _uid("doc")
            await store.add_evidence(cid, doc, "b1", "Zeta operates in the space",
                                     authority_tier=3, source_key="reg")
            pop = await store.population("operates_in_category", obj_norm)
            assert len(pop) == 1
            row = pop[0]
            assert row["entity_id"] == eid
            assert row["name"] == "Zeta Labs"
            assert row["claim_id"] == cid
            assert row["evidence"]["document_id"] == doc
            assert row["evidence"]["block_id"] == "b1"

            # entity_claims read
            claims = await store.entity_claims(eid, predicates=["operates_in_category"])
            assert len(claims) == 1
            assert claims[0]["evidence"]["quote"] == "Zeta operates in the space"

            # GC coupling: mark the doc's evidence stale → excluded from population
            flipped = await store.mark_evidence_stale([doc])
            assert flipped == 1
            assert await store.mark_evidence_stale([doc]) == 0   # already stale, no-op
            pop2 = await store.population("operates_in_category", obj_norm)
            # grounding+GC invariant: a claim with no ACTIVE evidence is EXCLUDED
            # (not returned with null evidence) — excluded until re-extracted.
            assert pop2 == []
        finally:
            await store.close()
    asyncio.run(body())


def test_run_ledger() -> None:
    async def body():
        store = ClaimGraphStore(DSN)
        try:
            rid = _uid("run")
            await store.record_run(rid, source_keys="reg", params={"dry": True})
            await store.finish_run(rid, status="done", claims_emitted=7, extract_calls=3,
                                   est_cost_usd=0.0012)
            pool = await store._get_pool()
            async with pool.acquire() as conn:
                r = await conn.fetchrow(
                    "SELECT status, claims_emitted, extract_calls, finished_at "
                    "FROM rs_extraction_run WHERE run_id=$1", rid)
            assert r["status"] == "done"
            assert r["claims_emitted"] == 7
            assert r["extract_calls"] == 3
            assert r["finished_at"] is not None
            with pytest.raises(ValueError):
                await store.finish_run(rid, bogus_counter=1)
        finally:
            await store.close()
    asyncio.run(body())
