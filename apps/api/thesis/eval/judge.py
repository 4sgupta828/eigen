"""Rubric judge for thesis ANSWER quality — the baseline the answer-quality work is measured against.

A judge model scores one answer on four dimensions the product cares about, given the question, the
thesis, the aspect, the item's rubric_focus, and the evidence the answer cited. Deliberately family-
independent when possible (pass a cross-family judge_llm, like the refuter) so it does not grade its own
homework. Pure prompt + parse; never raises (a failed judge scores 0 with a reason, so a batch never
dies on one item).
"""
from __future__ import annotations

import json

DIMENSIONS = ("coverage", "specificity", "groundedness", "usefulness")

_SYSTEM = """You are a demanding VC diligence lead grading the ANSWER an automated analyst gave to one
question about a startup thesis. Score 1-5 on each dimension (5 = excellent, 1 = useless), strictly:

- coverage: does it actually answer what THIS question asks, covering the facets a strong answer needs
  (see the RUBRIC FOCUS)? Partial or off-topic scores low.
- specificity: concrete facts — named companies/people, numbers, dates, mechanisms — not vague gloss
  ("some firms do X" is a 1-2; "OpenAI runs GPT-5.6 on WSE-3 at 750 tok/s" is a 5).
- groundedness: is every factual claim backed by the cited evidence, with honest register (a signal is
  not dressed as a filed fact)? Fabrication or uncited assertion scores 1. For a call_only aspect, an
  HONEST 'the record can't settle this, it needs a person' with useful proxies is GOOD groundedness,
  not a coverage failure.
- usefulness: would this move a real diligence decision, or is it filler?

Return ONLY: {"coverage":N,"specificity":N,"groundedness":N,"usefulness":N,"overall":N,
"rationale":"one sentence","missing":"the single most important thing a better answer would add"}.
overall is your holistic 1-5, not necessarily the average."""


def _prompt(*, question, thesis, aspect, rubric_focus, answer, evidence):
    ev = "\n".join(f"- [{e.get('id')}] ({e.get('register','')}/{e.get('evidence_kind','')}) "
                   f"{str(e.get('quote') or '')[:200]}" for e in (evidence or [])[:16]) or "(no evidence cited)"
    return (f"THESIS: {thesis}\nASPECT: {aspect}\nQUESTION: {question}\n"
            f"RUBRIC FOCUS (what a strong answer must cover): {rubric_focus}\n\n"
            f"ANSWER UNDER REVIEW (citation markers look like [[e:id]]):\n{answer or '(empty)'}\n\n"
            f"EVIDENCE THE ANSWER COULD CITE:\n{ev}\n\nScore it now as the JSON object.")


def _clamp(v):
    try:
        return max(1, min(5, int(round(float(v)))))
    except Exception:      # noqa: BLE001
        return 0


async def judge_answer(llm_json, *, question, thesis, aspect, rubric_focus, answer, evidence):
    """-> {coverage, specificity, groundedness, usefulness, overall, rationale, missing}. Never raises."""
    blank = {d: 0 for d in DIMENSIONS} | {"overall": 0, "rationale": "judge unavailable", "missing": ""}
    if llm_json is None:
        return blank
    try:
        raw = await llm_json(_SYSTEM, _prompt(question=question, thesis=thesis, aspect=aspect,
                                              rubric_focus=rubric_focus, answer=answer, evidence=evidence))
        d = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception:      # noqa: BLE001 — one bad judge call scores 0, never kills the batch
        return blank
    out = {dim: _clamp(d.get(dim)) for dim in DIMENSIONS}
    out["overall"] = _clamp(d.get("overall")) or _clamp(sum(out[x] for x in DIMENSIONS) / 4)
    out["rationale"] = str(d.get("rationale") or "")[:300]
    out["missing"] = str(d.get("missing") or "")[:300]
    return out


def aggregate(results: list[dict]) -> dict:
    """Mean of each dimension + overall across scored items, plus the count. A dimension mean ignores
    items the judge could not score (0)."""
    keys = DIMENSIONS + ("overall",)
    agg: dict = {"n": len(results)}
    for k in keys:
        vals = [r["scores"][k] for r in results if r.get("scores", {}).get(k)]
        agg[k] = round(sum(vals) / len(vals), 2) if vals else 0.0
    agg["n_scored"] = sum(1 for r in results if r.get("scores", {}).get("overall"))
    return agg
