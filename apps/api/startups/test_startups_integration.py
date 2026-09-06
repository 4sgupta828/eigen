"""Integration test against a real Postgres with pgvector (skipped without EIGEN_STARTUPS_TEST_DSN): the store's
DDL, upserts, the SQL facet legs with musts + exclusions in SQL, counts with unknown, derive, and the router end
to end with a fake model and a fake embedder. No network, no spend."""
from __future__ import annotations

import asyncio
import os
from datetime import date

import pytest

DSN = os.environ.get("EIGEN_STARTUPS_TEST_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="needs EIGEN_STARTUPS_TEST_DSN")


def _run(coro):
    return asyncio.run(coro)


async def _store():
    import asyncpg
    from api.startups.store import StartupStore
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)

    async def getter():
        return pool
    s = StartupStore(getter)
    await s.ensure_schema()
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE su_fact, su_financing, su_founder, su_page, su_formd, su_list, su_job, su_company CASCADE")
    return s, pool


def _fake_embed(texts):
    out = []
    for t in texts:
        v = [0.0] * 1536
        v[0] = 1.0 if "bank" in t.lower() else 0.0
        v[1] = 1.0 if "robot" in t.lower() else 0.0
        v[2] = 0.3
        out.append(v)
    return out


def test_store_and_evaluator_end_to_end():
    async def main():
        from eigen_kernel.facets import Contract, evaluate
        from api.startups import pipeline
        from api.startups.routes import _Bound
        from api.startups.schema import SCHEMA, WEIGHTS
        s, pool = await _store()
        try:
            await s.upsert_company({"id": "acme.ai", "name": "Acme AI", "website": "https://acme.ai", "one_liner": "inference infra for banks", "hq": "Austin, TX", "sources": ["yc"], "yc_batch": "W24"})
            await s.upsert_company({"id": "robo.co", "name": "Robo", "website": "https://robo.co", "one_liner": "warehouse robots", "hq": "Boston, MA", "sources": ["yc"]})
            await s.upsert_company({"id": "ghost.io", "name": "Ghost", "website": "https://ghost.io", "one_liner": "bank fraud tooling", "sources": ["yc"]})
            for cid, t in (("acme.ai", "inference infra for banks"), ("robo.co", "warehouse robots"), ("ghost.io", "bank fraud tooling")):
                await s.set_embedding(cid, _fake_embed([t])[0])
            await s.replace_facts("acme.ai", "yc", [{"key": "program", "value": "yc", "quote": "q"}, {"key": "tech_area", "value": "ai_infra", "quote": "q"}, {"key": "tech_area", "value": "nonsense"}])
            await s.replace_facts("robo.co", "yc", [{"key": "program", "value": "yc"}, {"key": "tech_area", "value": "robotics"}])
            await s.replace_facts("ghost.io", "yc", [{"key": "tech_area", "value": "fintech"}])
            # a filing + a stated round → derived facts
            await s.insert_formd([{"accession": "A1", "file_num": "021-1", "cik": "77", "entity_name": "Acme AI, Inc.", "name_norm": "acme", "previous_names": [], "city": "Austin", "state": "TX",
                                   "entity_type": "Corporation", "year_inc": 2022, "industry": "Other Technology", "revenue_range": "$1 - $1,000,000", "is_amendment": False, "previous_accession": "",
                                   "filing_date": "2025-03-05", "sale_date": "2025-02-20", "offering_usd": 12e6, "sold_usd": 9.6e6, "investors_count": 7, "is_pooled": False, "is_operating": True, "officers": []}], "2025q1")
            stats = await pipeline.run_match(s, pipeline.Providers())
            assert stats["exact_name"] == 1
            c = await s.company("acme.ai")
            assert c["cik"] == "77" and c["filings"][0]["match_method"] == "exact_name" and c["financing"][0]["kind"] == "formd"
            await s.upsert_financing("acme.ai", {"kind": "site", "round_name": "series_a", "amount_usd": 12e6, "event_date": date(2025, 3, 1), "investors": ["a16z"], "lead": "a16z", "quote": "raised $12M Series A led by a16z", "source_url": "https://acme.ai/press"})
            await s.replace_founders("acme.ai", "site", [{"name": "Jane Doe", "title": "CEO", "prior_companies": ["stripe"], "quote": "q"}, {"name": "Bob", "title": "CTO"}])
            n = await pipeline.derive_one(s, "acme.ai")
            assert n >= 6
            facts = {f["key"]: f for f in (await s.company("acme.ai"))["facts"] if f["provenance"] == "derived"}
            assert facts["stage"]["value"] == "series_a" and facts["total_disclosed_funding"]["value"] == "5m_20m" and facts["revenue_range"]["value"] == "1_1m"
            assert facts["founder_count"]["value"] == "2" and facts["lead_investor"]["value"] == "a16z"
            # evaluator: must in SQL, exclusion in SQL, unknown counted, semantic leg ranks banks first
            bound = _Bound(s, {"program": ["yc"]}, _fake_embed)
            out = await evaluate(Contract(kind="company", text="banks", must={"tech_area": ["fintech", "ai_infra"]}), bound, SCHEMA, WEIGHTS)
            ids = [r["id"] for r in out["rows"]]
            assert ids == ["ghost.io"]                       # acme excluded (yc), robo fails the must
            counts = await s.counts("company", {"tech_area": ["ai_infra", "robotics"]}, SCHEMA)
            assert counts["program"] == {"yc": 2} and counts["stage"] == {"series_a": 1, "unknown": 1} and counts["_total"] == 2
            out2 = await evaluate(Contract(kind="company", text="banks", must={"total_disclosed_funding": {"min": 5e6}}), _Bound(s, {}, _fake_embed), SCHEMA, WEIGHTS)
            assert [r["id"] for r in out2["rows"]] == ["acme.ai"]
            cov = await s.coverage()
            assert cov["companies"] == 3 and cov["known"]["stage"] == 1 and cov["formd"]["matched"] == 1
        finally:
            await pool.close()
    _run(main())


