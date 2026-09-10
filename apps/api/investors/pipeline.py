"""Investor Search ingest jobs (docs/specs/investors.md §6-7, Step 0). Nothing here spends model credits.

Five jobs, in dependency order:
  adv     — the two monthly Form ADV zips → firms, with AUM, geo, fund-type flags, disclosure counts
  funds   — the Form D quarters, re-parsed keeping the pooled-fund fields → fund vehicles
  attach  — SPV drop + degree-capped GP clustering + evidenced attach (`vehicle_bound`, see cluster.py)
  link    — the startup index's investor slugs → firms, and the edges that come with them
  derive  — the read model: investor_type, fund facts, portfolio facts, co-investors, evidence strength
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict

from api.jobs import Jobs
from api.investors import cluster as cl
from api.investors.schema import SCHEMA
from api.investors.sources import adv as adv_src
from api.investors.sources import funds as funds_src
from api.investors.store import InvestorStore, display_name, domain_of, slug

_log = logging.getLogger(__name__)
JOBS = Jobs("iv_job", thread_prefix="investors")

# Head-office city → the metro a person would actually say. Deliberately short: a city we cannot place is
# `unknown`, which is honest, rather than a guess that puts a Denver firm in the Bay Area.
METROS = {
    "bay_area": ("san francisco", "palo alto", "menlo park", "mountain view", "sunnyvale", "san mateo",
                 "redwood city", "oakland", "berkeley", "santa clara", "san jose", "burlingame", "los altos",
                 "atherton", "woodside", "emeryville", "foster city"),
    "new_york": ("new york", "brooklyn", "manhattan", "new york city"),
    "boston": ("boston", "cambridge", "somerville", "waltham", "newton"),
    "los_angeles": ("los angeles", "santa monica", "venice", "pasadena", "el segundo", "culver city"),
    "seattle": ("seattle", "bellevue", "kirkland", "redmond"),
    "austin": ("austin",), "chicago": ("chicago",), "denver": ("denver", "boulder"),
    "miami": ("miami", "miami beach", "coral gables"), "london": ("london",),
    "bangalore": ("bangalore", "bengaluru"), "mumbai": ("mumbai", "bombay"), "delhi": ("delhi", "gurugram", "gurgaon", "noida"),
    "dubai": ("dubai",), "abu_dhabi": ("abu dhabi",), "singapore": ("singapore",),
    "tel_aviv": ("tel aviv", "tel aviv-yafo", "herzliya"), "paris": ("paris",), "berlin": ("berlin",),
    "toronto": ("toronto",), "sydney": ("sydney",), "hong_kong": ("hong kong",),
}
_CITY_TO_METRO = {c: m for m, cities in METROS.items() for c in cities}

COUNTRIES = {"united states": "us", "united kingdom": "uk", "india": "in", "united arab emirates": "ae",
             "singapore": "sg", "australia": "au", "israel": "il", "canada": "ca", "germany": "de",
             "france": "fr", "cayman islands": "ky", "hong kong": "hk", "japan": "jp", "china": "cn",
             "switzerland": "ch", "netherlands": "nl", "sweden": "se", "brazil": "br", "ireland": "ie",
             "luxembourg": "lu", "spain": "es", "italy": "it", "south korea": "kr", "korea, republic of": "kr"}


def country_token(name: str) -> str:
    n = (name or "").strip().lower()
    return COUNTRIES.get(n, slug(n, 24)) if n else ""


def metro_token(city: str) -> str:
    return _CITY_TO_METRO.get((city or "").strip().lower(), "")


def band_of(key: str, number: float | None) -> str:
    """The band token a numeric facet value falls in, or '' — the kernel owns the bands, this just reads them."""
    if number is None:
        return ""
    k = SCHEMA.key(key)
    if k is None or not k.bands:
        return ""
    for name, lo, hi in k.bands:
        if (lo is None or number >= lo) and (hi is None or number < hi):
            return name
    return ""


def num_fact(key: str, number: float | None, **kw) -> list[dict]:
    b = band_of(key, number)
    return [{"key": key, "value": b, "number": float(number), **kw}] if b else []


# --------------------------------------------------------------------------- identity
def mint_id(*, name: str, domain: str, crd: str, state: str, taken: set) -> str:
    """A stable, readable firm id that is never a bare domain and never a bare name.

    Order: the domain's own label (a16z.com → a16z) · the name · then disambiguated by state, then by CRD.
    The disambiguation matters — two firms printing the same name in two states are two firms, and a slug
    minted from a name alone would silently merge them (the failure the panel caught in v1 of the spec).
    """
    base = ""
    if domain:
        base = slug(domain.split(".")[0], 40)
    if not base:
        base = slug(name, 40)
    if not base:
        base = f"crd_{crd}"
    for cand in (base, f"{base}_{slug(state, 6)}" if state else "", f"crd_{crd}_{base}"[:60] if crd else ""):
        if cand and cand not in taken:
            return cand
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


def curated_brands() -> dict:
    """{brand slug → the fund's own portfolio URL} from the startup module's curated list.

    These slugs are the vocabulary the startup index's `investor` facet already speaks, and a human wrote
    each one beside the firm's own portfolio page — so they are the brand's name, and they are RESERVED.
    Without reserving them, ADV mints `a16z` for whichever registrant on a16z.com it reads first, which was
    "A16Z Perennial Management" (the wealth arm) — and then every a16z portfolio edge lands on the wrong card.
    """
    import json
    from pathlib import Path
    f = Path(__file__).resolve().parents[1] / "startups" / "data" / "portfolios.json"
    try:
        return {str(r["fund"]): str(r.get("url") or "") for r in json.loads(f.read_text())
                if r.get("fund") and str(r.get("kind")) == "investor"}
    except Exception:      # noqa: BLE001 — a missing curated list costs reservations, never the job
        return {}


async def _existing_index(store: InvestorStore) -> tuple[dict, dict, set]:
    pool = await store.pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, crd, domain FROM iv_firm")
    by_crd = {r["crd"]: r["id"] for r in rows if r["crd"]}
    by_dom = {r["domain"]: r["id"] for r in rows if r["domain"]}
    taken = {r["id"] for r in rows}
    existing_brands = {r["id"] for r in rows}
    taken |= {b for b in curated_brands() if b not in existing_brands}
    return by_crd, by_dom, taken


# --------------------------------------------------------------------------- job: adv
async def run_adv(store: InvestorStore, *, limit: int = 0, jid: int | None = None) -> dict:
    """Download the newest registered + exempt ADV zips and upsert every venture/PE-managing firm."""
    await store.ensure_schema()
    pair = adv_src.latest_pair()
    if not pair:
        return {"error": "no ADV zips found on the SEC index page"}
    index = await _existing_index(store)
    out = {"files": [], "firms": 0, "new": 0, "skipped_not_investor": 0, "no_domain": 0, "affiliates": 0}
    for label, kind, url in pair:
        blob = adv_src.download(url)
        if not blob:
            out["files"].append({"file": label, "error": "download failed"})
            continue
        rows = adv_src.rows(blob)
        n = await ingest_adv_rows(store, rows, index=index, out=out, limit=limit, jid=jid)
        out["files"].append({"file": label, "kind": kind, "rows": len(rows), "firms": n})
        if limit and out["firms"] >= limit:
            break
    return out


async def ingest_adv_rows(store: InvestorStore, rows: list[dict], *, index: tuple, out: dict,
                          limit: int = 0, jid: int | None = None) -> int:
    """The ADV row loop, separated from downloading so it can be run over local files and tested.

    `index` is the (by_crd, by_domain, taken) triple from `_existing_index`, carried ACROSS files so the
    registered and exempt registers resolve against one another rather than minting the same firm twice.
    """
    by_crd, by_dom, taken = index
    n = 0
    for r in rows:
        p = adv_src.parse_firm(r)
        if not p or not adv_src.is_investor(p):
            if p:
                out["skipped_not_investor"] = out.get("skipped_not_investor", 0) + 1
            continue
        # CRD is the register's own permanent id and the ONLY thing that merges two rows here. A shared
        # domain does NOT: a16z.com is the website of both Andreessen Horowitz and a16z Perennial Management,
        # different advisers running different asset classes, and merging them let the wealth arm take the
        # `a16z` card and type it `pe_fund`. A shared domain is recorded as an affiliation instead, which is
        # what it actually evidences.
        fid = by_crd.get(p["crd"])
        sibling = by_dom.get(p["domain"]) if p["domain"] else None
        if not fid:
            fid = mint_id(name=p["name"], domain=p["domain"], crd=p["crd"], state=p["hq_state"], taken=taken)
            taken.add(fid)
            out["new"] = out.get("new", 0) + 1
        by_crd[p["crd"]] = fid
        if p["domain"]:
            by_dom.setdefault(p["domain"], fid)
        else:
            out["no_domain"] = out.get("no_domain", 0) + 1
        await store.upsert_firm({
            "id": fid, "name": display_name(p["name"]), "legal_name": p["legal_name"], "crd": p["crd"],
            "cik": p["cik"], "site": p["site"], "domain": p["domain"], "hq_city": p["hq_city"],
            "hq_state": p["hq_state"], "hq_country": p["hq_country"], "entity_form": p["entity_form"],
            "fund_flags": p["funds"], "sources": adv_src.registers_of(p)})
        await store.add_alias(slug(p["name"]), fid, basis="adv_name")
        if sibling and sibling != fid:
            await store.relate(sibling, fid, "affiliate", source_url=p["site"])
            out["affiliates"] = out.get("affiliates", 0) + 1
        await store.put_facts(fid, _adv_facts(p), keys=["registered_with", "aum", "country", "state",
                                                        "metro", "regulatory_disclosures"])
        n += 1
        out["firms"] = out.get("firms", 0) + 1
        if jid and out["firms"] % 500 == 0:
            await JOBS.progress(store, jid, dict(out))
        if limit and out["firms"] >= limit:
            break
    return n


def _adv_facts(p: dict) -> list[dict]:
    url = f"https://adviserinfo.sec.gov/firm/summary/{p['crd']}"
    common = {"provenance": "adv", "source_url": url, "as_of": p.get("latest_filing_iso") or None}
    facts: list[dict] = [{"key": "registered_with", "value": r, "basis": "adv", **common}
                         for r in adv_src.registers_of(p)]
    if p.get("aum") is not None:
        facts += num_fact("aum", p["aum"], basis=p["aum_basis"], display=f"${p['aum']:,.0f}", **common)
    c = country_token(p.get("hq_country", ""))
    if c:
        facts.append({"key": "country", "value": c, "basis": "adv", **common})
    if p.get("hq_state") and c in ("us", "ca"):
        facts.append({"key": "state", "value": p["hq_state"].lower(), "basis": "adv", **common})
    m = metro_token(p.get("hq_city", ""))
    if m:
        facts.append({"key": "metro", "value": m, "basis": "adv", **common})
    d = int(p.get("disclosures") or 0)
    facts.append({"key": "regulatory_disclosures", "basis": "adv_item_11",
                  "value": "none_reported" if d == 0 else ("1_2" if d <= 2 else "3_plus"), **common})
    return facts


# --------------------------------------------------------------------------- job: funds
async def run_funds(store: InvestorStore, *, since: tuple = (2019, 1), quarters: list[str] | None = None,
                    jid: int | None = None) -> dict:
    """Re-parse the Form D quarters, keeping the pooled-fund fields the startup parser discards."""
    await store.ensure_schema()
    want = funds_src.list_quarters(tuple(since))
    if quarters:
        want = [(lab, url) for lab, url in want if lab in set(quarters)]
    out = {"quarters": 0, "filings": 0, "funds": 0, "spv": 0, "vc_pe": 0, "done": []}
    for lab, url in want:
        blob = funds_src.download_quarter(url)
        if not blob:
            out["done"].append({"quarter": lab, "error": "download failed"})
            continue
        recs = funds_src.parse_quarter(blob, quarter=lab)
        out["filings"] += len(recs)
        out["spv"] += sum(1 for r in recs if r["is_spv"])
        out["vc_pe"] += sum(1 for r in recs if funds_src.venture_or_pe(r))
        n = await store.upsert_funds(recs)
        out["funds"] += n
        out["quarters"] += 1
        out["done"].append({"quarter": lab, "filings": len(recs), "stored": n})
        if jid:
            await JOBS.progress(store, jid, dict(out))
    return out


# --------------------------------------------------------------------------- job: attach
async def run_attach(store: InvestorStore, *, jid: int | None = None) -> dict:
    """Cluster fund vehicles into managers and attach each cluster to a named firm where evidence allows."""
    await store.ensure_schema()
    pool = await store.pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""SELECT id, name, cik, state, first_sale, persons, is_spv
                                   FROM iv_fund WHERE fund_type IN ('Venture Capital Fund', 'Private Equity Fund')""")
        firms = [dict(r) for r in await conn.fetch("SELECT id, name, legal_name, cik, hq_state FROM iv_firm")]
    funds = []
    respv: list[tuple] = []
    for r in rows:
        import json as _json
        persons = r["persons"] if isinstance(r["persons"], list) else _json.loads(r["persons"] or "[]")
        # `is_spv` is DERIVED from the name, so it is recomputed here rather than trusted from the column.
        # That means improving the pattern takes effect on the next attach instead of requiring all thirty
        # quarters to be downloaded and re-parsed — which is how the trailing-series vehicles were fixed.
        spv = funds_src.is_spv(r["name"])
        if spv != r["is_spv"]:
            respv.append((r["id"], spv))
        funds.append({"id": r["id"], "name": r["name"], "cik": r["cik"] or "", "state": r["state"] or "",
                      "first_sale": str(r["first_sale"] or ""), "persons": persons, "is_spv": spv})
    async with pool.acquire() as conn:
        if respv:
            await conn.executemany("UPDATE iv_fund SET is_spv = $2 WHERE id = $1", respv)
        # Clear every attachment in scope before re-deciding. Without this the job is not idempotent: a
        # vehicle reclassified as an SPV drops out of clustering and therefore out of the update list, and
        # silently KEEPS the firm it was attached to on a previous run — which is why Okeanos still showed
        # 76 funds after 2,708 of its series vehicles had been reclassified.
        await conn.execute("""UPDATE iv_fund SET firm_id = NULL, cluster_id = '', match_method = '',
                              match_note = '' WHERE fund_type IN ('Venture Capital Fund', 'Private Equity Fund')""")
    assign = cl.cluster_funds(funds)
    groups: dict[str, list[dict]] = defaultdict(list)
    for f in funds:
        cid = assign.get(f["id"])
        if cid:
            groups[cid].append(f)
    out = {"funds": len(funds), "spv": sum(1 for f in funds if f["is_spv"]), "reclassified_spv": len(respv),
           "clusters": len(groups),
           "attached_clusters": 0, "attached_funds": 0, "split_clusters": 0, "by_method": {}}
    index = cl.build_firm_index(firms)
    updates: list[tuple] = []
    for i, (cid, members) in enumerate(groups.items()):
        per = cl.assign_cluster(members, index)
        got = set()
        for f in members:
            fid, method, note = per[f["id"]]
            updates.append((f["id"], fid, cid, method, note))
            if fid:
                out["attached_funds"] += 1
                out["by_method"][method] = out["by_method"].get(method, 0) + 1
                got.add(fid)
        if got:
            out["attached_clusters"] += 1
        if len(got) > 1:
            out["split_clusters"] = out.get("split_clusters", 0) + 1
        if jid and i % 500 == 0:
            await JOBS.progress(store, jid, dict(out))
    async with pool.acquire() as conn:
        await conn.executemany("""UPDATE iv_fund SET firm_id = $2, cluster_id = $3, match_method = $4,
                                  match_note = $5 WHERE id = $1""", updates)
    out["largest_cluster"] = max((len(v) for v in groups.values()), default=0)
    return out


