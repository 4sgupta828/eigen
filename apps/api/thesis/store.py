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

import asyncio
import json
import hashlib
import hmac
import secrets
import uuid

from .schema import OPEN


def _loads(v):
    """asyncpg returns jsonb as a str (or already-decoded) depending on codecs — normalize to Python."""
    if v is None:
        return None
    return json.loads(v) if isinstance(v, str) else v


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


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
-- Cross-finding synthesis over EVERY answered question at once: the founder-voice Startup Pitch Deck and
-- the integrated Collective Take (diligence verdict). Deck is {spine:{one_liner,insight,bottom_line},
-- sections:[{key,title,headline:{text,markers},points:[{text,markers}]}], generated_at}; take is
-- {bottom_line, sections:[{key,title,grounded,analysis}]}. (Older decks used sections:[{prose}]; the
-- client still renders those.) Regenerated free from existing findings; distinct from `overall`.
ALTER TABLE ts_thesis ADD COLUMN IF NOT EXISTS pitch_deck jsonb NOT NULL DEFAULT '{}';
ALTER TABLE ts_thesis ADD COLUMN IF NOT EXISTS collective_take jsonb NOT NULL DEFAULT '{}';
-- The competitive-landscape matrix: the thesis company vs. named peers across the startup rubric,
-- {columns:[{key,label}], rows:[{entity,subject,cells:[{text,markers}]}]}. Cells empty where unknown.
ALTER TABLE ts_thesis ADD COLUMN IF NOT EXISTS competitive jsonb NOT NULL DEFAULT '{}';
-- The dated, typed LandscapeBrief from the orient-and-scan (keeps the QUESTIONS current, not just the
-- answers): {as_of, incumbents, entrants, funding, regulation, benchmarks, why_now, unknowns}.
ALTER TABLE ts_thesis ADD COLUMN IF NOT EXISTS landscape_brief jsonb NOT NULL DEFAULT '{}';
ALTER TABLE ts_thesis ADD COLUMN IF NOT EXISTS owner_token_hash text NOT NULL DEFAULT '';
ALTER TABLE ts_thesis ADD COLUMN IF NOT EXISTS decision jsonb NOT NULL DEFAULT '{}';
ALTER TABLE ts_thesis ADD COLUMN IF NOT EXISTS research_status text NOT NULL DEFAULT 'not_run';
-- The genesis agent's current best one-sentence formalization, before the user confirms it. A thesis
-- with zero claims is a DRAFT (still in genesis); this holds what "Use this thesis" would commit.
ALTER TABLE ts_thesis ADD COLUMN IF NOT EXISTS proposed_thesis text NOT NULL DEFAULT '';
-- The SEQUENCE of thesis versions, so the author can BACKTRACK to any earlier wording and REDO an update
-- differently (a new edit from a reverted version branches — parent_id points at where it came from).
-- Each entry: {id, text, parent_id, source: user_edit|self_improve|directed|genesis, rationale, at}.
-- `active_version` is the one the current `thesis`/`proposed_thesis` text reflects.
ALTER TABLE ts_thesis ADD COLUMN IF NOT EXISTS versions jsonb NOT NULL DEFAULT '[]';
ALTER TABLE ts_thesis ADD COLUMN IF NOT EXISTS active_version text NOT NULL DEFAULT '';
-- The genesis agent's SHAPING MEMORY: how THIS author wants the thesis shaped (priorities, constraints,
-- style) — carried into every turn + the self-improve loop so the agent understands them over time.
ALTER TABLE ts_thesis ADD COLUMN IF NOT EXISTS shaping_prefs jsonb NOT NULL DEFAULT '[]';

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
-- The line-of-inquiry (cluster) a question belongs to is now GENERATED per thesis, not a fixed group,
-- so its display name/framing is denormalized onto the question (the cluster's own row would otherwise
-- need a table). All questions in one inquiry_key carry the same name/framing.
ALTER TABLE ts_question ADD COLUMN IF NOT EXISTS inquiry_name text NOT NULL DEFAULT '';
ALTER TABLE ts_question ADD COLUMN IF NOT EXISTS inquiry_framing text NOT NULL DEFAULT '';
ALTER TABLE ts_question ADD COLUMN IF NOT EXISTS inquiry_order int NOT NULL DEFAULT 0;
-- Priority LEVEL, assigned at generation with full context: 0 = P0 (critical crux, run first), 1 = P1,
-- 2 = P2 … Higher levels are incremental coverage. The critical-subset run is simply priority = 0; a
-- user runs deeper levels for more coverage. Default 1 so an un-prioritized question is mid, not a crux.
ALTER TABLE ts_question ADD COLUMN IF NOT EXISTS priority int NOT NULL DEFAULT 1;

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

