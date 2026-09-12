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
import hashlib
import hmac
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
-- The integrated reading of every claim at once. A table of ten takes is ten judgements the reader
-- still has to add up; this is the addition, and it is the part they act on.
ALTER TABLE ts_thesis ADD COLUMN IF NOT EXISTS overall text NOT NULL DEFAULT '';
ALTER TABLE ts_thesis ADD COLUMN IF NOT EXISTS owner_token_hash text NOT NULL DEFAULT '';
ALTER TABLE ts_thesis ADD COLUMN IF NOT EXISTS decision jsonb NOT NULL DEFAULT '{}';
ALTER TABLE ts_thesis ADD COLUMN IF NOT EXISTS research_status text NOT NULL DEFAULT 'not_run';
-- The genesis agent's current best one-sentence formalization, before the user confirms it. A thesis
-- with zero claims is a DRAFT (still in genesis); this holds what "Use this thesis" would commit.
ALTER TABLE ts_thesis ADD COLUMN IF NOT EXISTS proposed_thesis text NOT NULL DEFAULT '';

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
-- The written case on each side. Evidence rows are not an argument: a reader handed six quotes has
-- to do the reasoning themselves, and the reasoning is the work.
ALTER TABLE ts_claim ADD COLUMN IF NOT EXISTS case_for text NOT NULL DEFAULT '';
ALTER TABLE ts_claim ADD COLUMN IF NOT EXISTS case_against text NOT NULL DEFAULT '';
ALTER TABLE ts_claim ADD COLUMN IF NOT EXISTS leans text NOT NULL DEFAULT '';
ALTER TABLE ts_claim ADD COLUMN IF NOT EXISTS critical boolean NOT NULL DEFAULT false;
ALTER TABLE ts_claim ADD COLUMN IF NOT EXISTS falsifier text NOT NULL DEFAULT '';
ALTER TABLE ts_claim ADD COLUMN IF NOT EXISTS what_would_change text NOT NULL DEFAULT '';
ALTER TABLE ts_claim ADD COLUMN IF NOT EXISTS research_status text NOT NULL DEFAULT 'open';
-- Which run last settled this claim. The async runner's resume signal is CLAIM-LEVEL: on resume it
-- skips a claim already tested by the current run, and re-drives only the unfinished ones. (The
-- evidence unique index is only a double-insert backstop; it is keyed on the full span tuple, not on
-- the run, so it cannot answer "is this claim done for this run?".)
ALTER TABLE ts_claim ADD COLUMN IF NOT EXISTS tested_run_id text NOT NULL DEFAULT '';

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
ALTER TABLE ts_evidence ADD COLUMN IF NOT EXISTS document_id text NOT NULL DEFAULT '';
ALTER TABLE ts_evidence ADD COLUMN IF NOT EXISTS block_id text NOT NULL DEFAULT '';
ALTER TABLE ts_evidence ADD COLUMN IF NOT EXISTS atom_id text NOT NULL DEFAULT '';
ALTER TABLE ts_evidence ADD COLUMN IF NOT EXISTS relation text NOT NULL DEFAULT 'context';
ALTER TABLE ts_evidence ADD COLUMN IF NOT EXISTS evidence_kind text NOT NULL DEFAULT '';
ALTER TABLE ts_evidence ADD COLUMN IF NOT EXISTS source_subject text NOT NULL DEFAULT '';
ALTER TABLE ts_evidence ADD COLUMN IF NOT EXISTS period text NOT NULL DEFAULT '';
ALTER TABLE ts_evidence ADD COLUMN IF NOT EXISTS span_hash text NOT NULL DEFAULT '';
ALTER TABLE ts_evidence ADD COLUMN IF NOT EXISTS gate_results jsonb NOT NULL DEFAULT '{}';
ALTER TABLE ts_evidence ADD COLUMN IF NOT EXISTS facets jsonb NOT NULL DEFAULT '{}';
ALTER TABLE ts_evidence ADD COLUMN IF NOT EXISTS run_id text NOT NULL DEFAULT '';
ALTER TABLE ts_evidence ADD COLUMN IF NOT EXISTS independence_key text NOT NULL DEFAULT '';
CREATE UNIQUE INDEX IF NOT EXISTS ux_ts_evidence_run_span
    ON ts_evidence (thesis_id, rung, run_id, span_hash, relation)
    WHERE run_id <> '' AND span_hash <> '';

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
-- The claim set a follow-up turn was scoped to (one agent, N selected claims). Single `rung` is still
-- written for back-compat; `rungs` is the multi-claim context the tested-phase agent reasons over.
ALTER TABLE ts_turn ADD COLUMN IF NOT EXISTS rungs jsonb NOT NULL DEFAULT '[]';

