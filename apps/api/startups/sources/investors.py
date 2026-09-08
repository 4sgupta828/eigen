"""Resolve an investor slug to the firm's own site — or leave it unresolved.

The investor facet stores slugs (`slow_ventures`, `8vc`) because that is how the affiliation arrived.
A card should show a name and link to the firm, which needs a site we can trust.

Two sources, in order:
1. The fund portfolio pages we already crawl. Verified by construction: we read that page.
2. The keyless name→domain suggester, behind a NAME GATE. Ungated it is confidently wrong in a way
   that matters: it resolves "gfc" to GF Securities, "8vc" to Virginia's Community Colleges and
   "accel" to Accela. The gate requires the slug's words to be a leading WORD sequence of the
   suggested name, so "bessemer" may resolve to "Bessemer Venture Partners" while "accel" may not
   resolve to "Accela".

Anything unresolved stays unresolved. A wrong link to a venture firm is worse than a plain name.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import http
from .lookup import suggest

_SKIP_DOMAINS = {"linkedin.com", "twitter.com", "x.com", "crunchbase.com", "facebook.com",
                 "wikipedia.org", "youtube.com", "medium.com", "github.com"}


def words(s: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", (s or "").lower()) if w]


def display_name(slug: str) -> str:
    """`slow_ventures` → `Slow Ventures`; acronyms we cannot case are left alone."""
    parts = [p for p in re.split(r"[_\-]+", (slug or "").strip()) if p]
    out = []
    for p in parts:
        out.append(p if (p.isupper() or any(c.isdigit() for c in p)) else p.capitalize())
    return " ".join(out)


def name_matches(slug: str, suggested: str) -> bool:
    """The slug's words must OPEN the suggested name, word for word.

    A prefix test on the raw string is not enough — "accel" prefixes "accela" — so the comparison is
    per word: ["accel"] against ["accela"] fails, ["bessemer"] against ["bessemer","venture",
    "partners"] passes.
    """
    a, b = words(slug), words(suggested)
    if not a or not b or len(a) > len(b):
        return False
    return all(x == y for x, y in zip(a, b))


def curated_sites() -> dict:
    """{slug → site} from the fund portfolio pages we crawl — verified by construction."""
    from urllib.parse import urlsplit
    out: dict[str, str] = {}
    try:
        rows = json.loads((Path(__file__).resolve().parents[1] / "data" / "portfolios.json").read_text())
    except Exception:      # noqa: BLE001
        return out
    for r in rows:
        slug, url = str(r.get("fund") or ""), str(r.get("url") or "")
        if slug and url.startswith("http"):
            p = urlsplit(url)
            out[slug] = f"{p.scheme}://{p.netloc}"
    return out


def resolve(slug: str) -> dict | None:
    """{slug, name, site, basis} or None. Never guesses.

    A curated fund resolves on sight. Everything else must be a MULTI-WORD name, because one short
    token carries too little identity: run over the real index, single-token slugs resolved "avp" to
    AVP Beach Volleyball, "bond" to Bond Collective, "town" to Town & Country and "gfc" to a Dutch
    news site. Some single tokens were right — crv, ivp, jmi — and nothing in the answer told them
    apart from the wrong ones, which is the whole argument for refusing them.
    """
    curated = curated_sites().get(slug)
    if curated:
        return {"slug": slug, "name": display_name(slug), "site": curated, "basis": "portfolio_page"}
    if len(words(slug)) < 2:
        return None
    name = display_name(slug)
    for s in suggest(name)[:5]:
        dom = http.registrable_domain(str(s.get("domain") or ""))
        if not dom or dom in _SKIP_DOMAINS:
            continue
        if name_matches(slug, str(s.get("name") or "")):
            return {"slug": slug, "name": str(s.get("name") or name), "site": f"https://{dom}",
                    "basis": "name_lookup"}
    return None