-- The expert ROSTER — a personal, cross-thesis map of the people you've found and talked to. Keyed on
-- owner_id (the authenticated user): experts discovered while validating one thesis stay available to
-- the next. `url` is their public profile; a call transcript (below) references the expert saved here.
CREATE TABLE IF NOT EXISTS ts_expert (
    id          text PRIMARY KEY,
    owner_id    text NOT NULL DEFAULT '',
    name        text NOT NULL,
    url         text NOT NULL DEFAULT '',   -- public profile (LinkedIn, homepage) — never a guessed one
    firm        text NOT NULL DEFAULT '',   -- for independence: two accounts from one firm are one account
    role        text NOT NULL DEFAULT '',   -- buyer / operator / advisor …
    headline    text NOT NULL DEFAULT '',
    source      text NOT NULL DEFAULT '',   -- exa | pdl | manual
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ts_expert_owner ON ts_expert (owner_id, updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ts_expert_owner_url ON ts_expert (owner_id, url) WHERE url <> '';

-- An expert-call TRANSCRIPT attached to one LINE OF INQUIRY, with its verbatim-gated INSIGHTS. Each
-- insight is a quote the expert actually said, tagged validates|invalidates|context toward the line's
-- questions — expert opinion is 'stated', informative but never controlling (the sentiment discipline).
-- Owner-only: the raw transcript never leaves the owner's view.
CREATE TABLE IF NOT EXISTS ts_transcript (
    id          text PRIMARY KEY,
    thesis_id   text NOT NULL REFERENCES ts_thesis(id) ON DELETE CASCADE,
    inquiry_key text NOT NULL,
    expert_id   text NOT NULL DEFAULT '',   -- ts_expert.id when saved to the roster, else ''
    expert_name text NOT NULL DEFAULT '',
    expert_url  text NOT NULL DEFAULT '',
    firm        text NOT NULL DEFAULT '',
    role        text NOT NULL DEFAULT '',
    transcript  text NOT NULL DEFAULT '',   -- the raw paste, owner-only
    insights    jsonb NOT NULL DEFAULT '[]',
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ts_transcript_inq ON ts_transcript (thesis_id, inquiry_key, created_at DESC);

-- The public ThesisBoard: a GLOBAL, cross-user gallery of theses their authors chose to publish. Each
-- row is a FROZEN, ANONYMIZED snapshot built at publish time — unanswered questions stripped, the
-- submitter's identity removed (the `payload` is self-contained and safe to serve with no auth). The
-- source `thesis_id`/`owner_id` are kept ONLY so the author can re-publish or unpublish (and for
-- moderation) and are NEVER included in any public read path. Re-publishing the same thesis REPLACES its
-- snapshot in place (stable public URL). Deleting the source thesis cascades nothing here on purpose —
-- unpublish is an explicit author/admin action — so `thesis_id` is a plain column, not an FK.
CREATE TABLE IF NOT EXISTS ts_board (
    id               text PRIMARY KEY,            -- public entry id (the board URL); unguessable
    thesis_id        text NOT NULL,               -- internal: source thesis (re-publish / unpublish)
    owner_id         text NOT NULL DEFAULT '',    -- internal: publisher; NEVER served publicly
    title            text NOT NULL DEFAULT '',
    summary          text NOT NULL DEFAULT '',    -- the thesis sentence, for the card
    findings         int  NOT NULL DEFAULT 0,     -- answered-question count, for the card
    payload          jsonb NOT NULL DEFAULT '{}', -- the sanitized, self-contained public snapshot
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ts_board_thesis ON ts_board (thesis_id);
CREATE INDEX IF NOT EXISTS ix_ts_board_recent ON ts_board (created_at DESC);
"""


class ActiveRunError(RuntimeError):
    pass


class SpendCapError(RuntimeError):
    pass


_SCHEMA_READY = False
_SCHEMA_LOCK = asyncio.Lock()


async def ensure_schema(pool) -> None:
    """Run the DDL ONCE per process, serialized. Running the full 40-statement DDL on every store call
    (as this used to) took ALTER/CREATE-INDEX locks on every table each request — and once ts_transcript
    added a FK to ts_thesis, two concurrent requests (e.g. add_turn + GET) deadlocked on those DDL locks.
    The DDL is idempotent (IF NOT EXISTS), so doing it once at first use is correct and lock-free after."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    async with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        last = None
        for _ in range(3):        # a rare cross-worker startup collision on the idempotent DDL → retry
            try:
                async with pool.acquire() as conn:
                    await conn.execute(_DDL)
                _SCHEMA_READY = True
                return
            except Exception as exc:      # noqa: BLE001
                last = exc
                await asyncio.sleep(0.4)
        raise last


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
              owner_token: str = "", trusted: bool = False) -> dict | None:
    """Return the ledger only for its owner or an explicit read-only share capability. `trusted=True`
    is for SERVER-SIDE callers (e.g. the background research runner, already authorized at the route)
    that hold no user credential — it skips the ownership gate; never set it from a request handler."""
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
        is_owner = authenticated_owner or capability_owner or trusted
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
    out["pitch_deck"] = _j(out.get("pitch_deck") or {}) or {}
    out["collective_take"] = _j(out.get("collective_take") or {}) or {}
    out["competitive"] = _j(out.get("competitive") or {}) or {}
    out["landscape_brief"] = _j(out.get("landscape_brief") or {}) or {}
    out["versions"] = _j(out.get("versions") or []) or []           # thesis version timeline (backtrack)
    out["shaping_prefs"] = _j(out.get("shaping_prefs") or []) or []  # how the author wants it shaped
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
    # Evidence is stored per RUNG (= the profile ASPECT key). The inquiries flow gathers evidence for the
    # vertical's full aspect set, which is BROADER than the legacy decompose ladder (schema.LADDER) — so
    # some aspects (e.g. prior_landscape, differentiation, traction) have evidence but no ts_claim row.
    # Surface that evidence too, or its [[e:id]] citations resolve to nothing on the client (the regression
    # that made citations vanish on those questions). A synthetic claim carries only the evidence.
    _covered = {c["rung"] for c in claims}
    for _rung, _rows in by_rung.items():
        if _rung and _rung not in _covered:
            out["claims"].append({"rung": _rung, "claim": "", "settleable": "", "verdict": "open",
                                  "research_status": "open", "critical": False, "attacked": False,
                                  "evidence": _rows})
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
    """The genesis agent's current best thesis, draft-only, overwritten each turn. `proposed_thesis` is
    an unbounded `text` column; the 2000-char cap matches commit_claims (the ceiling when this becomes
    the committed thesis) so a detailed sample/genesis thesis survives the whole draft path uncut."""
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE ts_thesis SET proposed_thesis = $2, updated_at = now() WHERE id = $1",
            thesis_id, (proposed or "")[:2000])


async def add_thesis_version(pool, thesis_id: str, text: str, *, source: str = "user_edit",
                             rationale: str = "", parent_id: str = "") -> str:
    """Append a thesis version and make it active — the unit of backtracking. Sets the DRAFT
    (`proposed_thesis`) text to it (committing to `thesis` stays the explicit 'Use this thesis' step).
    `parent_id` records which version this one was derived from; when omitted it chains onto the active
    one, so a linear edit history and a branch (edit-after-revert) are the same mechanism. -> version id."""
    text = (text or "").strip()[:2000]
    if not text:
        return ""
    await ensure_schema(pool)
    vid = uuid.uuid4().hex[:12]
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow("SELECT versions, active_version FROM ts_thesis WHERE id = $1", thesis_id)
        if row is None:
            return ""
        versions = list(_loads(row["versions"]) or [])
        parent = parent_id or row["active_version"] or ""
        versions.append({"id": vid, "text": text, "parent_id": parent, "source": source,
                         "rationale": (rationale or "")[:600], "at": _now_iso()})
        await conn.execute(
            "UPDATE ts_thesis SET versions = $2::jsonb, active_version = $3, proposed_thesis = $4, "
            "updated_at = now() WHERE id = $1",
            thesis_id, json.dumps(versions[-100:]), vid, text)
    return vid


async def list_thesis_versions(pool, thesis_id: str) -> list[dict]:
    """The version sequence, oldest first, with the active one flagged — the backtrack timeline."""
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT versions, active_version FROM ts_thesis WHERE id = $1", thesis_id)
    if row is None:
        return []
    active = row["active_version"] or ""
    return [{**v, "active": v.get("id") == active} for v in (_loads(row["versions"]) or [])]


async def revert_thesis_version(pool, thesis_id: str, version_id: str) -> dict | None:
    """Backtrack: make an earlier version active again and restore its text as the draft. A later edit
    from here branches (its parent_id becomes this version). -> {id, text} or None if unknown."""
    await ensure_schema(pool)
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow("SELECT versions FROM ts_thesis WHERE id = $1", thesis_id)
        if row is None:
            return None
        target = next((v for v in (_loads(row["versions"]) or []) if v.get("id") == version_id), None)
        if target is None:
            return None
        await conn.execute(
            "UPDATE ts_thesis SET active_version = $2, proposed_thesis = $3, updated_at = now() WHERE id = $1",
            thesis_id, version_id, (target.get("text") or "")[:2000])
    return {"id": version_id, "text": target.get("text") or ""}


async def set_shaping_prefs(pool, thesis_id: str, prefs: list[str]) -> None:
    """Persist the genesis agent's read of how this author wants the thesis shaped (deduped, capped)."""
    await ensure_schema(pool)
    clean = []
    for p in (prefs or []):
        s = str(p or "").strip()[:200]
        if s and s not in clean:
            clean.append(s)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE ts_thesis SET shaping_prefs = $2::jsonb, updated_at = now() WHERE id = $1",
                           thesis_id, json.dumps(clean[:12]))


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


async def set_pitch_deck(pool, thesis_id: str, deck: dict) -> None:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE ts_thesis SET pitch_deck = $2::jsonb, updated_at = now() WHERE id = $1",
                           thesis_id, json.dumps(deck or {}))


