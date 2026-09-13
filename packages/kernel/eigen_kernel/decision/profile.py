"""The adaptation seam. A vertical implements `DecisionProfile` and exposes it on its manifest; the
kernel engine reads it. This is where a decision-testing surface becomes native to a domain — its
coverage structure, its prompts, its authority, its judgment — without the kernel learning any domain
noun.

It is a structural Protocol, not a base class: a vertical supplies any object with these members. The
kernel calls them; it never inspects domain internals.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import Aspect, Inquiry, Question, QuestionStatus


@runtime_checkable
class DecisionProfile(Protocol):
    # ---- coverage structure (domain-owned, not the model's to edit) ----
    def aspects(self) -> tuple[Aspect, ...]:
        """The fixed set of coverage units the decision rests on."""

    def inquiries(self) -> tuple[Inquiry, ...]:
        """A partition of the aspects into inquiry cards. Every aspect in exactly one inquiry."""

    # ---- prompts the model is steered by (domain vocabulary as DATA, never in kernel code) ----
    # OPTIONAL extension methods a profile MAY also expose (accessed via hasattr, kept off the required
    # Protocol surface so a minimal profile still satisfies it, like `inquiry_directive`):
    #   frame_directive(decision) -> str   guidance for the UNDERSTANDING step (frame.py): what a
    #       load-bearing assumption, a real risk, and a meaningful anchor look like in THIS domain, so
    #       the frame is deep and specific rather than a generic restatement.
    #   inquiry_directive(decision) -> str system guidance for decision-level question generation.
    def question_directive(self, aspect: Aspect, decision: str) -> str:
        """System guidance for generating a balanced, typed Socratic question set for one aspect —
        including how to phrase each question's declarative `target` and its polarity, in this
        domain's language."""

    # ---- judgment ----
    def qualify(self, evidence: list[dict]) -> str:
        """Given the qualified evidence for one question's `target`, return its target status
        (types.TARGET_*). This is where authority/independence thresholds (e.g. a low-authority signal
        is never controlling) are enforced — domain judgment, not kernel mechanics."""

    def aggregate_aspect(self, signals: list[str], *, critical: bool) -> str:
        """Given the per-question aspect signals (types.ASPECT_*) for one aspect, return its verdict
        (types.VERDICTS). The thresholds — how much support, how a single contradiction weighs — are
        domain judgment."""
