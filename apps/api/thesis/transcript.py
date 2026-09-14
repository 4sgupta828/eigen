"""Turn an expert-call transcript into gated, typed `call` evidence — the close-the-loop step.

A transcript is FIRST-PERSON testimony, not a third-party artifact, so it gets its own path (the corpus
gates assume filings/blogs/papers). It runs long (8-10k words), so we chunk it; and a model asked to
"quote" will paraphrase, so every extracted point must survive a VERBATIM-span gate — its quote has to
appear in the transcript character-for-character (whitespace-normalized), else it is dropped. The
transcript is the source; a hallucinated quote is not evidence.

Verdict semantics live in `call_status` and are deliberately conservative (panel review 2026-09-13):
one account is never a settle; a call is never `controlling`; TWO INDEPENDENT accounts (distinct person
AND firm) one way are needed to move a call_only aspect to supported/contradicted.
"""
from __future__ import annotations

import json
import re

MAX_POINTS = 12
CHUNK_WORDS = 2200

_SYSTEM = """You extract what an expert said on a diligence call that bears on ONE aspect of a startup
thesis. Return ONLY points the speaker actually asserted about THIS thesis's subject — not about peers
or the industry in general, and not your own inference. Keep "what our customers do" separate from "what
I would personally pay". For each point:
- "quote": a VERBATIM span copied exactly from the transcript (character-for-character; do NOT paraphrase).
- "point": one sentence of what it asserts about the aspect.
- "relation": "supports" if it supports the aspect, "contradicts" if it argues against it.
Only include points that clearly bear on the aspect. Output ONLY a JSON object."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


async def extract_call_points(llm_json, *, transcript: str, aspect_prompt: str, thesis: str,
                              subject: str = "") -> list[dict]:
    """-> [{quote, point, relation}]. Never raises; [] when there is no model or nothing gated survives.
    Each quote is verified to be a verbatim span of the transcript before it is kept."""
    if llm_json is None or not (transcript or "").strip():
        return []
    words = transcript.split()
    chunks = [" ".join(words[i:i + CHUNK_WORDS]) for i in range(0, len(words), CHUNK_WORDS)] or [transcript]
    hay = _norm(transcript)
    out: list[dict] = []
    seen: set = set()
    for chunk in chunks:
        user = (f"THESIS: {thesis}\nSUBJECT: {subject}\nASPECT: {aspect_prompt}\n\n"
                f"TRANSCRIPT:\n{chunk}\n\n"
                'Return {"points": [{"quote": "...", "point": "...", '
                '"relation": "supports|contradicts"}]}.')
        try:
            raw = await llm_json(_SYSTEM, user)
            d = raw if isinstance(raw, dict) else json.loads(raw)
            pts = d.get("points") or []
        except Exception:      # noqa: BLE001 — extraction never blocks; a bad chunk contributes nothing
            pts = []
        for p in pts:
            quote = str((p or {}).get("quote") or "").strip()
            rel = "contradicts" if str((p or {}).get("relation")) == "contradicts" else "supports"
            if not quote or _norm(quote) not in hay:        # VERBATIM-span gate — the quote must be real
                continue
            k = _norm(quote)[:120]
            if k in seen:
                continue
            seen.add(k)
            out.append({"quote": quote[:600], "point": str((p or {}).get("point") or "").strip()[:300],
                        "relation": rel})
            if len(out) >= MAX_POINTS:
                return out
    return out


_INSIGHTS_SYSTEM = """You extract what an expert said on a diligence call that bears on a LINE OF INQUIRY
in a startup thesis. Return ONLY points the speaker actually asserted about THIS thesis's subject — not
about peers or the industry in general, and not your own inference. For each point:
- "quote": a VERBATIM span copied exactly from the transcript (character-for-character; do NOT paraphrase).
- "insight": one sentence of what it means for the thesis.
- "stance": "validates" if it supports the thesis / this line of inquiry, "invalidates" if it argues
  against it, "context" if it is relevant background that does neither.
