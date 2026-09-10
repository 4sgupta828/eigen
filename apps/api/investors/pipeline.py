"""Investor Search ingest jobs (docs/specs/investors.md §6-7, Step 0). Nothing here spends model credits.

Five jobs, in dependency order:
  adv     — the two monthly Form ADV zips → firms, with AUM, geo, fund-type flags, disclosure counts
  funds   — the Form D quarters, re-parsed keeping the pooled-fund fields → fund vehicles
  attach  — SPV drop + degree-capped GP clustering + evidenced attach (`vehicle_bound`, see cluster.py)
  link    — the startup index's investor slugs → firms, and the edges that come with them
  derive  — the read model: investor_type, fund facts, portfolio facts, co-investors, evidence strength
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import defaultdict

from api.jobs import Jobs
from api.investors import cluster as cl
from api.investors.schema import SCHEMA
from api.investors.sources import adv as adv_src
from api.investors.sources import funds as funds_src
from api.investors.store import InvestorStore, display_name, domain_of, now_iso, slug

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
    out = {"curated": 0, "merged_into_registrant": 0, "affiliates": 0, "slugs": 0, "bound": 0, "unbound": 0,
           "edges": 0, "unbound_examples": []}

    pf = Path(__file__).resolve().parents[1] / "startups" / "data" / "portfolios.json"
    curated = {}
    try:
        for r in json.loads(pf.read_text()):
            if str(r.get("kind")) == "investor" and r.get("fund"):
                curated[str(r["fund"])] = str(r.get("url") or "")
    except Exception:      # noqa: BLE001 — a missing curated list costs links, never the job
        curated = {}
    # Which registered firms sit on each curated brand's domain, and what brand each of them reduces to.
    async with (await store.pool()).acquire() as conn:
        same_domain: dict = defaultdict(list)
        for r in await conn.fetch("SELECT id, name, legal_name, domain FROM iv_firm WHERE domain <> ''"):
            same_domain[r["domain"]].append(dict(r))

    for fund_slug, url in curated.items():
        dom = domain_of(url)
        # If a registered firm on this domain reduces to exactly this brand, they are the same firm and the
        # curated slug is one of its names — "felicis" and "Felicis Ventures Management Company" are not two
        # investors. Aliasing rather than minting is what stops the same fund appearing twice in a result.
        # The reduction has to be exact: "a16z" does not reduce "A16Z Perennial Management" (which strips to
        # "a16z perennial", a different business), so that pair stays two cards, as it should.
        twin = next((f for f in same_domain.get(dom, [])
                     if any(slug(cand) == fund_slug for cand, _ in cl.brand_variants(f))), None)
        if twin:
            await store.add_alias(fund_slug, twin["id"], basis="curated_brand", source_url=url)
            out["curated"] += 1
            out["merged_into_registrant"] = out.get("merged_into_registrant", 0) + 1
            continue
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
                SELECT f.value, f.company_id, f.provenance, f.source_url, f.key,
                       c.name AS company_name, c.website
                FROM su_fact f LEFT JOIN su_company c ON c.id = f.company_id
                WHERE f.key IN ('investor','lead_investor') AND f.value = ANY($1)""", list(bound))
            edges = []
            for r in rows:
                basis = {"portfolio": "portfolio_page", "press": "press_round", "site": "company_site",
                         "news": "press_round"}.get(r["provenance"], "company_site")
                edges.append({"firm_id": bound[r["value"]], "company_id": r["company_id"], "basis": basis,
                              "role": "lead" if r["key"] == "lead_investor" else "investor",
                              # the company's name travels onto the edge so a portfolio renders without a join
                              "company_name": company_label(r["company_name"] or "", r["company_id"]),
                              "company_site": r["website"] or f"https://{r['company_id']}",
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
            # A curated BRAND (a16z) carries no registration of its own, and its type stays UNKNOWN until one
            # of its own fund filings attaches. It is tempting to read the type off an affiliate that shares
            # the domain — but "a16z Perennial Management" is a wealth business, and typing the venture brand
            # `pe_fund` from it is precisely the subject-congruence failure this spec exists to prevent: the
            # evidence's subject is not the claim's subject. Unknown is the correct answer here.
            t = _investor_type(f, ftypes, latest)
            if t:
                facts.append({"key": "investor_type", "value": t, "basis": "derived", "provenance": "derived",
                              "source_url": src})
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
            # People and portfolio counts belong on the card, so they are facts like any other. `people_count`
            # is observed over what the team page listed — a firm's own page is exhaustive for its own staff
            # in a way nothing else here is, so this denominator is the page rather than our index.
            npeople = await conn.fetchval("SELECT count(*) FROM iv_person WHERE firm_id = $1", fid) or 0
            if npeople:
                facts += num_fact("people_count", float(npeople), provenance="site", basis="team_page",
                                  denominator=int(npeople))
                roles = await conn.fetch("""SELECT role, count(*) n FROM iv_person WHERE firm_id = $1
                                            AND role <> '' GROUP BY 1 ORDER BY 2 DESC LIMIT 8""", fid)
                facts += [{"key": "team_role", "value": r["role"], "display": str(r["n"]),
                           "provenance": "site", "basis": "team_page"} for r in roles]

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
                "co_investor", "evidence_strength", "people_count", "team_role"])
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