async def set_collective_take(pool, thesis_id: str, take: dict) -> None:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE ts_thesis SET collective_take = $2::jsonb, updated_at = now() WHERE id = $1",
                           thesis_id, json.dumps(take or {}))


async def set_competitive(pool, thesis_id: str, matrix: dict) -> None:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE ts_thesis SET competitive = $2::jsonb, updated_at = now() WHERE id = $1",
                           thesis_id, json.dumps(matrix or {}))


async def set_landscape_brief(pool, thesis_id: str, brief: dict) -> None:
    """Persist the dated orient-and-scan brief on the thesis (reused within TTL; surfaced in the UI)."""
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE ts_thesis SET landscape_brief = $2::jsonb, updated_at = now() WHERE id = $1",
                           thesis_id, json.dumps(brief or {}))


async def add_competitive_players(pool, thesis_id: str, new_players: list[dict], *,
                                  space: str = "", columns: list[dict] | None = None) -> int:
    """Append profiled players to the stored competitive landscape (dedupe by name, keep existing) — so the
    user can EXPAND the map with '+ Add competitors' without re-researching what's already there. Creates
    the landscape if none exists yet. -> number of players added."""
    await ensure_schema(pool)
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow("SELECT competitive FROM ts_thesis WHERE id = $1", thesis_id)
        if row is None:
            return 0
        land = _loads(row["competitive"]) or {}
        players = list(land.get("players") or [])
        have = {str(p.get("name") or "").strip().lower() for p in players}
        added = 0
        for p in (new_players or []):
            nm = str(p.get("name") or "").strip()
            if nm and nm.lower() not in have:
                players.append(p); have.add(nm.lower()); added += 1
        land["players"] = players
        land["empty"] = not players
        if space and not land.get("space"):
            land["space"] = space
        if columns and not land.get("columns"):
            land["columns"] = columns
        await conn.execute("UPDATE ts_thesis SET competitive = $2::jsonb, updated_at = now() WHERE id = $1",
                           thesis_id, json.dumps(land))
    return added


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