-- Lines of inquiry / Socratic questions (the decision-engine surface). A question is TYPED (its lens),
-- carries the reader-facing text plus the declarative `target` the evidence run tests, and — once
-- answered — its target_status, grounded answer, and the run that produced them. Editing an ANSWERED
-- question supersedes it (a new row, the old marked superseded) so prior answers stay traceable; an
-- unrun question is edited in place. Status: active | superseded | removed.
CREATE TABLE IF NOT EXISTS ts_question (
    id            text PRIMARY KEY,
    thesis_id     text NOT NULL REFERENCES ts_thesis(id) ON DELETE CASCADE,
    inquiry_key   text NOT NULL,
    aspect_key    text NOT NULL,
    kind          text NOT NULL,
    text          text NOT NULL,
    target        text NOT NULL,
    polarity      int  NOT NULL DEFAULT 1,
    sort_order    int  NOT NULL DEFAULT 0,
    status        text NOT NULL DEFAULT 'active',       -- active | superseded | removed
    target_status text NOT NULL DEFAULT '',             -- decision.TARGET_* once answered
    answer        text NOT NULL DEFAULT '',             -- grounded, [[e:id]]-cited prose
    evidence_ids  jsonb NOT NULL DEFAULT '[]',
    run_id        text NOT NULL DEFAULT '',             -- the run that last answered it ('' = never run)
    superseded_by text NOT NULL DEFAULT '',
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ts_question_inq ON ts_question (thesis_id, inquiry_key, sort_order);

CREATE TABLE IF NOT EXISTS ts_run (
    id              text PRIMARY KEY,
    thesis_id       text NOT NULL REFERENCES ts_thesis(id) ON DELETE CASCADE,
    idempotency_key text NOT NULL,
    state           text NOT NULL DEFAULT 'approved',
    stage           text NOT NULL DEFAULT 'approved',
    projected_usd   numeric NOT NULL DEFAULT 0,
    approved_usd    numeric NOT NULL DEFAULT 0,
    actual_usd      numeric NOT NULL DEFAULT 0,
    metadata        jsonb NOT NULL DEFAULT '{}',
    error           jsonb NOT NULL DEFAULT '{}',
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (thesis_id, idempotency_key)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ts_run_one_active
    ON ts_run (thesis_id) WHERE state IN ('approved', 'running');
"""


class ActiveRunError(RuntimeError):
    pass


class SpendCapError(RuntimeError):
    pass


async def ensure_schema(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_DDL)


def _j(v):
    return json.loads(v) if isinstance(v, str) else v


def hash_owner_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


async def create(pool, *, thesis: str, claims: list[dict], subject: dict,
                 owner_id: str = "", title: str = "") -> dict:
    await ensure_schema(pool)
    tid = uuid.uuid4().hex[:16]
    share_token = secrets.token_urlsafe(24)
    owner_token = "" if owner_id else secrets.token_urlsafe(32)
    owner_hash = hash_owner_token(owner_token) if owner_token else ""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO ts_thesis (id, owner_id, title, thesis, subject, share_token,
                                      owner_token_hash)
               VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7)""",
            tid, owner_id, (title or thesis)[:160], thesis, json.dumps(subject or {}),
            share_token, owner_hash)
        for c in claims:
            await conn.execute(
                """INSERT INTO ts_claim (thesis_id, rung, claim, settleable, verdict, critical,
                                          falsifier, what_would_change, research_status)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                   ON CONFLICT (thesis_id, rung) DO NOTHING""",
                tid, c["rung"], c["claim"], c["settleable"], c.get("verdict") or OPEN,
                bool(c.get("critical")), c.get("falsifier") or "",
                c.get("what_would_change") or "", c.get("research_status") or OPEN)
    return {"id": tid, "owner_token": owner_token or None}


async def get(pool, *, thesis_id: str = "", share_token: str = "", owner_id: str = "",
              owner_token: str = "") -> dict | None:
    """Return the ledger only for its owner or an explicit read-only share capability."""
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        if thesis_id:
            t = await conn.fetchrow("SELECT * FROM ts_thesis WHERE id = $1", thesis_id)
        else:
            t = await conn.fetchrow("SELECT * FROM ts_thesis WHERE share_token = $1", share_token)
        if not t:
            return None
        stored_owner = str(t.get("owner_id") or "")
        stored_hash = str(t.get("owner_token_hash") or "")
        stored_share = str(t.get("share_token") or "")
        authenticated_owner = bool(owner_id) and bool(stored_owner) and stored_owner == owner_id
        capability_owner = (not stored_owner and bool(owner_token) and bool(stored_hash)
                            and hmac.compare_digest(hash_owner_token(owner_token), stored_hash))
        shared = bool(share_token) and bool(stored_share) and hmac.compare_digest(
            share_token, stored_share)
        is_owner = authenticated_owner or capability_owner
        if not is_owner and not shared:
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
    out["decision"] = _j(out.get("decision") or {})
    for k in ("created_at", "updated_at"):
        out[k] = out[k].isoformat()
    out["is_owner"] = is_owner
    out.pop("share_token", None)
    out.pop("owner_token_hash", None)
    by_rung: dict[str, list] = {}
    for e in ev:
        if not is_owner and e.get("source_key") == "call":
            continue
        row = {k: e[k] for k in e.keys() if k not in ("created_at",)}
        for key in ("gate_results", "facets"):
            if key in row:
                row[key] = _j(row[key]) or {}
        by_rung.setdefault(e["rung"], []).append(row)
    out["claims"] = [{**{k: c[k] for k in c.keys() if k != "attacked_at"},
                      "attacked": bool(c["attacked_at"]),
                      "evidence": by_rung.get(c["rung"], [])} for c in claims]
    out["turns"] = ([{"role": r["role"], "move": r["move"], "rung": r["rung"],
                      "rungs": _j(r["rungs"]) if "rungs" in r else [],
                      "text": r["text"], "payload": _j(r["payload"])} for r in turns]
                    if is_owner else [])
    return out


async def add_evidence(pool, thesis_id: str, rung: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    await ensure_schema(pool)
    async with pool.acquire() as conn, conn.transaction():
        for r in rows:
            await conn.execute(
                """INSERT INTO ts_evidence (id, thesis_id, rung, side, register, source_key,
                       signal_only, title, quote, source_url, as_of, basis, said_by, said_role,
                       document_id, block_id, atom_id, relation, evidence_kind, source_subject,
                       period, span_hash, gate_results, facets, run_id, independence_key)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,
                           $19,$20,$21,$22,$23::jsonb,$24::jsonb,$25,$26)
                   ON CONFLICT DO NOTHING""",
                r.get("id") or uuid.uuid4().hex[:16], thesis_id, rung, r["side"], r["register"],
                r.get("source_key") or "", bool(r.get("signal_only")), (r.get("title") or "")[:300],
                (r.get("quote") or "")[:1200], r.get("source_url") or "", r.get("as_of") or "",
                r.get("basis") or "", r.get("said_by") or "", r.get("said_role") or "",
                r.get("document_id") or "", r.get("block_id") or "", r.get("atom_id") or "",
                r.get("relation") or "context", r.get("evidence_kind") or "",
                r.get("source_subject") or "", r.get("period") or r.get("as_of") or "",
                r.get("span_hash") or "", json.dumps(r.get("gate_results") or {}),
                json.dumps(r.get("facets") or {}), r.get("run_id") or "",
                r.get("independence_key") or "")
    return len(rows)


async def set_verdict(pool, thesis_id: str, rung: str, verdict: str, note: str = "",
                      *, attacked: bool = False, run_id: str = "") -> None:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            f"""UPDATE ts_claim SET verdict = $3, research_status = $3, note = $4
                   {", attacked_at = now()" if attacked else ""}
                   {", tested_run_id = $5" if run_id else ""}
                 WHERE thesis_id = $1 AND rung = $2""",     # noqa: S608 — literal, not user input
            *( (thesis_id, rung, verdict, note[:400], run_id) if run_id
               else (thesis_id, rung, verdict, note[:400]) ))
        await conn.execute("UPDATE ts_thesis SET updated_at = now() WHERE id = $1", thesis_id)


async def set_proposed_thesis(pool, thesis_id: str, proposed: str) -> None:
    """The genesis agent's current best one-sentence thesis. Draft-only; overwritten each turn."""
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE ts_thesis SET proposed_thesis = $2, updated_at = now() WHERE id = $1",
            thesis_id, (proposed or "")[:600])


