"""asyncpg store for Investor Search (docs/specs/investors.md §6). Its own `iv_*` tables, its own pool.

Two departures from the startup store, both deliberate and both forced by measurement:

1. **The firm id is a minted slug, never a domain.** Measured against the real Form ADV registers on
   2026-09-09: of 7,424 VC/PE-managing firms, 980 publish no website at all and 2,417 more share a domain
   with another firm — 1,355 of them because they list `linkedin.com` as their website. A domain primary key
   fuses those into one node. The domain is an attribute and a merge signal (`iv_alias`), never the key.
2. **Every fact carries its REGISTER and its DENOMINATOR.** `filed | stated | observed` is what makes §0
   enforceable in SQL rather than by convention, and an observed number without the population it was measured
   over is not a number we are willing to render.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from eigen_kernel.facets import UNKNOWN, FacetSchema, FacetType

from .schema import KIND, REGISTER, SCHEMA

_DDL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS iv_firm (
    id            text PRIMARY KEY,             -- minted slug: a16z, general_catalyst, crd_342972_galileo_global
    name          text NOT NULL,
    legal_name    text NOT NULL DEFAULT '',
    kind          text NOT NULL DEFAULT 'firm',  -- firm | individual
    crd           text NOT NULL DEFAULT '',      -- Form ADV organization CRD — permanent strong id
    cik           text NOT NULL DEFAULT '',
    site          text NOT NULL DEFAULT '',
    domain        text NOT NULL DEFAULT '',      -- registrable domain, '' when they publish none
    hq_city       text NOT NULL DEFAULT '',
    hq_state      text NOT NULL DEFAULT '',
    hq_country    text NOT NULL DEFAULT '',
    entity_form   text NOT NULL DEFAULT '',      -- LLC, LP, corporation … as the register states it
    sources       text[] NOT NULL DEFAULT '{}',  -- sec_ria | sec_era | sec_formd | fca | portfolio_page | …
    status        text NOT NULL DEFAULT 'active',-- active | suppressed
    crawl         jsonb NOT NULL DEFAULT '{}',
    embedding     vector(1536),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
-- What the register says this adviser runs: {vc, pe, hedge, …}. An ALTER rather than a column in the CREATE
-- above, because CREATE TABLE IF NOT EXISTS is a no-op on a database that already has the table.
ALTER TABLE iv_firm ADD COLUMN IF NOT EXISTS fund_flags jsonb NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS ix_iv_firm_name   ON iv_firm (lower(name));
CREATE INDEX IF NOT EXISTS ix_iv_firm_crd    ON iv_firm (crd) WHERE crd <> '';
CREATE INDEX IF NOT EXISTS ix_iv_firm_domain ON iv_firm (domain) WHERE domain <> '';
CREATE INDEX IF NOT EXISTS ix_iv_firm_vec    ON iv_firm USING hnsw (embedding vector_cosine_ops);
-- The keyword leg. `simple` rather than `english`: firm names are proper nouns, and stemming "Ventures" to
-- "ventur" buys nothing while breaking exact-name matching.
ALTER TABLE iv_firm ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('simple'::regconfig,
        coalesce(name,'') || ' ' || coalesce(legal_name,'') || ' ' || coalesce(hq_city,'') || ' ' ||
        coalesce(replace(domain,'.',' '),''))) STORED;
CREATE INDEX IF NOT EXISTS ix_iv_firm_tsv ON iv_firm USING gin (tsv);

-- The join key's registry. `a16z`, `andreessen_horowitz` and `andreessen_horowitz_a16z` are three strings the
-- startup extractor can emit for one firm; this is where they become one id.
CREATE TABLE IF NOT EXISTS iv_alias (
    slug         text PRIMARY KEY,
    firm_id      text NOT NULL REFERENCES iv_firm(id) ON DELETE CASCADE,
    basis        text NOT NULL DEFAULT '',      -- curated | domain | crd | name_exact | operator
    source_url   text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_iv_alias_firm ON iv_alias (firm_id);

-- Brand succession is a dated arrow, never a merge: Sequoia -> Peak XV keeps both cards and both portfolios.
CREATE TABLE IF NOT EXISTS iv_firm_rel (
    from_id      text NOT NULL REFERENCES iv_firm(id) ON DELETE CASCADE,
    to_id        text NOT NULL REFERENCES iv_firm(id) ON DELETE CASCADE,
    kind         text NOT NULL,                 -- renamed | spun_out | affiliate | brand
    effective    date,
    source_url   text NOT NULL DEFAULT '',
    PRIMARY KEY (from_id, to_id, kind)
);

CREATE TABLE IF NOT EXISTS iv_fund (
    id           text PRIMARY KEY,              -- Form D file number when present, else the accession
    firm_id      text REFERENCES iv_firm(id) ON DELETE SET NULL,
    cluster_id   text NOT NULL DEFAULT '',      -- manager cluster before (or without) a firm attach
    name         text NOT NULL,
    file_num     text NOT NULL DEFAULT '',
    accession    text NOT NULL DEFAULT '',
    cik          text NOT NULL DEFAULT '',
    fund_type    text NOT NULL DEFAULT '',      -- as the filer states it: Venture Capital Fund | Private Equity Fund | …
    offered_usd  double precision,
    sold_usd     double precision,
    min_investment double precision,
    first_sale   date,
    filing_date  date,
    investors_n  bigint,
    city         text NOT NULL DEFAULT '',
    state        text NOT NULL DEFAULT '',
    persons      jsonb NOT NULL DEFAULT '[]',   -- related persons as filed: {name, roles}
    is_spv       boolean NOT NULL DEFAULT false,
    match_method text NOT NULL DEFAULT '',      -- cik | name_sequence | site_page | cluster | ''
    match_note   text NOT NULL DEFAULT '',
    quarter      text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_iv_fund_firm    ON iv_fund (firm_id) WHERE firm_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_iv_fund_cluster ON iv_fund (cluster_id) WHERE cluster_id <> '';
CREATE INDEX IF NOT EXISTS ix_iv_fund_type    ON iv_fund (fund_type) WHERE NOT is_spv;

CREATE TABLE IF NOT EXISTS iv_person (
    id           text PRIMARY KEY,              -- <firm_id>:<name_slug> for firm people; angel:<name_slug> for angels
    firm_id      text REFERENCES iv_firm(id) ON DELETE CASCADE,
    name         text NOT NULL,
    title        text NOT NULL DEFAULT '',
    role         text NOT NULL DEFAULT '',      -- gp | partner | principal | related_person | angel
    links        jsonb NOT NULL DEFAULT '{}',   -- {linkedin, x, site} — only where a page printed them
    basis        text NOT NULL DEFAULT '',
    source_url   text NOT NULL DEFAULT '',
    quote        text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_iv_person_firm ON iv_person (firm_id);

CREATE TABLE IF NOT EXISTS iv_edge (
    firm_id      text NOT NULL REFERENCES iv_firm(id) ON DELETE CASCADE,
    company_id   text NOT NULL,                 -- su_company.id (a domain, or cik:<n>)
    basis        text NOT NULL,                 -- portfolio_page | press_round | company_site | formd_person | lead
    role         text NOT NULL DEFAULT '',
    round_name   text NOT NULL DEFAULT '',
    event_date   date,
    source_url   text NOT NULL DEFAULT '',
    quote        text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (firm_id, company_id, basis)
);
CREATE INDEX IF NOT EXISTS ix_iv_edge_company ON iv_edge (company_id);
-- The company's name as the portfolio page printed it. A portfolio is mostly companies we do not hold, so
-- the edge must be renderable on its own rather than only through a join to su_company.
ALTER TABLE iv_edge ADD COLUMN IF NOT EXISTS company_name text NOT NULL DEFAULT '';
ALTER TABLE iv_edge ADD COLUMN IF NOT EXISTS company_site text NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS iv_page (
    firm_id      text NOT NULL REFERENCES iv_firm(id) ON DELETE CASCADE,
    url          text NOT NULL,
    kind         text NOT NULL DEFAULT '',
    sha          text NOT NULL,
    text         text NOT NULL DEFAULT '',
    html         text NOT NULL DEFAULT '',
    fetched_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (firm_id, url)
);

CREATE TABLE IF NOT EXISTS iv_fact (
    id           bigserial PRIMARY KEY,
    firm_id      text NOT NULL REFERENCES iv_firm(id) ON DELETE CASCADE,
    key          text NOT NULL,
    value        text NOT NULL DEFAULT '',
    number       double precision,
    display      text NOT NULL DEFAULT '',
    register     text NOT NULL,                 -- filed | stated | observed  (docs/specs/investors.md §0)
    basis        text NOT NULL DEFAULT '',      -- adv_raum | sum_of_filed_funds | form_d | site | derived
    provenance   text NOT NULL,
    source_url   text NOT NULL DEFAULT '',
    quote        text NOT NULL DEFAULT '',
    as_of        date,
    denominator  int,                           -- observed facts only: the population it was measured over
    confidence   real NOT NULL DEFAULT 1.0,
    schema_version text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (firm_id, key, value, provenance)
);
CREATE INDEX IF NOT EXISTS ix_iv_fact_kv   ON iv_fact (key, value);
CREATE INDEX IF NOT EXISTS ix_iv_fact_firm ON iv_fact (firm_id, key);

CREATE TABLE IF NOT EXISTS iv_return (
    id           bigserial PRIMARY KEY,
    firm_id      text REFERENCES iv_firm(id) ON DELETE SET NULL,
    fund_family  text NOT NULL,                 -- the LP's name for the fund; bound to a family, not a file number
    lp           text NOT NULL,                 -- CalSTRS | CalPERS | …
    vintage      int,
    committed    double precision,
    contributed  double precision,
    distributed  double precision,
    net_irr      double precision,
    dpi          double precision,
    tvpi         double precision,
    as_of        date,
    source_url   text NOT NULL DEFAULT '',
    UNIQUE (lp, fund_family, as_of)
);

CREATE TABLE IF NOT EXISTS iv_map (
    id           text PRIMARY KEY,
    owner_id     text NOT NULL,
    title        text NOT NULL,
    brief        text NOT NULL DEFAULT '',
    contract     jsonb NOT NULL,
    rows         jsonb NOT NULL DEFAULT '[]',
    coverage     jsonb NOT NULL DEFAULT '{}',
    notes        text NOT NULL DEFAULT '',
    share_token  text NOT NULL,
    revision     int NOT NULL DEFAULT 0,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_iv_map_owner ON iv_map (owner_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS iv_map_revision (
    map_id       text NOT NULL REFERENCES iv_map(id) ON DELETE CASCADE,
    revision     int NOT NULL,
    reason       text NOT NULL DEFAULT '',
    contract     jsonb NOT NULL,
    rows         jsonb NOT NULL DEFAULT '[]',
    coverage     jsonb NOT NULL DEFAULT '{}',
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (map_id, revision)
);

CREATE TABLE IF NOT EXISTS iv_job (
    id           bigserial PRIMARY KEY,
    kind         text NOT NULL,
    params       jsonb NOT NULL DEFAULT '{}',
    status       text NOT NULL DEFAULT 'queued',
    progress     jsonb NOT NULL DEFAULT '{}',
    error        text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
"""

