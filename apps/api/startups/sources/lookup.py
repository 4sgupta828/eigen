"""Website discovery for a company we know only by legal name (the Form D issuers): Clearbit's keyless company
autocomplete (name prefix → {name, domain}). A hit counts only when the suggested NAME is the issuer's normalised
name (legal-form suffixes stripped) — 'Kivo Inc' does not become 'Kivo Daily'. Free, unauthenticated, paced."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .formd import name_norm
from . import http

URL = "https://autocomplete.clearbit.com/v1/companies/suggest?query={q}"
_SKIP = ("linkedin.com", "facebook.com", "wikipedia.org", "crunchbase.com", "bloomberg.com", "zoominfo.com", "opencorporates.com", "sec.gov", "dnb.com")


def suggest(name: str, *, timeout: float = 12.0) -> list[dict]:
    q = urllib.parse.quote((name or "").strip()[:80])
    if not q:
        return []
    req = urllib.request.Request(URL.format(q=q), headers={"User-Agent": http.UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "ignore") or "[]")
    except Exception:   # noqa: BLE001
        return []
    return [d for d in data if isinstance(d, dict) and d.get("domain")] if isinstance(data, list) else []


_SUFFIX = ("inc", "inc.", "incorporated", "llc", "l.l.c.", "ltd", "ltd.", "limited", "corp", "corp.", "corporation", "co", "co.", "company", "plc", "pbc", "lp", "llp")


def clean_name(legal_name: str) -> str:
    """The name as a person would type it: commas out, trailing legal forms off, casing kept ('Nuburu, Inc.' → 'Nuburu')."""
    toks = [t for t in (legal_name or "").replace(",", " ").split() if t]
    while toks and toks[-1].lower().strip(".") in {x.strip(".") for x in _SUFFIX}:
        toks.pop()
    return " ".join(toks)


def website_for(legal_name: str) -> dict | None:
    """{name, domain} when a suggestion's normalised name equals the issuer's; else None (never a guess)."""
    target = name_norm(legal_name)
    if not target or len(target) < 3:
        return None
    for s in suggest(clean_name(legal_name))[:5]:
        dom = http.registrable_domain(str(s.get("domain") or ""))
        if not dom or any(dom == d or dom.endswith("." + d) for d in _SKIP):
            continue
        if name_norm(str(s.get("name") or "")) == target:
            return {"name": str(s.get("name") or ""), "domain": dom}
    return None
