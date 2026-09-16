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

import time

from eigen_kernel.decision import compose_over_findings, compose_memo, compose_matrix

from . import store as tstore


def _empty_deck(sections) -> dict:
    return {"sections": [{"key": s["key"], "title": s["title"], "prose": ""} for s in sections],
            "empty": True, "generated_at": 0}


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
                         "status": q.get("target_status") or ""})
    return thesis, subject, findings


async def synthesize_all(pool, thesis_id: str, profile, llm_json, take_llm_json=None) -> dict:
    """Compose + persist the Pitch Deck, Collective Take, and Competitive Analysis for a thesis. Returns
    {"deck": {...}, "take": {...}, "competitive": {...}, "findings": <n>}. With no findings yet, persists
    empty artifacts so the UI shows an honest 'run a line of inquiry first', never stale content.

    `take_llm_json`: the deep-thinking (reasoning) seam for the Collective Take; falls back to `llm_json`
    when not supplied. The take alone reasons second-order across every finding, so it gets the stronger
    reasoner; the deck + matrix stay on the faster seam."""
    take_llm = take_llm_json or llm_json
    deck_dir, deck_secs = profile.pitch_deck_spec()
    take_dir, take_secs = profile.collective_take_spec()
    thesis, subject, findings = await _load_findings(pool, thesis_id, profile)
    # The COMPETITIVE landscape is NO LONGER built here: it is its own gated, web-researched artifact
    # (apps/api/thesis/competitive.py via POST /competitive/research), so re-synthesis never overwrites a
    # researched landscape with an empty passive matrix. synthesize_all owns only the deck + take.
    if not findings:
        deck_obj, take_obj = _empty_deck(deck_secs), _empty_take(take_secs)
        await tstore.set_pitch_deck(pool, thesis_id, deck_obj)
        await tstore.set_collective_take(pool, thesis_id, take_obj)
        return {"deck": deck_obj, "take": take_obj, "findings": 0}

    deck = await compose_over_findings(llm_json, directive=deck_dir, sections=list(deck_secs),
                                       findings=findings, decision=thesis, layout="bullets")
    take = await compose_memo(take_llm, directive=take_dir, sections=list(take_secs),
                              findings=findings, decision=thesis, answer_chars=2400)
    now = int(time.time())
    n = len(findings)
    deck_obj = {"sections": deck, "empty": False, "generated_at": now, "findings": n}
    take_obj = {"bottom_line": take.get("bottom_line") or {"text": "", "markers": ""},
                "sections": take.get("sections") or [], "empty": False, "generated_at": now, "findings": n}
    await tstore.set_pitch_deck(pool, thesis_id, deck_obj)
    await tstore.set_collective_take(pool, thesis_id, take_obj)
    return {"deck": deck_obj, "take": take_obj, "findings": n}
