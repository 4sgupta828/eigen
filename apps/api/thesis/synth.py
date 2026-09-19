"""Cross-finding synthesis for a thesis — three investor artifacts composed over EVERY answered
question at once:

  • Startup Pitch Deck   — the steelman investor deck, slide by slide (compose_over_findings)
  • Collective Take      — a two-layer diligence memo: grounded facts + tagged reasoning blocks
                           (compose_memo — factra's decision-memo model)
  • Competitive Analysis — the thesis company vs. named peers across the startup rubric (compose_matrix)

The unit of citation is the FINDING (an already-grounded answer), so the synthesis reasons over findings
and cites them; the reader drills from a finding to its own sources in the lines-of-inquiry view. The
mechanics are the kernel's; the section specs, analyst voices, and competitive rubric are the vertical's
(`pitch_deck_spec` / `collective_take_spec` / `competitive_spec`). Never spends unless there are
findings; never raises.
"""
from __future__ import annotations

import logging
import time

from eigen_kernel.decision import compose_deck, compose_memo

_log = logging.getLogger("eigen.thesis.synth")

from . import store as tstore


def _take_substantive(take: dict) -> bool:
    """True if a collective take actually has content — a bottom line, or a section with grounded facts
    or reasoning. Used to refuse to overwrite a real take with a blank one from a failed re-synthesis."""
    if not take or take.get("empty"):
        return False
    if (take.get("bottom_line") or {}).get("text"):
        return True
    for s in (take.get("sections") or []):
        if (s.get("grounded") or []) or (s.get("analysis") or []):
            return True
    return False


def _deck_substantive(deck: dict) -> bool:
    """True if a deck actually has content — a spine or at least one section with a headline or points.
    Used to refuse to overwrite a real deck with a blank one from a failed/empty rebuild."""
    if not deck or deck.get("empty"):
        return False
    if deck.get("spine"):
        return True
    for s in (deck.get("sections") or []):
        if (s.get("points") or []) or (s.get("headline") or {}).get("text") or s.get("prose"):
            return True
    return False


def _empty_deck(sections) -> dict:
    return {"spine": {}, "sections": [{"key": s["key"], "title": s["title"],
            "headline": {"text": "", "markers": ""}, "points": []} for s in sections],
            "empty": True, "generated_at": 0}


def _take_context(take_obj: dict, *, cap: int = 2800) -> str:
    """The Collective Take rendered as plain narrative CONTEXT for the deck — the connect-the-dots read
    the deck should build its story around. NOT a citation source: the deck still cites findings, never
    this text. Markers are stripped; the bottom line and the tagged reasoning blocks carry the signal."""
    if not take_obj or take_obj.get("empty"):
        return ""
    import re
    strip = lambda t: re.sub(r"\[\[e:[^\]]+\]\]", "", str(t or "")).strip()
    parts: list[str] = []
    bl = strip((take_obj.get("bottom_line") or {}).get("text"))
    if bl:
        parts.append(f"BOTTOM LINE: {bl}")
    for s in (take_obj.get("sections") or []):
        reasons = [f"  [{a.get('kind')}] {strip(a.get('text'))}"
                   for a in (s.get("analysis") or []) if strip(a.get("text"))]
        if reasons:
            parts.append(str(s.get("title") or s.get("key") or "") + "\n" + "\n".join(reasons))
    return "\n".join(parts)[:cap].strip()


def _empty_take(sections) -> dict:
    return {"bottom_line": {"text": "", "markers": ""},
            "sections": [{"key": s["key"], "title": s["title"], "grounded": [], "analysis": []}
                         for s in sections], "empty": True, "generated_at": 0}


def _empty_matrix(columns) -> dict:
    return {"columns": [{"key": c["key"], "label": c["label"]} for c in columns], "rows": [],
            "empty": True, "generated_at": 0}


def _aspect_prompt(profile, key: str) -> str:
    a = next((a for a in profile.aspects() if a.key == key), None)
    return getattr(a, "prompt", key) if a else key