async def get_active_run(pool, *, thesis_id: str) -> dict | None:
    """The thesis's one in-flight run (state approved|running), or None — so the client can RE-ATTACH its
    progress indicator after a browser refresh instead of losing it while the run keeps going server-side."""
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ts_run WHERE thesis_id = $1 AND state IN ('approved','running') "
            "ORDER BY updated_at DESC LIMIT 1", thesis_id)
    return _run_out(row) if row else None


async def cancel_run(pool, *, thesis_id: str, run_id: str | None = None) -> str | None:
    """Cooperatively stop a run: mark it cancelled so its background loop halts before the next unit and
    the poller stops waiting. Cancels the given run, or the thesis's one active run when run_id is None.
    Returns the cancelled run id, or None if there was nothing active to cancel."""
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE ts_run SET state='cancelled', stage='cancelled', updated_at=now()
                 WHERE thesis_id=$1 AND ($2::text IS NULL OR id=$2) AND state IN ('approved','running')
                 RETURNING id""",
            thesis_id, run_id)
    return row["id"] if row else None


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


# ---- public ThesisBoard: a global gallery of anonymized, published snapshots ------------------------

async def publish_board(pool, *, thesis_id: str, owner_id: str, title: str, summary: str,
                        payload: dict, findings: int) -> str:
    """Insert or REPLACE this thesis's frozen public snapshot; returns the (stable) public entry id.
    Re-publishing the same thesis keeps its existing id so shared board URLs never break."""
    await ensure_schema(pool)
    new_id = secrets.token_urlsafe(12)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO ts_board (id, thesis_id, owner_id, title, summary, findings, payload)
                    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
               ON CONFLICT (thesis_id) DO UPDATE SET
                    title = EXCLUDED.title, summary = EXCLUDED.summary, findings = EXCLUDED.findings,
                    payload = EXCLUDED.payload, updated_at = now()
               RETURNING id""",
            new_id, thesis_id, owner_id or "", title or "", summary or "", int(findings or 0),
            json.dumps(payload or {}))
    return str(row["id"] if row else "")


