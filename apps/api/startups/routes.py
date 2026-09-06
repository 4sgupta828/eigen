"""Startup Search API (mounted behind `EIGEN_STARTUP_SEARCH`).

  POST /startups/compile   {text}                → {contract, notes}            (one cached DeepSeek call)
  POST /startups/evaluate  {contract}            → {rows, counts, coverage, contract, labels}   (no model call)
  GET  /startups/{id}                            → the company with every fact's evidence
  GET  /startups/coverage                        → index size, known-rate per key, sources, jobs
  POST /startups/lists · GET /startups/lists/{id}
  POST /admin/startups/jobs {kind, params}       → start an ingest job (X-Admin-Token)
  GET  /admin/startups/jobs                      → recent jobs and their progress
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from eigen_kernel.facets import Contract, evaluate, matches_must, validate_contract

from . import compile as compile_mod, pipeline
from .schema import KIND, SCHEMA, WEIGHTS, labels
from .store import StartupStore

_COMPILE_CACHE: dict[str, tuple[dict, list[str]]] = {}
_COUNTS_CACHE: dict = {}


async def index_counts(store: StartupStore) -> dict:
    """Index-wide per-key per-value counts (no musts), cached for 10 minutes — the compiler's reality check."""
    import time
    now = time.time()
    if _COUNTS_CACHE.get("at", 0) < now - 600:
        c = await store.counts(KIND, {}, SCHEMA)
        c.pop("_total", None)
        _COUNTS_CACHE.update({"at": now, "counts": c})
    return _COUNTS_CACHE["counts"]


def startup_search_enabled() -> bool:
    return os.environ.get("EIGEN_STARTUP_SEARCH", "").strip().lower() in ("1", "true", "on", "yes")


class CompileIn(BaseModel):
    text: str
    limit: int = 60


class EvaluateIn(BaseModel):
    contract: dict


class ListIn(BaseModel):
    name: str
    contract: dict
    rows: list = []


class JobIn(BaseModel):
    kind: str
    params: dict = {}


class RosterAtsIn(BaseModel):
    rows: list


class _Bound:
    """The kernel evaluator's store view: exclusions and the embedder bound in, so `evaluate` stays generic."""

    def __init__(self, store: StartupStore, exclude: dict, embed):
        self._s, self._x, self._e = store, exclude, embed

    async def enumerate(self, kind, must, *, cap=400):
        return await self._s.enumerate(kind, must, cap=cap, exclude=self._x)

    async def semantic(self, kind, text, must, *, cap=400):
        rows = await self._s.semantic(kind, text, must, cap=cap, exclude=self._x, embed=self._e) if self._e else []
        # no embedder, or nothing embedded yet → the words cannot rank, but the musts still filter: enumerate instead
        return rows or await self._s.enumerate(kind, must, cap=cap, exclude=self._x)

    async def counts(self, kind, must, schema, *, depth=None):
        return await self._s.counts(kind, must, schema, depth=depth, exclude=self._x)

    async def noise_floor(self, kind, text):
        return None


class MapIn(BaseModel):
    title: str = ""
    brief: str = ""
    contract: dict
    rows: list = []
    coverage: dict = {}


class MapReviseIn(BaseModel):
    contract: dict
    rows: list = []
    coverage: dict = {}
    reason: str = "navigated"
    title: str | None = None
    notes: str | None = None


async def _no_user(token: str):
    return None


