"""Finding a company we have never heard of.

The index holds ~17k companies, which is a fraction of the ones a diligence question can be about.
Before this, typing a name we did not hold ended the dive: "no company we hold matches that name" —
true, and useless.

So: resolve the name against the open web, establish the company's OWN domain, and admit it to the
index. Two rules keep that from being a way to fill the index with rubbish:

- **The domain must plausibly BE the company.** The kernel's resolver already refuses to return a
  reference, press or social domain as anyone's own site; on top of that we require the domain's name
  to match the name that was typed. A resolver that falls back to "the first non-reference result"
  is fine for reading a page and not good enough for creating a record, so an unmatched result comes
  back as a candidate to confirm, not as a company.
- **The page has to exist.** A resolved domain that does not answer is not a company we found.

This SPENDS: one web search, and possibly one small model call to pick between candidates.
"""
from __future__ import annotations

import os
import re

DISCOVER_USD = float(os.environ.get("EIGEN_DEEPDIVE_DISCOVER_USD", "0.01"))


def project_discover_cost() -> dict:
    return {"searches": 1, "projected_usd": DISCOVER_USD}


def _slugish(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def name_matches_domain(name: str, domain: str) -> bool:
    """Does this domain's own name plausibly say the company that was typed?

    Deliberately stricter than the kernel's read-time matcher: creating an index row on a guess is
    how "gfc" became a Dutch news site in the investor work.
    """
    n = _slugish(name)
    d = _slugish((domain or "").split(".")[0])
    if not n or not d:
        return False
    if n == d or n in d or d in n:
        return True
    # "Eleven Labs" → elevenlabs.io; "Fluid Stack" → fluidstack.io
    return len(n) >= 6 and (d.startswith(n[:6]) or n.startswith(d[:6]))


async def find(name: str, *, manifest, llm=None) -> dict:
    """`{"status": "found"|"unsure"|"unknown", "domain", "name", "why"}` — never raises."""
    name = (name or "").strip()
    templates = getattr(manifest, "company_reader", None)
    if not (name and templates):
        return {"status": "unknown", "domain": "", "name": name,
                "why": "no web reader configured for this deployment"}
    try:
        from eigen_kernel.research.deep_company import resolve_own_domain

        from .web import _source
        domain = await resolve_own_domain(entity=name, templates=templates, source=_source(manifest),
                                          tenant_id="default", llm=llm)
    except Exception:      # noqa: BLE001 — a search that fails is a company we did not find
        return {"status": "unknown", "domain": "", "name": name, "why": "the web search failed"}
    if not domain:
        return {"status": "unknown", "domain": "", "name": name,
                "why": "nothing on the web looks like that company's own site"}
    if len(_slugish(name)) <= 4:
        # A short token is not a name: "GFC" resolves to whichever GFC the web ranks highest, and the
        # investor work already showed what that costs. Confirm, never assume.
        return {"status": "unsure", "domain": domain, "name": name,
                "why": f"“{name}” is short enough to mean several companies; the web's first answer is {domain}"}
    if not name_matches_domain(name, domain):
        # We found something; we are not confident it is what was asked for. Offer, never assume.
        return {"status": "unsure", "domain": domain, "name": name,
                "why": f"the closest site is {domain}, whose name does not match what you typed"}
    return {"status": "found", "domain": domain, "name": name, "why": ""}


async def admit(su_store, *, domain: str, name: str) -> dict:
    """Create the minimal company record a dive needs, and hand back what the dive will read.

    `sources: ["deepdive"]` marks the row as web-discovered rather than sourced from YC, a filing or a
    fund's portfolio, so the provenance of the index stays legible.
    """
    cid = domain.lower()
    await su_store.upsert_company({
        "id": cid, "name": name.strip(), "website": f"https://{cid}", "sources": ["deepdive"],
    })
    return await su_store.company(cid)