async def claims_tested_by_run(pool, thesis_id: str, run_id: str) -> set[str]:
    """The rungs already settled by THIS run — the claim-level resume signal. A resumed run re-drives
    only the claims not in this set, so an interrupted run never re-attacks a completed claim."""
    if not run_id:
        return set()
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT rung FROM ts_claim WHERE thesis_id = $1 AND tested_run_id = $2",
            thesis_id, run_id)
    return {r["rung"] for r in rows}


async def set_cases(pool, thesis_id: str, cases: dict[str, dict]) -> int:
    if not cases:
        return 0
    await ensure_schema(pool)
    async with pool.acquire() as conn, conn.transaction():
        for rung, c in cases.items():
            await conn.execute(
                """UPDATE ts_claim SET case_for = $3, case_against = $4, leans = $5
                    WHERE thesis_id = $1 AND rung = $2""",
                thesis_id, rung, c.get("case_for") or "", c.get("case_against") or "",
                c.get("leans") or "")
    return len(cases)


async def set_overall(pool, thesis_id: str, overall: str) -> None:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE ts_thesis SET overall = $2, updated_at = now() WHERE id = $1",
                           thesis_id, (overall or "")[:2000])


async def set_focus(pool, thesis_id: str, rung: str) -> None:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE ts_thesis SET focus_rung = $2 WHERE id = $1", thesis_id, rung)


