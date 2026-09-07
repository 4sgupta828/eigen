"""Recent searches, per account — so a line of enquiry can be picked up again.

Kept apart from shares on purpose. A SHARE is a public, frozen page you chose to publish; a HISTORY
entry is private, is never published, and stores the QUERY rather than the results — re-running it
against a corpus that has grown since is the point, not a problem.

Only signed-in searches are recorded. An anonymous reader's history lives in their own browser,
because writing a per-browser query log to the server would be collecting something nobody asked us
to keep.
"""
from __future__ import annotations

import json

MODES = ("voices", "startups")
KEEP_PER_MODE = 100        # a working memory, not an archive

DDL = """
CREATE TABLE IF NOT EXISTS eigen_search_history (
    user_id   text NOT NULL,
    mode      text NOT NULL,
    fingerprint text NOT NULL,
    title     text NOT NULL DEFAULT '',
    query     jsonb NOT NULL DEFAULT '{}'::jsonb,
    hits      int NOT NULL DEFAULT 0,
    runs      int NOT NULL DEFAULT 1,
    last_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, mode, fingerprint));
CREATE INDEX IF NOT EXISTS eigen_search_history_recent
    ON eigen_search_history (user_id, mode, last_at DESC);
"""


def fingerprint(query: dict) -> str:
    """One key per distinct search, so running the same thing twice moves it up rather than
    filling the list with duplicates."""
    return json.dumps(query or {}, sort_keys=True, separators=(",", ":"))[:800]


async def ensure(conn) -> None:
    await conn.execute(DDL)


async def record(conn, user_id: str, *, mode: str, title: str, query: dict, hits: int) -> None:
    """Best-effort: a history write must never break the search it is describing."""
    if not user_id or mode not in MODES:
        return
    await ensure(conn)
    await conn.execute(
        "INSERT INTO eigen_search_history (user_id, mode, fingerprint, title, query, hits) "
        "VALUES ($1,$2,$3,$4,$5::jsonb,$6) "
        "ON CONFLICT (user_id, mode, fingerprint) DO UPDATE "
        "SET last_at = now(), runs = eigen_search_history.runs + 1, hits = EXCLUDED.hits, "
        "    title = EXCLUDED.title",
        user_id, mode, fingerprint(query), (title or "")[:200], json.dumps(query or {}), int(hits))


async def listing(conn, user_id: str, *, mode: str = "", limit: int = 40) -> list[dict]:
    await ensure(conn)
    if not user_id:
        return []
    if mode:
        rows = await conn.fetch(
            "SELECT mode, title, query, hits, runs, last_at FROM eigen_search_history "
            "WHERE user_id = $1 AND mode = $2 ORDER BY last_at DESC LIMIT $3",
            user_id, mode, int(max(1, min(limit, KEEP_PER_MODE))))
    else:
        rows = await conn.fetch(
            "SELECT mode, title, query, hits, runs, last_at FROM eigen_search_history "
            "WHERE user_id = $1 ORDER BY last_at DESC LIMIT $2",
            user_id, int(max(1, min(limit, KEEP_PER_MODE))))
    out = []
    for r in rows:
        q = r["query"]
        out.append({"mode": r["mode"], "title": r["title"],
                    "query": json.loads(q) if isinstance(q, str) else (q or {}),
                    "hits": int(r["hits"] or 0), "runs": int(r["runs"] or 0),
                    "at": r["last_at"].isoformat() if r["last_at"] else ""})
    return out


async def clear(conn, user_id: str, *, mode: str = "") -> int:
    await ensure(conn)
    if not user_id:
        return 0
    sql = "DELETE FROM eigen_search_history WHERE user_id = $1" + (" AND mode = $2" if mode else "")
    res = await (conn.execute(sql, user_id, mode) if mode else conn.execute(sql, user_id))
    return int(str(res).rsplit(" ", 1)[-1]) if str(res).startswith("DELETE") else 0