def test_router_with_fake_model():
    async def main():
        import asyncpg
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.startups import pipeline
        from api.startups.routes import build_router
        from api.startups.store import StartupStore
        s, pool = await _store()
        await s.upsert_company({"id": "acme.ai", "name": "Acme AI", "website": "https://acme.ai", "one_liner": "inference infra for banks", "sources": ["yc"]})
        await s.set_embedding("acme.ai", _fake_embed(["banks"])[0])
        await s.replace_facts("acme.ai", "yc", [{"key": "tech_area", "value": "ai_infra"}, {"key": "program", "value": "yc"}])
        await pool.close()
        return s

    _run(main())

    async def fake_llm(system, user):
        return {"text": "ai infra for banks", "must": {"tech_area": ["ai_infra"]}, "must_not": {"program": ["techstars"]}, "center": {"key": "stage", "value": "seed", "span": 1}}

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.startups import pipeline
    from api.startups.routes import build_router
    from api.startups.store import StartupStore
    import asyncpg

    app = FastAPI()
    state = {}

    async def getter():
        if "pool" not in state:
            state["pool"] = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
        return state["pool"]
    store = StartupStore(getter)
    app.include_router(build_router(store, pipeline.Providers(llm_json=fake_llm, embed=_fake_embed), dsn=DSN, admin_token="t"))
    with TestClient(app) as client:
        r = client.post("/startups/compile", json={"text": "seed AI infra startups selling to banks, not techstars"})
        assert r.status_code == 200, r.text
        contract = r.json()["contract"]
        assert contract["must"] == {"tech_area": ["ai_infra"]} and contract["scope"] == {"exclude": {"program": ["techstars"]}}
        r = client.post("/startups/evaluate", json={"contract": contract})
        assert r.status_code == 200, r.text
        d = r.json()
        assert [x["id"] for x in d["rows"]] == ["acme.ai"] and d["rows"][0]["company"]["name"] == "Acme AI"
        assert d["counts"]["program"] == {"yc": 1} and d["coverage"]["matched"] == 1 and "order" in d["labels"]
        assert client.get("/startups/acme.ai").json()["facts"][0]["key"] in ("program", "tech_area")
        assert client.get("/startups/coverage").json()["companies"] == 1
        assert client.post("/admin/startups/jobs", json={"kind": "derive"}).status_code == 401
        r = client.post("/admin/startups/jobs", json={"kind": "extract", "params": {"limit": 1000, "max_usd": 1.0}}, headers={"X-Admin-Token": "t"})
        assert r.json()["refused"] is True                       # the spend gate
        lid = client.post("/startups/lists", json={"name": "my list", "contract": contract, "rows": d["rows"][:1]}).json()["id"]
        assert client.get(f"/startups/lists/{lid}").json()["name"] == "my list"


