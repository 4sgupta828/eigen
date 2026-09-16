"""Decision-level question generation + clustering — the factra move, made systematic (panel 2026-09-16).

One agent reads the whole DECISION and generates thesis-native questions that COVER it, clustered into
named lines of inquiry. The kernel then makes the set SYSTEMATIC without reading a single domain word:

  1. allocate_budget — a frame-weighted, global-target soft budget per aspect (budget.py). Depth follows
     THIS decision's risk density, not a flat ceiling; every aspect keeps a floor of 1.
  2. score + select — rank each question by how tightly it binds to the frame's assumptions/risks, keep
     the best up to each aspect's budget, drop near-duplicates (select.py). Selection, never a hard gate:
     a dimension is trimmed for precision, never emptied.
  3. coverage floor — any aspect the model (after selection) left with nothing is filled by a SECOND
     thesis-native pass, the raw aspect prompt only as a last resort. No filler is manufactured to reach
     a budget the model could not fill — the unused share was already reallocated in step 1.

The coverage CONTRACT is still the profile's aspect set; the rubric and directive come from the profile.
Domain-free throughout.
"""
from __future__ import annotations

import asyncio
import json
import re

from .types import Aspect, Inquiry, Question, QuestionKind
from .budget import allocate_budget, DEFAULT_TOTAL
from .select import score_questions, select_for_aspect

MAX_QUESTIONS = 48         # a hard safety ceiling on the whole set; the allocator's `total` is the real knob


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


def _as_question(q: dict) -> Question:
    return Question(kind=QuestionKind(q["kind"]), text=q["text"], target=q["target"],
                    polarity=q["polarity"], dimension=q["dimension"])


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
                             directive: str, frame: dict | None = None,
                             total: int = DEFAULT_TOTAL, embed=None) -> list[dict]:
    """-> [{key, name, framing, questions:[{dimension,kind,text,target,polarity}]}]. Never raises.
    Thesis-native questions + clusters from the model; the kernel makes the set systematic:
    frame-weighted per-aspect budgets, relevance ranking, de-dup, and a guaranteed coverage floor.

    `total` is the global question budget (a smaller number = a shallower pass). `embed(texts)->vectors`
    sharpens relevance + de-dup on paraphrase; omitted, both fall back to lexical."""
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

    # ── Flatten to a global list, remembering each question's cluster, so selection can be per-DIMENSION
    #    (a dimension may be split across clusters) while output stays per-CLUSTER (the card shape). ─────
    cluster_meta: list[dict] = []          # {key, name, framing} per surviving cluster slot
    coerced: list[dict] = []               # global question dicts
    q_of_cluster: list[int] = []           # cluster index per global question
    for c in clusters:
        name = str((c or {}).get("name") or "").strip()
        if not name:
            continue
        ci = len(cluster_meta)
        cluster_meta.append({"key": _slug(name), "name": name[:120],
                             "framing": str(c.get("framing") or "").strip()[:200]})
        for item in (c.get("questions") or []):
            q = _coerce_question(item, valid)
            if q:
                coerced.append(q); q_of_cluster.append(ci)

    if not coerced:
        return _fallback(aspects)

    # ── Systematic selection: budget → score → keep the best per aspect up to budget, floor 1. ──────────
    budget = allocate_budget(aspects, frame, total=min(total, MAX_QUESTIONS))
    questions = [_as_question(q) for q in coerced]
    scores, embed_vecs = score_questions(questions, frame, embed=embed)
    gi_of = {id(q): i for i, q in enumerate(questions)}
    kept_gis: set[int] = set()
    for a in aspects:
        gis = [i for i, q in enumerate(coerced) if q["dimension"] == a.key]
        if not gis:
            continue
        picked = select_for_aspect([questions[i] for i in gis], [scores[i] for i in gis],
                                   budget=max(1, budget.get(a.key, 1)), floor=1,
                                   embed_vecs=embed_vecs, indices=gis)
        kept_gis.update(gi_of[id(q)] for q in picked)

    # Hard safety ceiling on the whole set (the allocator's total normally binds first): keep the
    # highest-relevance, required-lens-first questions if somehow over.
    if len(kept_gis) > MAX_QUESTIONS:
        ranked = sorted(kept_gis, key=lambda i: (0 if questions[i].kind in
                        (QuestionKind.SEEK_SUPPORT, QuestionKind.SEEK_CONTRADICTION) else 1, -scores[i]))
        kept_gis = set(ranked[:MAX_QUESTIONS])

    # ── Rebuild the clusters from the kept questions (preserve names/framing; drop empty clusters). ─────
    out: list[dict] = []
    seen_dims: set = set()
    for ci, meta in enumerate(cluster_meta):
        qs = [coerced[gi] for gi in range(len(coerced)) if gi in kept_gis and q_of_cluster[gi] == ci]
        if qs:
            out.append({**meta, "questions": qs})
            seen_dims.update(q["dimension"] for q in qs)
    if not out:
        return _fallback(aspects)

    # ── Coverage floor: any contract dimension left with nothing is filled thesis-natively (a second
    #    pass), the raw rubric prompt only as a last resort — never the generic default. ────────────────
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


