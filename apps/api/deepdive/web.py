"""The web leg — what only news and analysis carry, in the register it deserves.

This is the LAST leg of a dive and the only one that reads pages we do not hold. It reuses the
kernel's `retrieve_deep_company`, which already resolves the company's own domain (refusing to mistake
a Crunchbase or TechCrunch page for the company's site), fans out a bounded set of queries, and stops
on a deadline.

Two rules govern what comes back:

- **Independent coverage is a SIGNAL, not a fact.** Anything from the external leg (news, analysis)
  lands in the `signal` register and is labelled as coverage. It is never merged with a filed number
  and never allowed to state something as established.
- **Congruence still applies.** A sentence from a news page must NAME this company; off the company's
  own domain there is no page-owner to establish the subject, so an unattributed sentence is dropped.

Bounded and fail-safe: the kernel module returns `[]` on timeout or error, and this returns no
sections rather than an exception.
"""
from __future__ import annotations

import os
import re

from .gates import metric_defined, subject_bound

_SENT = re.compile(r"(?<=[.!?])\s+")

# Roughly what one bounded read costs across the keyed engines. Deliberately an over-estimate: the
# projection a user is shown should not turn out to have been optimistic.
WEB_USD_PER_QUERY = float(os.environ.get("EIGEN_DEEPDIVE_WEB_USD", "0.006"))


def project_web_cost(templates: dict) -> dict:
    n = int(templates.get("max_queries") or 8)
    return {"queries": n, "usd_per_query": WEB_USD_PER_QUERY,
            "projected_usd": round(n * WEB_USD_PER_QUERY, 3)}


def _source(manifest):
    from eigen_kernel.retrieval.web import WebRetrievalSource
    from eigen_kernel.runtime.build import build_web
    return WebRetrievalSource(
        build_web(mode=os.environ.get("EIGEN_PROVIDER_MODE") or "live",
                  domains=getattr(manifest, "web_domains", ()), recent=True),
        max_results=int(os.environ.get("EIGEN_WEB_MAX_RESULTS", "8")),
        domain_facets=getattr(manifest, "web_domain_facets", None))


_FACET_TITLES = {
    "founders_team": "Team, as the web describes it",
    "product": "Product, as the web describes it",
    "technology": "Technology, as the web describes it",
    "pricing": "Pricing, as the web describes it",
    "customers": "Customers, as the web describes it",
    "blog_changelog": "What they have been shipping",
    "funding_investors_valuation": "Funding coverage",
    "competitors_traction": "Market position coverage",
}
# The two external facets are coverage ABOUT the company by somebody else.
_EXTERNAL = ("funding_investors_valuation", "competitors_traction")


def _claims_from(hits, subject_terms: list[str], own_domain: str) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for h in hits:
        facet = (h.facets or {}).get("deep_facet") or "product"
        url = ((h.facets or {}).get("url") or (h.extra or {}).get("url")
               or getattr(h.locator, "document_id", "") or h.document_id or "")
        external = facet in _EXTERNAL
        for s in _SENT.split((h.text or "").replace("\n", " ")):
            s = " ".join(s.split())
            if not (40 <= len(s) <= 320):
                continue
            # Off our own domain nothing establishes the subject except the sentence itself.
            ok, _why = subject_bound(s, subject_terms, url=url,
                                     own_domain="" if external else own_domain)
            if not ok:
                continue
            if re.search(r"\d", s) and not metric_defined(s)[0]:
                continue
            key = s.lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            by.setdefault(facet, []).append({
                "claim": s, "source_url": url, "register": "signal" if external else "stated",
                "attribution": (h.document_title or "independent coverage") if external
                               else "the company's own site, read from the web",
            })
            if len(by[facet]) >= 6:
                break
    return by


async def read_web(company: dict, *, manifest, subject_terms: list[str]) -> dict:
    """Sections + attempted rows from the bounded web read. Never raises."""
    from eigen_kernel.research.deep_company import retrieve_deep_company
    templates = getattr(manifest, "company_reader", None)
    name = company.get("name") or company.get("id") or ""
    own = company.get("website") or company.get("id") or ""
    if not (templates and name):
        return {"sections": [], "attempted": [{"source": "Web read", "found": 0, "unit": "pages",
                                               "result": "not configured for this deployment"}],
                "projection": {}}
    try:
        hits = await retrieve_deep_company(company=name, templates=templates, source=_source(manifest),
                                           tenant_id="default")
    except Exception:      # noqa: BLE001 — the dossier stands without this leg
        return {"sections": [], "attempted": [{"source": "Web read", "found": 0, "unit": "pages",
                                               "result": "unavailable on this run"}],
                "projection": project_web_cost(templates)}
    by = _claims_from(hits, subject_terms, own)
    sections = []
    for facet, rows in by.items():
        external = facet in _EXTERNAL
        sections.append({
            "title": _FACET_TITLES.get(facet, facet.replace("_", " ")),
            "kind": "stated", "claims": rows,
            "note": ("how the press and analysts describe this — coverage, not an established fact, "
                     "and never a substitute for a filing") if external else
                    "read from the company's own pages on the open web",
        })
    return {"sections": sections,
            "attempted": [{"source": "Web read", "found": len(hits), "unit": "pages"},
                          {"source": "Web claims kept", "found": sum(len(v) for v in by.values()),
                           "unit": "claims"}],
            "projection": project_web_cost(templates)}