def test_accounts_and_maps_end_to_end():
    """Password accounts (register / login / logout / me) + Startup Maps (create, list, get, share, navigate,
    revise, delete) against the real app with accounts on and a fake model."""
    import asyncpg
    from fastapi.testclient import TestClient
    os.environ.update({"EIGEN_STARTUP_SEARCH": "1", "EIGEN_ACCOUNTS": "1", "EIGEN_CORPUS_DSN": DSN, "EIGEN_ACTIVE_VERTICAL": "tech",
                       "EIGEN_PROVIDER_MODE": "replay", "EIGEN_INGEST_IN_API": "false", "EIGEN_ADMIN_TOKEN": "t"})
    from api import startups as _pkg
    from api.startups import pipeline
    from api.app import create_app

    async def seed():
        s, pool = await _store()
        await s.upsert_company({"id": "acme.ai", "name": "Acme AI", "website": "https://acme.ai", "one_liner": "inference infra for banks", "sources": ["yc"]})
        await s.replace_facts("acme.ai", "yc", [{"key": "tech_area", "value": "ai_infra"}])
        from api.accounts import AccountStore
        acct = AccountStore(DSN, vertical="tech")
        await acct._ensure()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM eigen_user_token; DELETE FROM eigen_user WHERE email LIKE 'maps-test%'")
        await pool.close()
        await (await acct._get_pool()).close()
    _run(seed())

    async def fake_llm(system, user):
        return {"text": "ai infra", "must": {"tech_area": ["ai_infra"]}}
    real = pipeline.Providers.from_env
    pipeline.Providers.from_env = classmethod(lambda cls: pipeline.Providers(llm_json=fake_llm, embed=_fake_embed))
    try:
        app = create_app()
        with TestClient(app) as c:
            r = c.post("/auth/register", json={"name": "Map Tester", "email": "maps-test@example.com", "password": "pw1"})
            assert r.status_code == 200, r.text
            tok = r.json()["token"]
            assert c.post("/auth/register", json={"name": "Again", "email": "maps-test@example.com", "password": "x"}).status_code == 409
            assert c.post("/auth/login", json={"email": "maps-test@example.com", "password": "wrong"}).status_code == 401
            tok2 = c.post("/auth/login", json={"email": "maps-test@example.com", "password": "pw1"}).json()["token"]
            assert c.get("/me", headers={"x-eigen-token": tok2}).json()["user"]["email"] == "maps-test@example.com"
            contract = c.post("/startups/compile", json={"text": "ai infra"}).json()["contract"]
            ev = c.post("/startups/evaluate", json={"contract": contract}).json()
            assert [x["id"] for x in ev["rows"]] == ["acme.ai"]
            assert c.post("/startups/maps", json={"title": "AI infra", "contract": contract, "rows": ev["rows"]}).status_code == 401
            m = c.post("/startups/maps", json={"title": "AI infra", "brief": "ai infra", "contract": contract, "rows": ev["rows"], "coverage": ev["coverage"]}, headers={"x-eigen-token": tok}).json()
            assert m["rows"] == 1 and m["share_token"]
            assert [x["id"] for x in c.get("/startups/maps", headers={"x-eigen-token": tok}).json()["maps"]] == [m["id"]]
            assert c.get(f"/startups/maps/{m['id']}").status_code == 404                                  # not mine, no share
            shared = c.get(f"/startups/maps/{m['id']}?share={m['share_token']}").json()
            assert shared["owner"] is False and "share_token" not in shared and shared["rows"][0]["id"] == "acme.ai"
            nav = c.post(f"/startups/maps/{m['id']}/navigate", json={"contract": {**contract, "must": {"tech_area": ["fintech"]}}}, headers={"x-eigen-token": tok}).json()
            assert nav["rows"] == [] and nav["map"]["owner"] is True and "why_empty" in nav["coverage"]
            rev = c.post(f"/startups/maps/{m['id']}/revise", json={"contract": contract, "rows": ev["rows"], "reason": "narrowed"}, headers={"x-eigen-token": tok}).json()
            assert rev["revision"] == 1 and len(c.get(f"/startups/maps/{m['id']}", headers={"x-eigen-token": tok}).json()["revisions"]) == 2
            c.post("/auth/logout", headers={"x-eigen-token": tok2})
            assert c.get("/me", headers={"x-eigen-token": tok2}).status_code == 401
            assert c.delete(f"/startups/maps/{m['id']}", headers={"x-eigen-token": tok}).json()["deleted"] is True
    finally:
        pipeline.Providers.from_env = real


