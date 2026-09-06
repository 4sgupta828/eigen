"""Ingest pipeline — the jobs that build the index (run in a background thread with their own pool).

Jobs: `yc` (directory → companies, facts, founders, embeddings), `formd` (quarterly zips → su_formd),
`match` (Form D issuers ↔ companies → financing events + CIK), `crawl` (sites + ATS boards → pages, roles),
`extract` (DeepSeek over crawled pages → facts / founders / financing; the only spending step besides
embeddings), `derive` (computed facets). Every job records progress in `su_job`; every spending job takes a
`limit` and reports a projected cost before it spends."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import traceback
from datetime import date

from .sources import ats, formd, site, yc
from . import derive, extract, resolve
from .store import StartupStore

_log = logging.getLogger(__name__)
EXTRACT_USD_PER_COMPANY = float(os.environ.get("EIGEN_STARTUP_EXTRACT_USD", "0.012"))   # DeepSeek, ~30k tokens in / 1k out
EMBED_MODEL_USD_PER_M = 0.02


class Providers:
    """The two spending seams, injectable. `llm_json(system, user) -> dict`; `embed(texts) -> vectors`."""

    def __init__(self, llm_json=None, embed=None):
        self.llm_json = llm_json
        self.embed = embed

    @classmethod
    def from_env(cls) -> "Providers":
        """DeepSeek (OpenAI-protocol, JSON mode) for extraction / compile; OpenAI embeddings for the semantic leg."""
        from eigen_kernel.providers import _jsonsafe
        from eigen_kernel.providers.embeddings import OpenAIEmbedder
        # EIGEN_STARTUP_LLM_PROVIDER: deepseek (default) | openai — both OpenAI-protocol JSON mode, cheap models.
        provider = (os.environ.get("EIGEN_STARTUP_LLM_PROVIDER") or "deepseek").strip().lower()
        if provider == "openai":
            model = os.environ.get("EIGEN_STARTUP_LLM_MODEL") or "gpt-4o-mini"
            api_key = os.environ.get("OPENAI_API_KEY", "")
            base_url = None
        else:
            model = os.environ.get("EIGEN_STARTUP_LLM_MODEL") or "deepseek-chat"
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            base_url = os.environ.get("EIGEN_DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        state: dict = {}

        async def llm_json(system: str, user: str) -> dict:
            if "client" not in state:
                from openai import AsyncOpenAI
                state["client"] = AsyncOpenAI(api_key=api_key, base_url=base_url)
            resp = await state["client"].chat.completions.create(
                model=model, response_format={"type": "json_object"}, temperature=0,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
            return _jsonsafe.loads(resp.choices[0].message.content)
        emb = OpenAIEmbedder(dim=1536)
        return cls(llm_json=llm_json if api_key else None, embed=emb.embed if os.environ.get("OPENAI_API_KEY") else None)


async def _job(store: StartupStore, kind: str, params: dict) -> int:
    pool = await store.pool()
    async with pool.acquire() as conn:
        return int(await conn.fetchval("INSERT INTO su_job (kind, params, status) VALUES ($1, $2::jsonb, 'running') RETURNING id", kind, json.dumps(params)))


async def _progress(store: StartupStore, jid: int, progress: dict, status: str = "running", error: str = "") -> None:
    pool = await store.pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE su_job SET progress = $2::jsonb, status = $3, error = $4, updated_at = now() WHERE id = $1", jid, json.dumps(progress), status, error[:2000])


def embed_text(c: dict) -> str:
    return f"{c.get('name', '')}: {c.get('one_liner', '')}. {(c.get('description') or '')[:800]}"


# ------------------------------------------------------------------ YC
async def run_yc(store: StartupStore, prov: Providers, *, batches: list[str] | None = None, limit: int = 0, details: bool = True, jid: int | None = None) -> dict:
    await store.ensure_schema()
    bs = batches or yc.batches()
    n_companies = n_founders = n_emb = 0
    to_embed: list[tuple[str, str]] = []
    for b in bs:
        for hit in yc.companies_in_batch(b):
            if limit and n_companies >= limit:
                break
            rec = dict(hit)
            if details:
                rec.update({k: v for k, v in yc.detail(str(hit.get("slug") or "")).items() if v not in (None, "", [])})
            conv = yc.to_company(rec)
            if not conv:
                continue
            cid = await store.upsert_company(conv["company"])
            await store.replace_facts(cid, "yc", conv["facts"], keys=["program", "status", "tech_area", "headcount", "founded", "country", "metro"])
            if conv["founders"]:
                await store.replace_founders(cid, "yc", conv["founders"])
                n_founders += len(conv["founders"])
            to_embed.append((cid, embed_text(conv["company"])))
            n_companies += 1
            if jid and n_companies % 50 == 0:
                await _progress(store, jid, {"batch": b, "companies": n_companies, "founders": n_founders, "embedded": n_emb})
        n_emb += await _embed_all(store, prov, to_embed)      # per batch, so the semantic leg works while the job runs
        to_embed = []
        if limit and n_companies >= limit:
            break
    return {"batches": len(bs), "companies": n_companies, "founders": n_founders, "embedded": n_emb}


async def _embed_all(store: StartupStore, prov: Providers, items: list[tuple[str, str]]) -> int:
    if not prov.embed or not items:
        return 0
    n = 0
    for i in range(0, len(items), 100):
        chunk = items[i:i + 100]
        try:
            vecs = await asyncio.get_event_loop().run_in_executor(None, prov.embed, [t for _, t in chunk])
        except Exception as e:   # noqa: BLE001
            _log.warning("embed batch failed: %s", e)
            continue
        for (cid, _), v in zip(chunk, vecs):
            await store.set_embedding(cid, v)
            n += 1
    return n


async def run_embed(store: StartupStore, prov: Providers, *, limit: int = 20000, jid: int | None = None) -> dict:
    """Backfill embeddings for companies that have none (≈ $0.02 per 1M tokens; a company ≈ 150 tokens)."""
    await store.ensure_schema()
    pool = await store.pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name, one_liner, description FROM su_company WHERE status = 'active' AND embedding IS NULL LIMIT $1", limit)
    n = await _embed_all(store, prov, [(r["id"], embed_text(dict(r))) for r in rows])
    return {"embedded": n, "of": len(rows)}


# ------------------------------------------------------------------ Form D
async def run_formd(store: StartupStore, *, since: tuple[int, int] = (2019, 1), quarters: list[str] | None = None, jid: int | None = None) -> dict:
    await store.ensure_schema()
    qs = formd.list_quarters(tuple(int(x) for x in since))
    if quarters:
        qs = [q for q in qs if q[0] in set(quarters)]
    done = {}
    pool = await store.pool()
    async with pool.acquire() as conn:
        have = {r["quarter"] for r in await conn.fetch("SELECT DISTINCT quarter FROM su_formd")}
    for label, url in qs:
        if label in have:
            done[label] = "already"
            continue
        zb = await asyncio.get_event_loop().run_in_executor(None, formd.download_quarter, url)
        if not zb:
            done[label] = "download_failed"
            continue
        recs = formd.parse_quarter(zb)
        n = await store.insert_formd(recs, label)
        done[label] = n
        if jid:
            await _progress(store, jid, {"quarters": done})
    return {"quarters": done}


async def run_match(store: StartupStore, prov: Providers, *, llm_budget: int = 0, include_rejected: bool = False, jid: int | None = None) -> dict:
    """Match operating Form D issuers to companies. Structural first; the model only for `ambiguous` and only
    up to `llm_budget` judgments (each ≈ $0.0005 on DeepSeek)."""
    await store.ensure_schema()
    pool = await store.pool()
    async with pool.acquire() as conn:
        comps = [dict(r) for r in await conn.fetch("SELECT id, name, legal_name, cik, hq, one_liner, aliases, website, yc_batch FROM su_company WHERE status = 'active'")]
        skip = "('no_candidate')" if include_rejected else "('rejected','no_candidate')"
        filings = [dict(r) for r in await conn.fetch(f"SELECT accession, file_num, cik, entity_name, name_norm, previous_names, city, state, entity_type, year_inc, industry, revenue_range, is_amendment, filing_date, sale_date, offering_usd, sold_usd, investors_count FROM su_formd WHERE is_operating AND company_id IS NULL AND match_method NOT IN {skip}")]
    by_norm: dict[str, list[dict]] = {}
    for c in comps:
        for nm in {formd.name_norm(c["name"]), formd.name_norm(c.get("legal_name") or "")} | {formd.name_norm(a) for a in (c.get("aliases") or [])}:
            if nm:
                by_norm.setdefault(nm, []).append(c)
    by_cik = {c["cik"]: c for c in comps if c.get("cik")}
    stats = {"filings": len(filings), "cik": 0, "exact_name": 0, "llm_merge": 0, "llm_rejected": 0, "ambiguous_unjudged": 0, "no_candidate": 0}
    spent = 0
    for f in filings:
        cands = []
        if f.get("cik") and f["cik"] in by_cik:
            cands = [by_cik[f["cik"]]]
        else:
            names = {f["name_norm"]} | {formd.name_norm(p) for p in (f.get("previous_names") or [])}
            seen = set()
            for nm in names:
                for c in by_norm.get(nm, []):
                    if c["id"] not in seen:
                        seen.add(c["id"]); cands.append(c)
        method, comp = resolve.decide_structural(f, cands)
        note = ""
        if method == "ambiguous":
            pool_c = [comp] if comp else cands[:3]
            if prov.llm_json and spent < llm_budget:
                best = None
                for c in pool_c:
                    spent += 1
                    same, conf, reason = await resolve.judge_merge(prov.llm_json, f, c)
                    if same and conf >= 0.8 and (best is None or conf > best[1]):
                        best = (c, conf, reason)
                if best:
                    method, comp, note = "llm_merge", best[0], f"{best[1]:.2f} {best[2]}"
                    stats["llm_merge"] += 1
                else:
                    method, comp, note = "rejected", None, "model: not the same company"
                    stats["llm_rejected"] += 1
            else:
                stats["ambiguous_unjudged"] += 1
                continue
        if method == "none":
            stats["no_candidate"] += 1
            async with pool.acquire() as conn:
                await conn.execute("UPDATE su_formd SET match_method = 'no_candidate' WHERE accession = $1", f["accession"])
            continue
        if method in ("cik", "exact_name"):
            stats[method] += 1
        async with pool.acquire() as conn:
            await conn.execute("UPDATE su_formd SET company_id = $2, match_method = $3, match_note = $4 WHERE accession = $1", f["accession"], comp["id"] if comp else None, method, note)
            if comp and f.get("cik") and not comp.get("cik"):
                await conn.execute("UPDATE su_company SET cik = $2, legal_name = CASE WHEN legal_name = '' THEN $3 ELSE legal_name END, sources = array_append(sources, 'formd') WHERE id = $1 AND NOT ('formd' = ANY(sources))", comp["id"], f["cik"], f["entity_name"])
                comp["cik"] = f["cik"]; by_cik[f["cik"]] = comp
        if comp:
            await store.upsert_financing(comp["id"], {"kind": "formd", "file_num": f.get("file_num") or f["accession"], "accession": f["accession"], "round_name": "",
                                                     "amount_usd": f.get("sold_usd"), "offering_usd": f.get("offering_usd"), "event_date": f.get("sale_date") or f.get("filing_date"),
                                                     "source_url": formd.edgar_url({"cik": f.get("cik"), "accession": f["accession"]}), "quote": formd.render_summary({**f, "officers": []})})
        if jid and (stats["cik"] + stats["exact_name"] + stats["llm_merge"]) % 100 == 0:
            await _progress(store, jid, stats)
    stats["llm_calls"] = spent
    return stats


# ------------------------------------------------------------------ crawl + extract + derive
async def run_crawl(store: StartupStore, *, ids: list[str] | None = None, limit: int = 50, recrawl_days: int = 90, jid: int | None = None) -> dict:
    await store.ensure_schema()
    pool = await store.pool()
    async with pool.acquire() as conn:
        if ids:
            rows = await conn.fetch("SELECT id, website FROM su_company WHERE id = ANY($1) AND status = 'active'", ids)
        else:
            rows = await conn.fetch("""SELECT id, website FROM su_company WHERE status = 'active' AND website <> ''
                                       AND (crawl = '{}'::jsonb OR (crawl->>'at')::timestamptz < now() - ($1 || ' days')::interval)
                                       ORDER BY updated_at DESC LIMIT $2""", str(recrawl_days), limit)
    n_ok = n_fail = 0
    for r in rows:
        res = await asyncio.get_event_loop().run_in_executor(None, site.crawl, r["website"])
        pages = res["pages"]
        roles, board = ([], None)
        if pages:
            roles, board = await asyncio.get_event_loop().run_in_executor(None, ats.hiring_for, [p["html"] for p in pages])
        meta = {"at": date.today().isoformat(), "pages": [{"kind": p["kind"], "url": p["url"], "chars": len(p["text"])} for p in pages],
                "failed": res["failed"], "ats": {"board": list(board) if board else None, "roles": [{"title": x["title"], "location": x["location"], "department": x["department"], "url": x["url"]} for x in roles[:200]]}}
        await store.save_pages(r["id"], [{k: p[k] for k in ("url", "kind", "sha", "text")} for p in pages], meta)
        n_ok += 1 if pages else 0
        n_fail += 0 if pages else 1
        if jid and (n_ok + n_fail) % 10 == 0:
            await _progress(store, jid, {"crawled": n_ok, "failed": n_fail, "of": len(rows)})
    return {"crawled": n_ok, "failed": n_fail}


def project_extract_cost(n: int) -> dict:
    return {"companies": n, "usd_per_company": EXTRACT_USD_PER_COMPANY, "projected_usd": round(n * EXTRACT_USD_PER_COMPANY, 2)}


async def run_extract(store: StartupStore, prov: Providers, *, ids: list[str] | None = None, limit: int = 25, max_usd: float = 5.0, jid: int | None = None) -> dict:
    """The spending step: one DeepSeek call per crawled company. Refuses to start past `max_usd`."""
    await store.ensure_schema()
    if not prov.llm_json:
        return {"error": "no llm provider"}
    pool = await store.pool()
    async with pool.acquire() as conn:
        if ids:
            rows = await conn.fetch("SELECT id, name, website, one_liner, crawl FROM su_company WHERE id = ANY($1) AND crawl <> '{}'::jsonb", ids)
        else:
            rows = await conn.fetch("""SELECT id, name, website, one_liner, crawl FROM su_company WHERE status = 'active' AND crawl <> '{}'::jsonb
                                       AND (extracted_at IS NULL OR extracted_at < (crawl->>'at')::timestamptz) ORDER BY updated_at DESC LIMIT $1""", limit)
    proj = project_extract_cost(len(rows))
    if proj["projected_usd"] > max_usd:
        return {"refused": True, "projection": proj, "max_usd": max_usd}
    n = n_facts = 0
    for r in rows:
        pages = await store.pages(r["id"])
        crawl = json.loads(r["crawl"]) if isinstance(r["crawl"], str) else (r["crawl"] or {})
        roles = (crawl.get("ats") or {}).get("roles") or []
        res = await extract.extract_company(prov.llm_json, {"name": r["name"], "website": r["website"], "one_liner": r["one_liner"]}, pages, roles)
        if res is None:
            continue
        n += 1
        n_facts += await store.replace_facts(r["id"], "site", res["facts"], keys=list(extract.EXTRACTABLE))
        if res["founders"]:
            await store.replace_founders(r["id"], "site", res["founders"])
        for ev in res["financing"]:
            await store.upsert_financing(r["id"], ev)
        async with pool.acquire() as conn:
            crawl["role_functions"] = res["role_functions"]
            crawl["customers"] = res["customers"]
            crawl["metrics"] = res["metrics"]
            await conn.execute("UPDATE su_company SET crawl = $2::jsonb, one_liner = CASE WHEN one_liner = '' THEN $3 ELSE one_liner END, extracted_at = now() WHERE id = $1",
                               r["id"], json.dumps(crawl, default=str), res["one_liner"])
        await derive_one(store, r["id"])
        if jid and n % 5 == 0:
            await _progress(store, jid, {"extracted": n, "facts": n_facts, "of": len(rows), "projection": proj})
    return {"extracted": n, "facts": n_facts, "projection": proj}


async def derive_one(store: StartupStore, cid: str) -> int:
    c = await store.company(cid)
    if not c:
        return 0
    roles = ((c.get("crawl") or {}).get("ats") or {}).get("roles") or []
    rf = (c.get("crawl") or {}).get("role_functions") or {}
    filings = [dict(f, source_url=formd.edgar_url({"cik": c.get("cik"), "accession": f.get("accession")})) for f in c.get("filings") or []]
    facts = derive.derive_facts(c, c.get("financing") or [], filings, c.get("founders") or [], roles, rf)
    keys = ["total_disclosed_funding", "last_round_amount", "last_round_months", "stage", "financing_scale", "revenue_range", "investor", "lead_investor",
            "founder_count", "founder_prior_company", "hiring", "hiring_function", "evidence_strength"]
    return await store.replace_facts(cid, "derived", facts, keys=keys)


async def run_derive(store: StartupStore, *, ids: list[str] | None = None, jid: int | None = None) -> dict:
    await store.ensure_schema()
    pool = await store.pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id FROM su_company WHERE status = 'active'" + (" AND id = ANY($1)" if ids else ""), *([ids] if ids else []))
    n = nf = 0
    for r in rows:
        nf += await derive_one(store, r["id"])
        n += 1
        if jid and n % 200 == 0:
            await _progress(store, jid, {"derived": n, "facts": nf, "of": len(rows)})
    return {"derived": n, "facts": nf}


# ------------------------------------------------------------------ funding news (Brave + model), Form D issuers as companies
BRAVE_USD_PER_QUERY = 0.005


async def run_news(store: StartupStore, prov: Providers, *, limit: int = 200, max_usd: float = 2.0, batch: int = 20, provider: str = "brave", jid: int | None = None) -> dict:
    """Round name / amount / lead / investors from funding headlines. Companies without a stated round first,
    the better-evidenced ones (a filing, a team, open roles) before the rest. Spend = Brave queries (+ a tiny model cost)."""
    from .sources import news
    await store.ensure_schema()
    if not prov.llm_json:
        return {"error": "no llm provider"}
    per_query = BRAVE_USD_PER_QUERY if provider == "brave" else 0.0        # GDELT is free (and slow: 5 s between requests)
    proj = {"companies": limit, "provider": provider, "projected_usd": round(limit * per_query + limit * 0.0005, 2)}
    if proj["projected_usd"] > max_usd:
        return {"refused": True, "projection": proj, "max_usd": max_usd}
    pool = await store.pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""SELECT c.id, c.name, c.website, c.hq FROM su_company c
                                   WHERE c.status = 'active' AND c.id NOT LIKE 'cik:%' AND coalesce(c.crawl->>'news_provider', '') <> $2
                                     AND NOT EXISTS (SELECT 1 FROM su_financing f WHERE f.company_id = c.id AND f.kind = 'press')
                                   ORDER BY (EXISTS (SELECT 1 FROM su_formd d WHERE d.company_id = c.id)) DESC,
                                            (EXISTS (SELECT 1 FROM su_fact x WHERE x.company_id = c.id AND x.key = 'hiring')) DESC, c.updated_at DESC LIMIT $1""", limit, provider)
    n_q = n_hit = n_ev = 0
    items: list[dict] = []
    async def flush():
        nonlocal n_ev
        if not items:
            return
        try:
            out = await prov.llm_json(news.NEWS_SYSTEM, news.news_payload(items))
        except Exception:   # noqa: BLE001
            out = {}
        evs = news.validate_news(out if isinstance(out, dict) else {}, items)
        for i, b in enumerate(items):
            for ev in evs.get(i, []):
                await store.upsert_financing(b["id"], ev); n_ev += 1
            async with pool.acquire() as conn:
                await conn.execute("UPDATE su_company SET crawl = crawl || jsonb_build_object('news_at', $2::text, 'news_hits', $3::int, 'news_provider', $4::text) WHERE id = $1", b["id"], date.today().isoformat(), len(b["articles"]), provider)
            if evs.get(i):
                await derive_one(store, b["id"])
        items.clear()
    for r in rows:
        fetch = news.gdelt_funding_news if provider == "gdelt" else news.brave_funding_news
        arts = await asyncio.get_event_loop().run_in_executor(None, lambda r=r: fetch(r["name"], r["website"]))
        n_q += 1
        if arts:
            n_hit += 1
            items.append({"id": r["id"], "name": r["name"], "website": r["website"], "hq": r["hq"], "articles": arts})
        else:
            async with pool.acquire() as conn:
                await conn.execute("UPDATE su_company SET crawl = crawl || jsonb_build_object('news_at', $2::text, 'news_hits', 0, 'news_provider', $3::text) WHERE id = $1", r["id"], date.today().isoformat(), provider)
        if len(items) >= batch:
            await flush()
        if jid and n_q % 25 == 0:
            await _progress(store, jid, {"queried": n_q, "with_news": n_hit, "events": n_ev, "of": len(rows)})
        await asyncio.sleep(5.5 if provider == "gdelt" else 1.0)      # GDELT: one request per 5 s; Brave: one per second
    await flush()
    return {"queried": n_q, "with_news": n_hit, "events": n_ev, "projection": proj}


