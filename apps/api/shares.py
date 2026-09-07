"""Permanent, public links to a search — a FROZEN snapshot, not a re-run.

A shared link has to show the recipient what the sender saw. Re-running the query would not do that:
feeds roll, blocks are re-ingested under new ids, and a corpus that grows daily would quietly change
the page under a link that was supposed to be a record. So a share stores the RESULTS, and opening
one renders them exactly as they were, with the date they were taken.

Two deliberate choices:

**Explicit, not automatic.** A link is minted when someone asks for one. Auto-minting a public URL
for every search would publish a diligence trail nobody chose to publish — the queries themselves
say what someone is looking at, and that is often the sensitive part.

**Public but unguessable.** No account is needed to open one, because "send this to a colleague"
is the whole point. The token is 22 characters of urandom, so a link is only reachable by someone
who was given it.
"""
from __future__ import annotations

import json
import secrets

MAX_PAYLOAD_BYTES = 400_000        # a page of results, not an archive
MODES = ("voices", "startups")

DDL = """
CREATE TABLE IF NOT EXISTS eigen_share (
    token      text PRIMARY KEY,
    mode       text NOT NULL,
    title      text NOT NULL DEFAULT '',
    query      jsonb NOT NULL DEFAULT '{}'::jsonb,
    payload    jsonb NOT NULL DEFAULT '{}'::jsonb,
    owner_id   text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    opens      bigint NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS eigen_share_owner ON eigen_share (owner_id, created_at DESC);
"""


def new_token() -> str:
    return secrets.token_urlsafe(16)[:22]


async def ensure(conn) -> None:
    await conn.execute(DDL)


async def create(conn, *, mode: str, title: str, query: dict, payload: dict,
                 owner_id: str = "") -> dict:
    """Freeze one page of results and return its token. Raises ValueError on a bad mode or an
    oversized payload — a share that silently truncated its own results would be a lie."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode}")
    body = json.dumps(payload or {})
    if len(body.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError("too much to share at once — narrow the results first")
    await ensure(conn)
    token = new_token()
    await conn.execute(
        "INSERT INTO eigen_share (token, mode, title, query, payload, owner_id) "
        "VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6)",
        token, mode, (title or "")[:200], json.dumps(query or {}), body, owner_id or "")
    return {"token": token, "mode": mode, "title": (title or "")[:200]}


async def get(conn, token: str) -> dict | None:
    """The frozen page, or None. Counts the open — a sender may reasonably want to know a link was
    used, and it costs one statement."""
    await ensure(conn)
    r = await conn.fetchrow(
        "UPDATE eigen_share SET opens = opens + 1 WHERE token = $1 "
        "RETURNING token, mode, title, query, payload, created_at, opens", token)
    if not r:
        return None

    def js(v):
        return json.loads(v) if isinstance(v, str) else (v or {})
    return {"token": r["token"], "mode": r["mode"], "title": r["title"],
            "query": js(r["query"]), "payload": js(r["payload"]),
            "created_at": r["created_at"].isoformat() if r["created_at"] else "",
            "opens": int(r["opens"] or 0)}


async def listing(conn, owner_id: str, *, limit: int = 50) -> list[dict]:
    """The links one account has minted, newest first. Anonymous shares belong to nobody and are
    deliberately not listable — the token is the only way back to them."""
    await ensure(conn)
    if not owner_id:
        return []
    rows = await conn.fetch(
        "SELECT token, mode, title, created_at, opens FROM eigen_share "
        "WHERE owner_id = $1 ORDER BY created_at DESC LIMIT $2", owner_id, int(max(1, min(limit, 200))))
    return [{"token": r["token"], "mode": r["mode"], "title": r["title"], "opens": int(r["opens"] or 0),
             "created_at": r["created_at"].isoformat() if r["created_at"] else ""} for r in rows]
