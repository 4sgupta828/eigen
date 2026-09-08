"""Decide HOW a company makes money, from what it says about itself.

The business model is one of the first things an investor asks and one of the emptiest fields we
hold: 527 companies of 17,665. The signal is not missing — 14,411 have a one-liner or a description
— it simply was never read.

This is a CLASSIFICATION into a closed vocabulary, not free text, and it carries the same discipline
as every other extracted fact:

* the answer must be one of the eight values the schema defines, or nothing;
* the model must quote the words it decided from, and the quote must appear verbatim in the source,
  so a decision cannot rest on something the company never said;
* "cannot tell" is a real answer and the common one for a company that only describes a problem.
  A guessed "saas" on 14,000 companies would look like coverage and be worth nothing.
"""
from __future__ import annotations

import re

VALUES = ("saas", "usage", "marketplace", "hardware", "open_core", "services",
          "consumer_subscription", "other")
MAX_TEXT = 2200

SYSTEM = (
    "You decide HOW ONE STARTUP MAKES MONEY, from its own description. Return STRICT JSON: "
    '{"business_model": str, "quote": str, "confident": bool}\n'
    "business_model MUST be exactly one of:\n"
    "  saas — recurring licence or seat fees from businesses\n"
    "  usage — metered or consumption pricing (per call, per token, per GB)\n"
    "  marketplace — takes a cut of transactions between two sides\n"
    "  hardware — sells physical devices\n"
    "  open_core — open-source project with a paid hosted or enterprise tier\n"
    "  services — people-delivered work: consulting, agency, managed service\n"
    "  consumer_subscription — recurring fees from individuals\n"
    "  other — earns money in a way none of the above describes\n"
    "  unknown — the text does not say how they make money\n"
    "RULES\n"
    "- quote: the words FROM THE TEXT you decided on, copied exactly. If you cannot quote the text, "
    'the answer is "unknown".\n'
    "- Describing a product or a problem is NOT a business model. Most companies say what they build "
    'and not how they charge; "unknown" is the correct answer for them and it is the common one.\n'
    "- Do not infer from the sector. A developer tool is not automatically saas, and an AI company is "
    "not automatically usage-priced.\n"
    "- confident: false when you are reading between the lines."
)


def user_payload(name: str, one_liner: str, description: str, site_text: str = "") -> str:
    body = "\n".join(x for x in (one_liner or "", description or "", site_text or "") if x)
    return f"Company: {name}\n\n{body[:MAX_TEXT]}"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def validate(out: dict, source_text: str) -> dict | None:
    """{value, quote} when the text supports it, else None. Never returns a guess."""
    value = str((out or {}).get("business_model") or "").strip().lower()
    if value not in VALUES:
        return None                       # includes "unknown", which is a real and common answer
    quote = " ".join(str((out or {}).get("quote") or "").split())
    if not quote or len(quote) < 12:
        return None
    if _norm(quote) not in _norm(source_text):
        return None                       # decided from something the company never said
    if not bool((out or {}).get("confident", True)):
        return None                       # reading between the lines is not a fact
    return {"value": value, "quote": quote[:400]}
