"""The startup facet SCHEMA — the vocabulary of Startup Search (docs/specs/startup-search.md §3).

Mechanics (types, contract grammar, evaluator, counts) live in `eigen_kernel.facets`; this module only says
WHICH keys exist, their vocabularies / bands / order, one line of guidance per key for the extractor and the
compiler, the ranking weights, and the labels the UI shows. `unknown` is never stored: a company with no row
for a key is unknown by absence (a must excludes it; prefer / avoid ignore it; the rail counts it)."""
from __future__ import annotations

from eigen_kernel.facets import FacetKey, FacetSchema, FacetType, FacetWeights

KIND = "company"
C = (KIND,)

STAGES = ("pre_seed", "seed", "series_a", "series_b", "series_c", "series_d_plus", "growth")
REVENUE_RANGES = ("no_revenue", "1_1m", "1m_5m", "5m_25m", "25m_100m", "100m_plus")
TECH_AREAS = ("ai_infra", "llm_apps", "agents", "devtools", "data", "security", "robotics", "hardware_semis",
              "bio_health", "climate_energy", "fintech", "consumer", "enterprise_saas", "space_defense", "other")
CUSTOMERS = ("enterprise", "smb", "developer", "consumer", "government")
BUSINESS_MODELS = ("saas", "usage", "marketplace", "hardware", "open_core", "services", "consumer_subscription", "other")
STATUSES = ("active", "acquired", "shut_down", "public")
PROGRAMS = ("yc", "techstars", "spc", "ai_fund", "a16z_speedrun", "neo", "pear", "hf0", "antler", "ef", "alchemist",
            "500", "sequoia_arc", "other")
EVIDENCE_STRENGTH = ("single_source", "two_sources", "filing_backed")
OPEN_SOURCE = ("found",)

USD_BANDS = (("under_1m", None, 1e6), ("1m_5m", 1e6, 5e6), ("5m_20m", 5e6, 20e6), ("20m_50m", 20e6, 50e6),
             ("50m_100m", 50e6, 100e6), ("100m_plus", 100e6, None))
ARR_BANDS = (("under_100k", None, 1e5), ("100k_1m", 1e5, 1e6), ("1m_10m", 1e6, 10e6), ("10m_50m", 10e6, 50e6), ("50m_plus", 50e6, None))
AWARD_BANDS = (("under_500k", None, 5e5), ("500k_2m", 5e5, 2e6), ("2m_plus", 2e6, None))
MONTHS_BANDS = (("0_6", None, 6.0), ("6_12", 6.0, 12.0), ("12_24", 12.0, 24.0), ("24_plus", 24.0, None))
FOUNDER_BANDS = (("1", 1.0, 2.0), ("2", 2.0, 3.0), ("3", 3.0, 4.0), ("4_plus", 4.0, None))
HEADCOUNT_BANDS = (("1_10", None, 11.0), ("11_50", 11.0, 51.0), ("51_200", 51.0, 201.0), ("201_1000", 201.0, 1001.0), ("1000_plus", 1001.0, None))
YEAR_BANDS = (("before_2020", None, 2020.0), ("2020_2022", 2020.0, 2023.0), ("2023", 2023.0, 2024.0), ("2024", 2024.0, 2025.0), ("2025_plus", 2025.0, None))
HIRING_BANDS = (("1_5", 1.0, 6.0), ("6_20", 6.0, 21.0), ("20_plus", 21.0, None))
PATENT_BANDS = (("1_3", 1.0, 4.0), ("4_plus", 4.0, None))

