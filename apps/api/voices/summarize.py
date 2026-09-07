"""Summarise one essay or episode for the expanded card — written once, then stored.

Two paths, and the card always says which one it got.

**Model.** When a JSON-capable model is configured and has credit, it writes 3-5 points about what
the piece actually argues. Lazy: nothing is summarised until a reader opens that card, so spend
follows attention rather than corpus size. Cached by document, so a second reader pays nothing.

**Extractive.** When no model is available — both accounts are empty as of 2026-09-07 — the same
panel is filled by picking the most informative sentences out of the piece itself. It is a weaker
summary and the card says so. That is much better than an empty panel or a spinner that never
resolves, and it keeps the feature honest about what produced the words.

A chapter-pointer document needs no model at all: its "summary" is the publisher's own chapter list,
which is already a summary of the episode. Nothing there is a quotation, so nothing is invented.
"""
from __future__ import annotations

import re

MAX_INPUT_CHARS = 12000        # one call, bounded: ~3k tokens in, a few hundred out
MAX_POINTS = 5

SYSTEM = (
    "You summarise first-person writing by startup founders, investors and operators for an "
    "investor's reading list. Return STRICT JSON: {\"heading\": str, \"points\": [str]}.\n"
    "RULES:\n"
    "- 3 to 5 points. Each is ONE sentence, under 25 words, stating something the piece actually "
    "argues or reports. No preamble, no 'the author discusses'.\n"
    "- Prefer the specific over the general: a number, a mechanism, a named mistake, a concrete "
    "recommendation. Drop anything you could have written without reading the piece.\n"
    "- Never invent a fact, a figure or an outcome that is not in the text. If the piece is thin, "
    "return fewer points rather than padding.\n"
    "- The heading is 2 to 5 words naming the subject, not a sentence.\n"
    "- This is one person's opinion and experience. Summarise what THEY claim; do not endorse it "
    "and do not add your own judgment."
)

_FIG = re.compile(r"\$?\d[\d,.]*\s*(?:%|percent|k|m|bn|b|x|million|billion)?", re.I)


def verify(points: list[str], text: str) -> list[str]:
    """Drop a point the piece does not support. A code-owned gate, not a request in the prompt.

    The failure this prevents is the one that matters in this genre: a summary that invents a figure.
    Every number a point asserts must appear in the source text, normalised for separators, or the
    point goes. A point with no figures passes — prose paraphrase is the model's job — but a
    fabricated "$40M" or "3x" cannot survive.
    """
    def figs(s: str) -> set[str]:
        out = set()
        for m in _FIG.finditer(s or ""):
            raw = m.group(0).strip().lower().replace(",", "").replace("$", "").rstrip(".")
            digits = re.sub(r"[^0-9.]", "", raw)
            if digits and any(c.isdigit() for c in digits):
                out.add(digits.rstrip("."))
        return out

    src = figs(text)
    kept = []
    for p in points:
        if figs(p) - src:            # a number the source never states
            continue
        kept.append(p.strip()[:220])
    return kept


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'“])")
_STOP = {"the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with", "at", "by",
         "from", "is", "are", "was", "were", "be", "been", "it", "its", "this", "that", "these",
         "those", "as", "we", "i", "you", "they", "he", "she", "our", "their", "my", "your", "have",
         "has", "had", "do", "does", "did", "not", "so", "if", "then", "than", "there", "what",
         "which", "who", "when", "where", "how", "will", "would", "can", "could", "should", "about"}


def sentences(text: str) -> list[str]:
    out = []
    for s in _SENT.split(" ".join((text or "").split())):
        s = s.strip()
        if 40 <= len(s) <= 320:
            out.append(s)
    return out


def extractive_points(text: str, k: int = MAX_POINTS) -> list[str]:
    """The most informative sentences, in the order the piece makes them.

    Scored by the frequency of the content words they carry, normalised by length so a long
    sentence does not win merely for being long, with a small bonus for a sentence containing a
    figure — in this genre the sentence with the number is usually the sentence with the point.
    """
    sents = sentences(text)
    if not sents:
        return []
    freq: dict[str, int] = {}
    for s in sents:
        for w in re.findall(r"[a-z][a-z'-]+", s.lower()):
            if w not in _STOP and len(w) > 2:
                freq[w] = freq.get(w, 0) + 1
    scored = []
    for i, s in enumerate(sents):
        words = [w for w in re.findall(r"[a-z][a-z'-]+", s.lower()) if w not in _STOP and len(w) > 2]
        if not words:
            continue
        score = sum(freq.get(w, 0) for w in words) / (len(words) ** 0.6)
        if re.search(r"\d", s):
            score *= 1.15
        scored.append((score, i, s))
    scored.sort(reverse=True)
    picked = sorted(scored[:k], key=lambda t: t[1])
    return [s for _score, _i, s in picked]


