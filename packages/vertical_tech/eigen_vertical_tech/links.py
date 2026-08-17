"""Canonical source URLs for tech citations (domain-specific → lives here).

Turns a stored document_id ("<source_key>:<native_id>") into the canonical source page,
with a text-fragment (#:~:text=) deep-link to the cited quote where supported.
"""
from __future__ import annotations

import urllib.parse


def _text_fragment(quote: str | None) -> str:
    if not quote:
        return ""
    snippet = quote.strip().split("\n")[0][:120]
    return "#:~:text=" + urllib.parse.quote(snippet)


def source_url(document_id: str, quote: str | None = None, facets: dict | None = None) -> str | None:
    """Canonical URL for a citation's document, or None if no clean page exists. `facets` (optional)
    lets sources that need extra keys build a precise link — e.g. EDGAR needs the CIK to reach the
    exact filing index (the accession alone doesn't)."""
    frag = _text_fragment(quote)
    f = facets or {}
    # WEB findings store the full page URL as the document_id — that IS the link.
    if document_id.startswith("http://") or document_id.startswith("https://"):
        return document_id + frag
    src, _, native = document_id.partition(":")
    if not native:
        return None

    if src in ("edgar", "sec"):                       # native = accession (or CIK)
        if native.isdigit():                          # a bare CIK → the company's filing list
            return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={native}"
        acc = native.replace("-", "")
        cik = str(f.get("cik", "")).lstrip("0")
        if cik:                                       # precise filing-index page
            return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{native}-index.html"
        return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum={native}"
    if src == "arxiv":                                # native = arXiv id
        return f"https://arxiv.org/abs/{native}{frag}"
    if src == "openalex":                             # native = OpenAlex work id (W…)
        return f"https://openalex.org/{native}"
    if src == "semantic_scholar":                     # native = S2 paper id
        return f"https://www.semanticscholar.org/paper/{native}"
    if src == "crossref":                             # native = DOI
        return f"https://doi.org/{native}"
    if src == "wikidata":                             # native = QID (Q…)
        return f"https://www.wikidata.org/wiki/{native}"
    if src == "patentsview":                          # native = patent number
        return f"https://patents.google.com/patent/US{native}{frag}"
    if src == "github":                               # native = owner/repo
        return f"https://github.com/{native}"
    if src == "hackernews":                           # native = item id
        return f"https://news.ycombinator.com/item?id={native}"
    if src == "gdelt":                                # native IS the article url
        return native + frag if native.startswith("http") else None
    return None
