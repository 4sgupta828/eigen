"""Back-filling the sector areas from text we already hold — free, and precise before broad.

Adding a facet VALUE without coverage makes a search worse, not better: "ecommerce startups" would
return nothing where it used to return approximations. The extractor will fill these going forward,
but re-extracting 17,000 companies costs money, and the answer is already sitting in their own
one-liners and descriptions.

So this is a rule pass, and it is built for PRECISION over recall, because these values FILTER a
search: a phrase must be distinctive (never "building", never a bare "ev"), it must match on a word
boundary, and the sentence that matched is stored as the fact's quote so every assignment can be
checked. A company that matches nothing simply keeps the areas it already has.
"""
from __future__ import annotations

import re

# Distinctive phrases only. The loose version of this list matched 1,276 companies for proptech,
# almost all of them on the word "building" as a verb — which is why each entry here either names an
# industry or is a term of art in it.
PHRASES: dict[str, tuple[str, ...]] = {
    "ecommerce": ("e-commerce", "ecommerce", "online store", "online stores", "online retail",
                  "d2c", "direct-to-consumer", "shopify", "woocommerce", "storefront", "shopping cart",
                  "product catalog", "retail brands", "merchandising", "dropshipping"),
    "martech_sales": ("marketing team", "marketing teams", "martech", "go-to-market", "sales team",
                      "sales teams", "sales reps", "crm", "lead generation", "outbound sales",
                      "email campaigns", "ad campaigns", "adtech", "demand generation", "seo"),
    "hr_people": ("hr team", "hr teams", "hr software", "hrtech", "recruiting", "recruiters",
                  "applicant tracking", "payroll", "people ops", "employee onboarding", "talent acquisition",
                  "performance reviews", "benefits administration"),
    "legal_compliance": ("law firm", "law firms", "legaltech", "legal team", "legal teams",
                         "contract review", "contract management", "compliance team", "soc 2", "iso 27001",
                         "regulatory compliance", "gdpr", "hipaa compliance", "audit readiness", "litigation"),
    "proptech": ("proptech", "real estate", "property management", "commercial real estate",
                 "construction projects", "construction teams", "mortgage", "landlords", "tenants",
                 "building management", "architecture firms"),
    "logistics_supply": ("supply chain", "logistics", "freight", "warehouse", "warehousing",
                         "last-mile", "last mile", "fulfillment", "shipping carriers", "customs brokerage",
                         "inventory management", "3pl"),
    "edtech": ("edtech", "students", "teachers", "classroom", "curriculum", "online courses",
               "tutoring", "k-12", "higher education", "corporate training", "learning management"),
    "gaming_media": ("video game", "video games", "game studio", "game developers", "gaming",
                     "creators", "creator economy", "video editing", "streaming platform", "podcasts",
                     "music production", "film production", "vfx"),
    "agtech_food": ("agtech", "agriculture", "farmers", "farming", "crop", "restaurants",
                    "food service", "grocery", "food brands", "kitchen operations", "vertical farming"),
    "crypto_web3": ("crypto", "cryptocurrency", "blockchain", "web3", "onchain", "on-chain",
                    "ethereum", "solana", "stablecoin", "defi", "smart contracts", "digital assets"),
    "insurance": ("insurance", "insurtech", "underwriting", "insurance claims", "policyholders",
                  "actuarial", "reinsurance", "insurance carriers"),
    "mobility": ("automotive", "vehicles", "fleet management", "ev charging", "autonomous driving",
                 "self-driving", "aviation", "airlines", "public transit", "trucking", "rideshare"),
    "manufacturing": ("manufacturing", "factories", "factory floor", "shop floor", "industrial automation",
                      "cnc", "production lines", "plant operations", "quality inspection"),
    "govtech": ("govtech", "government agencies", "public sector", "municipalities", "federal agencies",
                "city government", "permitting"),
    "quantum": ("quantum computing", "quantum computer", "qubit", "qubits", "quantum algorithms"),
}

# Words whose presence means the phrase is describing somebody ELSE's field, not this company's.
_MAX_AREAS = 2
_SENT = re.compile(r"(?<=[.!?])\s+")


def _hit(text: str, phrase: str) -> str:
    """The sentence containing `phrase` on a word boundary, or "" — the quote that justifies a fact."""
    pat = re.compile(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", re.I)
    for sentence in _SENT.split(text or ""):
        if pat.search(sentence):
            return " ".join(sentence.split())[:300]
    return ""


def areas_for(text: str, *, known: set[str] | None = None) -> list[dict]:
    """`[{value, quote, phrase}]` — at most two new areas, best-evidenced first.

    "Best-evidenced" is the number of distinct phrases that matched: a company whose text says
    "supply chain", "freight" and "3PL" is a logistics company; one that says "crypto" once may be
    mentioning it in passing.
    """
    text = (text or "").strip()
    if len(text) < 20:
        return []
    known = known or set()
    scored: list[tuple[int, str, str, str]] = []
    for area, phrases in PHRASES.items():
        if area in known:
            continue
        quote, first, n = "", "", 0
        for p in phrases:
            q = _hit(text, p)
            if q:
                n += 1
                if not quote:
                    quote, first = q, p
        if n:
            scored.append((n, area, quote, first))
    scored.sort(key=lambda r: (-r[0], r[1]))
    return [{"value": a, "quote": q, "phrase": p} for _n, a, q, p in scored[:_MAX_AREAS]]
