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

# The coverage ladder — the aspects a technology-investment thesis rests on. Fixed; not the model's to
# edit (a model that just read an encouraging sentence will call anything settleable). "corpus" = the
# public record can settle it; "call_only" = only a person who has lived it can.
_LADDER: tuple[tuple[str, str, str, bool], ...] = (
    ("problem_exists", "Does the problem actually occur in the wild?", "corpus", True),
    ("status_quo_costs", "Does the status quo cost real money, headcount or time?", "corpus", True),
    ("already_spending", "Does anyone already allocate budget or people to it?", "corpus", True),
    ("function_owns", "Does a named function own the problem?", "corpus", False),
    ("budget_category", "Does a budget category already exist to buy this from?", "partly", False),
    ("buyer_nameable", "Can an economic buyer be named — not a user?", "partly", True),
    ("switching_feasible", "Is the switching cost surmountable?", "call_only", True),
    ("catalyst", "Is something forcing a revisit now?", "partly", False),
    ("willingness_to_pay", "Does willingness to pay exceed the cost to serve?", "call_only", True),
    ("enough_buyers", "Do enough such buyers exist?", "corpus", True),
)

# The lines of inquiry — a fixed partition of the ladder into cards (every aspect in exactly one).
_INQUIRIES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("problem", "Is the problem real, and does it cost?", "the pain and its price",
     ("problem_exists", "status_quo_costs", "already_spending")),
    ("buyer", "Who owns the budget to buy this?", "the economic buyer and the money",
     ("function_owns", "budget_category", "buyer_nameable", "willingness_to_pay")),
    ("timing", "Can they switch, and why now?", "switching cost and catalyst",
     ("switching_feasible", "catalyst")),
    ("market", "Are there enough buyers?", "the size of the segment",
     ("enough_buyers",)),
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

Read for the MECHANISM: what is the actual claim of how value is created and captured — the wedge into the
market, why this team/product wins the job over the incumbent and the status quo, and the causal chain
that has to hold for the thesis to pay off. Say it in the thesis's own nouns.

Then name the LOAD-BEARING ASSUMPTIONS: the specific premises that, if false, break the thesis — not
truisms. Push past the obvious. The ones that quietly sink tech theses: the buyer is actually a USER with
no budget, not an economic buyer; the "why now" catalyst is manufactured, not real; switching costs or
integration burden are underestimated; the wedge is a feature an incumbent ships in a quarter; the ROI
only clears at a scale the segment doesn't reach; the budget line it's sold from doesn't exist yet;
distribution/GTM is assumed rather than proven; realized adoption is confused with stated intent.

Name the RISKS the same way — concrete, non-obvious failure modes for THIS thesis, each phrased so
evidence could show it is happening (incumbent response, regulatory shift, a substitute, a concentrated
buyer, unit economics). Name the ANCHORS: the concrete entities, numbers, products, and named claims the
thesis makes that the public record could check. Distinguish STATED INTENT from REALIZED FACT throughout —
a roadmap or a press release is intent, not evidence the thesis holds."""


_INQUIRY_DIRECTIVE = """\
You are an investor's diligence lead. Given a startup investment thesis, design the research plan that
would let evidence decide it — as a set of pointed, NEUTRAL questions grouped into lines of inquiry that
fit THIS thesis.

Every question must be specific to this thesis — its actual product, buyer, segment, and substitute —
never a generic template ("Does a market exist?"). Across the whole set, balance the lenses: some seek
support, some seek disconfirmation (the red team), some resolve an ambiguity, some challenge a hidden
assumption. Neutrality is in the balance of the SET, never in a hedged question.

You are given a COVERAGE CONTRACT of dimensions every thesis rests on; tag each question with the
dimension key it addresses, and make sure every dimension is covered. But the LINES OF INQUIRY you group
them into should read like this thesis's own diligence agenda (e.g. "Who signs the check, and is it
budgeted?"), not the raw dimension names.

For each question give a flat DECLARATIVE `target` the public record could confirm or refute, and a
`polarity`: +1 if confirming the target supports the thesis on that dimension, -1 if it contradicts it."""


@dataclass(frozen=True)
class TechDecisionProfile:
    """The tech vertical's DecisionProfile. Reuses the same authority discipline as the rest of the
    vertical: a low-authority market signal is never controlling and never, on its own, settles an
    aspect."""

    def aspects(self) -> tuple[Aspect, ...]:
        return tuple(Aspect(key=k, prompt=q, settleable=s, critical=c) for k, q, s, c in _LADDER)

    def inquiries(self) -> tuple[Inquiry, ...]:
        return tuple(Inquiry(key=k, name=n, framing=f, aspect_keys=a) for k, n, f, a in _INQUIRIES)

    def question_directive(self, aspect: Aspect, decision: str) -> str:
        return _QUESTION_DIRECTIVE

    def frame_directive(self, decision: str) -> str:
        return _FRAME_DIRECTIVE

    def inquiry_directive(self, decision: str) -> str:
        return _INQUIRY_DIRECTIVE

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
