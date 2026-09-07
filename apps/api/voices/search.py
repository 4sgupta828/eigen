"""Search first-person content and shape it as MOMENTS. Pure functions plus one SQL builder.

A moment is what the user actually wants back: who said or wrote it, on what, when, and a link that
opens at the exact place. Two kinds reach the surface and they are not equal:

  essay    — the person's own words. Evidence of what they argue.
  chapter  — a publisher's timestamped marker. A POINTER: where to listen, never what was said.

The distinction is carried in the data (`source_kind`), not in a prompt, and `is_quotable` is the
single place that decides whether a moment may ever be shown inside quotation marks.

Keyword-first by design: `rs_block.tsv` is a generated column, so this works with no embedding
provider at all. Semantic ranking is added when vectors exist, never required for the mode to run.
"""
from __future__ import annotations

import re

VOICE_SOURCE_KEYS = ("founder_essay", "show_notes", "expert_feed", "podcast")

# "[00:13:00] Is Series A the hardest stage — https://show.fm/ep?t=780"
_CHAPTER_LINE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s*(.+?)(?:\s+—\s+(https?://\S+))?$")


def is_quotable(source_kind: str) -> bool:
    """False for a chapter pointer. A producer's chapter title is not speech, so quoting it would
    manufacture a statement nobody made. Everything else may be quoted with attribution."""
    return (source_kind or "").lower() != "chapter_pointer"


def kind_of(source_kind: str, source_key: str) -> str:
    sk = (source_kind or "").lower()
    if sk == "chapter_pointer" or source_key == "show_notes":
        return "chapter"
    if source_key == "podcast":
        return "transcript"
    return "essay"


def seconds_of(stamp: str) -> int:
    try:
        h, m, s = (int(p) for p in stamp.split(":"))
    except ValueError:
        return 0
    return h * 3600 + m * 60 + s


def moment(row: dict) -> dict:
    """One `rs_block` row → a card. Never invents a link, a speaker or a timestamp."""
    facets = row.get("facets") or {}
    text = (row.get("text") or "").strip()
    source_kind = str(facets.get("source_kind") or "")
    kind = kind_of(source_kind, str(row.get("source_key") or ""))

    t_start, url, body = 0, str(facets.get("episode_url") or ""), text
    if kind == "chapter":
        m = _CHAPTER_LINE.match(text)
        if m:
            t_start = seconds_of(m.group(1))
            body = m.group(2).strip()
            url = m.group(3) or url
    if kind != "chapter":
        # the passage that matched, when the query produced one; else the block's opening
        body = (row.get("snippet") or body or "").strip() or body
    speaker = str(facets.get("guest") or facets.get("author") or "")
    return {
        "id": f"{row.get('document_id')}::{row.get('block_id')}",
        "kind": kind,
        "quotable": is_quotable(source_kind),
        "text": body,
        "title": str(row.get("document_title") or ""),
        "show": str(facets.get("publication") or ""),
        "speaker": speaker,
        "role": str(facets.get("voice_role") or ("guest" if kind == "chapter" else "")),
        "published": str(facets.get("published") or facets.get("year") or ""),
        "url": url,
        "t_start": t_start,
        "company_id": str(facets.get("company_id") or ""),
        # The register the UI must print. A pointer is never presented as something anyone said.
        "register": ("Chapter marker written by the publisher — listen from this point"
                     if kind == "chapter" else "First-person account, attributed to its author"),
    }


def build_query(*, q: str, kinds: tuple[str, ...] = (), company_id: str = "", speaker: str = "",
                limit: int = 30, table: str = "rs_block") -> tuple[str, list]:
    """Keyword search over the voice corpus. Returns (sql, params) — no I/O, so it is testable.

    An empty `q` is legitimate ("show me what founders are saying"): it degrades to the newest rows
    rather than to an error, because a mode that returns nothing when the box is empty reads broken.
    """
    where = ["source_key = ANY($1)"]
    params: list = [list(VOICE_SOURCE_KEYS)]
    n = 1

    if kinds:
        keys = []
        if "chapter" in kinds:
            keys.append("show_notes")
        if "essay" in kinds:
            keys += ["founder_essay", "expert_feed"]
        if "transcript" in kinds:
            keys.append("podcast")
        params[0] = keys or list(VOICE_SOURCE_KEYS)
    if company_id:
        n += 1
        where.append(f"facets->>'company_id' = ${n}")
        params.append(company_id)
    if speaker:
        n += 1
        where.append(f"(facets->>'guest' ILIKE ${n} OR facets->>'author' ILIKE ${n})")
        params.append(speaker)

    if q.strip():
        n += 1
        where.append(f"tsv @@ plainto_tsquery('english', ${n})")
        params.append(q.strip())
        rank = f"ts_rank(tsv, plainto_tsquery('english', ${n}))"
        order = f"{rank} DESC, created_at DESC NULLS LAST"
        # An essay block can be thousands of characters, so the head of it is rarely the part that
        # answered the question. ts_headline returns the passage that actually matched.
        snippet = (f"ts_headline('english', text, plainto_tsquery('english', ${n}), "
                   f"'MaxWords=48, MinWords=20, ShortWord=3, MaxFragments=1, StartSel=\u00ab, StopSel=\u00bb')")
    else:
        rank = "0.0"
        order = "created_at DESC NULLS LAST"
        snippet = "left(text, 320)"

    n += 1
    params.append(int(max(1, min(limit, 100))))
    sql = (f"SELECT document_id, block_id, text, document_title, source_key, facets, "
           f"{rank} AS score, {snippet} AS snippet "
           f"FROM {table} WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ${n}")
    return sql, params
