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
                 "profit", "margin", "ebitda", "cash", "burn", "orders", "transactions", "developers")
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
    out = {m.group(1).strip() for m in _CAP_ORG.finditer(text)}
    out |= {m.group(1).strip() for m in _CAP_RUN.finditer(text)}
    return {n for n in out if len(n) > 2}


def _mentions(text: str, subject_terms: list[str]) -> bool:
    low = (text or "").lower()
    return any(t and t.lower() in low for t in subject_terms)


def subject_bound(text: str, subject_terms: list[str], *, url: str = "") -> tuple[bool, str]:
    """Does this sentence assert something about OUR company? `(ok, why_not)`.

    Admitted when the subject is named, or when the company speaks in the first person on its own
    pages and nobody else is named. Refused when another organisation is named and ours is not, and
    refused for ANY first-person claim on a customer/case-study page — there "we" is the customer at
    least as often as the vendor, and that misattribution is the single most expensive mistake this
    module exists to prevent.
    """
    t = (text or "").strip()
    if not t:
        return False, "empty"
    named = _mentions(t, subject_terms)
    others = {n for n in _names(t) if not _mentions(n, subject_terms)}
    path = (url or "").lower()
    third_party_page = any(p in path for p in _THIRD_PARTY_PATHS)
    if named and not others:
        return True, ""
    if third_party_page and _FIRST_PERSON.search(t):
        # "we" on a customers/case-study page is the customer far more often than the vendor, and we
        # cannot tell which from the sentence. Abstain.
        return False, "first-person voice on a customer page — the speaker is not established"
    if _FIRST_PERSON.search(t) and not others:
        return True, ""
    if others and not named:
        return False, "names " + sorted(others)[0] + " and not the subject"
    if named:
        return True, ""
    return False, "no subject named"


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
