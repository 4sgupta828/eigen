"""Schema-driven extraction of a company's own pages with DeepSeek — every extracted fact carries a verbatim
quote that CODE verifies against the page text, and every figure must appear in its quote.

One call per company: the model reads the crawled pages (capped) with the schema's vocabulary rendered from
`schema.py` and returns strict JSON. Code then: validates values against the schema; span-checks each quote
(normalised substring of the page text — same rule as the kernel's provenance gate); drops any number whose
digits are not in the quote; drops `intent` items from facts (kept nowhere — the site is re-read next crawl);
types the ATS roles' functions from their titles in the same call. Fail-safe: a bad response writes nothing."""
from __future__ import annotations

import json
import re
from datetime import date

from eigen_kernel.facets import UNKNOWN, FacetType

from .schema import EXTRACTABLE, SCHEMA, KIND

PAGE_CAP = 7000          # chars per page shown to the model
PAGES_CAP = 6
ROLE_FUNCTIONS = ("engineering", "research", "product", "design", "sales", "marketing", "operations", "finance", "people", "support", "other")
_WS = re.compile(r"\s+")
_ROUND = {"pre-seed": "pre_seed", "preseed": "pre_seed", "pre_seed": "pre_seed", "seed": "seed", "seed extension": "seed", "seed+": "seed",
          "series a": "series_a", "series b": "series_b", "series c": "series_c", "series d": "series_d_plus", "series e": "series_d_plus",
          "series f": "series_d_plus", "growth": "growth", "late stage": "growth"}
_MULT = {"k": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}


def norm(s: str) -> str:
    return _WS.sub(" ", (s or "").strip().lower())


def quote_in(quote: str, text: str) -> bool:
    q = norm(quote)
    return bool(q) and len(q) >= 12 and q in text


def figure_in_quote(amount: float, quote: str) -> bool:
    """The invented-figure rule: some rendering of the number's significant digits must appear in the quote
    ('$12M', '12 million', '12,000,000', '$1.5B')."""
    q = quote.replace(",", "").lower()
    if amount is None:
        return False
    cands = set()
    for div, suf in ((1, ""), (1e3, "k"), (1e6, "m"), (1e9, "b")):
        x = amount / div
        for fmt in ("{:.0f}", "{:.1f}", "{:.2f}"):
            s = fmt.format(x).rstrip("0").rstrip(".") if "." in fmt.format(x) else fmt.format(x)
            if s and s != "0":
                cands.add(s)
    return any(re.search(r"(?<![\d.])" + re.escape(c) + r"(?![\d])", q) for c in cands)


def parse_money(v) -> float | None:
    """'$12M' / '12 million' / 12000000 / {'amount':12,'unit':'m'} → USD float (structural parse only)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        v = f"{v.get('amount', '')}{v.get('unit', '')}"
    s = str(v).lower().replace(",", "").replace("$", "").replace("usd", "").strip()
    m = re.match(r"^([\d.]+)\s*(k|m|mm|b|bn|million|billion)?\b", s)
    if not m:
        return None
    try:
        return float(m.group(1)) * _MULT.get(m.group(2) or "", 1.0)
    except ValueError:
        return None


def system_prompt() -> str:
    keys = "\n".join(f"- {k.key} ({k.type.value}): " + (" | ".join(k.values) if k.values else ("a number in " + k.unit if k.unit else "short lowercase tokens"))
                     + (f" — {k.guidance}" if k.guidance else "") for k in SCHEMA.for_kind(KIND) if k.key in EXTRACTABLE)
    return f"""You read a startup's OWN web pages and return what they STATE, as strict JSON. You never guess, never infer from
silence, and never use outside knowledge. Every item carries `quote`: a VERBATIM sentence or fragment copied from the
pages (12+ characters, exact wording) that states it. Items whose quote is not in the pages are discarded by code.