def _frame_for_aspects(frame: dict | None, keys: set) -> dict | None:
    """Slice the frame down to the assumptions/risks that bear on THIS inquiry's aspects (untagged ones
    are kept — they may still be relevant), so a focused generation call sees the substance it needs
    without the whole thesis's frame diluting it. Keeps the reading + unknowns for context."""
    if not frame:
        return frame
    def keep(items):
        return [it for it in (items or []) if (it.get("dimension") or "") in keys or not it.get("dimension")]
    return {"reading": frame.get("reading", ""), "assumptions": keep(frame.get("assumptions")),
            "risks": keep(frame.get("risks")), "unknowns": frame.get("unknowns") or [],
            "anchors": frame.get("anchors") or []}


_INQUIRY_FOCUS = ("You are drafting questions for ONE line of inquiry of this specific decision — a focused "
                  "facet, not the whole thing. Go DEEP on it. Every question must turn on THIS decision's "
                  "OWN specifics — the named entities, products, buyers, numbers, and the assumptions/risks "
                  "above — never a generic template. A question that could be asked of ANY decision of this "
                  "kind (a rubric restatement like the dimension prompt itself) is a FAILURE: anchor each to "
                  "a concrete noun from the decision. Balance the lenses across the set (seek support, seek "
                  "disconfirmation, resolve an ambiguity, challenge a hidden premise).")


async def _gen_one_inquiry(llm_json, *, decision: str, name: str, framing: str,
                           inq_aspects: tuple[Aspect, ...], directive: str, frame: dict | None) -> list[dict]:
    """Thesis-native questions for ONE inquiry's aspects. Focused (2–4 aspects) so the model can be
    specific rather than spreading thin across the whole contract — the fix for generic, cookie-cutter
    questions. Returns coerced question dicts tagged with their aspect key; [] on any failure."""
    valid = {a.key for a in inq_aspects}
    rubric = "\n".join(f"- {a.key}: {a.prompt}"
                       + (" [only a person can settle this]" if a.settleable == "call_only" else "")
                       + (" [critical]" if a.critical else "") for a in inq_aspects)
    fb = _frame_block(_frame_for_aspects(frame, valid))
    user = (f"DECISION (the thesis to test):\n{decision}\n\n"
            f"LINE OF INQUIRY: {name}" + (f" — {framing}" if framing else "") + "\n\n"
            + ((fb + "\n\n") if fb else "")
            + _INQUIRY_FOCUS + "\n\n"
            + "DIMENSIONS this line must cover (tag each question with its key in `dimension`):\n" + rubric
            + "\n\nReturn ONE JSON object: {\"questions\": [{\"dimension\": \"<key>\", \"kind\": "
            "\"seek_support|seek_contradiction|resolve_ambiguity|challenge_assumption\", \"text\": \"the "
            "question in THIS thesis's own nouns\", \"target\": \"a flat declarative statement the record "
            "could confirm or refute\", \"polarity\": 1|-1}]}. polarity is +1 if confirming target "
            "supports the thesis on that dimension, -1 if it contradicts it. Output ONLY the JSON object.")
    try:
        raw = await llm_json(directive + "\n\n" + _INQUIRY_FOCUS, user)
        d = raw if isinstance(raw, dict) else json.loads(raw)
        items = d.get("questions") or []
    except Exception:      # noqa: BLE001 — one inquiry failing never blocks the rest
        return []
    out = []
    for it in items:
        q = _coerce_question(it, valid)
        if q:
            out.append(q)
    return out


