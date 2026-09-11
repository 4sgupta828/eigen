"""Investor Search endpoints (docs/specs/investors.md §6). Step 0: evaluate, coverage, dossier, admin jobs.

`POST /investors/compile` (brief → contract) is the one endpoint that costs a model call, and it lands with the
UI in Step 1. Everything mounted here reads rows we already hold and spends nothing.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from eigen_kernel.facets import Contract, evaluate, validate_contract

from api import intent_check as intent_mod

from . import advise as advise_mod
from . import intent_prompt
from . import compile as compile_mod
from . import pipeline
from .schema import KIND, REGISTER, SCHEMA, WEIGHTS, labels
from .store import InvestorStore


def investor_search_enabled() -> bool:
    return os.environ.get("EIGEN_INVESTOR_SEARCH", "").strip() not in ("", "0", "false", "no")


class CompileIn(BaseModel):
    text: str
    limit: int = 60


class AdviseIn(BaseModel):
    name: str = ""            # the startup's name or domain
    stage: str = ""           # pre_seed | seed | series_a | ...
    geo: list[str] = []       # country tokens: us, uk, in, ae
    sectors: list[str] = []   # the startup schema's tech-area vocabulary
    deck_text: str = ""       # text pulled from an uploaded deck
    # An explicit "we are raising $X", used ONLY to demote funds whose minimum cheque dwarfs the round.
    # Never to infer a stage — an amount is not a round, and stage_from_text exists so we never guess it.
    raise_target: float | None = None
    limit: int = 40


class ReadStartupIn(BaseModel):
    url: str = ""                       # the startup's own site — read for free
    deck_text: str = ""                 # text already extracted client-side
    attachments: list[dict] = []        # [{name, media_type, data(base64)}] — a deck as a PDF


class SaveMapIn(BaseModel):
    title: str = ""
    brief: str = ""
    contract: dict = {}
    rows: list = []
    notes: str = ""


class EvaluateIn(BaseModel):
    contract: dict
    counts: bool = True
    query: str = ""           # the words the reader typed, for the intent debugger
    history: list = []        # [{asked, offered, chose, told}] — the conversation so far
    intent: bool = True       # a caller that does not want the question can say so


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
    _intent_cache: dict = {}
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
        matched = (out.get("counts") or {}).pop("_total", None)
        out["coverage"]["matched"] = matched
        out["labels"] = labels()
        out["directions"] = _directions(out, c, matched)
        # THE INTENT DEBUGGER. The directions above filter what came back; this asks whether the question
        # was understood at all — a reading, not a count. One model call, gated and cached.
        if body.intent:
            got = await intent_mod.check(llm_json=llm_json, kind=KIND, query=body.query or c.text or "",
                                         contract=c, out=out, rows=rows, schema=SCHEMA,
                                         prompt=intent_prompt, cache=_intent_cache, history=body.history)
            if got:
                out["intent"] = got
        return out

    @r.post("/investors/advise")
    async def advise(body: AdviseIn) -> dict:
        """Which investors have already funded companies like this one, at this stage, in this geography.

        Not a prediction. Every row carries the signals it matched and the register each came from, so a
        founder can tell "eleven seed rounds we can date" from "their site says they do seed" — and the
        conflicts are shown alongside, because a firm that already backs a competitor is the one row on the
        list where a strong match is a reason NOT to send the email.
        """
        stage = (body.stage or "").strip()
        sectors = [s.strip() for s in body.sectors if s.strip()]
        geo = [g.strip().lower() for g in body.geo if g.strip()]
        notes: list[str] = []
        subject: dict = {}

        # A deck says what it is raising; read only an explicit round name from it, never an amount.
        if body.deck_text and not stage:
            stage = advise_mod.stage_from_text(body.deck_text)
            if stage:
                notes.append(f"Read '{stage.replace('_', ' ')}' from the deck — change it if that is wrong.")

        # A named startup we already hold tells us its sector, geography and who is on its cap table, which
        # is better than anything the founder would have to type.
        co_investors: list[str] = []
        if body.name:
            subject, found_sectors, found_geo, co_investors = await _subject_of(store, body.name)
            sectors = sectors or found_sectors
            geo = geo or found_geo
            if subject:
                notes.append(f"Matched {subject['name']} in the index — using its sector, geography and "
                             f"existing investors.")
            else:
                notes.append(f"No company called '{body.name}' in the index yet, so the advice rests on what "
                             f"you typed rather than on their record.")

        if not (stage or sectors or geo):
            raise HTTPException(status_code=400, detail="give at least a stage, a sector or a geography")

        # Candidates come from the SIGNALS, one targeted query per signal, fused by reciprocal rank.
        #
        # The first version ranked instead of retrieving: it passed the signals as `prefer` with no `must`,
        # which enumerates a capped slice of the index by prominence and re-orders THAT. The firm that
        # actually matched the sector was never a candidate, so a search with a real answer returned nothing.
        # A preference cannot find a row; only a filter can, so each signal gets its own filter and the
        # results are fused.
        from eigen_kernel.facets.contract_search import rrf_fuse
        legs: dict = {}
        for key, vals in (("observed_sector", sectors), ("sector_focus", sectors),
                          ("observed_stage", [stage] if stage else []), ("stated_stage", [stage] if stage else []),
                          ("observed_geo", geo), ("co_investor", co_investors)):
            if not vals:
                continue
            got = await store.enumerate(KIND, {key: list(vals)}, cap=150)
            if got:
                legs[key] = got
        if not legs:
            legs["deploying"] = await store.enumerate(KIND, {"still_deploying": ["yes_recent"]}, cap=150)
        rows = rrf_fuse(legs)
        out = {"coverage": {"candidates": {k: len(v) for k, v in legs.items()}}}
        hydrated = await _hydrate(store, [x["id"] for x in rows])
        sector_of = await _sectors_of_companies(
            store, [c2["id"] for r in rows for c2 in (hydrated.get(r["id"], {}).get("portfolio_sample") or [])])

        ranked = []
        for x in rows:
            firm = hydrated.get(x["id"], {})
            why, score = advise_mod.reasons_for(x, stage=stage, sectors=sectors, geo=geo,
                                                co_investors=co_investors)
            if not advise_mod.is_advice(why):
                # "has money and raised recently" is true of thousands of firms; ranking on it produces an
                # alphabetical list wearing the costume of a recommendation.
                continue
            conflicts = advise_mod.conflicts_for(firm.get("portfolio_sample"), sectors, sector_of)
            # Anti-signals move the RANK. A firm that already funds a direct competitor was previously
            # ranked exactly where its positive signals put it, with a warning attached — top of the
            # list, for the one founder who must not email it first.
            penalty, warn = advise_mod.penalties_for(x, conflicts=conflicts, raise_target=body.raise_target)
            ranked.append({**x, "firm": firm, "why": why, "fit": round(max(0.0, score - penalty), 2),
                           "matched_on": advise_mod.axes_with_evidence(why),
                           "against": warn, "conflicts": conflicts})
        ranked.sort(key=lambda r: (-r["fit"], -len(r["why"]), r["id"]))
        for i, r in enumerate(ranked):
            r["rank"] = i + 1

        if not ranked:
            cov = await store.coverage()
            with_pf = (cov.get("known") or {}).get("portfolio_count", 0)
            notes.append(
                f"No investor in the index has a recorded match for this stage, sector and geography yet. "
                f"That is a gap in what we have READ, not a finding about the market: we hold complete "
                f"registration and fund records for {cov.get('firms', 0):,} firms, but a portfolio for only "
                f"{with_pf:,} of them so far. Matching on what a firm has actually backed needs that number "
                f"to grow, which the site crawl is doing now.")
        return {"rows": ranked[:body.limit], "subject": subject, "notes": notes, "labels": labels(),
                "asked": {"stage": stage, "sectors": sectors, "geo": geo},
                "coverage": out.get("coverage") or {}}

    @r.post("/investors/read-startup")
    async def read_startup(body: ReadStartupIn) -> dict:
        """Read a startup from its own site or its deck, and say what we can match it against.

        Reading is free: site.crawl for a URL, the PDF text layer for a deck. Exactly one model call
        turns that into a structured profile, and only when there is text to turn. The PLAN comes
        back either way, because with observed sector known for under 1% of firms a ranked list is
        often the less honest of the two things we could hand over (docs/specs/investor-matching.md).
        """
        import asyncio as _a
        from api.investors import read_startup as rs

        text, sources = "", []
        if body.attachments:
            t, names = rs.text_from_attachments(body.attachments)
            text, sources = t, names
        if not text and body.url:
            loop = _a.get_event_loop()
            try:
                text, sources = await loop.run_in_executor(None, rs.text_from_site, body.url)
            except Exception as e:      # a site that will not be read is a stated gap, not a 500
                return {"profile": {}, "sources": [], "read": False,
                        "note": f"Could not read {body.url}: {str(e)[:160]}"}
        if not text and body.deck_text:
            text, sources = body.deck_text, ["pasted text"]
        if not (text or "").strip():
            return {"profile": {}, "sources": [], "read": False,
                    "note": "Nothing to read yet — give a website, a deck, or a description. A scanned "
                            "deck with no text layer reads as empty here rather than being guessed at."}

        lab = labels()
        sect_vocab = [v["value"] for v in (lab.get("observed_sector") or {}).get("values", [])] or []
        geo_vocab = [v["value"] for v in (lab.get("observed_geo") or {}).get("values", [])] or []
        profile = {}
        if llm_json:
            try:
                profile = await rs.read_profile(llm_json, text, sectors_vocab=sect_vocab, geo_vocab=geo_vocab)
            except Exception as e:
                return {"profile": {}, "sources": sources, "read": True,
                        "note": f"Read the text but could not structure it: {str(e)[:160]}"}
        # Coverage only supplies the plan's framing numbers. Losing it must not lose the reading the
        # founder just waited on — a stats query is not a reason to throw away a crawled site.
        try:
            cov = await store.coverage()
        except Exception:
            cov = {}
        return {"profile": profile, "sources": sources, "read": True,
                "chars_read": len(text), "plan": rs.plan_for(profile, coverage=cov, matched=0)}

    @r.post("/investors/maps")
    async def save_map(body: SaveMapIn, x_eigen_token: str = Header(default="")) -> dict:
        if not x_eigen_token:
            raise HTTPException(status_code=401, detail="sign in to save a search map")
        return await store.save_map(owner_id=x_eigen_token, title=body.title or "Investor search",
                                    brief=body.brief, contract=body.contract, rows=body.rows,
                                    coverage=await store.coverage(), notes=body.notes)

    @r.get("/investors/maps")
    async def my_maps(x_eigen_token: str = Header(default="")) -> dict:
        if not x_eigen_token:
            return {"maps": []}
        return {"maps": await store.my_maps(x_eigen_token)}

    @r.get("/investors/maps/{map_id}")
    async def get_map(map_id: str, share: str = "", x_eigen_token: str = Header(default="")) -> dict:
        got = await store.get_map(map_id, owner_id=x_eigen_token, share=share)
        if not got:
            raise HTTPException(status_code=404, detail="no such map")
        return got

    @r.get("/investors/coverage")
    async def coverage() -> dict:
        cov = await store.coverage()
        cov["registers"] = dict(REGISTER)
        # The honest caveat that belongs next to every count: this register is American.
        # Says the same thing in half the words. The point a reader needs is that a missing number is a
        # gap in the register, not a small firm — "coverage fact, not a judgment about its size" was
        # explaining our own reasoning rather than telling them what to conclude.
        cov["caveats"] = ["Form ADV is a US register — no US registration means no filed AUM here, "
                          "not a small firm."]
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


def _directions(out: dict, c: Contract, matched: int | None) -> list[dict]:
    """The few ways this investor search could usefully go next. Model-free; see the startups twin."""
    from eigen_kernel.facets import facet_directions, rank_directions, worth_steering
    try:
        ok, why = worth_steering({"pool": matched or 0})
        # The reason travels even when the answer is no — see the startups twin.
        out["steering"] = {"offered": False, "reason": why, "pool": matched or 0}
        if not ok:
            return []
        settled = set(c.must or {}) | set(c.avoid or {}) | set((c.scope or {}).get("exclude") or {})
        cands = facet_directions(out.get("counts") or {}, SCHEMA, KIND, exclude=settled, labels=labels(),
                                 pool=matched or 0)
        got = [{"key": d.key, "label": d.label, "values": d.values, "section": d.section,
                "hits": d.hits, "why": d.why, "source": d.source, "reason": why,
                "register": REGISTER.get(d.key, "")}
               for d in rank_directions(cands, top=3)]
        out["steering"] = ({"offered": True, "reason": why, "pool": matched or 0} if got else
                           {"offered": False, "pool": matched or 0,
                            "reason": "nothing here splits these results usefully"})
        return got
    except Exception:      # noqa: BLE001
        return []


async def _subject_of(store: InvestorStore, name: str) -> tuple[dict, list[str], list[str], list[str]]:
    """Resolve the founder's own company in the startup index -> (subject, sectors, geo, its investors)."""
    from api.investors.store import domain_of
    q = (name or "").strip()
    dom = domain_of(q)
    pool = await store.pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, name, one_liner FROM su_company
               WHERE id = $1 OR lower(name) = lower($2) ORDER BY (id = $1) DESC LIMIT 1""", dom or q, q)
        if not row:
            return {}, [], [], []
        facts = await conn.fetch(
            "SELECT key, value FROM su_fact WHERE company_id = $1 AND key IN ('tech_area','country','investor')",
            row["id"])
    by: dict = {}
    for f in facts:
        by.setdefault(f["key"], []).append(f["value"])
    return ({"id": row["id"], "name": row["name"], "one_liner": row["one_liner"]},
            by.get("tech_area", []), by.get("country", []), by.get("investor", []))


async def _sectors_of_companies(store: InvestorStore, ids: list[str]) -> dict:
    """{company id -> [tech areas]} for conflict checking, in one query rather than one per firm."""
    if not ids:
        return {}
    pool = await store.pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT company_id, value FROM su_fact WHERE key = 'tech_area' AND company_id = ANY($1)",
            list(set(ids)))
    out: dict = {}
    for r in rows:
        out.setdefault(r["company_id"], []).append(r["value"])
    return out


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
