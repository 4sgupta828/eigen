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

from . import compile as compile_mod, grouping as grouping_mod, pipeline, ranking
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
    sort: str = "relevance"     # see ranking.SORTS — relevance, funding, hiring, youngest, …


class ListIn(BaseModel):
    name: str
    contract: dict
    rows: list = []


class GroupIn(BaseModel):
    rows: list = []               # the rows on screen: {id, company:{name, one_liner}} — max 200
    question: str = ""


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

    degraded: str = ""

    async def semantic(self, kind, text, must, *, cap=400):
        rows = []
        if self._e:
            try:
                rows = await self._s.semantic(kind, text, must, cap=cap, exclude=self._x, embed=self._e)
            except Exception as e:   # noqa: BLE001 — an embedding provider outage (no credits, rate limit) must never 500 a search
                self.degraded = f"embeddings unavailable ({type(e).__name__}): the words cannot rank — filters only"
        # no embedder, nothing embedded yet, or the provider is down → the words cannot rank, but the musts still filter
        return rows or await self._s.enumerate(kind, must, cap=cap, exclude=self._x)

    async def counts(self, kind, must, schema, *, depth=None):
        return await self._s.counts(kind, must, schema, depth=depth, exclude=self._x)

    async def noise_floor(self, kind, text):
        return None


