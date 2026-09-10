"""Investor Search endpoints (docs/specs/investors.md §6). Step 0: evaluate, coverage, dossier, admin jobs.

`POST /investors/compile` (brief → contract) is the one endpoint that costs a model call, and it lands with the
UI in Step 1. Everything mounted here reads rows we already hold and spends nothing.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from eigen_kernel.facets import Contract, evaluate, validate_contract

from . import compile as compile_mod
from . import pipeline
from .schema import KIND, REGISTER, SCHEMA, WEIGHTS, labels
from .store import InvestorStore


def investor_search_enabled() -> bool:
    return os.environ.get("EIGEN_INVESTOR_SEARCH", "").strip() not in ("", "0", "false", "no")


class CompileIn(BaseModel):
    text: str
    limit: int = 60


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


def build_router(store: InvestorStore, *, dsn: str, admin_token: str = "", embed=None, llm_json=None) -> APIRouter:
    r = APIRouter()
    # Compiling the same brief twice must not cost twice. Keyed by the brief text; bounded so a long session
    # cannot grow it without limit.
    _compiled: dict = {}

    def _admin(tok: str) -> None:
        if not admin_token or tok != admin_token:
            raise HTTPException(status_code=403, detail="admin token required")

    @r.get("/investors/labels")
    async def investor_labels() -> dict:
        return labels()

    @r.post("/investors/compile")
    async def compile_brief(body: CompileIn) -> dict:
        """A thesis brief → a contract the user can then edit chip by chip. One small model call, cached.

        The coverage table goes INTO the compiler, so a must on something the index barely knows is downgraded
        with a note rather than silently returning nothing — which, before the firm-site pass has run, is what
        every stated key would do.
        """
        text = (body.text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="a brief is required")
        key = f"{text}|{body.limit}"
        if key in _compiled:
            return {**_compiled[key], "cached": True}
        cov = await store.coverage()
        counts = await store.counts(KIND, {}, SCHEMA)
        c, notes = await compile_mod.compile_brief(
            llm_json, text, coverage=cov.get("known_rate") or {},
            value_counts={k: v for k, v in counts.items() if k != "_total"}, limit=body.limit)
        out = {"contract": c.to_dict(), "notes": notes, "labels": labels(),
               "compiled_by": "model" if llm_json else "words_only"}
        if len(_compiled) > 200:
            _compiled.clear()
        _compiled[key] = out
        return out

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
        # The two things the card is actually about, and neither survives a facet projection: WHO is there,
        # with the links their own page printed, and WHAT they have backed. Capped per firm so a search of
        # sixty firms does not ship a thousand portfolio rows.
        people = await conn.fetch("""
            SELECT firm_id, name, title, role, links FROM (
              SELECT p.*, row_number() OVER (PARTITION BY firm_id
                     ORDER BY CASE role WHEN 'founding_partner' THEN 0 WHEN 'managing_partner' THEN 1
                                        WHEN 'general_partner' THEN 2 WHEN 'founder' THEN 3
                                        WHEN 'partner' THEN 4 WHEN 'chief' THEN 5 WHEN 'principal' THEN 6
                                        WHEN 'venture_partner' THEN 7 ELSE 9 END, name) rn
              FROM iv_person p WHERE p.firm_id = ANY($1)) t WHERE rn <= 6""", ids)
        edges = await conn.fetch("""
            SELECT firm_id, company_id, company_name, company_site, basis, role FROM (
              SELECT e.*, row_number() OVER (PARTITION BY firm_id
                     ORDER BY (e.basis = 'press_round') DESC, e.event_date DESC NULLS LAST, e.company_name) rn
              FROM iv_edge e WHERE e.firm_id = ANY($1)) t WHERE rn <= 8""", ids)
    out = {}
    for x in rows:
        d = dict(x)
        d["iapd"] = f"https://adviserinfo.sec.gov/firm/summary/{d['crd']}" if d["crd"] else ""
        d["people"], d["portfolio_sample"] = [], []
        out[d["id"]] = d
    for p in people:
        row = out.get(p["firm_id"])
        if row is not None:
            links = p["links"] if isinstance(p["links"], dict) else _loads(p["links"])
            row["people"].append({"name": p["name"], "title": p["title"], "role": p["role"], "links": links})
    for e in edges:
        row = out.get(e["firm_id"])
        if row is not None:
            row["portfolio_sample"].append({"id": e["company_id"], "name": e["company_name"] or e["company_id"],
                                            "site": e["company_site"], "basis": e["basis"]})
    return out


def _loads(v):
    import json
    try:
        return json.loads(v or "{}")
    except Exception:      # noqa: BLE001
        return {}


def _matched_register(row: dict) -> dict:
    """Which register carried each facet this row has — the card's "matched seed: the firm says so" line.

    One control can match a stated key or its observed twin (§4); the filter does not care which, and the card
    must, so the answer travels with the row rather than being re-derived in the UI.
    """
    return {k: REGISTER.get(k, "") for k in (row.get("facets") or {})}