async def generate_by_inquiry(llm_json, *, decision: str, inquiries: tuple[Inquiry, ...],
                              aspects: tuple[Aspect, ...], directive: str, frame: dict | None = None,
                              total: int = DEFAULT_TOTAL, embed=None) -> list[dict]:
    """-> [{key, name, framing, questions:[...]}], one entry per PROFILE inquiry (a fixed, coverage-safe
    partition). Generates each line of inquiry with its OWN focused, frame-driven call — so questions are
    deep and thesis-native instead of a single call spread thin across the whole contract (the fix for
    cookie-cutter questions). Per-aspect budget + relevance selection + de-dup still apply; a dimension a
    focused call missed is gap-filled thesis-natively. Never raises."""
    if llm_json is None:
        return _fallback(aspects)
    by_key = {a.key: a for a in aspects}
    budget = allocate_budget(aspects, frame, total=min(total, MAX_QUESTIONS))
    inq_aspects = {inq.key: tuple(by_key[k] for k in inq.aspect_keys if k in by_key) for inq in inquiries}

    raws = await asyncio.gather(*[
        _gen_one_inquiry(llm_json, decision=decision, name=inq.name, framing=inq.framing,
                         inq_aspects=inq_aspects[inq.key], directive=directive, frame=frame)
        for inq in inquiries if inq_aspects[inq.key]], return_exceptions=True)

    out: list[dict] = []
    covered: set = set()
    ri = 0
    for inq in inquiries:
        if not inq_aspects[inq.key]:
            continue
        coerced = raws[ri] if ri < len(raws) and isinstance(raws[ri], list) else []
        ri += 1
        questions = [_as_question(q) for q in coerced]
        scores, embed_vecs = score_questions(questions, frame, embed=embed)
        gi_of = {id(q): i for i, q in enumerate(questions)}
        kept: list[dict] = []
        for a in inq_aspects[inq.key]:
            gis = [i for i, q in enumerate(coerced) if q["dimension"] == a.key]
            if not gis:
                continue
            picked = select_for_aspect([questions[i] for i in gis], [scores[i] for i in gis],
                                       budget=max(1, budget.get(a.key, 2)), floor=1,
                                       embed_vecs=embed_vecs, indices=gis)
            for q in picked:
                kept.append(coerced[gi_of[id(q)]]); covered.add(a.key)
        if kept:
            out.append({"key": inq.key, "name": inq.name, "framing": inq.framing, "questions": kept})

    # Coverage floor: any aspect no focused call reached is gap-filled thesis-natively into its inquiry.
    inq_of_aspect = {k: inq for inq in inquiries for k in inq.aspect_keys}
    missing = [by_key[a.key] for a in aspects if a.key not in covered]
    if missing:
        gap = await _gapfill(llm_json, decision=decision, missing=missing, frame=frame,
                             directive=directive, valid={a.key for a in aspects})
        filled = {q["dimension"] for q in gap}
        gap += [{"dimension": a.key, "kind": "seek_support", "text": a.prompt, "target": a.prompt,
                 "polarity": 1} for a in missing if a.key not in filled]
        by_inq: dict = {}
        for q in gap:
            ik = getattr(inq_of_aspect.get(q["dimension"]), "key", "further-checks")
            by_inq.setdefault(ik, []).append(q)
        existing = {o["key"]: o for o in out}
        for inq in inquiries:
            qs = by_inq.get(inq.key)
            if not qs:
                continue
            if inq.key in existing:
                existing[inq.key]["questions"].extend(qs)
            else:
                out.append({"key": inq.key, "name": inq.name, "framing": inq.framing, "questions": qs})
    return out or _fallback(aspects)


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
