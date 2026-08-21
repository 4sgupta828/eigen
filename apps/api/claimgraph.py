"""Claim-graph store — Layer 1 of the grounded, temporal claim graph.

The atomic unit is a GROUNDED, BITEMPORAL CLAIM
`(subject_entity, predicate, object[value|entity], valid_time, evidence{document_id,
block_id, quote, authority_tier}, confidence)`. Every product surface (startups
table, landscape map, competitor set) is a query over the accumulated graph. See
`docs/factgraph_slice1_plan.md` for the panel synthesis and the reused-vs-net-new
split.

App-level (NOT kernel) Postgres module, same DSN `EIGEN_CORPUS_DSN` and same style
as `apps/api/glossary.py` / `apps/api/gap_queue.py` (asyncpg pool, module-level
`_DDL`, lazy `_ensure()`). The store MECHANICS are domain-neutral; the vocabulary
(predicate names, entity kinds) arrives as DATA seeded from the vertical registry
`eigen_vertical_tech.claim_predicates.SLICE1_PREDICATES`.

WRITE ETHOS (mirrors `packages/kernel/eigen_kernel/people/store.py`):
  * append-only — a claim is written once; conflicting/newer facts are NEW claims.
  * never-resurrect — suppression/staleness is a STATUS FLIP, never a DELETE.
    Entities go active→suppressed; evidence goes active→stale/retracted; losing
    claims stay queryable (resolution names the winner, doesn't erase the losers).
  * per-claim provenance — every user-visible fact is a claim citing a block+quote;
    the canonical entity id is an internal resolution artifact, not itself a quote.

Deterministic ids (pure stdlib hashlib) make writes idempotent: the same logical
claim always hashes to the same `claim_id`, so re-extraction upserts, never dups.

NOTE: not wired into app startup or any live path yet — that is a later task.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any, Sequence

_WS = re.compile(r"\s+")

# Legal-form suffix tokens stripped when normalizing a name for alias resolution.
# These are structural (a company's legal form), NOT a semantic judgement — the
# named four (inc/llc/ltd/corp) are the brief's floor; the rest are common forms.
_LEGAL_SUFFIXES = frozenset({
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation",
    "co", "company", "plc", "gmbh", "lp", "llp", "sa", "ag", "nv", "bv",
    "srl", "oy", "ab", "as", "pty",
})


# --------------------------------------------------------------------------- #
# Pure helpers (NO DB — unit-tested directly)                                 #
# --------------------------------------------------------------------------- #
def normalize_quote(s: str) -> str:
    """Whitespace-collapsed, lowercased — IDENTICAL to
    `eigen_kernel.research.provenance.normalize` so a `quote_hash` computed here
    lines up with the span gate's normalized-substring check. Keep in lockstep."""
    return _WS.sub(" ", (s or "").strip().lower())


def normalize_name(s: str) -> str:
    """Normalize an entity name/alias for exact (non-fuzzy) resolution: lowercase,
    drop punctuation, collapse whitespace, and strip trailing legal-form suffixes
    (`Acme, Inc.` / `Acme LLC` / `Acme Corp` → `acme`). Structural only (Rule 18):
    this is a computable string normalization, not a semantic merge — slice-1 does
    NO fuzzy ER."""
    s = (s or "").lower()
    s = re.sub(r"[^\w\s]", " ", s)          # punctuation → space (keeps digits/underscore)
    tokens = _WS.sub(" ", s).strip().split()
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def quote_hash(quote: str) -> str:
    """sha256 of the NORMALIZED quote (so trivial reflow/case never breaks dedup)."""
    return hashlib.sha256(normalize_quote(quote).encode("utf-8")).hexdigest()


def _sha(*parts: str) -> str:
    """sha256 over unit-separator-joined parts (0x1f can't appear in the inputs)."""
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def make_claim_id(*, tenant_id: str, subject_id: str, predicate: str, object_kind: str,
                  object_norm: str, object_entity_id: str, valid_from: str,
                  schema_version: int) -> str:
    """Deterministic claim id = sha256 of the DEDUP KEY. The object discriminator is
    the referenced entity for entity-claims, else the normalized value. `valid_from`
    is the ISO date string (or '' when unknown/static) — a different valid_from is a
    DIFFERENT logical claim (bitemporal), so it hashes differently."""
    obj = object_entity_id if object_kind == "entity" else object_norm
    return _sha(tenant_id, subject_id, predicate, object_kind, obj,
                valid_from or "", str(schema_version))


