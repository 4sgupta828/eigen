"""The startup vertical's word list for the query lexicon (kernel: `eigen_kernel.facets.lexicon`).

The lexicon reads closed vocabularies straight off the schema. What it cannot know is the DOMAIN's own
surface forms — that "yc" means the program, that "bay area" means the metro, that "series a" is a stage —
nor which keys are safe to harden, nor which values are ordinary English words that a bare match would
misread. That judgment is vocabulary, so it lives here rather than in the kernel.
"""
from __future__ import annotations

# Words that carry no facet and no semantic content. Their presence must not stop a query counting as
# "fully accounted for" — "companies backed by a16z" is entirely a filter, and the three words in front of
# the name are grammar.
FILLER = frozenset("""
a an and the of in at on for to from with by or is are was were be been being that this these those
me my our we us you your i it its as into over under about across per via than then so such any all
some more most less least other others new old show find get give list search look looking want need
company companies startup startups business businesses firm firms org orgs team teams people who what
which where when how why please just only also including include included based backed funded invested
investing investment investments portfolio round rounds raise raised raising money capital cash fund funds
sector sectors area areas space spaces industry industries market markets working work works
""".split())

# Keys a bare word in the query may HARDEN into a filter. Deliberately short: these are the ones where a
# lexicon hit is unambiguous enough that filtering is plainly what the reader meant. `tech_area` is absent
# on purpose — the area vocabulary is coarse, and the compiler already has a careful rule for when an area
# filters versus ranks (compile.py); letting the lexicon harden one behind its back would fight it.
MUST_KEYS = frozenset({"stage", "program", "status", "business_model", "customer", "country", "metro", "state"})

# Values that are also ordinary English words. A bare match on one of these is as likely to be grammar as
# intent, so it ranks instead of filtering — unless the whole query IS that one word, where there is no
# grammar around it to misread.
RISKY_VALUES = frozenset({"data", "security", "consumer", "growth", "seed", "active", "other", "public",
                          "services", "hardware", "agents", "insurance", "mobility", "manufacturing"})

# Surface forms the schema's own value list does not contain.
ALIASES = {
    "program": {"y combinator": "yc", "ycombinator": "yc", "south park commons": "spc",
                "entrepreneur first": "ef", "500 startups": "500",},
    "stage": {
              "series d": "series_d_plus", "series e": "series_d_plus",
              "preseed": "pre_seed", "pre-seed": "pre_seed", "late stage": "growth"},
    "metro": {"bay area": "bay_area", "sf": "bay_area", "san francisco": "bay_area",
              "silicon valley": "bay_area", "nyc": "new_york", "new york": "new_york",
              "la": "los_angeles", "los angeles": "los_angeles", "sfo": "bay_area"},
    "country": {"usa": "us", "u s": "us", "united states": "us", "america": "us",
                "united kingdom": "uk", "britain": "uk", "england": "uk", "india": "in",
                "germany": "de", "france": "fr", "israel": "il", "canada": "ca"},
    "status": { "shutdown": "shut_down", "dead": "shut_down", "exited": "acquired", "ipo": "public", "listed": "public"},
    "business_model": { "usage based": "usage", "subscription": "consumer_subscription"},
    "customer": {"b2b": "enterprise", "b2c": "consumer",
                 "developers": "developer", "public sector": "government"},
    "tech_area": { "ai infrastructure": "ai_infra", "llm": "llm_apps",
                  "dev tools": "devtools", "developer tools": "devtools",
                  "climate": "climate_energy", "biotech": "bio_health", "healthtech": "bio_health",
                  "crypto": "crypto_web3", "web3": "crypto_web3", "e-commerce": "ecommerce", "insurtech": "insurance", "legaltech": "legal_compliance", "hr tech": "hr_people",
                  "defense": "space_defense", "space": "space_defense",
                  "semiconductors": "hardware_semis", "chips": "hardware_semis",},
}


def config() -> dict:
    return {"filler": FILLER, "must_keys": MUST_KEYS, "risky_values": RISKY_VALUES, "aliases": ALIASES}
