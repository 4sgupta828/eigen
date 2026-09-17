"""The technology-investing adaptation of the kernel decision-testing engine.

The kernel (eigen_kernel.decision) knows how to interrogate ANY decision with typed Socratic questions
and aggregate what the evidence says. This profile teaches it what a TECHNOLOGY-INVESTMENT decision
rests on — the aspect ladder, how the aspects group into lines of inquiry, how to phrase the questions
in an investor's language, and the judgment thresholds. Swap this profile and the same engine informs a
different domain; the kernel never learns what a buyer or a filing is.
"""
from __future__ import annotations

from dataclasses import dataclass

from eigen_kernel.decision import (
    Aspect, Inquiry,
    TARGET_SUPPORTED, TARGET_CONTRADICTED, TARGET_UNTESTED,
    ASPECT_SUPPORT, ASPECT_CONTRADICTION,
    SUPPORTED, CONTRADICTED, UNDER_TESTED, UNSETTLEABLE,
)

from .authority import TechAuthorityPolicy

_AUTHORITY = TechAuthorityPolicy()

# The coverage ladder — the aspects a technology-investment thesis rests on: the SYSTEMATIC sweep a
# funding decision turns on. Fixed; not the model's to edit (a model that just read an encouraging
# sentence will call anything settleable). "corpus" = the public record can settle it; "partly" = partly;
# "call_only" = only a person who has lived it can, so it is NEVER sent to the evidence pipeline (its
# questions stand as the expert-call agenda; the aspect reads unsettleable).
#
# DELIBERATELY NOT rungs (panel 2026-09-16): the VALUE PROPOSITION, the GO-TO-MARKET motion, and WHAT
# CORE TECH is required are "how the thesis reads" — the FRAME step captures them as the mechanism, and
# they bias the question budget; making each a separate corpus rung double-counts one frame assumption
# across three aspects. What survives here are the EVIDENCE-SETTLEABLE dimensions. `feeds` = the opaque
# downstream artifact slot(s) an aspect's answers populate (deck/matrix keys), used only as a hint.
_LADDER: tuple[tuple[str, str, str, bool, tuple[str, ...]], ...] = (
    ("problem_exists", "Does the problem actually occur in the wild?", "corpus", True, ("problem",)),
    ("status_quo_costs", "Does the status quo cost real money, headcount or time?", "corpus", True,
     ("problem",)),
    ("already_spending", "Does anyone already allocate budget or people to it?", "corpus", True,
     ("problem", "business_model")),
    ("prior_landscape",
     "Who else — incumbents and past startups — has tried to solve this, and how did those attempts fare?",
     "corpus", True, ("competition", "central_idea")),
    ("differentiation",
     "Is there a specific, real difference from the named alternatives — not marketing?", "partly", True,
     ("solution", "tech_edge")),
    ("defensibility", "Is the advantage durable against incumbents and fast-followers?", "partly", True,
     ("competition", "moats")),
    ("tech_feasibility",
     "Is the core technology the thesis requires proven, or does it still carry research/build risk?",
     "partly", True, ("solution", "tech_edge")),
    ("traction", "Is there realized proof — named buyers, paid adoption, benchmarks — not just intent?",
     "corpus", True, ("traction",)),
    ("business_model",
     "Does the business model make money — pricing and unit economics that clear the cost to serve?",
     "partly", True, ("business_model",)),
    ("function_owns", "Does a named function own the problem?", "corpus", False, ("customers",)),
    ("budget_category", "Does a budget category already exist to buy this from?", "partly", False,
     ("business_model",)),
    ("buyer_nameable", "Can an economic buyer be named — not a user?", "partly", True, ("customers",)),
    ("enough_buyers", "Do enough such buyers exist?", "corpus", True, ("market",)),
    ("catalyst", "Is something forcing a revisit now?", "partly", False, ("why_now",)),
    ("regulatory_platform",
     "Does the thesis depend on rules, platforms or partners outside its control?", "partly", False,
     ("diligence",)),
    # call_only — no document settles these; the questions are the agenda for the expert call.
    ("switching_feasible", "Is the switching cost surmountable?", "call_only", True, ("diligence",)),
    ("willingness_to_pay", "Does willingness to pay exceed the cost to serve?", "call_only", True,
     ("business_model",)),
    ("team_credibility", "Are the founders credible for THIS problem — founder-market fit?", "call_only",
     True, ("team",)),
)