async def commit_claims(pool, thesis_id: str, *, thesis: str, claims: list[dict],
                        subject: dict) -> None:
    """Confirm a draft: set its committed thesis text + subject and write the decomposed claims. Used
    by genesis → confirm. Insert-only on claims (a re-confirm never clobbers an existing ladder)."""
    await ensure_schema(pool)
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """UPDATE ts_thesis SET thesis = $2, subject = $3::jsonb, proposed_thesis = '',
                   updated_at = now() WHERE id = $1""",
            thesis_id, thesis[:2000], json.dumps(subject or {}))
        for c in claims:
            await conn.execute(
                """INSERT INTO ts_claim (thesis_id, rung, claim, settleable, verdict, critical,
                                          falsifier, what_would_change, research_status)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                   ON CONFLICT (thesis_id, rung) DO NOTHING""",
                thesis_id, c["rung"], c["claim"], c["settleable"], c.get("verdict") or OPEN,
                bool(c.get("critical")), c.get("falsifier") or "",
                c.get("what_would_change") or "", c.get("research_status") or OPEN)


async def revise_claim(pool, thesis_id: str, rung: str, claim: str) -> None:
    """The author reworded the claim. Their wording wins — it is their thesis."""
    await ensure_schema(pool)
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """UPDATE ts_claim
                  SET claim=$3, verdict='open', research_status = 'open', note='', attacked_at=NULL,
                      case_for='', case_against='', leans=''
                WHERE thesis_id=$1 AND rung=$2""",
            thesis_id, rung, claim[:600])
        await conn.execute("DELETE FROM ts_evidence WHERE thesis_id=$1 AND rung=$2", thesis_id, rung)
        await conn.execute(
            """UPDATE ts_thesis SET decision='{}'::jsonb, research_status='not_run',
                                    overall='', updated_at=now() WHERE id=$1""", thesis_id)


async def add_turn(pool, thesis_id: str, *, role: str, move: str = "", rung: str = "",
                   text: str = "", payload: dict | None = None,
                   rungs: list[str] | None = None) -> None:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO ts_turn (thesis_id, role, move, rung, text, payload, rungs)
               VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb)""",
            thesis_id, role, move, rung, text[:4000], json.dumps(payload or {}),
            json.dumps(list(rungs or [])))


async def recent(pool, *, owner_id: str = "", limit: int = 40) -> list[dict]:
    await ensure_schema(pool)
    if not owner_id:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT t.id, t.title, t.thesis, t.updated_at,
                      count(*) FILTER (WHERE c.verdict <> 'open') AS settled,
                      count(c.rung) AS claims
                 FROM ts_thesis t LEFT JOIN ts_claim c ON c.thesis_id = t.id
                WHERE t.owner_id = $1
                GROUP BY t.id ORDER BY t.updated_at DESC LIMIT $2""", owner_id, limit)
    return [{"id": r["id"], "title": r["title"], "thesis": r["thesis"],
             "settled": int(r["settled"] or 0), "claims": int(r["claims"] or 0),
             "updated_at": r["updated_at"].isoformat()} for r in rows]