def make_evidence_id(*, claim_id: str, document_id: str, block_id: str,
                     quote_hash_hex: str) -> str:
    """Deterministic evidence id = sha256(claim_id|document_id|block_id|quote_hash)."""
    return _sha(claim_id, document_id, block_id, quote_hash_hex)


def _iso(d: "date | None") -> str:
    return d.isoformat() if d is not None else ""


# --------------------------------------------------------------------------- #
# DDL — 7 tables, CREATE TABLE IF NOT EXISTS, on EIGEN_CORPUS_DSN             #
# --------------------------------------------------------------------------- #
_DDL = """
-- Typed entities. The row is a RESOLUTION ARTIFACT; identity is backed by identity
-- claims. Every USER-VISIBLE fact about the entity is a claim (below), not a column.
CREATE TABLE IF NOT EXISTS rs_entity (
    entity_id      text PRIMARY KEY,          -- natural key: 'domain:acme.com'|'yc:slug'|'cik:..'|'__unresolved:<norm>'
    tenant_id      text NOT NULL DEFAULT 'demo',
    kind           text NOT NULL,             -- company|person|investor|product|category|technology|market
    name           text NOT NULL,
    canonical_name text NOT NULL DEFAULT '',
    primary_domain text NOT NULL DEFAULT '',
    status         text NOT NULL DEFAULT 'active',   -- active|suppressed  (never DELETE)
    first_run_id   text NOT NULL DEFAULT '',
    facets         jsonb NOT NULL DEFAULT '{}',
    retrieved_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_rs_entity_kind   ON rs_entity (tenant_id, kind);
CREATE INDEX IF NOT EXISTS ix_rs_entity_name   ON rs_entity (lower(name));
CREATE INDEX IF NOT EXISTS ix_rs_entity_domain ON rs_entity (primary_domain) WHERE primary_domain <> '';

-- alias -> entity resolution (strong-id + normalized-name bootstrap; no fuzzy ER in slice 1)
CREATE TABLE IF NOT EXISTS rs_entity_alias (
    alias_norm  text NOT NULL,
    entity_id   text NOT NULL REFERENCES rs_entity(entity_id),
    alias       text NOT NULL,
    source      text NOT NULL DEFAULT '',
    retrieved_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (alias_norm, entity_id)
);

-- The atomic bitemporal grounded claim. Object is EITHER a value or an entity ref.
CREATE TABLE IF NOT EXISTS rs_claim (
    claim_id        text PRIMARY KEY,          -- deterministic sha256 of the dedup key (see below)
    tenant_id       text NOT NULL DEFAULT 'demo',
    subject_id      text NOT NULL REFERENCES rs_entity(entity_id),
    predicate       text NOT NULL,             -- must be an rs_predicate.name with status='active' at write
    object_kind     text NOT NULL,             -- 'value' | 'entity'
    object_value    text NOT NULL DEFAULT '',  -- when object_kind='value'
    object_norm     text NOT NULL DEFAULT '',  -- normalized object for dedup/grouping
    object_entity_id text NOT NULL DEFAULT '', -- when object_kind='entity'
    unit            text NOT NULL DEFAULT '',
    valid_from      date,                       -- valid-time (nullable = unknown/static)
    valid_to        date,
    valid_granularity text NOT NULL DEFAULT '', -- 'year'|'quarter'|'month'|'day'|''
    observed_at     date,                        -- as-stated observation date if any
    ingested_at     timestamptz NOT NULL DEFAULT now(),
    superseded_at   timestamptz,                 -- set when a newer claim supersedes (never overwrite)
    retracted_at    timestamptz,                 -- set when source retracted
    confidence      numeric NOT NULL DEFAULT 0,
    schema_version  int NOT NULL DEFAULT 1,
    extractor_version text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_rs_claim_subj_pred ON rs_claim (tenant_id, subject_id, predicate);
CREATE INDEX IF NOT EXISTS ix_rs_claim_pred_obj  ON rs_claim (predicate, object_norm);
CREATE INDEX IF NOT EXISTS ix_rs_claim_pred_oent ON rs_claim (predicate, object_entity_id) WHERE object_entity_id <> '';
-- "current" fast-path: non-retracted, non-superseded
CREATE INDEX IF NOT EXISTS ix_rs_claim_current ON rs_claim (tenant_id, subject_id, predicate)
    WHERE retracted_at IS NULL AND superseded_at IS NULL;

-- Per-claim provenance, 1..N per claim. Each row is span-gate-ready (carries block_id + quote).
CREATE TABLE IF NOT EXISTS rs_claim_evidence (
    evidence_id    text PRIMARY KEY,           -- sha256(claim_id|document_id|block_id|quote_hash)
    claim_id       text NOT NULL REFERENCES rs_claim(claim_id),
    tenant_id      text NOT NULL DEFAULT 'demo',
    workspace_id   text NOT NULL DEFAULT '',
    document_id    text NOT NULL,
    block_id       text NOT NULL,
    quote          text NOT NULL,
    quote_hash     text NOT NULL,
    source_key     text NOT NULL DEFAULT '',
    authority_tier int NOT NULL DEFAULT 0,
    evidence_kind  text NOT NULL DEFAULT '',
    evidence_status text NOT NULL DEFAULT 'active',  -- active|stale|retracted (GC coupling sets 'stale')
    retrieved_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (claim_id, block_id, quote_hash)
);
CREATE INDEX IF NOT EXISTS ix_rs_claim_ev_doc   ON rs_claim_evidence (document_id);
CREATE INDEX IF NOT EXISTS ix_rs_claim_ev_block ON rs_claim_evidence (block_id);

-- Winner per (subject, predicate, valid-bucket); losers stay queryable in rs_claim.
CREATE TABLE IF NOT EXISTS rs_claim_resolution (
    tenant_id        text NOT NULL DEFAULT 'demo',
    subject_id       text NOT NULL,
    predicate        text NOT NULL,
    valid_bucket     text NOT NULL DEFAULT '',   -- '' for static; else e.g. '2025' for time-bucketed
    winning_claim_id text NOT NULL REFERENCES rs_claim(claim_id),
    conflict_claim_ids jsonb NOT NULL DEFAULT '[]',
    winner_authority_tier int NOT NULL DEFAULT 0,
    rationale        text NOT NULL DEFAULT '',
    resolved_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, subject_id, predicate, valid_bucket)
);

-- Predicate registry: growable-hybrid. Production extraction emits only status='active'.
CREATE TABLE IF NOT EXISTS rs_predicate (
    name            text PRIMARY KEY,
    status          text NOT NULL DEFAULT 'candidate',  -- active|candidate|retired
    object_kind     text NOT NULL DEFAULT 'value',      -- value|entity|either
    cardinality     text NOT NULL DEFAULT 'multi',      -- single|multi
    unit_hint       text NOT NULL DEFAULT '',
    temporal_policy text NOT NULL DEFAULT 'static',     -- point|interval|static
    description     text NOT NULL DEFAULT '',
    added_at        timestamptz NOT NULL DEFAULT now()
);

-- Extraction-run audit + cost ledger.
CREATE TABLE IF NOT EXISTS rs_extraction_run (
    run_id           text PRIMARY KEY,
    tenant_id        text NOT NULL DEFAULT 'demo',
    schema_version   int NOT NULL DEFAULT 1,
    source_keys      text NOT NULL DEFAULT '',
    blocks_considered int NOT NULL DEFAULT 0,
    blocks_relevant   int NOT NULL DEFAULT 0,
    extract_calls     int NOT NULL DEFAULT 0,
    entail_calls      int NOT NULL DEFAULT 0,
    claims_emitted    int NOT NULL DEFAULT 0,
    claims_gated_out  int NOT NULL DEFAULT 0,
    est_cost_usd     numeric NOT NULL DEFAULT 0,
    params           jsonb NOT NULL DEFAULT '{}',
    status           text NOT NULL DEFAULT 'running',   -- running|done|failed|dry_run
    started_at       timestamptz NOT NULL DEFAULT now(),
    finished_at      timestamptz
);
"""