# The lines of inquiry — a fixed partition of the ladder into cards (every aspect in exactly one).
_INQUIRIES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("problem", "Is the problem real, and does it cost?", "the pain and its price",
     ("problem_exists", "status_quo_costs", "already_spending")),
    ("buyer", "Who owns the budget, and will they pay?", "the economic buyer and the money",
     ("function_owns", "budget_category", "buyer_nameable", "willingness_to_pay")),
    ("timing", "Can they switch, and why now?", "switching cost, catalyst, and outside dependencies",
     ("switching_feasible", "catalyst", "regulatory_platform")),
    ("market", "Is the market big enough, and does the model work?", "segment size and unit economics",
     ("enough_buyers", "business_model")),
    ("landscape", "Who else is in the field, and can this defend a lead?",
     "prior attempts, differentiation, and the moat", ("prior_landscape", "differentiation", "defensibility")),
    ("technology", "Is the core technology feasible?", "what the tech requires and whether it is proven",
     ("tech_feasibility",)),
    ("execution", "Is there proof, and can this team win it?", "realized traction and founder-market fit",
     ("traction", "team_credibility")),
)

_REQUIRED_GATES = ("span_ok", "entailed", "on_subject", "kind_ok", "period_ok")


def _qualified(row: dict) -> bool:
    gates = row.get("gate_results") or {}
    return row.get("relation") in ("supports", "contradicts") and all(
        gates.get(name) is True for name in _REQUIRED_GATES)


def _independent(rows: list[dict]) -> int:
    return len({str(r.get("independence_key") or r.get("document_id") or r.get("source_url") or "").strip()
                for r in rows
                if str(r.get("independence_key") or r.get("document_id") or r.get("source_url") or "").strip()})


# How each role's expertise reads as a people-search query. The role is WHO can settle a rung the
# record can't (see thesis ASK_WHO / people.py): a buyer owns the budget, an operator lives the status
# quo, an advisor tracks the category. These are ranking/query phrasings only — never evidence.
_ROLE_QUERY = {
    "buyer": "economic buyers and budget owners",
    "operator": "hands-on operators and practitioners who live the status quo",
    "advisor": "analysts and advisors who track the category",
}


_QUESTION_DIRECTIVE = """\
You are stress-testing a startup investment thesis with its author. For ONE aspect of the thesis, write
a balanced set of pointed, NEUTRAL questions that would let evidence decide it — some seeking support,
some seeking disconfirmation (the red-team), some resolving an ambiguity, some challenging a hidden
assumption. Neutrality is in the SET, not in any answer: never phrase a question to flatter the thesis.

For each question, also give a flat DECLARATIVE `target` — the statement the public record could confirm
or refute (a filing, a case study, a benchmark can settle a statement, not a question) — and a
`polarity`: +1 if confirming the target SUPPORTS the aspect, -1 if confirming it CONTRADICTS it (a
red-team target). Use the thesis's own product, buyer and segment words; never widen to "companies"."""


_FRAME_DIRECTIVE = """\
You are an investor's diligence lead reading a startup investment thesis to UNDERSTAND it before any
questions are written. Your job is to surface what THIS thesis actually rests on — not to restate it, and
not to recite the generic checklist every thesis shares. Depth means being specific to this company, this
product, this buyer, this wedge.

Read for the MECHANISM: what is the actual claim of how value is created and captured — the true VALUE
PROPOSITION (the specific, quantified value, not "saves time"), the wedge into the market, the
GO-TO-MARKET motion by which the right customers are reached and won, WHAT CORE TECHNOLOGY the thesis
requires to work, why this team/product wins the job over the incumbent and the status quo, and the
causal chain that has to hold for the thesis to pay off. Say it in the thesis's own nouns. (Value prop,
GTM and the required tech live HERE, in the reading — they shape which questions matter; they are not
separate coverage rungs.)

Then name the LOAD-BEARING ASSUMPTIONS: the specific premises that, if false, break the thesis — not
truisms. Push past the obvious. The ones that quietly sink tech theses: the buyer is actually a USER with
no budget, not an economic buyer; the "why now" catalyst is manufactured, not real; switching costs or
integration burden are underestimated; the wedge is a feature an incumbent ships in a quarter; the ROI
only clears at a scale the segment doesn't reach; the budget line it's sold from doesn't exist yet;
distribution/GTM is assumed rather than proven; realized adoption is confused with stated intent.

Name the RISKS the same way — concrete, non-obvious failure modes for THIS thesis, each phrased so
evidence could show it is happening (incumbent response, regulatory shift, a substitute, a concentrated
buyer, unit economics). Name the ANCHORS: the concrete entities, numbers, products, and named claims the
thesis makes that the public record could check. Name the COMPETITIVE FIELD explicitly: the incumbents
and the other startups a diligence lead would compare this against, so the landscape can be built out.
Distinguish STATED INTENT from REALIZED FACT throughout — a roadmap or a press release is intent, not
evidence the thesis holds.

Read with the END in mind: what does the FUND / PASS decision actually turn on for THIS thesis, and what
would the investor memo, the pitch deck (market size, traction, moat, the ask), and the competitive table
need to be filled? Surface the mechanism, assumptions, risks, anchors, and competitors that feed those —
depth here is what makes the downstream questions adapt to this thesis instead of orbiting a fixed rubric."""