async def _load_findings(pool, thesis_id: str, profile) -> tuple[str, str, list[dict]]:
    """(thesis text, subject label, findings). A finding is one ANSWERED question, carrying its id (for
    citation), the line of inquiry + aspect it sits under, its status, and its grounded answer."""
    d = await tstore.get(pool, thesis_id=thesis_id, trusted=True)
    if not d:
        return "", "", []
    thesis = d.get("thesis") or ""
    subject = " ".join(str(v) for v in (d.get("subject") or {}).values()).strip()
    qs = await tstore.list_questions(pool, thesis_id)
    findings: list[dict] = []
    for q in qs:
        if not q.get("target_status") or not (q.get("answer") or "").strip():
            continue
        findings.append({"id": str(q.get("id")), "line": q.get("inquiry_name") or "Findings",
                         "aspect": _aspect_prompt(profile, q.get("aspect_key") or ""),
                         "question": q.get("text") or "", "answer": q.get("answer") or "",
                         "status": q.get("target_status") or "",
                         "priority": int(q.get("priority") or 1)})
    return thesis, subject, findings


# The synthesis prompt must stay within a size the model reliably composes over — an unbounded finding
# set was what made the take time out / blank on deeper runs. We keep the MOST decision-relevant findings
# (crux P0 first, then P1, P2 …) up to a character budget with headroom for the instructions + the memo
# itself, rather than feeding everything. Comfortably fits every normal thesis; only the largest are cut.
_TAKE_FINDINGS_CHARS = 26000     # ~6.5K tokens of findings — leaves ample room in the model's context
_TAKE_ANSWER_CHARS = 2000        # per-finding answer cap fed to synthesis (matches compose's answer_chars)


def _bound_findings(findings: list[dict], *, max_chars: int = _TAKE_FINDINGS_CHARS,
                    per_answer: int = _TAKE_ANSWER_CHARS) -> tuple[list[dict], bool]:
    """Rank findings by decision-relevance (priority level, crux first) and keep those that fit the budget,
    so synthesis never overflows. Returns (kept, truncated). At least one finding is always kept."""
    ranked = sorted(findings or [], key=lambda f: (int(f.get("priority", 1)), str(f.get("line", ""))))
    kept, used = [], 0
    for f in ranked:
        cost = min(len(f.get("answer", "")), per_answer) + len(f.get("question", "")) + 48
        if kept and used + cost > max_chars:
            break
        kept.append(f)
        used += cost
    return kept, len(kept) < len(ranked)


async def synthesize_all(pool, thesis_id: str, profile, llm_json, take_llm_json=None,
                         default_llm=None) -> dict:
    """Compose + persist the COLLECTIVE TAKE (the integrated diligence read). Returns
    {"take": {...}, "findings": <n>}. With no findings yet, persists an empty take.

    The Pitch Deck (synthesize_deck) and the Competitive landscape (competitive.research_landscape) are
    now SEPARATE, independently-triggered artifacts — a run/rebuild produces the take, and the user
    generates the deck (and researches competitors) on demand afterward. So this never overwrites a deck
    the user asked for, and the take is the fast, always-current synthesis after a run.

    `take_llm_json`: the deep-thinking (reasoning) seam; falls back to `llm_json` when not supplied."""
    take_llm = take_llm_json or llm_json
    take_dir, take_secs = profile.collective_take_spec()
    thesis, subject, findings = await _load_findings(pool, thesis_id, profile)
    existing = ((await tstore.get(pool, thesis_id=thesis_id, trusted=True)) or {}).get("collective_take") or {}
    if not findings:
        # A transient 0-findings must never wipe a take that was built when findings existed.
        if _take_substantive(existing):
            return {"take": existing, "findings": 0}
        take_obj = _empty_take(take_secs)
        await tstore.set_collective_take(pool, thesis_id, take_obj)
        return {"take": take_obj, "findings": 0}
    n = len(findings)
    # Bound the input so synthesis stays reliable on deep runs — keep the most decision-relevant findings
    # within a size the model composes over cleanly, rather than feeding an unbounded set that times out.
    use_findings, truncated = _bound_findings(findings)

    async def _compose(llm):
        take = await compose_memo(llm, directive=take_dir, sections=list(take_secs),
                                  findings=use_findings, decision=thesis, answer_chars=_TAKE_ANSWER_CHARS)
        return {"bottom_line": take.get("bottom_line") or {"text": "", "markers": ""},
                "sections": take.get("sections") or [], "empty": False,
                "generated_at": int(time.time()), "findings": n,
                "synthesized_over": len(use_findings), "truncated": truncated}

    # Try the seams in order of quality, falling through on failure so ONE dead provider (e.g. OpenAI out
    # of credits) can't blank the take when another seam is live: reasoning → strong → default.
    seams: list = []
    for s in (take_llm, llm_json, default_llm):
        if s is not None and s not in seams:
            seams.append(s)
    take_obj, which = None, -1
    for i, s in enumerate(seams):
        take_obj = await _compose(s)
        if _take_substantive(take_obj):
            which = i
            break
    _log.info("synthesize_all: findings=%d used=%d truncated=%s seams=%d ok_via=%s",
              n, len(use_findings), truncated, len(seams), which)
    if which >= 0:
        await tstore.set_collective_take(pool, thesis_id, take_obj)
        return {"take": take_obj, "findings": n, "rebuilt": True}
    # Every seam failed. Attribute it to the real cause (out of credits, rate-limited, …) so the Brief can
    # SHOW why, never a silent blank. Keep a good existing take if there is one; else persist an error take.
    try:
        from .llm import LAST_LLM_ERROR
        reason = LAST_LLM_ERROR.get() or "The synthesis model was unavailable."
    except Exception:      # noqa: BLE001
        reason = "The synthesis model was unavailable."
    if _take_substantive(existing):
        return {"take": existing, "findings": n, "rebuilt": False,
                "error": "synthesis_unavailable", "error_detail": reason}
    err_take = _empty_take(take_secs)
    err_take.update({"error": "synthesis_unavailable", "error_detail": reason, "findings": n})
    await tstore.set_collective_take(pool, thesis_id, err_take)
    return {"take": err_take, "findings": n, "rebuilt": False,
            "error": "synthesis_unavailable", "error_detail": reason}