_TECHISH = {"other technology": None, "computers": "hardware_semis", "telecommunications": "other", "biotechnology": "bio_health",
            "other health care": "bio_health", "medical device": "bio_health", "pharmaceuticals": "bio_health", "energy": "climate_energy",
            "other energy": "climate_energy", "business services": None, "aerospace": "space_defense"}


async def run_formd_companies(store: StartupStore, *, since: str = "2022-01-01", min_usd: float = 2_000_000, limit: int = 20000, jid: int | None = None) -> dict:
    """The unmatched operating Form D issuers in technology-ish industry groups that sold ≥ `min_usd` since `since`
    become companies keyed `cik:<n>` — legal identity, filing-backed funding and officers, no site yet."""
    from .sources.yc import _geo
    await store.ensure_schema()
    pool = await store.pool()
    async with pool.acquire() as conn:
        issuers = await conn.fetch("""SELECT cik, max(entity_name) AS entity_name, max(city) AS city, max(state) AS state, max(industry) AS industry,
                                             max(year_inc) AS year_inc, sum(sold_usd) FILTER (WHERE NOT is_amendment) AS sold, max(sale_date) AS last_sale
                                      FROM su_formd WHERE is_operating AND company_id IS NULL AND cik <> '' AND lower(industry) = ANY($1)
                                        AND sale_date >= $2::date GROUP BY cik HAVING coalesce(sum(sold_usd) FILTER (WHERE NOT is_amendment), 0) >= $3
                                      ORDER BY sold DESC NULLS LAST LIMIT $4""", list(_TECHISH), date.fromisoformat(since), float(min_usd), limit)
    # an issuer whose name matches an existing (site-keyed) company is left to the match job — never a duplicate node
    async with pool.acquire() as conn:
        known = {formd.name_norm(r["name"]) for r in await conn.fetch("SELECT name FROM su_company WHERE id NOT LIKE 'cik:%'")}
        known |= {formd.name_norm(r["legal_name"]) for r in await conn.fetch("SELECT legal_name FROM su_company WHERE legal_name <> ''")}
    known.discard("")
    n = skipped = 0
    for it in issuers:
        if formd.name_norm(it["entity_name"]) in known:
            skipped += 1
            continue
        cid = f"cik:{it['cik']}"
        hq = ", ".join(x for x in (it["city"], it["state"]) if x)
        await store.upsert_company({"id": cid, "name": it["entity_name"], "legal_name": it["entity_name"], "cik": it["cik"], "hq": hq, "sources": ["formd"],
                                    "one_liner": f"{(it['industry'] or 'Private').strip()} company in {hq} (from SEC Form D filings; no website on record yet)"})
        facts = [{"key": "status", "value": "active", "quote": "Active issuer on SEC Form D", "source_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={it['cik']}"}]
        area = _TECHISH.get((it["industry"] or "").lower())
        if area:
            facts.append({"key": "tech_area", "value": area, "quote": f"Industry group: {it['industry']} (Form D)", "source_url": facts[0]["source_url"], "confidence": 0.5})
        if it["year_inc"]:
            facts.append({"key": "founded", "number": float(it["year_inc"]), "display": str(it["year_inc"]), "quote": f"Year of incorporation: {it['year_inc']} (Form D)", "source_url": facts[0]["source_url"]})
        for key, val in _geo(hq):
            facts.append({"key": key, "value": val, "quote": f"Issuer address: {hq} (Form D)", "source_url": facts[0]["source_url"]})
        await store.replace_facts(cid, "formd", facts, keys=["status", "tech_area", "founded", "country", "metro"])
        async with pool.acquire() as conn:
            fil = await conn.fetch("SELECT accession, file_num, sold_usd, offering_usd, sale_date, filing_date FROM su_formd WHERE cik = $1 AND is_operating", it["cik"])
            await conn.execute("UPDATE su_formd SET company_id = $2, match_method = 'issuer' WHERE cik = $1 AND is_operating", it["cik"], cid)
        for f in fil:
            await store.upsert_financing(cid, {"kind": "formd", "file_num": f["file_num"] or f["accession"], "accession": f["accession"], "round_name": "",
                                               "amount_usd": f["sold_usd"], "offering_usd": f["offering_usd"], "event_date": f["sale_date"] or f["filing_date"],
                                               "source_url": formd.edgar_url({"cik": it["cik"], "accession": f["accession"]}),
                                               "quote": f"Total amount sold: ${(f['sold_usd'] or 0):,.0f}; date of first sale {f['sale_date']} (Form D {f['accession']})"})
        await derive_one(store, cid)
        n += 1
        if jid and n % 200 == 0:
            await _progress(store, jid, {"companies": n, "of": len(issuers)})
    return {"companies": n, "skipped_name_match": skipped, "of": len(issuers)}


