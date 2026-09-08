"""Dossier storage — versioned, shareable, and never silently recomputed.

Mirrors `su_map` / `su_map_revision` (a versioned saved SEARCH) for a versioned saved DOSSIER, so a
DeepDive gets the same permanent public link Startup and Voices searches already have. A repeat dive
on the same company returns the stored dossier with its date; a refresh writes a new revision instead
of overwriting, because "what did we know on the day we decided" is the question diligence asks.
"""
from __future__ import annotations

import json
import secrets
import uuid

DDL = """
CREATE TABLE IF NOT EXISTS su_dossier (
    id           text PRIMARY KEY,
    company_id   text NOT NULL,
    owner_id     text NOT NULL DEFAULT '',
    title        text NOT NULL DEFAULT '',
    sections     jsonb NOT NULL DEFAULT '[]',
    attempted    jsonb NOT NULL DEFAULT '[]',
    company      jsonb NOT NULL DEFAULT '{}',
    basis        text NOT NULL DEFAULT 'held',   -- held | held+web (what was allowed to be spent)
    spend        jsonb NOT NULL DEFAULT '{}',
    share_token  text NOT NULL,
    revision     int NOT NULL DEFAULT 0,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_su_dossier_company ON su_dossier (company_id);
CREATE INDEX IF NOT EXISTS ix_su_dossier_owner ON su_dossier (owner_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS su_dossier_revision (
    dossier_id   text NOT NULL REFERENCES su_dossier(id) ON DELETE CASCADE,
    revision     int NOT NULL,
    reason       text NOT NULL DEFAULT '',
    sections     jsonb NOT NULL DEFAULT '[]',
    attempted    jsonb NOT NULL DEFAULT '[]',
    basis        text NOT NULL DEFAULT 'held',
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dossier_id, revision)
);
"""


async def ensure_schema(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(DDL)


def _j(v):
    return json.loads(v) if isinstance(v, str) else v


async def save(pool, doss: dict, *, owner_id: str = "", reason: str = "initial") -> dict:
    """Insert, or add a revision to, the dossier for this company. Returns id + share token."""
    await ensure_schema(pool)
    cid = doss["company"]["id"]
    sections, attempted = json.dumps(doss.get("sections") or []), json.dumps(doss.get("attempted") or [])
    company, spend = json.dumps(doss.get("company") or {}), json.dumps(doss.get("spend") or {})
    basis = doss.get("basis") or "held"
    title = (doss["company"].get("name") or cid)[:160]
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow("SELECT id, revision, share_token FROM su_dossier WHERE company_id = $1", cid)
        if row:
            did, rev, tok = row["id"], int(row["revision"]) + 1, row["share_token"]
            await conn.execute("""UPDATE su_dossier SET sections=$2::jsonb, attempted=$3::jsonb, company=$4::jsonb,
                                  basis=$5, spend=$6::jsonb, revision=$7, updated_at=now() WHERE id=$1""",
                               did, sections, attempted, company, basis, spend, rev)
        else:
            did, rev, tok = uuid.uuid4().hex[:16], 0, secrets.token_urlsafe(18)
            await conn.execute("""INSERT INTO su_dossier (id, company_id, owner_id, title, sections, attempted,
                                  company, basis, spend, share_token, revision)
                                  VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8,$9::jsonb,$10,0)""",
                               did, cid, owner_id, title, sections, attempted, company, basis, spend, tok)
        await conn.execute("""INSERT INTO su_dossier_revision (dossier_id, revision, reason, sections, attempted, basis)
                              VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6)""",
                           did, rev, reason, sections, attempted, basis)
    return {"id": did, "share_token": tok, "revision": rev, "company_id": cid}


async def get(pool, *, company_id: str = "", dossier_id: str = "", share_token: str = "") -> dict | None:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        if company_id:
            r = await conn.fetchrow("SELECT * FROM su_dossier WHERE company_id = $1", company_id)
        elif share_token:
            r = await conn.fetchrow("SELECT * FROM su_dossier WHERE share_token = $1", share_token)
        else:
            r = await conn.fetchrow("SELECT * FROM su_dossier WHERE id = $1", dossier_id)
        if not r:
            return None
        revs = await conn.fetch("SELECT revision, reason, created_at FROM su_dossier_revision WHERE dossier_id = $1 ORDER BY revision", r["id"])
    out = {k: r[k] for k in r.keys()}
    for k in ("sections", "attempted", "company", "spend"):
        out[k] = _j(out[k])
    for k in ("created_at", "updated_at"):
        out[k] = out[k].isoformat()
    out["revisions"] = [{"revision": x["revision"], "reason": x["reason"], "created_at": x["created_at"].isoformat()} for x in revs]
    return out


async def recent(pool, *, limit: int = 50) -> list[dict]:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        rows = await conn.fetch("""SELECT id, company_id, title, basis, revision, updated_at,
                                   jsonb_array_length(sections) AS n FROM su_dossier
                                   ORDER BY updated_at DESC LIMIT $1""", limit)
    return [{"id": r["id"], "company_id": r["company_id"], "title": r["title"], "basis": r["basis"],
             "revision": r["revision"], "sections": int(r["n"] or 0),
             "updated_at": r["updated_at"].isoformat()} for r in rows]
