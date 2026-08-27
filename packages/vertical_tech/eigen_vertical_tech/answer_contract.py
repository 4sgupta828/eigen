"""Tech ANSWER-CONTRACT — the question-driven evidence REGIME (flag EIGEN_ANSWER_CONTRACT).

ONE small LLM classification (`TECH_CONTRACT_PROMPT`) decides what KIND of evidence a question demands;
`ANSWER_PROFILES[stance]` then supplies the opaque knobs the kernel threads into retrieval + ranking +
compose. This is where the intelligence lives — retrieval stays generic. The split honours our rules:
the LLM owns the semantic judgment (which regime), code owns the mechanics (stance → knobs), and no
regime EVER fabricates an evidence tier — "current" merely chooses to LEAD with recency and label
un-benchmarked releases as such; "established" leads with authority. Fail-safe: any classification
miss → "balanced" (today's behavior). The kernel interprets none of these strings.
"""
from __future__ import annotations

from .freshness import TECH_FRESHNESS_POLICY

# System prompt for the ONE derivation call. Emits {mode, stance, axes}. mode stays "exploratory"
# (we use the contract for STANCE, not enumeration); stance is the evidence regime.
TECH_CONTRACT_PROMPT = """You classify a TECH-RESEARCH question to decide what KIND of evidence best
answers it. Output JSON with:
- `mode`: always "exploratory".
- `stance`: ONE of:
  - "current"  — the question is about the CURRENT/LATEST state, newest releases, what JUST happened,
    who leads RIGHT NOW, recent news/funding/launches, or where things are HEADED. Freshness matters
    more than long-established proof. (e.g. "what are the latest frontier models", "who leads now",
    "recent AI funding", "what's new in X").
  - "established" — the question is about PROVEN, benchmarked, peer-reviewed, well-tested, foundational
    knowledge: how something WORKS, why, established comparisons, seminal methods, durable technical
    fact. Authority and rigor matter more than recency. (e.g. "how does RAG work", "what is the
    transformer architecture", "proven techniques for X", "benchmarked comparison of established Y").
  - "balanced" — anything that is neither clearly current-events nor clearly foundational, or a mix.
- `axes`: 0-5 short evidence dimensions the answer must cover (optional).

Decide from the QUESTION'S INTENT, not keywords. When genuinely unsure, choose "balanced". Output ONLY
the JSON object."""


# CONTRACT-RENDERED COMPOSE prompt (EIGEN_CONTRACT_COMPOSE). Unlike the base prompt above (mode always
# "exploratory"), this one classifies the ANSWER SHAPE the question asks for — because compose now renders
# it. The load-bearing addition: recognize an ENUMERATIVE ask ("all X", "every Y", "build me a table",
# "break down into categories", "compare across the field") as enumerative EVEN WHEN the items are not
# named — the row items are then DISCOVERED from the evidence. This is the fix for "build me a table of all
# problems", which the base prompt flattened to exploratory. Rule 18: the LLM judges shape from intent.
TECH_CONTRACT_COMPOSE_PROMPT = """You classify a TECH-RESEARCH question to decide what SHAPE of answer it
asks for. Output JSON with:
- `mode`: ONE of:
  - "enumerative" — the question asks you to ENUMERATE / LIST / TABULATE / BREAK DOWN a SET of things, or
    to survey/compare ACROSS a field of multiple items. Signals: "list all…", "every…", "build me a
    table", "what are the … (plural set)", "break this down by category", "map/compare the players/
    approaches/problems/use-cases". CHOOSE THIS EVEN IF the specific items are NOT named in the question —
    a "table of all X" names the DIMENSIONS, not the rows; the rows get discovered from evidence. The
    deliverable is a COMPLETE multi-item breakdown, not a single verdict.
  - "exploratory" — anything else: a focused/direct question, a how/why explanation, a single-subject
    diligence, a yes/no or build-vs-buy DECISION, "assess the moat", "what did X raise". These want a
    direct reasoned answer, NOT a table. This is the DEFAULT — when unsure between the two, choose
    "exploratory" (a wrongly-forced table is worse than a missed one).
- `entities`: if the question NAMES the specific items to enumerate (e.g. "compare Cursor, Copilot, and
  Cody"), list them (the row items). If the items are NOT named (e.g. "all problems", "every approach"),
  leave `entities` EMPTY — they will be discovered from the evidence. For a non-enumerative question,
  empty.
- `axes`: 0-5 short evidence DIMENSIONS the answer must cover — for an enumerative ask these are the table
  COLUMNS (e.g. "value mechanism", "ROI evidence", "integration complexity", "limitations"). Extract them
  from what the question asks to understand.
- `stance`: ONE of "current" | "established" | "balanced" (as in the base tech classifier: current = the
  latest/newest state; established = proven/foundational; balanced = neither or a mix).

Decide from the QUESTION'S INTENT, not keywords. Output ONLY the JSON object."""


