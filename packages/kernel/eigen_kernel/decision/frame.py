"""Decision framing — the UNDERSTANDING step that must precede question generation.

Generating questions straight from a fixed coverage rubric produces generic questions: the model just
re-skins each rubric dimension with the decision's nouns. Depth comes from first READING the decision on
its own terms — what is actually being claimed, the mechanism it rests on, the load-bearing premises,
the specific (non-obvious) ways it fails — and only THEN asking questions that test THOSE. This module
does the reading: one agent returns a structured `frame` the question step then interrogates.

Domain-free: what counts as understanding in a given domain is taught by the vertical's `directive`; the
kernel only fixes the SHAPE of the frame and normalizes it. The frame never overrides the coverage
contract — it deepens the questions asked within it (generate.py keeps the rubric as a coverage floor).
"""
from __future__ import annotations

import json

from .types import Aspect

MAX_ASSUMPTIONS = 8
MAX_RISKS = 8
MAX_UNKNOWNS = 6
MAX_ANCHORS = 8


def _str(x, cap: int) -> str:
    return str(x if x is not None else "").strip()[:cap]


def _tagged(items, valid: set, cap_n: int) -> list[dict]:
    out: list[dict] = []
    for it in (items or []):
        if isinstance(it, dict):
            text = _str(it.get("text"), 300)
            dim = _str(it.get("dimension"), 60)
        else:
            text, dim = _str(it, 300), ""
        if not text:
            continue
        out.append({"text": text, "dimension": dim if dim in valid else ""})
        if len(out) >= cap_n:
            break
    return out


def _strings(items, cap_n: int) -> list[str]:
    out: list[str] = []
    for it in (items or []):
        s = _str(it if not isinstance(it, dict) else it.get("text"), 300)
        if s:
            out.append(s)
        if len(out) >= cap_n:
            break
    return out


def normalize_frame(d: dict, valid: set) -> dict:
    """Coerce a raw model frame into the fixed shape; drop anything unusable. Empty frame is valid
    (question generation then falls back to rubric-only, its prior behavior)."""
    if not isinstance(d, dict):
        return {}
    return {
        "reading": _str(d.get("reading"), 800),
        "assumptions": _tagged(d.get("assumptions"), valid, MAX_ASSUMPTIONS),
        "risks": _tagged(d.get("risks"), valid, MAX_RISKS),
        "unknowns": _strings(d.get("unknowns"), MAX_UNKNOWNS),
        "anchors": _strings(d.get("anchors"), MAX_ANCHORS),
    }


def is_substantive(frame: dict | None) -> bool:
    """A frame worth handing to the question step: it read the decision and found something specific to
    test (an assumption or a risk), not just an empty restatement."""
    return bool(frame) and bool(frame.get("assumptions") or frame.get("risks"))


async def frame_decision(llm_json, *, decision: str, context: str = "", directive: str = "",
                         aspects: tuple[Aspect, ...] = ()) -> dict:
    """Read the decision and return a structured understanding of it. Never raises; returns {} when
    there is no model or the output is unusable, so the caller falls back cleanly to rubric-only
    generation. `context` is any raw material behind the decision (e.g. the conversation that produced
    it); `directive` is the vertical's guidance on what understanding means in this domain."""
    if llm_json is None or not (decision or "").strip():
        return {}
    valid = {a.key for a in aspects}
    coverage = "\n".join(f"- {a.key}: {a.prompt}" for a in aspects)
    sections = [f"DECISION (the proposition to test):\n{decision}"]
    if (context or "").strip():
        sections.append("HOW IT WAS ARRIVED AT (raw — mine it for the real substance, "
                        "the specifics the one-line decision leaves out):\n" + context.strip()[:6000])
    if coverage:
        sections.append("COVERAGE MAP — when an assumption or risk you name maps to one of these "
                        "dimensions, tag it with the key (else leave dimension empty):\n" + coverage)
    sections.append(
        "Read this decision closely on ITS OWN terms and return your UNDERSTANDING of it — NOT questions "
        "yet. Return ONE JSON object:\n"
        '{"reading": "<=800 chars: what is actually being claimed — the mechanism it rests on, the '
        'specific wedge, why it would work if it works",\n'
        ' "assumptions": [{"text": "a LOAD-BEARING premise this decision rests on, in its own nouns — '
        'the kind of thing that, if false, breaks it", "dimension": "<key or \'\'>"}],\n'
        ' "risks": [{"text": "a SPECIFIC, non-obvious way THIS decision fails — not a generic caveat", '
        '"dimension": "<key or \'\'>"}],\n'
        ' "unknowns": ["a concrete fact not yet known that would change the picture"],\n'
        ' "anchors": ["a concrete entity, number, or claim the decision names"]}\n'
        "Be specific to THIS decision; a generic answer that would fit any decision is a failure. "
        "Output ONLY the JSON object.")
    try:
        raw = await llm_json(directive, "\n\n".join(sections))
        d = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception:      # noqa: BLE001 — framing never blocks; fall open to rubric-only generation
        return {}
    return normalize_frame(d, valid)
