"""The two gates that stand between "the quote is real" and "the claim is true".

The span gate already proves a quote appears in a document. Neither of these is about that. They are
the CONGRUENCE checks the standing directive demands, and both are string-level and free — they run
before any model is asked anything, and they fail-safe to abstain.

`subject_bound` — a company's own domain is FULL of other companies. Case studies, partner pages,
competitor comparisons. A customer testimonial on anthropic.com saying "we saw a 50% revenue increase"
passes every provenance check and is a claim about the CUSTOMER. So: a sentence carrying a claim about
the subject must actually name the subject, or must name nobody else.

`metric_defined` — "growth is up 300%" is not a number you can put in a dossier: no unit, no base, no
definition. A figure is admitted only when the surrounding text says WHAT it measures.
"""
from __future__ import annotations

import re

# Enough of an "other company" signal to be worth doubting a sentence, without a full NER pass.
_ORG_TAIL = r"(?:Inc\.?|LLC|Ltd\.?|Corp\.?|GmbH|Labs|Technologies|Systems|Software|Health|Bank|Group)"
_CAP_ORG = re.compile(r"\b([A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,3}\s+" + _ORG_TAIL + r")\b")
_CAP_RUN = re.compile(r"\b([A-Z][a-zA-Z0-9]{2,}(?:\s+[A-Z][a-zA-Z0-9]{2,}){0,2})\b")
# First person on a company's own page is the company speaking about itself.
_FIRST_PERSON = re.compile(r"\b(we|our|us|I)\b", re.I)
# Page paths where the subject of the prose is routinely somebody else.
_THIRD_PARTY_PATHS = ("/customers", "/case-stud", "/success", "/partners", "/testimonial", "/stories/")

_UNITLESS = re.compile(r"(?<![\w$€£])(\d[\d,.]*)\s*(%|x|×)(?!\w)")
# A figure is only a fact when the text says what it counts.
_METRIC_WORDS = ("arr", "annual recurring revenue", "revenue", "bookings", "gmv", "gross merchandise",
                 "run rate", "run-rate", "customers", "users", "employees", "headcount", "seats",
                 "downloads", "requests", "queries", "tokens", "valuation", "raised", "funding",
                 "profit", "margin", "ebitda", "cash", "burn", "orders", "transactions", "developers",
                 # A price is a defined figure: "$99 per month" says exactly what it measures.
                 "price", "pricing", "per month", "per year", "per seat", "per user", "/mo", "/month",
                 "plan", "subscription", "per request", "per token", "per hour", "per gpu")
_MONEY = re.compile(r"[$€£]\s?\d")
# How far from a figure a metric word still describes it.
_NEAR = 45
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def _is_date_figure(text: str, m) -> bool:
    """A date is not a measurement. "Jul 6, 2026" must never satisfy the definition gate."""
    ctx = text[max(0, m.start() - 12):m.end() + 8].lower()
    if any(mo in ctx for mo in _MONTHS):
        return True
    tok = m.group(0).strip()
    return bool(re.fullmatch(r"(19|20)\d{2}", tok)) or bool(re.search(r"\d{4}-\d{2}-\d{2}", ctx))


def _names(text: str) -> set[str]:
    """Capitalised runs that plausibly name ANOTHER organisation.

    Two things are deliberately not names: the first word of a sentence (every sentence starts
    capitalised — "Pricing starts at $99" does not name a company called Pricing), and ordinary words
    that marketing copy capitalises anyway (Team, Enterprise, Free, Pro). Reading either as an org
    made the gate refuse a company's own pricing page, which is the opposite of its job.
    """
    out = {m.group(1).strip() for m in _CAP_ORG.finditer(text)}
    for m in _CAP_RUN.finditer(text):
        run = m.group(1).strip()
        if _sentence_initial(text, m.start()):
            # Only the leading word is explained by the sentence break; keep the rest of the run.
            rest = run.split(" ", 1)
            if len(rest) == 1:
                continue
            run = rest[1]
        if run.lower() in _COMMON_CAPS or all(w.lower() in _COMMON_CAPS for w in run.split()):
            continue
        if all(w.isupper() and len(w) <= 5 for w in run.split()):
            continue                                   # SSO, API, SOC2 — acronyms, not companies
        out.add(run)
    return {n for n in out if len(n) > 2}


def _sentence_initial(text: str, i: int) -> bool:
    before = text[:i].rstrip()
    return not before or before[-1] in ".!?:;\u2022-\u2014"


# Words a company's own copy capitalises that name no organisation.
_COMMON_CAPS = {
    "the", "we", "our", "us", "this", "that", "these", "those", "it", "you", "your",
    "team", "teams", "enterprise", "free", "pro", "plus", "basic", "starter", "premium", "business",
    "pricing", "plans", "plan", "product", "products", "platform", "features", "security", "privacy",
    "docs", "documentation", "api", "sdk", "cloud", "support", "sales", "contact", "careers", "jobs",
    "about", "blog", "news", "press", "customers", "partners", "solutions", "company", "home",
    "monthly", "annual", "yearly", "per", "seat", "user", "month", "year", "day", "week",
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "today", "now", "new", "all", "get", "start", "learn", "read",
}