# SUBJECT-KIND addendum — the extra `subject_kind` output key that lets the kernel route the
# entity-scoped open-web probe (flag EIGEN_WEB_ENTITY_OPEN) and the deep company/person readers
# (flags EIGEN_DEEP_COMPANY_READER / EIGEN_DEEP_PEOPLE_READER). Factored into ONE constant so EVERY
# contract prompt that needs it (the base entity variant AND the landscape variant) stays in lockstep:
# a person/single-entity question must classify identically no matter which base prompt is active. The
# judgment is the LLM's (Rule 18): no keyword matching — decide from the question's intent.
_SUBJECT_KIND_ADDENDUM = """

ALSO add one more key to the SAME JSON object:
- `subject_kind`: ONE of:
  - "specific_entity" — the question is DILIGENCE on a SINGLE NAMED company / product / project: what
    it is, how its tech works, its moat/traction/team/funding/risks (e.g. "what is Blazel", "how does
    X's tech work and what's its moat", "is Acme's approach defensible", "tell me about the startup Y").
    A question about ONE named company's FOUNDERS, team, or leadership is diligence on THAT company →
    specific_entity, even when it says "founders" (plural) (e.g. "tell me everything about Traversal.com
    founders", "who runs Acme", "Acme's founding team"). It becomes "general" only when NO single company
    is named (a class/many companies, e.g. "founders of AI SRE startups").
  - "person" — the question is DILIGENCE on a SINGLE NAMED person: biography, role, career history,
    founder/investor background, public views, affiliations, or reputation (e.g. "tell me about Jane
    Roe", "what has Pat Lee built", "what is Sam Altman's background").
  - "general" — anything else: a landscape/population map, a comparison across many players, a how/why
    about a concept, a trend, or any question NOT centered on one named entity.
  Decide from the QUESTION'S INTENT, not keywords. When unsure, choose "general".

WHEN `subject_kind` is "person" OR "specific_entity", ALSO set `entities` to a ONE-element list holding
the exact named subject — the person's name (for "person") or the company/product name (for
"specific_entity"), e.g. entities=["Zain Jaffer"] or entities=["Traversal.com"]. This names the subject
the deep reader will research. For "general" leave `entities` as it was (the landscape categories, or
empty). Output ONLY the JSON object (WITH the extra `subject_kind` key alongside the others)."""


# REFLECTION addendum (flag EIGEN_REFLECTION). Appended to whichever contract prompt is active when
# reflection is on, so the ONE derivation call ALSO returns the "heart of the question" — the user's real
# underlying intent — used to steer retrieval + compose WITHOUT replacing the literal question. Rule 18 +
# grounding: these are judgments about the QUESTION, never assertions of fact about any entity; the
# span-gate still grounds every emitted claim. Emitted only under the flag → OFF derivation is identical.
TECH_REFLECTION_ADDENDUM = """

ALSO reflect on the HEART of the question and add these keys to the SAME JSON object (judge from the
QUESTION ALONE — never assert facts about any company/person/technology; these only shape HOW we answer):
- `intent`: ONE short sentence naming the user's REAL underlying job — the decision or understanding they
  are actually after beneath the literal words (e.g. for "tell me everything about Traversal.com founders"
  → "assess whether Traversal's founding team is credible/experienced enough to back", NOT "list the
  founders"; for a landscape question → "understand the competitive structure and where the durable
  advantage lies well enough to place a bet or build").
- `intent_confidence`: "high" if that intent is unambiguous from the question; "medium" if a reasonable
  inference; "low" if the question is genuinely ambiguous or you would be GUESSING. When "low", keep
  `intent` faithful to the LITERAL question — do NOT invent a deeper intent you are unsure of.
- `answer_brief`: ONE or TWO sentences naming what a GREAT answer MUST deliver to satisfy that intent —
  the specific dimensions/shape it should cover (this guides coverage + framing; it states no facts).
Decide from the question's real intent, not keywords. Output ONLY the JSON object (now also with
`intent`, `intent_confidence`, and `answer_brief`)."""


