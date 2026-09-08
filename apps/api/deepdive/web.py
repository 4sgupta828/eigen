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

from .assemble import reads_like_a_sentence
from .gates import _mentions, metric_defined, subject_bound

# Copy that appears on every site and says nothing about any company.
_BOILER = ("for more information", "please visit", "learn more", "contact us", "sign up",
           "read more", "all rights reserved", "cookie", "subscribe", "follow us", "privacy policy",
           # form, footer and legal furniture, which names the company and says nothing about it
           "confirmation email", "your submission", "fill out", "required field", "try again",
           "terms of service", "javascript", "browser", "unsubscribe", "newsletter")
# A sentence that opens inside quotation marks is somebody being quoted. On a customers page that is
# the customer; in an article it is whoever the journalist called. Either way it is not the company
# speaking, and attributing it to the company is the misattribution this whole module guards against.
_OPENS_QUOTED = ("\u201c", '"', "\u2018", "'")

_SENT = re.compile(r"(?<=[.!?])\s+")
_FIRST_PERSON = re.compile(r"\b(we|our|us)\b", re.I)

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


def _claims_from(hits, subject_terms: list[str], own_domain: str = "",
                 tally: dict | None = None) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    seen: set[str] = set()
    t = tally if tally is not None else {}

    def drop(why):
        t[why] = t.get(why, 0) + 1
    for h in hits:
        facet = (h.facets or {}).get("deep_facet") or "product"
        url = ((h.facets or {}).get("url") or (h.extra or {}).get("url")
               or getattr(h.locator, "document_id", "") or h.document_id or "")
        external = facet in _EXTERNAL
        for s in _SENT.split((h.text or "").replace("\n", " ")):
            s = " ".join(s.split())
            if not (40 <= len(s) <= 320):
                continue
            if not reads_like_a_sentence(s):
                drop("not prose"); continue
            low = s.lower()
            if any(b in low for b in _BOILER):
                drop("page furniture"); continue
            if s.startswith(_OPENS_QUOTED):
                drop("somebody else is speaking"); continue
            if external and _FIRST_PERSON.search(s):
                drop("first person in coverage"); continue
            # On the open web the sentence must NAME the company. `subject_bound` lets a first-person
            # sentence stand on the company's own pages, which is right when we crawled the page
            # ourselves and wrong here: "We believe whoever deploys frontier infrastructure fastest
            # will shape whether AI expands human freedom" is a manifesto, not a claim about anybody.
            if not _mentions(s, subject_terms):
                drop("does not name the company"); continue
            ok, why = subject_bound(s, subject_terms, url=url)
            if not ok:
                drop(why); continue
            if re.search(r"\d", s) and not metric_defined(s)[0]:
                drop("a figure with no definition"); continue
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
        return {"sections": [], "projection": {},
                "attempted": [_att("Web read", 0, "pages", "not configured for this deployment")]}
    try:
        hits = await retrieve_deep_company(company=name, templates=templates, source=_source(manifest),
                                           tenant_id="default")
    except Exception:      # noqa: BLE001 — the dossier stands without this leg
        return {"sections": [], "projection": project_web_cost(templates),
                "attempted": [_att("Web read", 0, "pages", "unavailable on this run")]}
    tally: dict = {}
    by = _claims_from(hits, subject_terms, own, tally=tally)
    sections, own_rows = [], []
    for facet, rows in by.items():
        if facet in _EXTERNAL:
            sections.append({
                "title": _FACET_TITLES[facet], "kind": "stated", "claims": rows,
                "note": "how the press and analysts describe this — coverage, not an established "
                        "fact, and never a substitute for a filing",
            })
        else:
            own_rows.extend(rows)
    if own_rows:
        sections.insert(0, {"title": "Their own pages, read from the web", "kind": "stated",
                            "claims": own_rows[:12],
                            "note": "the company's own words, found on the open web"})
    kept = sum(len(v) for v in by.values())
    return {"sections": sections,
            "attempted": [_att("Web read", len(hits), "pages"),
                          _att("Web claims kept", kept, "claims",
                               "" if kept else _top_reason(tally))],
            "dropped": tally,
            "projection": project_web_cost(templates)}


def _top_reason(tally: dict) -> str:
    if not tally:
        return "nothing found"
    why, n = max(tally.items(), key=lambda kv: kv[1])
    return f"read, nothing survived ({why}, {n}×)"


def _att(source: str, found: int, unit: str, result: str = "") -> dict:
    """Every attempted row carries a `result`; the Manifest of Absence renders it when found is 0."""
    return {"source": source, "found": found, "unit": unit,
            "result": result or ("found" if found else "nothing found")}
