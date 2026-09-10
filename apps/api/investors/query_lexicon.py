"""The investor vertical's word list for the query lexicon (kernel: `eigen_kernel.facets.lexicon`).

Same mechanism as the startup side, different judgment. The keys an investor query may HARDEN are
narrower, because the investor index is thinner: a `must` on a stated key filters on what a firm chose
to write on its own website, and before the firm-site pass has run for a firm that is silence rather
than a no.
"""
from __future__ import annotations

FILLER = frozenset("""
a an and the of in at on for to from with by or is are was were be been being that this these those
me my our we us you your i it its as into over under about across per via than then so such any all
some more most less least other others new show find get give list search look looking want need who
what which where when how why please just only also including include included based
investor investors fund funds firm firms vc vcs backer backers capital money invest invests investing
investment investments round rounds cheque check cheques checks writes write ticket tickets
startup startups company companies business businesses founder founders team teams people
""".split())

# Only FILED keys may harden. A stated key describes what a firm says about itself, and it is unknown for
# most firms until their site has been read — a must on one would filter by our own crawl progress rather
# than by anything about the market, which is the coverage trap the spec's §0 exists to avoid.
MUST_KEYS = frozenset({"investor_type", "country", "state", "metro", "still_deploying", "registered_with"})

# Values that are ordinary English words as well as facet values.
RISKY_VALUES = frozenset({"angel", "growth", "other", "government", "seed", "partner", "partners"})

ALIASES = {
    "investor_type": {"vc": "venture_fund", "venture capital": "venture_fund", "venture fund": "venture_fund",
                      "vc fund": "venture_fund", "private equity": "pe_fund", "pe": "pe_fund",
                      "buyout": "pe_fund", "angels": "angel", "angel investor": "angel",
                      "angel group": "angel_group", "angel network": "angel_group",
                      "fund of funds": "fund_of_funds", "fof": "fund_of_funds",
                      "corporate vc": "corporate_vc", "cvc": "corporate_vc",
                      "family office": "family_office", "sovereign wealth": "sovereign",
                      "sovereign fund": "sovereign", "venture debt": "venture_debt",
                      "accelerator": "accelerator", "incubator": "accelerator", "studio": "studio",
                      "seed fund": "seed_fund", "growth fund": "growth_fund", "endowment": "endowment",
                      "hedge fund": "crossover_hedge", "crossover": "crossover_hedge"},
    "country": {"usa": "us", "u s": "us", "united states": "us", "america": "us", "american": "us",
                "united kingdom": "uk", "britain": "uk", "british": "uk", "england": "uk",
                "india": "in", "indian": "in", "uae": "ae", "emirates": "ae", "dubai": "ae",
                "singapore": "sg", "australia": "au", "israel": "il", "canada": "ca",
                "germany": "de", "france": "fr", "europe": "europe"},
    "metro": {"bay area": "bay_area", "sf": "bay_area", "san francisco": "bay_area",
              "silicon valley": "bay_area", "sand hill": "bay_area", "menlo park": "bay_area",
              "nyc": "new_york", "new york": "new_york", "la": "los_angeles", "los angeles": "los_angeles",
              "london": "london", "bangalore": "bangalore", "bengaluru": "bangalore",
              "mumbai": "mumbai", "singapore": "singapore", "tel aviv": "tel_aviv", "boston": "boston"},
    "still_deploying": {"active": "yes_recent", "still investing": "yes_recent", "deploying": "yes_recent",
                        "raising": "yes_recent", "dormant": "quiet", "quiet": "quiet", "inactive": "quiet"},
    "stated_stage": {"series a": "series_a", "series b": "series_b", "series c": "series_c",
                     "pre seed": "pre_seed", "preseed": "pre_seed", "pre-seed": "pre_seed",
                     "early stage": "seed", "late stage": "growth"},
    "leads_rounds": {"lead": "leads", "leads": "leads", "leading": "leads", "follow": "follows",
                     "follows": "follows", "co-invest": "follows"},
    "sector_focus": {"ai infra": "ai_infra", "ai infrastructure": "ai_infra", "llm": "llm_apps",
                     "dev tools": "devtools", "developer tools": "devtools", "climate": "climate_energy",
                     "biotech": "bio_health", "healthtech": "bio_health", "crypto": "crypto_web3",
                     "web3": "crypto_web3", "e-commerce": "ecommerce", "insurtech": "insurance",
                     "legaltech": "legal_compliance", "defense": "space_defense", "deeptech": "hardware_semis"},
}


def config() -> dict:
    return {"filler": FILLER, "must_keys": MUST_KEYS, "risky_values": RISKY_VALUES, "aliases": ALIASES}
