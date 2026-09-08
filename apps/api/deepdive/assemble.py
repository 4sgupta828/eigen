"""Assemble a dossier from what we ALREADY HOLD — no model, no network, no spend.

This is step 2 of docs/specs/deepdive.md and is worth shipping alone: for a company already in the
index, the stored facts, filings, financing events, founders, open roles and crawled pages make a
dossier that is strictly more than a startup card shows, at zero cost.

Two rules shape every section:
- A section with no claims does NOT render (`sections` only carries what has evidence), and
- what we looked for and did not find is recorded in `attempted` — the Manifest of Absence. In
  diligence a verified negative ("claims proprietary technology, zero granted patents") is a finding,
  and it is also what stops a half-empty dossier from reading as a broken product.

Registers are never mixed. `filed` is a number from a filing. `stated` is a claim the company or a
named person made — always attributed, never promoted to fact. Nothing here computes a third-party
estimate, and nothing extrapolates a current number from an old one.
"""
from __future__ import annotations

import re
from datetime import date

from api.startups.schema import SCHEMA, VALUE_LABELS

# The schema's own human labels: a dossier that prints "financing scale" and "last round months" is
# showing the reader our column names.
KEY_LABELS = {k.key: k.label for k in SCHEMA.keys}
from .gates import metric_defined, subject_bound

# Facts that describe the company's own shape, grouped into the section they belong to.
_FOUNDATIONS = ("founded", "country", "state", "metro", "status", "program", "tech_area")
_MONEY_FACTS = ("stage", "total_disclosed_funding", "last_round_amount", "last_round_months",
                "financing_scale", "evidence_strength")
_MARKET = ("headcount", "open_source", "patents_granted")
# These two answer questions of their own — how the money is made, and who pays — so they get their
# own headings rather than sitting in a bag of "traction".
_MONEY_MODEL = ("business_model",)
_WHO_BUYS = ("customer",)
# ARR is the one self-reported money figure we hold; it belongs in the stated ledger, never in filed.
_STATED_FACTS = ("arr",)

_PRICING_PATHS = ("/pricing", "/plans")
_CUSTOMER_PATHS = ("/customers", "/case-stud", "/customer-stories", "/testimonial")


def label(v: str) -> str:
    return VALUE_LABELS.get(v, (v or "").replace("_", " "))


def _fact_claim(f: dict) -> dict:
    key = f.get("key") or ""
    return {"key": key, "key_label": KEY_LABELS.get(key, key.replace("_", " ")),
            "value": f.get("value"), "label": label(f.get("value") or ""),
            "display": f.get("display") or "", "number": f.get("number"),
            "provenance": f.get("provenance") or "", "basis": f.get("basis") or "",
            "source_url": f.get("source_url") or "", "quote": f.get("quote") or "",
            "as_of": str(f.get("as_of") or "")[:10]}


