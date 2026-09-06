"""Startup Search storage — its own tables (`su_*`) on the corpus Postgres, and the facet-store adapter the
kernel evaluator reads through.

Tables: `su_company` (one row per company keyed by its website domain), `su_fact` (typed facet rows, each with
the evidence that grounds it: provenance, source URL, verbatim quote, as-of, basis), `su_financing` (financing
events: filings and stated rounds), `su_founder`, `su_page` (crawl cache by content hash), `su_formd` (every
bulk filing, matched or not), `su_list` (saved searches). `su_fact` IS the read model: the evaluator filters
and counts over it with the musts applied in SQL on every leg (no row can leak past a must)."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone

from eigen_kernel.facets import UNKNOWN, FacetSchema, FacetType

from .schema import KIND, SCHEMA

_DDL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS su_company (
    id            text PRIMARY KEY,            -- registrable domain (product identity)
    name          text NOT NULL,
    legal_name    text NOT NULL DEFAULT '',
    cik           text NOT NULL DEFAULT '',    -- legal identity once a filing is matched
    website       text NOT NULL DEFAULT '',
    one_liner     text NOT NULL DEFAULT '',
    description   text NOT NULL DEFAULT '',
    hq            text NOT NULL DEFAULT '',
    yc_slug       text NOT NULL DEFAULT '',
    yc_batch      text NOT NULL DEFAULT '',
    aliases       text[] NOT NULL DEFAULT '{}',
    sources       text[] NOT NULL DEFAULT '{}',
    status        text NOT NULL DEFAULT 'active',   -- active | suppressed
    crawl         jsonb NOT NULL DEFAULT '{}',      -- {at, pages, failed, ats}
    extracted_at  timestamptz,
    embedding     vector(1536),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_su_company_name ON su_company (lower(name));
CREATE INDEX IF NOT EXISTS ix_su_company_cik  ON su_company (cik) WHERE cik <> '';
CREATE INDEX IF NOT EXISTS ix_su_company_vec  ON su_company USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS su_fact (
    id           bigserial PRIMARY KEY,
    company_id   text NOT NULL REFERENCES su_company(id) ON DELETE CASCADE,
    key          text NOT NULL,
    value        text NOT NULL DEFAULT '',      -- normalised token / band
    number       double precision,              -- numeric keys: the raw number
    display      text NOT NULL DEFAULT '',
    provenance   text NOT NULL,                 -- yc | formd | site | ats | press | portfolio | github | derived
    basis        text NOT NULL DEFAULT '',      -- e.g. stated_round | inferred_from_filing | filing_range | self_reported
    source_url   text NOT NULL DEFAULT '',
    quote        text NOT NULL DEFAULT '',
    as_of        date,
    confidence   real NOT NULL DEFAULT 1.0,
    schema_version text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (company_id, key, value, provenance)
);
CREATE INDEX IF NOT EXISTS ix_su_fact_kv ON su_fact (key, value);
CREATE INDEX IF NOT EXISTS ix_su_fact_company ON su_fact (company_id, key);

CREATE TABLE IF NOT EXISTS su_financing (
    id           bigserial PRIMARY KEY,
    company_id   text NOT NULL REFERENCES su_company(id) ON DELETE CASCADE,
    kind         text NOT NULL,                 -- formd | press | site
    file_num     text NOT NULL DEFAULT '',      -- Form D file number (amendments share it)
    accession    text NOT NULL DEFAULT '',
    round_name   text NOT NULL DEFAULT '',      -- stated round token (seed, series_a …) or ''
    amount_usd   double precision,              -- formd: amount sold; press/site: stated amount
    offering_usd double precision,
    event_date   date,
    investors    text[] NOT NULL DEFAULT '{}',
    lead         text NOT NULL DEFAULT '',
    source_url   text NOT NULL DEFAULT '',
    quote        text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (company_id, kind, file_num, round_name, event_date)
);
CREATE INDEX IF NOT EXISTS ix_su_fin_company ON su_financing (company_id);

CREATE TABLE IF NOT EXISTS su_founder (
    id           bigserial PRIMARY KEY,
    company_id   text NOT NULL REFERENCES su_company(id) ON DELETE CASCADE,
    name         text NOT NULL,
    title        text NOT NULL DEFAULT '',
    prior_companies text[] NOT NULL DEFAULT '{}',
    provenance   text NOT NULL,
    source_url   text NOT NULL DEFAULT '',
    quote        text NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_su_founder_name ON su_founder (company_id, lower(name));

CREATE TABLE IF NOT EXISTS su_page (
    company_id   text NOT NULL REFERENCES su_company(id) ON DELETE CASCADE,
    url          text NOT NULL,
    kind         text NOT NULL DEFAULT '',
    sha          text NOT NULL,
    text         text NOT NULL DEFAULT '',
    fetched_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (company_id, url)
);

CREATE TABLE IF NOT EXISTS su_formd (
    accession    text PRIMARY KEY,
    file_num     text NOT NULL DEFAULT '',
    cik          text NOT NULL DEFAULT '',
    entity_name  text NOT NULL,
    name_norm    text NOT NULL,
    previous_names text[] NOT NULL DEFAULT '{}',
    city         text NOT NULL DEFAULT '',
    state        text NOT NULL DEFAULT '',
    entity_type  text NOT NULL DEFAULT '',
    year_inc     int,
    industry     text NOT NULL DEFAULT '',
    revenue_range text NOT NULL DEFAULT '',
    is_amendment boolean NOT NULL DEFAULT false,
    previous_accession text NOT NULL DEFAULT '',
    filing_date  date,
    sale_date    date,
    offering_usd double precision,
    sold_usd     double precision,
    investors_count bigint,
    is_operating boolean NOT NULL DEFAULT false,
    officers     jsonb NOT NULL DEFAULT '[]',
    quarter      text NOT NULL DEFAULT '',
    company_id   text REFERENCES su_company(id) ON DELETE SET NULL,
    match_method text NOT NULL DEFAULT '',     -- cik | exact_name | llm_merge | rejected | ''
    match_note   text NOT NULL DEFAULT ''
);
ALTER TABLE su_formd ALTER COLUMN investors_count TYPE bigint;
CREATE INDEX IF NOT EXISTS ix_su_formd_norm ON su_formd (name_norm) WHERE is_operating;
CREATE INDEX IF NOT EXISTS ix_su_formd_cik  ON su_formd (cik);
CREATE INDEX IF NOT EXISTS ix_su_formd_company ON su_formd (company_id) WHERE company_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS su_map (
    id           text PRIMARY KEY,
    owner_id     text NOT NULL,
    title        text NOT NULL,
    brief        text NOT NULL DEFAULT '',
    contract     jsonb NOT NULL,
    rows         jsonb NOT NULL DEFAULT '[]',      -- snapshot: [{id, name, one_liner, score, rank, facets}] at save time
    coverage     jsonb NOT NULL DEFAULT '{}',
    notes        text NOT NULL DEFAULT '',
    share_token  text NOT NULL,
    revision     int NOT NULL DEFAULT 0,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_su_map_owner ON su_map (owner_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS su_map_revision (
    map_id       text NOT NULL REFERENCES su_map(id) ON DELETE CASCADE,
    revision     int NOT NULL,
    reason       text NOT NULL DEFAULT '',
    contract     jsonb NOT NULL,
    rows         jsonb NOT NULL DEFAULT '[]',
    coverage     jsonb NOT NULL DEFAULT '{}',
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (map_id, revision)
);
CREATE TABLE IF NOT EXISTS su_list (
    id           text PRIMARY KEY,
    name         text NOT NULL,
    contract     jsonb NOT NULL,
    rows         jsonb NOT NULL DEFAULT '[]',
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS su_job (
    id           bigserial PRIMARY KEY,
    kind         text NOT NULL,          -- yc | formd | site | derive | extract
    params       jsonb NOT NULL DEFAULT '{}',
    status       text NOT NULL DEFAULT 'queued',
    progress     jsonb NOT NULL DEFAULT '{}',
    error        text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
"""


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:60]