def test_guided_intake_route_end_to_end():
    """/startups/intake/step over the real store: opening → tech-area question with live counts → answer → … → ready."""
    from fastapi.testclient import TestClient
    os.environ.update({"EIGEN_STARTUP_SEARCH": "1", "EIGEN_CORPUS_DSN": DSN, "EIGEN_ACTIVE_VERTICAL": "tech", "EIGEN_PROVIDER_MODE": "replay", "EIGEN_INGEST_IN_API": "false"})
    from api.startups import pipeline
    from api.app import create_app

    async def seed():
        s, pool = await _store()
        for i, area in enumerate(["ai_infra", "ai_infra", "fintech"]):
            await s.upsert_company({"id": f"g{i}.ai", "name": f"G{i}", "website": f"https://g{i}.ai", "one_liner": "x", "sources": ["yc"]})
            await s.replace_facts(f"g{i}.ai", "yc", [{"key": "tech_area", "value": area}, {"key": "country", "value": "us" if i else "uk"}])
        await pool.close()
    _run(seed())

    async def fake_llm(system, user):
        if "compile a venture investor" in system:
            return {"text": "ai companies", "must": {}, "prefer": {}}
        return {"answers": {}, "free_text": "", "search_now": False}
    real = pipeline.Providers.from_env
    pipeline.Providers.from_env = classmethod(lambda cls: pipeline.Providers(llm_json=fake_llm, embed=_fake_embed))
    try:
        with TestClient(create_app()) as c:
            r = c.post("/startups/intake/step", json={}).json()
            assert r["stage"] == "opening"
            r = c.post("/startups/intake/step", json={"state": r["state"], "message": "ai companies"}).json()
            assert r["stage"] == "questions" and r["question"]["name"] == "tech_area"
            opts = {o[0]: o[2] for o in r["question"]["options"]}
            assert opts.get("ai_infra", 0) >= 2 and "labels" in r
            r = c.post("/startups/intake/step", json={"state": r["state"], "answer": {"name": "tech_area", "value": "ai_infra"}}).json()
            assert r["question"]["name"] == "stage" and [o[0] for o in r["question"]["options"]][0] == "pre_seed"
            r = c.post("/startups/intake/step", json={"state": r["state"], "search_now": True}).json()
            assert r["stage"] == "ready" and r["ready"]["contract"]["must"]["tech_area"] == ["ai_infra"] and r["ready"]["pool"] >= 2
            ev = c.post("/startups/evaluate", json={"contract": r["ready"]["contract"]}).json()
            assert {x["id"] for x in ev["rows"]} >= {"g0.ai", "g1.ai"}
    finally:
        pipeline.Providers.from_env = real