# --------------------------------------------------------------------------- job: sites
# What a firm's own site is asked for. `team` and `portfolio` are the two that matter and neither exists in
# the startup crawler's vocabulary (`site.py:_WANT` knows about/team/customers/pricing/careers/press) — a
# fund has no pricing page and its portfolio page is the whole point.
FIRM_WANT = (
    ("team", ("team", "people", "our-team", "our-people", "partners", "who-we-are", "about-us", "staff",
              "leadership", "members")),
    ("portfolio", ("portfolio", "companies", "investments", "our-companies", "our-portfolio", "our-investments",
                   "founders", "family")),
    ("about", ("about", "about-us", "company", "our-story", "mission", "approach", "thesis", "philosophy")),
    ("contact", ("contact", "contact-us", "pitch", "submit", "apply", "get-in-touch", "connect")),
)


async def run_sites(store: InvestorStore, *, limit: int = 400, recrawl_days: int = 90,
                    ids: list[str] | None = None, jid: int | None = None) -> dict:
    """Crawl each firm's own site — politely, and only the four pages a fund card needs.

    Reuses the startup module's fetcher (robots first, one request per host per two seconds, byte cap, a
    real User-Agent with a contact address) so there is one crawling policy in this codebase, not two.
    """
    from api.startups.sources import site as site_src
    await store.ensure_schema()
    pool = await store.pool()
    async with pool.acquire() as conn:
        if ids:
            rows = await conn.fetch("SELECT id, site, domain FROM iv_firm WHERE id = ANY($1)", ids)
        else:
            rows = await conn.fetch("""SELECT id, site, domain FROM iv_firm
                                       WHERE status = 'active' AND domain <> ''
                                         AND (crawl->>'at' IS NULL OR (crawl->>'at')::timestamptz < now() - ($1 || ' days')::interval)
                                       ORDER BY (SELECT count(*) FROM iv_edge e WHERE e.firm_id = iv_firm.id) DESC,
                                                id LIMIT $2""", str(recrawl_days), limit)
    out = {"of": len(rows), "crawled": 0, "pages": 0, "failed": 0, "with_team": 0, "with_portfolio": 0}
    for i, r in enumerate(rows):
        try:
            got = await asyncio.to_thread(site_src.crawl, r["site"] or f"https://{r['domain']}",
                                          max_pages=6, want=FIRM_WANT)
        except Exception as e:      # noqa: BLE001 — one bad site never stops the sweep
            out["failed"] += 1
            await store.note_crawl(r["id"], {"at": now_iso(), "error": str(e)[:200]})
            continue
        pages = got.get("pages") or []
        if pages:
            out["crawled"] += 1
            out["pages"] += await store.put_pages(r["id"], pages)
        kinds = [p.get("kind") for p in pages]
        out["with_team"] += 1 if "team" in kinds else 0
        out["with_portfolio"] += 1 if "portfolio" in kinds else 0
        if not pages:
            out["failed"] += 1
        await store.note_crawl(r["id"], {"at": now_iso(), "pages": kinds,
                                         "failed": [f.get("kind") for f in (got.get("failed") or [])]})
        if jid and i % 25 == 0:
            await JOBS.progress(store, jid, dict(out))
    return out