async def synthesize_deck(pool, thesis_id: str, profile, llm_json, reference: str = "",
                          references: list[dict] | None = None) -> dict:
    """Compose + persist the Startup Pitch Deck — a SEPARATE, on-demand artifact, generated after the
    Collective Take exists. A 10x-founder pitch: a throughline SPINE plus a headline-driven slide per
    section, built over the findings and informed (for narrative shape only) by the Collective Take.

    `reference` (optional): excerpts of similar PUBLIC VC theses / founder memos, given as STRUCTURE +
    NARRATIVE exemplars — how a strong pitch in this space reads. It is NOT a citation source and its
    specifics are never borrowed; the deck still argues ONLY from the findings.
    `references` (optional): the same memos as structured [{title,url,source,snippet}] cards, ridden
    along with the deck as "similar theses to check out" for the reader (links out, not cited).
    -> {"deck": {...}, "findings": <n>}."""
    deck_dir, spine, deck_secs = profile.pitch_deck_spec()
    refs = [r for r in (references or []) if isinstance(r, dict) and r.get("url")]
    thesis, _subject, findings = await _load_findings(pool, thesis_id, profile)
    d = await tstore.get(pool, thesis_id=thesis_id, trusted=True)
    existing = (d or {}).get("pitch_deck") or {}
    if not findings:
        # A transient 0-findings must never wipe a deck that was built when findings existed.
        if _deck_substantive(existing):
            return {"deck": existing, "findings": 0}
        deck_obj = _empty_deck(deck_secs)
        deck_obj["references"] = refs
        await tstore.set_pitch_deck(pool, thesis_id, deck_obj)
        return {"deck": deck_obj, "findings": 0}
    context = _take_context((d or {}).get("collective_take") or {})
    if reference.strip():
        context = ((context + "\n\n") if context else "") + (
            "HOW STRONG PUBLIC PITCHES / VC THESES IN THIS SPACE READ (structure + narrative EXEMPLARS only "
            "— NEVER a source, never borrow their specifics or numbers; your deck argues ONLY from the "
            "findings above and cites them by F-number):\n" + reference.strip())
    deck = await compose_deck(llm_json, directive=deck_dir, spine_intent=spine, sections=list(deck_secs),
                              findings=findings, decision=thesis, context=context)
    # A blank compose (LLM hiccup, malformed JSON, or every unit dropped by the citation gate) must not
    # clobber a good deck — otherwise a flaky rebuild makes the deck "disappear" until you regenerate.
    if not _deck_substantive(deck) and _deck_substantive(existing):
        return {"deck": existing, "findings": len(findings)}
    deck_obj = {"spine": deck.get("spine") or {}, "sections": deck.get("sections") or [],
                "references": refs, "empty": False, "generated_at": int(time.time()),
                "findings": len(findings)}
    await tstore.set_pitch_deck(pool, thesis_id, deck_obj)
    return {"deck": deck_obj, "findings": len(findings)}