_SLUG_RX = re.compile(r"[^a-z0-9]+")
# Hosts that are somebody's page, not somebody's site. Measured: 1,355 ADV firms give linkedin.com as their
# website, which is why this list exists before the first row is written rather than after the first bug.
NOT_A_SITE = {"linkedin.com", "twitter.com", "x.com", "facebook.com", "instagram.com", "youtube.com",
              "medium.com", "substack.com", "wordpress.com", "wixsite.com", "squarespace.com", "google.com",
              "crunchbase.com", "angel.co", "wellfound.com", "notion.site", "notion.so", "bit.ly", "sites.google.com"}


def slug(s: str, cap: int = 60) -> str:
    return _SLUG_RX.sub("_", (s or "").lower()).strip("_")[:cap]


def domain_of(url: str) -> str:
    """The registrable domain of a website field, or '' when it is a social page or unparseable.

    Delegates the public-suffix handling to the startup module's `registrable_domain` — one implementation of
    "what is this company's domain" across both modes, so an investor's site and a portfolio company's site are
    keyed the same way. What this adds is `NOT_A_SITE`: a firm whose "website" is a LinkedIn page has no domain.
    """
    from api.startups.sources.http import registrable_domain
    d = registrable_domain(url or "")
    return "" if not d or d in NOT_A_SITE else d


