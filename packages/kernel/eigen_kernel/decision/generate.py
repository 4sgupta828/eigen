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


def _frame_block(frame: dict | None) -> str:
    """Render the decision frame (from frame.py) as the SUBSTANCE the questions must interrogate. When a
    frame is present, the rubric drops from generative-seed to coverage-floor: the model writes questions
    that test THESE specific assumptions and probe THESE specific risks, not the generic rubric."""
    if not frame:
        return ""
    parts = []
    if frame.get("reading"):
        parts.append("HOW THIS DECISION READS (the mechanism to interrogate):\n" + frame["reading"])
    if frame.get("assumptions"):
        parts.append("LOAD-BEARING ASSUMPTIONS — write the question(s) whose answer would CONFIRM or "
                     "BREAK each one (tag with its dimension when given):\n"
                     + "\n".join(f"- {a['text']}"
                                 + (f"  [{a['dimension']}]" if a.get("dimension") else "")
                                 for a in frame["assumptions"]))
    if frame.get("risks"):
        parts.append("SPECIFIC RISKS — write the DISCONFIRMING probe (a seek_contradiction or "
                     "challenge_assumption question) for each:\n"
                     + "\n".join(f"- {r['text']}"
                                 + (f"  [{r['dimension']}]" if r.get("dimension") else "")
                                 for r in frame["risks"]))
    if frame.get("unknowns"):
        parts.append("OPEN UNKNOWNS worth resolving:\n"
                     + "\n".join(f"- {u}" for u in frame["unknowns"]))
    return "\n\n".join(parts)


async def generate_inquiries(llm_json, *, decision: str, aspects: tuple[Aspect, ...],
                             directive: str, frame: dict | None = None) -> list[dict]:
    """-> [{key, name, framing, questions:[{dimension,kind,text,target,polarity}]}]. Never raises.
    Thesis-native questions + clusters from the model; code guarantees every aspect is covered.

    When `frame` (from frame.py) is supplied, its assumptions/risks become the SUBSTANCE the questions
    interrogate — that is where depth comes from — while the aspect rubric drops to a coverage floor."""
    valid = {a.key for a in aspects}
    if llm_json is None:
        return _fallback(aspects)
    rubric = "\n".join(f"- {a.key}: {a.prompt}"
                       + (" [only a person can settle this]" if a.settleable == "call_only" else "")
                       + (" [critical]" if a.critical else "") for a in aspects)
    frame_block = _frame_block(frame)
    seed = ((frame_block + "\n\n") if frame_block else "")
    contract_role = ("COVERAGE FLOOR — every dimension must still be addressed by at least one question "
                     "(tag it in `dimension`), but let the assumptions and risks above drive WHAT you "
                     "ask; do not reduce the set to one generic question per dimension:"
                     if frame_block else
                     "COVERAGE CONTRACT — every one of these dimensions must be addressed by at least "
                     "one question, tagged with its key in `dimension`:")
    user = (f"DECISION (the thesis to test):\n{decision}\n\n"
            f"{seed}"
            f"{contract_role}\n{rubric}\n\n"
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
    # Coverage gate: any contract dimension the model missed is added so the thesis is never left with a
    # blind spot — but phrased THESIS-NATIVELY (a second pass), not as the raw rubric prompt, so the
    # gap-fill never reintroduces the generic questions the frame step exists to avoid.
    missing = [a for a in aspects if a.key not in seen_dims]
    if missing:
        gap_qs = await _gapfill(llm_json, decision=decision, missing=missing,
                                frame=frame, directive=directive, valid=valid) if llm_json else []
        filled = {q["dimension"] for q in gap_qs}
        raw = [{"dimension": a.key, "kind": "seek_support", "text": a.prompt, "target": a.prompt,
                "polarity": 1} for a in missing if a.key not in filled]   # degraded fallback only
        out.append({"key": "further-checks", "name": "Further checks",
                    "framing": "coverage the drafted lines of inquiry did not reach",
                    "questions": gap_qs + raw})
    return out


async def _gapfill(llm_json, *, decision: str, missing, frame: dict | None,
                   directive: str, valid: set) -> list[dict]:
    """One thesis-native question per missing dimension, so coverage never falls back to the raw rubric
    prompt. Returns coerced question dicts; [] on any failure (caller uses the raw-prompt fallback)."""
    rubric = "\n".join(f"- {a.key}: {a.prompt}" for a in missing)
    reading = (frame or {}).get("reading") or ""
    user = (f"DECISION (the thesis to test):\n{decision}\n\n"
            + (f"HOW IT READS:\n{reading}\n\n" if reading else "")
            + "COVERAGE GAP — the draft did not yet ask about these dimensions. Write ONE pointed "
            "question for EACH, in THIS thesis's own nouns (never the generic prompt text), tagged with "
            f"its dimension key:\n{rubric}\n\n"
            'Return ONE JSON object: {"questions": [{"dimension": "<key>", "kind": "seek_support|'
            'seek_contradiction|resolve_ambiguity|challenge_assumption", "text": "the question", '
            '"target": "a flat declarative statement the record could confirm or refute", '
            '"polarity": 1|-1}]}. Output ONLY the JSON object.')
    try:
        raw = await llm_json(directive, user)
        d = raw if isinstance(raw, dict) else json.loads(raw)
        items = d.get("questions") or []
    except Exception:      # noqa: BLE001 — gap-fill never blocks; caller falls back to raw prompts
        return []
    out: list[dict] = []
    got: set = set()
    for it in items:
        q = _coerce_question(it, valid)
        if q and q["dimension"] not in got:
            out.append(q); got.add(q["dimension"])
    return out
