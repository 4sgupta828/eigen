"""Bind an episode's GUEST to a company we index — and refuse to bind anything weaker.

This is the feature's sharpest edge. Getting it wrong does not produce a missing card, it produces a
card that says a founder discussed their company when they did not. Two measurements shaped the
gates, both run against the real index on 2026-09-07:

  * Naive matching is worthless. Matching any indexed company name against episode text bound 100% of
    episodes, because *inside*, *check*, *built*, *ambition* and *mercury* are all company names in
    our index. A collective row ("Founders") matched as a person.
  * Gated matching is honest and rare. Requiring a two-token founder name AND that founder's own
    company name bound 1-4% of episodes, and the bindings were correct (Ryan Petersen/Flexport,
    Brian Chesky/Airbnb, Amjad Masad/Replit, Wade Foster/Zapier).

So the rule is: a person must be a PERSON, they must be the GUEST (named in the title, never merely
mentioned in the body), and their own company must be named too. Anything else is left unbound. An
unbound episode is still searchable — it simply never appears on a company's card.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from api.startups.extract import is_person_name   # noqa: E402  (a founder row must name a person)

# Company names that are also ordinary English words. Each one produced a false bind in the naive
# measurement, so a company whose whole name is one of these never attaches an episode to a card.
# Names that are unambiguous in context (Stripe, Airbnb, Replit) are deliberately NOT here.
MIN_COMPANY_CHARS = 5
STOP_COMPANIES = {
    "inside", "check", "built", "ambition", "mercury", "figure", "assembly", "brand", "capital",
    "series", "growth", "found", "founders", "startup", "venture", "product", "future", "people",
    "double", "square", "general", "primary", "current", "public", "simple", "modern", "better",
}


def name_in(needle: str, haystack: str) -> bool:
    """Whole-token containment, case-insensitive. 'ray' must not match 'Murray'."""
    if not needle or not haystack:
        return False
    return re.search(r"(?:^|[^a-z0-9])" + re.escape(needle.lower()) + r"(?:[^a-z0-9]|$)",
                     haystack.lower()) is not None


def bindable_company(name: str) -> bool:
    n = (name or "").strip().lower()
    return len(n) >= MIN_COMPANY_CHARS and n not in STOP_COMPANIES


def bind_guest(*, title: str, body: str, guest: str, founders: dict) -> dict:
    """Decide what an episode may claim about a person.

    `founders` maps a lowercased founder name → {"company_id", "company_name"}.
    Returns {} when nothing binds, else {person, company_id, company_name, basis}.

    `basis` is the honest label of HOW it bound, and the UI prints it:
      guest_and_company — the title names the guest and their own company appears. Card-worthy.
      guest_only        — the title names the guest; the company is not confirmed. Searchable, not
                          attached to a company card.
    """
    guest = " ".join((guest or "").split())
    if not guest or not is_person_name(guest) or len(guest.split()) < 2:
        return {}
    if not name_in(guest, title):
        return {}                       # a guest is named in the TITLE; a body mention is not a guest
    rec = founders.get(guest.lower())
    if not rec:
        return {}
    company_name = str(rec.get("company_name") or "")
    blob = f"{title}\n{body}"
    if bindable_company(company_name) and name_in(company_name, blob):
        return {"person": guest, "company_id": rec.get("company_id", ""),
                "company_name": company_name, "basis": "guest_and_company"}
    return {"person": guest, "company_id": "", "company_name": "", "basis": "guest_only"}


def facet_patch(binding: dict) -> dict:
    """The facets a binding adds to an episode's blocks. Only a full binding names a company."""
    if not binding:
        return {}
    out = {"person": binding["person"], "bind_basis": binding["basis"]}
    if binding.get("company_id"):
        out["company_id"] = binding["company_id"]
        out["company_name"] = binding["company_name"]
    return out