# --------------------------------------------------------------------------- job: people
async def run_people(store: InvestorStore, *, ids: list[str] | None = None, jid: int | None = None) -> dict:
    """Read the crawled team pages into named people with the profile links the page printed (no model call)."""
    from api.investors.sources import people as people_src
    await store.ensure_schema()
    pool = await store.pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""SELECT p.firm_id, p.url, p.html, v.domain
                                   FROM iv_page p JOIN iv_firm v ON v.id = p.firm_id
                                   WHERE p.kind IN ('team', 'about') AND p.html <> ''
                                     AND ($1::text[] IS NULL OR p.firm_id = ANY($1))""",
                                ids)
    by_firm: dict = defaultdict(list)
    for r in rows:
        by_firm[r["firm_id"]].append(r)
    out = {"firms": 0, "with_people": 0, "people": 0, "with_links": 0}
    for i, (fid, pages) in enumerate(by_firm.items()):
        found: dict = {}
        for pg in pages:
            for person in people_src.parse_team(pg["html"], base_domain=pg["domain"]):
                slot = found.setdefault(person["name"], person)
                slot.setdefault("source_url", pg["url"])
                slot["links"] = {**person.get("links", {}), **slot.get("links", {})}
                if not slot.get("role"):
                    slot["role"], slot["title"] = person.get("role", ""), person.get("title", "")
        out["firms"] += 1
        if found:
            out["with_people"] += 1
            out["people"] += await store.put_people(fid, list(found.values()))
            out["with_links"] += sum(1 for p in found.values()
                                     if p["links"].get("linkedin") or p["links"].get("x"))
        if jid and i % 100 == 0:
            await JOBS.progress(store, jid, dict(out))
    return out


# --------------------------------------------------------------------------- job: portfolio
# Anchor text on a portfolio page is often not the company's name: a logo grid links "Visit Website", an
# arrow, or the bare domain. A card that reads "Visit Website · Visit Website · Visit Website" is useless, so
# a name that carries no identity is replaced by one derived from the domain, which always does.
_GENERIC_LABEL = re.compile(r"(?i)^[\s.\-—→›»]*(visit(\s+(web)?site)?|website|learn\s+more|read\s+more|view|more"
                            r"|link|open|see\s+more|company|profile|details|→|›|»|\W*)[\s.\-—→›»]*$")


def company_label(name: str, domain: str) -> str:
    """The company's name as a person would write it — from the anchor text when it says anything, else the
    domain's own label ("about.sourcegraph.com" -> "Sourcegraph")."""
    n = (name or "").strip()
    # Screen-reader suffixes ride along in the anchor text: "aaru.com/ (opens in new tab)".
    n = re.sub(r"(?i)\s*[\(\[]?\s*(opens?\s+in\s+(a\s+)?new\s+(tab|window)|new\s+window|external\s+link)"
               r"\s*[\)\]]?\s*$", "", n).strip()
    n = re.sub(r"[\s\-—→›»/]+$", "", n.lstrip(".\u2022-— ")).strip()
    looks_like_domain = bool(re.fullmatch(r"[a-z0-9.\-]+\.[a-z]{2,}", n.lower()))
    if n and not looks_like_domain and not _GENERIC_LABEL.match(n):
        return n[:120]
    label = (domain or "").split(".")[0]
    return (label[:1].upper() + label[1:]) if label else (n[:120] or domain)


