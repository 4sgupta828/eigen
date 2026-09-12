"""From per-question findings to an aspect verdict — the kernel resolves POLARITY (generic), the
profile decides the THRESHOLDS (domain judgment).

The split matters: turning "the record confirms the target" into "this supports/contradicts the aspect"
is pure logic (the question's polarity), so the kernel does it. Deciding how much support is "enough",
or that a low-authority signal can never settle it, is domain judgment, so the profile does it. The
Socratic layer is a VIEW over the profile's judgment, never a second decision engine.
"""
from __future__ import annotations

from .types import (
    QuestionStatus,
    TARGET_SUPPORTED, TARGET_CONTRADICTED,
    ASPECT_SUPPORT, ASPECT_CONTRADICTION, ASPECT_NONE,
)


def resolve_signal(status: QuestionStatus) -> str:
    """Apply the question's polarity to what the record said about its target. Confirming a +1 target
    supports the aspect; confirming a -1 target (a red-team target) contradicts it. Evidence that the
    target is FALSE flips the sign. Nothing found → no signal."""
    pol = status.question.polarity
    if status.target_status == TARGET_SUPPORTED:
        return ASPECT_SUPPORT if pol >= 0 else ASPECT_CONTRADICTION
    if status.target_status == TARGET_CONTRADICTED:
        return ASPECT_CONTRADICTION if pol >= 0 else ASPECT_SUPPORT
    return ASPECT_NONE


def aggregate_aspect(profile, statuses: list[QuestionStatus], *, critical: bool) -> str:
    """Resolve every question to an aspect signal (kernel/generic), then hand the signal set to the
    profile for the domain-judgment verdict. The kernel supplies no thresholds of its own."""
    signals = [resolve_signal(s) for s in statuses]
    return profile.aggregate_aspect(signals, critical=critical)