_LEGAL_TAIL = re.compile(r"(?i)[\s,]+(l\.?l\.?c\.?|l\.?p\.?|l\.?l\.?p\.?|inc\.?|incorporated|corp\.?|corporation|"
                         r"ltd\.?|limited|plc|pte\.?|gmbh|s\.?a\.?r\.?l\.?|b\.?v\.?|pty)\.?$")


def display_name(raw: str) -> str:
    """A firm name a person would recognise, from a register that shouts.

    Form ADV stores names in capitals ("UP PARTNERS MANAGEMENT COMPANY, LLC"), and a plain `.title()` turns
    the brands this mode is mostly about into nonsense: A16Z → "A16Z", 8VC → "8Vc", DCVC → "Dcvc". So the
    legal tail comes off, the rest is title-cased, and a short token that is an acronym — carrying a digit, or
    having no vowels — goes back to upper case.
    """
    name = (raw or "").strip()
    if not name:
        return ""
    prev = None
    while prev != name:                       # "Acme Holdings, LLC, L.P." — strip each tail, not just one
        prev = name
        name = _LEGAL_TAIL.sub("", name).strip(" ,.")
    if not name:
        name = (raw or "").strip()
    if not name.isupper():
        return name
    out = []
    for tok in name.split():
        core = re.sub(r"[^A-Za-z0-9]", "", tok)
        if core and len(core) <= 5 and (any(c.isdigit() for c in core) or not set(core.lower()) & set("aeiouy")):
            out.append(tok)                   # A16Z, DCVC, RCP, 8VC — leave them shouting
        else:
            out.append(tok.title())
    return " ".join(out)


def pg_text(v, cap: int | None = None) -> str:
    """Text Postgres will actually accept.

    A `text` column cannot hold a NUL byte, and the open web serves them: a firm's site returned HTML with an
    embedded 0x00 and the whole crawl job died with `invalid byte sequence for encoding "UTF8"`. Every string
    that comes from a fetched page goes through here — one bad byte on one site must not end a sweep over
    thousands.
    """
    s = (v or "").replace("\x00", "")
    return s[:cap] if cap else s


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vec(v) -> str | None:
    return None if v is None else "[" + ",".join(f"{float(x):.6f}" for x in v) + "]"


# With no search words there is nothing to rank by, and `updated_at` put "1789 Capital Management" at the top
# of "US venture funds" — alphabetical by accident of ingest order, which is no order at all. Recency of the
# last fund filing first, then size: for a founder, a firm that closed a fund last year is a live one, and a
# firm that has not filed since 2019 is not raising your round however large it once was. Both are filed facts.
_PROMINENCE = ("(SELECT f.number FROM iv_fact f WHERE f.firm_id = v.id AND f.key = 'latest_fund_year') DESC NULLS LAST, "
               "(SELECT f.number FROM iv_fact f WHERE f.firm_id = v.id AND f.key = 'aum') DESC NULLS LAST, "
               "v.id")


