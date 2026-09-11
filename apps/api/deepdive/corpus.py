"""What OUR OWN corpus already holds about this company.

DeepDive read the company's site, the keyless public sources and the open web — and never once looked
in the corpus this product is built on. 650,525 blocks sat there: 464k SEC filings, 92k preprints,
33k code documents, 19k papers, plus patents, funding and news. For a company we have ingested
anything about, the deepest source available was the one we never queried.

This is FREE — our own Postgres, keyword search over the tsvector that already exists. It runs at
every depth, including `held`, which is what turns `held` from two reference rows into a real reading.

Discipline, unchanged from the rest of DeepDive:
  - A hit must NAME the company. `subject_bound` decides that, not this module.
  - Each hit keeps its source_key, its title and its URL, so every row can be opened.
  - The register comes from what the source IS — a filing is `filed`, a paper or news is `stated` —
    never from how confident the text sounds.
"""
from __future__ import annotations

import re

# source_key -> (section title, register). A filing is a filing; an article is somebody writing.
_REGISTER = {
    "edgar": ("Regulatory filings", "filed"),
    "filing": ("Regulatory filings", "filed"),
    "uspto": ("Patents", "filed"),
    "patentsview": ("Patents", "filed"),
    "nsf": ("Public funding", "filed"),
    "nih_reporter": ("Public funding", "filed"),
    "companies_house": ("Regulatory filings", "filed"),
    "arxiv": ("Research", "stated"),
    "openalex": ("Research", "stated"),
    "semantic_scholar": ("Research", "stated"),
    "crossref": ("Research", "stated"),
    "openreview": ("Research", "stated"),
    "github": ("Public code", "observed"),
    "huggingface": ("Public models", "observed"),
    "startup_news": ("Press", "stated"),
    "gdelt": ("Press", "stated"),
    "news": ("Press", "stated"),
    "eng_blog": ("Their engineering writing", "stated"),
    "founder_essay": ("Founder and investor writing", "stated"),
    "yc": ("Programmes", "stated"),
}

MAX_PER_SOURCE = 4
MAX_TOTAL = 40


def _terms(name: str, domain: str) -> list[str]:
    """What counts as naming this company. Deliberately narrow: a short or generic name matched
    loosely turns every block mentioning 'Scale' or 'Anthropic-like' into a claim about them."""
    out = []
    n = (name or "").strip()
    if len(n) >= 3:
        out.append(n)
    d = (domain or "").strip().lower().replace("www.", "")
    if d and "." in d:
        out.append(d)
        stem = d.split(".")[0]
        if len(stem) >= 4 and stem.lower() != n.lower():
            out.append(stem)
    return out[:3]


def names_subject(text: str, title: str, terms: list[str]) -> bool:
    """Does this passage actually NAME the company? Case-insensitive, and a bare name must stand as
    its own word — "Scale" must not be matched inside "scaled", which is how a generic name turns
    half the corpus into claims about one startup."""
    hay = f"{text}\n{title}".lower()
    for t in terms:
        t = t.lower().strip()
        if not t:
            continue
        if "." in t:                       # a domain: a substring match is already specific
            if t in hay:
                return True
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", hay):
            return True
    return False


async def corpus_hits(dsn: str, *, name: str, domain: str, tenant: str = "demo") -> tuple[list[dict], dict]:
    """([hit], attempt). Keyword search over the corpus we already hold. Never raises: a corpus we
    cannot reach makes the dossier thinner and is reported as an attempt, exactly like a failed fetch."""
    terms = _terms(name, domain)
    if not dsn or not terms:
        return [], {"source": "Eigen corpus", "found": 0, "unit": "passages",
                    "result": "no corpus configured" if not dsn else "no usable name to search for"}
    try:
        import asyncpg
    except Exception:
        return [], {"source": "Eigen corpus", "found": 0, "unit": "passages", "result": "unavailable"}

    # EVERY term, not just the first. The search used to pass `terms[0]` and drop the rest, so a
    # company whose corpus presence is under its DOMAIN (github, papers citing a URL) went unfound
    # while a perfectly good second term sat unused. `websearch_to_tsquery` is the one form that
    # takes an OR.
    q = " OR ".join(f'"{t}"' if " " in t else t for t in terms)
    rows = []
    try:
        conn = await asyncpg.connect(dsn)
        try:
            rows = await conn.fetch(
                """SELECT document_id, block_id, text, document_title, source_key,
                          COALESCE(facets->>'url', facets->>'source_url', facets->>'link',
                                   facets->>'permalink', facets->>'landing_page') AS url,
                          facets->>'published_at' AS published_at
                     FROM rs_block
                    WHERE tenant_id = $1 AND tsv @@ websearch_to_tsquery('english', $2)
                 ORDER BY ts_rank(tsv, websearch_to_tsquery('english', $2)) DESC
                    LIMIT $3""", tenant, q, MAX_TOTAL * 6)
        finally:
            await conn.close()
    except Exception as e:      # noqa: BLE001
        return [], {"source": "Eigen corpus", "found": 0, "unit": "passages", "result": f"unavailable ({str(e)[:60]})"}

    per: dict[str, int] = {}
    out = []
    for r in rows:
        sk = (r["source_key"] or "").lower()
        title, register = _REGISTER.get(sk, ("Also in our corpus", "stated"))
        if per.get(sk, 0) >= MAX_PER_SOURCE:
            continue
        text = (r["text"] or "").strip()
        # SUBJECT BINDING, ours to enforce here. `tsv` matches a stemmed lexeme anywhere in the
        # block; that is a candidate, not a claim about this company. Keep only passages where the
        # company is NAMED — in the passage or in its document title — which is the same rule
        # gates.subject_bound applies to everything else in the dossier.
        if not names_subject(text, r["document_title"] or "", terms):
            continue
        # The claim is the passage itself, quoted. We are not summarising our own corpus back at the
        # reader — the point is that they can see the sentence and open the document.
        if len(text) < 40:
            continue
        per[sk] = per.get(sk, 0) + 1
        out.append({"section": title, "register": register, "source_key": sk,
                    "claim": text[:400], "quote": text[:400],
                    "document_title": r["document_title"] or "", "source_url": r["url"] or "",
                    "as_of": (r["published_at"] or "")[:10], "document_id": r["document_id"]})
        if len(out) >= MAX_TOTAL:
            break
    return out, {"source": "Eigen corpus", "found": len(out), "unit": "passages",
                 "result": "" if out else "nothing about this company in the corpus yet"}


def as_sections(hits: list[dict]) -> list[dict]:
    """Group corpus hits into dossier sections, in the shape assemble.py already emits."""
    by: dict[str, list[dict]] = {}
    for h in hits:
        by.setdefault(h["section"], []).append(h)
    order = ["Regulatory filings", "Patents", "Public funding", "Research", "Public code",
             "Public models", "Press", "Their engineering writing", "Founder and investor writing",
             "Programmes", "Also in our corpus"]
    out = []
    for title in order:
        if title in by:
            out.append({"title": title, "kind": "corpus", "claims": by[title]})
    for title, cl in by.items():
        if title not in order:
            out.append({"title": title, "kind": "corpus", "claims": cl})
    return out