SCHEMA = FacetSchema(keys=(
    # ---- stage and money ----
    FacetKey(key="stage", type=FacetType.ordinal, kinds=C, label="Stage", values=STAGES,
             guidance="ONLY a round name the text STATES (seed, Series A, …); an amount alone is never a stage; 'seed extension' / 'SAFE' → seed, 'bridge' → the round it follows if stated"),
    FacetKey(key="financing_scale", type=FacetType.numeric, kinds=C, label="Latest filing sold", unit="usd", bands=USD_BANDS,
             guidance="(derived: the amount sold on the latest SEC Form D — not a stage)"),
    FacetKey(key="total_disclosed_funding", type=FacetType.numeric, kinds=C, label="Total disclosed funding", unit="usd", bands=USD_BANDS,
             guidance="(derived from financing events; filings and stated rounds)"),
    FacetKey(key="last_round_amount", type=FacetType.numeric, kinds=C, label="Last round", unit="usd", bands=USD_BANDS, guidance="(derived)"),
    FacetKey(key="last_round_months", type=FacetType.numeric, kinds=C, label="Last round age", unit="months ago", bands=MONTHS_BANDS, guidance="(derived)"),
    FacetKey(key="revenue_range", type=FacetType.ordinal, kinds=C, label="Revenue range (filing)", values=REVENUE_RANGES,
             guidance="(from the SEC Form D revenue-range box; 'Decline to Disclose' is unknown)"),
    FacetKey(key="arr", type=FacetType.numeric, kinds=C, label="ARR (self-reported)", unit="usd", bands=ARR_BANDS,
             guidance="a figure the text states as ARR or annual recurring revenue; run-rate, GMV, bookings and 'revenue' are NOT arr"),
    FacetKey(key="non_dilutive", type=FacetType.numeric, kinds=C, label="Non-dilutive awards", unit="usd", bands=AWARD_BANDS, guidance="(from award records)"),
    # ---- what they do ----
    FacetKey(key="tech_area", type=FacetType.categorical, kinds=C, label="Tech area", values=TECH_AREAS,
             guidance="1–2 areas from the list that describe what the company builds (ai_infra = models, inference, training, eval tooling; llm_apps = products built on LLMs; agents = autonomous agents; devtools; data = data infrastructure / analytics; security; robotics; hardware_semis; bio_health; climate_energy; fintech; consumer; enterprise_saas; space_defense)"),
    FacetKey(key="customer", type=FacetType.categorical, kinds=C, label="Customer", values=CUSTOMERS,
             guidance="who buys: enterprise, smb, developer, consumer, government — as the text states or clearly implies"),
    FacetKey(key="business_model", type=FacetType.categorical, kinds=C, label="Business model", values=BUSINESS_MODELS,
             guidance="how they charge, only when the text says (pricing page, 'usage-based', 'marketplace', hardware sales, open core)"),
    FacetKey(key="status", type=FacetType.categorical, kinds=C, label="Status", values=STATUSES, guidance="acquired when the pages say acquired / joining / has joined another company; shut_down when they say closed or wound down; public when listed; else active"),
    # ---- backers and programs ----
    FacetKey(key="lead_investor", type=FacetType.set, kinds=C, label="Lead investor", top_n=15, guidance="the fund the text says LED a round, as a lowercase slug (a16z, sequoia)"),
    FacetKey(key="investor", type=FacetType.set, kinds=C, label="Investors", top_n=20,
             guidance="funds the text says INVESTED (not customers, not partners, not a logo wall), lowercase slugs"),
    FacetKey(key="program", type=FacetType.categorical, kinds=C, label="Program", values=PROGRAMS,
             guidance="accelerator / studio / fellowship the company went through, only when stated (Y Combinator → yc, South Park Commons → spc, AI Fund → ai_fund)"),
    # ---- people ----
    FacetKey(key="founder_count", type=FacetType.numeric, kinds=C, label="Founders", unit="people", bands=FOUNDER_BANDS, guidance="(derived from named founders)"),
    FacetKey(key="founder_prior_company", type=FacetType.set, kinds=C, label="Founders came from", top_n=15,
             guidance="companies the text says a FOUNDER previously worked at, lowercase slugs (google, stripe, openai)"),
    FacetKey(key="headcount", type=FacetType.numeric, kinds=C, label="Headcount", unit="people", bands=HEADCOUNT_BANDS,
             guidance="team size only when a number is stated"),
    # ---- place and time ----
    FacetKey(key="country", type=FacetType.set, kinds=C, label="Country", top_n=12, guidance="lowercase ISO-ish code of the HQ country (us, uk, de, in, ca, fr, il)"),
    FacetKey(key="metro", type=FacetType.set, kinds=C, label="Metro", top_n=15, guidance="normalized HQ metro token (bay_area, new_york, london, boston, seattle, los_angeles, austin)"),
    FacetKey(key="founded", type=FacetType.numeric, kinds=C, label="Founded", unit="year", bands=YEAR_BANDS, guidance="the founding year when stated"),
    # ---- momentum signals (structured; never sentiment) ----
    FacetKey(key="hiring", type=FacetType.numeric, kinds=C, label="Open roles", unit="roles", bands=HIRING_BANDS, guidance="(from the company's ATS board)"),
    FacetKey(key="hiring_function", type=FacetType.set, kinds=C, label="Hiring for", top_n=10, guidance="(from the company's ATS board)"),
    FacetKey(key="open_source", type=FacetType.categorical, kinds=C, label="Open source", values=OPEN_SOURCE, guidance="(from a public code host)"),
    FacetKey(key="patents_granted", type=FacetType.numeric, kinds=C, label="Granted patents", unit="patents", bands=PATENT_BANDS, guidance="(from the patent office; granted only)"),
    FacetKey(key="evidence_strength", type=FacetType.ordinal, kinds=C, label="Evidence", values=EVIDENCE_STRENGTH, guidance="(derived: how many independent sources back the funding facts)"),
))

# Keys the extractor may fill from a company's own pages (everything else is structured or derived).
EXTRACTABLE = ("stage", "arr", "tech_area", "customer", "business_model", "status", "lead_investor", "investor", "program",
               "founder_prior_company", "headcount", "country", "metro", "founded")
# Keys whose value is self-reported when it comes from the company's own site — the card says so.
SELF_REPORTED_SENSITIVE = ("arr", "stage", "headcount", "investor", "lead_investor")
# A must on these is downgraded to a prefer by the compiler (low public coverage / self-selected); the user's own
# rail taps are never downgraded.
LOW_COVERAGE_DEFAULT_PREFER = ("arr",)