# --------------------------------------------------------------------------- job: link
async def run_link(store: InvestorStore, *, jid: int | None = None) -> dict:
    """Bind the startup index's investor slugs to firms, and turn every bound slug into portfolio edges.

    The curated portfolio slugs (`api/startups/data/portfolios.json`) are canonical by construction — a human
    wrote them next to the fund's own portfolio URL — so they mint firms outright. Everything else is extractor
    output and only binds when it matches an alias or a firm name exactly; an unbound slug stays unbound and is
    counted, because a wrong link to a venture firm is worse than a missing one.
    """
    import json
    from pathlib import Path
    await store.ensure_schema()
    by_crd, by_dom, taken = await _existing_index(store)
    out = {"curated": 0, "affiliates": 0, "slugs": 0, "bound": 0, "unbound": 0, "edges": 0,
           "unbound_examples": []}

    pf = Path(__file__).resolve().parents[1] / "startups" / "data" / "portfolios.json"
    curated = {}
    try:
        for r in json.loads(pf.read_text()):
            if str(r.get("kind")) == "investor" and r.get("fund"):
                curated[str(r["fund"])] = str(r.get("url") or "")
    except Exception:      # noqa: BLE001 — a missing curated list costs links, never the job
        curated = {}
    for fund_slug, url in curated.items():
        dom = domain_of(url)
        # The brand is its own node, keyed by the curated slug. A registered adviser that happens to share the
        # domain is an AFFILIATE of the brand, not the brand itself — "AH Capital Management, L.L.C." and
        # "a16z Perennial Management" are both real, and neither of them is what a founder means by "a16z".
        fid = fund_slug
        await store.upsert_firm({"id": fid, "name": display_name(fund_slug.replace("_", " ").title()),
                                 "site": f"https://{dom}" if dom else "", "domain": dom,
                                 "sources": ["portfolio_page"]})
        await store.add_alias(fund_slug, fid, basis="curated", source_url=url)
        taken.add(fid)
        sibling = by_dom.get(dom) if dom else None
        if sibling and sibling != fid:
            await store.relate(fid, sibling, "affiliate", source_url=url)
            out["affiliates"] = out.get("affiliates", 0) + 1
        out["curated"] += 1

    pool = await store.pool()
    async with pool.acquire() as conn:
        slugs = [r["value"] for r in await conn.fetch(
            "SELECT DISTINCT value FROM su_fact WHERE key IN ('investor','lead_investor') AND value <> ''")]
        alias = {r["slug"]: r["firm_id"] for r in await conn.fetch("SELECT slug, firm_id FROM iv_alias")}
        out["slugs"] = len(slugs)
        bound = {s: alias[s] for s in slugs if s in alias}
        out["bound"], out["unbound"] = len(bound), len(slugs) - len(bound)
        out["unbound_examples"] = [s for s in slugs if s not in alias][:20]
        if bound:
            rows = await conn.fetch("""
                SELECT value, company_id, provenance, source_url, key
                FROM su_fact WHERE key IN ('investor','lead_investor') AND value = ANY($1)""", list(bound))
            edges = []
            for r in rows:
                basis = {"portfolio": "portfolio_page", "press": "press_round", "site": "company_site",
                         "news": "press_round"}.get(r["provenance"], "company_site")
                edges.append({"firm_id": bound[r["value"]], "company_id": r["company_id"], "basis": basis,
                              "role": "lead" if r["key"] == "lead_investor" else "investor",
                              "source_url": r["source_url"] or ""})
            for i in range(0, len(edges), 2000):
                out["edges"] += await store.put_edges(edges[i:i + 2000])
                if jid:
                    await JOBS.progress(store, jid, dict(out))
    return out


