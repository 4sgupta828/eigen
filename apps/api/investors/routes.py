"""Investor Search endpoints (docs/specs/investors.md §6). Step 0: evaluate, coverage, dossier, admin jobs.

`POST /investors/compile` (brief → contract) is the one endpoint that costs a model call, and it lands with the
UI in Step 1. Everything mounted here reads rows we already hold and spends nothing.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from eigen_kernel.facets import Contract, evaluate, validate_contract

from . import pipeline
from .schema import KIND, REGISTER, SCHEMA, WEIGHTS, labels
from .store import InvestorStore


def investor_search_enabled() -> bool:
    return os.environ.get("EIGEN_INVESTOR_SEARCH", "").strip() not in ("", "0", "false", "no")


class EvaluateIn(BaseModel):
    contract: dict
    counts: bool = True


class JobIn(BaseModel):
    kind: str
    params: dict = {}


class _Bound:
    """The kernel evaluator's store view: exclusions and the embedder bound in, so `evaluate` stays generic."""

    degraded: str = ""
    legs: dict = {}

    def __init__(self, store: InvestorStore, exclude: dict, embed):
        self._s, self._x, self._e = store, exclude, embed

    async def enumerate(self, kind, must, *, cap=400):
        return await self._s.enumerate(kind, must, cap=cap, exclude=self._x)

    async def semantic(self, kind, text, must, *, cap=400):
        """The kernel asks one store for "the words leg"; here that leg is HYBRID.

        Vector similarity and Postgres full text are fused by reciprocal rank (`store.hybrid`), so "climate
        infrastructure funds in Europe" is answered by the embedding and "8VC" by the lexical index, and
        neither query has to know which one it needed. If both legs come back empty the musts still filter —
        a search that cannot rank is degraded, never broken.
        """
        try:
            rows, diag = await self._s.hybrid(kind, text, must, cap=cap, exclude=self._x, embed=self._e)
        except Exception as e:          # noqa: BLE001 — retrieval trouble must never 500 a search
            rows, diag = [], {"degraded": f"search degraded ({type(e).__name__}): filters only"}
        self.legs = diag
        if diag.get("degraded"):
            self.degraded = diag["degraded"]
        return rows or await self._s.enumerate(kind, must, cap=cap, exclude=self._x)

    async def counts(self, kind, must, schema, *, depth=None):
        return await self._s.counts(kind, must, schema, depth=depth, exclude=self._x)

    async def noise_floor(self, kind, text):
        return None


def build_router(store: InvestorStore, *, dsn: str, admin_token: str = "", embed=None) -> APIRouter:
    r = APIRouter()

    def _admin(tok: str) -> None:
        if not admin_token or tok != admin_token:
            raise HTTPException(status_code=403, detail="admin token required")

    @r.get("/investors/labels")
    async def investor_labels() -> dict:
        return labels()

    @r.post("/investors/evaluate")
    async def evaluate_contract(body: EvaluateIn) -> dict:
        c = Contract.from_dict({**body.contract, "kind": KIND})
        errs = validate_contract(c, SCHEMA)
        if errs:
            raise HTTPException(status_code=400, detail="; ".join(errs))
        exclude = dict((c.scope or {}).get("exclude") or {})
        bound = _Bound(store, exclude, embed)
        out = await evaluate(c, bound, SCHEMA, WEIGHTS,
                             depth=({"counts": False} if not body.counts else None))
        if bound.degraded:
            out["coverage"]["degraded"] = bound.degraded
        if bound.legs:
            out["coverage"]["retrieval"] = bound.legs      # {legs: {semantic: n, keyword: n}, both: n}
        rows = out["rows"]
        hydrated = await _hydrate(store, [x["id"] for x in rows])
        for i, x in enumerate(rows):
            x["firm"] = hydrated.get(x["id"], {})
            x["rank"] = i + 1
            x["matched_register"] = _matched_register(x)
            if x.get("_found_by"):
                x["found_by"] = x.pop("_found_by")         # which retrieval leg surfaced this firm
        out["coverage"]["matched"] = (out.get("counts") or {}).pop("_total", None)
        out["labels"] = labels()
        return out

    @r.get("/investors/coverage")
    async def coverage() -> dict:
        cov = await store.coverage()
        cov["registers"] = dict(REGISTER)
        # The honest caveat that belongs next to every count: this register is American.
        cov["caveats"] = ["Form ADV is a US register: a firm with no US adviser registration has no filed AUM "
                          "here, which is a coverage fact and not a judgment about its size."]
        return cov

    @r.get("/investors/{firm_id}")
    async def firm(firm_id: str) -> dict:
        got = await store.firm(firm_id)
        if not got:
            raise HTTPException(status_code=404, detail="no such investor")
        got["labels"] = labels()
        return got

    # ------------------------------------------------------------------ admin
    @r.post("/admin/investors/jobs")
    async def start_job(body: JobIn, x_admin_token: str = Header(default="")) -> dict:
        _admin(x_admin_token)
        if body.kind not in pipeline.RUNNERS:
            raise HTTPException(status_code=400, detail=f"unknown job kind; try {sorted(pipeline.RUNNERS)}")
        jid = await pipeline.start_job(store, dsn, body.kind, body.params or {})
        return {"id": jid, "kind": body.kind, "status": "running"}

    @r.get("/admin/investors/jobs")
    async def jobs(x_admin_token: str = Header(default="")) -> dict:
        _admin(x_admin_token)
        return {"jobs": await pipeline.JOBS.recent(store, limit=20)}

    @r.post("/admin/investors/jobs/{job_id}/cancel")
    async def cancel_job(job_id: int, x_admin_token: str = Header(default="")) -> dict:
        _admin(x_admin_token)
        ok = await pipeline.JOBS.cancel(store, job_id)
        return {"id": job_id, "cancelling": ok}

    return r


async def _hydrate(store: InvestorStore, ids: list[str]) -> dict:
    """What a card needs beyond its facets: name, site, HQ, and the fund line."""
    if not ids:
        return {}
    pool = await store.pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT v.id, v.name, v.site, v.domain, v.hq_city, v.hq_state, v.hq_country, v.crd, v.kind, v.sources,
                   (SELECT count(*) FROM iv_fund f WHERE f.firm_id = v.id AND NOT f.is_spv) AS funds,
                   (SELECT count(DISTINCT e.company_id) FROM iv_edge e WHERE e.firm_id = v.id) AS portfolio
            FROM iv_firm v WHERE v.id = ANY($1)""", ids)
    out = {}
    for x in rows:
        d = dict(x)
        d["iapd"] = f"https://adviserinfo.sec.gov/firm/summary/{d['crd']}" if d["crd"] else ""
        out[d["id"]] = d
    return out


def _matched_register(row: dict) -> dict:
    """Which register carried each facet this row has — the card's "matched seed: the firm says so" line.

    One control can match a stated key or its observed twin (§4); the filter does not care which, and the card
    must, so the answer travels with the row rather than being re-derived in the UI.
    """
    return {k: REGISTER.get(k, "") for k in (row.get("facets") or {})}
