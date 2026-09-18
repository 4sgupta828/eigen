"""Voices organization — cluster the candidate first-person pieces (podcasts / talks / blogs / essays
retrieved from the Voices corpus) by HOW they bear on this thesis's investigation, and prune the ones
that are only loosely on-topic. The retrieval + per-piece AI summary reuse the Voices mode's own
endpoints; this module adds the one LLM pass that makes the list "super relevant" and organizes it.

Voices are a SIGNAL, not evidence — the directive (the vertical's) keeps that framing; here we only run
the model and gate its output. Never raises into the request path.
"""
from __future__ import annotations

import json
import re

_WS = re.compile(r"\s+")


def _clip(s, n: int) -> str:
    return _WS.sub(" ", str(s or "")).strip()[:n]


def thesis_context(doc: dict, questions: list[dict], *, cap: int = 2200) -> str:
    """A compact read of the thesis + what the investigation cares about, so the model can judge how a
    piece bears on it. Lean by design — the candidate snippets carry the rest."""
    doc = doc or {}
    parts = [f"THESIS: {_clip(doc.get('thesis'), 400)}"]
    subject = " ".join(str(v) for v in (doc.get("subject") or {}).values()).strip()
    if subject:
        parts.append("SUBJECT: " + _clip(subject, 200))
    take = doc.get("collective_take") or {}
    bl = _clip((take.get("bottom_line") or {}).get("text"), 300)
    if bl:
        parts.append("HOW IT LEANS: " + bl)
    # The live angles of investigation — the lines of inquiry the voices should be organized against.
    lines = []
    seen = set()
    for q in (questions or []):
        nm = _clip(q.get("inquiry_name"), 70)
        if nm and nm.lower() not in seen:
            seen.add(nm.lower())
            lines.append(nm)
    if lines:
        parts.append("LINES OF INVESTIGATION: " + "; ".join(lines[:10]))
    return "\n".join(parts)[:cap].strip()


def _candidate_block(candidates: list[dict]) -> str:
    rows = []
    for i, c in enumerate(candidates):
        who = " · ".join(filter(None, [_clip(c.get("speaker"), 50), _clip(c.get("show"), 50)]))
        rows.append(f"[{i}] ({_clip(c.get('kind'), 16)}) {_clip(c.get('title'), 140)}"
                    + (f" — {who}" if who else "")
                    + (f": {_clip(c.get('snippet'), 220)}" if c.get("snippet") else ""))
    return "\n".join(rows)


async def organize_voices(llm_json, *, directive: str, context: str, candidates: list[dict],
                          max_buckets: int = 6) -> dict:
    """Cluster candidates into relevance-to-the-investigation buckets, dropping the off-topic ones.
    Returns {"buckets": [{"label", "items": [{"id", "why"}]}]}. Never raises; on failure returns an
    empty result so the caller can fall back to the flat list."""
    cands = [c for c in (candidates or []) if isinstance(c, dict) and c.get("id")][:30]
    empty = {"buckets": []}
    if llm_json is None or not cands:
        return empty
    user = (
        context + "\n\n"
        + "CANDIDATE PIECES (index in brackets):\n" + _candidate_block(cands) + "\n\n"
        + "Keep only the pieces that genuinely bear on THIS thesis; organize the kept ones into buckets "
          "by how they bear on the investigation. EMIT JSON:\n"
          '{"buckets": [{"label": "<how these bear on it>", '
          '"items": [{"i": <candidate index>, "why": "<one line: how this piece bears on the thesis>"}]}]}\n'
          "Drop an off-topic piece by simply not listing it. Output ONLY the JSON.")
    try:
        raw = await llm_json(directive, user)
        d = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception:      # noqa: BLE001
        return empty
    if not isinstance(d, dict):
        return empty
    buckets, used = [], set()
    for b in (d.get("buckets") or []):
        if not isinstance(b, dict):
            continue
        label = _clip(b.get("label"), 80)
        items = []
        for it in (b.get("items") or []):
            if not isinstance(it, dict):
                continue
            try:
                idx = int(it.get("i"))
            except Exception:      # noqa: BLE001
                continue
            if idx < 0 or idx >= len(cands) or idx in used:
                continue
            used.add(idx)
            items.append({"id": cands[idx]["id"], "why": _clip(it.get("why"), 200)})
            if len(items) >= 12:
                break
        if label and items:
            buckets.append({"label": label, "items": items})
        if len(buckets) >= max_buckets:
            break
    return {"buckets": buckets}
