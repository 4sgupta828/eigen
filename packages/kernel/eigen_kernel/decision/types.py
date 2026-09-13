"""The vocabulary of the decision-testing engine — generic, domain-free.

A vertical maps its own nouns onto these (its coverage units become Aspects, its proposition becomes
the Decision). The kernel never says what domain it is in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class QuestionKind(str, Enum):
    """The generic reasoning lenses. Neutrality of an inquiry comes from asking a BALANCED set of these,
    not from hedging any one answer. Each lens is domain-independent — it applies to any decision."""
    SEEK_SUPPORT = "seek_support"              # is there evidence the aspect holds?
    SEEK_CONTRADICTION = "seek_contradiction"  # is there evidence against it? (the red-team lens)
    RESOLVE_AMBIGUITY = "resolve_ambiguity"    # where it could go two ways, which does the record show?
    CHALLENGE_ASSUMPTION = "challenge_assumption"  # name a hidden premise and test it


# The minimum lenses every aspect must be interrogated through for the inquiry to be balanced. The
# other two are used where the aspect warrants them; code (not the model) enforces this coverage.
REQUIRED_KINDS: tuple[QuestionKind, ...] = (QuestionKind.SEEK_SUPPORT, QuestionKind.SEEK_CONTRADICTION)


@dataclass(frozen=True)
class Question:
    """A typed Socratic question. `text` is what the reader sees; `target` is the DECLARATIVE
    proposition the evidence pipeline actually tests (a document can confirm or refute a statement, not
    a question). `polarity` says whether confirming `target` SUPPORTS the aspect (+1) or CONTRADICTS it
    (-1) — so verdict resolution never has to guess the meaning from the question kind."""
    kind: QuestionKind
    text: str                    # the question, in the reader's frame
    target: str                  # the declarative sub-claim the evidence run is anchored on
    polarity: int = 1            # +1: confirming target supports the aspect; -1: confirming contradicts it
    dimension: str = ""          # the coverage aspect (rubric key) this question addresses — ties a
    #                              thesis-native question back to the fixed coverage contract for verdicts


@dataclass
class QuestionStatus:
    """What the evidence run found for a question's `target`, before polarity is applied. The engine
    fills `target_status`; the aspect signal is derived (see aggregate.resolve_signal)."""
    question: Question
    target_status: str = "target_untested"   # TARGET_SUPPORTED | TARGET_CONTRADICTED | TARGET_UNTESTED
    evidence_ids: tuple[str, ...] = ()        # the qualified evidence this status rests on
    answer: str = ""                          # the grounded, cited prose (built by the vertical's synthesis)


@dataclass(frozen=True)
class Aspect:
    """A coverage unit the decision rests on. The vertical supplies the set; it is NOT the model's to
    edit. `settleable` names how it can be settled (the profile owns the vocabulary of values)."""
    key: str
    prompt: str                  # the canonical question this aspect asks of the decision
    settleable: str = ""         # profile-defined: e.g. from-the-record vs needs-a-person
    critical: bool = False


@dataclass(frozen=True)
class Inquiry:
    """A group of related aspects — one card. The grouping is a fixed partition of the aspect set (so
    coverage cannot regress), supplied by the profile."""
    key: str
    name: str
    framing: str
    aspect_keys: tuple[str, ...] = ()


# ---- verdicts (per aspect) ----------------------------------------------------------------------
SUPPORTED = "supported"
CONTRADICTED = "contradicted"
UNDER_TESTED = "under_tested"      # looked, found nothing qualified either way
OPEN = "open"                      # not yet explored
UNSETTLEABLE = "unsettleable"      # no record can settle it — needs a person
VERDICTS = (SUPPORTED, CONTRADICTED, UNDER_TESTED, OPEN, UNSETTLEABLE)

# ---- per-question target status ------------------------------------------------------------------
TARGET_SUPPORTED = "target_supported"
TARGET_CONTRADICTED = "target_contradicted"
TARGET_UNTESTED = "target_untested"

# ---- per-question aspect signal (after polarity) -------------------------------------------------
ASPECT_SUPPORT = "aspect_support"
ASPECT_CONTRADICTION = "aspect_contradiction"
ASPECT_NONE = "aspect_none"