class IntakeIn(BaseModel):
    state: dict | None = None
    message: str = ""
    answer: dict | None = None
    search_now: bool = False


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

    def _group_options(rows: list) -> list[dict]:
        """Which dimensions would actually organise THESE rows. Free: pure Python over the rows we
        already returned. A dimension that fails is absent from the menu rather than offered empty."""
        from datetime import date
        from eigen_kernel.facets.grouping import eligible
        year = date.today().year
        out = [{"key": "auto", "label": "Auto", "score": 1e9,
                "why": "let a model segment these by what the companies do"}]
        for key, label, source, kind in grouping_mod.GROUP_DIMENSIONS:
            if kind == "auto":
                continue
            vals = [(grouping_mod.values_for(r, source, this_year=year) or [""])[0] for r in rows]
            # Thresholds tuned to THIS index, not to a dense one. Measured on a 60-row result set:
            # "what they build" was excluded for having 9 groups against a limit of 8, and "where they
            # are" for 27% unstated against a limit of 25% — the two most useful cuts, both lost on a
            # technicality. A dimension where 40% is unknown still organises the 60% that is known,
            # and the unknown rows are shown as their own group with their own size, so nothing is
            # hidden. What stays strict is the rule that matters: a single value swallowing the set
            # organises nothing.
            e = eligible(vals, kind=kind, max_unstated=0.60, max_groups=12)
            if e.ok:
                out.append({"key": key, "label": label, "score": round(e.score, 3),
                            "groups": e.groups, "known": round(e.known, 3), "source": source})
        return sorted(out, key=lambda o: -o["score"])

    async def _labels_with_investors() -> dict:
        """The rail's labels plus the investor directory, so a name on a card can become a link."""
        out = labels()
        try:
            out["investor_sites"] = await store.investor_sites()
        except Exception:      # noqa: BLE001 — a missing directory costs links, never a response
            out["investor_sites"] = {}
        return out

    async def _evaluate_core(c: Contract, counts: bool = True) -> dict:
        errs = validate_contract(c, SCHEMA)
        if errs:
            raise HTTPException(status_code=400, detail="; ".join(errs))
        exclude = dict((c.scope or {}).get("exclude") or {})
        bound = _Bound(store, exclude, providers.embed)
        out = await evaluate(c, bound, SCHEMA, WEIGHTS, depth=({"counts": False} if not counts else None))
        if bound.degraded:
            out["coverage"]["degraded"] = bound.degraded
        rows = [x for x in out["rows"] if not _excluded(x, exclude)]
        hydrated = await store.companies_by_ids([x["id"] for x in rows])
        for i, x in enumerate(rows):
            x["company"] = hydrated.get(x["id"], {})
            x["rank"] = i + 1
        total = (out.get("counts") or {}).pop("_total", None)
        out["rows"] = rows
        out["coverage"]["matched"] = total
        return out

    async def _slice(must: dict, exclude: dict) -> int:
        return await store.slice_size(must, exclude=exclude)

    async def _evaluate(c: Contract, merge: dict | None = None) -> dict:
        """Single evaluate, or — with words and a model — roster's MERGED search: recipes probed, fused, the head judged blind."""
        from . import contract_search as cs
        merge = merge or {}
        mode = merge.get("mode") or ("merged" if (c.text and providers.llm_json) else "single")
        user_keys = set(merge.get("user_keys") or [])
        relaxed: list = []
        if merge.get("relax") and c.must:
            # SMART RELAXING (first searches only; a rail Apply runs the chips as set): too few results → the least
            # important musts rank instead of filtering, until the pool is a good size
            if mode == "merged" and c.text and providers.llm_json:
                async def _probe_eval(contract, counts=True):
                    return await _evaluate_core(Contract.from_dict({**contract.to_dict(), "limit": 60}), counts=False)
                probe, relaxed = await cs.relax_to_enough(c, user_keys=user_keys, slice_fn=_slice, evaluate_fn=_probe_eval)
                if relaxed:
                    c = Contract.from_dict(probe.get("contract") or c.to_dict()); c.limit = int(merge.get("limit") or 60)
            else:
                out, relaxed = await cs.relax_to_enough(c, user_keys=user_keys, slice_fn=_slice, evaluate_fn=_evaluate_core)
                out["relaxed"] = relaxed
                rows = out["rows"]
                out["coverage"]["index"] = await store.coverage()
                out["labels"] = await _labels_with_investors()
                return out
        if mode == "merged" and c.text and providers.llm_json:
            try:
                out = await cs.merged_search(c, user_keys=user_keys, evaluate_fn=_evaluate_core, slice_fn=_slice, llm_json=providers.llm_json, off=merge.get("off"), top=int(c.limit))
            except HTTPException:
                raise
            except Exception as e:   # noqa: BLE001 — the merged path must never be the reason a search fails outright
                out = await _evaluate_core(c)
                out["coverage"]["degraded"] = (out["coverage"].get("degraded") or "") + f" merged search unavailable ({type(e).__name__})"
            out["coverage"]["matched"] = (out.get("coverage") or {}).get("matched")
        else:
            out = await _evaluate_core(c)
        out["relaxed"] = relaxed
        rows = out["rows"]
        out["coverage"]["index"] = await store.coverage()
        out["labels"] = await _labels_with_investors()
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

    # ---- Guided search: roster's intake adapted — one turn per call, state rides the request (spec §1 of guided-intake, startups)
    async def _counts_for_intake(must: dict, exclude: dict) -> dict:
        c = await store.counts(KIND, must, SCHEMA, exclude=exclude)
        return c

    async def _compile_for_intake(text: str):
        cov = (await store.coverage()).get("known_rate", {})
        if not providers.llm_json:
            return Contract(kind=KIND, text=text[:200]), ["no language model configured — the words alone rank"]
        return await compile_mod.compile_brief(providers.llm_json, text, coverage=cov, value_counts=await index_counts(store))

    @r.post("/startups/intake/step")
    async def intake_step(body: IntakeIn) -> dict:
        from .intake import StartupIntake
        svc = StartupIntake(llm_json=providers.llm_json, counts_fn=_counts_for_intake, compile_fn=_compile_for_intake, slice_fn=_slice, coverage_fn=lambda: store.coverage())
        out = await svc.step(state=body.state, message=body.message, answer=body.answer, search_now_flag=body.search_now)
        out["labels"] = await _labels_with_investors()
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
        from .contract_search import merge_options
        c = Contract.from_dict(body.contract); c.kind = KIND
        out = await _evaluate(c, merge_options(body.contract))
        # Relevance answers "who matches my words"; these answer "who raised most", "who is hiring
        # hardest", "who has been at this longest" — the questions that make a long list navigable.
        out["ranking"] = ranking.apply(out.get("rows") or [], body.sort)
        out["sorts"] = ranking.options()
        out["group_options"] = _group_options(out.get("rows") or [])
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
    async def evaluate_contract(body: EvaluateIn, x_eigen_token: str = Header(default="")) -> dict:
        from .contract_search import merge_options
        c = Contract.from_dict(body.contract)
        c.kind = KIND
        out = await _evaluate(c, merge_options(body.contract))
        # Relevance answers "who matches my words"; these answer "who raised most", "who is hiring
        # hardest", "who has been at this longest" — the questions that make a long list navigable.
        out["ranking"] = ranking.apply(out.get("rows") or [], body.sort)
        out["sorts"] = ranking.options()
        out["group_options"] = _group_options(out.get("rows") or [])
        # a private note of what was asked, so a line of enquiry can be resumed later
        try:
            u = await user_of(x_eigen_token) if user_of else None
            uid = str((u or {}).get("id") or "")
            if uid:
                from api.history import record as _record
                import asyncpg  # noqa: F401 — the pool is the store's
                pool = await store.pool()
                async with pool.acquire() as conn:
                    await _record(conn, uid, mode="startups",
                                  title=(body.contract.get("text") or "startup search")[:200],
                                  query={"contract": body.contract},
                                  hits=len(out.get("rows") or []))
        except Exception:   # noqa: BLE001 — history must never break the search
            pass
        return out

    @r.post("/startups/group")
    async def group_rows(body: GroupIn) -> dict:
        """Segment the rows on screen by what the companies DO. One model call, only when asked.

        Costs about a tenth of a cent and takes a couple of seconds. Any failure falls back to the
        free token split rather than to an error — a grouping is a convenience, and losing it must
        never lose the results.
        """
        from eigen_kernel.facets.grouping import enforce, token_groups
        rows = (body.rows or [])[:200]
        if len(rows) < 6:
            return {"groups": [], "leftovers": list(range(len(rows))), "source": "none",
                    "notes": ["too few companies to group"]}
        lines = "\n".join(grouping_mod.row_line(i, r) for i, r in enumerate(rows))[:12000]
        ids = [str(r.get("id") or i) for i, r in enumerate(rows)]
        notes: list[str] = []
        proposed = []
        source = "fallback"
        if providers.llm_json:
            try:
                data = await providers.llm_json(grouping_mod.segment_prompt(), lines)
                proposed = (data or {}).get("groups") or []
                source = "model"
                gs, left, ns = enforce(proposed, len(rows))
                dom = next((n for n in ns if n.startswith("dominant")), "")
                if dom:      # one group swallowing the set is a list, not a segmentation: ask once more
                    name = dom.split("'")[1] if "'" in dom else ""
                    big = max((len(g.ids) for g in gs), default=0)
                    data2 = await providers.llm_json(
                        grouping_mod.resegment_prompt(name, big, len(rows)), lines)
                    gs2, left2, ns2 = enforce((data2 or {}).get("groups") or [], len(rows))
                    if gs2 and not any(n.startswith("dominant") for n in ns2):
                        gs, left, ns = gs2, left2, ns2
                        notes.append("re-asked: the first answer had one dominant group")
                proposed = gs
                notes += ns
            except Exception as e:      # noqa: BLE001 — a grouping must never cost the results
                notes.append(f"the model was unavailable ({type(e).__name__}); grouped by shared words")
                proposed, source = [], "fallback"
        if not proposed:
            toks = [set(str((r.get("company") or {}).get("one_liner") or "").lower().split()) for r in rows]
            proposed, left, ns = token_groups(toks)
            notes += ns
            source = "fallback"
            gs, left = proposed, left
        else:
            gs = proposed
        return {"groups": [{"name": g.name, "why": g.why, "key": g.key,
                            "ids": [ids[i] for i in g.ids if 0 <= i < len(ids)]} for g in gs],
                "leftovers": [ids[i] for i in left if 0 <= i < len(ids)],
                "source": source, "notes": notes[:6]}

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
        if body.kind == "business_model":
            n = int(params.get("limit", 200))
            params["max_usd"] = float(params.get("max_usd", 1.0))
            proj = pipeline.project_business_model_cost(n)
            if proj["projected_usd"] > params["max_usd"]:
                return {"refused": True, "projection": proj, "max_usd": params["max_usd"]}
        if body.kind == "careers_roles":
            n = int(params.get("limit", 200))
            params["max_usd"] = float(params.get("max_usd", 2.0))
            proj = pipeline.project_careers_cost(n)
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

    @r.post("/admin/startups/jobs/{job_id}/cancel")
    async def cancel_job(job_id: int, x_admin_token: str = Header(default="")) -> dict:
        """Ask a running job to stop at its next progress report."""
        _admin(x_admin_token)
        pool = await store.pool()
        async with pool.acquire() as conn:
            n = await conn.execute("UPDATE su_job SET status = 'cancelling', updated_at = now() WHERE id = $1 AND status = 'running'", job_id)
        return {"job_id": job_id, "cancelling": n.endswith("1")}

    @r.get("/admin/startups/jobs")
    async def jobs(x_admin_token: str = Header(default="")) -> dict:
        _admin(x_admin_token)
        await store.ensure_schema()
        pool = await store.pool()
        async with pool.acquire() as conn:
            # a 'running' row silent for 30 minutes is a zombie (its thread died with a restart the startup hook missed)
            await conn.execute("UPDATE su_job SET status = 'orphaned', error = 'no progress for 30 minutes; the job thread is gone — re-launch it', updated_at = now() WHERE status = 'running' AND updated_at < now() - interval '30 minutes'")
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