def _run_out(row) -> dict | None:
    if not row:
        return None
    out = {k: row[k] for k in row.keys()}
    for key in ("metadata", "error"):
        out[key] = _j(out.get(key) or {})
    for key in ("projected_usd", "approved_usd", "actual_usd"):
        out[key] = float(out.get(key) or 0)
    for key in ("created_at", "updated_at"):
        if key in out and hasattr(out[key], "isoformat"):
            out[key] = out[key].isoformat()
    return out


async def create_run(pool, *, thesis_id: str, idempotency_key: str, projected_usd: float,
                     approved_usd: float, metadata: dict) -> dict:
    await ensure_schema(pool)
    key = (idempotency_key or "").strip()
    if not key:
        raise ValueError("idempotency_key is required")
    async with pool.acquire() as conn, conn.transaction():
        existing = await conn.fetchrow(
            "SELECT * FROM ts_run WHERE thesis_id = $1 AND idempotency_key = $2",
            thesis_id, key)
        if existing:
            return _run_out(existing)
        active = await conn.fetchrow(
            "SELECT * FROM ts_run WHERE thesis_id = $1 AND state IN ('approved','running')",
            thesis_id)
        if active:
            raise ActiveRunError("a research run is already active")
        run_id = uuid.uuid4().hex[:20]
        row = await conn.fetchrow(
            """INSERT INTO ts_run (id, thesis_id, idempotency_key, projected_usd,
                                    approved_usd, metadata)
               VALUES ($1,$2,$3,$4,$5,$6::jsonb) RETURNING *""",
            run_id, thesis_id, key, float(projected_usd), float(approved_usd),
            json.dumps(metadata or {}))
    return _run_out(row)


async def get_run(pool, *, thesis_id: str, run_id: str) -> dict | None:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ts_run WHERE thesis_id = $1 AND id = $2", thesis_id, run_id)
    return _run_out(row)


async def advance_run(pool, *, thesis_id: str, run_id: str, stage: str,
                      state: str = "running", actual_delta: float = 0.0) -> dict:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE ts_run
                  SET stage=$3, state=$4, actual_usd=actual_usd+$5, updated_at=now()
                WHERE thesis_id=$1 AND id=$2 AND actual_usd+$5 <= approved_usd
                RETURNING *""",
            thesis_id, run_id, stage, state, float(actual_delta))
    if not row:
        raise SpendCapError("research run is missing or would exceed its approved cost")
    return _run_out(row)


async def fail_run(pool, *, thesis_id: str, run_id: str, stage: str, error: dict) -> None:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE ts_run SET state='failed', stage=$3, error=$4::jsonb, updated_at=now()
                 WHERE thesis_id=$1 AND id=$2""",
            thesis_id, run_id, stage, json.dumps(error or {}))


async def set_decision(pool, thesis_id: str, decision: dict, *, research_status: str) -> None:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE ts_thesis SET decision=$2::jsonb, research_status=$3, updated_at=now()
                 WHERE id=$1""",
            thesis_id, json.dumps(decision or {}), research_status)


async def issue_share(pool, thesis_id: str) -> str:
    await ensure_schema(pool)
    token = secrets.token_urlsafe(24)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE ts_thesis SET share_token=$2, updated_at=now() WHERE id=$1 RETURNING share_token",
            thesis_id, token)
    return str(row["share_token"] if row else "")


async def revoke_share(pool, thesis_id: str) -> None:
    # Rotation invalidates every previously copied read-only URL without creating a nullable state.
    await issue_share(pool, thesis_id)


# ---- lines of inquiry: Socratic questions ------------------------------------------------------
import hashlib as _hashlib


def _q_out(row) -> dict:
    out = {k: row[k] for k in row.keys() if k != "created_at"}
    out["evidence_ids"] = _j(out.get("evidence_ids") or [])
    return out


async def set_questions(pool, thesis_id: str, inquiry_key: str, questions: list[dict]) -> None:
    """Replace the UNRUN active questions of one inquiry with a freshly generated set. Answered
    questions (run_id != '') are left untouched — regenerating never discards work the user paid for."""
    await ensure_schema(pool)
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """UPDATE ts_question SET status='removed'
                 WHERE thesis_id=$1 AND inquiry_key=$2 AND status='active' AND run_id=''""",
            thesis_id, inquiry_key)
        for i, q in enumerate(questions):
            await conn.execute(
                """INSERT INTO ts_question (id, thesis_id, inquiry_key, aspect_key, kind, text, target,
                                            polarity, sort_order)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                uuid.uuid4().hex[:16], thesis_id, inquiry_key, q["aspect_key"], q["kind"],
                q["text"][:400], q["target"][:400], int(q.get("polarity", 1)), i)