WEIGHTS = FacetWeights(
    prefer={"program": 0.15, "lead_investor": 0.15, "investor": 0.10, "tech_area": 0.12, "founder_prior_company": 0.12,
            "country": 0.10, "metro": 0.10, "customer": 0.08, "hiring_function": 0.05, "stage": 0.10},
    avoid={"status": 0.20, "tech_area": 0.15, "program": 0.15, "investor": 0.10, "country": 0.10},
    default_prefer=0.08, default_avoid=0.08, center_per_step=0.08, max_hits_per_key=3)

SCHEMA_VERSION = SCHEMA.version()

VALUE_LABELS = {
    "pre_seed": "pre-seed", "series_a": "series A", "series_b": "series B", "series_c": "series C", "series_d_plus": "series D+",
    "no_revenue": "no revenue", "1_1m": "$1–1M", "1m_5m": "$1–5M", "5m_25m": "$5–25M", "25m_100m": "$25–100M", "100m_plus": "$100M+",
    "under_1m": "< $1M", "5m_20m": "$5–20M", "20m_50m": "$20–50M", "50m_100m": "$50–100M",
    "under_100k": "< $100k", "100k_1m": "$100k–1M", "1m_10m": "$1–10M", "10m_50m": "$10–50M", "50m_plus": "$50M+",
    "under_500k": "< $500k", "500k_2m": "$500k–2M", "2m_plus": "$2M+",
    "0_6": "< 6 mo", "6_12": "6–12 mo", "12_24": "12–24 mo", "24_plus": "> 24 mo",
    "4_plus": "4+", "1_10": "1–10", "11_50": "11–50", "51_200": "51–200", "201_1000": "201–1,000", "1000_plus": "1,000+",
    "before_2020": "before 2020", "2020_2022": "2020–22", "2025_plus": "2025+", "1_5": "1–5", "6_20": "6–20", "20_plus": "20+", "1_3": "1–3",
    "ai_infra": "AI infra", "llm_apps": "LLM apps", "devtools": "dev tools", "hardware_semis": "hardware / semis", "bio_health": "bio / health",
    "climate_energy": "climate / energy", "enterprise_saas": "enterprise SaaS", "space_defense": "space / defense",
    "smb": "SMB", "saas": "SaaS", "open_core": "open core", "consumer_subscription": "consumer subscription", "shut_down": "shut down",
    "yc": "Y Combinator", "spc": "South Park Commons", "ai_fund": "AI Fund", "a16z_speedrun": "a16z speedrun", "hf0": "HF0", "ef": "Entrepreneur First",
    "sequoia_arc": "Sequoia Arc", "single_source": "one source", "two_sources": "two sources", "filing_backed": "filing-backed",
    "found": "found", "us": "US", "uk": "UK", "bay_area": "Bay Area", "new_york": "New York", "los_angeles": "Los Angeles",
}
KEY_ORDER = [k.key for k in SCHEMA.keys if k.navigable]


def labels() -> dict:
    """What the UI needs to render the rail: key labels, value labels, types, order."""
    return {"keys": {k.key: k.label for k in SCHEMA.keys}, "values": VALUE_LABELS,
            "types": {k.key: k.type.value for k in SCHEMA.keys}, "order": KEY_ORDER,
            "units": {k.key: k.unit for k in SCHEMA.keys if k.unit}, "version": SCHEMA_VERSION}


# Form D's revenue-range box, verbatim options → our ordinal (anything else, incl. "Decline to Disclose", is unknown).
FORMD_REVENUE = {"no revenues": "no_revenue", "$1 - $1,000,000": "1_1m", "$1,000,001 - $5,000,000": "1m_5m",
                 "$5,000,001 - $25,000,000": "5m_25m", "$25,000,001 - $100,000,000": "25m_100m", "over $100,000,000": "100m_plus"}

# YC's closed industry labels → tech_area (a lookup between two closed vocabularies, not a judgment).
YC_INDUSTRY_TO_AREA = {
    "b2b": "enterprise_saas", "fintech": "fintech", "healthcare": "bio_health", "consumer": "consumer",
    "industrials": "hardware_semis", "government": "space_defense", "real estate and construction": "other", "education": "consumer",
    "artificial intelligence": "llm_apps", "ai": "llm_apps", "machine learning": "ai_infra", "infrastructure": "ai_infra",
    "developer tools": "devtools", "engineering, product and design": "devtools", "data engineering": "data", "analytics": "data",
    "security": "security", "robotics": "robotics", "hardware": "hardware_semis", "semiconductors": "hardware_semis",
    "climate": "climate_energy", "energy": "climate_energy", "biotech": "bio_health", "drug discovery": "bio_health",
    "diagnostics": "bio_health", "medical devices": "bio_health", "aerospace": "space_defense", "defense": "space_defense",
    "space": "space_defense", "crypto / web3": "fintech", "payments": "fintech", "banking and exchange": "fintech",
    "insurance": "fintech", "marketplace": "consumer", "social": "consumer", "gaming": "consumer",
}


def area_from_yc_industries(industries: list[str]) -> list[str]:
    out: list[str] = []
    for i in industries or []:
        a = YC_INDUSTRY_TO_AREA.get(str(i).strip().lower())
        if a and a not in out:
            out.append(a)
    return out[:2]