_INQUIRY_DIRECTIVE = """\
You are an investor's diligence lead. Given a startup investment thesis, design the research plan that
would let evidence decide it — as a set of pointed, NEUTRAL questions grouped into lines of inquiry that
fit THIS thesis.

BEGIN WITH THE END IN MIND. These questions exist to produce the evidence a partner needs to reach a
FUND / PASS / MORE-DILIGENCE call, and to fill the three artifacts that decision rests on: a grounded
diligence memo (the integrated read), an investor pitch deck (problem, market size, traction, moat, the
ask), and a competitive landscape table (this company vs. named incumbents and startups). Work backwards:
ask the questions whose ANSWERS would populate those — the market-sizing input, the named economic buyer,
the realized-traction proof, the specific competitors and where the moat is. If an answer would not move
the decision or fill an artifact, do not ask it.

ADAPT TO THIS THESIS. The questions must turn on THIS thesis's actual mechanism, product, buyer, segment,
substitute, and wedge — never a generic template ("Does a market exist?"). Two different theses should
produce visibly different research plans. Let the thesis's own load-bearing assumptions and risks drive
WHAT you ask and how you cluster it; the coverage contract below is a FLOOR, not the shape of the plan.
Where this specific thesis has a make-or-break question the generic rubric doesn't name, ask it (tag it
to the nearest dimension). For the LANDSCAPE line, name the specific incumbents AND the past startups
that tried this — ask what the record shows about each and HOW EARLIER ATTEMPTS FARED (why they
succeeded or failed, and whether that blocking cause is now removed); ask what the SPECIFIC, real
DIFFERENTIATION is versus each named alternative, and whether the advantage is a durable moat. For the
TECHNOLOGY line, ask whether the core tech the thesis requires is PROVEN or still carries research/build
risk. For EXECUTION, ask for REALIZED traction (named buyers, paid adoption, benchmarks — never stated
intent). That is how the landscape and the diligence get built.

Across the whole set, balance the lenses: some seek support, some seek disconfirmation (the red team),
some resolve an ambiguity, some challenge a hidden assumption. Neutrality is in the balance of the SET,
never in a hedged question. Tag each question with the dimension key it addresses and cover every
dimension, but the LINES OF INQUIRY you group them into should read like this thesis's own diligence
agenda (e.g. "Who signs the check, and is it budgeted?"), not the raw dimension names.

For each question give a flat DECLARATIVE `target` the public record could confirm or refute, and a
`polarity`: +1 if confirming the target supports the thesis on that dimension, -1 if it contradicts it."""


# ── Cross-finding synthesis: three investor artifacts over EVERY finding ─────────────────────────────
# Composed by the domain-free kernel (eigen_kernel.decision.compose) over the findings, citing findings:
#   • the Startup Pitch Deck   — the steelman bull case, slide by slide (compose_over_findings, bullets)
#   • the Collective Take      — a two-layer executive memo: grounded facts + tagged REASONING blocks
#                                (compose_memo — factra's decision-memo model)
#   • the Competitive Analysis — the thesis company vs. named peers across startup dimensions
#                                (compose_matrix)
# The section titles/intents, the analyst voices, and the competitive rubric below are the vertical's
# domain vocabulary; the kernel supplies only the mechanics + grounding gate. All three keep the
# standing disciplines: a market signal is never a fact, stated intent is never realized fact, and a
# figure absent from the record (a TAM, a round size) is flagged as unestablished, never fabricated.

