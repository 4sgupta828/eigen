"""Prioritize a CRITICAL SUBSET of questions across ALL lines of inquiry.

Running every question is thorough but expensive; most of the fund/pass call turns on a handful. This
picks the subset whose answers would most move the decision — ranked by an LLM that reads the whole
thesis (the adaptive signal), with a deterministic score as the fallback and the tie-breaker so the
result is never worse than a sensible default and never blocks. Coverage floor: at least one question
per CRITICAL aspect survives, so prioritization never silently drops a load-bearing dimension.

call_only aspects (settled by a person, not a document) are excluded — they never run against evidence.
"""
from __future__ import annotations

import json

_CALL_ONLY = "call_only"
_CONTRA = "seek_contradiction"
_CHALLENGE = "challenge_assumption"
_SUPPORT = "seek_support"


def _aspect_index(profile) -> dict:
    return {a.key: a for a in profile.aspects()}


def _score(aspect, kind: str) -> float:
    """Deterministic decision-value score. Critical aspects dominate; disconfirming and assumption-
    challenging lenses outrank plain support (a stress test is worth most where it can break the thesis)."""
    s = 2.0 if getattr(aspect, "critical", False) else 0.6
    if kind == _CONTRA:
        s += 1.0
    elif kind == _CHALLENGE:
        s += 0.7
    elif kind == _SUPPORT:
        s += 0.4
    return s


async def _llm_rank(llm_json, *, thesis: str, runnable: list[dict]) -> list[str]:
    """Ask the model which questions' answers would MOST move the fund/pass call — returns an ordered list
    of question ids, best first. [] on any failure (caller uses the deterministic order)."""
    if llm_json is None or not runnable:
        return []
    listing = "\n".join(f"[{q['id']}] ({q.get('aspect_key','')}/{q.get('kind','')}) {q.get('text','')[:200]}"
                        for q in runnable)
    system = ("You are an investor's diligence lead. Given a thesis and its candidate research questions, "
              "return the questions whose ANSWERS would MOST move the FUND / PASS decision — the "
              "load-bearing cruxes and the sharpest disconfirming probes first. Prefer breadth across the "
              "decision (problem, buyer, market, competition, moat, tech, traction) over piling into one "
              "area. Return ONLY {\"ranked_ids\": [\"<id>\", ...]} best first; you may omit low-value ones.")
    user = f"THESIS:\n{thesis}\n\nCANDIDATE QUESTIONS (id, aspect/lens, text):\n{listing}\n\nReturn the JSON."
    try:
        raw = await llm_json(system, user)
        d = raw if isinstance(raw, dict) else json.loads(raw)
        return [str(x) for x in (d.get("ranked_ids") or []) if str(x)]
    except Exception:      # noqa: BLE001 — ranking never blocks; deterministic order stands
        return []


async def select_subset(profile, question_rows: list[dict], *, thesis: str = "", llm_json=None,
                        cap: int = 12) -> list[dict]:
    """-> the chosen question ROWS (a subset of `question_rows`) to run. Unanswered, non-call_only
    questions only. LLM ranking when available, deterministic score otherwise/as tie-breaker; a coverage
    floor guarantees every critical aspect keeps at least its top question. Deterministic and safe."""
    by_key = _aspect_index(profile)
    runnable = []
    for q in question_rows:
        a = by_key.get(q.get("aspect_key"))
        if a is None or getattr(a, "settleable", "") == _CALL_ONLY:
            continue
        if q.get("target_status"):                      # already answered — nothing to run
            continue
        runnable.append(q)
    if not runnable:
        return []
    det = {q["id"]: _score(by_key[q["aspect_key"]], q.get("kind", "")) for q in runnable}
    ranked_ids = await _llm_rank(llm_json, thesis=thesis, runnable=runnable)
    order = {qid: i for i, qid in enumerate(ranked_ids)}
    # sort by the LLM rank (if it placed the id), then by deterministic score, then stable by id
    runnable.sort(key=lambda q: (order.get(q["id"], 10_000), -det[q["id"]], q["id"]))
    chosen = runnable[:max(1, cap)]
    chosen_ids = {q["id"] for q in chosen}
    # Coverage floor: every CRITICAL aspect keeps at least its highest-scored runnable question.
    crit = {k for k, a in by_key.items() if getattr(a, "critical", False)}
    covered = {q["aspect_key"] for q in chosen}
    for akey in crit:
        if akey in covered:
            continue
        cands = [q for q in runnable if q["aspect_key"] == akey]
        if cands:
            best = max(cands, key=lambda q: det[q["id"]])
            if best["id"] not in chosen_ids:
                chosen.append(best); chosen_ids.add(best["id"])
    return chosen