class InvestorStore:
    """asyncpg-backed, satisfying the kernel's FacetStore protocol for entity kind `investor`."""

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
    async def upsert_firm(self, f: dict) -> str:
        """Insert or refresh a firm by id. A present, non-empty field wins; an empty one never overwrites."""
        await self.ensure_schema()
        pool = await self.pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO iv_firm (id, name, legal_name, kind, crd, cik, site, domain, hq_city, hq_state,
                                     hq_country, entity_form, sources, fund_flags)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    name        = CASE WHEN EXCLUDED.name <> '' THEN EXCLUDED.name ELSE iv_firm.name END,
                    legal_name  = CASE WHEN EXCLUDED.legal_name <> '' THEN EXCLUDED.legal_name ELSE iv_firm.legal_name END,
                    crd         = CASE WHEN EXCLUDED.crd <> '' THEN EXCLUDED.crd ELSE iv_firm.crd END,
                    cik         = CASE WHEN EXCLUDED.cik <> '' THEN EXCLUDED.cik ELSE iv_firm.cik END,
                    site        = CASE WHEN EXCLUDED.site <> '' THEN EXCLUDED.site ELSE iv_firm.site END,
                    domain      = CASE WHEN EXCLUDED.domain <> '' THEN EXCLUDED.domain ELSE iv_firm.domain END,
                    hq_city     = CASE WHEN EXCLUDED.hq_city <> '' THEN EXCLUDED.hq_city ELSE iv_firm.hq_city END,
                    hq_state    = CASE WHEN EXCLUDED.hq_state <> '' THEN EXCLUDED.hq_state ELSE iv_firm.hq_state END,
                    hq_country  = CASE WHEN EXCLUDED.hq_country <> '' THEN EXCLUDED.hq_country ELSE iv_firm.hq_country END,
                    entity_form = CASE WHEN EXCLUDED.entity_form <> '' THEN EXCLUDED.entity_form ELSE iv_firm.entity_form END,
                    sources     = ARRAY(SELECT DISTINCT unnest(iv_firm.sources || EXCLUDED.sources)),
                    fund_flags  = CASE WHEN EXCLUDED.fund_flags <> '{}'::jsonb THEN EXCLUDED.fund_flags ELSE iv_firm.fund_flags END,
                    updated_at  = now()
            """, f["id"], f.get("name", ""), f.get("legal_name", ""), f.get("kind", "firm"), f.get("crd", ""),
                 f.get("cik", ""), f.get("site", ""), f.get("domain", ""), f.get("hq_city", ""), f.get("hq_state", ""),
                 f.get("hq_country", ""), f.get("entity_form", ""), list(f.get("sources") or []),
                 _json(f.get("fund_flags") or {}))
        return f["id"]

    async def firm_by_strong_id(self, *, crd: str = "", domain: str = "", cik: str = "") -> str | None:
        """The id of the firm carrying this strong id, or None. Never matches on name."""
        await self.ensure_schema()
        pool = await self.pool()
        async with pool.acquire() as conn:
            for col, val in (("crd", crd), ("cik", cik), ("domain", domain)):
                if val:
                    got = await conn.fetchval(f"SELECT id FROM iv_firm WHERE {col} = $1 LIMIT 1", val)
                    if got:
                        return got
        return None

    async def add_alias(self, alias: str, firm_id: str, *, basis: str = "", source_url: str = "") -> None:
        await self.ensure_schema()
        pool = await self.pool()
        async with pool.acquire() as conn:
            await conn.execute("""INSERT INTO iv_alias (slug, firm_id, basis, source_url) VALUES ($1,$2,$3,$4)
                                  ON CONFLICT (slug) DO NOTHING""", alias, firm_id, basis, source_url)

    async def firm_of_alias(self, alias: str) -> str | None:
        await self.ensure_schema()
        pool = await self.pool()
        async with pool.acquire() as conn:
            return await conn.fetchval("SELECT firm_id FROM iv_alias WHERE slug = $1", alias)

    async def relate(self, from_id: str, to_id: str, kind: str, *, effective=None, source_url: str = "") -> None:
        """A dated arrow between two firms — renamed, spun out, affiliate, brand. Never a merge."""
        await self.ensure_schema()
        pool = await self.pool()
        async with pool.acquire() as conn:
            await conn.execute("""INSERT INTO iv_firm_rel (from_id, to_id, kind, effective, source_url)
                                  VALUES ($1,$2,$3,$4,$5) ON CONFLICT (from_id, to_id, kind) DO NOTHING""",
                               from_id, to_id, kind, _date(effective), source_url)

    async def upsert_funds(self, funds: list[dict]) -> int:
        if not funds:
            return 0
        await self.ensure_schema()
        pool = await self.pool()
        rows = [(f["id"], f.get("name", ""), f.get("file_num", ""), f.get("accession", ""), f.get("cik", ""),
                 f.get("fund_type", ""), f.get("offered_usd"), f.get("sold_usd"), f.get("min_investment"),
                 _date(f.get("first_sale")), _date(f.get("filing_date")), f.get("investors_n"),
                 f.get("city", ""), f.get("state", ""), _json(f.get("persons") or []), bool(f.get("is_spv")),
                 f.get("quarter", "")) for f in funds]
        async with pool.acquire() as conn:
            await conn.executemany("""
                INSERT INTO iv_fund (id, name, file_num, accession, cik, fund_type, offered_usd, sold_usd,
                                     min_investment, first_sale, filing_date, investors_n, city, state, persons,
                                     is_spv, quarter)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb,$16,$17)
                ON CONFLICT (id) DO UPDATE SET
                    sold_usd    = COALESCE(EXCLUDED.sold_usd, iv_fund.sold_usd),
                    offered_usd = COALESCE(EXCLUDED.offered_usd, iv_fund.offered_usd),
                    investors_n = COALESCE(EXCLUDED.investors_n, iv_fund.investors_n),
                    first_sale  = LEAST(iv_fund.first_sale, EXCLUDED.first_sale),
                    filing_date = GREATEST(iv_fund.filing_date, EXCLUDED.filing_date),
                    persons     = CASE WHEN EXCLUDED.persons <> '[]'::jsonb THEN EXCLUDED.persons ELSE iv_fund.persons END
            """, rows)
        return len(rows)

    async def attach_fund(self, fund_id: str, firm_id: str | None, *, cluster_id: str = "",
                          method: str = "", note: str = "") -> None:
        await self.ensure_schema()
        pool = await self.pool()
        async with pool.acquire() as conn:
            await conn.execute("""UPDATE iv_fund SET firm_id = $2, cluster_id = $3, match_method = $4, match_note = $5
                                  WHERE id = $1""", fund_id, firm_id, cluster_id, method, note)

    async def put_facts(self, firm_id: str, facts: list[dict], *, keys: list[str] | None = None) -> int:
        """DELETE-then-INSERT per key: `iv_fact` is a rebuildable read model, not an append-only ledger.

        The register is taken from the SCHEMA, never from the caller — that is what makes §0's promise
        ("a stated number may never be shown where a filed one belongs") a property of the code.
        """
        await self.ensure_schema()
        pool = await self.pool()
        ks = list(keys or {f["key"] for f in facts})
        rows = []
        for f in facts:
            key = f["key"]
            reg = REGISTER.get(key)
            if reg is None:
                continue
            rows.append((firm_id, key, pg_text(str(f.get("value", "")), 200), f.get("number"),
                         pg_text(f.get("display"), 120), reg, pg_text(f.get("basis"), 60),
                         pg_text(f.get("provenance"), 40), pg_text(f.get("source_url"), 2000),
                         pg_text(f.get("quote"), 600), _date(f.get("as_of")), f.get("denominator"),
                         float(f.get("confidence", 1.0)), SCHEMA.version()))
        async with pool.acquire() as conn:
            async with conn.transaction():
                if ks:
                    await conn.execute("DELETE FROM iv_fact WHERE firm_id = $1 AND key = ANY($2)", firm_id, ks)
                if rows:
                    await conn.executemany("""
                        INSERT INTO iv_fact (firm_id, key, value, number, display, register, basis, provenance,
                                             source_url, quote, as_of, denominator, confidence, schema_version)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                        ON CONFLICT (firm_id, key, value, provenance) DO NOTHING""", rows)
        return len(rows)

    async def put_edges(self, edges: list[dict]) -> int:
        if not edges:
            return 0
        await self.ensure_schema()
        pool = await self.pool()
        rows = [(e["firm_id"], pg_text(e["company_id"], 253), pg_text(e.get("basis") or "portfolio_page", 40),
                 pg_text(e.get("role"), 40), pg_text(e.get("round_name"), 40), _date(e.get("event_date")),
                 pg_text(e.get("source_url"), 2000), pg_text(e.get("quote"), 600),
                 pg_text(e.get("company_name"), 120), pg_text(e.get("company_site"), 400)) for e in edges]
        async with pool.acquire() as conn:
            await conn.executemany("""
                INSERT INTO iv_edge (firm_id, company_id, basis, role, round_name, event_date, source_url, quote,
                                     company_name, company_site)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT (firm_id, company_id, basis) DO UPDATE SET
                    role = CASE WHEN EXCLUDED.role = 'lead' THEN 'lead' ELSE iv_edge.role END,
                    round_name = CASE WHEN EXCLUDED.round_name <> '' THEN EXCLUDED.round_name ELSE iv_edge.round_name END,
                    event_date = COALESCE(EXCLUDED.event_date, iv_edge.event_date),
                    company_name = CASE WHEN EXCLUDED.company_name <> '' THEN EXCLUDED.company_name ELSE iv_edge.company_name END,
                    company_site = CASE WHEN EXCLUDED.company_site <> '' THEN EXCLUDED.company_site ELSE iv_edge.company_site END""", rows)
        return len(rows)

    async def put_people(self, firm_id: str, people: list[dict]) -> int:
        """Replace this firm's people. A team page is a snapshot, so a partner who left should leave the card.

        Stored: name, stated title and role, and the profile links the page printed. NEVER a photo, an email,
        a phone number or an address — an investor card is about a professional role, and the spec's PII rule
        for individuals is enforced by what this method is able to write.
        """
        await self.ensure_schema()
        pool = await self.pool()
        rows = []
        for p in people:
            name = (p.get("name") or "").strip()
            if not name:
                continue
            links = {k: v for k, v in (p.get("links") or {}).items() if k in ("linkedin", "x", "profile", "site")}
            links = {k: pg_text(v, 400) for k, v in links.items()}
            rows.append((f"{firm_id}:{slug(name)}", firm_id, pg_text(name, 120), pg_text(p.get("title"), 80),
                         pg_text(p.get("role"), 40), _json(links), pg_text(p.get("basis"), 40),
                         pg_text(p.get("source_url"), 2000)))
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM iv_person WHERE firm_id = $1", firm_id)
                if rows:
                    await conn.executemany("""
                        INSERT INTO iv_person (id, firm_id, name, title, role, links, basis, source_url)
                        VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8)
                        ON CONFLICT (id) DO UPDATE SET
                            title = EXCLUDED.title, role = EXCLUDED.role, links = EXCLUDED.links,
                            basis = EXCLUDED.basis, source_url = EXCLUDED.source_url""", rows)
        return len(rows)

    async def put_pages(self, firm_id: str, pages: list[dict]) -> int:
        await self.ensure_schema()
        pool = await self.pool()
        rows = [(firm_id, pg_text(p.get("final_url") or p.get("url"), 2000), pg_text(p.get("kind"), 40),
                 pg_text(p.get("sha"), 64), pg_text(p.get("text"), 200_000), pg_text(p.get("html"), 400_000))
                for p in pages if (p.get("final_url") or p.get("url"))]
        async with pool.acquire() as conn:
            await conn.executemany("""
                INSERT INTO iv_page (firm_id, url, kind, sha, text, html) VALUES ($1,$2,$3,$4,$5,$6)
                ON CONFLICT (firm_id, url) DO UPDATE SET
                    kind = EXCLUDED.kind, sha = EXCLUDED.sha, text = EXCLUDED.text, html = EXCLUDED.html,
                    fetched_at = now()""", rows)
        return len(rows)

    async def note_crawl(self, firm_id: str, info: dict) -> None:
        await self.ensure_schema()
        pool = await self.pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE iv_firm SET crawl = $2::jsonb, updated_at = now() WHERE id = $1",
                               firm_id, _json(info))

    # ------------------------------------------------------------------ facet protocol
    def _must_sql(self, must: dict, args: list, *, exclude: dict | None = None) -> list[str]:
        """One EXISTS per must key (OR within the key), applied to iv_firm `v`; NOT EXISTS per exclusion key.

        A must on a key that has a UNIFIED twin (stated_stage ↔ observed_stage) matches EITHER register — one
        control, two registers underneath (§4). The card reports which one matched; the filter does not care.
        """
        from .schema import UNIFIED
        pairs = {**UNIFIED, **{v: k for k, v in UNIFIED.items()}}
        cl: list[str] = []
        for key, want in (must or {}).items():
            if self._schema.key(key) is None:
                continue
            keys = [key] + ([pairs[key]] if key in pairs else [])
            if isinstance(want, dict):
                lo, hi = want.get("min"), want.get("max")
                args.append(keys); ki = len(args)
                conds = [f"f.key = ANY(${ki})"]
                if lo is not None:
                    args.append(float(lo)); conds.append(f"f.number >= ${len(args)}")
                if hi is not None:
                    args.append(float(hi)); conds.append(f"f.number <= ${len(args)}")
                cl.append("EXISTS (SELECT 1 FROM iv_fact f WHERE f.firm_id = v.id AND " + " AND ".join(conds) + ")")
            else:
                vals = [str(x) for x in (want or []) if str(x) and str(x) != UNKNOWN]
                if not vals:
                    continue
                args.append(keys); ki = len(args)
                args.append(vals); vi = len(args)
                cl.append(f"EXISTS (SELECT 1 FROM iv_fact f WHERE f.firm_id = v.id AND f.key = ANY(${ki}) AND f.value = ANY(${vi}))")
        for key, vals in (exclude or {}).items():
            vals = [str(x) for x in (vals or []) if str(x)]
            if self._schema.key(key) is None or not vals:
                continue
            args.append(key); ki = len(args)
            args.append(vals); vi = len(args)
            cl.append(f"NOT EXISTS (SELECT 1 FROM iv_fact f WHERE f.firm_id = v.id AND f.key = ${ki} AND f.value = ANY(${vi}))")
        return cl

    async def _rows(self, conn, ids: list[str], sims: dict[str, float]) -> list[dict]:
        if not ids:
            return []
        # `denominator` rides along because an observed fact is only meaningful against the population
        # it was measured over: five climate companies out of ten is a thesis, five out of a thousand
        # is a rounding error, and without the denominator a ranker cannot tell those apart.
        facts = await conn.fetch(
            "SELECT firm_id, key, value, number, denominator FROM iv_fact WHERE firm_id = ANY($1)", ids)
        by = {i: {"id": i, "kind": KIND, "sim": sims.get(i, 0.0), "facets": {}, "numeric": {}, "denom": {}}
              for i in ids}
        for f in facts:
            r = by[f["firm_id"]]
            r["facets"].setdefault(f["key"], [])
            if f["value"] and f["value"] not in r["facets"][f["key"]]:
                r["facets"][f["key"]].append(f["value"])
            if f["number"] is not None:
                cur = r["numeric"].get(f["key"])
                r["numeric"][f["key"]] = max(cur, f["number"]) if cur is not None else f["number"]
            if f["denominator"] is not None:
                d = r["denom"].get(f["key"])
                r["denom"][f["key"]] = max(d, f["denominator"]) if d is not None else f["denominator"]
        return [by[i] for i in ids]

    async def enumerate(self, kind: str, must: dict, *, cap: int = 400, exclude: dict | None = None) -> list[dict]:
        await self.ensure_schema()
        pool = await self.pool()
        args: list = []
        where = " AND ".join(["v.status = 'active'"] + self._must_sql(must, args, exclude=exclude))
        args.append(cap)
        async with pool.acquire() as conn:
            ids = [r["id"] for r in await conn.fetch(
                f"SELECT v.id FROM iv_firm v WHERE {where} ORDER BY {_PROMINENCE} LIMIT ${len(args)}", *args)]
            return await self._rows(conn, ids, {})

    async def semantic(self, kind: str, text: str, must: dict, *, cap: int = 400,
                       exclude: dict | None = None, embed=None) -> list[dict]:
        if embed is None:
            return []
        await self.ensure_schema()
        vec = embed([text])[0]
        pool = await self.pool()
        args: list = [_vec(vec)]
        where = " AND ".join(["v.status = 'active'", "v.embedding IS NOT NULL"] + self._must_sql(must, args, exclude=exclude))
        args.append(cap)
        async with pool.acquire() as conn:
            rows = await conn.fetch(f"""SELECT v.id, 1 - (v.embedding <=> $1::vector) AS sim FROM iv_firm v
                                        WHERE {where} ORDER BY v.embedding <=> $1::vector LIMIT ${len(args)}""", *args)
            sims = {r["id"]: float(r["sim"] or 0.0) for r in rows}
            return await self._rows(conn, list(sims), sims)

    async def keyword(self, kind: str, text: str, must: dict, *, cap: int = 400,
                      exclude: dict | None = None) -> list[dict]:
        """The lexical leg: Postgres full text over the firm's names, city and domain, plus an alias hit.

        A vector index is very good at "climate infrastructure funds in Europe" and quietly bad at "8VC" —
        a short proper noun has almost no semantic signal, and the nearest neighbours of a rare token are
        noise. The alias arm is what makes "andreessen horowitz" find `a16z`, which no embedding of the name
        will do either.
        """
        await self.ensure_schema()
        q = (text or "").strip()
        if not q:
            return []
        pool = await self.pool()
        args: list = [q, slug(q)]
        where = " AND ".join(["v.status = 'active'"] + self._must_sql(must, args, exclude=exclude))
        args.append(cap)
        async with pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT v.id,
                       GREATEST(ts_rank(v.tsv, websearch_to_tsquery('simple', $1)),
                                CASE WHEN a.slug IS NOT NULL THEN 1.0 ELSE 0 END) AS score
                FROM iv_firm v
                LEFT JOIN iv_alias a ON a.firm_id = v.id AND a.slug = $2
                WHERE {where} AND (v.tsv @@ websearch_to_tsquery('simple', $1) OR a.slug IS NOT NULL)
                ORDER BY score DESC, v.updated_at DESC LIMIT ${len(args)}""", *args)
            sims = {r["id"]: float(r["score"] or 0.0) for r in rows}
            return await self._rows(conn, list(sims), sims)

    async def hybrid(self, kind: str, text: str, must: dict, *, cap: int = 400, exclude: dict | None = None,
                     embed=None, k: int = 60, weights: dict | None = None) -> tuple[list[dict], dict]:
        """Both legs, reciprocal-rank-fused. Returns (rows, diagnostics).

        RRF is used rather than a score blend because the two legs' scores are not comparable — cosine
        similarity and `ts_rank` live on different scales with different distributions, and normalising them
        against each other invents a calibration nobody measured. Rank is the only thing they agree on.

        The fused score is mapped back onto `sim` in (0, 1] so the kernel evaluator, which knows nothing about
        fusion, keeps ranking exactly as it does for a single leg. `_found_by` travels with the row so the card
        can say which leg found it.
        """
        from eigen_kernel.facets.contract_search import rrf_fuse
        legs: dict[str, list[dict]] = {}
        diag: dict = {}
        if embed is not None:
            try:
                legs["semantic"] = await self.semantic(kind, text, must, cap=cap, exclude=exclude, embed=embed)
            except Exception as e:      # noqa: BLE001 — an embedding outage degrades to keyword, never a 500
                diag["degraded"] = f"embeddings unavailable ({type(e).__name__}): keyword only"
        legs["keyword"] = await self.keyword(kind, text, must, cap=cap, exclude=exclude)
        legs = {n: rows for n, rows in legs.items() if rows}
        if not legs:
            return [], diag
        if len(legs) == 1:
            only = next(iter(legs))
            diag["legs"] = {only: len(legs[only])}
            rows = legs[only][:cap]
            for i, r in enumerate(rows, start=1):
                r["_found_by"] = {only: i}      # the card says which leg found it, fused or not
            return rows, diag
        fused = rrf_fuse(legs, k=k, weights=weights)[:cap]
        top = fused[0]["_fused"] if fused else 1.0
        for r in fused:
            r["sim"] = round(min(1.0, r["_fused"] / top), 6) if top else 0.0
        diag["legs"] = {n: len(v) for n, v in legs.items()}
        diag["fused"] = len(fused)
        diag["both"] = sum(1 for r in fused if len(r.get("_found_by") or {}) > 1)
        return fused, diag

    async def counts(self, kind: str, must: dict, schema: FacetSchema, *, depth: dict | None = None,
                     exclude: dict | None = None) -> dict:
        await self.ensure_schema()
        pool = await self.pool()
        args: list = []
        where = " AND ".join(["v.status = 'active'"] + self._must_sql(must, args, exclude=exclude))
        nav = [k for k in schema.for_kind(kind) if k.navigable]
        async with pool.acquire() as conn:
            total = int(await conn.fetchval(f"SELECT count(*) FROM iv_firm v WHERE {where}", *args) or 0)
            rows = await conn.fetch(f"""WITH s AS (SELECT v.id FROM iv_firm v WHERE {where})
                                        SELECT f.key, f.value, count(DISTINCT f.firm_id) AS n
                                        FROM iv_fact f JOIN s ON s.id = f.firm_id GROUP BY 1, 2""", *args)
            have = await conn.fetch(f"""WITH s AS (SELECT v.id FROM iv_firm v WHERE {where})
                                        SELECT f.key, count(DISTINCT f.firm_id) AS n
                                        FROM iv_fact f JOIN s ON s.id = f.firm_id GROUP BY 1""", *args)
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
        await self.ensure_schema()
        pool = await self.pool()
        args: list = []
        where = " AND ".join(["v.status = 'active'"] + self._must_sql(must, args, exclude=exclude))
        args.append(cap)
        async with pool.acquire() as conn:
            return int(await conn.fetchval(
                f"SELECT count(*) FROM (SELECT 1 FROM iv_firm v WHERE {where} LIMIT ${len(args)}) t", *args) or 0)

    # ------------------------------------------------------------------ reads for the card
    async def firm(self, firm_id: str) -> dict | None:
        await self.ensure_schema()
        pool = await self.pool()
        async with pool.acquire() as conn:
            r = await conn.fetchrow("SELECT * FROM iv_firm WHERE id = $1", firm_id)
            if not r:
                return None
            out = {k: r[k] for k in r.keys() if k != "embedding"}
            out["funds"] = [dict(x) for x in await conn.fetch(
                "SELECT id, name, fund_type, sold_usd, offered_usd, first_sale, investors_n, state FROM iv_fund "
                "WHERE firm_id = $1 AND NOT is_spv ORDER BY first_sale DESC NULLS LAST LIMIT 50", firm_id)]
            out["facts"] = [dict(x) for x in await conn.fetch(
                "SELECT key, value, number, display, register, basis, source_url, as_of, denominator "
                "FROM iv_fact WHERE firm_id = $1 ORDER BY key", firm_id)]
            out["people"] = [dict(x) for x in await conn.fetch(
                "SELECT name, title, role, links, source_url FROM iv_person WHERE firm_id = $1 LIMIT 60", firm_id)]
            out["edges"] = [dict(x) for x in await conn.fetch(
                "SELECT company_id, company_name, company_site, basis, role, round_name, event_date, source_url "
                "FROM iv_edge WHERE firm_id = $1 ORDER BY event_date DESC NULLS LAST LIMIT 400", firm_id)]
        return out

    async def coverage(self) -> dict:
        await self.ensure_schema()
        pool = await self.pool()
        async with pool.acquire() as conn:
            firms = int(await conn.fetchval("SELECT count(*) FROM iv_firm WHERE status = 'active'") or 0)
            known = {r["key"]: int(r["n"]) for r in await conn.fetch(
                "SELECT key, count(DISTINCT firm_id) AS n FROM iv_fact GROUP BY 1")}
            src = {r["s"]: int(r["n"]) for r in await conn.fetch(
                "SELECT unnest(sources) AS s, count(*) AS n FROM iv_firm GROUP BY 1 ORDER BY 2 DESC")}
            funds = dict(await conn.fetchrow(
                "SELECT count(*) AS total, count(*) FILTER (WHERE NOT is_spv) AS real, "
                "count(*) FILTER (WHERE firm_id IS NOT NULL) AS attached FROM iv_fund") or {})
            edges = int(await conn.fetchval("SELECT count(*) FROM iv_edge") or 0)
        return {"firms": firms, "known": known,
                "known_rate": {k: round(v / firms, 3) for k, v in known.items()} if firms else {},
                "sources": src, "funds": {k: int(v or 0) for k, v in funds.items()}, "edges": edges}


def _date(v):
    if not v:
        return None
    if hasattr(v, "year"):
        return v
    try:
        from datetime import date
        return date.fromisoformat(str(v)[:10])
    except Exception:      # noqa: BLE001 — a bad date is no date, never a failed ingest
        return None


def _json(v) -> str:
    import json
    return json.dumps(v)
