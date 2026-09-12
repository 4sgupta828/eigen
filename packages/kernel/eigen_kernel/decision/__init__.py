"""Decision-testing engine — domain-free mechanics for informing a decision against evidence.

This is the kernel's reusable engine for the pattern: take a DECISION (a proposition someone must
act on), decompose it into ASPECTS (a coverage structure), group them into INQUIRIES, interrogate each
aspect 360° with TYPED SOCRATIC QUESTIONS, answer each question from evidence, and aggregate what was
found into a per-aspect VERDICT and a recommendation.

The kernel owns the MECHANICS and the generic reasoning lenses. It names NO domain noun. Everything
domain-specific — what the aspects are, how they group, how questions are phrased, what evidence is
authoritative, what counts as "enough" — is supplied by a `DecisionProfile` from the active vertical's
manifest. The same engine informs a technology decision here, a different one elsewhere, by swapping the
profile; the kernel is untouched. (Standing directive: kernel = mechanics, vertical = vocabulary/judgment.)
"""
from __future__ import annotations

from .types import (
    QuestionKind, Question, QuestionStatus, Aspect, Inquiry,
    SUPPORTED, CONTRADICTED, UNDER_TESTED, OPEN, UNSETTLEABLE,
    TARGET_SUPPORTED, TARGET_CONTRADICTED, TARGET_UNTESTED,
    ASPECT_SUPPORT, ASPECT_CONTRADICTION, ASPECT_NONE,
)
from .profile import DecisionProfile
from .questions import generate_questions, required_kinds_covered
from .aggregate import resolve_signal, aggregate_aspect

__all__ = [
    "QuestionKind", "Question", "QuestionStatus", "Aspect", "Inquiry",
    "SUPPORTED", "CONTRADICTED", "UNDER_TESTED", "OPEN", "UNSETTLEABLE",
    "TARGET_SUPPORTED", "TARGET_CONTRADICTED", "TARGET_UNTESTED",
    "ASPECT_SUPPORT", "ASPECT_CONTRADICTION", "ASPECT_NONE",
    "DecisionProfile", "generate_questions", "required_kinds_covered",
    "resolve_signal", "aggregate_aspect",
]