Return: {{"one_liner": str (<= 140 chars, what the company does, in the company's own framing),
 "facets": [{{"key": <one of the keys below>, "value": <token> | <number>, "quote": str, "modality": "realized"|"intent"}}],
 "founders": [{{"name": str, "title": str, "prior_companies": [lowercase slugs], "quote": str}}],
 "financing": [{{"round_name": str|"", "amount": str|"", "currency": "USD"|"EUR"|"GBP"|"other", "date": "YYYY-MM"|"", "investors": [slugs], "lead": slug|"", "quote": str, "modality": "realized"|"intent"}}],
 "metrics": [{{"kind": "arr"|"revenue"|"run_rate"|"gmv"|"bookings"|"users"|"other", "amount": str, "currency": str, "period": str, "quote": str, "modality": "realized"|"intent"}}],
 "customers": [{{"name": str, "quote": str}}],
 "role_functions": {{"<role title exactly as given>": one of {list(ROLE_FUNCTIONS)}}}}}

Rules: a founder is only someone the pages call founder / co-founder / founding CEO-CTO (not 'founding engineer', not advisors).
`prior_companies` only when the pages say the founder previously worked there. A 'trusted by' or customer logo is a customer,
never an investor. An investor is a fund the pages say invested / led / backed. `modality` is "intent" for plans and targets
("we plan to raise", "targeting $10M ARR"). Metrics: ARR only when the pages say ARR / annual recurring revenue.
Keys and vocabularies:
{keys}
Use only these keys. Omit anything the pages do not state."""


def user_payload(company: dict, pages: list[dict], roles: list[dict]) -> str:
    doc = {"company": {"name": company.get("name"), "website": company.get("website"), "known_one_liner": company.get("one_liner") or ""},
           "pages": [{"kind": p.get("kind"), "url": p.get("url"), "text": (p.get("text") or "")[:PAGE_CAP]} for p in pages[:PAGES_CAP]],
           "open_role_titles": [r.get("title") for r in roles[:60]]}
    return json.dumps(doc, ensure_ascii=False)


_COLLECTIVE = {
    "team", "teams", "founders", "cofounders", "co-founders", "leadership", "management",
    "staff", "crew", "everyone", "employees", "people", "folks", "us", "we", "company",
}


def is_person_name(name: str) -> bool:
    """A founder row must name a PERSON. 'Founding Team', 'Our Founders', a sentence about
    the team — not people. Kept deliberately narrow: mononyms, nicknames in quotes or
    parentheses and post-nominal letters are all real founder names we have seen."""
    name = (name or "").strip()
    if not name:
        return False
    parts = [p for p in re.split(r"[\s,]+", name) if p]
    if not parts or len(parts) > 8:
        return False
    low = [p.lower().strip(".&()\"'’") for p in parts]
    if any(p in _COLLECTIVE for p in low):
        return False
    return bool(re.search(r"[A-Za-z]", name))


def validate(out: dict, pages: list[dict], roles: list[dict], *, as_of: date | None = None) -> dict:
    """The model's JSON → {facts, founders, financing, metrics, customers, one_liner, role_functions}, every item gated."""
    text = norm("\n".join(p.get("text") or "" for p in pages))
    url_of = {p.get("kind"): p.get("url") for p in pages}
    def src(kind_hint: str = "") -> str:
        return url_of.get(kind_hint) or (pages[0].get("url") if pages else "")
    facts: list[dict] = []
    for it in (out.get("facets") or []):
        if not isinstance(it, dict) or it.get("modality") == "intent":
            continue
        key = str(it.get("key") or "")
        k = SCHEMA.key(key)
        q = str(it.get("quote") or "")
        if k is None or key not in EXTRACTABLE or not quote_in(q, text):
            continue
        if k.type is FacetType.numeric:
            num = parse_money(it.get("value")) if k.unit == "usd" else None
            if num is None:
                try:
                    num = float(str(it.get("value")).replace(",", ""))
                except (TypeError, ValueError):
                    continue
            if not figure_in_quote(num, q):
                continue
            facts.append({"key": key, "number": num, "display": str(it.get("value"))[:60], "quote": q, "source_url": src(), "as_of": as_of,
                          "basis": "self_reported", "confidence": 0.7})
        else:
            vals = it.get("value") if isinstance(it.get("value"), list) else [it.get("value")]
            for v in vals:
                if key == "stage":
                    v = _ROUND.get(norm(str(v)), v)
                nv = SCHEMA.validate_value(key, v)
                if nv is not None and nv != UNKNOWN:
                    facts.append({"key": key, "value": nv, "quote": q, "source_url": src(), "as_of": as_of, "basis": "self_reported", "confidence": 0.7})
    founders = []
    for f in (out.get("founders") or []):
        if not isinstance(f, dict) or not quote_in(str(f.get("quote") or ""), text):
            continue
        name = str(f.get("name") or "").strip()
        if not name or not is_person_name(name) or norm(name) not in text:
            continue
        founders.append({"name": name[:120], "title": str(f.get("title") or "")[:120],
                         "prior_companies": [_slug(x) for x in (f.get("prior_companies") or []) if _slug(x)][:6],
                         "quote": str(f.get("quote"))[:800], "source_url": src("team") or src("about")})
    financing = []
    for ev in (out.get("financing") or []):
        if not isinstance(ev, dict) or ev.get("modality") == "intent" or not quote_in(str(ev.get("quote") or ""), text):
            continue
        amt = parse_money(ev.get("amount")) if str(ev.get("currency") or "USD").upper() == "USD" else None
        if amt is not None and not figure_in_quote(amt, str(ev.get("quote"))):
            amt = None
        rn_raw = norm(str(ev.get("round_name") or ""))
        rn = _ROUND.get(rn_raw, "")
        if rn and not re.search(r"\b" + re.escape(rn_raw.split(" extension")[0].replace("-", " ").replace("_", " ")) + r"\b", norm(str(ev.get("quote"))).replace("-", " ")):
            rn = ""                                  # the round word itself must be in the quote
        if not rn and amt is None:
            continue
        financing.append({"kind": "site", "round_name": rn, "amount_usd": amt, "event_date": _month(ev.get("date")),
                          "investors": [_slug(x) for x in (ev.get("investors") or []) if _slug(x)][:12], "lead": _slug(ev.get("lead") or ""),
                          "quote": str(ev.get("quote"))[:800], "source_url": src("press") or src()})
    metrics = []
    for m in (out.get("metrics") or []):
        if not isinstance(m, dict) or m.get("modality") == "intent" or not quote_in(str(m.get("quote") or ""), text):
            continue
        amt = parse_money(m.get("amount")) if str(m.get("currency") or "USD").upper() == "USD" else None
        if amt is None or not figure_in_quote(amt, str(m.get("quote"))):
            continue
        metrics.append({"kind": str(m.get("kind") or "other"), "amount_usd": amt, "period": str(m.get("period") or "")[:40], "quote": str(m.get("quote"))[:800], "source_url": src()})
        if m.get("kind") == "arr":
            facts.append({"key": "arr", "number": amt, "display": str(m.get("amount"))[:60], "quote": str(m.get("quote"))[:800], "source_url": src(),
                          "as_of": as_of, "basis": "self_reported", "confidence": 0.7})
    customers = [{"name": str(c.get("name"))[:120], "quote": str(c.get("quote"))[:400]} for c in (out.get("customers") or [])
                 if isinstance(c, dict) and c.get("name") and quote_in(str(c.get("quote") or ""), text)][:20]
    rf_raw = out.get("role_functions") or {}
    titles = {norm(r.get("title") or ""): r for r in roles}
    role_functions: dict[str, str] = {}
    if isinstance(rf_raw, dict):
        for title, fn in rf_raw.items():
            if norm(title) in titles and str(fn) in ROLE_FUNCTIONS:
                role_functions[norm(title)] = str(fn)
    one_liner = str(out.get("one_liner") or "").strip()[:160]
    return {"facts": facts, "founders": founders, "financing": financing, "metrics": metrics, "customers": customers,
            "role_functions": role_functions, "one_liner": one_liner}


def _slug(s) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s or "").lower()).strip("_")[:40]


def _month(s) -> date | None:
    m = re.match(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$", str(s or "").strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1))
    except ValueError:
        return None


async def extract_company(llm_json, company: dict, pages: list[dict], roles: list[dict], *, as_of: date | None = None) -> dict | None:
    """`llm_json(system, user) -> dict` is injected (DeepSeek in prod, a fake in tests). None on failure."""
    if not pages:
        return None
    try:
        out = await llm_json(system_prompt(), user_payload(company, pages, roles))
    except Exception:   # noqa: BLE001 — a failed call writes nothing
        return None
    if not isinstance(out, dict):
        return None
    return validate(out, pages, roles, as_of=as_of or date.today())