async def board_list(pool, *, limit: int = 60) -> list[dict]:
    """Public board cards, newest first. Never returns owner_id / thesis_id / the full payload."""
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, title, summary, findings, created_at, updated_at
                 FROM ts_board ORDER BY created_at DESC LIMIT $1""", min(200, max(1, limit)))
    return [{"id": r["id"], "title": r["title"], "summary": r["summary"],
             "findings": int(r["findings"] or 0), "published_at": r["created_at"].isoformat(),
             "updated_at": r["updated_at"].isoformat()} for r in rows]


async def board_get(pool, entry_id: str) -> dict | None:
    """The public snapshot for one board entry — the self-contained, already-anonymized payload plus its
    display fields. NEVER includes thesis_id or owner_id (they are not selected)."""
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            """SELECT id, title, summary, findings, payload, created_at, updated_at
                 FROM ts_board WHERE id = $1""", entry_id)
    if not r:
        return None
    out = _j(r["payload"]) or {}
    out["board_id"] = r["id"]
    out["title"] = r["title"]
    out["summary"] = r["summary"]
    out["findings"] = int(r["findings"] or 0)
    out["published_at"] = r["created_at"].isoformat()
    out["updated_at"] = r["updated_at"].isoformat()
    out["anonymous"] = True
    return out


async def board_entry_for_thesis(pool, thesis_id: str) -> str:
    """The public entry id for a thesis if it is currently published, else ''. Owner-facing only."""
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT id FROM ts_board WHERE thesis_id = $1", thesis_id)
    return str(r["id"]) if r else ""


async def board_delete(pool, thesis_id: str) -> None:
    """Unpublish: remove this thesis's board snapshot. Caller must already be the verified owner."""
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM ts_board WHERE thesis_id = $1", thesis_id)


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


