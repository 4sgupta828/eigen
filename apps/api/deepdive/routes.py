"""DeepDive routes.

Three depths, and the DEEPEST is the default:

- `held`  — free. Rows we already hold plus the keyless public sources. No model, no web.
- `read`  — spends a little: a deeper crawl of the company's own site, then one model call per page,
            every claim gated on a verbatim quote, subject congruence and metric definition.
- `full`  — adds the bounded web read for what only news and analysis carry, kept in a signal register.

Every depth above `held` is PROJECTED and GATED before anything is spent: a projection over `max_usd`
returns a refusal with the number in it and charges nothing. That cap is the gate — NOT a click per
leg. A dive used to default to `held` and then offer to read their site, then offer the web, so the
answer a reader got depended on how many times they pressed a button; the legs are cheap and the
reader asked for the company, so the dive reads everything it can and the cap stops it going wide.

`held` survives as an explicit downshift for a reader who wants only what costs nothing.

The mode is flag-gated (EIGEN_DEEPDIVE). OFF is a true no-op: no routes, no tables touched.
"""
from __future__ import annotations

import os
import re

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from . import discover as discovery
from . import public as public_sources
from . import store as dstore
from .assemble import build, merge_sections
from .resolve import resolve

DEPTHS = ("held", "read", "full")
# A page of a company's own site is longer than a careers page and the answer is a small JSON list;
# measured against the careers extractor ($0.0005/page on gpt-4o-mini), three times the input.
EXTRACT_USD_PER_PAGE = float(os.environ.get("EIGEN_DEEPDIVE_PAGE_USD", "0.0015"))
MAX_READ_PAGES = 14


def deepdive_enabled() -> bool:
    return os.environ.get("EIGEN_DEEPDIVE", "").lower() in ("1", "true", "yes", "on")


class DiveIn(BaseModel):
    q: str = ""                     # a name, a domain, or a company id
    company_id: str = ""            # set when the caller already picked from candidates
    refresh: bool = False           # write a new revision instead of returning the stored one
    public: bool = True             # the keyless public sources (EDGAR, Wikidata, GitHub) — free
    depth: str = "full"             # held | read | full — a dive READS, that is what a dive is
    discover: bool = True           # a name we do not hold: look for it on the web and admit it
    accept_domain: str = ""         # the caller confirmed an unsure match
    max_usd: float = 0.50           # refuse before spending more than this
    project_only: bool = False      # return the projection and spend nothing


# A dossier's `basis` is the record of WHICH LEGS RAN, written as "held+corpus+read+web". It is also
# the cache key: a stored dossier answers a request only if it ran every leg the request needs.
#
# `corpus` is listed for `held` too, and that is deliberate. The corpus leg is free and runs at every
# depth — but dossiers written before it existed say only "held", so without it in the needs list
# they would keep being served as complete while missing the deepest material we have. One rebuild
# each and they carry it.
CORPUS_MARK = "corpus"
_DEPTH_NEEDS = {"held": (CORPUS_MARK,), "read": (CORPUS_MARK, "read"),
                "full": (CORPUS_MARK, "read", "web")}


def basis_covers(basis: str, depth: str) -> bool:
    """Does a dossier we already hold answer a request at this depth?

    A dossier read at `full` covers a later `read` or `held` request; the reverse is not true. Without
    this the cache only ever hit at `held`, so a reader opening the SAME company at the same depth was
    quoted the full price again for a dossier already on disk — and the ⌖ DeepDive link on a card,
    which asks for the deepest read, would have charged on every single click.
    """
    b = str(basis or "")
    return all(part in b for part in _DEPTH_NEEDS.get(depth, ()))


def project(depth: str, n_pages: int, templates) -> dict:
    """What a dive at this depth will cost, before it is run."""
    pages = min(n_pages, MAX_READ_PAGES) if depth in ("read", "full") else 0
    extract = round(pages * EXTRACT_USD_PER_PAGE, 4)
    web = 0.0
    if depth == "full" and templates:
        from .web import project_web_cost
        web = project_web_cost(templates)["projected_usd"]
    return {"depth": depth, "pages": pages, "usd_per_page": EXTRACT_USD_PER_PAGE,
            "extract_usd": extract, "web_usd": web, "projected_usd": round(extract + web, 4)}


