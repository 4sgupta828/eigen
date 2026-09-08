"""Reading the company's own pages with a model — the first leg of a dive that SPENDS.

What makes this different from the startup extractor: that one fills typed facets (stage, tech area,
business model) from a short one-liner. This reads long pages and asks for CLAIMS — what they sell, to
whom, on what terms, what they say they have achieved — and every claim must survive three checks
before it exists:

  1. the quote appears VERBATIM in the page the model was given (the span check — a model that
     paraphrases has invented evidence, and the claim is dropped, not repaired);
  2. `subject_bound` — the quote is about THIS company, not a customer quoted on its case-study page;
  3. `metric_defined` — if the claim carries a figure, the figure has a unit and a definition.

A claim that fails any of them is discarded and counted. Fail-safe is abstain: the section simply
does not render, and "Where we looked" says the page was read and yielded nothing.
"""
from __future__ import annotations

import json
import re

from .gates import metric_defined, subject_bound

# Closed vocabulary. A model free to invent claim kinds produces a different dossier every run and
# nothing that can be compared across companies.
KINDS = ("what_they_sell", "who_buys", "pricing_terms", "differentiator", "milestone",
         "named_customer", "named_partner", "risk_or_limit")

SYSTEM = """You read one page from a company's own website and report only what the page STATES.

Return JSON: {"claims": [{"kind": "...", "text": "...", "quote": "..."}]}

Rules that decide whether a claim is kept:
- `kind` is one of: what_they_sell, who_buys, pricing_terms, differentiator, milestone,
  named_customer, named_partner, risk_or_limit. Nothing else.
- `quote` MUST be copied CHARACTER FOR CHARACTER from the page. Do not fix typos, do not shorten
  across an ellipsis, do not join two sentences. A quote that does not appear in the page verbatim
  causes the claim to be thrown away.
- `text` is one plain sentence saying what the quote establishes about THIS company.
- Only claims about the company whose page this is. A customer testimonial, a partner's product, or a
  competitor named in a comparison is NOT a claim about this company — skip it.
- A number without a unit and a definition ("up 300%", "10x faster") is not a milestone. Skip it.
- Marketing adjectives are not claims. "The leading platform" says nothing; skip it.
- If the page states nothing that qualifies, return {"claims": []}. An empty answer is a correct answer.
"""

MAX_PAGE_CHARS = 9000


def user_payload(name: str, url: str, kind: str, text: str) -> str:
    return json.dumps({"company": name, "page_url": url, "page_kind": kind,
                       "page_text": (text or "")[:MAX_PAGE_CHARS]}, ensure_ascii=False)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def verbatim(quote: str, page_text: str) -> bool:
    """The same normalisation the kernel's span verifier uses: whitespace-collapsed, lowercased."""
    q = _norm(quote)
    return bool(q) and len(q) >= 12 and q in _norm(page_text)


_NUMERIC_KINDS = ("milestone", "pricing_terms")


def keep(claim: dict, *, page_text: str, page_url: str, subject_terms: list[str],
         own_domain: str = "") -> tuple[bool, str]:
    """`(kept, why_not)` — the three checks, in the order that costs least to fail."""
    kind, text, quote = claim.get("kind"), (claim.get("text") or "").strip(), (claim.get("quote") or "").strip()
    if kind not in KINDS:
        return False, "kind outside the vocabulary"
    if not text or len(text) > 400:
        return False, "no usable sentence"
    if not verbatim(quote, page_text):
        return False, "quote is not verbatim in the page"
    ok, why = subject_bound(quote, subject_terms, url=page_url, own_domain=own_domain)
    if not ok:
        return False, why
    if kind in _NUMERIC_KINDS and re.search(r"\d", quote):
        ok, why = metric_defined(quote)
        if not ok:
            return False, why
    return True, ""


_TITLES = {"what_they_sell": "What they sell", "who_buys": "Who buys", "pricing_terms": "Pricing and terms",
           "differentiator": "What they say makes them different", "milestone": "Stated milestones",
           "named_customer": "Named customers", "named_partner": "Named partners",
           "risk_or_limit": "Limits they state themselves"}
# Order the reader wants: what it is, who it's for, on what terms, then the softer material.
_ORDER = ("what_they_sell", "who_buys", "pricing_terms", "named_customer", "named_partner",
          "differentiator", "milestone", "risk_or_limit")


def sections_from(kept: list[dict]) -> list[dict]:
    by: dict[str, list[dict]] = {}
    for c in kept:
        by.setdefault(c["kind"], []).append(c)
    out = []
    for kind in _ORDER:
        rows = by.get(kind) or []
        if not rows:
            continue
        out.append({"title": _TITLES[kind], "kind": "stated",
                    "claims": [{"claim": r["text"], "quote": r["quote"], "source_url": r["source_url"],
                                "register": "stated", "attribution": "the company's own site"} for r in rows],
                    "note": "the company's own words, each backed by a quote that appears on the page"})
    return out


async def read_pages(llm_json, *, name: str, subject_terms: list[str], pages: list[dict],
                     own_domain: str = "", max_pages: int = 10) -> dict:
    """Read up to `max_pages` of the company's own pages. Returns sections + a tally of what was dropped.

    One model call per page. The caller has already projected and gated the cost.
    """
    kept: list[dict] = []
    dropped: dict[str, int] = {}
    read = 0
    for p in pages[:max_pages]:
        text, url = p.get("text") or "", p.get("url") or ""
        if len(text) < 200:
            continue
        try:
            data = await llm_json(SYSTEM, user_payload(name, url, p.get("kind") or "", text))
        except Exception:      # noqa: BLE001 — one refusal or timeout never stops the read
            dropped["model call failed"] = dropped.get("model call failed", 0) + 1
            continue
        read += 1
        for c in (data or {}).get("claims") or []:
            if not isinstance(c, dict):
                continue
            ok, why = keep(c, page_text=text, page_url=url, subject_terms=subject_terms,
                           own_domain=own_domain)
            if ok:
                kept.append({"kind": c["kind"], "text": c["text"].strip(), "quote": c["quote"].strip(),
                             "source_url": url})
            else:
                dropped[why] = dropped.get(why, 0) + 1
    return {"sections": sections_from(kept), "read": read, "kept": len(kept), "dropped": dropped}