- "refers_to": the exact text of the question (from the list given) it bears on most, or "" if none.
Only include points that clearly bear on this line of inquiry. Output ONLY a JSON object."""

_STANCES = ("validates", "invalidates", "context")


async def extract_insights(llm_json, *, transcript: str, inquiry_name: str, framing: str,
                           questions: list[str], thesis: str, subject: str = "") -> list[dict]:
    """-> [{quote, insight, stance, refers_to}] for a LINE OF INQUIRY. Same verbatim-span gate as
    extract_call_points (a quote must appear character-for-character in the transcript) — an expert's
    words, not a paraphrase. Stance maps each point to validates|invalidates|context for the thesis.
    Never raises; [] when there is no model or nothing gated survives."""
    if llm_json is None or not (transcript or "").strip():
        return []
    words = transcript.split()
    chunks = [" ".join(words[i:i + CHUNK_WORDS]) for i in range(0, len(words), CHUNK_WORDS)] or [transcript]
    hay = _norm(transcript)
    qlist = "\n".join(f"- {q}" for q in (questions or []) if q) or "- (no specific questions)"
    out: list[dict] = []
    seen: set = set()
    for chunk in chunks:
        user = (f"THESIS: {thesis}\nSUBJECT: {subject}\nLINE OF INQUIRY: {inquiry_name}\n"
                f"WHAT IT TESTS: {framing}\nQUESTIONS IN THIS LINE:\n{qlist}\n\n"
                f"TRANSCRIPT:\n{chunk}\n\n"
                'Return {"points": [{"quote": "...", "insight": "...", '
                '"stance": "validates|invalidates|context", "refers_to": "..."}]}.')
        try:
            raw = await llm_json(_INSIGHTS_SYSTEM, user)
            d = raw if isinstance(raw, dict) else json.loads(raw)
            pts = d.get("points") or []
        except Exception:      # noqa: BLE001 — extraction never blocks; a bad chunk contributes nothing
            pts = []
        for p in pts:
            quote = str((p or {}).get("quote") or "").strip()
            stance = str((p or {}).get("stance") or "").strip().lower()
            if stance not in _STANCES:
                stance = "context"
            if not quote or _norm(quote) not in hay:        # VERBATIM-span gate — the quote must be real
                continue
            k = _norm(quote)[:120]
            if k in seen:
                continue
            seen.add(k)
            out.append({"quote": quote[:600], "insight": str((p or {}).get("insight") or "").strip()[:300],
                        "stance": stance, "refers_to": str((p or {}).get("refers_to") or "").strip()[:300]})
            if len(out) >= MAX_POINTS:
                return out
    return out


def insight_tally(insights: list[dict]) -> dict:
    """Count validates/invalidates/context across a line's insights — a quick read of which way the
    expert calls point, WITHOUT ever letting them settle the line (expert opinion is 'stated', not
    controlling; the corpus/web evidence run still owns the verdict)."""
    t = {s: 0 for s in _STANCES}
    for i in insights or []:
        s = str((i or {}).get("stance") or "context").lower()
        t[s if s in t else "context"] += 1
    return t


def call_status(call_rows: list[dict]) -> tuple[str, str]:
    """(verdict, note) for a call_only aspect from its `call` evidence. Independence keyed per person AND
    firm — three employees of one buyer are ONE account. One account is `primary_research_needed`; a
    call is never controlling; >=2 independent accounts one way move it to supported/contradicted."""
    def acct(r):
        # Independence is per ACCOUNT: distinct FIRM (so three people at one buyer are ONE account);
        # fall back to the person only when the firm is unknown.
        return _norm(r.get("source_subject") or "") or ("person:" + _norm(r.get("said_by") or ""))
    calls = [r for r in (call_rows or []) if (r.get("source_key") == "call") and r.get("said_by")]
    for_accts = {acct(r) for r in calls if r.get("relation") == "supports"}
    against_accts = {acct(r) for r in calls if r.get("relation") == "contradicts"}
    n_for, n_against = len(for_accts), len(against_accts)
    if not calls:
        return "unsettleable", "No document can settle this — it needs a person."
    if n_against >= 2 and n_for < 2:
        return "contradicted", f"{n_against} independent accounts argue against this."
    if n_for >= 2 and n_against < 2:
        return "supported", f"{n_for} independent accounts support this — first-hand, not filed."
    if n_for and n_against:
        return "open", "Accounts conflict — weigh them; neither side has two independent voices yet."
    return "primary_research_needed", "One account so far; seek an independent second (different firm)."
