"""Thesis storage — a ledger, not a report.

Three calls with an industry expert produce three sets of notes that live in three places and are
forgotten by the time the fourth happens. Here every piece of evidence attaches to the CLAIM it bears
on, whether it came from the corpus or from a call, and is typed the same way — so "proving or
disproving it" is a state that can be read rather than a feeling that accumulates.

Follows `su_map`'s shape rather than `iv_map`'s: of the three saved-artifact implementations in this
repo it is the only one that writes revisions, does not leak its share token to non-owners, and keys
ownership on a resolved user id instead of a raw bearer token.
"""
from __future__ import annotations

import json
import secrets
import uuid

from .schema import OPEN

_DDL = """
CREATE TABLE IF NOT EXISTS ts_thesis (
    id          text PRIMARY KEY,
    owner_id    text NOT NULL DEFAULT '',
    title       text NOT NULL DEFAULT '',
    thesis      text NOT NULL,              -- the sentence, as the user wrote it
    subject     jsonb NOT NULL DEFAULT '{}',-- what the decomposer read out of it: product, segment…
    share_token text NOT NULL,
    revision    int NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ts_thesis_owner ON ts_thesis (owner_id, updated_at DESC);
-- Which claim the conversation is currently on. A stress test that jumps rung to rung every turn is
-- a monologue on a timer; the agent stays on one thing until it is settled or set aside.
ALTER TABLE ts_thesis ADD COLUMN IF NOT EXISTS focus_rung text NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS ts_claim (
    thesis_id   text NOT NULL REFERENCES ts_thesis(id) ON DELETE CASCADE,
    rung        text NOT NULL,              -- schema.RUNGS — the ladder is fixed, the text is not
    claim       text NOT NULL,              -- the rung instantiated for THIS thesis
    settleable  text NOT NULL,              -- corpus | partly | call_only — from schema, not a model
    verdict     text NOT NULL DEFAULT 'open',
    note        text NOT NULL DEFAULT '',   -- why this verdict, in one line
    attacked_at timestamptz,                -- when the refuter last went after it
    PRIMARY KEY (thesis_id, rung)
);

CREATE TABLE IF NOT EXISTS ts_evidence (
    id          text PRIMARY KEY,
    thesis_id   text NOT NULL REFERENCES ts_thesis(id) ON DELETE CASCADE,
    rung        text NOT NULL,
    side        text NOT NULL,              -- for | against  (against is not a footnote here)
    register    text NOT NULL,              -- filed | stated | observed
    source_key  text NOT NULL DEFAULT '',
    signal_only boolean NOT NULL DEFAULT false,   -- sentiment, quarantined from every conclusion
    title       text NOT NULL DEFAULT '',
    quote       text NOT NULL DEFAULT '',
    source_url  text NOT NULL DEFAULT '',
    as_of       text NOT NULL DEFAULT '',
    -- a call: who said it, in what role, when. `basis` is what keeps a person's account from ever
    -- being read as a filing.
    basis       text NOT NULL DEFAULT '',
    said_by     text NOT NULL DEFAULT '',
    said_role   text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ts_evidence_claim ON ts_evidence (thesis_id, rung, side);

CREATE TABLE IF NOT EXISTS ts_turn (
    id          bigserial PRIMARY KEY,
    thesis_id   text NOT NULL REFERENCES ts_thesis(id) ON DELETE CASCADE,
    role        text NOT NULL,              -- agent | user
    move        text NOT NULL DEFAULT '',   -- settled | attacked | needs_person | asked
    rung        text NOT NULL DEFAULT '',
    text        text NOT NULL DEFAULT '',
    payload     jsonb NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ts_turn_thesis ON ts_turn (thesis_id, id);
"""


async def ensure_schema(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_DDL)


def _j(v):
    return json.loads(v) if isinstance(v, str) else v