def chapter_points(text: str, k: int = MAX_POINTS) -> list[str]:
    """For an episode, the publisher's own chapter titles — longest first, since a one-word chapter
    ("Intro") says nothing. Returned as the list they are, never as speech."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip().startswith("[")]
    titles = []
    for ln in lines:
        m = re.match(r"^\[\d{2}:\d{2}:\d{2}\]\s*(.+?)(?:\s+—\s+https?://\S+)?$", ln)
        if m:
            t = m.group(1).strip().rstrip(" -–—")
            if len(t) >= 8:
                titles.append(t)
    return sorted(titles, key=len, reverse=True)[:k]


def user_payload(title: str, author: str, text: str) -> str:
    body = (text or "")[:MAX_INPUT_CHARS]
    who = f"By {author}. " if author else ""
    return f"{who}Title: {title}\n\n{body}"


async def summarize(*, title: str, author: str, text: str, is_chapter: bool, llm_json=None) -> dict:
    """Return {heading, points, note, basis}. Never raises: a summary is a convenience, and a card
    that fails to summarise must still show the piece."""
    if is_chapter:
        return {"heading": "What the episode covers", "points": chapter_points(text),
                "note": "The publisher's own chapter list. Nothing here is a quotation.",
                "basis": "chapters"}
    if llm_json is not None:
        try:
            out = await llm_json(SYSTEM, user_payload(title, author, text))
            raw = [str(p).strip() for p in (out.get("points") or []) if str(p).strip()][:MAX_POINTS]
            pts = verify(raw, text)          # a figure the piece never states is not a summary
            if pts:
                return {"heading": str(out.get("heading") or "What it says")[:80], "points": pts,
                        "note": f"Summarised from the full piece{', by ' + author if author else ''}.",
                        "basis": "model"}
        except Exception as e:      # noqa: BLE001 — an outage degrades the panel, never breaks it
            note = f"No model available ({type(e).__name__}), so these are the piece's own sentences."
            return {"heading": "Key passages", "points": extractive_points(text), "note": note,
                    "basis": "extractive"}
    return {"heading": "Key passages", "points": extractive_points(text),
            "note": "Selected from the piece's own sentences — no model was available to summarise it.",
            "basis": "extractive"}


# ── cache ────────────────────────────────────────────────────────────────────────────────────────
DDL = """
CREATE TABLE IF NOT EXISTS vo_summary (
    document_id text PRIMARY KEY,
    heading     text NOT NULL DEFAULT '',
    points      jsonb NOT NULL DEFAULT '[]'::jsonb,
    note        text NOT NULL DEFAULT '',
    basis       text NOT NULL DEFAULT '',
    made_at     timestamptz NOT NULL DEFAULT now());
"""

# An essay does not change, so the summary of one does not either. The TTL exists only so that an
# EXTRACTIVE summary written during a model outage is re-attempted later, when credit exists — a
# model summary is kept far longer because re-buying it would be paying twice for the same words.
TTL_DAYS = {"model": 365, "chapters": 365, "extractive": 3}


async def cached(conn, document_id: str) -> dict | None:
    """The stored summary, or None when there is none or it has aged out of its basis's window."""
    import json
    await conn.execute(DDL)
    r = await conn.fetchrow(
        "SELECT heading, points, note, basis, EXTRACT(EPOCH FROM (now() - made_at)) / 86400.0 AS age "
        "FROM vo_summary WHERE document_id = $1", document_id)
    if not r:
        return None
    if float(r["age"] or 0) > TTL_DAYS.get(r["basis"], 7):
        return None
    pts = json.loads(r["points"]) if isinstance(r["points"], str) else (r["points"] or [])
    return {"heading": r["heading"], "points": pts, "note": r["note"], "basis": r["basis"]}


async def store(conn, document_id: str, summary: dict) -> None:
    """Never cache an empty read: a summary with no points is a failure, not a result."""
    if not (summary.get("points") or []):
        return
    import json
    await conn.execute(DDL)
    await conn.execute(
        "INSERT INTO vo_summary (document_id, heading, points, note, basis, made_at) "
        "VALUES ($1,$2,$3::jsonb,$4,$5, now()) ON CONFLICT (document_id) DO UPDATE "
        "SET heading=EXCLUDED.heading, points=EXCLUDED.points, note=EXCLUDED.note, "
        "    basis=EXCLUDED.basis, made_at=now()",
        document_id, summary.get("heading", "")[:120], json.dumps(summary.get("points") or []),
        summary.get("note", "")[:200], summary.get("basis", "")[:20])
