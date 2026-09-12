"""Running an inquiry — gather evidence per question, qualify it, aggregate to verdicts. Domain-free.

The kernel does NOT know how to search a corpus for a technology claim, or what a filing is. It takes an
injected `gather(question) -> evidence` — the app wraps its own retrieval + gates behind that seam (and
may cache per aspect so a support/contradiction pair shares one retrieval). The kernel only orchestrates:
each question's target status comes from the profile's `qualify`, the aspect verdict from the profile's
`aggregate_aspect` over the polarity-resolved signals. An optional injected `synthesize(question,
evidence) -> answer` produces the grounded, cited prose; with none, the status carries no prose and the
verdict still stands (evidence, not narrative, decides).
"""
from __future__ import annotations

from typing import Awaitable, Callable

from .aggregate import aggregate_aspect
from .types import Aspect, Question, QuestionStatus, UNSETTLEABLE

# gather: given a question, return the gated evidence rows for its declarative target.
Gather = Callable[[Question], Awaitable[list[dict]]]
# synthesize (optional): given a question and its evidence, return grounded cited prose.
Synthesize = Callable[[Question, list[dict]], Awaitable[str]]


def _ids(evidence: list[dict]) -> tuple[str, ...]:
    return tuple(str(e.get("id") or "") for e in evidence if e.get("id"))


async def run_question(gather: Gather, profile, question: Question,
                       synthesize: Synthesize | None = None) -> QuestionStatus:
    """One question: gather → qualify → (optionally) synthesize. Never raises on a gather/synth failure —
    an unreachable question is `target_untested`, not a crash."""
    try:
        evidence = await gather(question) or []
    except Exception:      # noqa: BLE001 — a failed gather leaves the question untested, not the run dead
        evidence = []
    status = QuestionStatus(question=question, target_status=profile.qualify(evidence),
                            evidence_ids=_ids(evidence))
    if synthesize is not None:
        try:
            status.answer = await synthesize(question, evidence) or ""
        except Exception:      # noqa: BLE001 — the verdict does not depend on the prose
            status.answer = ""
    return status


async def run_aspect(gather: Gather, profile, aspect: Aspect, questions: list[Question],
                     synthesize: Synthesize | None = None) -> tuple[str, list[QuestionStatus]]:
    """Run every question of one aspect and derive its verdict. An aspect no record can settle
    (profile marks it) is reported unsettleable rather than under-tested — a structural gap, not a
    coverage gap."""
    statuses = [await run_question(gather, profile, q, synthesize) for q in questions]
    if getattr(aspect, "settleable", "") == "call_only" and not any(
            s.target_status != "target_untested" for s in statuses):
        return UNSETTLEABLE, statuses
    return aggregate_aspect(profile, statuses, critical=aspect.critical), statuses


async def run_inquiry(gather: Gather, profile, aspect_keys: tuple[str, ...],
                      questions_by_aspect: dict[str, list[Question]],
                      synthesize: Synthesize | None = None) -> dict[str, dict]:
    """Run every aspect in one inquiry. -> {aspect_key: {verdict, statuses}}. This is the unit the user
    kicks off; the engine runs its aspects, the app persists the result."""
    out: dict[str, dict] = {}
    by_key = {a.key: a for a in profile.aspects()}
    for key in aspect_keys:
        aspect = by_key.get(key)
        if aspect is None:
            continue
        verdict, statuses = await run_aspect(gather, profile, aspect,
                                             questions_by_aspect.get(key, []), synthesize)
        out[key] = {"verdict": verdict, "statuses": statuses}
    return out