def build_router(pool_of, su_store, *, providers=None, manifest=None, user_of=None) -> APIRouter:
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
        depth = body.depth if body.depth in DEPTHS else "full"
        cid = (body.company_id or "").strip().lower()
        pool = await pool_of()
        discovered = False
        if not cid and body.accept_domain:
            # The caller looked at an unsure match and said yes. Admit it under the name they typed.
            await discovery.admit(su_store, domain=body.accept_domain.lower(), name=body.q or body.accept_domain)
            cid, discovered = body.accept_domain.lower(), True
        if not cid:
            res = await resolve(pool, body.q)
            if res["status"] == "resolved":
                cid = res["company"]["id"]
            elif res["status"] == "unknown" and body.discover:
                # A PROJECTION MUST NOT SPEND. `project_only` was only honoured further down, past
                # `discovery.find` — so pricing a dive for a company we do not hold ran the web
                # search, and a caller that priced-then-dived paid for discovery twice.
                if body.project_only:
                    return {"status": "projection", "company": {"id": "", "name": body.q},
                            "projection": {"depth": depth, "pages": 0, "extract_usd": 0.0, "web_usd": 0.0,
                                           "discover": True,
                                           **discovery.project_discover_cost()}}
                found = await discovery.find(body.q, manifest=manifest, llm=_llm(providers))
                if found["status"] != "found":
                    return {"status": found["status"], "reason": found["why"],
                            "candidates": [], "discovered": found,
                            "projection": discovery.project_discover_cost()}
                await discovery.admit(su_store, domain=found["domain"], name=body.q)
                cid, discovered = found["domain"], True
            else:
                # A refusal carries the candidates so the caller can pick — it never guesses.
                return {"status": res["status"], "reason": res.get("reason", ""),
                        "candidates": res["candidates"],
                        "can_discover": res["status"] == "unknown",
                        "projection": discovery.project_discover_cost()}

        # A dossier we already hold that covers what was asked for is FREE — at every depth, not just
        # `held`. `refresh` is how a reader deliberately buys a newer one.
        if not body.refresh:
            held = await dstore.get(pool, company_id=cid)
            if held and basis_covers(held.get("basis"), depth):
                if body.project_only:
                    return {"status": "projection", "cached": True,
                            "projection": {"depth": depth, "pages": 0, "extract_usd": 0.0,
                                           "web_usd": 0.0, "projected_usd": 0.0, "cached": True},
                            "company": {"id": cid, "name": held.get("name") or ""}}
                return {"status": "ok", "cached": True, "dossier": held}

        # Finding a company on the web is already a spend. Stopping at "what we hold" then shows a
        # company we have held for four seconds — a stub. A company we just discovered is READ.
        # This used to fire on `discover` being *permitted* rather than having *happened*, which with
        # discovery on by default would have quietly overridden an explicit `held`.
        if discovered and depth == "held":
            depth = "read"

        c = await su_store.company(cid)
        if not c:
            raise HTTPException(status_code=404, detail="we hold no company with that id")
        pages = await su_store.pages(cid)
        if discovered and not pages:
            # A company we just met has nothing but a domain, so "what we hold" would be an empty
            # page. Reading their site is HTTP, not a model — free, and the difference between a
            # dossier and a stub.
            pages = await _deep_crawl(su_store, c, pages)
            c = await su_store.company(cid) or c

        # ---- the gate: project first, spend after, never the other way round
        proj = project(depth, max(len(pages), 6 if depth != "held" else 0),
                       getattr(manifest, "company_reader", None))
        if body.project_only:
            return {"status": "projection", "projection": proj, "company": {"id": cid, "name": c.get("name")}}
        if proj["projected_usd"] > body.max_usd:
            return {"status": "refused", "refused": True, "projection": proj, "max_usd": body.max_usd,
                    "reason": f"this dive projects ${proj['projected_usd']:.2f}, over the ${body.max_usd:.2f} cap"}

        # The investor directory turns slugs into names and links — the same map the card uses.
        try:
            sites = await su_store.investor_sites()
        except Exception:      # noqa: BLE001 — investors are still named, just not linked
            sites = {}
        # THE FREE DOSSIER FIRST, then the corpus — in that order, deliberately. What we already hold
        # about this company (who backs them, who runs it) is what tells a corpus passage apart from
        # a passage about something that shares their name. A search for "Clay" cannot be resolved by
        # the word "Clay"; it is resolved by clay.com, or by Sequoia sitting in the same sentence.
        doss = build(c, pages, sites)
        corp_sections, corp_attempt = [], None
        try:
            from . import corpus as dd_corpus
            hits, corp_attempt = await dd_corpus.corpus_hits(
                os.environ.get("EIGEN_CORPUS_DSN", ""),
                name=c.get("name") or "", domain=c.get("website") or c.get("id") or "",
                cik=str(c.get("cik") or ""), ui=getattr(manifest, "ui", None),
                corroborators=_corroborators(c, doss))
            corp_sections = dd_corpus.as_sections(hits)
        except Exception as e:      # noqa: BLE001 — a corpus we cannot reach thins the dossier, never fails it
            corp_attempt = {"source": "Eigen corpus", "found": 0, "unit": "passages",
                            "result": f"unavailable ({str(e)[:60]})"}
        doss["sections"].extend(corp_sections)
        if corp_attempt:
            doss["attempted"].append(corp_attempt)
        legs = ["held"] + ([CORPUS_MARK] if corp_attempt else [])
        doss["spend"] = {"projection": proj, "depth": depth}
        if discovered:
            doss["discovered"] = True
            doss["attempted"].insert(0, {"source": "Web discovery", "found": 1, "unit": "company",
                                         "result": "not in the index — found and read from the web"})

        if body.public:
            # Keyless, identity-gated, and free — but a source being down must never cost the dossier.
            try:
                secs, att = await public_sources.gather(c)
                doss["sections"].extend(secs)
                doss["attempted"].extend(att)
            except Exception:      # noqa: BLE001
                doss["attempted"].append({"source": "Public sources", "found": 0, "unit": "sources",
                                          "result": "could not be reached on this run"})

        if depth in ("read", "full"):
            legs.append("read")
            pages = await _deep_crawl(su_store, c, pages)
            got = await _read_pages(providers, c, pages)
            doss["sections"].extend(got["sections"])
            doss["attempted"].append({"source": "Own-site read", "found": got["kept"], "unit": "claims",
                                      "result": _read_result(got)})

        if depth == "full":
            legs.append("web")
            from .web import read_web
            got = await read_web(c, manifest=manifest, subject_terms=_terms(c))
            doss["sections"].extend(got["sections"])
            doss["attempted"].extend(got["attempted"])
            doss["spend"]["web_dropped"] = got.get("dropped") or {}

        # Every leg has contributed; one heading, one card.
        doss["basis"] = "+".join(legs)
        doss["sections"] = merge_sections(doss["sections"])
        meta = await dstore.save(pool, doss, owner_id=await _owner(authorization),
                                 reason=depth if body.refresh or depth != "held" else "initial")
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


