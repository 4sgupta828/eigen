"""DeepDive routes.

Everything here is FREE: resolution is three indexed reads, assembly reads rows we already hold. No
route in this file spends a model call or a web call — the paid legs (deeper own-site crawl, then the
web read) come later behind a projection and a max_usd gate, per docs/specs/deepdive.md §4.6.

The mode is flag-gated (EIGEN_DEEPDIVE). OFF is a true no-op: no routes, no tables touched.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from . import store as dstore
from .assemble import build
from .resolve import resolve


def deepdive_enabled() -> bool:
    return os.environ.get("EIGEN_DEEPDIVE", "").lower() in ("1", "true", "yes", "on")


class DiveIn(BaseModel):
    q: str = ""                     # a name, a domain, or a company id
    company_id: str = ""            # set when the caller already picked from candidates
    refresh: bool = False           # write a new revision instead of returning the stored one


def build_router(pool_of, su_store, *, user_of=None) -> APIRouter:
    r = APIRouter()

    async def _owner(token: str) -> str:
        if not user_of:
            return ""
        u = await user_of(token)
        return (u or {}).get("id") or ""

    @r.post("/deepdive/resolve")
    async def dd_resolve(body: DiveIn):
        """Which company does this name mean? Ambiguous is an answer, not a failure."""
        return await resolve(await pool_of(), body.q)

    @r.post("/deepdive")
    async def dd_dive(body: DiveIn, authorization: str = Header(default="")):
        cid = (body.company_id or "").strip().lower()
        if not cid:
            res = await resolve(await pool_of(), body.q)
            if res["status"] != "resolved":
                # A refusal carries the candidates so the caller can pick — it never guesses.
                return {"status": res["status"], "reason": res.get("reason", ""),
                        "candidates": res["candidates"]}
            cid = res["company"]["id"]

        pool = await pool_of()
        if not body.refresh:
            held = await dstore.get(pool, company_id=cid)
            if held:
                return {"status": "ok", "cached": True, "dossier": held}

        c = await su_store.company(cid)
        if not c:
            raise HTTPException(status_code=404, detail="we hold no company with that id")
        pages = await su_store.pages(cid)
        doss = build(c, pages)
        meta = await dstore.save(pool, doss, owner_id=await _owner(authorization),
                                 reason="refresh" if body.refresh else "initial")
        return {"status": "ok", "cached": False, "dossier": {**doss, **meta}}

    @r.get("/deepdive/{company_id}")
    async def dd_get(company_id: str):
        d = await dstore.get(await pool_of(), company_id=company_id.lower())
        if not d:
            raise HTTPException(status_code=404, detail="no dossier for that company yet")
        return {"status": "ok", "dossier": d}

    @r.get("/deepdive/share/{token}")
    async def dd_share(token: str):
        d = await dstore.get(await pool_of(), share_token=token)
        if not d:
            raise HTTPException(status_code=404, detail="no such dossier")
        d.pop("share_token", None)
        return {"status": "ok", "dossier": d}

    @r.get("/deepdives")
    async def dd_recent(limit: int = 50):
        return {"dossiers": await dstore.recent(await pool_of(), limit=min(200, max(1, limit)))}

    return r