async def set_inquiries(pool, thesis_id: str, inquiries: list[dict]) -> None:
    """Replace ALL unrun questions of a thesis with a freshly generated set of lines of inquiry (the
    decision-level generation produces every cluster at once). Answered questions (run_id != '') are
    left untouched, so regenerating never discards paid-for work. Each inquiry:
    {key, name, framing, questions:[{dimension, kind, text, target, polarity}]}."""
    await ensure_schema(pool)
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "UPDATE ts_question SET status='removed' WHERE thesis_id=$1 AND status='active' AND run_id=''",
            thesis_id)
        order = 0
        for inq in inquiries:
            for i, q in enumerate(inq.get("questions") or []):
                await conn.execute(
                    """INSERT INTO ts_question (id, thesis_id, inquiry_key, aspect_key, kind, text,
                           target, polarity, sort_order, inquiry_name, inquiry_framing, inquiry_order,
                           priority)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)""",
                    uuid.uuid4().hex[:16], thesis_id, inq["key"], q["dimension"], q["kind"],
                    q["text"][:400], q["target"][:400], int(q.get("polarity", 1)), i,
                    (inq.get("name") or "")[:120], (inq.get("framing") or "")[:200], order,
                    max(0, int(q.get("priority", 1))))
            order += 1


async def set_question_priorities(pool, thesis_id: str, levels: dict) -> int:
    """Persist priority LEVELS on existing questions ({qid: level}) — used to (re)assign P0/P1/P2 to a
    thesis whose questions were drafted before priorities, without regenerating. -> rows updated."""
    if not levels:
        return 0
    await ensure_schema(pool)
    n = 0
    async with pool.acquire() as conn, conn.transaction():
        for qid, lvl in levels.items():
            n += 1 if await conn.execute(
                "UPDATE ts_question SET priority=$3 WHERE thesis_id=$1 AND id=$2",
                thesis_id, str(qid), max(0, int(lvl))) != "UPDATE 0" else 0
    return n


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


async def remove_inquiry(pool, thesis_id: str, inquiry_key: str) -> int:
    """Drop one line of inquiry's UNRUN questions so the user can redraft it. Answered questions
    (run_id != '') are preserved — deleting a line never silently discards paid-for research. Returns
    the number of drafted questions removed."""
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        res = await conn.execute(
            """UPDATE ts_question SET status='removed'
                 WHERE thesis_id=$1 AND inquiry_key=$2 AND status='active' AND run_id=''""",
            thesis_id, inquiry_key)
    return int((res or "UPDATE 0").split()[-1])


async def clear_inquiries(pool, thesis_id: str) -> int:
    """Drop ALL unrun questions across every line of inquiry — a clean slate to draft fresh from.
    Answered questions are preserved (paid work is never discarded silently). Returns the count removed."""
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        res = await conn.execute(
            "UPDATE ts_question SET status='removed' WHERE thesis_id=$1 AND status='active' AND run_id=''",
            thesis_id)
    return int((res or "UPDATE 0").split()[-1])