async def list_questions(pool, thesis_id: str, inquiry_key: str = "") -> list[dict]:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM ts_question WHERE thesis_id=$1 AND status='active'
                 AND ($2='' OR inquiry_key=$2) ORDER BY inquiry_key, sort_order""",
            thesis_id, inquiry_key)
    return [_q_out(r) for r in rows]


async def add_question(pool, thesis_id: str, inquiry_key: str, aspect_key: str, *, kind: str,
                       text: str, target: str, polarity: int = 1) -> str:
    await ensure_schema(pool)
    qid = uuid.uuid4().hex[:16]
    async with pool.acquire() as conn:
        nxt = await conn.fetchval(
            "SELECT coalesce(max(sort_order),0)+1 FROM ts_question WHERE thesis_id=$1 AND inquiry_key=$2",
            thesis_id, inquiry_key)
        await conn.execute(
            """INSERT INTO ts_question (id, thesis_id, inquiry_key, aspect_key, kind, text, target,
                                        polarity, sort_order)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
            qid, thesis_id, inquiry_key, aspect_key, kind, text[:400], target[:400],
            int(polarity), int(nxt or 0))
    return qid


async def edit_question(pool, thesis_id: str, qid: str, *, text: str = "", target: str = "") -> str:
    """Mutable-until-run: an unrun question is edited in place. An ANSWERED question is superseded — a
    new row inherits its slot, the old is marked superseded — so prior answers stay traceable and a
    re-run is required. Returns the id now in effect."""
    await ensure_schema(pool)
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "SELECT * FROM ts_question WHERE thesis_id=$1 AND id=$2 AND status='active'", thesis_id, qid)
        if not row:
            return ""
        new_text = (text or row["text"])[:400]
        new_target = (target or row["target"])[:400]
        if row["run_id"] == "":
            await conn.execute(
                "UPDATE ts_question SET text=$3, target=$4 WHERE thesis_id=$1 AND id=$2",
                thesis_id, qid, new_text, new_target)
            return qid
        nid = uuid.uuid4().hex[:16]
        await conn.execute(
            """INSERT INTO ts_question (id, thesis_id, inquiry_key, aspect_key, kind, text, target,
                                        polarity, sort_order)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
            nid, thesis_id, row["inquiry_key"], row["aspect_key"], row["kind"], new_text, new_target,
            int(row["polarity"]), int(row["sort_order"]))
        await conn.execute(
            "UPDATE ts_question SET status='superseded', superseded_by=$3 WHERE thesis_id=$1 AND id=$2",
            thesis_id, qid, nid)
        return nid


async def remove_question(pool, thesis_id: str, qid: str) -> None:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE ts_question SET status='removed' WHERE thesis_id=$1 AND id=$2", thesis_id, qid)


async def answer_question(pool, thesis_id: str, qid: str, *, target_status: str, answer: str,
                          evidence_ids: list[str], run_id: str) -> None:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE ts_question SET target_status=$3, answer=$4, evidence_ids=$5::jsonb, run_id=$6
                 WHERE thesis_id=$1 AND id=$2""",
            thesis_id, qid, target_status, answer[:4000], json.dumps(list(evidence_ids or [])), run_id)


def active_question_hash(questions: list[dict]) -> str:
    """The run's idempotency signature — a hash of the active question set (id + target). Re-running the
    SAME set is a no-op (create_run dedups on it); editing any question changes the hash, so it becomes a
    new run while the superseded answers stay put."""
    parts = sorted(f"{q.get('id','')}:{q.get('target','')}" for q in (questions or []))
    return _hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:24]
