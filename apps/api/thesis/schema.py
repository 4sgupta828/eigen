"""The claim ladder — the fixed schema a thesis is decomposed into.

A thesis ("mid-market banks will pay for automated evidence collection") is not one question and
cannot be tested as one. It rests on a ladder of propositions that could each be false, and the
propositions are NOT equally knowable. That inequality is the whole design: two of them can never be
settled from documents however much we ingest, and pretending otherwise is how a stress test becomes
a hallucination engine.

The ladder is DECLARED HERE and is not the model's to edit. The model instantiates a rung for a given
thesis — what is the problem, who has it, which segment — and never decides whether the rung is
settleable, because a model that has just found encouraging text will say that it is.
"""
from __future__ import annotations

# How a rung can be settled.
#   corpus     — the public record answers it; asking a human is a waste of their time
#   partly     — the record gets you the category, a person gets you the specifics
#   call_only  — no document can settle it. Structural, not a coverage gap.
CORPUS, PARTLY, CALL_ONLY = "corpus", "partly", "call_only"

# (key, question put to the thesis, how it settles, what settles it)
LADDER: tuple[tuple[str, str, str, str], ...] = (
    ("problem_exists", "Does the problem actually occur in the wild?", CORPUS,
     "forum workarounds, postmortems, filed risk factors"),
    ("status_quo_costs", "Does the status quo cost real money, headcount or time?", CORPUS,
     "migration write-ups, glue repos, write-offs and margin commentary"),
    ("already_spending", "Does anyone already allocate budget or people to it?", CORPUS,
     "grants, spend categories, hiring for the problem"),
    ("function_owns", "Does a named function own the problem?", CORPUS,
     "job titles, filed officer roles, conference talks by the owner"),
    ("budget_category", "Does a budget category already exist to buy this from?", PARTLY,
     "incumbent pricing, spend categories, customer concentration"),
    ("buyer_nameable", "Can an economic buyer be named — not a user?", PARTLY,
     "case studies naming a champion, filed officer roles, procurement records"),
    ("switching_feasible", "Is the switching cost surmountable?", CALL_ONLY,
     "nobody publishes latent ease; the record shows obstacles only"),
    ("catalyst", "Is something forcing a revisit now?", PARTLY,
     "regulation, a technical discontinuity, a public failure"),
    ("willingness_to_pay", "Does willingness to pay exceed the cost to serve?", CALL_ONLY,
     "no document records a budget never allocated for a SKU never offered"),
    ("enough_buyers", "Do enough such buyers exist?", CORPUS,
     "firm counts by segment, funding density"),
)

RUNGS = tuple(k for k, _q, _s, _w in LADDER)
QUESTION = {k: q for k, q, _s, _w in LADDER}
SETTLEABLE = {k: s for k, _q, s, _w in LADDER}
SETTLED_BY = {k: w for k, _q, _s, w in LADDER}

# Who can answer a rung the record cannot. The request named these three roles; they are not
# interchangeable and they are found from different evidence (see people.py).
BUYER, OPERATOR, ADVISOR = "buyer", "operator", "advisor"
ASK_WHO: dict[str, tuple[str, ...]] = {
    "problem_exists": (OPERATOR,),
    "status_quo_costs": (OPERATOR,),
    "already_spending": (BUYER, OPERATOR),
    "function_owns": (BUYER, ADVISOR),
    "budget_category": (BUYER,),
    "buyer_nameable": (BUYER, ADVISOR),
    "switching_feasible": (OPERATOR, BUYER),
    "catalyst": (ADVISOR,),
    "willingness_to_pay": (BUYER,),
    "enough_buyers": (ADVISOR,),
}

ROLE_LABEL = {BUYER: "someone who buys this", OPERATOR: "someone who lives the status quo",
              ADVISOR: "someone who watches the category"}

# ---- verdicts ---------------------------------------------------------------------------------
# `under_tested` is the one nobody else ships and the most honest state in the set: we went looking
# for evidence AGAINST this and found none either way. It comes from the kernel's existing
# disconfirming-search flag (research/react.py) — disconfirmation attempted is not disconfirmation
# found, and a claim nobody could attack is not thereby proven.
SUPPORTED, CONTRADICTED, UNDER_TESTED, OPEN, UNSETTLEABLE = (
    "supported", "contradicted", "under_tested", "open", "unsettleable")
VERDICTS = (SUPPORTED, CONTRADICTED, UNDER_TESTED, OPEN, UNSETTLEABLE)

VERDICT_LABEL = {
    SUPPORTED: "the record supports this",
    CONTRADICTED: "the record argues against this",
    UNDER_TESTED: "we tried to break this and found nothing either way",
    OPEN: "not looked at yet",
    UNSETTLEABLE: "no document can settle this — it needs a person",
}

# ---- evidence ---------------------------------------------------------------------------------
# The three registers, unchanged from the rest of Eigen. A call is `stated` with a basis naming who
# said it: strong evidence for exactly the rungs documents cannot reach, and never laundered upward.
FILED, STATED, OBSERVED = "filed", "stated", "observed"
SIDE_FOR, SIDE_AGAINST = "for", "against"

# What a source is, decided by where it came from — never by how confident the text sounds.
SOURCE_REGISTER = {
    "edgar": FILED, "companies_house": FILED, "uspto": FILED, "patentsview": FILED,
    "nsf": FILED, "nih_reporter": FILED,
    "github": OBSERVED, "huggingface": OBSERVED,
    "arxiv": STATED, "openalex": STATED, "crossref": STATED, "semantic_scholar": STATED,
    "eng_blog": STATED, "founder_essay": STATED, "expert_feed": STATED, "web": STATED,
    "news": STATED, "startup_news": STATED, "gdelt": STATED,
    "hackernews": STATED, "reddit": STATED, "stackexchange": STATED,
    "podcast": STATED, "show_notes": STATED, "youtube_chapters": STATED,
    "wikipedia": STATED, "wikidata": STATED, "yc": STATED,
    "call": STATED,
}

# Sources that are SENTIMENT, not description. The standing directive keeps these out of any
# conclusion; here they are also the most seductive false positive in the whole mode — an
# enthusiastic forum thread reads exactly like demand and is not.
SIGNAL_ONLY = frozenset({"hackernews", "reddit", "gdelt", "news", "startup_news"})


def register_of(source_key: str) -> str:
    return SOURCE_REGISTER.get((source_key or "").lower(), STATED)


def is_signal_only(source_key: str) -> bool:
    return (source_key or "").lower() in SIGNAL_ONLY


def labels() -> dict:
    """Everything the client needs to render a thesis without hardcoding the vocabulary."""
    return {
        "ladder": [{"key": k, "question": q, "settleable": s, "settled_by": w,
                    "ask": list(ASK_WHO.get(k, ()))} for k, q, s, w in LADDER],
        "verdicts": VERDICT_LABEL,
        "roles": ROLE_LABEL,
        "registers": {FILED: "filed", STATED: "stated", OBSERVED: "observed"},
    }
