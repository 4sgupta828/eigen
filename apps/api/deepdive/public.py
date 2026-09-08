"""Keyless public sources, looked up BY IDENTIFIER for one company.

The inventory's finding: eigen holds 28 connectors and not one of them is ever invoked for a NAMED
company — they are ingest-time and topic-keyed. This module closes that gap for the sources that need
no API key, so a dive costs nothing but a few HTTP calls.

Every lookup here is fail-safe and identity-gated:
- a source that errors, rate-limits or returns nothing yields an `attempted` row saying so, never an
  exception and never a silent omission;
- an entity is only accepted when its own identifiers agree with ours (Wikidata's official website
  must be the domain we resolved, EDGAR is keyed by CIK). A near-match on a name is REFUSED — the
  investor-resolution work already taught us what "gfc" matches when you let a name alone decide.

Nothing here calls a model.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote

from eigen_vertical_tech.connectors._http import HttpStrategy

_HTTP = HttpStrategy(max_retries=2, base_delay=1.0)

# EDGAR's own guidance: identify yourself. `_http` already sends EIGEN_HTTP_CONTACT as the UA.
_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_WBSEARCH = "https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&language=en&type=item&limit=5&search={q}"
_WBGET = "https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&props=claims|labels|descriptions&ids={qid}"
_GH_ORG = "https://api.github.com/orgs/{org}"
_GH_REPOS = "https://api.github.com/orgs/{org}/repos?per_page=30&sort=updated"

# The filing types worth naming in a dossier, and what each one IS. A 10-K is audited; an S-1 is a
# registration; a Form D is an exempt offering. Printing them under one word would be the exact
# intent-vs-fact blur the standing directive forbids.
_FORM_MEANING = {
    "10-K": "annual report (audited)", "10-Q": "quarterly report", "8-K": "material event",
    "S-1": "IPO registration", "S-1/A": "IPO registration (amended)", "20-F": "annual report (foreign issuer)",
    "D": "exempt offering (Form D)", "D/A": "exempt offering (amended)", "424B4": "IPO prospectus",
    "DEF 14A": "proxy statement", "SC 13D": "beneficial ownership", "SC 13G": "passive ownership",
}
_FORMS_WANTED = tuple(_FORM_MEANING)


def _attempt(source: str, found: int, unit: str, result: str = "") -> dict:
    return {"source": source, "found": found, "unit": unit,
            "result": result or ("found" if found else "nothing found")}


async def _json(url: str, **opts):
    return json.loads(await _HTTP.fetch(url, **opts))


# ---------------------------------------------------------------------------- SEC
async def edgar_filings(cik, *, limit: int = 25) -> tuple[list[dict], dict]:
    """Every filing EDGAR lists for this CIK — not just the Form Ds we store.

    A private startup usually has only Form Ds; a company that has filed an S-1 or a 10-K has a
    different evidence class available, and that difference is itself worth showing.
    """
    if not cik:
        return [], _attempt("SEC EDGAR (all filings)", 0, "filings", "no CIK — not an SEC filer we know of")
    try:
        d = await _json(_SUBMISSIONS.format(cik=int(cik)))
    except Exception:      # noqa: BLE001 — a source that is down is a source we say nothing about
        return [], _attempt("SEC EDGAR (all filings)", 0, "filings", "unavailable")
    recent = ((d.get("filings") or {}).get("recent") or {})
    forms, dates, accs, docs = (recent.get("form") or [], recent.get("filingDate") or [],
                                recent.get("accessionNumber") or [], recent.get("primaryDocument") or [])
    out = []
    for i, form in enumerate(forms):
        if form not in _FORMS_WANTED:
            continue
        acc = accs[i] if i < len(accs) else ""
        out.append({"claim": f"{form} — {_FORM_MEANING.get(form, 'filing')}",
                    "form": form, "filing_date": dates[i] if i < len(dates) else "",
                    "register": "filed", "attribution": "SEC EDGAR",
                    "source_url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/"
                                  + (docs[i] if i < len(docs) else "")})
        if len(out) >= limit:
            break
    return out, _attempt("SEC EDGAR (all filings)", len(out), "filings")


# ---------------------------------------------------------------------------- Wikidata
_P = {"P571": "founded", "P112": "founder", "P169": "chief executive", "P1128": "employees",
      "P452": "industry", "P749": "parent organisation", "P355": "subsidiary", "P414": "listed on",
      "P159": "headquarters", "P856": "official website", "P1454": "legal form", "P2139": "revenue"}


def _host(u: str) -> str:
    return re.sub(r"^www\.", "", (u or "").split("//")[-1].split("/")[0].lower())


def _claim_values(ent: dict, pid: str) -> list[str]:
    vals = []
    for c in (ent.get("claims") or {}).get(pid, []):
        dv = (((c.get("mainsnak") or {}).get("datavalue") or {}).get("value"))
        if isinstance(dv, str):
            vals.append(dv)
        elif isinstance(dv, dict):
            if "time" in dv:
                vals.append(str(dv["time"]).lstrip("+")[:10])
            elif "amount" in dv:
                vals.append(str(dv["amount"]).lstrip("+"))
            elif "id" in dv:
                vals.append(dv["id"])          # a QID: shown only when we can label it
    return vals


async def wikidata_profile(name: str, domain: str) -> tuple[list[dict], dict]:
    """Structured profile, accepted ONLY when Wikidata's own official-website property is our domain.

    That gate is the whole point. Name search alone would happily hand back a bank, a film or a
    Dutch news site for a three-letter company name.
    """
    if not name:
        return [], _attempt("Wikidata", 0, "profiles", "no name to search")
    try:
        hits = (await _json(_WBSEARCH.format(q=quote(name)))).get("search") or []
    except Exception:      # noqa: BLE001
        return [], _attempt("Wikidata", 0, "profiles", "unavailable")
    for h in hits[:5]:
        qid = h.get("id")
        if not qid:
            continue
        try:
            ent = ((await _json(_WBGET.format(qid=qid))).get("entities") or {}).get(qid) or {}
        except Exception:      # noqa: BLE001
            continue
        sites = [_host(u) for u in _claim_values(ent, "P856")]
        if not domain or _host(domain) not in sites:
            continue                                   # identity not proven — do not accept it
        rows = []
        for pid, lbl in _P.items():
            if pid in ("P856",):
                continue
            for v in _claim_values(ent, pid)[:4]:
                if str(v).startswith("Q"):             # an unlabelled entity id says nothing to a reader
                    continue
                rows.append({"claim": f"{lbl}: {v}", "register": "stated",
                             "attribution": "Wikidata (community reference)",
                             "source_url": f"https://www.wikidata.org/wiki/{qid}"})
        return rows, _attempt("Wikidata", len(rows), "properties")
    return [], _attempt("Wikidata", 0, "profiles", "no entity whose official site is this company")


# ---------------------------------------------------------------------------- GitHub
async def github_org(domain: str, name: str) -> tuple[list[dict], dict]:
    """Public code presence, accepted only when the org's blog/website is our domain.

    Keyless GitHub is ~10 requests a minute, so this is two calls and it gives up quietly.
    """
    slug = re.sub(r"[^a-z0-9-]", "", (name or "").lower().replace(" ", "-"))
    label = _host(domain).split(".")[0]
    # Orgs rarely sit at the obvious spelling — Anthropic's is `anthropics`. Try the few shapes that
    # actually occur; the website gate below is what decides, so a wrong guess costs one 404.
    guesses = [g for g in dict.fromkeys([slug, label, slug + "s" if slug else "", slug + "-ai" if slug else ""]) if g]
    if not guesses:
        return [], _attempt("GitHub", 0, "repos", "no org to look up")
    org, hit = None, ""
    for g in guesses[:4]:
        try:
            cand = await _json(_GH_ORG.format(org=quote(g)))
        except Exception:      # noqa: BLE001
            continue
        if not domain or _host(cand.get("blog") or "") == _host(domain):
            org, hit = cand, g
            break
    if org is None:
        return [], _attempt("GitHub", 0, "repos", "no public org whose site is this company")
    try:
        repos = await _json(_GH_REPOS.format(org=quote(hit)))
    except Exception:      # noqa: BLE001
        repos = []
    rows = []
    for r in sorted(repos, key=lambda x: -int(x.get("stargazers_count") or 0))[:8]:
        rows.append({"claim": f"{r.get('name')} — {int(r.get('stargazers_count') or 0):,} stars"
                              + (f" · {r.get('language')}" if r.get("language") else ""),
                     "register": "filed",       # a star count is a counted public fact, not a claim
                     "attribution": "GitHub", "source_url": r.get("html_url") or ""})
    return rows, _attempt("GitHub", len(rows), "repos")


async def gather(company: dict) -> tuple[list[dict], list[dict]]:
    """Run every keyless source for one company. Returns (sections, attempted).

    Sequential on purpose: these are polite public APIs and a dive is one company, not a sweep.
    """
    cid = company.get("id") or ""
    domain = company.get("website") or cid
    name = company.get("name") or cid
    sections, attempted = [], []

    filings, a = await edgar_filings(company.get("cik"))
    attempted.append(a)
    if filings:
        sections.append({"title": "What they have filed", "kind": "filed", "claims": filings,
                         "note": "every filing EDGAR lists — an exempt offering and an audited annual report are not the same evidence"})

    wd, a = await wikidata_profile(name, domain)
    attempted.append(a)
    if wd:
        sections.append({"title": "Reference profile", "kind": "stated", "claims": wd,
                         "note": "community reference data, accepted only because its official site is this company's domain"})

    gh, a = await github_org(domain, name)
    attempted.append(a)
    if gh:
        sections.append({"title": "Public code", "kind": "stated", "claims": gh})

    return sections, attempted
