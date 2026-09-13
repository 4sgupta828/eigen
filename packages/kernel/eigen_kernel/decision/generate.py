"""Decision-level question generation + clustering — the factra move.

Instead of asking a fixed question per fixed aspect, one agent reads the whole DECISION and generates
thesis-native questions that COVER it, then clusters them into named lines of inquiry. The coverage
CONTRACT is still the profile's aspect set (the rubric): code guarantees every aspect is addressed by at
least one question (Rule 18 — the model authors thesis-specific wording and clusters; code enforces that
nothing in the contract is dropped). Domain-free: the rubric and the directive come from the profile.
"""
from __future__ import annotations

import json
import re

from .types import Aspect, Question, QuestionKind

MAX_QUESTIONS = 24          # a ceiling on the whole set, so cost stays bounded
MAX_PER_DIMENSION = 4


def _slug(name: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "inquiry")[:40]


def _fallback(aspects: tuple[Aspect, ...]) -> list[dict]:
    """No model, or unusable output: one honest line of inquiry, one seek-support question per aspect,
    phrased with the aspect's canonical prompt. Coverage is total; wording is generic (degraded)."""
    return [{"key": "coverage", "name": "What this decision rests on",
             "framing": "the load-bearing questions", "questions": [
                 {"dimension": a.key, "kind": "seek_support", "text": a.prompt,
                  "target": a.prompt, "polarity": 1} for a in aspects]}]


def _coerce_question(item: dict, valid_dims: set) -> dict | None:
    try:
        kind = QuestionKind(str(item.get("kind") or "").strip())
    except ValueError:
        return None
    text = str(item.get("text") or "").strip()
    target = str(item.get("target") or "").strip()
    dim = str(item.get("dimension") or "").strip()
    if not text or not target or dim not in valid_dims:
        return None
    pol = -1 if str(item.get("polarity")) in ("-1", "-", "against", "contradict") else 1
    return {"dimension": dim, "kind": kind.value, "text": text[:400], "target": target[:400], "polarity": pol}


async def generate_inquiries(llm_json, *, decision: str, aspects: tuple[Aspect, ...],
                             directive: str) -> list[dict]:
    """-> [{key, name, framing, questions:[{dimension,kind,text,target,polarity}]}]. Never raises.
    Thesis-native questions + clusters from the model; code guarantees every aspect is covered."""
    valid = {a.key for a in aspects}
    if llm_json is None:
        return _fallback(aspects)
    rubric = "\n".join(f"- {a.key}: {a.prompt}"
                       + (" [only a person can settle this]" if a.settleable == "call_only" else "")
                       + (" [critical]" if a.critical else "") for a in aspects)
    user = (f"DECISION (the thesis to test):\n{decision}\n\n"
            f"COVERAGE CONTRACT — every one of these dimensions must be addressed by at least one "
            f"question, tagged with its key in `dimension`:\n{rubric}\n\n"
            'Return ONE JSON object: {"inquiries": [{"name": "...", "framing": "...", '
            '"questions": [{"dimension": "<key>", "kind": "seek_support|seek_contradiction|'
            'resolve_ambiguity|challenge_assumption", "text": "the question, in THIS thesis\'s own '
            'nouns", "target": "a flat declarative statement the record could confirm or refute", '
            '"polarity": 1|-1}]}]}. polarity is +1 if confirming target supports the thesis on that '
            "dimension, -1 if it contradicts it. Cluster the questions into 3–5 named lines of inquiry "
            "that fit THIS thesis (not generic buckets). Output ONLY the JSON object.")
    try:
        raw = await llm_json(directive, user)
        d = raw if isinstance(raw, dict) else json.loads(raw)
        clusters = d.get("inquiries") or []
    except Exception:      # noqa: BLE001 — generation never blocks; fall open to full coverage
        clusters = []

    out: list[dict] = []
    seen_dims: set = set()
    total = 0
    for c in clusters:
        name = str((c or {}).get("name") or "").strip()
        if not name:
            continue
        per_dim: dict = {}
        qs = []
        for item in (c.get("questions") or []):
            q = _coerce_question(item, valid)
            if not q:
                continue
            per_dim[q["dimension"]] = per_dim.get(q["dimension"], 0) + 1
            if per_dim[q["dimension"]] > MAX_PER_DIMENSION or total >= MAX_QUESTIONS:
                continue
            qs.append(q); seen_dims.add(q["dimension"]); total += 1
        if qs:
            out.append({"key": _slug(name), "name": name[:120],
                        "framing": str(c.get("framing") or "").strip()[:200], "questions": qs})
    if not out:
        return _fallback(aspects)
    # Coverage gate: any contract dimension the model missed is added as a canonical question so the
    # thesis is never left with a blind spot.
    missing = [a for a in aspects if a.key not in seen_dims]
    if missing:
        out.append({"key": "further-checks", "name": "Further checks",
                    "framing": "coverage the drafted lines of inquiry did not reach",
                    "questions": [{"dimension": a.key, "kind": "seek_support", "text": a.prompt,
                                   "target": a.prompt, "polarity": 1} for a in missing]})
    return out