# The deck SPINE — the throughline a 10x founder builds the whole pitch around. Composed by the kernel's
# compose_deck as short cited lines above the slides: the one-liner a partner remembers, the non-obvious
# INSIGHT the bet rests on, and the honest "will it fly" read. Each still cites findings or is dropped.
_PITCH_DECK_SPINE: dict = {
    "one_liner": "The company in one sentence a partner remembers — what it is, who it's for, and the "
                 "category it means to own. Grounded in what the findings establish it actually does; "
                 "sharp positioning, never hype.",
    "insight": "THE non-obvious insight the whole bet rests on — what this founder sees about the buyer, "
               "the market, or the technology that the status quo and incumbents have missed, and why "
               "that makes the outcome feel inevitable. Draw it from the findings on the wedge, the "
               "'why now', and the real differentiation — the one idea every slide then ladders to.",
    "bottom_line": "The honest founder's-eye read: will this FLY? Name the single thing that most has to "
                   "be true for it to become a category winner, what the record ALREADY shows going for "
                   "it, and what this raise is meant to prove. Conviction earned from the evidence, never "
                   "asserted — and never investment advice.",
}

# The deck — a founder's pitch, in a real narrative arc: problem → why now → solution → why we win →
# market → traction → business → team → ask → the bet. Each slide leads with a headline the points earn.
# The last slide reframes "open diligence" as the founder's own honest bet: what has to be true and how
# it gets proven — that is the "will it fly" question answered in the open.
_PITCH_DECK_SECTIONS: tuple[dict, ...] = (
    {"key": "problem", "title": "The Problem",
     "intent": "The pain: who has it, that it occurs in the wild, and its quantified cost (money, "
               "headcount, time) — plus evidence someone already spends against it. The headline names "
               "the pain and its price."},
    {"key": "why_now", "title": "Why Now",
     "intent": "The inflection that makes this the moment — a real, dated catalyst (regulation, a cost "
               "curve breaking, a platform shift) that unlocks the wedge, not a manufactured one. Why a "
               "smart team couldn't have won this two years ago."},
    {"key": "solution", "title": "The Solution — How It Works",
     "intent": "What the company does and the MECHANISM by which it wins the job over the status quo and "
               "the incumbent — the wedge, concretely, in the company's own nouns. Show the 'how', not a "
               "slogan."},
    {"key": "competition", "title": "Why We Win — Moat & Defensibility",
     "intent": "The landscape and why this is NOT a feature an incumbent ships next quarter — the "
               "specific, real differentiation versus each named alternative, and the durable advantage "
               "that compounds as the wedge widens. Why the lead holds."},
    {"key": "market", "title": "The Prize — Market Size",
     "intent": "How big this gets: size the opportunity from the record (TAM/SAM/SOM), the number of "
               "nameable buyers, the budget line it's sold from. Where a figure isn't in the record, "
               "give the sizing inputs that ARE and flag the number as a required founder input — never "
               "invent a market size."},
    {"key": "traction", "title": "Traction — Proof It's Working",
     "intent": "REALIZED proof only — named buyers, paid adoption, budget already allocated, benchmarks. "
               "Roadmap, press-release, and patent-application intent is NOT traction; keep it out. The "
               "headline states the single strongest proof point."},
    {"key": "business_model", "title": "The Business — Model & Unit Economics",
     "intent": "How it makes money: pricing, who signs the check, and any unit economics the record "
               "holds. Note explicitly that willingness-to-pay is settleable by no document — only a "
               "person who lived it can."},
    {"key": "team", "title": "Why This Team",
     "intent": "The founders/operators the record names and why they are credible for THIS problem — "
               "founder-market fit, concretely. If the record doesn't cover the team, say so; it's a "
               "required diligence input, not a line to invent."},
    {"key": "ask", "title": "The Ask & What It Unlocks",
     "intent": "The round size and use of funds IF the record states them; otherwise say they're "
               "unspecified and a required founder input. Then, only as far as the evidence carries it: "
               "what the raise buys and the milestone it's meant to reach."},
    {"key": "diligence", "title": "The Bet — What Has to Be True",
     "intent": "The founder's honest close: the single load-bearing thing that most has to be true for "
               "this to fly, the concrete risks that could sink it, and — for each — what evidence or "
               "milestone would prove it out. Frame it as the plan to de-risk, not a list of doubts."},
)