async def run_portfolio(store: InvestorStore, *, ids: list[str] | None = None, jid: int | None = None) -> dict:
    """Read each crawled portfolio page structurally into firm -> company edges (no model call).

    Reuses the startup module's portfolio reader, which takes links and embedded JSON only and denies social,
    press and hosting domains. The edge means AFFILIATION — the firm asserting its own portfolio — which is
    not the same as participating in a round, and the card labels it that way.
    """
    from api.startups.sources import portfolio as pf
    from api.startups.sources.http import registrable_domain
    await store.ensure_schema()
    pool = await store.pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""SELECT p.firm_id, p.url, p.html, v.domain
                                   FROM iv_page p JOIN iv_firm v ON v.id = p.firm_id
                                   WHERE p.kind = 'portfolio' AND p.html <> ''
                                     AND ($1::text[] IS NULL OR p.firm_id = ANY($1))""", ids)
    out = {"pages": len(rows), "firms": 0, "edges": 0, "skipped_own_domain": 0}
    seen_firms = set()
    for i, r in enumerate(rows):
        try:
            cands = pf.parse_page(r["html"], r["url"])
        except Exception:      # noqa: BLE001
            continue
        edges = []
        for c in cands:
            dom = registrable_domain(str(c.get("website") or ""))
            if not dom or dom == r["domain"]:
                out["skipped_own_domain"] += 1
                continue
            edges.append({"firm_id": r["firm_id"], "company_id": dom, "basis": "portfolio_page",
                          "role": "portfolio_affiliation",
                          "company_name": company_label(str(c.get("name") or ""), dom),
                          "company_site": f"https://{dom}", "source_url": r["url"]})
        if edges:
            seen_firms.add(r["firm_id"])
            out["edges"] += await store.put_edges(edges)
        if jid and i % 25 == 0:
            await JOBS.progress(store, jid, dict(out))
    out["firms"] = len(seen_firms)
    return out



# --------------------------------------------------------------------------- job: profiles
# How many of a firm's own people-pages one run will fetch. A fund's senior bench is small; this is a cap on
# politeness, not on ambition, and at one request per host every two seconds it bounds the time per firm.
MAX_PROFILE_FETCHES = 12


async def run_profiles(store: InvestorStore, *, limit: int = 200, ids: list[str] | None = None,
                       jid: int | None = None) -> dict:
    """Follow each person's own page on the firm's site to get their LinkedIn and X (no model call).

    The team page names people; their individual pages carry the links. Only people who have a profile link
    and no social links yet are fetched, so a re-run costs nothing for anyone already resolved.
    """
    from api.investors.sources import people as people_src
    from api.startups.sources import http as http_src
    await store.ensure_schema()
    pool = await store.pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.id, p.firm_id, p.name, p.links, v.domain
            FROM iv_person p JOIN iv_firm v ON v.id = p.firm_id
            WHERE p.links ? 'profile' AND (NOT (p.links ? 'linkedin') OR p.role = '')
              AND ($1::text[] IS NULL OR p.firm_id = ANY($1))
            ORDER BY p.firm_id, CASE p.role WHEN 'founding_partner' THEN 0 WHEN 'managing_partner' THEN 1
                     WHEN 'general_partner' THEN 2 WHEN 'founder' THEN 3 WHEN 'partner' THEN 4 ELSE 8 END
            LIMIT $2""", ids, limit * MAX_PROFILE_FETCHES)
    per_firm: dict = defaultdict(int)
    out = {"of": len(rows), "fetched": 0, "resolved": 0, "linkedin": 0, "x": 0, "roles": 0}
    for i, r in enumerate(rows):
        if per_firm[r["firm_id"]] >= MAX_PROFILE_FETCHES:
            continue
        links = r["links"] if isinstance(r["links"], dict) else _loads(r["links"])
        url = links.get("profile")
        if not url:
            continue
        per_firm[r["firm_id"]] += 1
        out["fetched"] += 1
        try:
            f = await asyncio.to_thread(http_src.get, url)
        except Exception:      # noqa: BLE001 — one dead profile page never stops the sweep
            continue
        if not f.ok:
            continue
        got = people_src.parse_profile_links(f.text, r["name"], firm_domain=r["domain"] or "")
        if not got:
            continue
        out["resolved"] += 1
        out["linkedin"] += 1 if got.get("linkedin") else 0
        out["x"] += 1 if got.get("x") else 0
        role, title = got.pop("role", ""), got.pop("title", "")
        out["roles"] = out.get("roles", 0) + (1 if role else 0)
        async with pool.acquire() as conn:
            await conn.execute("""UPDATE iv_person SET links = links || $2::jsonb,
                                    role = CASE WHEN role = '' THEN $3 ELSE role END,
                                    title = CASE WHEN title = '' THEN $4 ELSE title END
                                  WHERE id = $1""", r["id"], _jsonl(got), role, title[:80])
        if jid and i % 25 == 0:
            await JOBS.progress(store, jid, dict(out))
    return out


def _jsonl(v) -> str:
    import json
    return json.dumps(v)


RUNNERS = {"adv": run_adv, "funds": run_funds, "attach": run_attach, "link": run_link, "derive": run_derive,
           "sites": run_sites, "people": run_people, "portfolio": run_portfolio,
           "profiles": run_profiles}
NEEDS_PROV: set = set()          # Step 0 spends nothing; the model-backed jobs arrive in Step 4


async def start_job(store: InvestorStore, dsn: str, kind: str, params: dict) -> int:
    return await JOBS.start(store, dsn, kind, params, runners=RUNNERS,
                            store_factory=InvestorStore, needs_prov=NEEDS_PROV)


async def orphan_running_jobs(store: InvestorStore) -> int:
    return await JOBS.orphan_running(store)