# ENTITY-OPEN variant (flag EIGEN_WEB_ENTITY_OPEN). Byte-identical derivation to TECH_CONTRACT_PROMPT
# PLUS the `subject_kind` key. Built by concatenation so it stays in lockstep with the base prompt.
TECH_CONTRACT_PROMPT_ENTITY = TECH_CONTRACT_PROMPT + _SUBJECT_KIND_ADDENDUM


# Per-stance policy knobs (opaque to the kernel). See eigen_kernel/contract/manifest.py::answer_profiles.
_CURRENT_RECENCY = {"min_rank": 0, "weight": 0.5, "horizon_years": 1}   # strong, short-horizon recency

ANSWER_PROFILES: dict = {
    "current": {
        "recency": _CURRENT_RECENCY,
        "suppress_authority": True,        # a fresh announcement must be able to out-rank an older benchmark
        # web_open deliberately OFF: fully dropping the whitelist surfaced content-farm/SEO junk
        # (icreat.ai, swfte.com…) that out-ranked authoritative pages. The EXPANDED whitelist now
        # includes the labs' own announcement blogs (openai.com/anthropic.com/blog.google/x.ai…) +
        # leaderboards + trade press, which — with the deep discover→drill research below — already
        # reaches the newest models (GPT-5.6/Opus 5/Kimi K3/DeepSeek-V4-Pro) via CREDIBLE sources.
        "web_open": False,
        "web_recency_days": 150,           # per-request web floor ≈ the current ~5 months
        "max_steps": 14,                   # thorough: discover the leaderboard, then drill into each model
        "compose_claim_cap": 60,           # a landscape answer spans ~15 models, not a handful
        "planner_steer": (
            "This is a CURRENT / LATEST-STATE question. Research it THOROUGHLY, like an analyst: FIRST "
            "search the current model leaderboard(s) and THIS MONTH's releases/announcements; then, for "
            "EACH leading provider and EACH newest model you discover (e.g. the specific latest models "
            "from OpenAI, Anthropic, Google, xAI, Meta, DeepSeek, Moonshot/Kimi, Qwen, Mistral, Z.ai), "
            "issue a SEPARATE targeted search for that exact model/provider to get its own page. Do not "
            "stop after one or two overview searches — cover the whole field."),
        "answer_directive": (
            "REGIME = CURRENT STATE — produce a COMPREHENSIVE, well-structured landscape, not a short "
            "memo. Lead with the newest developments. Include: (1) a TIERED leaderboard TABLE of the "
            "current frontier models (provider · model · rough standing · what stands out), ordered by "
            "current standing; (2) a per-provider read of who leads and each provider's distinct "
            "strength; (3) a short, clearly-labeled OUTLOOK synthesized ONLY from the cited facts. "
            "CURRENCY DISCIPLINE: label each model's status from its cited source — 'available', "
            "'announced', or 'on the leaderboard on paper' — and NEVER present an un-benchmarked release "
            "as if it had verified benchmark results. Cover as many current models as the evidence "
            "supports; do not lead with a prior generation merely because it is more benchmarked."),
    },
    "established": {
        "recency": None,                   # no recency boost — age is not a virtue here
        "suppress_authority": False,       # authority-first: keep the evidence-tier ranking
        "web_recency_days": None,
        "planner_steer": (
            "This question is about ESTABLISHED, proven knowledge. Prefer peer-reviewed papers, "
            "reproducible benchmarks, primary filings, and well-reviewed sources over news or "
            "announcements; foundational/seminal work is welcome regardless of age."),
        "answer_directive": (
            "REGIME = ESTABLISHED KNOWLEDGE. Prioritize the best-verified, benchmarked, peer-reviewed, "
            "primary evidence; foundational/seminal work is welcome regardless of age. Treat unverified "
            "announcements or news as low-weight signal, clearly labeled — never as established fact."),
    },
    # "balanced" is intentionally absent → no profile matches → the kernel keeps today's behavior. Kept
    # here as documentation; an explicit no-op entry would behave identically.
}