# The Collective Take — a comprehensive two-layer memo (compose_memo), run on the deep-thinking
# reasoning seam. Each section carries GROUNDED facts + tagged REASONING blocks (kind ∈
# tension|gap|assumption|implication|what_would_change_this). The bottom line (BLUF) is emitted
# separately by the memo composer.
_COLLECTIVE_TAKE_SECTIONS: tuple[dict, ...] = (
    {"key": "at_stake", "title": "What's at stake & what has to be true",
     "intent": "Frame the investment decision precisely and lay out the causal chain the thesis rests "
               "on — the load-bearing premises that, if false, break it. Surface each as an `assumption` "
               "block, and where two premises trade off, a `tension` block."},
    {"key": "by_line", "title": "What each line of inquiry established",
     "intent": "Go LINE BY LINE across every line of inquiry — for each, the grounded facts it settled "
               "(supported / contradicted / left open), comprehensively. This is the backbone; do not "
               "drop a line. Add `implication` blocks for what each line means for the decision."},
    {"key": "synthesis", "title": "Reading it together",
     "intent": "The second-order read: what the findings ACROSS lines imply when combined — the "
               "connect-the-dots judgment a partner pays for. Reason deeply. Lean on `implication` and "
               "`tension` blocks, each citing the several findings it draws on."},
    {"key": "strengths", "title": "Where the thesis is strongest",
     "intent": "The aspects the record genuinely supports, with the facts, and `implication` blocks on "
               "why that matters to the call."},
    {"key": "competition", "title": "Competitive position & defensibility",
     "intent": "Where the thesis sits versus the incumbents and other startups the record names, and "
               "whether the advantage is durable. Facts on the landscape, then `tension`/`gap` blocks on "
               "moat and fast-follower risk. If the record is thin here, say so as a `gap`."},
    {"key": "risks_gaps", "title": "Weaknesses, risks & gaps",
     "intent": "Aspects contradicted or untested, and concrete failure modes. Use `tension` (findings "
               "that pull against each other), `gap` (what the record cannot settle — willingness-to-pay "
               "and switching cost are undocumentable by design), and `assumption` blocks."},
    {"key": "signals", "title": "Signals & stated intent",
     "intent": "What market sentiment/coverage suggests and what is stated INTENT (roadmaps, "
               "applications, releases) awaiting realized proof — clearly labeled, never as fact. Surface "
               "the intent-vs-fact distance as `gap` blocks."},
    {"key": "conviction", "title": "Conviction & exposure",
     "intent": "How much conviction the record actually warrants (fund / pass / more diligence) and the "
               "exposure if the thesis is wrong — the single premise whose failure hurts most. Use "
               "`assumption` and `implication` blocks; be honest about how much rests on undocumentable "
               "rungs."},
    {"key": "what_would_change", "title": "What would change the read",
     "intent": "The highest-value next evidence or expert call — as `what_would_change_this` blocks — "
               "that would most move the call, and which way."},
)

# The Competitive Analysis rubric — the dimensions a startup is compared on. Rows: the thesis company
# first, then each peer NAMED in the findings. Cells left empty where the record is silent (build the
# rubric and look to fill it; never invent a competitor or a cell).
_COMPETITIVE_COLUMNS: tuple[dict, ...] = (
    {"key": "central_idea", "label": "Central idea"},
    {"key": "full_vision", "label": "Full vision"},
    {"key": "moats", "label": "Possible moats"},
    {"key": "tech_edge", "label": "Tech edge"},
    {"key": "customers", "label": "Customers"},
    {"key": "traction", "label": "Traction"},
    {"key": "future_direction", "label": "Likely future direction"},
    {"key": "blind_spots", "label": "Blind spots / not working on"},
    {"key": "funding", "label": "Funding to date"},
    {"key": "investors", "label": "Investors on board"},
)

