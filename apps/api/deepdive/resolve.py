"""Resolution — a name is not a company.

Everything DeepDive does afterwards is scoped to ONE canonical id, so getting the id wrong does not
produce a worse dossier, it produces a dossier about the wrong company. This module therefore has one
job and a bias: when the evidence does not single out a company, it REFUSES and hands back the
candidates rather than picking the most popular one.

Nothing here spends: it is three indexed reads against `su_company`.
"""
from __future__ import annotations

import re

# A name typed as a domain ("anthropic.com", "https://anthropic.com/about") is already an id.
_SCHEME = re.compile(r"^[a-z]+://", re.I)
_HOSTY = re.compile(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$", re.I)
# Words that carry no identity: two companies differing only by one of these are not distinguished.
_NOISE = ("inc", "inc.", "llc", "ltd", "ltd.", "limited", "corp", "corp.", "corporation", "co", "co.",
          "the", "company", "labs", "lab", "ai", "technologies", "technology", "tech", "systems", "software")


def as_domain(q: str) -> str:
    """The registrable-ish host if the query IS a url or hostname, else ""."""
    s = (q or "").strip().lower()
    if not s:
        return ""
    s = _SCHEME.sub("", s).split("/")[0].split("?")[0].strip().strip(".")
    if s.startswith("www."):
        s = s[4:]
    return s if _HOSTY.match(s) else ""


def norm(name: str) -> str:
    """A name reduced to its identifying tokens: casing, punctuation and suffixes dropped."""
    toks = [t for t in re.split(r"[^a-z0-9]+", (name or "").lower()) if t]
    keep = [t for t in toks if t not in _NOISE]
    return " ".join(keep or toks)


def _candidate(r: dict, basis: str) -> dict:
    return {"id": r["id"], "name": r.get("name") or r["id"], "website": r.get("website") or "",
            "one_liner": r.get("one_liner") or "", "hq": r.get("hq") or "", "basis": basis}


async def candidates(pool, q: str, *, limit: int = 8) -> list[dict]:
    """Companies we hold that the query could mean, best basis first, de-duplicated by id."""
    q = (q or "").strip()
    if not q:
        return []
    dom, n = as_domain(q), norm(q)
    out: list[dict] = []
    seen: set[str] = set()

    def add(rows, basis):
        for r in rows:
            if r["id"] not in seen:
                seen.add(r["id"])
                out.append(_candidate(dict(r), basis))

    cols = "id, name, website, one_liner, hq"
    async with pool.acquire() as conn:
        if dom:
            add(await conn.fetch(f"SELECT {cols} FROM su_company WHERE id = $1", dom), "domain")
        if n:
            # Exact identity match on the normalized name or any alias — the only "certain" text basis.
            add(await conn.fetch(
                f"SELECT {cols} FROM su_company WHERE lower(name) = $1 OR lower(legal_name) = $1 "
                f"OR $1 = ANY(SELECT lower(a) FROM unnest(aliases) a) LIMIT 20", q.lower()), "name")
            add(await conn.fetch(
                f"SELECT {cols} FROM su_company WHERE regexp_replace(lower(name), '[^a-z0-9]+', ' ', 'g') "
                f"= $1 LIMIT 20", n), "name")
            # A prefix sweep, kept last and clearly weaker: this is what makes a query AMBIGUOUS.
            add(await conn.fetch(
                f"SELECT {cols} FROM su_company WHERE lower(name) LIKE $1 ORDER BY length(name) LIMIT $2",
                n.split(" ")[0] + "%", limit), "prefix")
    return out[:limit]


async def resolve(pool, q: str) -> dict:
    """`{"status": "resolved"|"ambiguous"|"unknown", "company"?, "candidates": [...]}`.

    Resolved requires a SINGLE company on a certain basis (the query was a domain we hold, or it names
    the company exactly). Several exact matches, or only prefix guesses, is ambiguous — and ambiguous
    is a refusal, not a ranking problem: the caller must ask which one.
    """
    cands = await candidates(pool, q)
    certain = [c for c in cands if c["basis"] in ("domain", "name")]
    if len(certain) == 1:
        return {"status": "resolved", "company": certain[0], "candidates": cands}
    if not cands:
        return {"status": "unknown", "company": None, "candidates": [],
                "reason": "no company we hold matches that name"}
    return {"status": "ambiguous", "company": None, "candidates": cands,
            "reason": "more than one company could be meant — pick one" if certain
                      else "no exact match; these are the closest names we hold"}