def _vec(v) -> str | None:
    return None if v is None else "[" + ",".join(f"{float(x):.6f}" for x in v) + "]"


class StartupStore:
    """asyncpg-backed. `pool_getter` is an awaitable returning the shared pool (the app's pattern)."""

    def __init__(self, pool_getter, schema: FacetSchema = SCHEMA):
        self._pool_getter = pool_getter
        self._schema = schema
        self._ready = False

    async def pool(self):
        return await self._pool_getter()

    async def ensure_schema(self) -> None:
        if self._ready:
            return
        pool = await self.pool()
        async with pool.acquire() as conn:
            await conn.execute(_DDL)
        self._ready = True

    # ------------------------------------------------------------------ writes
    async def upsert_company(self, c: dict) -> str:
        """Insert or refresh a company by id (domain). Fields present and non-empty win; empty never overwrites."""
        await self.ensure_schema()
        pool = await self.pool()
        cid = c["id"]
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO su_company (id, name, legal_name, cik, website, one_liner, description, hq, yc_slug, yc_batch, aliases, sources)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                ON CONFLICT (id) DO UPDATE SET
                    name = CASE WHEN EXCLUDED.name <> '' THEN EXCLUDED.name ELSE su_company.name END,
                    legal_name = CASE WHEN EXCLUDED.legal_name <> '' THEN EXCLUDED.legal_name ELSE su_company.legal_name END,
                    cik = CASE WHEN EXCLUDED.cik <> '' THEN EXCLUDED.cik ELSE su_company.cik END,
                    website = CASE WHEN EXCLUDED.website <> '' THEN EXCLUDED.website ELSE su_company.website END,
                    one_liner = CASE WHEN EXCLUDED.one_liner <> '' THEN EXCLUDED.one_liner ELSE su_company.one_liner END,
                    description = CASE WHEN EXCLUDED.description <> '' THEN EXCLUDED.description ELSE su_company.description END,
                    hq = CASE WHEN EXCLUDED.hq <> '' THEN EXCLUDED.hq ELSE su_company.hq END,
                    yc_slug = CASE WHEN EXCLUDED.yc_slug <> '' THEN EXCLUDED.yc_slug ELSE su_company.yc_slug END,
                    yc_batch = CASE WHEN EXCLUDED.yc_batch <> '' THEN EXCLUDED.yc_batch ELSE su_company.yc_batch END,
                    aliases = (SELECT ARRAY(SELECT DISTINCT unnest(su_company.aliases || EXCLUDED.aliases))),
                    sources = (SELECT ARRAY(SELECT DISTINCT unnest(su_company.sources || EXCLUDED.sources))),
                    updated_at = now()""",
                cid, c.get("name") or cid, c.get("legal_name") or "", c.get("cik") or "", c.get("website") or "",
                c.get("one_liner") or "", c.get("description") or "", c.get("hq") or "", c.get("yc_slug") or "", c.get("yc_batch") or "",
                list(c.get("aliases") or []), list(c.get("sources") or []))
        return cid

    async def set_embedding(self, cid: str, vec: list[float]) -> None:
        pool = await self.pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE su_company SET embedding = $2::vector WHERE id = $1", cid, _vec(vec))

    async def replace_facts(self, cid: str, provenance: str, facts: list[dict], *, keys: list[str] | None = None) -> int:
        """Delete this provenance's rows for the given keys (or every key the facts touch) and insert the new ones —
        a rebuildable read model. Values are validated against the schema (off-vocabulary → dropped)."""
        await self.ensure_schema()
        pool = await self.pool()
        rows = []
        for f in facts:
            k = self._schema.key(f["key"])
            if k is None:
                continue
            number = f.get("number")
            if k.type is FacetType.numeric:
                if number is None:
                    continue
                value = self._schema.band_of(k.key, number)
                if value == UNKNOWN:
                    continue
            else:
                value = self._schema.validate_value(k.key, f.get("value"))
                if value is None:
                    continue
            rows.append((cid, k.key, value, float(number) if number is not None else None, str(f.get("display") or "")[:300], provenance,
                         str(f.get("basis") or "")[:60], str(f.get("source_url") or "")[:1000], str(f.get("quote") or "")[:1500],
                         f.get("as_of"), float(f.get("confidence", 1.0)), self._schema.version()))
        touched = sorted(set(keys or []) | {r[1] for r in rows})
        async with pool.acquire() as conn, conn.transaction():
            if touched:
                await conn.execute("DELETE FROM su_fact WHERE company_id = $1 AND provenance = $2 AND key = ANY($3)", cid, provenance, touched)
            if rows:
                await conn.executemany("""INSERT INTO su_fact (company_id, key, value, number, display, provenance, basis, source_url, quote, as_of, confidence, schema_version)
                                          VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) ON CONFLICT (company_id, key, value, provenance) DO UPDATE SET
                                          number = EXCLUDED.number, display = EXCLUDED.display, basis = EXCLUDED.basis, source_url = EXCLUDED.source_url,
                                          quote = EXCLUDED.quote, as_of = EXCLUDED.as_of, confidence = EXCLUDED.confidence, schema_version = EXCLUDED.schema_version""", rows)
        return len(rows)

    async def upsert_financing(self, cid: str, ev: dict) -> None:
        pool = await self.pool()
        async with pool.acquire() as conn:
            await conn.execute("""INSERT INTO su_financing (company_id, kind, file_num, accession, round_name, amount_usd, offering_usd, event_date, investors, lead, source_url, quote)
                                  VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                                  ON CONFLICT (company_id, kind, file_num, round_name, event_date) DO UPDATE SET
                                  accession = EXCLUDED.accession, amount_usd = EXCLUDED.amount_usd, offering_usd = EXCLUDED.offering_usd,
                                  investors = EXCLUDED.investors, lead = EXCLUDED.lead, source_url = EXCLUDED.source_url, quote = EXCLUDED.quote""",
                               cid, ev["kind"], ev.get("file_num") or "", ev.get("accession") or "", ev.get("round_name") or "",
                               ev.get("amount_usd"), ev.get("offering_usd"), ev.get("event_date"), list(ev.get("investors") or []),
                               ev.get("lead") or "", ev.get("source_url") or "", (ev.get("quote") or "")[:1500])

    async def replace_founders(self, cid: str, provenance: str, founders: list[dict]) -> None:
        pool = await self.pool()
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM su_founder WHERE company_id = $1 AND provenance = $2", cid, provenance)
            for f in founders:
                if not (f.get("name") or "").strip():
                    continue
                await conn.execute("""INSERT INTO su_founder (company_id, name, title, prior_companies, provenance, source_url, quote)
                                      VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (company_id, lower(name)) DO UPDATE SET
                                      title = CASE WHEN EXCLUDED.title <> '' THEN EXCLUDED.title ELSE su_founder.title END,
                                      prior_companies = (SELECT ARRAY(SELECT DISTINCT unnest(su_founder.prior_companies || EXCLUDED.prior_companies))),
                                      provenance = EXCLUDED.provenance, source_url = EXCLUDED.source_url, quote = EXCLUDED.quote""",
                                   cid, f["name"].strip()[:120], (f.get("title") or "")[:120], list(f.get("prior_companies") or []),
                                   provenance, (f.get("source_url") or "")[:1000], (f.get("quote") or "")[:800])

    async def save_pages(self, cid: str, pages: list[dict], crawl_meta: dict) -> None:
        pool = await self.pool()
        async with pool.acquire() as conn, conn.transaction():
            for p in pages:
                await conn.execute("""INSERT INTO su_page (company_id, url, kind, sha, text) VALUES ($1,$2,$3,$4,$5)
                                      ON CONFLICT (company_id, url) DO UPDATE SET kind = EXCLUDED.kind, sha = EXCLUDED.sha, text = EXCLUDED.text, fetched_at = now()""",
                                   cid, p["url"], p.get("kind") or "", p["sha"], p["text"].replace("\x00", "")[:60_000])
            await conn.execute("UPDATE su_company SET crawl = $2::jsonb, updated_at = now() WHERE id = $1", cid, json.dumps(crawl_meta))

    async def pages(self, cid: str) -> list[dict]:
        pool = await self.pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT url, kind, sha, text, fetched_at FROM su_page WHERE company_id = $1", cid)
        return [dict(r) for r in rows]

    async def mark_extracted(self, cid: str) -> None:
        pool = await self.pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE su_company SET extracted_at = now() WHERE id = $1", cid)

    async def insert_formd(self, recs: list[dict], quarter: str) -> int:
        await self.ensure_schema()
        pool = await self.pool()
        rows = [(r["accession"], r["file_num"], r["cik"], r["entity_name"], r["name_norm"], r["previous_names"], r["city"], r["state"],
                 r["entity_type"], r["year_inc"], r["industry"], r["revenue_range"], r["is_amendment"], r["previous_accession"],
                 _d(r["filing_date"]), _d(r["sale_date"]), r["offering_usd"], r["sold_usd"], r["investors_count"], r["is_operating"],
                 json.dumps(r["officers"]), quarter) for r in recs]
        async with pool.acquire() as conn:
            await conn.executemany("""INSERT INTO su_formd (accession, file_num, cik, entity_name, name_norm, previous_names, city, state, entity_type, year_inc,
                                      industry, revenue_range, is_amendment, previous_accession, filing_date, sale_date, offering_usd, sold_usd, investors_count,
                                      is_operating, officers, quarter) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21::jsonb,$22)
                                      ON CONFLICT (accession) DO NOTHING""", rows)
        return len(rows)

    # ------------------------------------------------------------------ maps (per-account saved searches, roster's model)
    async def create_map(self, *, owner_id: str, title: str, brief: str, contract: dict, rows: list[dict], coverage: dict) -> dict:
        import secrets, uuid
        await self.ensure_schema()
        mid, tok = uuid.uuid4().hex[:16], secrets.token_urlsafe(18)
        rows = _snapshot(rows)
        pool = await self.pool()
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("""INSERT INTO su_map (id, owner_id, title, brief, contract, rows, coverage, share_token)
                                  VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8)""",
                               mid, owner_id, (title or brief or "Startup map").strip()[:160], (brief or "")[:2000], json.dumps(contract), json.dumps(rows), json.dumps(coverage or {}), tok)
            await conn.execute("INSERT INTO su_map_revision (map_id, revision, reason, contract, rows, coverage) VALUES ($1, 0, 'initial', $2::jsonb, $3::jsonb, $4::jsonb)",
                               mid, json.dumps(contract), json.dumps(rows), json.dumps(coverage or {}))
        return {"id": mid, "share_token": tok, "title": title, "rows": len(rows)}

    async def get_map(self, mid: str, *, owner_id: str | None = None, share_token: str | None = None) -> dict | None:
        """The owner sees everything; a share token sees the map read-only; otherwise None."""
        await self.ensure_schema()
        pool = await self.pool()
        async with pool.acquire() as conn:
            m = await conn.fetchrow("SELECT id, owner_id, title, brief, contract, rows, coverage, notes, share_token, revision, created_at, updated_at FROM su_map WHERE id = $1", mid)
            if not m:
                return None
            if not (owner_id and m["owner_id"] == owner_id) and not (share_token and share_token == m["share_token"]):
                return None
            revs = await conn.fetch("SELECT revision, reason, created_at, jsonb_array_length(rows) AS n FROM su_map_revision WHERE map_id = $1 ORDER BY revision", mid)
        out = _row(m)
        for k in ("contract", "rows", "coverage"):
            out[k] = json.loads(out[k]) if isinstance(out[k], str) else out[k]
        out["owner"] = bool(owner_id and m["owner_id"] == owner_id)
        if not out["owner"]:
            out.pop("share_token", None)
        out["revisions"] = [{"revision": r["revision"], "reason": r["reason"], "rows": int(r["n"] or 0), "created_at": r["created_at"].isoformat()} for r in revs]
        return out

    async def list_maps(self, owner_id: str, *, limit: int = 50) -> list[dict]:
        await self.ensure_schema()
        pool = await self.pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, title, brief, revision, jsonb_array_length(rows) AS n, updated_at FROM su_map WHERE owner_id = $1 ORDER BY updated_at DESC LIMIT $2", owner_id, limit)
        return [{"id": r["id"], "title": r["title"], "brief": r["brief"], "revision": r["revision"], "rows": int(r["n"] or 0), "updated_at": r["updated_at"].isoformat()} for r in rows]

    async def revise_map(self, mid: str, *, owner_id: str, contract: dict, rows: list[dict], coverage: dict, reason: str = "navigated", title: str | None = None, notes: str | None = None) -> dict | None:
        await self.ensure_schema()
        rows = _snapshot(rows)
        pool = await self.pool()
        async with pool.acquire() as conn, conn.transaction():
            m = await conn.fetchrow("SELECT revision FROM su_map WHERE id = $1 AND owner_id = $2 FOR UPDATE", mid, owner_id)
            if not m:
                return None
            rev = int(m["revision"]) + 1
            await conn.execute("""UPDATE su_map SET contract = $2::jsonb, rows = $3::jsonb, coverage = $4::jsonb, revision = $5,
                                  title = COALESCE($6, title), notes = COALESCE($7, notes), updated_at = now() WHERE id = $1""",
                               mid, json.dumps(contract), json.dumps(rows), json.dumps(coverage or {}), rev, (title or None), notes)
            await conn.execute("INSERT INTO su_map_revision (map_id, revision, reason, contract, rows, coverage) VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6::jsonb)",
                               mid, rev, (reason or "")[:120], json.dumps(contract), json.dumps(rows), json.dumps(coverage or {}))
        return {"id": mid, "revision": rev, "rows": len(rows)}

    async def delete_map(self, mid: str, *, owner_id: str) -> bool:
        pool = await self.pool()
        async with pool.acquire() as conn:
            return (await conn.execute("DELETE FROM su_map WHERE id = $1 AND owner_id = $2", mid, owner_id)).endswith("1")

    # ------------------------------------------------------------------ reads
    async def company(self, cid: str) -> dict | None:
        await self.ensure_schema()
        pool = await self.pool()
        async with pool.acquire() as conn:
            c = await conn.fetchrow("SELECT id, name, legal_name, cik, website, one_liner, description, hq, yc_slug, yc_batch, aliases, sources, status, crawl, extracted_at, updated_at FROM su_company WHERE id = $1", cid)
            if not c:
                return None
            facts = await conn.fetch("SELECT key, value, number, display, provenance, basis, source_url, quote, as_of, confidence FROM su_fact WHERE company_id = $1 ORDER BY key, provenance", cid)
            fin = await conn.fetch("SELECT kind, file_num, accession, round_name, amount_usd, offering_usd, event_date, investors, lead, source_url, quote FROM su_financing WHERE company_id = $1 ORDER BY event_date NULLS LAST", cid)
            fo = await conn.fetch("SELECT name, title, prior_companies, provenance, source_url, quote FROM su_founder WHERE company_id = $1", cid)
            fd = await conn.fetch("SELECT accession, entity_name, city, state, filing_date, sale_date, sold_usd, offering_usd, revenue_range, is_amendment, match_method, officers FROM su_formd WHERE company_id = $1 ORDER BY filing_date", cid)
        out = dict(c)
        out["crawl"] = json.loads(out["crawl"]) if isinstance(out["crawl"], str) else (out["crawl"] or {})
        out["facts"] = [_row(r) for r in facts]
        out["financing"] = [_row(r) for r in fin]
        out["founders"] = [_row(r) for r in fo]
        out["filings"] = [_row(r) for r in fd]
        return out

    async def companies_by_ids(self, ids: list[str]) -> dict[str, dict]:
        if not ids:
            return {}
        pool = await self.pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, name, website, one_liner, hq, yc_batch, sources, crawl, extracted_at FROM su_company WHERE id = ANY($1)", ids)
            facts = await conn.fetch("SELECT company_id, key, value, number, display, provenance, basis, source_url, quote, as_of FROM su_fact WHERE company_id = ANY($1)", ids)
            fo = await conn.fetch("SELECT company_id, name, title, prior_companies, provenance FROM su_founder WHERE company_id = ANY($1)", ids)
        out = {r["id"]: {**_row(r), "facts": [], "founders": []} for r in rows}
        for f in facts:
            out.get(f["company_id"], {}).setdefault("facts", []).append(_row(f))
        for f in fo:
            out.get(f["company_id"], {}).setdefault("founders", []).append(_row(f))
        for c in out.values():
            c["crawl"] = json.loads(c["crawl"]) if isinstance(c.get("crawl"), str) else (c.get("crawl") or {})
        return out

    async def coverage(self) -> dict:
        await self.ensure_schema()
        pool = await self.pool()
        async with pool.acquire() as conn:
            total = int(await conn.fetchval("SELECT count(*) FROM su_company WHERE status = 'active'") or 0)
            known = await conn.fetch("SELECT key, count(DISTINCT company_id) AS n FROM su_fact f JOIN su_company c ON c.id = f.company_id WHERE c.status = 'active' GROUP BY key")
            src = await conn.fetch("SELECT s AS source, count(*) AS n FROM su_company, unnest(sources) s WHERE status = 'active' GROUP BY s")
            crawled = int(await conn.fetchval("SELECT count(*) FROM su_company WHERE status = 'active' AND crawl <> '{}'::jsonb") or 0)
            extracted = int(await conn.fetchval("SELECT count(*) FROM su_company WHERE status = 'active' AND extracted_at IS NOT NULL") or 0)
            formd = await conn.fetchrow("SELECT count(*) AS filings, count(*) FILTER (WHERE is_operating) AS operating, count(*) FILTER (WHERE company_id IS NOT NULL) AS matched, count(DISTINCT quarter) AS quarters FROM su_formd")
        return {"companies": total, "known": {r["key"]: int(r["n"]) for r in known},
                "known_rate": {r["key"]: (round(int(r["n"]) / total, 3) if total else 0.0) for r in known},
                "sources": {r["source"]: int(r["n"]) for r in src}, "crawled": crawled, "extracted": extracted,
                "formd": dict(formd) if formd else {}}

    # ------------------------------------------------------------------ FacetStore protocol (kernel evaluator)
    def _must_sql(self, must: dict, args: list, *, exclude: dict | None = None) -> list[str]:
        """One EXISTS per must key (OR within the key), applied to su_company `c`; NOT EXISTS per exclusion key."""
        cl: list[str] = []
        for key, want in (must or {}).items():
            k = self._schema.key(key)
            if k is None:
                continue
            if isinstance(want, dict):
                lo, hi = want.get("min"), want.get("max")
                conds = ["f.key = $%d" % (len(args) + 1)]
                args.append(key)
                if lo is not None:
                    args.append(float(lo)); conds.append("f.number >= $%d" % len(args))
                if hi is not None:
                    args.append(float(hi)); conds.append("f.number <= $%d" % len(args))
                cl.append("EXISTS (SELECT 1 FROM su_fact f WHERE f.company_id = c.id AND " + " AND ".join(conds) + ")")
            else:
                vals = [str(v) for v in (want or []) if str(v) and str(v) != UNKNOWN]
                if not vals:
                    continue
                args.append(key); ki = len(args)
                args.append(vals); vi = len(args)
                cl.append(f"EXISTS (SELECT 1 FROM su_fact f WHERE f.company_id = c.id AND f.key = ${ki} AND f.value = ANY(${vi}))")
        for key, vals in (exclude or {}).items():
            vals = [str(v) for v in (vals or []) if str(v)]
            if self._schema.key(key) is None or not vals:
                continue
            args.append(key); ki = len(args)
            args.append(vals); vi = len(args)
            cl.append(f"NOT EXISTS (SELECT 1 FROM su_fact f WHERE f.company_id = c.id AND f.key = ${ki} AND f.value = ANY(${vi}))")
        return cl

    async def _rows(self, conn, ids: list[str], sims: dict[str, float]) -> list[dict]:
        if not ids:
            return []
        facts = await conn.fetch("SELECT company_id, key, value, number FROM su_fact WHERE company_id = ANY($1)", ids)
        by: dict[str, dict] = {i: {"id": i, "kind": KIND, "sim": sims.get(i, 0.0), "facets": {}, "numeric": {}} for i in ids}
        for f in facts:
            r = by[f["company_id"]]
            r["facets"].setdefault(f["key"], [])
            if f["value"] not in r["facets"][f["key"]]:
                r["facets"][f["key"]].append(f["value"])
            if f["number"] is not None:
                cur = r["numeric"].get(f["key"])
                r["numeric"][f["key"]] = max(cur, f["number"]) if cur is not None else f["number"]
        return [by[i] for i in ids]

    async def enumerate(self, kind: str, must: dict, *, cap: int = 400, exclude: dict | None = None) -> list[dict]:
        await self.ensure_schema()
        pool = await self.pool()
        args: list = []
        cl = self._must_sql(must, args, exclude=exclude)
        where = " AND ".join(["c.status = 'active'"] + cl)
        args.append(cap)
        async with pool.acquire() as conn:
            ids = [r["id"] for r in await conn.fetch(f"SELECT c.id FROM su_company c WHERE {where} ORDER BY c.updated_at DESC LIMIT ${len(args)}", *args)]
            return await self._rows(conn, ids, {})

    async def semantic(self, kind: str, text: str, must: dict, *, cap: int = 400, exclude: dict | None = None, embed=None) -> list[dict]:
        if embed is None:
            return []
        await self.ensure_schema()
        vec = embed([text])[0]
        pool = await self.pool()
        args: list = [_vec(vec)]
        cl = self._must_sql(must, args, exclude=exclude)
        where = " AND ".join(["c.status = 'active'", "c.embedding IS NOT NULL"] + cl)
        args.append(cap)
        async with pool.acquire() as conn:
            rows = await conn.fetch(f"SELECT c.id, 1 - (c.embedding <=> $1::vector) AS sim FROM su_company c WHERE {where} ORDER BY c.embedding <=> $1::vector LIMIT ${len(args)}", *args)
            sims = {r["id"]: float(r["sim"] or 0.0) for r in rows}
            return await self._rows(conn, list(sims), sims)

    async def counts(self, kind: str, must: dict, schema: FacetSchema, *, depth: dict | None = None, exclude: dict | None = None) -> dict:
        await self.ensure_schema()
        pool = await self.pool()
        args: list = []
        cl = self._must_sql(must, args, exclude=exclude)
        where = " AND ".join(["c.status = 'active'"] + cl)
        nav = [k for k in schema.for_kind(kind) if k.navigable]
        async with pool.acquire() as conn:
            total = int(await conn.fetchval(f"SELECT count(*) FROM su_company c WHERE {where}", *args) or 0)
            rows = await conn.fetch(f"""WITH s AS (SELECT c.id FROM su_company c WHERE {where})
                                        SELECT f.key, f.value, count(DISTINCT f.company_id) AS n FROM su_fact f JOIN s ON s.id = f.company_id GROUP BY 1, 2""", *args)
            have = await conn.fetch(f"""WITH s AS (SELECT c.id FROM su_company c WHERE {where})
                                        SELECT f.key, count(DISTINCT f.company_id) AS n FROM su_fact f JOIN s ON s.id = f.company_id GROUP BY 1""", *args)
        by: dict[str, dict] = {}
        for r in rows:
            by.setdefault(r["key"], {})[r["value"]] = int(r["n"])
        have_n = {r["key"]: int(r["n"]) for r in have}
        out: dict = {}
        for k in nav:
            d = by.get(k.key, {})
            if k.type is FacetType.set:
                d = dict(sorted(d.items(), key=lambda kv: -kv[1])[: k.top_n])
            elif k.type in (FacetType.ordinal, FacetType.numeric):
                order = list(k.values) if k.type is FacetType.ordinal else [b[0] for b in k.bands]
                d = {v: d[v] for v in order if v in d}
            if k.type is not FacetType.set:
                unk = total - have_n.get(k.key, 0)
                if unk > 0:
                    d[UNKNOWN] = unk
            out[k.key] = d
        out["_total"] = total
        return out

    async def noise_floor(self, kind: str, text: str) -> float | None:
        return None

    async def slice_size(self, must: dict, *, exclude: dict | None = None, cap: int = 2001) -> int:
        """A LIMIT-bounded size of the must-slice — the structural probe recipes are measured with (tens of ms)."""
        await self.ensure_schema()
        pool = await self.pool()
        args: list = []
        cl = self._must_sql(must, args, exclude=exclude)
        where = " AND ".join(["c.status = 'active'"] + cl)
        args.append(cap)
        async with pool.acquire() as conn:
            return int(await conn.fetchval(f"SELECT count(*) FROM (SELECT 1 FROM su_company c WHERE {where} LIMIT ${len(args)}) t", *args) or 0)


def _snapshot(rows: list[dict]) -> list[dict]:
    """What a map remembers per row: identity, the one-liner, score / rank, and the facet tokens — never the
    hydrated card (that is re-read live), capped."""
    out = []
    for i, r in enumerate((rows or [])[:200]):
        co = r.get("company") or {}
        out.append({"id": r.get("id"), "name": co.get("name") or r.get("name") or r.get("id"), "one_liner": (co.get("one_liner") or r.get("one_liner") or "")[:200],
                    "score": r.get("score"), "rank": r.get("rank") or i + 1, "facets": r.get("facets") or {}})
    return out


def _d(s: str):
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _row(r) -> dict:
    out = {}
    for k, v in dict(r).items():
        if isinstance(v, (date, datetime)):
            out[k] = v.isoformat()
        elif isinstance(v, str) and k in ("officers",) :
            try:
                out[k] = json.loads(v)
            except Exception:   # noqa: BLE001
                out[k] = v
        else:
            out[k] = v
    return out


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