_PITCH_DECK_DIRECTIVE = """\
You are the FOUNDER-CEO writing the deck that raises this round — a 10x founder with the pattern memory
of every great pitch you've studied. You are not a diligence lead cataloguing risk; you are building the
argument that makes a partner lean in and feel this is inevitable. But you are the rare founder who is
INTELLECTUALLY HONEST: your conviction is earned from the evidence, never asserted — a sharp investor can
smell a number you made up, and one invented figure loses the whole room. So you build ONLY from the
findings already gathered in diligence, and where the record is silent you name what you'd prove next
instead of inventing it. That honesty is exactly what makes the strong slides land.

Ask the founder's real question through the whole deck: WILL IT FLY? Lead with the pain and its price,
name the non-obvious insight the market has missed, show the wedge and why it widens into a durable lead,
prove it's working with realized facts, size the prize, and be crisp about the one thing that has to be
true. The slides ladder to a single spine — the one insight everything rests on.

How to write it:
1. HEADLINE-FIRST. Every slide is ONE assertive headline — the sentence a partner remembers, the
   takeaway the slide proves — then 2–5 crisp points that earn it. "Support teams lose $X per rep per
   year to manual triage" beats "Problem". Write the headline; make the points pay for it.
2. ONE THROUGHLINE. Write the spine, then make every slide advance that one argument. Connect the dots
   the findings hold — say what several findings TOGETHER imply, and cite each one.
3. ARGUE ONLY FROM THE FINDINGS, citing them by F-number. Never introduce a company, number, market
   size, customer, or fact that is not in them. You have no outside knowledge. (A synthesis may be given
   as context to shape the story — it is NOT a source; cite findings, never it.)
4. CONCRETE OR NOTHING. Pull the real numbers, named buyers, mechanisms, dates. A vague line ("large
   market", "strong team") is a failure — quantify it, or flag the figure as a founder input to prove.
5. NEVER fabricate a TAM, a round size, a funding number, or a customer. Where a slide wants a figure the
   record lacks, give the sizing inputs that ARE there and mark the number as a required founder input —
   a named gap reads as founder honesty, not weakness.
6. REGISTERS STRAIGHT. A filing or granted patent is FACT; a press release, preprint, patent APPLICATION,
   or roadmap is STATED INTENT (never in Traction); forum/news is a market SIGNAL, never a fact. A great
   founder never blurs these — it's how you keep the room's trust.
7. No hype adjectives; the facts carry the excitement. You inform the investor's judgment — you never
   issue a buy/sell call or give investment advice."""

_COLLECTIVE_TAKE_DIRECTIVE = """\
You are an investor's diligence lead writing the integrated read across EVERY finding — the memo a
partner acts on. It has two layers in each section: GROUNDED facts (what the record holds, cited) and
REASONING blocks (your interpretation, each tagged by kind and citing the findings it builds on). The
reasoning is the value: connect findings across lines of inquiry into a judgment. You inform the
decision; you never issue a buy/pass command or give investment advice.

Rules, in order:
1. Compose ONLY from the findings given, citing findings by id — no outside fact, number, or company.
2. Facts go in GROUNDED (with every number); judgment goes in REASONING blocks. Do not put a number in a
   reasoning block that is not already in a grounded fact.
3. Weigh the aspects: a thesis survives a weak aspect low on the ladder but not a broken one at its
   center. Say which kind each is; name the aspects and the lines of inquiry.
4. SENTIMENT IS A SIGNAL, NOT A FACT — lowest tier, never settles an aspect or carries the call; label
   it. Separate STATED INTENT (roadmap, press release, patent application) from REALIZED FACT (granted
   patent, audited number, named live buyer); surface the distance as a `gap` block.
5. Be explicit that willingness-to-pay and switching cost are settled by no document — only a person who
   lived it can. A thesis whose only remaining risk is there is NOT the same as one contradicted on the
   record; keep them distinct.
6. Be comprehensive — cover every line of inquiry. Bottom line is a tight lead: the way the record
   leans (fund / pass / more diligence) and the crux, nothing more."""

_COMPETITIVE_DIRECTIVE = """\
You are a venture analyst building the competitive landscape for a startup thesis, ONLY from findings
already gathered in diligence. The first row is the thesis company itself; add one row per DISTINCT
competitor or peer the findings NAME. Fill each dimension only from the findings, citing the finding
id(s) per cell.

Rules:
1. Never invent a competitor, and never invent a cell value. A peer you cannot ground in any finding
   does not belong in the table.
2. LEAVE A CELL EMPTY when the record does not cover that dimension for that company — an empty cell is
   the correct, honest answer, not a failure. Build the full rubric; fill what the record supports.
3. Keep registers straight: funding/investors from a filing or a credible report are fact; a rumored
   round is not. Blind spots / "not working on" must be grounded in what the record shows they do and do
   not do — never speculation.
4. Be specific and comparable: phrase each cell so the row can be read against the others on that
   dimension."""