# Whitelisted numeric counters finish_run() may update (guards the dynamic SET).
_RUN_COUNTERS = frozenset({
    "schema_version", "blocks_considered", "blocks_relevant", "extract_calls",
    "entail_calls", "claims_emitted", "claims_gated_out", "est_cost_usd",
})


class ClaimGraphStore:
    """Async Postgres-backed grounded claim graph. Schema + predicate seed ensured
    lazily via `ensure_schema()`; all writes are deterministic-id idempotent."""

    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool = None
        self._ready = False

    async def _get_pool(self):
        if self._pool is None:
            import asyncpg
            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            self._ready = False

    async def ensure_schema(self) -> None:
        """Create the 7 tables (idempotent) THEN seed the vertical predicate registry.
        Predicates seed `ON CONFLICT (name) DO NOTHING` so a later status change (e.g.
        active→retired) is never clobbered by a re-seed."""
        if self._ready:
            return
        pool = await self._get_pool()
        # Vertical-owned vocabulary arrives as DATA. Lazy import so (a) the store has
        # no import-time dependency on the vertical, and (b) under pytest the worktree
        # copy on sys.path wins over any editable install elsewhere.
        from eigen_vertical_tech.claim_predicates import SLICE1_PREDICATES
        async with pool.acquire() as conn:
            await conn.execute(_DDL)
            for p in SLICE1_PREDICATES:
                await conn.execute(
                    """INSERT INTO rs_predicate
                         (name, status, object_kind, cardinality, unit_hint,
                          temporal_policy, description)
                       VALUES ($1,$2,$3,$4,$5,$6,$7)
                       ON CONFLICT (name) DO NOTHING""",
                    p["name"], p.get("status", "candidate"),
                    p.get("object_kind", "value"), p.get("cardinality", "multi"),
                    p.get("unit_hint", ""), p.get("temporal_policy", "static"),
                    p.get("description", ""))
        self._ready = True

    # ---- entities & aliases ------------------------------------------------ #
    async def upsert_entity(self, entity_id: str, kind: str, name: str, *,
                            canonical_name: str = "", primary_domain: str = "",
                            facets: dict | None = None, first_run_id: str = "",
                            tenant_id: str = "demo") -> str:
        """Upsert the resolution-artifact row. Refreshes name/canonical/domain/facets/
        retrieved_at on conflict; NEVER resets `status` (suppression is sticky)."""
        await self.ensure_schema()
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO rs_entity
                     (entity_id, tenant_id, kind, name, canonical_name, primary_domain,
                      first_run_id, facets)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb)
                   ON CONFLICT (entity_id) DO UPDATE SET
                     name = EXCLUDED.name,
                     canonical_name = EXCLUDED.canonical_name,
                     primary_domain = EXCLUDED.primary_domain,
                     facets = EXCLUDED.facets,
                     retrieved_at = now()""",
                entity_id, tenant_id, kind, name, canonical_name, primary_domain,
                first_run_id, json.dumps(facets or {}))
        return entity_id

    async def add_alias(self, alias: str, entity_id: str, source: str = "") -> str:
        """Register a normalized alias → entity mapping (exact-match resolution only)."""
        await self.ensure_schema()
        alias_norm = normalize_name(alias)
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO rs_entity_alias (alias_norm, entity_id, alias, source)
                   VALUES ($1,$2,$3,$4)
                   ON CONFLICT (alias_norm, entity_id) DO UPDATE SET
                     alias = EXCLUDED.alias, source = EXCLUDED.source,
                     retrieved_at = now()""",
                alias_norm, entity_id, alias, source)
        return alias_norm

    async def resolve_alias(self, alias: str) -> str | None:
        """Exact normalized-alias lookup only (NO fuzzy ER in slice 1)."""
        await self.ensure_schema()
        alias_norm = normalize_name(alias)
        if not alias_norm:
            return None
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT entity_id FROM rs_entity_alias WHERE alias_norm = $1 LIMIT 1",
                alias_norm)

    # ---- claims & evidence ------------------------------------------------- #
    async def upsert_claim(self, *, subject_id: str, predicate: str, object_kind: str,
                           object_value: str = "", object_entity_id: str = "",
                           object_norm: str | None = None, unit: str = "",
                           valid_from: "date | None" = None, valid_to: "date | None" = None,
                           valid_granularity: str = "", observed_at: "date | None" = None,
                           confidence: float = 0, schema_version: int = 1,
                           extractor_version: str = "", tenant_id: str = "demo") -> str:
        """Append-only, deterministic-id upsert of one grounded claim. Same logical
        claim → same `claim_id` → idempotent (re-extraction refreshes confidence/
        ingested_at only). NEVER flips supersede/retract here — those are separate
        lifecycle transitions."""
        await self.ensure_schema()
        if object_norm is None:
            object_norm = object_entity_id if object_kind == "entity" else normalize_name(object_value)
        claim_id = make_claim_id(
            tenant_id=tenant_id, subject_id=subject_id, predicate=predicate,
            object_kind=object_kind, object_norm=object_norm,
            object_entity_id=object_entity_id, valid_from=_iso(valid_from),
            schema_version=schema_version)
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO rs_claim
                     (claim_id, tenant_id, subject_id, predicate, object_kind,
                      object_value, object_norm, object_entity_id, unit, valid_from,
                      valid_to, valid_granularity, observed_at, confidence,
                      schema_version, extractor_version)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                   ON CONFLICT (claim_id) DO UPDATE SET
                     confidence = EXCLUDED.confidence,
                     ingested_at = now()""",
                claim_id, tenant_id, subject_id, predicate, object_kind,
                object_value, object_norm, object_entity_id, unit, valid_from,
                valid_to, valid_granularity, observed_at, confidence,
                schema_version, extractor_version)
        return claim_id

    async def add_evidence(self, claim_id: str, document_id: str, block_id: str,
                           quote: str, *, source_key: str = "", authority_tier: int = 0,
                           evidence_kind: str = "", workspace_id: str = "",
                           tenant_id: str = "demo") -> str:
        """Attach a span-gate-ready provenance row to a claim. Deduped on
        (claim_id, block_id, quote_hash) — re-citing the same span is a no-op."""
        await self.ensure_schema()
        qh = quote_hash(quote)
        evidence_id = make_evidence_id(
            claim_id=claim_id, document_id=document_id, block_id=block_id,
            quote_hash_hex=qh)
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO rs_claim_evidence
                     (evidence_id, claim_id, tenant_id, workspace_id, document_id,
                      block_id, quote, quote_hash, source_key, authority_tier,
                      evidence_kind)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                   ON CONFLICT (claim_id, block_id, quote_hash) DO NOTHING""",
                evidence_id, claim_id, tenant_id, workspace_id, document_id,
                block_id, quote, qh, source_key, authority_tier, evidence_kind)
        return evidence_id

    async def mark_evidence_stale(self, document_ids: Sequence[str]) -> int:
        """GC-coupling hook: when `rs_block` hard-deletes docs, flip their still-active
        evidence to 'stale' (never delete) so answers exclude claims whose span can no
        longer load until re-extracted. Returns the number of rows flipped."""
        if not document_ids:
            return 0
        await self.ensure_schema()
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            res = await conn.execute(
                "UPDATE rs_claim_evidence SET evidence_status = 'stale' "
                "WHERE document_id = ANY($1) AND evidence_status = 'active'",
                list(document_ids))
        try:
            return int((res or "UPDATE 0").split()[-1])
        except ValueError:
            return 0

    # ---- extraction-run ledger -------------------------------------------- #
    async def record_run(self, run_id: str, *, source_keys: str = "",
                         schema_version: int = 1, params: dict | None = None,
                         status: str = "running", tenant_id: str = "demo") -> str:
        """Open (or refresh) an extraction-run audit/cost row."""
        await self.ensure_schema()
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO rs_extraction_run
                     (run_id, tenant_id, schema_version, source_keys, params, status)
                   VALUES ($1,$2,$3,$4,$5::jsonb,$6)
                   ON CONFLICT (run_id) DO UPDATE SET
                     source_keys = EXCLUDED.source_keys,
                     params = EXCLUDED.params,
                     status = EXCLUDED.status""",
                run_id, tenant_id, schema_version, source_keys,
                json.dumps(params or {}), status)
        return run_id

    async def finish_run(self, run_id: str, *, status: str = "done", **counts: Any) -> None:
        """Close a run: set status + finished_at and update any whitelisted counters
        passed as kwargs (blocks_considered, extract_calls, claims_emitted, est_cost_usd, …)."""
        await self.ensure_schema()
        sets = ["status = $2", "finished_at = now()"]
        args: list[Any] = [run_id, status]
        for k, v in counts.items():
            if k not in _RUN_COUNTERS:
                raise ValueError(f"unknown run counter {k!r}")
            args.append(v)
            sets.append(f"{k} = ${len(args)}")
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"UPDATE rs_extraction_run SET {', '.join(sets)} WHERE run_id = $1", *args)

    # ---- grounded reads (used by later tasks) ------------------------------ #
    async def population(self, predicate: str, object_norm: str, *,
                         tenant_id: str = "demo") -> list[dict]:
        """Subjects (entity rows) with an ACTIVE claim `predicate=… AND object_norm=…`,
        each joined to that claim + one active evidence row. Ordered by name. This is
        the 'who is in category C' population read the landscape map is built from."""
        await self.ensure_schema()
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT e.entity_id, e.name, e.kind, e.primary_domain,
                          c.claim_id, c.predicate, c.object_kind, c.object_value,
                          c.object_norm, c.object_entity_id, c.confidence,
                          ev.document_id, ev.block_id, ev.quote, ev.authority_tier
                   FROM rs_claim c
                   JOIN rs_entity e ON e.entity_id = c.subject_id AND e.status = 'active'
                   LEFT JOIN LATERAL (
                       SELECT document_id, block_id, quote, authority_tier
                       FROM rs_claim_evidence ev
                       WHERE ev.claim_id = c.claim_id AND ev.evidence_status = 'active'
                       ORDER BY ev.authority_tier DESC, ev.retrieved_at
                       LIMIT 1
                   ) ev ON true
                   WHERE c.tenant_id = $1 AND c.predicate = $2 AND c.object_norm = $3
                     AND c.retracted_at IS NULL AND c.superseded_at IS NULL
                     AND ev.document_id IS NOT NULL   -- grounding+GC: exclude claims with no ACTIVE evidence
                   ORDER BY e.name""",
                tenant_id, predicate, object_norm)
        return [self._row_to_claim_dict(r) for r in rows]

    async def entity_claims(self, subject_id: str, *, predicates: Sequence[str] | None = None,
                            tenant_id: str = "demo") -> list[dict]:
        """Active claims for one entity (optionally filtered to `predicates`), each with
        its winning (highest-authority active) evidence — the per-cell grounded read
        compose cites. Ordered by predicate."""
        await self.ensure_schema()
        args: list[Any] = [tenant_id, subject_id]
        pred_clause = ""
        if predicates:
            args.append(list(predicates))
            pred_clause = f"AND c.predicate = ANY(${len(args)})"
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT c.subject_id AS entity_id, '' AS name, '' AS kind,
                           '' AS primary_domain,
                           c.claim_id, c.predicate, c.object_kind, c.object_value,
                           c.object_norm, c.object_entity_id, c.confidence,
                           c.unit, c.valid_from, c.valid_to,
                           ev.document_id, ev.block_id, ev.quote, ev.authority_tier
                    FROM rs_claim c
                    LEFT JOIN LATERAL (
                        SELECT document_id, block_id, quote, authority_tier
                        FROM rs_claim_evidence ev
                        WHERE ev.claim_id = c.claim_id AND ev.evidence_status = 'active'
                        ORDER BY ev.authority_tier DESC, ev.retrieved_at
                        LIMIT 1
                    ) ev ON true
                    WHERE c.tenant_id = $1 AND c.subject_id = $2
                      AND c.retracted_at IS NULL AND c.superseded_at IS NULL
                      AND ev.document_id IS NOT NULL   -- grounding+GC: only claims with ACTIVE evidence
                      {pred_clause}
                    ORDER BY c.predicate""",
                *args)
        out = []
        for r in rows:
            d = self._row_to_claim_dict(r)
            d["unit"] = r["unit"]
            d["valid_from"] = _iso(r["valid_from"]) or None
            d["valid_to"] = _iso(r["valid_to"]) or None
            out.append(d)
        return out

    # ---- aggregation reads (population → market map, Task 3) ---------------- #
    async def distinct_categories(self, *, tenant_id: str = "demo",
                                  min_members: int = 1) -> list[dict]:
        """DISTINCT market categories from ACTIVE, grounded `operates_in_category`
        claims, each with a distinct-member (company) count. Returns
        `[{object_norm, name, members}]` ordered by members DESC (name tie-break).

        Grounding-exclusion (same discipline as `population`): a claim is counted
        only when it has an ACTIVE evidence row — a company placed by a claim whose
        span was GC'd/stale never inflates a category. `name` is the category
        entity's `name` (join `rs_entity` on `object_entity_id`) or `object_norm`
        when no entity row exists. `members >= min_members` filters small clusters."""
        await self.ensure_schema()
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT c.object_norm AS object_norm,
                          COALESCE(NULLIF(max(cat.name), ''), c.object_norm) AS name,
                          count(DISTINCT c.subject_id) AS members
                   FROM rs_claim c
                   JOIN rs_entity e ON e.entity_id = c.subject_id AND e.status = 'active'
                   LEFT JOIN rs_entity cat ON cat.entity_id = c.object_entity_id
                   WHERE c.tenant_id = $1 AND c.predicate = 'operates_in_category'
                     AND c.retracted_at IS NULL AND c.superseded_at IS NULL
                     AND EXISTS (            -- grounding+GC: only claims with ACTIVE evidence
                         SELECT 1 FROM rs_claim_evidence ev
                         WHERE ev.claim_id = c.claim_id
                           AND ev.evidence_status = 'active')
                   GROUP BY c.object_norm
                   HAVING count(DISTINCT c.subject_id) >= $2
                   ORDER BY members DESC, name, object_norm""",
                tenant_id, min_members)
        return [{"object_norm": r["object_norm"], "name": r["name"],
                 "members": int(r["members"])} for r in rows]

    async def population_claims(self, *, tenant_id: str = "demo",
                               category_norms: Sequence[str] | None = None,
                               company_cap: int = 400,
                               claims_per_company_cap: int = 40) -> dict:
        """Grounded population read the market map is built from: COMPANY rows, each
        with its ACTIVE grounded claims across ALL slice predicates, every claim
        carrying its winning (highest-authority active) evidence.

        Scope: companies with ≥1 active grounded `operates_in_category` claim whose
        `object_norm` ∈ `category_norms` (when given); otherwise the whole grounded
        company population (any active grounded claim). Companies are capped at
        `company_cap` (ordered by name) and each company's claims at
        `claims_per_company_cap`. NO silent truncation — the returned `meta` carries
        `companies_truncated` / `claims_truncated` (+ the clipped company ids) so a
        clip is always surfaced.

        Grounding-exclusion: an INNER lateral join on ACTIVE evidence means a claim
        with no active evidence row is never returned (same rule as `population`).

        Returns `{"companies": [...], "meta": {...}}` where each company is
        `{entity_id, name, kind, primary_domain, claims:[{predicate, object_kind,
        object_value, object_entity_id, object_norm, confidence,
        evidence:{document_id, block_id, quote, authority_tier}}]}`."""
        await self.ensure_schema()
        # ALL slice predicates arrive as DATA from the vertical (kernel/vertical split).
        from eigen_vertical_tech.claim_predicates import SLICE1_PREDICATES
        slice_preds = [p["name"] for p in SLICE1_PREDICATES]

        norms = list(category_norms) if category_norms else None
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # 1) The company set — active companies grounded into scope. Fetch cap+1
            #    so a clip is DETECTABLE (no separate count query, no silent drop).
            if norms is not None:
                scope_exists = (
                    "AND c.predicate = 'operates_in_category' "
                    "AND c.object_norm = ANY($2::text[]) ")
                comp_rows = await conn.fetch(
                    f"""SELECT e.entity_id, e.name, e.kind, e.primary_domain
                        FROM rs_entity e
                        WHERE e.tenant_id = $1 AND e.status = 'active' AND e.kind = 'company'
                          AND EXISTS (
                              SELECT 1 FROM rs_claim c
                              WHERE c.tenant_id = $1 AND c.subject_id = e.entity_id
                                {scope_exists}
                                AND c.retracted_at IS NULL AND c.superseded_at IS NULL
                                AND EXISTS (SELECT 1 FROM rs_claim_evidence ev
                                            WHERE ev.claim_id = c.claim_id
                                              AND ev.evidence_status = 'active'))
                        ORDER BY e.name, e.entity_id
                        LIMIT $3""",
                    tenant_id, norms, company_cap + 1)
            else:
                comp_rows = await conn.fetch(
                    """SELECT e.entity_id, e.name, e.kind, e.primary_domain
                       FROM rs_entity e
                       WHERE e.tenant_id = $1 AND e.status = 'active' AND e.kind = 'company'
                         AND EXISTS (
                             SELECT 1 FROM rs_claim c
                             WHERE c.tenant_id = $1 AND c.subject_id = e.entity_id
                               AND c.retracted_at IS NULL AND c.superseded_at IS NULL
                               AND EXISTS (SELECT 1 FROM rs_claim_evidence ev
                                           WHERE ev.claim_id = c.claim_id
                                             AND ev.evidence_status = 'active'))
                       ORDER BY e.name, e.entity_id
                       LIMIT $2""",
                    tenant_id, company_cap + 1)

            companies_truncated = len(comp_rows) > company_cap
            comp_rows = comp_rows[:company_cap]
            company_ids = [r["entity_id"] for r in comp_rows]

            companies: list[dict] = [{
                "entity_id": r["entity_id"], "name": r["name"], "kind": r["kind"],
                "primary_domain": r["primary_domain"], "claims": [],
            } for r in comp_rows]
            by_id = {c["entity_id"]: c for c in companies}

            claim_rows: list = []
            if company_ids:
                # 2) One query for ALL their claims + winning evidence. INNER lateral
                #    join => grounding-exclusion; window ranks + caps per company and
                #    exposes the pre-cap total so a per-company clip is reportable.
                claim_rows = await conn.fetch(
                    """SELECT t.entity_id, t.predicate, t.object_kind, t.object_value,
                              t.object_norm, t.object_entity_id, t.confidence,
                              t.document_id, t.block_id, t.quote, t.authority_tier,
                              t.total_claims
                       FROM (
                           SELECT c.subject_id AS entity_id, c.predicate,
                                  c.object_kind, c.object_value, c.object_norm,
                                  c.object_entity_id, c.confidence,
                                  ev.document_id, ev.block_id, ev.quote, ev.authority_tier,
                                  row_number() OVER (
                                      PARTITION BY c.subject_id
                                      ORDER BY c.predicate, c.object_norm, c.claim_id) AS rn,
                                  count(*) OVER (PARTITION BY c.subject_id) AS total_claims
                           FROM rs_claim c
                           JOIN LATERAL (
                               SELECT document_id, block_id, quote, authority_tier
                               FROM rs_claim_evidence ev
                               WHERE ev.claim_id = c.claim_id
                                 AND ev.evidence_status = 'active'
                               ORDER BY ev.authority_tier DESC, ev.retrieved_at
                               LIMIT 1
                           ) ev ON true
                           WHERE c.tenant_id = $1 AND c.subject_id = ANY($2::text[])
                             AND c.predicate = ANY($3::text[])
                             AND c.retracted_at IS NULL AND c.superseded_at IS NULL
                       ) t
                       WHERE t.rn <= $4
                       ORDER BY t.entity_id, t.predicate, t.object_norm""",
                    tenant_id, company_ids, slice_preds, claims_per_company_cap)

        clipped_company_ids: list[str] = []
        for r in claim_rows:
            comp = by_id.get(r["entity_id"])
            if comp is None:
                continue
            comp["claims"].append({
                "predicate": r["predicate"],
                "object_kind": r["object_kind"],
                "object_value": r["object_value"],
                "object_entity_id": r["object_entity_id"],
                "object_norm": r["object_norm"],
                "confidence": float(r["confidence"]) if r["confidence"] is not None else 0.0,
                "evidence": {
                    "document_id": r["document_id"],
                    "block_id": r["block_id"],
                    "quote": r["quote"],
                    "authority_tier": r["authority_tier"],
                },
            })
            if r["total_claims"] > claims_per_company_cap:
                if r["entity_id"] not in clipped_company_ids:
                    clipped_company_ids.append(r["entity_id"])

        meta = {
            "company_count": len(companies),
            "companies_truncated": companies_truncated,
            "company_cap": company_cap,
            "claims_truncated": bool(clipped_company_ids),
            "claims_per_company_cap": claims_per_company_cap,
            "clipped_company_ids": clipped_company_ids,
        }
        return {"companies": companies, "meta": meta}

    @staticmethod
    def _row_to_claim_dict(r) -> dict:
        return {
            "entity_id": r["entity_id"],
            "name": r["name"],
            "kind": r["kind"],
            "primary_domain": r["primary_domain"],
            "claim_id": r["claim_id"],
            "predicate": r["predicate"],
            "object_kind": r["object_kind"],
            "object_value": r["object_value"],
            "object_norm": r["object_norm"],
            "object_entity_id": r["object_entity_id"],
            "confidence": float(r["confidence"]) if r["confidence"] is not None else 0.0,
            "evidence": None if r["document_id"] is None else {
                "document_id": r["document_id"],
                "block_id": r["block_id"],
                "quote": r["quote"],
                "authority_tier": r["authority_tier"],
            },
        }