# --------------------------------------------------------------------------- job: derive
async def run_derive(store: InvestorStore, *, ids: list[str] | None = None, jid: int | None = None) -> dict:
    """Recompute the read model. Deterministic, idempotent, and the only writer of `observed` facts.

    Every observed fact carries its denominator — the number of companies it was measured over — because an
    observed number without its population is not a number this product is willing to render (§0).
    """
    await store.ensure_schema()
    pool = await store.pool()
    out = {"firms": 0, "with_funds": 0, "with_portfolio": 0}
    async with pool.acquire() as conn:
        firm_ids = ids or [r["id"] for r in await conn.fetch("SELECT id FROM iv_firm WHERE status = 'active'")]
        for fid in firm_ids:
            facts: list[dict] = []
            f = await conn.fetchrow("SELECT id, kind, crd, domain, sources, fund_flags FROM iv_firm WHERE id = $1", fid)
            if not f:
                continue
            funds = await conn.fetch("""SELECT fund_type, sold_usd, first_sale FROM iv_fund
                                        WHERE firm_id = $1 AND NOT is_spv ORDER BY first_sale DESC NULLS LAST""", fid)
            src = f"https://adviserinfo.sec.gov/firm/summary/{f['crd']}" if f["crd"] else ""
            if funds:
                out["with_funds"] += 1
                sizes = [x["sold_usd"] for x in funds if x["sold_usd"] is not None]
                years = [x["first_sale"].year for x in funds if x["first_sale"]]
                base = {"provenance": "form_d", "basis": "form_d", "source_url": "https://www.sec.gov/"}
                facts += num_fact("funds_count", float(len(funds)), **base)
                if sizes:
                    facts += num_fact("latest_fund_size", float(sizes[0]), display=f"${sizes[0]:,.0f}", **base)
                if years:
                    facts += num_fact("latest_fund_year", float(max(years)), **base)
                    facts += num_fact("first_fund_year", float(min(years)), **base)
                    import datetime as _dt
                    recent = max(years) >= _dt.date.today().year - 3
                    facts.append({"key": "still_deploying", "value": "yes_recent" if recent else "quiet", **base})
            ftypes = {x["fund_type"] for x in funds}
            latest = next((x["sold_usd"] for x in funds if x["sold_usd"] is not None), None)
            t = _investor_type(f, ftypes, latest)
            # A curated BRAND (a16z) carries no registration of its own, and its type stays UNKNOWN until one
            # of its own fund filings attaches. It is tempting to read the type off an affiliate that shares
            # the domain — but "a16z Perennial Management" is a wealth business, and typing the venture brand
            # `pe_fund` from it is precisely the subject-congruence failure this spec exists to prevent: the
            # evidence's subject is not the claim's subject. Unknown is the correct answer here.
            # ---- observed, over the companies we actually hold ----
            edges = await conn.fetch("SELECT DISTINCT company_id FROM iv_edge WHERE firm_id = $1", fid)
            n = len(edges)
            if n:
                out["with_portfolio"] += 1
                cids = [r["company_id"] for r in edges]
                obs = {"provenance": "derived", "basis": "derived_over_our_index", "denominator": n}
                facts += num_fact("portfolio_count", float(n), **obs)
                for src_key, dst_key in (("tech_area", "observed_sector"), ("stage", "observed_stage"),
                                         ("country", "observed_geo")):
                    vals = await conn.fetch("""SELECT value, count(DISTINCT company_id) AS n FROM su_fact
                                               WHERE company_id = ANY($1) AND key = $2 AND value <> ''
                                               GROUP BY 1 ORDER BY 2 DESC LIMIT 12""", cids, src_key)
                    facts += [{"key": dst_key, "value": v["value"], "display": str(v["n"]), **obs} for v in vals]
                co = await conn.fetch("""SELECT value, count(DISTINCT company_id) AS n FROM su_fact
                                         WHERE company_id = ANY($1) AND key = 'investor' AND value <> ''
                                         GROUP BY 1 ORDER BY 2 DESC LIMIT 24""", cids)
                mine = {r["slug"] for r in await conn.fetch("SELECT slug FROM iv_alias WHERE firm_id = $1", fid)}
                facts += [{"key": "co_investor", "value": v["value"], "display": str(v["n"]), **obs}
                          for v in co if v["value"] not in mine][:20]
            kinds = {"adv" if s.startswith("sec_") else s for s in (f["sources"] or [])}
            if funds:
                kinds.add("form_d")
            if n:
                kinds.add("edges")
            facts.append({"key": "evidence_strength", "provenance": "derived", "basis": "derived",
                          "value": "filing_backed" if ("form_d" in kinds or "adv" in kinds)
                          else ("two_sources" if len(kinds) > 1 else "single_source")})
            await store.put_facts(fid, facts, keys=[
                "funds_count", "latest_fund_size", "latest_fund_year", "first_fund_year", "still_deploying",
                "investor_type", "portfolio_count", "observed_sector", "observed_stage", "observed_geo",
                "co_investor", "evidence_strength"])
            out["firms"] += 1
            if jid and out["firms"] % 500 == 0:
                await JOBS.progress(store, jid, dict(out))
    return out


