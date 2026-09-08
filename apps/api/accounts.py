"""Accounts + feedback persistence (adoption P0) — app-level, kernel-free, same Postgres as sessions.

Two tables, one store:
  - eigen_user: registered users (verified-clinician free tier). Registration is upsert-on-email and
    issues a bearer token (sha256 stored, raw returned ONCE). NPI verification (US) is a structural
    lookup against the public CMS registry — a computable fact, not a semantic judgment (Rule 18).
  - eigen_feedback: per-answer user feedback keyed to the SAME W1–W9 warrant taxonomy the eval and
    auditor use (docs/specs/answer-warrant-contract.md) — one contract, three uses. This is the
    accumulating ground-truth signal that eventually adjudicates the eval judges.

ALPHA HONESTY: there is no email-verification loop yet (no mail infra), so possession of an email is
self-declared; the token only proves "same registrant". Fine for a no-PHI research tool; add magic-link
verification before anything sensitive rides on identity.

Best-effort like SessionStore: a persistence failure must never break an answer.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import urllib.parse
import urllib.request
import uuid
from typing import Any

_DDL = """
CREATE TABLE IF NOT EXISTS eigen_user (
    id            TEXT PRIMARY KEY,
    vertical      TEXT NOT NULL,
    email         TEXT NOT NULL,
    name          TEXT NOT NULL,
    profession    TEXT NOT NULL DEFAULT '',
    country       TEXT NOT NULL DEFAULT '',
    npi           TEXT,
    npi_verified  BOOLEAN NOT NULL DEFAULT FALSE,
    token_hash    TEXT NOT NULL,
    disclaimer_ack_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (vertical, email)
);
CREATE INDEX IF NOT EXISTS idx_nu_token ON eigen_user (token_hash);
-- PASSWORD sign-in (roster's model): PBKDF2-HMAC-SHA256 hash + salt, set at registration, verified at login.
ALTER TABLE eigen_user ADD COLUMN IF NOT EXISTS pw_hash TEXT;
ALTER TABLE eigen_user ADD COLUMN IF NOT EXISTS pw_salt TEXT;
CREATE TABLE IF NOT EXISTS eigen_feedback (
    id          TEXT PRIMARY KEY,
    vertical    TEXT NOT NULL,
    user_id     TEXT,
    user_email  TEXT,
    session_id  TEXT NOT NULL DEFAULT '',
    turn_index  INTEGER NOT NULL DEFAULT 0,
    verdict     TEXT NOT NULL,
    modes       JSONB NOT NULL DEFAULT '[]'::jsonb,
    claim_index INTEGER,
    note        TEXT NOT NULL DEFAULT '',
    question    TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_nfb_vertical_created ON eigen_feedback (vertical, created_at DESC);
-- PER-DEVICE TOKENS: multiple active tokens per user, so signing in on a second browser/device no
-- longer orphans the first (the old single token_hash column rotated on every register). The legacy
-- column keeps being written and checked as a FALLBACK so pre-existing sessions stay valid.
CREATE TABLE IF NOT EXISTS eigen_user_token (
    token_hash  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_nut_user ON eigen_user_token (user_id, created_at DESC);
CREATE TABLE IF NOT EXISTS eigen_user_pref (
    user_id     TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, key)
);
"""

_MAX_TOKENS_PER_USER = 10   # prune oldest beyond this (a lost device's token eventually ages out)

_NPI_API = "https://npiregistry.cms.hhs.gov/api/?version=2.1&number="


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


import hmac as _hmac   # noqa: E402

_PBKDF2_ITER = 240_000


def hash_password(password: str) -> tuple[str, str]:
    """(pw_hash_hex, pw_salt_hex) via PBKDF2-HMAC-SHA256, 240k iterations, 16-byte random salt."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITER)
    return dk.hex(), salt.hex()


def verify_password(password: str, pw_hash_hex: str, pw_salt_hex: str) -> bool:
    """Constant-time verify. Always runs the KDF (the caller passes a dummy salt for unknown users)."""
    try:
        salt = bytes.fromhex(pw_salt_hex or "00" * 16)
    except ValueError:
        salt = b"\x00" * 16
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITER)
    return _hmac.compare_digest(dk.hex(), pw_hash_hex or "")


async def verify_npi(npi: str) -> bool:
    """Structural verification against the public CMS NPI registry: the number exists AND is an
    individual provider (NPI-1). A registry lookup is a computable fact (Rule 18). Fail-safe:
    any error/timeout → False (registration still succeeds, just unverified — retryable later)."""
    npi = (npi or "").strip()
    if not (npi.isdigit() and len(npi) == 10):
        return False

    def _fetch() -> bool:
        with urllib.request.urlopen(_NPI_API + urllib.parse.quote(npi), timeout=6) as r:
            data = json.loads(r.read().decode())
        for res in data.get("results") or []:
            if str(res.get("number")) == npi and res.get("enumeration_type") == "NPI-1":
                return True
        return False

    try:
        return await asyncio.to_thread(_fetch)
    except Exception:   # noqa: BLE001 — verification is best-effort, never blocks registration
        return False


class AccountStore:
    """Async Postgres store for users + feedback, vertical-scoped like SessionStore."""

    def __init__(self, dsn: str, *, vertical: str):
        self._dsn = dsn
        self._vertical = vertical
        self._pool = None
        self._ready = False

    async def _get_pool(self):
        if self._pool is None:
            import asyncpg
            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)
        return self._pool

    async def _ensure(self) -> None:
        if self._ready:
            return
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(_DDL)
        self._ready = True

    async def email_exists(self, email: str) -> bool:
        await self._ensure()
        async with (await self._get_pool()).acquire() as conn:
            return bool(await conn.fetchval("SELECT 1 FROM eigen_user WHERE vertical=$1 AND email=$2",
                                            self._vertical, email.lower().strip()))

    async def register(self, *, email: str, name: str, profession: str = "", country: str = "",
                       npi: str = "", npi_verified: bool = False,
                       disclaimer_ack: bool = False, pw_hash: str = "", pw_salt: str = "") -> tuple[dict[str, Any], str]:
        """Upsert-on-email; rotates the token every call (re-registering re-claims the account —
        acceptable at alpha, see module docstring). Returns (public user dict, RAW token — shown once)."""
        await self._ensure()
        pool = await self._get_pool()
        token = secrets.token_urlsafe(32)
        uid = uuid.uuid4().hex
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO eigen_user (id, vertical, email, name, profession, country, npi,
                                            npi_verified, token_hash, disclaimer_ack_at, pw_hash, pw_salt)
                   VALUES ($1,$2,$3,$4,$5,$6,NULLIF($7,''),$8,$9, CASE WHEN $10 THEN now() END,
                           NULLIF($11,''), NULLIF($12,''))
                   ON CONFLICT (vertical, email) DO UPDATE SET
                     name=EXCLUDED.name, profession=EXCLUDED.profession, country=EXCLUDED.country,
                     npi=COALESCE(EXCLUDED.npi, eigen_user.npi),
                     npi_verified=(eigen_user.npi_verified OR EXCLUDED.npi_verified),
                     token_hash=EXCLUDED.token_hash,
                     disclaimer_ack_at=COALESCE(eigen_user.disclaimer_ack_at, EXCLUDED.disclaimer_ack_at),
                     pw_hash=COALESCE(EXCLUDED.pw_hash, eigen_user.pw_hash),
                     pw_salt=COALESCE(EXCLUDED.pw_salt, eigen_user.pw_salt),
                     last_seen=now()
                   RETURNING id, email, name, profession, country, npi_verified, created_at""",
                uid, self._vertical, email.lower().strip(), name.strip(), profession.strip(),
                country.strip(), npi.strip(), npi_verified, _hash(token), disclaimer_ack, pw_hash, pw_salt)
        # PER-DEVICE: this registration's token is ADDED to the user's active set (the legacy
        # column above still rotates for back-compat, but auth checks this table first — so the
        # previous device's token, if it's in the table, keeps working).
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO eigen_user_token (token_hash, user_id) VALUES ($1,$2) "
                "ON CONFLICT DO NOTHING", _hash(token), row["id"])
            await conn.execute(
                """DELETE FROM eigen_user_token WHERE user_id=$1 AND token_hash NOT IN (
                     SELECT token_hash FROM eigen_user_token WHERE user_id=$1
                     ORDER BY created_at DESC LIMIT $2)""", row["id"], _MAX_TOKENS_PER_USER)
        user = {"id": row["id"], "email": row["email"], "name": row["name"],
                "profession": row["profession"], "country": row["country"],
                "verified": row["npi_verified"]}
        return user, token

    async def login(self, *, email: str, password: str) -> tuple[dict[str, Any], str] | None:
        """Verify email + password (constant time) and issue a new per-device token. None on bad
        credentials or on an account without a password (a token-only legacy registrant)."""
        await self._ensure()
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, email, name, profession, country, npi_verified, pw_hash, pw_salt
                   FROM eigen_user WHERE vertical=$1 AND email=$2""", self._vertical, email.lower().strip())
        ok = verify_password(password, (row["pw_hash"] if row else "") or "", (row["pw_salt"] if row else "") or "")
        if not row or not row["pw_hash"] or not ok:
            return None
        token = secrets.token_urlsafe(32)
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO eigen_user_token (token_hash, user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", _hash(token), row["id"])
            await conn.execute(
                """DELETE FROM eigen_user_token WHERE user_id=$1 AND token_hash NOT IN (
                     SELECT token_hash FROM eigen_user_token WHERE user_id=$1
                     ORDER BY created_at DESC LIMIT $2)""", row["id"], _MAX_TOKENS_PER_USER)
            await conn.execute("UPDATE eigen_user SET last_seen=now() WHERE id=$1", row["id"])
        user = {"id": row["id"], "email": row["email"], "name": row["name"], "profession": row["profession"],
                "country": row["country"], "verified": row["npi_verified"]}
        return user, token

    async def logout(self, token: str) -> None:
        if not token:
            return
        await self._ensure()
        h = _hash(token)
        async with (await self._get_pool()).acquire() as conn:
            await conn.execute("DELETE FROM eigen_user_token WHERE token_hash=$1", h)
            await conn.execute("UPDATE eigen_user SET token_hash='' WHERE token_hash=$1", h)

    async def user_by_token(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        await self._ensure()
        pool = await self._get_pool()
        h = _hash(token)
        async with pool.acquire() as conn:
            # per-device table first; legacy single-column hash as fallback (pre-existing sessions)
            row = await conn.fetchrow(
                """SELECT u.id, u.email, u.name, u.profession, u.country, u.npi_verified
                   FROM eigen_user_token t JOIN eigen_user u ON u.id = t.user_id
                   WHERE t.token_hash=$2 AND u.vertical=$1""", self._vertical, h)
            if row:
                await conn.execute(
                    "UPDATE eigen_user_token SET last_seen=now() WHERE token_hash=$1", h)
                await conn.execute("UPDATE eigen_user SET last_seen=now() WHERE id=$1", row["id"])
            else:
                row = await conn.fetchrow(
                    """UPDATE eigen_user SET last_seen=now()
                       WHERE vertical=$1 AND token_hash=$2
                       RETURNING id, email, name, profession, country, npi_verified""",
                    self._vertical, h)
        if not row:
            return None
        return {"id": row["id"], "email": row["email"], "name": row["name"],
                "profession": row["profession"], "country": row["country"],
                "verified": row["npi_verified"]}

    async def add_feedback(self, *, user: dict | None, session_id: str, turn_index: int,
                           verdict: str, modes: list[str], claim_index: int | None,
                           note: str, question: str) -> str:
        await self._ensure()
        pool = await self._get_pool()
        fid = uuid.uuid4().hex
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO eigen_feedback (id, vertical, user_id, user_email, session_id,
                                                turn_index, verdict, modes, claim_index, note, question)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11)""",
                fid, self._vertical, (user or {}).get("id"), (user or {}).get("email"),
                session_id[:64], turn_index, verdict, json.dumps(modes), claim_index,
                note[:2000], question[:1000])
        return fid

    async def feedback_summary(self, *, limit: int = 25) -> dict[str, Any]:
        """The accumulating signal, aggregated: totals, per-verdict, per-W-mode, per-day, recent rows.
        This is what 'watch what feedback is building up over time' reads."""
        await self._ensure()
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            total = await conn.fetchval(
                "SELECT count(*) FROM eigen_feedback WHERE vertical=$1", self._vertical)
            by_verdict = {r["verdict"]: r["n"] for r in await conn.fetch(
                "SELECT verdict, count(*) n FROM eigen_feedback WHERE vertical=$1 GROUP BY 1",
                self._vertical)}
            by_mode = {r["mode"]: r["n"] for r in await conn.fetch(
                """SELECT jsonb_array_elements_text(modes) AS mode, count(*) n
                   FROM eigen_feedback WHERE vertical=$1 GROUP BY 1 ORDER BY 2 DESC""",
                self._vertical)}
            by_day = [{"day": r["day"].isoformat(), "n": r["n"]} for r in await conn.fetch(
                """SELECT created_at::date AS day, count(*) n FROM eigen_feedback
                   WHERE vertical=$1 GROUP BY 1 ORDER BY 1 DESC LIMIT 30""", self._vertical)]
            recent = [dict(r) for r in await conn.fetch(
                """SELECT id, user_email, session_id, turn_index, verdict, modes::text AS modes,
                          claim_index, note, question, created_at
                   FROM eigen_feedback WHERE vertical=$1
                   ORDER BY created_at DESC LIMIT $2""", self._vertical, limit)]
        for r in recent:
            r["modes"] = json.loads(r["modes"] or "[]")
            r["created_at"] = r["created_at"].isoformat()
        n_users = None
        async with (await self._get_pool()).acquire() as conn:
            n_users = await conn.fetchval(
                "SELECT count(*) FROM eigen_user WHERE vertical=$1", self._vertical)
            n_verified = await conn.fetchval(
                "SELECT count(*) FROM eigen_user WHERE vertical=$1 AND npi_verified", self._vertical)
        return {"total": total, "by_verdict": by_verdict, "by_mode": by_mode,
                "by_day": by_day, "recent": recent,
                "users": {"registered": n_users, "npi_verified": n_verified}}

    async def first_user_email(self) -> str:
        """The earliest-registered account: the owner, when no admin list is configured."""
        await self._ensure()
        async with (await self._get_pool()).acquire() as conn:
            return (await conn.fetchval(
                "SELECT email FROM eigen_user WHERE vertical=$1 ORDER BY created_at ASC LIMIT 1",
                self._vertical) or "")

    async def accounts_overview(self, *, limit: int = 500) -> list[dict]:
        """Who has registered and what each has DONE — counts only, never what they searched for.

        The activity numbers are deliberately bare integers. A count answers "is anyone using this"
        without turning an admin screen into a log of other people's questions, which is what the
        query text would be. PII either way, so the caller gates access.
        """
        await self._ensure()
        async with (await self._get_pool()).acquire() as conn:
            # the history and map tables are optional: a deployment without Startup Search has neither
            for ddl in ("CREATE TABLE IF NOT EXISTS eigen_search_history (user_id text NOT NULL, "
                        "mode text NOT NULL, fingerprint text NOT NULL, title text NOT NULL DEFAULT '', "
                        "query jsonb NOT NULL DEFAULT '{}'::jsonb, hits int NOT NULL DEFAULT 0, "
                        "runs int NOT NULL DEFAULT 1, last_at timestamptz NOT NULL DEFAULT now(), "
                        "PRIMARY KEY (user_id, mode, fingerprint))",):
                await conn.execute(ddl)
            # Each activity count sits behind a feature that may not be installed. A deployment
            # without Startup Search has no map table; one without Voices has no favourites. A count
            # we cannot take is reported as None rather than failing the whole screen.
            counts = {
                "searches": "(SELECT count(*) FROM eigen_search_history h WHERE h.user_id = u.id)",
                "runs": "(SELECT coalesce(sum(h.runs), 0) FROM eigen_search_history h WHERE h.user_id = u.id)",
                "last_search": "(SELECT max(h.last_at) FROM eigen_search_history h WHERE h.user_id = u.id)",
                "maps": "(SELECT count(*) FROM su_map m WHERE m.owner_id = u.id)",
                "kept": "(SELECT count(*) FROM vo_favorite f WHERE f.user_id = u.id)",
                "shares": "(SELECT count(*) FROM eigen_share s WHERE s.owner_id = u.id)",
            }
            usable = {}
            for name, expr in counts.items():
                try:
                    await conn.fetchval(f"SELECT {expr} FROM eigen_user u WHERE false")
                    usable[name] = expr
                except Exception:      # noqa: BLE001 — the feature behind it is simply not installed
                    usable[name] = None
            cols = ", ".join(f"{e} AS {n}" for n, e in usable.items() if e)
            rows = await conn.fetch(
                f"""SELECT u.id, u.name, u.email, u.created_at, u.last_seen,
                           (u.pw_hash IS NOT NULL) AS has_password{(", " + cols) if cols else ""}
                    FROM eigen_user u WHERE u.vertical=$1 ORDER BY u.created_at DESC LIMIT $2""",
                self._vertical, int(max(1, min(limit, 5000))))
        out = []
        for r in rows:
            d = dict(r)
            for k in ("created_at", "last_seen", "last_search"):
                if d.get(k) is not None:
                    d[k] = d[k].isoformat()
            out.append(d)
        return out

    async def list_users(self, *, limit: int = 500) -> list[dict]:
        """All registered users (newest first) — name, email, profession, country, NPI-verified,
        registered + last-seen timestamps. Admin-only (PII); the caller gates access."""
        await self._ensure()
        async with (await self._get_pool()).acquire() as conn:
            rows = await conn.fetch(
                """SELECT name, email, profession, country, npi_verified,
                          created_at, last_seen
                   FROM eigen_user WHERE vertical=$1 ORDER BY created_at DESC LIMIT $2""",
                self._vertical, int(limit))
        out = []
        for r in rows:
            d = dict(r)
            for k in ("created_at", "last_seen"):
                if d.get(k) is not None:
                    d[k] = d[k].isoformat()
            out.append(d)
        return out

    # ---- per-user preferences (Eigen IN D-7: the server-authoritative profile substrate) ----

    async def get_pref(self, user_id: str, key: str) -> str:
        await self._ensure()
        async with (await self._get_pool()).acquire() as conn:
            v = await conn.fetchval(
                "SELECT value FROM eigen_user_pref WHERE user_id=$1 AND key=$2", user_id, key)
        return v or ""

    async def set_pref(self, user_id: str, key: str, value: str) -> None:
        await self._ensure()
        async with (await self._get_pool()).acquire() as conn:
            await conn.execute(
                """INSERT INTO eigen_user_pref (user_id, key, value) VALUES ($1,$2,$3)
                   ON CONFLICT (user_id, key) DO UPDATE SET value=EXCLUDED.value,
                   updated_at=now()""", user_id, key[:64], (value or "")[:200])
