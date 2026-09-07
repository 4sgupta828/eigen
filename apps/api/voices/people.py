"""Resolve a named speaker to their own profile — or say plainly that we are guessing.

The index already holds 11,330 founders with LinkedIn or X links, harvested from their companies'
own team pages. When a card names one of them, the card can link straight to that person. When it
does not, we do NOT invent a profile URL: a guessed `linkedin.com/in/<slug>` is wrong often enough
to be a liability, and it is wrong in the worst way, by pointing at a real stranger. The fallback is
a clearly-labelled search, which is the pattern the startup cards already use.

A name shared by two people in the index resolves to NOBODY. Ambiguity is the same failure as a
wrong guess, just with an audit trail.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote_plus


def is_person(name: str) -> bool:
    n = " ".join((name or "").split())
    return 2 <= len(n.split()) <= 4 and bool(re.search(r"[A-Za-z]", n))


def profile_searches(name: str) -> dict:
    """Where to look for THIS PERSON, on each network's own people search.

    The first version searched the web for the name plus the SHOW, which reliably found the podcast
    episode — the one thing the reader already has. A profile search must be about the person and
    nothing else, and it must land on a people directory rather than on general results, or it
    returns the interview again.
    """
    n = " ".join((name or "").split())[:120]
    if not n:
        return {}
    return {
        # LinkedIn's own people search: the canonical place a profile lives
        "linkedin": "https://www.linkedin.com/search/results/people/?keywords=" + quote_plus(n),
        # X's people tab, not its post search, for the same reason
        "twitter": "https://x.com/search?f=user&q=" + quote_plus(n),
    }


async def links_for(conn, names: list[str]) -> dict[str, dict]:
    """{name → {linkedin?, twitter?, basis}} for the names we can resolve from the founder index."""
    wanted = [" ".join(n.split()) for n in names if is_person(n)]
    if not wanted:
        return {}
    rows = await conn.fetch(
        "SELECT f.name, f.links, f.company_id FROM su_founder f "
        "WHERE lower(f.name) = ANY($1::text[]) AND f.links IS NOT NULL",
        [n.lower() for n in wanted])

    seen: dict[str, set] = {}
    found: dict[str, dict] = {}
    for r in rows:
        key = " ".join((r["name"] or "").split()).lower()
        links = r["links"]
        links = json.loads(links) if isinstance(links, str) else (links or {})
        if not (links.get("linkedin") or links.get("twitter")):
            continue
        seen.setdefault(key, set()).add(r["company_id"])
        found[key] = {k: v for k, v in links.items() if k in ("linkedin", "twitter") and v}

    out: dict[str, dict] = {}
    for n in wanted:
        rec = found.get(n.lower())
        # two people of the same name resolve to nobody: a confident wrong link is worse than none
        if rec and len(seen.get(n.lower(), set())) == 1:
            out[n] = dict(rec, basis="index")
    return out


def decorate(moments: list[dict], resolved: dict[str, dict]) -> None:
    """Attach `person` to each moment: the profile we hold, or a labelled search when we do not.

    A held profile is printed ONLY when this episode also bound the guest to their own company. The
    index has one "Matthew Smith"; the world has thousands, and a name-only match would send a
    reader confidently to a stranger's LinkedIn. Corroboration — the guest named in the title AND
    their company named in the episode — is what earns a direct link. Everything else gets the
    labelled search, which is honest about being a search.
    """
    for m in moments:
        name = " ".join(str(m.get("speaker") or "").split())
        if not is_person(name):
            continue
        rec = resolved.get(name)
        corroborated = str(m.get("bind_basis") or "") == "guest_and_company"
        if rec and corroborated:
            m["person"] = dict(rec, name=name)
        else:
            m["person"] = {"name": name, "basis": "search", "search": profile_searches(name),
                           # say WHY there is no direct link, so the gap is legible rather than a bug
                           "why": ("we hold a profile for this name but this episode does not confirm "
                                   "it is the same person" if rec else "")}
