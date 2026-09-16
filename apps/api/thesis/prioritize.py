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


async def assign_priorities(profile, inquiries: list[dict], *, thesis: str = "", llm_json=None,
                            p0_cap: int = 6) -> None:
    """Mark each generated question with a PRIORITY LEVEL at generation time (mutates the question dicts
    in place, setting `priority`): 0 = P0 (the few cruxes that most decide fund/pass — kept small),
    1 = P1 (important coverage), 2 = P2 (completeness). Assigned with full thesis context by the model,
    with a deterministic fallback (critical aspect + disconfirming lens). So the run never has to re-rank —
    it just filters by level. call_only questions are P2 (they route to an expert, not an evidence run)."""
    by_key = _aspect_index(profile)
    flat = [q for inq in (inquiries or []) for q in (inq.get("questions") or [])]
    if not flat:
        return

    def det(q) -> tuple[int, float]:
        a = by_key.get(q.get("dimension") or q.get("aspect_key"))
        if a is None or getattr(a, "settleable", "") == _CALL_ONLY:
            return 2, 0.0
        base = _score(a, q.get("kind", ""))
        return (0 if getattr(a, "critical", False) else 1), base

    # Deterministic default level + score for every question.
    for q in flat:
        lvl, sc = det(q)
        q["priority"], q["_pscore"] = lvl, sc
    # Cap P0 deterministically: keep the top `p0_cap` by score among the provisional P0s; demote the rest.
    p0 = sorted([q for q in flat if q["priority"] == 0], key=lambda q: -q["_pscore"])
    for q in p0[p0_cap:]:
        q["priority"] = 1

    # LLM refine (has the whole thesis + every question): pick the small P0 crux set + the P1 layer.
    if llm_json is not None:
        listing = "\n".join(f"[{i}] ({q.get('dimension','')}/{q.get('kind','')}) {q.get('text','')[:180]}"
                            for i, q in enumerate(flat))
        system = ("You are an investor's diligence lead assigning PRIORITY LEVELS to research questions for "
                  "a fund/pass decision. Level 0 = P0: the FEW cruxes whose answers most decide the deal — "
                  f"keep P0 SMALL and precise (about {p0_cap}, never more). Level 1 = P1: important coverage. "
                  "Level 2 = P2: completeness. Spread P0 across the decision (don't stack one area). "
                  'Return ONLY {"levels": {"<index>": 0|1|2, ...}} for the indices given.')
        user = f"THESIS:\n{thesis}\n\nQUESTIONS (index, dimension/lens, text):\n{listing}\n\nReturn the JSON."
        try:
            raw = await llm_json(system, user)
            d = raw if isinstance(raw, dict) else json.loads(raw)
            levels = d.get("levels") or {}
            n_p0 = 0
            for i, q in enumerate(flat):
                v = levels.get(str(i), levels.get(i))
                if v is None:
                    continue
                lvl = 0 if str(v) == "0" else (1 if str(v) == "1" else 2)
                if by_key.get(q.get("dimension")) and getattr(by_key[q["dimension"]], "settleable", "") == _CALL_ONLY:
                    lvl = 2                       # call_only never a crux — it routes to a person
                q["priority"] = lvl
                n_p0 += 1 if lvl == 0 else 0
            if n_p0 > p0_cap:                     # model over-marked P0 → keep the top by det score
                over = sorted([q for q in flat if q["priority"] == 0], key=lambda q: -q["_pscore"])
                for q in over[p0_cap:]:
                    q["priority"] = 1
        except Exception:      # noqa: BLE001 — keep the deterministic levels
            pass
    for q in flat:
        q.pop("_pscore", None)


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