def _corroborators(c: dict, doss: dict) -> tuple[str, ...]:
    """Names that, appearing beside an ambiguous company name, say it IS that company.

    Everything here is something we already hold about THIS company: who is on record backing them,
    who runs it, and the words of their own one-liner. None of it is a guess.
    """
    out: list[str] = []
    for sec in doss.get("sections") or []:
        kind = sec.get("kind")
        if kind not in ("investors", "people"):
            continue
        for cl in sec.get("claims") or []:
            n = (cl.get("name") or "").strip()
            if len(n) >= 4:
                out.append(n)
    one = (c.get("one_liner") or "")
    out += [w for w in re.findall(r"[A-Za-z][A-Za-z0-9.\-]{4,}", one) if w.lower() not in _STOP]
    seen, uniq = set(), []
    for x in out:
        if x.lower() not in seen:
            seen.add(x.lower())
            uniq.append(x)
    return tuple(uniq[:24])


# Words a one-liner is full of that identify nobody.
_STOP = {"platform", "software", "company", "startup", "solution", "solutions", "service",
         "services", "technology", "technologies", "product", "products", "business", "customer",
         "customers", "teams", "their", "there", "which", "using", "build", "builds", "building",
         "helps", "helping", "making", "makes", "provides", "providing", "powered", "modern",
         "first", "world", "every", "across", "without", "better", "faster"}


def _llm(providers):
    """The kernel's domain picker wants a `.complete()` LLM; the startups providers expose JSON chat.
    When there is no such client the resolver still works — it falls back to name matching."""
    return getattr(providers, "complete_llm", None)


def _terms(c: dict) -> list[str]:
    from .assemble import _subject_terms
    return _subject_terms(c)


def _read_result(got: dict) -> str:
    if got["kept"]:
        return "found"
    if not got["read"]:
        return "no page long enough to read"
    top = sorted((got.get("dropped") or {}).items(), key=lambda kv: -kv[1])
    return "read, nothing survived the gates" + (f" ({top[0][0]})" if top else "")


async def _deep_crawl(su_store, c: dict, pages: list[dict]) -> list[dict]:
    """Crawl the pages a dossier wants that a card never needed. HTTP only — this spends nothing."""
    import asyncio

    from api.startups.sources import site
    website = c.get("website") or c.get("id") or ""
    if not website:
        return pages
    try:
        res = await asyncio.get_event_loop().run_in_executor(
            None, lambda: site.crawl(website, max_pages=MAX_READ_PAGES, want=site.DEEP_WANT))
    except Exception:      # noqa: BLE001 — a site that will not be read leaves the held pages in place
        return pages
    fresh = res.get("pages") or []
    if not fresh:
        return pages
    meta = {**(c.get("crawl") or {}), "at": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).isoformat(), "pages": len(fresh),
        "failed": len(res.get("failed") or []), "depth": "deep"}
    try:
        await su_store.save_pages(c["id"], fresh, meta)
    except Exception:      # noqa: BLE001 — a failed write must not lose the read
        pass
    by_url = {p["url"]: p for p in pages}
    for p in fresh:
        by_url[p["url"]] = p
    return list(by_url.values())


async def _read_pages(providers, c: dict, pages: list[dict]) -> dict:
    from .extract import read_pages
    llm = getattr(providers, "llm_json", None)
    if llm is None:
        return {"sections": [], "read": 0, "kept": 0, "dropped": {"no model configured": 1}}
    return await read_pages(llm, name=c.get("name") or c.get("id") or "", subject_terms=_terms(c),
                            pages=pages, own_domain=c.get("website") or c.get("id") or "",
                            max_pages=MAX_READ_PAGES)
