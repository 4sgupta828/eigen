"""Tests for the corpus → claim-graph extraction JOB (Task 2b).

TWO layers, per the brief:

  * OFFLINE UNIT (no DB, no network): the cost-projection + cap math and the pure
    subject-name / slug / heading helpers. Always runs.

  * DSN-GATED INTEGRATION (skipped unless EIGEN_CORPUS_DSN is set — mirrors
    `test_claimgraph_integration.py`): seeds a few fake `rs_block` YC rows and
    MONKEYPATCHES `eigen_vertical_tech.claim_extract.extract_typed_claims` to return
    canned typed claims, so NO network / NO live LLM call happens. It asserts the JOB
    WIRING end to end: dry-run writes nothing, live writes entities+claims+evidence and
    `population()` finds the company grounded, and a cap-abort writes nothing.

WHAT THE MONKEYPATCHED TEST PROVES vs NOT (Rule 3): replacing the extractor with a canned
stub proves the JOB's mechanics — block selection, the source_key relevance gate, strong-id
subject resolution, value/category/`__unresolved` object resolution, deterministic
upsert of entity+claim+evidence with the right authority tier, the run ledger, and the
cost caps. It proves NOTHING about real extraction QUALITY (predicate choice, span/entail
grounding) — that is the extractor's own held-out concern (Task 2a's tests) and the live
eval (Task 5). We monkeypatch the extractor (not two LLM layers) precisely to keep this
test about the job.

    EIGEN_CORPUS_DSN=postgresql://strata:strata@localhost:5433/eigen_test \
      /Users/sgupta/eigen/.venv/bin/python -m pytest apps/api/test_claim_extract_job.py -q
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from api.claim_extract_job import (
    _first_heading,
    _slug_of,
    _subject_name,
    project_cost,
    run_claim_extraction,
)
from api.claimgraph import ClaimGraphStore, normalize_name


# --------------------------------------------------------------------------- #
# OFFLINE UNIT — cost/cap math + pure helpers (no DB, no network)             #
# --------------------------------------------------------------------------- #
def test_project_cost_one_call_per_block() -> None:
    # this extractor is ONE call per block → projected_calls == blocks_considered exactly.
    p = project_cost(120, max_blocks=500, max_llm_calls=200, max_usd=5.0,
                     price_per_call_usd=0.01)
    assert p["projected_calls"] == 120
    assert p["est_usd"] == 1.2
    assert p["over_caps"] == []          # within all caps


def test_project_cost_aborts_on_max_blocks() -> None:
    p = project_cost(600, max_blocks=500, max_llm_calls=10_000, max_usd=10_000,
                     price_per_call_usd=0.01)
    assert any("max_blocks" in r for r in p["over_caps"])


def test_project_cost_aborts_on_max_llm_calls() -> None:
    p = project_cost(250, max_blocks=10_000, max_llm_calls=200, max_usd=10_000,
                     price_per_call_usd=0.01)
    assert any("max_llm_calls" in r for r in p["over_caps"])


def test_project_cost_aborts_on_max_usd() -> None:
    # 300 calls * $0.05 = $15 > $5 cap → abort on cost even though block/call counts fit.
    p = project_cost(300, max_blocks=10_000, max_llm_calls=10_000, max_usd=5.0,
                     price_per_call_usd=0.05)
    assert p["est_usd"] == 15.0
    assert any("max_usd" in r for r in p["over_caps"])


def test_project_cost_zero_blocks() -> None:
    p = project_cost(0, max_blocks=500, max_llm_calls=200, max_usd=5.0,
                     price_per_call_usd=0.01)
    assert p["projected_calls"] == 0 and p["est_usd"] == 0.0 and p["over_caps"] == []


def test_pure_helpers() -> None:
    assert _slug_of("yc:acme") == "acme"
    assert _slug_of("yc:acme-labs") == "acme-labs"
    assert _slug_of("noprefix") == "noprefix"
    assert _first_heading("# Acme\nbody") == "Acme"
    assert _first_heading("no heading here") == ""
    # subject name precedence: title > first heading > slug
    assert _subject_name("Acme Inc", "# Heading\nx", "acme") == "Acme Inc"
    assert _subject_name("", "# Heading\nx", "acme") == "Heading"
    assert _subject_name("", "no heading", "acme") == "acme"


# --------------------------------------------------------------------------- #
# DSN-GATED INTEGRATION — job wiring, offline extractor stub                  #
# --------------------------------------------------------------------------- #
DSN = os.environ.get("EIGEN_CORPUS_DSN")
integration = pytest.mark.skipif(
    not DSN, reason="set EIGEN_CORPUS_DSN for claim-extract-job integration")

_CAT_NAME = "Developer Tools"
_CAT_NORM = normalize_name(_CAT_NAME)            # 'developer tools'


def _fake_extractor(calls: list[str]):
    """Return an async stand-in for `extract_typed_claims` that records each call's subject
    and returns canned typed claims (already in the extractor's OUTPUT shape). No network."""
    async def fake_extract(*, block_text, subject_name, predicates, client=None, model=None):
        calls.append(subject_name)
        if subject_name == "Acme":
            return [
                {"predicate": "operates_in_category", "object_kind": "entity",
                 "object_value": "", "object_entity_name": _CAT_NAME,
                 "quote": "Acme operates in the Developer Tools category"},
                {"predicate": "offers_product", "object_kind": "value",
                 "object_value": "Acme CLI", "object_entity_name": "",
                 "quote": "Acme offers Acme CLI"},
                {"predicate": "compared_to", "object_kind": "entity",
                 "object_value": "", "object_entity_name": "Widgets Inc",
                 "quote": "Acme is often compared to Widgets Inc"},
            ]
        if subject_name == "Beta":
            return [
                {"predicate": "operates_in_category", "object_kind": "entity",
                 "object_value": "", "object_entity_name": "Fintech",
                 "quote": "Beta operates in Fintech"},
            ]
        return []
    return fake_extract


async def _seed_yc_blocks(tenant: str) -> None:
    """Seed 2 real YC blocks + 1 whitespace-only block (must be skipped) into rs_block."""
    from eigen_kernel.retrieval.postgres import PostgresRetrievalSource
    src = PostgresRetrievalSource(DSN)
    try:
        await src.ensure_schema()
        facets = {"source_kind": "reference", "entity_type": "company"}
        await src.upsert_block(
            tenant_id=tenant, document_id="yc:acme", block_id="b1",
            text="# Acme\nAcme operates in the Developer Tools category. "
                 "Acme offers Acme CLI. Acme is often compared to Widgets Inc.",
            facets=facets, document_title="Acme", content_type="text", source_key="yc")
        await src.upsert_block(
            tenant_id=tenant, document_id="yc:beta", block_id="b1",
            text="# Beta\nBeta operates in Fintech.",
            facets=facets, document_title="Beta", content_type="text", source_key="yc")
        # whitespace-only text → must be skipped by selection (blocks_considered stays 2)
        await src.upsert_block(
            tenant_id=tenant, document_id="yc:gamma", block_id="b1", text="   ",
            facets=facets, document_title="Gamma", content_type="text", source_key="yc")
    finally:
        await src.close()


@integration
def test_dry_run_writes_nothing_and_makes_no_llm_call(monkeypatch) -> None:
    async def body():
        tenant = "t_" + uuid.uuid4().hex[:12]
        await _seed_yc_blocks(tenant)
        calls: list[str] = []
        import eigen_vertical_tech.claim_extract as ce
        monkeypatch.setattr(ce, "extract_typed_claims", _fake_extractor(calls))

        res = await run_claim_extraction(
            dsn=DSN, source_keys=["yc"], tenant_id=tenant, dry_run=True)

        assert res["status"] == "dry_run"
        assert res["dry_run"] is True
        assert res["blocks_considered"] == 2            # whitespace block skipped
        assert res["projected_calls"] == 2              # projection present
        assert res["est_cost_usd"] == 0.02
        assert res["claims_emitted"] == 0
        assert calls == []                              # NO LLM/extractor call in dry run

        store = ClaimGraphStore(DSN)
        try:
            pool = await store._get_pool()
            async with pool.acquire() as conn:
                n_claims = await conn.fetchval(
                    "SELECT count(*) FROM rs_claim WHERE tenant_id=$1", tenant)
                n_ent = await conn.fetchval(
                    "SELECT count(*) FROM rs_entity WHERE tenant_id=$1", tenant)
                ledger = await conn.fetchrow(
                    "SELECT status FROM rs_extraction_run WHERE run_id=$1", res["run_id"])
            assert n_claims == 0                         # nothing written
            assert n_ent == 0
            assert ledger["status"] == "dry_run"
        finally:
            await store.close()
    asyncio.run(body())


@integration
def test_live_writes_entities_claims_evidence_and_population(monkeypatch) -> None:
    async def body():
        tenant = "t_" + uuid.uuid4().hex[:12]
        await _seed_yc_blocks(tenant)
        calls: list[str] = []
        import eigen_vertical_tech.claim_extract as ce
        monkeypatch.setattr(ce, "extract_typed_claims", _fake_extractor(calls))

        res = await run_claim_extraction(
            dsn=DSN, source_keys=["yc"], tenant_id=tenant, dry_run=False)

        assert res["status"] == "done"
        assert res["blocks_considered"] == 2
        assert res["extract_calls"] == 2                 # one call per block
        assert sorted(calls) == ["Acme", "Beta"]         # extractor called per subject
        assert res["claims_emitted"] == 4                # 3 (Acme) + 1 (Beta)

        store = ClaimGraphStore(DSN)
        try:
            pool = await store._get_pool()
            async with pool.acquire() as conn:
                # subject company (strong-id), category node, and __unresolved company node
                acme = await conn.fetchrow(
                    "SELECT kind, name FROM rs_entity WHERE entity_id='yc:acme' AND tenant_id=$1",
                    tenant)
                cat = await conn.fetchrow(
                    "SELECT kind, name FROM rs_entity WHERE entity_id=$1 AND tenant_id=$2",
                    "category:" + _CAT_NORM, tenant)
                unresolved = await conn.fetchrow(
                    "SELECT kind, name FROM rs_entity WHERE entity_id=$1 AND tenant_id=$2",
                    "__unresolved:widgets", tenant)
                # evidence carries the YC authority tier (verified_structured → rank 5)
                ev = await conn.fetchrow(
                    "SELECT authority_tier, evidence_kind, block_id FROM rs_claim_evidence "
                    "WHERE tenant_id=$1 AND document_id='yc:acme' LIMIT 1", tenant)
                ledger = await conn.fetchrow(
                    "SELECT status, blocks_considered, extract_calls, claims_emitted, est_cost_usd "
                    "FROM rs_extraction_run WHERE run_id=$1", res["run_id"])
            assert acme["kind"] == "company" and acme["name"] == "Acme"
            assert cat is not None and cat["kind"] == "category" and cat["name"] == _CAT_NAME
            assert unresolved is not None and unresolved["kind"] == "company"
            assert ev["authority_tier"] == 5 and ev["evidence_kind"] == "verified_structured"
            assert ev["block_id"] == "b1"                # real block id → span-gate re-verifiable
            assert ledger["status"] == "done"
            assert ledger["blocks_considered"] == 2
            assert ledger["extract_calls"] == 2
            assert ledger["claims_emitted"] == 4
            assert float(ledger["est_cost_usd"]) == 0.02

            # population read: who operates in 'developer tools' → exactly Acme, grounded.
            pop = await store.population("operates_in_category", _CAT_NORM, tenant_id=tenant)
            assert len(pop) == 1
            assert pop[0]["entity_id"] == "yc:acme"
            assert pop[0]["name"] == "Acme"
            assert pop[0]["evidence"]["document_id"] == "yc:acme"
            assert pop[0]["evidence"]["block_id"] == "b1"
        finally:
            await store.close()
    asyncio.run(body())


@integration
def test_cap_abort_writes_nothing(monkeypatch) -> None:
    async def body():
        tenant = "t_" + uuid.uuid4().hex[:12]
        await _seed_yc_blocks(tenant)
        calls: list[str] = []
        import eigen_vertical_tech.claim_extract as ce
        monkeypatch.setattr(ce, "extract_typed_claims", _fake_extractor(calls))

        # 2 eligible blocks > max_blocks=1 → abort BEFORE any spend, even in live mode.
        res = await run_claim_extraction(
            dsn=DSN, source_keys=["yc"], tenant_id=tenant, dry_run=False, max_blocks=1)

        assert res["status"] == "aborted"
        assert res["extract_calls"] == 0
        assert res["claims_emitted"] == 0
        assert any("max_blocks" in r for r in res["abort_reason"])
        assert calls == []                               # never called the extractor

        store = ClaimGraphStore(DSN)
        try:
            pool = await store._get_pool()
            async with pool.acquire() as conn:
                n_claims = await conn.fetchval(
                    "SELECT count(*) FROM rs_claim WHERE tenant_id=$1", tenant)
                n_ent = await conn.fetchval(
                    "SELECT count(*) FROM rs_entity WHERE tenant_id=$1", tenant)
                ledger = await conn.fetchrow(
                    "SELECT status FROM rs_extraction_run WHERE run_id=$1", res["run_id"])
            assert n_claims == 0 and n_ent == 0          # nothing written on abort
            assert ledger["status"] == "aborted"
        finally:
            await store.close()
    asyncio.run(body())
