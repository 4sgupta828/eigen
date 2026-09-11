"""Read a startup from its own site or its deck, then say what we can and cannot match it against.

Two jobs, deliberately separated:

1. READ — free. `site.crawl` for a URL (robots-first, paced, the same crawling policy the rest of the
   codebase uses) and the PDF text layer for a deck. No model touches this step.
2. UNDERSTAND — one model call, and only if there is text to understand. It maps what was read into
   the vocabularies the index already speaks, and it must quote: every field carries the verbatim
   span it came from, so a founder can check the reading before trusting the search built on it.

The PLAN exists because of a measurement. Observed sector is known for 0.8% of the 7,453 firms we
hold and observed stage for 0.6%; a ranked list built on that is sixty firms wearing a costume. When
the index cannot answer well, saying so and handing over a search plan is the honest output —
docs/specs/investor-matching.md §1.

NOT ADVICE. The plan never says how much to raise or from whom. It says what the filed record shows
about funds of a given size, what to verify, and what we could not establish. "Funds of this size
report a median first cheque of $X in their Form D filings" is an observation; "raise $X" is advice,
and this file does not produce it.
"""
from __future__ import annotations

import json
import re

MAX_TEXT = 24_000          # what we hand the model; a deck is mostly repetition past this
MAX_PAGES_TEXT = 6_000     # per crawled page, so one verbose blog post cannot crowd out the rest


def text_from_site(website: str, *, crawl=None) -> tuple[str, list[str]]:
    """(text, source_urls). Free: fetch and parse only."""
    if crawl is None:
        from api.startups.sources import site as site_src
        crawl = site_src.crawl
    got = crawl(website) or {}
    chunks, urls = [], []
    for p in (got.get("pages") or []):
        t = (p.get("text") or "").strip()
        if not t:
            continue
        chunks.append(f"## {p.get('kind') or 'page'} — {p.get('final_url') or p.get('url')}\n{t[:MAX_PAGES_TEXT]}")
        urls.append(p.get("final_url") or p.get("url") or "")
    return ("\n\n".join(chunks)[:MAX_TEXT], [u for u in urls if u])


def text_from_attachments(attachments: list[dict]) -> tuple[str, list[str]]:
    """(text, names). PDFs via their text layer; plain text as-is. A scanned deck yields nothing and
    is reported as nothing rather than sent to a vision model behind the founder's back."""
    from api import media
    out, names = [], []
    for att in attachments or []:
        mt = (att.get("media_type") or "").lower()
        name = att.get("name") or "attachment"
        try:
            if "pdf" in mt or name.lower().endswith(".pdf"):
                t = media._pdf_text(att)
            elif mt.startswith("text/"):
                import base64
                t = base64.b64decode(att.get("data") or "", validate=False).decode("utf-8", "replace")
            else:
                continue
        except Exception:
            continue
        if (t or "").strip():
            out.append(f"## {name}\n{t.strip()[:MAX_TEXT]}")
            names.append(name)
    return ("\n\n".join(out)[:MAX_TEXT], names)


SYSTEM = """You read a startup's own website or pitch deck and return STRUCTURED JSON. You are a
reader, not an analyst: every field must be supported by words actually present in the text.

Rules that matter more than completeness:
- QUOTE OR OMIT. Every populated field carries `quote`: a verbatim span from the text. If you cannot
  quote it, leave the field empty and name it in `unknown`. A guess is worse than a gap here.
- NEVER infer the round from an amount. "Raising $3M" is an amount. Only an explicit round name
  ("seed", "Series A") sets `stage_claimed`.
- Map sectors ONLY into the provided vocabulary. If nothing fits, return an empty list — do not
  invent a category and do not stretch "we use AI" into every AI tag.
- Do not evaluate the company. No assessment of quality, traction strength or fundability.

Return JSON only:
{"name": "", "one_liner": "", "what_it_does": "", "customer": "",
 "stage_claimed": "", "raise_target_usd": null, "sectors": [], "geo": [],
 "existing_investors": [], "team": [{"name":"","role":""}],
 "quotes": {"one_liner":"", "stage_claimed":"", "raise_target_usd":"", "customer":""},
 "unknown": []}"""


