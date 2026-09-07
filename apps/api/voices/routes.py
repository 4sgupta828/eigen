"""Voices routes — the mode's API.

Public: search moments, and fetch the moments bound to one company (the "from the founders" strip on
a startup card). Admin: ingest and bind, both free of model spend.

The mode is flag-gated (EIGEN_VOICES). OFF is a true no-op: no routes, no tables touched.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from . import favorites, people
from .ingest import bind_guests, ingest_voices, mark_boilerplate, refresh_guests
from .search import VOICE_SOURCE_KEYS, build_query, dedupe, moment
from .summarize import MAX_INPUT_CHARS, cached, store, summarize


def voices_enabled() -> bool:
    return os.environ.get("EIGEN_VOICES", "").lower() in ("1", "true", "yes", "on")


class SearchIn(BaseModel):
    q: str = ""
    kinds: list[str] = []
    company_id: str = ""
    speaker: str = ""
    limit: int = 30
    days: int = 0                 # browse window: 7, 30, 90 … 0 means no window
    # "recent" (publication date), "watched" (the platform's own view count, video only) or
    # "guest" (episodes with a named guest — the ordering that works where no view count exists)
    order: str = "recent"


class SummaryIn(BaseModel):
    id: str                       # "<document_id>::<block_id>" as a moment card carries it
    refresh: bool = False


class FavoriteIn(BaseModel):
    moment: dict = {}             # the card as rendered, so a saved item survives the feed rolling
    id: str = ""                  # or just the id, when removing
    note: str = ""


class JobIn(BaseModel):
    kind: str = "ingest"
    limit: int = 60


def _window(days: int) -> tuple[str, bool]:
    """The ISO date a browse window starts at, or "" for no window."""
    days = int(days or 0)
    if days <= 0:
        return "", False
    from datetime import date, timedelta
    return (date.today() - timedelta(days=min(days, 3650))).isoformat(), False


def build_router(pool_of, *, manifest=None, pg_source_of=None, tenant_id: str = "default",
                 admin_token: str = "", llm_json=None, user_of=None) -> APIRouter:
    router = APIRouter()

    async def _user(token: str) -> str:
        """The signed-in account id, or "" — favourites are per account, never per browser."""
        if user_of is None or not token:
            return ""
        try:
            u = await user_of(token)
        except Exception:      # noqa: BLE001 — a broken session must not break a search
            return ""
        return str((u or {}).get("id") or "") if isinstance(u, dict) else str(getattr(u, "id", "") or "")

    async def _rows(sql: str, params: list) -> list[dict]:
        pool = await pool_of()
        async with pool.acquire() as conn:
            out = await conn.fetch(sql, *params)
        import json

        def shape(rec) -> dict:
            d = dict(rec)
            d.pop("created_at", None)      # an internal column, never part of a card
            if "facets" in d:      # not every query selects facets (the coverage query does not)
                d["facets"] = json.loads(d["facets"]) if isinstance(d["facets"], str) else (d["facets"] or {})
            return d
        return [shape(r) for r in out]

    @router.post("/voices/search")
    async def voices_search(body: SearchIn, x_eigen_token: str = Header(default="")) -> dict:
        """Moments matching the question. Keyword-ranked, so it works with no embedding provider."""
        want = max(1, min(int(body.limit or 30), 60))
        since, widened = _window(body.days)
        # over-fetch, then dedupe: the ranking cannot know that five blocks are the same sidebar
        # A BROWSE shows one moment per piece: a feed of "what landed" should list distinct
        # episodes, not two chapters of the same one. A SEARCH may show two, because a second
        # passage from the same piece is often the better answer.
        browse = not body.q.strip()
        sql, params = build_query(q=body.q, kinds=tuple(body.kinds), company_id=body.company_id,
                                  speaker=body.speaker, limit=want * 6, since=since,
                                  order=body.order, per_document=browse)
        rows = await _rows(sql, params)
        # A window that returns almost nothing is worse than a wider one: widen rather than show an
        # empty week, and say which window the reader is actually looking at.
        if since and len(rows) < 6:
            since, widened = "", True
            sql, params = build_query(q=body.q, kinds=tuple(body.kinds), company_id=body.company_id,
                                      speaker=body.speaker, limit=want * 6, order=body.order,
                                      per_document=browse)
            rows = await _rows(sql, params)
        moments = dedupe([moment(r) for r in rows], limit=want,
                         per_document=1 if browse else 2)
        # who is speaking, and where to find them — resolved once for the whole page
        pool = await pool_of()
        async with pool.acquire() as conn:
            resolved = await people.links_for(conn, [m.get("speaker") or "" for m in moments])
        people.decorate(moments, resolved)
        uid = await _user(x_eigen_token)
        if uid:
            async with pool.acquire() as conn:
                kept = set(await favorites.ids(conn, uid))
            for m in moments:
                m["saved"] = m["id"] in kept
        return {
            "moments": moments,
            "counts": {
                "total": len(moments),
                "quotable": sum(1 for m in moments if m["quotable"]),
                "pointers": sum(1 for m in moments if not m["quotable"]),
            },
            # Said plainly so the UI never has to guess: ranking is words-only until vectors exist.
            # Said plainly so the UI never has to guess what it is showing.
            "ranking": ("keyword" if body.q.strip() else
                        {"watched": "most watched", "guest": "interviews, newest first"}
                        .get(body.order, "newest first")),
            "window": {"days": 0 if not since else int(body.days), "widened": widened,
                       "since": since},
        }

    @router.get("/voices/company/{company_id}")
    async def voices_for_company(company_id: str, limit: int = 8) -> dict:
        """The 'from the founders' strip. Only fully-bound episodes appear — a guest whose company
        was not confirmed is searchable but never attached to that company's card."""
        sql, params = build_query(q="", company_id=company_id, limit=limit, per_document=True)
        return {"moments": [moment(r) for r in await _rows(sql, params)]}

    @router.get("/voices/favorites")
    async def voices_favorites(x_eigen_token: str = Header(default="")) -> dict:
        uid = await _user(x_eigen_token)
        if not uid:
            return {"moments": [], "signed_in": False}
        pool = await pool_of()
        async with pool.acquire() as conn:
            return {"moments": await favorites.listing(conn, uid), "signed_in": True}

    @router.post("/voices/favorites")
    async def voices_favorite_add(body: FavoriteIn, x_eigen_token: str = Header(default="")) -> dict:
        uid = await _user(x_eigen_token)
        if not uid:
            raise HTTPException(status_code=401, detail="sign in to keep a moment")
        m = body.moment or {}
        if not (m.get("id") or body.id):
            raise HTTPException(status_code=400, detail="a moment is required")
        pool = await pool_of()
        async with pool.acquire() as conn:
            return await favorites.add(conn, uid, m or {"id": body.id}, body.note)

    @router.delete("/voices/favorites/{moment_id:path}")
    async def voices_favorite_remove(moment_id: str, x_eigen_token: str = Header(default="")) -> dict:
        uid = await _user(x_eigen_token)
        if not uid:
            raise HTTPException(status_code=401, detail="sign in to keep a moment")
        pool = await pool_of()
        async with pool.acquire() as conn:
            return await favorites.remove(conn, uid, moment_id)

    @router.post("/voices/summary")
    async def voices_summary(body: SummaryIn) -> dict:
        """Summarise the whole piece behind a moment, for the expanded card.

        Lazy and cached by document: nothing is summarised until someone opens it, and the second
        reader pays nothing. When no model is available the summary is extractive and says so.
        """
        document_id = (body.id or "").split("::", 1)[0]
        if not document_id:
            raise HTTPException(status_code=400, detail="a moment id is required")
        pool = await pool_of()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT text, document_title, source_key, facets FROM rs_block "
                "WHERE document_id = $1 AND source_key = ANY($2) ORDER BY block_id", document_id,
                list(VOICE_SOURCE_KEYS))
            if not rows:
                raise HTTPException(status_code=404, detail="that piece is no longer in the corpus")
            import json as _json
            facets = rows[0]["facets"]
            facets = _json.loads(facets) if isinstance(facets, str) else (facets or {})
            is_chapter = (str(facets.get("source_kind") or "") == "chapter_pointer"
                          or rows[0]["source_key"] in ("show_notes", "youtube_chapters"))
            title = rows[0]["document_title"] or ""
            author = str(facets.get("author") or facets.get("guest") or "")
            text = "\n".join((r["text"] or "") for r in rows)

            hit = None if body.refresh else await cached(conn, document_id)
            if hit is None:
                hit = await summarize(title=title, author=author, text=text, is_chapter=is_chapter,
                                      llm_json=llm_json)
                await store(conn, document_id, hit)
                hit = dict(hit, cached=False)
            else:
                hit = dict(hit, cached=True)
        # For an episode the chapter list IS the piece, so it is sent as text; for an essay the
        # readable body already rides in `sections`, and sending the raw dump too would only give the
        # panel a wall of text to fall back to.
        if is_chapter:
            hit["text"] = text[:MAX_INPUT_CHARS]
        hit["title"] = title
        return hit

    @router.get("/voices/sources")
    async def voices_sources() -> dict:
        """What the corpus actually holds, by show/publication — the honest coverage answer."""
        sql = ("SELECT facets->>'publication' AS name, source_key, count(*) AS blocks, "
               "count(DISTINCT document_id) AS items FROM rs_block "
               "WHERE source_key = ANY($1) AND facets->>'publication' IS NOT NULL "
               "GROUP BY 1, 2 ORDER BY items DESC LIMIT 60")
        rows = await _rows(sql, [list(VOICE_SOURCE_KEYS)])
        return {"sources": [{"name": r["name"], "kind": r["source_key"],
                             "items": r["items"], "blocks": r["blocks"]} for r in rows]}

    @router.post("/admin/voices/jobs")
    async def voices_job(body: JobIn, x_admin_token: str = Header(default="")) -> dict:
        """Ingest feeds or bind guests. Both are free of model spend; ingest writes keyword-only
        blocks when no embedder is configured."""
        want = admin_token or os.environ.get("EIGEN_ADMIN_TOKEN", "")
        if want and x_admin_token != want:
            raise HTTPException(status_code=401, detail="admin token required")
        if body.kind == "bind":
            return {"kind": "bind", "result": await bind_guests(await pool_of())}
        if body.kind == "refresh_guests":
            return {"kind": "refresh_guests", "result": await refresh_guests(await pool_of())}
        if body.kind == "mark_boilerplate":
            return {"kind": "mark_boilerplate", "result": await mark_boilerplate(await pool_of())}
        if body.kind == "ingest":
            if manifest is None or pg_source_of is None:
                raise HTTPException(status_code=503, detail="ingest not configured")
            res = await ingest_voices(manifest, await pg_source_of(), tenant_id=tenant_id,
                                      limit=body.limit)
            return {"kind": "ingest", "blocks": res}
        raise HTTPException(status_code=400, detail=f"unknown job kind {body.kind}")

    return router