def _by_key(facts: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for f in facts:
        out.setdefault(f.get("key") or "", []).append(f)
    return out


def _section(title: str, kind: str, claims: list[dict], note: str = "") -> dict | None:
    return {"title": title, "kind": kind, "claims": claims, "note": note} if claims else None


def _subject_terms(c: dict) -> list[str]:
    terms = [c.get("name") or "", c.get("legal_name") or "", (c.get("id") or "").split(".")[0]]
    terms += list(c.get("aliases") or [])
    return [t for t in terms if t and len(t) > 2]


# Splitting on every period turns "Fluidstack Ltd. raised $830 million in a Series A round." into two
# fragments, both too short to survive, so the claim silently never existed. The abbreviations that
# actually appear in company prose are excluded from the split.
_ABBR = ("inc", "ltd", "llc", "corp", "co", "plc", "gmbh", "sa", "nv", "ag", "pte", "pty", "bv",
         "mr", "mrs", "ms", "dr", "prof", "st", "no", "vs", "etc", "eg", "ie", "jr", "sr",
         "u.s", "u.k", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\u201c\"'])")


def sentences(text: str) -> list[str]:
    """Sentences of `text`, with abbreviations kept whole and whitespace collapsed."""
    out: list[str] = []
    for part in _SENT.split((text or "").replace("\n", " ")):
        # Stripped markup leaves a gap before the punctuation it used to wrap: "$18 billion ,".
        part = re.sub(r"\s+([,;:.!?%])", r"\1", " ".join(part.split()))
        if not part:
            continue
        # If the previous piece ended on an abbreviation, this is its continuation, not a sentence.
        if out:
            tail = out[-1].rstrip(".").split(" ")[-1].lower().rstrip(",")
            if tail in _ABBR:
                out[-1] = out[-1] + " " + part
                continue
        out.append(part)
    return out
# Crawled pages carry navigation, card decks and footers, none of which is a sentence. A run of
# title-case fragments with no verb is furniture; the ledger takes prose or nothing.
_TITLE_RUN = re.compile(r"(?:\b[A-Z][a-zA-Z]+\b[ ,]*){5,}")


def reads_like_a_sentence(s: str) -> bool:
    if not s.endswith((".", "!", "?")):
        return False
    words = s.split()
    lower = [w for w in words if w[:1].islower()]
    # A headline stack is nearly all capitalised; a short factual sentence is not. A flat floor of
    # five lowercase words looked reasonable and threw away "Fluidstack builds gigawatt-scale data
    # centers." — four lowercase words and a perfectly good claim. Judge the ratio, not the count.
    if len(lower) < 3 or len(lower) < 0.35 * len(words):
        return False
    return not _TITLE_RUN.search(s)


def stated_milestones(pages: list[dict], subject_terms: list[str], *, limit: int = 12) -> list[dict]:
    """The claims ledger: sentences from the company's own pages that state a defined figure ABOUT
    the company. Both gates must pass; a sentence that fails either is not weakened, it is dropped."""
    out: list[dict] = []
    for p in pages:
        url, text = p.get("url") or "", p.get("text") or ""
        for s in sentences(text):
            if not (40 <= len(s) <= 320) or not reads_like_a_sentence(s):
                continue
            ok_m, why_m = metric_defined(s)
            if not ok_m:
                continue
            ok_s, why_s = subject_bound(s, subject_terms, url=url)
            if not ok_s:
                continue
            out.append({"claim": s, "source_url": url, "register": "stated",
                        "attribution": "the company's own site"})
            if len(out) >= limit:
                return out
    return out


def named_customers(pages: list[dict]) -> list[dict]:
    """The pages that name customers. A crawled page's opening characters are its navigation, not its
    content, so the row is the LINK — the model reads these pages properly at depth `read`."""
    hits = [p for p in pages if any(k in (p.get("url") or "").lower() for k in _CUSTOMER_PATHS)]
    return [{"claim": "They publish a customers page", "source_url": p["url"],
             "register": "stated", "attribution": "the company's own site"} for p in hits[:3]]


def pricing(pages: list[dict]) -> list[dict]:
    hits = [p for p in pages if any(k in (p.get("url") or "").lower() for k in _PRICING_PATHS)]
    return [{"claim": "They publish prices", "source_url": p["url"],
             "register": "stated", "attribution": "the company's own site"} for p in hits[:2]]


def hiring_intent(byk: dict[str, list[dict]]) -> dict:
    """Open roles and their composition — the honest replacement for a guessed org chart.

    What a company is hiring FOR is a verifiable public fact and says more about strategy than a
    reporting line synthesized from inflated titles ever could (docs/specs/deepdive.md §3).
    """
    n = next((f.get("number") for f in byk.get("hiring", []) if f.get("number") is not None), None)
    fns = [label(f.get("value") or "") for f in byk.get("hiring_function", [])]
    src = next((f.get("source_url") for f in byk.get("hiring", []) if f.get("source_url")), "")
    quote = next((f.get("quote") for f in byk.get("hiring", []) if f.get("quote")), "")
    titles = [t.strip(" -•\t") for t in (quote or "").split("\n") if 3 < len(t.strip()) < 90][:12]
    return {"open_roles": int(n) if n is not None else None, "functions": fns,
            "board_url": src, "titles": titles}


def filed_financials(c: dict) -> list[dict]:
    """Only what a filing states. For a private company this is usually a Form D offering — an
    amount SOLD, which is not revenue and is labelled as what it is."""
    out = []
    for f in c.get("filings") or []:
        out.append({"claim": "SEC Form D: sold ${:,.0f} of a ${:,.0f} offering".format(
            float(f.get("sold_usd") or 0), float(f.get("offering_usd") or 0))
            if f.get("sold_usd") is not None else "SEC Form D filed",
            "filing_date": str(f.get("filing_date") or "")[:10],
            "revenue_range": f.get("revenue_range") or "",
            "accession": f.get("accession") or "", "register": "filed",
            "attribution": "SEC EDGAR", "source_url": _edgar_url(c.get("cik"), f.get("accession"))})
    return out


def _edgar_url(cik, accession) -> str:
    if not (cik and accession):
        return ""
    a = str(accession).replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{a}/"


def financing_events(c: dict) -> list[dict]:
    out = []
    for e in c.get("financing") or []:
        out.append({"round": e.get("round_name") or e.get("kind") or "",
                    "amount_usd": e.get("amount_usd") or e.get("offering_usd"),
                    "date": str(e.get("event_date") or "")[:10],
                    "investors": list(e.get("investors") or []), "lead": e.get("lead") or "",
                    "source_url": e.get("source_url") or "", "quote": e.get("quote") or "",
                    "register": "filed" if (e.get("kind") or "") == "formd" else "stated"})
    return out


def attempted(c: dict, byk: dict, pages: list[dict]) -> list[dict]:
    """The Manifest of Absence — where we looked, and what was there."""
    crawl = c.get("crawl") or {}
    rows = [
        ("SEC EDGAR (Form D)", len(c.get("filings") or []), "filings"),
        ("Company site crawl", len(pages), "pages"),
        ("Pricing page", len(pricing(pages)), "pages"),
        ("Named-customer page", len(named_customers(pages)), "pages"),
        ("ATS job board", int(next((f.get("number") or 0 for f in byk.get("hiring", [])), 0) or 0), "open roles"),
        ("Granted patents", int(next((f.get("number") or 0 for f in byk.get("patents_granted", [])), 0) or 0), "patents"),
        ("Named founders", len(c.get("founders") or []), "people"),
        ("Financing events", len(c.get("financing") or []), "events"),
    ]
    out = [{"source": s, "found": n, "unit": u, "result": ("found" if n else "nothing found")} for s, n, u in rows]
    if not crawl.get("at"):
        out.append({"source": "Company site crawl", "found": 0, "unit": "pages", "result": "never attempted"})
    return out


def merge_sections(sections: list[dict]) -> list[dict]:
    """One heading, one card. Several legs legitimately answer the same question — the index knows the
    business model, the site states it, the press describes it — and rendering three cards all called
    "How they make money" makes the reader do the joining. Order of first appearance is kept, and each
    claim keeps its own register and source, so a filed fact never blends into a stated one."""
    out: list[dict] = []
    at: dict[str, int] = {}
    for sec in sections:
        if not sec or not sec.get("claims"):
            continue
        title = sec.get("title") or ""
        # Two legs can answer one question in different SHAPES — a facet row and a quoted claim. Each
        # claim carries the shape it was built for, so merging never renders a row with the wrong one.
        for c in sec["claims"]:
            c.setdefault("row", sec.get("kind") or "fact")
        if title in at:
            keep = out[at[title]]
            seen = {str(c.get("claim") or c.get("display") or c.get("name") or "")[:120] for c in keep["claims"]}
            for c in sec["claims"]:
                k = str(c.get("claim") or c.get("display") or c.get("name") or "")[:120]
                if k and k in seen:
                    continue
                seen.add(k)
                keep["claims"].append(c)
            if sec.get("note") and not keep.get("note"):
                keep["note"] = sec["note"]
        else:
            at[title] = len(out)
            out.append(dict(sec, claims=list(sec["claims"])))
    return out


def build(c: dict, pages: list[dict]) -> dict:
    """The whole free dossier for one resolved company."""
    byk = _by_key(c.get("facts") or [])
    terms = _subject_terms(c)
    sections = []

    found = [_fact_claim(f) for k in _FOUNDATIONS for f in byk.get(k, [])]
    sections.append(_section("Foundations", "fact", found))

    people = [{"name": f.get("name"), "title": f.get("title") or "", "bio": f.get("bio") or "",
               "prior": list(f.get("prior_companies") or []), "links": f.get("links") or {},
               "source_url": f.get("source_url") or "", "quote": f.get("quote") or "",
               "register": "stated"} for f in (c.get("founders") or [])]
    sections.append(_section("Key people", "people", people,
                             note="named on the company's own pages or in a filing"))

    hire = hiring_intent(byk)
    sections.append(_section("Hiring intent", "hiring",
                             [hire] if (hire["open_roles"] or hire["functions"]) else []))

    money = [_fact_claim(f) for k in _MONEY_FACTS for f in byk.get(k, [])]
    sections.append(_section("Funding", "fact", money))
    sections.append(_section("Financing events", "financing", financing_events(c)))
    sections.append(_section("Filed financials", "filed", filed_financials(c),
                             note="amounts a filing states — an offering sold is not revenue"))

    stated = [_fact_claim(f) for k in _STATED_FACTS for f in byk.get(k, [])]
    stated_rows = [{"claim": s["display"] or s["label"], "source_url": s["source_url"],
                    "quote": s["quote"], "register": "stated",
                    "attribution": "self-reported"} for s in stated]
    stated_rows += stated_milestones(pages, terms)
    sections.append(_section("Stated milestones", "stated", stated_rows,
                             note="what the company has claimed publicly — never treated as a filed number"))

    sections.append(_section("Pricing and terms", "stated", pricing(pages)))
    sections.append(_section("Named customers", "stated", named_customers(pages)))

    sections.append(_section("How they make money", "fact",
                             [_fact_claim(f) for k in _MONEY_MODEL for f in byk.get(k, [])],
                             note="the model on record for this company"))
    sections.append(_section("Who buys", "fact",
                             [_fact_claim(f) for k in _WHO_BUYS for f in byk.get(k, [])]))
    mkt = [_fact_claim(f) for k in _MARKET for f in byk.get(k, [])]
    sections.append(_section("Model and traction", "fact", mkt))

    return {
        "company": {"id": c.get("id"), "name": c.get("name"), "website": c.get("website") or "",
                    "one_liner": c.get("one_liner") or "", "hq": c.get("hq") or "",
                    "cik": c.get("cik"), "yc_batch": c.get("yc_batch") or ""},
        "sections": [s for s in sections if s],
        "attempted": attempted(c, byk, pages),
        "basis": "held",          # nothing here was fetched or generated for this dossier
        "as_of": date.today().isoformat(),
    }
