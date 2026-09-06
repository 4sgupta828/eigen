"""Roster's job index, shared — the hiring signal for companies roster already reads from public ATS boards.

Roster (the sibling product) keeps ~200k open postings from Greenhouse / Ashby / Lever / SmartRecruiters /
Workday boards. Its export (`scripts/export` over `railway ssh`, one row per (company, board)) is imported
here rather than re-fetched: `{company, source, n, url, roles[{title, location, department, url}]}`. A row
attaches to a company by its normalised NAME (roster keys companies by name slug); the board url is kept so
the crawl step can refresh from the ATS API directly. Provenance 'ats'."""
from __future__ import annotations

import json
import re

from .formd import name_norm


def _n(s: str) -> str:
    return name_norm(str(s or "").replace("-", " ").replace("_", " "))


def load(path: str) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def index_by_name(rows: list[dict]) -> dict[str, dict]:
    """One board per company name (the board with the most roles wins)."""
    out: dict[str, dict] = {}
    for r in rows:
        k = _n(r.get("company"))
        if not k:
            continue
        if k not in out or int(r.get("n") or 0) > int(out[k].get("n") or 0):
            out[k] = r
    return out


def board_of(row: dict) -> tuple[str, str] | None:
    """(ats, token) from the posting url when it is one of the three JSON-board ATSes."""
    u = str(row.get("url") or "")
    m = re.search(r"greenhouse\.io/(?:embed/job_board\?for=|v1/boards/)?([A-Za-z0-9_-]+)", u) if "greenhouse" in u else None
    if row.get("source") == "greenhouse" and m:
        return ("greenhouse", m.group(1))
    m = re.search(r"jobs\.lever\.co/([A-Za-z0-9_-]+)", u)
    if row.get("source") == "lever" and m:
        return ("lever", m.group(1))
    m = re.search(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)", u)
    if row.get("source") == "ashby" and m:
        return ("ashby", m.group(1))
    return None


async def attach(store, rows: list[dict]) -> dict:
    """Write each matched company's open-role count + roles (crawl.ats) with provenance 'ats'."""
    from datetime import date
    by = index_by_name(rows)
    pool = await store.pool()
    async with pool.acquire() as conn:
        comps = await conn.fetch("SELECT id, name, aliases, crawl FROM su_company WHERE status = 'active'")
    matched = 0
    for c in comps:
        keys = {_n(c["name"])} | {_n(a) for a in (c["aliases"] or [])} | {_n(c["id"].split(".")[0])}
        keys.discard("")
        row = next((by[k] for k in keys if k in by), None)
        if not row:
            continue
        roles = [{"title": x.get("title") or "", "location": x.get("location") or "", "department": x.get("department") or "", "url": x.get("url") or ""} for x in (row.get("roles") or []) if x.get("title")]
        n = int(row.get("n") or len(roles))
        crawl = json.loads(c["crawl"]) if isinstance(c["crawl"], str) else (c["crawl"] or {})
        ats = crawl.get("ats") or {}
        if not ats.get("roles"):
            crawl["ats"] = {"board": list(board_of(row)) if board_of(row) else [row.get("source"), ""], "roles": roles[:200], "n": n, "from": "roster"}
            async with pool.acquire() as conn:
                await conn.execute("UPDATE su_company SET crawl = $2::jsonb, sources = CASE WHEN 'roster_ats' = ANY(sources) THEN sources ELSE array_append(sources, 'roster_ats') END WHERE id = $1", c["id"], json.dumps(crawl))
        await store.replace_facts(c["id"], "ats", [{"key": "hiring", "number": float(n), "display": f"{n} open roles", "basis": "ats_board",
                                                    "quote": "; ".join(r["title"][:60] for r in roles[:8]), "source_url": row.get("url") or "", "as_of": date.today()}], keys=["hiring"])
        matched += 1
    return {"boards": len(by), "companies_matched": matched}