def _investor_type(firm, fund_types: set, latest_sold: float | None) -> str:
    """The type, from what is FILED — never from what the firm calls itself.

    Seed versus venture is decided by the size of the latest fund, because "seed fund" is a self-description
    that a $400M fund also uses. A firm with no filed fund and no register row gets no type at all.
    """
    if (firm.get("kind") or "firm") == "individual":
        return "angel"
    vc, pe = "Venture Capital Fund" in fund_types, "Private Equity Fund" in fund_types
    if vc and not pe:
        # Only a FILED fund size may call something a seed fund: "seed fund" is a self-description a $400M
        # fund uses too, and with no size we say `venture_fund` rather than guess small.
        if latest_sold is not None and latest_sold < 50e6:
            return "seed_fund"
        return "venture_fund"
    if pe and not vc:
        return "pe_fund"
    if vc and pe:
        return "venture_fund"
    # No fund filing attached yet — but the register itself states which kinds of fund this adviser runs, and
    # that is a filed fact in its own right. Without it a16z and Kleiner Perkins both render as "other", which
    # is the kind of wrong that makes a whole mode look broken.
    raw = firm.get("fund_flags") if hasattr(firm, "get") else None
    flags = raw if isinstance(raw, dict) else _loads(raw)
    if flags.get("vc"):
        return "venture_fund"
    if flags.get("pe"):
        return "pe_fund"
    srcs = set(firm.get("sources") or [])
    if srcs & {"sec_era", "sec_ria"}:
        return "other"
    return ""


def _loads(v):
    import json
    try:
        return json.loads(v or "{}")
    except Exception:      # noqa: BLE001
        return {}


RUNNERS = {"adv": run_adv, "funds": run_funds, "attach": run_attach, "link": run_link, "derive": run_derive}
NEEDS_PROV: set = set()          # Step 0 spends nothing; the model-backed jobs arrive in Step 4


async def start_job(store: InvestorStore, dsn: str, kind: str, params: dict) -> int:
    return await JOBS.start(store, dsn, kind, params, runners=RUNNERS,
                            store_factory=InvestorStore, needs_prov=NEEDS_PROV)


async def orphan_running_jobs(store: InvestorStore) -> int:
    return await JOBS.orphan_running(store)