async def create(pool, *, thesis: str, claims: list[dict], subject: dict,
                 owner_id: str = "", title: str = "") -> dict:
    await ensure_schema(pool)
    tid = uuid.uuid4().hex[:16]
    tok = secrets.token_urlsafe(18)
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO ts_thesis (id, owner_id, title, thesis, subject, share_token)
               VALUES ($1,$2,$3,$4,$5::jsonb,$6)""",
            tid, owner_id, (title or thesis)[:160], thesis, json.dumps(subject or {}), tok)
        for c in claims:
            await conn.execute(
                """INSERT INTO ts_claim (thesis_id, rung, claim, settleable, verdict)
                   VALUES ($1,$2,$3,$4,$5) ON CONFLICT (thesis_id, rung) DO NOTHING""",
                tid, c["rung"], c["claim"], c["settleable"], c.get("verdict") or OPEN)
    return {"id": tid, "share_token": tok}


async def get(pool, *, thesis_id: str = "", share_token: str = "", owner_id: str = "") -> dict | None:
    """The whole ledger. The share token is popped for anyone who is not the owner — the bug
    `iv_map.get_map` still has."""
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        if thesis_id:
            t = await conn.fetchrow("SELECT * FROM ts_thesis WHERE id = $1", thesis_id)
        else:
            t = await conn.fetchrow("SELECT * FROM ts_thesis WHERE share_token = $1", share_token)
        if not t:
            return None
        claims = await conn.fetch(
            "SELECT * FROM ts_claim WHERE thesis_id = $1", t["id"])
        ev = await conn.fetch(
            """SELECT * FROM ts_evidence WHERE thesis_id = $1
               ORDER BY side, register, created_at""", t["id"])
        turns = await conn.fetch(
            "SELECT * FROM ts_turn WHERE thesis_id = $1 ORDER BY id", t["id"])
    out = {k: t[k] for k in t.keys()}
    out["subject"] = _j(out["subject"])
    for k in ("created_at", "updated_at"):
        out[k] = out[k].isoformat()
    is_owner = bool(owner_id) and out["owner_id"] == owner_id
    out["is_owner"] = is_owner
    if not is_owner:
        out.pop("share_token", None)
    by_rung: dict[str, list] = {}
    for e in ev:
        row = {k: e[k] for k in e.keys() if k not in ("created_at",)}
        by_rung.setdefault(e["rung"], []).append(row)
    out["claims"] = [{**{k: c[k] for k in c.keys() if k != "attacked_at"},
                      "attacked": bool(c["attacked_at"]),
                      "evidence": by_rung.get(c["rung"], [])} for c in claims]
    out["turns"] = [{"role": r["role"], "move": r["move"], "rung": r["rung"],
                     "text": r["text"], "payload": _j(r["payload"])} for r in turns]
    return out


async def add_evidence(pool, thesis_id: str, rung: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    await ensure_schema(pool)
    async with pool.acquire() as conn, conn.transaction():
        for r in rows:
            await conn.execute(
                """INSERT INTO ts_evidence (id, thesis_id, rung, side, register, source_key,
                       signal_only, title, quote, source_url, as_of, basis, said_by, said_role)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)""",
                uuid.uuid4().hex[:16], thesis_id, rung, r["side"], r["register"],
                r.get("source_key") or "", bool(r.get("signal_only")), (r.get("title") or "")[:300],
                (r.get("quote") or "")[:1200], r.get("source_url") or "", r.get("as_of") or "",
                r.get("basis") or "", r.get("said_by") or "", r.get("said_role") or "")
    return len(rows)


async def set_verdict(pool, thesis_id: str, rung: str, verdict: str, note: str = "",
                      *, attacked: bool = False) -> None:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            f"""UPDATE ts_claim SET verdict = $3, note = $4
                   {", attacked_at = now()" if attacked else ""}
                 WHERE thesis_id = $1 AND rung = $2""",     # noqa: S608 — literal, not user input
            thesis_id, rung, verdict, note[:400])
        await conn.execute("UPDATE ts_thesis SET updated_at = now() WHERE id = $1", thesis_id)


async def set_focus(pool, thesis_id: str, rung: str) -> None:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE ts_thesis SET focus_rung = $2 WHERE id = $1", thesis_id, rung)


async def revise_claim(pool, thesis_id: str, rung: str, claim: str) -> None:
    """The author reworded the claim. Their wording wins — it is their thesis."""
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE ts_claim SET claim = $3 WHERE thesis_id = $1 AND rung = $2",
                           thesis_id, rung, claim[:600])


async def add_turn(pool, thesis_id: str, *, role: str, move: str = "", rung: str = "",
                   text: str = "", payload: dict | None = None) -> None:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO ts_turn (thesis_id, role, move, rung, text, payload)
               VALUES ($1,$2,$3,$4,$5,$6::jsonb)""",
            thesis_id, role, move, rung, text[:4000], json.dumps(payload or {}))


async def recent(pool, *, owner_id: str = "", limit: int = 40) -> list[dict]:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT t.id, t.title, t.thesis, t.updated_at,
                      count(*) FILTER (WHERE c.verdict <> 'open') AS settled,
                      count(*) AS claims
                 FROM ts_thesis t LEFT JOIN ts_claim c ON c.thesis_id = t.id
                WHERE ($1 = '' OR t.owner_id = $1)
                GROUP BY t.id ORDER BY t.updated_at DESC LIMIT $2""", owner_id, limit)
    return [{"id": r["id"], "title": r["title"], "thesis": r["thesis"],
             "settled": int(r["settled"] or 0), "claims": int(r["claims"] or 0),
             "updated_at": r["updated_at"].isoformat()} for r in rows]