@dataclass(frozen=True)
class TechDecisionProfile:
    """The tech vertical's DecisionProfile. Reuses the same authority discipline as the rest of the
    vertical: a low-authority market signal is never controlling and never, on its own, settles an
    aspect."""

    def aspects(self) -> tuple[Aspect, ...]:
        return tuple(Aspect(key=k, prompt=q, settleable=s, critical=c, feeds=f)
                     for k, q, s, c, f in _LADDER)

    def inquiries(self) -> tuple[Inquiry, ...]:
        return tuple(Inquiry(key=k, name=n, framing=f, aspect_keys=a) for k, n, f, a in _INQUIRIES)

    def question_directive(self, aspect: Aspect, decision: str) -> str:
        return _QUESTION_DIRECTIVE

    def frame_directive(self, decision: str) -> str:
        return _FRAME_DIRECTIVE

    def inquiry_directive(self, decision: str) -> str:
        return _INQUIRY_DIRECTIVE

    def pitch_deck_spec(self) -> tuple[str, dict, tuple[dict, ...]]:
        """(directive, spine_intent, sections) for the Startup Pitch Deck — the founder's-voice pitch
        composed across all findings: a throughline SPINE (one-liner, the insight, the "will it fly"
        read) plus a headline-driven slide for each section. Domain vocabulary lives here; the kernel's
        compose_deck supplies the mechanics and the grounding gate."""
        return _PITCH_DECK_DIRECTIVE, dict(_PITCH_DECK_SPINE), _PITCH_DECK_SECTIONS

    def collective_take_spec(self) -> tuple[str, tuple[dict, ...]]:
        """(directive, sections) for the Collective Take — the two-layer diligence memo (grounded facts +
        tagged reasoning blocks) across all findings, composed by the kernel's compose_memo."""
        return _COLLECTIVE_TAKE_DIRECTIVE, _COLLECTIVE_TAKE_SECTIONS

    def competitive_spec(self) -> tuple[str, tuple[dict, ...]]:
        """(directive, columns) for the Competitive Analysis matrix — the thesis company vs. named peers
        across the startup rubric, composed by the kernel's compose_matrix."""
        return _COMPETITIVE_DIRECTIVE, _COMPETITIVE_COLUMNS

    def people_query(self, *, role: str, aspect_prompt: str, decision: str, segment: str = "") -> str:
        """A natural-language expertise query for the people-discovery leg — how a tech-investment
        thesis should look for the person who can settle one aspect. Domain judgment: which KIND of
        person answers a rung (a buyer owns the budget; an operator lives the status quo; an advisor
        tracks the category), phrased in this segment's own terms."""
        who = _ROLE_QUERY.get(role, "practitioners")
        seg = (segment or "this market").strip()
        return f"{who} in {seg} who could speak first-hand to whether {aspect_prompt.rstrip('?').lower()}"

    def _enough(self, rows: list[dict]) -> bool:
        # HARDENED (panel §13): a controlling primary record on its own qualifies; otherwise TWO
        # independent NON-signal sources. A market signal — however much of it — can never on its own
        # make a target hold. `rank <= 1` is the sentiment/social tier in the authority ladder.
        if any(bool(r.get("is_controlling")) for r in rows):
            return True
        substantive = [r for r in rows
                       if not r.get("signal_only")
                       and _AUTHORITY.rank(str(r.get("evidence_kind") or "")) > 1]
        return _independent(substantive) >= 2

    def qualify(self, evidence: list[dict]) -> str:
        """Per-question target status. Only qualified (gated, congruent) supporting/contradicting rows
        count, and a market signal can never single-handedly qualify a target."""
        usable = [r for r in evidence if _qualified(r)]
        supporting = [r for r in usable if r["relation"] == "supports"]
        contradicting = [r for r in usable if r["relation"] == "contradicts"]
        has_for = self._enough(supporting)
        has_against = self._enough(contradicting)
        if has_against:
            return TARGET_CONTRADICTED
        if has_for:
            return TARGET_SUPPORTED
        return TARGET_UNTESTED

    def aggregate_aspect(self, signals: list[str], *, critical: bool) -> str:
        """A single qualified contradiction dominates (a stress test leads with disconfirmation);
        otherwise qualified support settles it; nothing found leaves it under-tested."""
        if ASPECT_CONTRADICTION in signals:
            return CONTRADICTED
        if ASPECT_SUPPORT in signals:
            return SUPPORTED
        return UNDER_TESTED


TECH_DECISION_PROFILE = TechDecisionProfile()