async def answer_question(pool, thesis_id: str, qid: str, *, target_status: str, answer: str,
                          evidence_ids: list[str], run_id: str) -> None:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE ts_question SET target_status=$3, answer=$4, evidence_ids=$5::jsonb, run_id=$6
                 WHERE thesis_id=$1 AND id=$2""",
            thesis_id, qid, target_status, answer[:9000], json.dumps(list(evidence_ids or [])), run_id)


def new_idempotency_key() -> str:
    """A fresh unique run key — for runs (e.g. competitive research) not keyed on a question set."""
    return uuid.uuid4().hex[:16]


def active_question_hash(questions: list[dict]) -> str:
    """The run's idempotency signature — a hash of the active question set (id + target). Re-running the
    SAME set is a no-op (create_run dedups on it); editing any question changes the hash, so it becomes a
    new run while the superseded answers stay put."""
    parts = sorted(f"{q.get('id','')}:{q.get('target','')}" for q in (questions or []))
    return _hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:24]


# ---- Expert roster (global, per owner) + per-line-of-inquiry transcripts --------------------------

def _expert_out(row) -> dict:
    d = {k: row[k] for k in row.keys()}
    for k in ("created_at", "updated_at"):
        if k in d and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    return d


async def save_expert(pool, owner_id: str, *, name: str, url: str = "", firm: str = "",
                      role: str = "", headline: str = "", source: str = "manual") -> str:
    """Upsert one expert into the owner's roster. Dedups on (owner_id, url) when a url is present, so
    saving the same profile twice updates rather than duplicates. Returns the expert id."""
    await ensure_schema(pool)
    eid = uuid.uuid4().hex[:16]
    async with pool.acquire() as conn:
        if url:
            existing = await conn.fetchrow(
                "SELECT id FROM ts_expert WHERE owner_id = $1 AND url = $2", owner_id, url)
            if existing:
                await conn.execute(
                    """UPDATE ts_expert SET name=$3, firm=$4, role=$5, headline=$6, source=$7,
                           updated_at=now() WHERE owner_id=$1 AND url=$2""",
                    owner_id, url, name[:200], firm[:200], role[:120], headline[:400], source[:40])
                return str(existing["id"])
        await conn.execute(
            """INSERT INTO ts_expert (id, owner_id, name, url, firm, role, headline, source)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
            eid, owner_id, name[:200], url[:600], firm[:200], role[:120], headline[:400], source[:40])
    return eid


async def list_experts(pool, owner_id: str) -> list[dict]:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM ts_expert WHERE owner_id = $1 ORDER BY updated_at DESC LIMIT 500", owner_id)
    return [_expert_out(r) for r in rows]


async def remove_expert(pool, owner_id: str, expert_id: str) -> int:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        res = await conn.execute(
            "DELETE FROM ts_expert WHERE owner_id = $1 AND id = $2", owner_id, expert_id)
    return int((res or "DELETE 0").split()[-1])


async def add_transcript(pool, thesis_id: str, inquiry_key: str, *, expert_id: str = "",
                         expert_name: str = "", expert_url: str = "", firm: str = "", role: str = "",
                         transcript: str = "", insights: list[dict] | None = None) -> str:
    """Save one expert-call transcript + its extracted insights against a line of inquiry."""
    await ensure_schema(pool)
    tid = uuid.uuid4().hex[:16]
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO ts_transcript (id, thesis_id, inquiry_key, expert_id, expert_name,
                   expert_url, firm, role, transcript, insights)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)""",
            tid, thesis_id, inquiry_key, expert_id, expert_name[:200], expert_url[:600],
            firm[:200], role[:120], (transcript or "")[:60000], json.dumps(insights or []))
    return tid


async def list_transcripts(pool, thesis_id: str, inquiry_key: str = "",
                           *, include_raw: bool = False) -> list[dict]:
    """Transcripts for a thesis (optionally one line of inquiry). `include_raw` returns the raw paste —
    owner-only; the default omits it so a shared view never carries the transcript body."""
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        if inquiry_key:
            rows = await conn.fetch(
                """SELECT * FROM ts_transcript WHERE thesis_id = $1 AND inquiry_key = $2
                   ORDER BY created_at DESC""", thesis_id, inquiry_key)
        else:
            rows = await conn.fetch(
                "SELECT * FROM ts_transcript WHERE thesis_id = $1 ORDER BY created_at DESC", thesis_id)
    out = []
    for r in rows:
        d = {k: r[k] for k in r.keys()}
        d["insights"] = _j(d.get("insights")) or []
        if "created_at" in d and hasattr(d["created_at"], "isoformat"):
            d["created_at"] = d["created_at"].isoformat()
        if not include_raw:
            d.pop("transcript", None)
        out.append(d)
    return out


async def remove_transcript(pool, thesis_id: str, transcript_id: str) -> int:
    await ensure_schema(pool)
    async with pool.acquire() as conn:
        res = await conn.execute(
            "DELETE FROM ts_transcript WHERE thesis_id = $1 AND id = $2", thesis_id, transcript_id)
    return int((res or "DELETE 0").split()[-1])