# LANDSCAPE-COVERAGE contract (flag EIGEN_LANDSCAPE_COVERAGE). Same one-call contract, but for a
# "map the landscape / examine ALL X / cluster companies / who is building" question it returns
# mode="enumerative" with the conceptual CATEGORIES as `entities` — so the kernel fans retrieval out
# per category (entity×axis legs) instead of a few narrow searches. GUARDRAIL (Rule 18 + grounding):
# the categories are a conceptual FRAME derived from knowledge (safe — a frame is not a fact); the
# companies, founders, funding, and stage are NEVER emitted here and must be extracted from retrieved
# evidence downstream. Non-landscape questions stay exploratory (identical to TECH_CONTRACT_PROMPT).
TECH_LANDSCAPE_CONTRACT_PROMPT = """You classify a TECH-RESEARCH question and, for LANDSCAPE/POPULATION
questions, plan its coverage. Output JSON with `mode`, `entities`, `axes`, `stance`.

FIRST decide `mode`:
- "enumerative" — the question asks to MAP A LANDSCAPE or examine a POPULATION: "examine all X",
  "map the landscape", "cluster the companies/startups", "who is building X", "the whole market for X",
  "list the players in X" — especially when it asks for many entities across several dimensions. For
  these, set `entities` to the 6-10 CONCEPTUAL CATEGORIES the landscape breaks into (the economic
  segments / sub-fields a knowledgeable analyst would use to partition it — NOT company names). These
  categories are a search frame, not an answer: name the SEGMENTS, never specific companies/founders/
  funding here. Set `axes` to the DIMENSIONS the question asks to compare across (e.g. moat,
  differentiation, customer segment, funding, stage, founders) — 3-6 short phrases.
- "exploratory" — anything else (a normal question, a single-entity ask, a how/why, a lookup). Leave
  `entities` empty.

THEN `stance`: "current" (latest/newest/who-leads-now/recent funding) | "established" (proven/
benchmarked/how-it-works/foundational) | "balanced" (mixed/unsure). Decide from INTENT, not keywords.

Output ONLY the JSON object. For an enumerative landscape question the categories must be genuine
distinct segments (e.g. for "AI startups": frontier models, coding agents, horizontal enterprise agents,
vertical AI, AI search/knowledge, voice/multimodal, AI infrastructure, physical AI/robotics, defense/
industrial AI, generative media) — pick the ones that actually fit the specific question's scope."""


# LANDSCAPE + SUBJECT-KIND variant. When the landscape-coverage flag is on, the app swaps the ACTIVE
# contract prompt to the landscape prompt (app.py) — which, without this, DROPS the `subject_kind` key
# and so silently disables the deep company/person readers for EVERY question (a single-entity or person
# ask under landscape coverage could never route a deep read). This variant restores `subject_kind` on
# the landscape path so the two orthogonal concerns — landscape enumeration AND deep-reader routing —
# both work. A landscape/population question stays enumerative with subject_kind="general"; a person or
# single-entity ask stays exploratory (empty entities) and carries subject_kind="person"/"specific_entity"
# to route its deep read. Same lockstep addendum as the base entity variant.
TECH_LANDSCAPE_CONTRACT_PROMPT_ENTITY = TECH_LANDSCAPE_CONTRACT_PROMPT + _SUBJECT_KIND_ADDENDUM