# ------------------------------------------------------------------ runner (background thread, own loop + pool)
RUNNERS = {"yc": run_yc, "embed": run_embed, "formd": run_formd, "match": run_match, "crawl": run_crawl, "extract": run_extract, "derive": run_derive,
           "news": run_news, "formd_companies": run_formd_companies}
NEEDS_PROV = {"yc", "embed", "match", "extract", "news"}


async def start_job(store: StartupStore, dsn: str, kind: str, params: dict, *, providers: Providers | None = None) -> int:
    """Insert the job row on the caller's loop (so the caller gets an id), then run the job on a daemon thread
    with its own event loop and pool."""
    import asyncpg
    await store.ensure_schema()
    jid = await _job(store, kind, params)

    async def _ret(p):
        return p

    def _run() -> None:
        async def main():
            pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
            tstore = StartupStore(lambda: _ret(pool))
            prov = providers or (Providers.from_env() if kind in NEEDS_PROV else Providers())
            try:
                fn = RUNNERS[kind]
                kw = dict(params); kw["jid"] = jid
                out = await (fn(tstore, prov, **kw) if kind in NEEDS_PROV else fn(tstore, **kw))
                await _progress(tstore, jid, out, status="done")
            except Exception as e:   # noqa: BLE001
                _log.exception("startup job %s failed", kind)
                await _progress(tstore, jid, {}, status="failed", error=f"{e}\n{traceback.format_exc()[-1500:]}")
            finally:
                await pool.close()
        asyncio.run(main())

    threading.Thread(target=_run, daemon=True, name=f"startups-{kind}-{jid}").start()
    return jid