_LEGAL_TAIL = re.compile(r"\b(inc|inc\.|llc|ltd|ltd\.|limited|corp|corp\.|corporation|gmbh|co|co\.)$", re.I)


def _norm_org(s: str) -> str:
    """A company name reduced for comparison: punctuation and a legal suffix dropped."""
    t = re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())
    t = " ".join(t.split())
    return _LEGAL_TAIL.sub("", t).strip()


def _mentions(text: str, subject_terms: list[str]) -> bool:
    """Is the subject named here, as a whole word?

    Substring matching says yes to "Acme Health Inc." when the subject is "Acme" — a different
    company, and precisely the wrong-company attribution this file exists to stop. Whole-word
    matching says yes to the token and lets `_is_ours` decide whether a longer run is still us.
    """
    low = (text or "").lower()
    return any(t and re.search(r"\b" + re.escape(t.lower()) + r"\b", low) for t in subject_terms)


def _is_ours(run: str, subject_terms: list[str]) -> bool:
    """A detected organisation is OURS only when its name IS one of ours — not when it merely
    starts with it. "Acme Health" is not "Acme"."""
    n = _norm_org(run)
    return any(n == _norm_org(t) for t in subject_terms if t)


def subject_bound(text: str, subject_terms: list[str], *, url: str = "",
                  own_domain: str = "") -> tuple[bool, str]:
    """Does this sentence assert something about OUR company? `(ok, why_not)`.

    Admitted when the subject is named; when the company speaks in the first person on its own pages;
    or when the sentence sits on the company's OWN domain, on a page that is not about third parties,
    and names no other organisation — a pricing page's prices are the site owner's prices, and
    demanding the company name itself in every sentence of its own copy refuses nearly all of it.

    Refused when another organisation is named and ours is not, and refused for ANY first-person claim
    on a customer or case-study page: there "we" is the customer at least as often as the vendor, and
    that misattribution is the single most expensive mistake this module exists to prevent.
    """
    t = (text or "").strip()
    if not t:
        return False, "empty"
    named = _mentions(t, subject_terms)
    others = {n for n in _names(t) if not _is_ours(n, subject_terms)}
    path = (url or "").lower()
    third_party_page = any(p in path for p in _THIRD_PARTY_PATHS)
    if named and not others:
        return True, ""
    if third_party_page and _FIRST_PERSON.search(t):
        return False, "first-person voice on a customer page — the speaker is not established"
    if others and not named:
        return False, "names " + max(others, key=len) + " and not the subject"
    if named and others:
        # Both are named, so the sentence has to say which one it is about. English puts the subject
        # first: "Anthropic raised $450M from Spark Capital" is ours; "Acme Health Inc. reported $40M"
        # is not, even though the subject's name is inside that peer's name.
        first_other = min(_pos(t, o) for o in others)
        first_ours = min([p for p in (_pos(t, s) for s in subject_terms) if p >= 0] or [10 ** 6])
        if first_ours < first_other:
            return True, ""
        return False, "opens with " + sorted(others, key=lambda o: _pos(t, o))[0] + ", not the subject"
    if _FIRST_PERSON.search(t):
        return True, ""
    if own_domain and _host_of(url) == _host_of(own_domain) and not third_party_page:
        # The page's owner is the subject of its own unattributed copy.
        return True, ""
    return False, "no subject named"


def _pos(text: str, term: str) -> int:
    m = re.search(r"\b" + re.escape((term or "").lower()) + r"\b", (text or "").lower())
    return m.start() if m else 10 ** 6


def _host_of(u: str) -> str:
    h = (u or "").split("//")[-1].split("/")[0].lower()
    return h[4:] if h.startswith("www.") else h


def metric_defined(text: str) -> tuple[bool, str]:
    """Does a figure in this sentence carry a unit and a definition? `(ok, why_not)`.

    The figure and the metric word must be NEAR each other. Checking only that both appear somewhere
    in the text lets a page of navigation through: "Features Jul 6, 2026 … used by developers
    everywhere" has digits and has the word "developers", and means nothing. Dates are not figures.
    """
    t = (text or "").strip()
    if not t:
        return False, "empty"
    low = t.lower()
    spans = [m for m in re.finditer(r"[$€£]?\s?\d[\d,.]*\s*(?:%|x|×|million|billion|thousand|bn|k|m)?", t)
             if not _is_date_figure(t, m)]
    if not spans:
        return False, "no figure"
    for m in spans:
        near = low[max(0, m.start() - _NEAR):m.end() + _NEAR]
        said = [w for w in _METRIC_WORDS if w in near]
        if not said:
            continue
        money = bool(_MONEY.search(t[max(0, m.start() - 2):m.end()])) or bool(
            re.search(r"\d[\d,.]*\s*(million|billion|thousand|k\b|m\b|bn\b)", low[m.start():m.end() + 12]))
        bare = bool(_UNITLESS.fullmatch(m.group(0).strip()))
        if bare and not money:
            # "up 300%" beside the word "revenue" is still a percentage with no base.
            continue
        return True, ""
    if any(w in low for w in _METRIC_WORDS):
        return False, "a figure and a metric word that are not about each other"
    return False, "no metric named — a number with no definition is not comparable"
