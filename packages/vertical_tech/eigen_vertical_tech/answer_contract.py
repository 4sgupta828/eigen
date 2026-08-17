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


# Per-stance policy knobs (opaque to the kernel). See eigen_kernel/contract/manifest.py::answer_profiles.
_CURRENT_RECENCY = {"min_rank": 0, "weight": 0.5, "horizon_years": 1}   # strong, short-horizon recency

ANSWER_PROFILES: dict = {
    "current": {
        "recency": _CURRENT_RECENCY,
        "suppress_authority": True,        # a fresh announcement must be able to out-rank an older benchmark
        "web_open": True,                  # OPEN WEB: reach labs' own announcement blogs + niche pages,
        #                                    not just the trusted whitelist (span-gate still verifies)
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