async def read_profile(llm_json, text: str, *, sectors_vocab: list[str], geo_vocab: list[str]) -> dict:
    """One model call. Returns {} when there is nothing to read — never a fabricated profile."""
    if not (text or "").strip():
        return {}
    payload = {"sectors_vocabulary": sectors_vocab, "geo_vocabulary": geo_vocab, "text": text[:MAX_TEXT]}
    got = await llm_json(SYSTEM, json.dumps(payload))
    if isinstance(got, str):
        try:
            got = json.loads(got)
        except Exception:
            return {}
    if not isinstance(got, dict):
        return {}
    got["sectors"] = [s for s in (got.get("sectors") or []) if s in set(sectors_vocab)]
    got["geo"] = [g for g in (got.get("geo") or []) if g in set(geo_vocab)]
    # An amount is not a round. The model is told this; this enforces it.
    if got.get("stage_claimed") and not re.search(r"pre.?seed|seed|series\s*[a-d]|growth",
                                                  str(got.get("quotes", {}).get("stage_claimed") or ""), re.I):
        got.setdefault("unknown", []).append("stage (no explicit round name in the text)")
        got["stage_claimed"] = ""
    return got


def cheque_bands(funds: list[dict]) -> dict:
    """What the FILED record says funds of each size actually put to work, from Form D rows we hold.

    This is the only quantitative thing we can honestly offer a founder about amounts, and it is an
    observation about other people's filings — not a recommendation about theirs.
    """
    bands: dict[str, list[float]] = {}
    for f in funds or []:
        size = f.get("sold_usd") or f.get("offered_usd")
        n = f.get("investors_n")
        if not size or not n or n <= 0:
            continue
        key = ("under $50M" if size < 50e6 else "$50-250M" if size < 250e6
               else "$250M-1B" if size < 1e9 else "over $1B")
        bands.setdefault(key, []).append(size / n)
    out = {}
    for k, v in bands.items():
        v.sort()
        out[k] = {"funds": len(v), "median_per_investor_usd": round(v[len(v) // 2])}
    return out


def plan_for(profile: dict, *, coverage: dict, matched: int) -> dict:
    """The search-and-evaluation plan. Deterministic — no model, no opinion about the company.

    It exists for the case the measurement predicts: the index holds registration and fund filings for
    every firm and a PORTFOLIO for almost none, so "who funds companies like yours" is a question the
    data cannot yet answer well. Rather than dress a thin ranking as a recommendation, we hand over
    what to search, what to demand, and what we could not establish.
    """
    known = (coverage or {}).get("known") or {}
    firms = (coverage or {}).get("firms") or 0
    pf = known.get("portfolio_count", 0)
    sect = known.get("observed_sector", 0)

    steps = [
        {"do": "Search on what is filed, not what is claimed",
         "why": f"We hold registration and AUM for {firms:,} firms — that part of the record is close to "
                f"complete, so fund size, vehicle count and filing recency are dependable filters."},
        {"do": "Treat a firm's own stage and sector claims as a starting point, then check them",
         "why": "A site saying 'we back founders early' beside a $2B vehicle and a $50M minimum is a "
                "contradiction the filings will show you and the site will not."},
        {"do": "Ask every firm which of their last ten cheques looks like yours",
         "why": f"This is the question our index cannot answer for you yet: we hold a portfolio for "
                f"{pf:,} of {firms:,} firms ({100*pf/max(1,firms):.1f}%) and an observed sector for {sect:,}. "
                f"A partner can answer it in one email."},
        {"do": "Check who else is on their cap tables before you take the meeting",
         "why": "A fund that already backs a direct competitor is usually the wrong door, and it is the "
                "one thing that is cheap to find out and expensive to discover late."},
    ]
    gaps = [
        f"Portfolio coverage is {100*pf/max(1,firms):.1f}% — 'who has funded companies like yours' is "
        f"the weakest thing we can currently tell you, and we would rather say so than rank on it.",
    ]
    if not (profile or {}).get("sectors"):
        gaps.append("We could not place your company in the index's sector vocabulary from what we read, "
                    "so sector was not used to narrow the search.")
    if not (profile or {}).get("stage_claimed"):
        gaps.append("No explicit round name appeared in what we read. We did not infer one from an amount.")
    return {"steps": steps, "gaps": gaps, "matched": matched,
            "note": "A search plan, not investment advice. Nothing here recommends an amount to raise "
                    "or a firm to take money from."}
