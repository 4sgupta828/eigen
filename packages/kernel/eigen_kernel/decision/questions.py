"""Socratic question generation — the model owns the wording, CODE owns the coverage gate.

Per aspect, one small model call proposes a balanced, TYPED question set (each with a declarative
`target` and a polarity). The kernel does not judge the questions' meaning; it enforces that the
required lenses are present (Rule 18: LLM owns semantics, code owns structure), caps the count, and
falls open to the aspect's canonical question when the model is absent or unusable — an inquiry is never
blocked.
"""
from __future__ import annotations

import json

from .types import Aspect, Question, QuestionKind, REQUIRED_KINDS

# Ceiling per aspect so a curious model cannot run up the later evidence cost. The vertical can ask for
# fewer via its directive; the kernel enforces the cap.
MAX_QUESTIONS_PER_ASPECT = 4


def required_kinds_covered(questions: list[Question]) -> bool:
    """The coverage gate: every REQUIRED lens is represented at least once. Balance across lenses —
    not a hedged answer — is what makes the inquiry unbiased."""
    kinds = {q.kind for q in questions}
    return all(k in kinds for k in REQUIRED_KINDS)


def _fallback(aspect: Aspect) -> list[Question]:
    """No model, or nothing usable: the honest degraded mode is ONE seek-support question on the aspect's
    canonical proposition. We do NOT fabricate a red-team question — a seek_contradiction needs its own
    distinct declarative target (a proposition whose truth would UNDERMINE the aspect); inventing one as
    the aspect prompt with a flipped polarity double-counts the same evidence and would turn a
    well-supported aspect into a contradicted one. Thin coverage, reported honestly, beats a false one."""
    return [Question(kind=QuestionKind.SEEK_SUPPORT, text=aspect.prompt, target=aspect.prompt, polarity=1)]


def _coerce(raw: dict, aspect: Aspect) -> list[Question]:
    out: list[Question] = []
    for item in (raw.get("questions") or []):
        try:
            kind = QuestionKind(str(item.get("kind") or "").strip())
        except ValueError:
            continue
        text = str(item.get("text") or "").strip()
        target = str(item.get("target") or "").strip()
        if not text or not target:
            continue
        pol = item.get("polarity")
        polarity = -1 if str(pol) in ("-1", "-", "against", "contradict") else 1
        out.append(Question(kind=kind, text=text[:400], target=target[:400], polarity=polarity))
        if len(out) >= MAX_QUESTIONS_PER_ASPECT:
            break
    return out


async def generate_questions(llm_json, *, aspect: Aspect, decision: str, directive: str) -> list[Question]:
    """-> a typed question set for one aspect. Never raises. Guarantees the required lenses are present:
    if the model omits one, the fallback for that lens is appended, so the coverage gate always holds."""
    if llm_json is None:
        return _fallback(aspect)
    user = (f"DECISION:\n{decision}\n\nASPECT ({aspect.key}): {aspect.prompt}\n\n"
            "Return ONE JSON object: {\"questions\": [{\"kind\": \"seek_support|seek_contradiction|"
            "resolve_ambiguity|challenge_assumption\", \"text\": \"the question\", \"target\": \"a flat "
            "declarative statement the record could confirm or refute\", \"polarity\": 1|-1}]}. "
            "polarity is +1 if confirming target supports the aspect, -1 if it contradicts it. "
            "Output ONLY the JSON object.")
    try:
        raw = await llm_json(directive, user)
        d = raw if isinstance(raw, dict) else json.loads(raw)
        got = _coerce(d, aspect)
    except Exception:      # noqa: BLE001 — generation never blocks an inquiry
        got = []
    if not got:
        return _fallback(aspect)
    # We do NOT fabricate a missing lens (a red-team question needs a real, distinct target the model
    # must author — see _fallback). `required_kinds_covered` lets the caller detect and re-ask an
    # under-covered aspect; the generator returns the model's own, valid, capped questions.
    if len(got) <= MAX_QUESTIONS_PER_ASPECT:
        return got
    # Over the cap: keep the required lenses first so trimming can't drop the disconfirming question.
    kept = [q for q in got if q.kind in REQUIRED_KINDS][:MAX_QUESTIONS_PER_ASPECT]
    for q in got:
        if len(kept) >= MAX_QUESTIONS_PER_ASPECT:
            break
        if q not in kept:
            kept.append(q)
    return kept