def build_router(store: StartupStore, providers: pipeline.Providers, *, dsn: str, admin_token: str = "", user_of=None) -> APIRouter:
    r = APIRouter()
    user_of = user_of or _no_user

    def _admin(tok: str) -> None:
        if admin_token and tok != admin_token:
            raise HTTPException(status_code=401, detail="admin token required")

    async def _require_user(token: str) -> dict:
        u = await user_of(token)
        if not u:
            raise HTTPException(status_code=401, detail="sign in to save maps")
        return u

    async def _evaluate(c: Contract) -> dict:
        errs = validate_contract(c, SCHEMA)
        if errs:
            raise HTTPException(status_code=400, detail="; ".join(errs))
        exclude = dict((c.scope or {}).get("exclude") or {})
        out = await evaluate(c, _Bound(store, exclude, providers.embed), SCHEMA, WEIGHTS)
        rows = [x for x in out["rows"] if not _excluded(x, exclude)]
        hydrated = await store.companies_by_ids([x["id"] for x in rows])
        for i, x in enumerate(rows):
            x["company"] = hydrated.get(x["id"], {})
            x["rank"] = i + 1
        total = out["counts"].pop("_total", None)
        out["rows"] = rows
        out["coverage"]["matched"] = total
        out["coverage"]["index"] = await store.coverage()
        out["labels"] = labels()
        if not rows:
            ic = await index_counts(store)
            why = {}
            for key, vals in (c.must or {}).items():
                if isinstance(vals, dict):
                    why[key] = {"range": vals, "known": sum(n for v, n in ic.get(key, {}).items() if v != "unknown")}
                else:
                    why[key] = {v: ic.get(key, {}).get(v, 0) for v in vals}
            out["coverage"]["why_empty"] = why
        return out

    # ---- Startup Maps: a saved search is a durable, per-account artifact (contract + snapshot + revisions + share link)
    @r.post("/startups/maps")
    async def create_map(body: MapIn, x_eigen_token: str = Header(default="")) -> dict:
        u = await _require_user(x_eigen_token)
        c = Contract.from_dict(body.contract); c.kind = KIND
        errs = validate_contract(c, SCHEMA)
        if errs:
            raise HTTPException(status_code=400, detail="; ".join(errs))
        return await store.create_map(owner_id=u["id"], title=body.title, brief=body.brief, contract=c.to_dict(), rows=body.rows, coverage=body.coverage)

    @r.get("/startups/maps")
    async def my_maps(x_eigen_token: str = Header(default="")) -> dict:
        u = await _require_user(x_eigen_token)
        return {"maps": await store.list_maps(u["id"])}

    @r.get("/startups/maps/{map_id}")
    async def get_map(map_id: str, share: str = "", x_eigen_token: str = Header(default="")) -> dict:
        u = await user_of(x_eigen_token)
        m = await store.get_map(map_id, owner_id=(u or {}).get("id"), share_token=share or None)
        if not m:
            raise HTTPException(status_code=404, detail="no such map (or not yours — ask for its share link)")
        m["labels"] = labels()
        return m

    @r.post("/startups/maps/{map_id}/navigate")
    async def navigate_map(map_id: str, body: EvaluateIn, share: str = "", x_eigen_token: str = Header(default="")) -> dict:
        """Re-evaluate an edited contract for this map WITHOUT saving (the rail's Apply on a map)."""
        u = await user_of(x_eigen_token)
        m = await store.get_map(map_id, owner_id=(u or {}).get("id"), share_token=share or None)
        if not m:
            raise HTTPException(status_code=404, detail="no such map")
        c = Contract.from_dict(body.contract); c.kind = KIND
        out = await _evaluate(c)
        out["map"] = {"id": m["id"], "title": m["title"], "revision": m["revision"], "owner": m["owner"]}
        return out

    @r.post("/startups/maps/{map_id}/revise")
    async def revise_map(map_id: str, body: MapReviseIn, x_eigen_token: str = Header(default="")) -> dict:
        u = await _require_user(x_eigen_token)
        c = Contract.from_dict(body.contract); c.kind = KIND
        errs = validate_contract(c, SCHEMA)
        if errs:
            raise HTTPException(status_code=400, detail="; ".join(errs))
        res = await store.revise_map(map_id, owner_id=u["id"], contract=c.to_dict(), rows=body.rows, coverage=body.coverage, reason=body.reason, title=body.title, notes=body.notes)
        if not res:
            raise HTTPException(status_code=404, detail="no such map, or not yours")
        return res

    @r.delete("/startups/maps/{map_id}")
    async def delete_map(map_id: str, x_eigen_token: str = Header(default="")) -> dict:
        u = await _require_user(x_eigen_token)
        return {"deleted": await store.delete_map(map_id, owner_id=u["id"])}

    @r.post("/startups/compile")
    async def compile_brief(body: CompileIn) -> dict:
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="empty brief")
        key = hashlib.sha1(f"{text}|{body.limit}".encode()).hexdigest()
        if key in _COMPILE_CACHE:
            c, notes = _COMPILE_CACHE[key]
            return {"contract": c, "notes": notes, "cached": True}
        cov = (await store.coverage()).get("known_rate", {})
        if not providers.llm_json:
            raise HTTPException(status_code=503, detail="no language model configured")
        contract, notes = await compile_mod.compile_brief(providers.llm_json, text, coverage=cov, value_counts=await index_counts(store), limit=body.limit)
        out = (contract.to_dict(), notes)
        _COMPILE_CACHE[key] = out
        return {"contract": out[0], "notes": out[1], "cached": False}

    @r.post("/startups/evaluate")
    async def evaluate_contract(body: EvaluateIn) -> dict:
        c = Contract.from_dict(body.contract)
        c.kind = KIND
        return await _evaluate(c)

    @r.get("/startups/coverage")
    async def coverage() -> dict:
        cov = await store.coverage()
        pool = await store.pool()
        async with pool.acquire() as conn:
            jobs = await conn.fetch("SELECT id, kind, status, progress, error, created_at, updated_at FROM su_job ORDER BY id DESC LIMIT 12")
        cov["jobs"] = [_job_row(j) for j in jobs]
        cov["labels"] = labels()
        return cov

    @r.get("/startups/lists/{list_id}")
    async def get_list(list_id: str) -> dict:
        pool = await store.pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT id, name, contract, rows, created_at FROM su_list WHERE id = $1", list_id)
        if not row:
            raise HTTPException(status_code=404, detail="no such list")
        return {"id": row["id"], "name": row["name"], "contract": json.loads(row["contract"]), "rows": json.loads(row["rows"]), "created_at": row["created_at"].isoformat()}

    @r.post("/startups/lists")
    async def save_list(body: ListIn) -> dict:
        await store.ensure_schema()
        lid = uuid.uuid4().hex[:12]
        pool = await store.pool()
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO su_list (id, name, contract, rows) VALUES ($1, $2, $3::jsonb, $4::jsonb)", lid, body.name[:120], json.dumps(body.contract), json.dumps(body.rows[:200]))
        return {"id": lid}

    @r.get("/startups/{company_id:path}")
    async def company(company_id: str) -> dict:
        c = await store.company(company_id)
        if not c:
            raise HTTPException(status_code=404, detail="no such company")
        c["labels"] = labels()
        return c

    @r.post("/admin/startups/jobs")
    async def start_job(body: JobIn, x_admin_token: str = Header(default="")) -> dict:
        _admin(x_admin_token)
        if body.kind not in pipeline.RUNNERS:
            raise HTTPException(status_code=400, detail=f"unknown job kind; one of {sorted(pipeline.RUNNERS)}")
        params = dict(body.params)
        if body.kind == "extract":
            n = int(params.get("limit", 25))
            params["max_usd"] = float(params.get("max_usd", 5.0))
            proj = pipeline.project_extract_cost(n)
            if proj["projected_usd"] > params["max_usd"]:
                return {"refused": True, "projection": proj, "max_usd": params["max_usd"]}
        jid = await pipeline.start_job(store, dsn, body.kind, params, providers=providers)
        return {"job_id": jid, "kind": body.kind, "params": params}

    @r.post("/admin/startups/roster-ats")
    async def roster_ats(body: RosterAtsIn, x_admin_token: str = Header(default="")) -> dict:
        """Import roster's shared ATS board export (one row per company board) as the hiring signal. No spend."""
        _admin(x_admin_token)
        from .sources import roster_ats as _ra
        await store.ensure_schema()
        return await _ra.attach(store, body.rows)

    @r.get("/admin/startups/jobs")
    async def jobs(x_admin_token: str = Header(default="")) -> dict:
        _admin(x_admin_token)
        await store.ensure_schema()
        pool = await store.pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, kind, status, params, progress, error, created_at, updated_at FROM su_job ORDER BY id DESC LIMIT 30")
        return {"jobs": [_job_row(j) for j in rows]}

    return r


def _excluded(row: dict, exclude: dict) -> bool:
    for key, vals in (exclude or {}).items():
        have = set((row.get("facets") or {}).get(key) or [])
        if have & {str(v) for v in vals}:
            return True
    return False


def _job_row(j) -> dict:
    d = dict(j)
    for k in ("params", "progress"):
        if isinstance(d.get(k), str):
            try:
                d[k] = json.loads(d[k])
            except Exception:   # noqa: BLE001
                pass
    for k in ("created_at", "updated_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d
